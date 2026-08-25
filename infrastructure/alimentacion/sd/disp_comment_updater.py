"""Actualizador offline de comentarios por instancia en Source Documents.

Modifica un par de archivos ``.s7dcl`` + ``.s7res`` exportados por
TIA Portal para escribir el comentario de cada instancia de un array
de UDTs en un DB de dispositivo. Replica el patrón OFFLINE de
``infrastructure/sd/modifiers.py`` (sin imports de
``siemens_tia_scripting``, solo ``pathlib``, ``re``, ``dataclasses``).

Convención de archivos
----------------------
``<db_name>.s7dcl`` contiene (resumido)::

    DATA_BLOCK DB<N>_<HW>
        VAR
            "<ARRAY>" : Array[0.._.N_MAX_...] of _.UDT_...
        END_VAR
        ...
        { S7_MLC := "MLC_abc" }
        "<ARRAY>"[i] := ();
        ...
    END_DATA_BLOCK

``<db_name>.s7res`` contiene::

    MultiLingualTexts:
      - id: MLC_abc
        es-ES: <texto>
      ...

El cruce entre ambos es el ID ``MLC_abc``: aparece en el bloque
``S7_MLC := "..."`` del ``.s7dcl`` y como ``id:`` en el ``.s7res``.

Uso típico
----------
::

    updater = DispCommentUpdater(
        s7dcl_path=Path("DB2000_ED.s7dcl"),
        s7res_path=Path("DB2000_ED.s7res"),
        slot_map={0: "NO USAR", 1: "Bomba 1", 2: "Bomba 2"},
        db_array_name="ED",
    )
    result = updater.update()
    updater.save(s7dcl_path, s7res_path)
    if updater.was_modified():
        ...
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from infrastructure.alimentacion.sd.disp_mlc_registry import DispMLCRegistry


_logger: logging.Logger = logging.getLogger(f"{__name__}.DispCommentUpdater")

# Tamaño máximo permitido para un comentario (límite práctico S7_MLC).
# Truncamos silenciosamente con warning si se supera.
_MAX_COMMENT_LEN: int = 254

# Texto que se escribe cuando ``plc_comentario`` está vacío.
_EMPTY_TEXT: str = "."

# Texto fijo para el slot 0 (siempre "NO USAR" según decisión de diseño).
_NO_USAR_TEXT: str = "NO USAR"


# ── Resultado del update ────────────────────────────────────────────────


@dataclass(frozen=True)
class DispCommentResult:
    """Resumen de la actualización.

    Attributes:
        reused:   ``{slot: mlc_id}`` para slots cuyo MLC ya existía.
        inserted: ``{slot: mlc_id}`` para slots con MLC nuevo generado.
        no_usar_mlc: MLC del slot 0 (respetado si ya existía; creado si no).
        total_mlcs_in_res: número de entradas MultiLingualTexts en el
                           ``.s7res`` resultante (post-update).
    """

    reused: dict[int, str]
    inserted: dict[int, str]
    no_usar_mlc: str
    total_mlcs_in_res: int


# ── Codificación ────────────────────────────────────────────────────────

_S7DCL_ENCODING: str = "utf-8"          # sin BOM
_S7RES_ENCODING: str = "utf-8-sig"      # con BOM (lo genera TIA al exportar)


# ── Regex de parsing ────────────────────────────────────────────────────

# Detecta una asignación `<ARRAY>[i] := ();` (con posibles espacios).
_ASSIGNMENT_RE = re.compile(
    r"""(?xm)
    ^(?P<indent>\s*)
    (?P<lhs>"?(?P<array>[A-Za-z_][A-Za-z0-9_]*)"?\s*\[(?P<idx>\d+)\])\s*:=\s*\(\s*\)\s*;
    \s*$
    """
)

# Detecta un bloque `{ ... S7_MLC := "MLC_xxx" ... }` (single-line o multi-línea).
# Acepta tanto `{ S7_MLC := "..." }` (todo en una línea) como
# `{\n    S7_MLC := "..."\n}` (bloque expandido).
_MLC_BLOCK_RE = re.compile(
    r"""(?xm)
    ^(?P<indent>\s*)\{(?P<body>[^}]*)\}\s*$
    """
)

# Captura el `S7_MLC := "MLC_xxx"` dentro del cuerpo de un bloque.
# El ``;`` final es opcional: en formato compacto ``{ S7_MLC := "..." }``
# el ``;`` está después del ``}`` que cierra el bloque (no dentro).
_MLC_INNER_RE = re.compile(
    r"""S7_MLC\s*:=\s*"(?P<mlc>[A-Za-z_][A-Za-z0-9_]*)"\s*;?"""
)


# ── Entry point ─────────────────────────────────────────────────────────


class DispCommentUpdater:
    """Actualiza los comentarios por instancia de un DB de dispositivo.

    Attributes:
        s7dcl_path: ruta al archivo ``.s7dcl``.
        s7res_path: ruta al archivo ``.s7res``.
        slot_map: ``{slot: texto}`` con ``slot_map[0] == "NO USAR"``.
        db_array_name: nombre del array dentro del DB (p. ej. ``"ED"``).
                       Se obtiene del config (``db_array_name``), nunca
                       hardcoded.

    Raises:
        ValueError: si ``slot_map[0] != "NO USAR"`` o ``db_array_name`` vacío.
        FileNotFoundError: si los archivos no existen.
    """

    def __init__(
        self,
        s7dcl_path: str | Path,
        s7res_path: str | Path,
        slot_map: dict[int, str],
        db_array_name: str,
    ) -> None:
        self._s7dcl_path = Path(s7dcl_path)
        self._s7res_path = Path(s7res_path)

        if not self._s7dcl_path.is_file():
            raise FileNotFoundError(f"No se encontró .s7dcl: '{self._s7dcl_path}'")
        if not self._s7res_path.is_file():
            raise FileNotFoundError(f"No se encontró .s7res: '{self._s7res_path}'")

        if not db_array_name or not db_array_name.strip():
            raise ValueError("db_array_name es obligatorio y no puede estar vacío.")
        self._db_array_name = db_array_name.strip()

        if 0 not in slot_map or slot_map[0] != _NO_USAR_TEXT:
            raise ValueError(
                f"slot_map[0] debe ser {_NO_USAR_TEXT!r} (got {slot_map.get(0)!r})."
            )
        self._slot_map: dict[int, str] = dict(slot_map)

        # Carga en memoria.
        self._s7dcl: str = self._s7dcl_path.read_text(encoding=_S7DCL_ENCODING)
        self._s7res: str = self._s7res_path.read_text(encoding=_S7RES_ENCODING)

        # Estado mutable.
        self._modified: bool = False
        self._registry: DispMLCRegistry = self._build_registry()
        self._result: DispCommentResult | None = None

    # ── API pública ────────────────────────────────────────────────────

    def update(self) -> DispCommentResult:
        """Orquesta la actualización. Retorna ``DispCommentResult``.

        Algoritmo (ver docstring del plan):
          1. Para cada i in slot_map: localizar MLC existente o crear uno.
          2. Slot 0: siempre debe tener MLC (respetar o crear).
          3. Reescribir ``.s7res`` (alta/baja de entradas).
          4. Devolver resultado.
        """
        reused: dict[int, str] = {}
        inserted: dict[int, str] = {}

        # 1) Para cada slot del map, asegurar asignación + MLC.
        for slot, raw_text in self._slot_map.items():
            text = self._sanitize_comment_text(raw_text, slot)
            existing_mlc = self._find_assignment_mlc(slot)
            if existing_mlc is not None:
                # MLC ya estaba en el .s7dcl; lo respetamos.
                self._registry.reserve([existing_mlc])
                reused[slot] = existing_mlc
                # Si el .s7res perdió esta entrada, la restauramos con el texto.
                self._upsert_s7res_entry(existing_mlc, text)
            else:
                # Crear MLC nuevo.
                new_mlc = self._registry.next_mlc_id()
                self._inject_mlc_block_or_assignment(slot, new_mlc)
                self._upsert_s7res_entry(new_mlc, text)
                inserted[slot] = new_mlc

        # 2) Slot 0 — siempre debe tener MLC. Si no lo tiene, crearlo.
        # (El bucle anterior ya lo garantiza porque slot_map[0] está en slot_map;
        # pero defendámonos por si slot_map se construye sin 0.)
        no_usar_mlc = reused.get(0) or inserted.get(0) or self._ensure_slot0_mlc()

        # 3) Eliminar MLCs huérfanos del .s7res (los que ya no se referencian).
        # IMPORTANTE: ``referenced`` debe incluir TODOS los MLCs del .s7dcl,
        # no solo los de los slots. TIA exige que el ``count`` de MLCs en el
        # .s7dcl coincida EXACTAMENTE con el del .s7res. Si omitimos los
        # MLCs de cabecera (``S7_BlockComment``, ``S7_BlockTitle``,
        # ``S7_MLC`` en declaraciones de array), ``_prune_s7res`` los borra
        # del .s7res y el reimport falla con
        # "Mlc ids present in resource file does not match the count
        #  of Mlc ids present in source file".
        referenced = (
            set(reused.values())
            | set(inserted.values())
            | {no_usar_mlc}
            | self._extract_all_mlcs_from_s7dcl()
        )

        # 3.bis) Si el .s7dcl referencia MLCs que el .s7res no tiene
        # (caso típico: la exportación de TIA omite los MLCs de cabecera
        # como ``MLC_block_cmt``, ``MLC_arr_cmt``), los añadimos al
        # .s7res con texto ``"."`` (convención TIA "sin comentario").
        # TIA los regenera o los respeta; en cualquier caso, el balance
        # .s7dcl/.s7res se mantiene y el reimport funciona.
        existing_in_res = self._extract_existing_mlcs()
        for mlc_id in referenced:
            if mlc_id not in existing_in_res:
                self._upsert_s7res_entry(mlc_id, ".")

        self._prune_s7res(referenced)

        # 4) Resultado.
        total_mlcs = self._count_s7res_entries()
        self._result = DispCommentResult(
            reused=reused,
            inserted=inserted,
            no_usar_mlc=no_usar_mlc,
            total_mlcs_in_res=total_mlcs,
        )
        return self._result

    def was_modified(self) -> bool:
        return self._modified

    def save(
        self,
        output_s7dcl_path: str | Path | None = None,
        output_s7res_path: str | Path | None = None,
    ) -> None:
        """Escribe los archivos (in-place si no se pasan rutas de salida)."""
        out_dcl = Path(output_s7dcl_path) if output_s7dcl_path else self._s7dcl_path
        out_res = Path(output_s7res_path) if output_s7res_path else self._s7res_path
        out_dcl.parent.mkdir(parents=True, exist_ok=True)
        out_res.parent.mkdir(parents=True, exist_ok=True)
        out_dcl.write_text(self._s7dcl, encoding=_S7DCL_ENCODING)
        out_res.write_text(self._s7res, encoding=_S7RES_ENCODING)

    # ── Internals: registry ─────────────────────────────────────────────

    def _build_registry(self) -> DispMLCRegistry:
        """Inicializa el registry con todos los MLCs presentes en el ``.s7res``."""
        existing = self._extract_existing_mlcs()
        return DispMLCRegistry(used_ids=existing)

    def _extract_existing_mlcs(self) -> set[str]:
        """Lee el ``.s7res`` y devuelve el set de IDs ``MLC_*`` presentes."""
        return set(re.findall(r"^\s*-\s*id:\s*(MLC_\S+)\s*$", self._s7res, re.MULTILINE))

    def _extract_all_mlcs_from_s7dcl(self) -> set[str]:
        """Extrae TODOS los MLCs referenciados en el ``.s7dcl``.

        Tres formatos soportados (todos producen una referencia MLC que
        TIA cuenta y que DEBE tener su entrada en el .s7res):

        1. **Cabecera del bloque**:
           ``S7_BlockComment := "MLC_32c"``,
           ``S7_BlockTitle := "MLC_wT"``.

        2. **Bloque de declaración de variable/array**:
           ``{ S7_MLC := "MLC_3Vz" }`` antes de
           ``"ED" : Array[...] of _.UDT_...``.

        3. **Bloque adyacente a asignación de instancia**:
           ``{ S7_MLC := "MLC_3vw" }`` antes de ``ED[i] := ();``.

        Si omitimos cualquiera de estos formatos del conjunto de
        ``referenced`` que se pasa a ``_prune_s7res``, el updater borra
        las entradas correspondientes del .s7res y el reimport en TIA
        falla con "Mlc ids present in resource file does not match
        the count of Mlc ids present in source file".
        """
        return set(
            re.findall(
                r'S7_(?:BlockComment|BlockTitle|MLC)\s*:=\s*"(MLC_[A-Za-z0-9_]+)"',
                self._s7dcl,
            )
        )

    # ── Internals: .s7dcl ───────────────────────────────────────────────

    def _find_assignment_mlc(self, slot: int) -> str | None:
        """Busca ``<ARRAY>[slot] := ();`` y devuelve su MLC asociado (si existe).

        El MLC asociado es el bloque ``{ S7_MLC := "..." }`` que aparece
        INMEDIATAMENTE antes de la asignación, sin otra asignación
        ``<ARRAY>[<otro>]:=();`` del mismo array en medio. Esto es
        importante porque el formato TIA puede tener varios bloques
        ``S7_MLC`` consecutivos (uno por slot) y cada uno va con su slot.

        Devuelve ``None`` si la asignación no existe o si existe pero sin MLC.
        """
        match = self._find_assignment(slot)
        if match is None:
            return None
        assign_start = match.start()
        # Encontrar la asignación previa del mismo array (si existe) para
        # delimitar el rango de búsqueda. Si no hay previa, empezamos
        # desde el inicio.
        prev_assign_end = 0
        for prev in _ASSIGNMENT_RE.finditer(self._s7dcl[:assign_start]):
            if prev.group("array") == self._db_array_name:
                prev_assign_end = prev.end()
        # Buscar el ÚLTIMO bloque S7_MLC en el rango [prev_assign_end, assign_start).
        search_range = self._s7dcl[prev_assign_end:assign_start]
        last_mlc: str | None = None
        for blk in _MLC_BLOCK_RE.finditer(search_range):
            inner = _MLC_INNER_RE.search(blk.group("body"))
            if inner:
                last_mlc = inner.group("mlc")
        return last_mlc

    def _find_assignment(self, slot: int) -> re.Match[str] | None:
        """Localiza la asignación ``<ARRAY>[slot] := ();`` en el .s7dcl."""
        for m in _ASSIGNMENT_RE.finditer(self._s7dcl):
            array = m.group("array")
            idx = int(m.group("idx"))
            if array == self._db_array_name and idx == slot:
                return m
        return None

    def _inject_mlc_block_or_assignment(self, slot: int, mlc_id: str) -> None:
        """Inserta la asignación y/o su bloque S7_MLC.

        - Si existe ``<ARRAY>[slot] := ();`` sin bloque MLC → añade el bloque antes.
        - Si no existe la asignación → añade bloque + asignación al final del bloque
          de inicialización (última asignación del array). Si no hay inicialización,
          la añade justo antes de ``END_DATA_BLOCK``.
        """
        match = self._find_assignment(slot)
        if match is not None:
            # Existe la asignación. ¿Tiene MLC? Si no, añadir el bloque.
            existing = self._find_assignment_mlc(slot)
            if existing is None:
                # Insertar bloque antes de la asignación, con la indentación
                # que tenga la asignación.
                indent = match.group("indent")
                block = f"{indent}{{\n{indent}    S7_MLC := \"{mlc_id}\";\n{indent}}}\n"
                self._upsert_s7dcl_block(match, block)
            return

        # No existe la asignación. Insertar bloque + asignación.
        # Estrategia: añadir al final del bloque de inicialización, justo
        # antes de ``END_DATA_BLOCK``. Si no aparece ``END_DATA_BLOCK``,
        # añadir al final del archivo.
        new_block = (
            f'        {{ S7_MLC := "{mlc_id}"; }}\n'
            f'        "{self._db_array_name}"[{slot}] := ();\n'
        )
        marker = "END_DATA_BLOCK"
        idx = self._s7dcl.rfind(marker)
        if idx < 0:
            # Sin END_DATA_BLOCK → añadir al final.
            self._s7dcl = self._s7dcl.rstrip() + "\n\n" + new_block
        else:
            self._s7dcl = self._s7dcl[:idx] + new_block + self._s7dcl[idx:]
        self._modified = True

    def _upsert_s7dcl_block(self, match: re.Match[str], block: str) -> None:
        """Inserta un bloque MLC justo antes de ``match``. Marca modified solo si cambia."""
        before = self._s7dcl
        self._s7dcl = (
            self._s7dcl[: match.start()] + block + self._s7dcl[match.start() :]
        )
        if self._s7dcl != before:
            self._modified = True

    def _ensure_slot0_mlc(self) -> str:
        """Asegura que ``<ARRAY>[0] := ();`` existe con un MLC. Devuelve el MLC.

        Usado como red de seguridad si slot_map no incluye 0 (no debería pasar,
        pero defendámonos).
        """
        existing = self._find_assignment_mlc(0)
        if existing is not None:
            self._registry.reserve([existing])
            return existing
        new_mlc = self._registry.next_mlc_id()
        self._inject_mlc_block_or_assignment(0, new_mlc)
        self._upsert_s7res_entry(new_mlc, _NO_USAR_TEXT)
        return new_mlc

    # ── Internals: .s7res ───────────────────────────────────────────────

    def _upsert_s7res_entry(self, mlc_id: str, text: str) -> None:
        """Inserta o actualiza una entrada ``- id: <mlc_id> / es-ES: <text>``.

        Si la entrada existe, reemplaza su texto ``es-ES``. Si no, la añade
        al bloque ``MultiLingualTexts`` (o lo crea si no existe).
        """
        text = self._escape_s7res_text(text)
        before = self._s7res

        # Buscar entrada existente.
        pattern = re.compile(
            rf"(?xm)^(?P<indent>\s*-\s*id:\s*{re.escape(mlc_id)}\s*\n)"
            rf"(?P<inner>(?:\s+[^\n]*\n)*?)"
            rf"(?=\s*-\s*id:|\s*MultiLingualTexts:|\Z)"
        )
        m = pattern.search(self._s7res)
        if m is not None:
            # Reemplazar SOLO el es-ES de esta entrada.
            new_inner = re.sub(
                r"es-ES:\s*[^\n]*",
                f"es-ES: {text}",
                m.group("inner"),
                count=1,
            )
            self._s7res = (
                self._s7res[: m.start("inner")]
                + new_inner
                + self._s7res[m.end("inner") :]
            )
        else:
            # No existe → añadir al final de MultiLingualTexts.
            new_entry = f"  - id: {mlc_id}\n    es-ES: {text}\n"
            # Si MultiLingualTexts existe y tiene entradas, añadir antes de la
            # siguiente línea que no sea parte de la lista (o al final del bloque).
            list_start = re.search(
                r"(?m)^MultiLingualTexts:\s*$", self._s7res
            )
            if list_start is None:
                # No hay bloque MultiLingualTexts; crearlo al principio.
                self._s7res = "MultiLingualTexts:\n" + new_entry + self._s7res
            else:
                # Buscar el final de la lista YAML (línea no indentada o fin).
                insert_pos = self._find_s7res_append_pos()
                self._s7res = self._s7res[:insert_pos] + new_entry + self._s7res[insert_pos:]

        if self._s7res != before:
            self._modified = True

    def _find_s7res_append_pos(self) -> int:
        """Encuentra la posición donde añadir una nueva entrada MultiLingualTexts.

        Estrategia: encontrar el final de la última entrada YAML de la
        lista (línea ``- id: MLC_xxx`` o ``es-ES: ...`` indentada), y
        devolver el offset justo después de esa línea (incluyendo el
        ``\n`` final).
        """
        # Cualquier línea indentada que parezca de la lista.
        # Acepta 2 o 4 espacios (o más) de indentación, indistintamente.
        last_entry_end = 0
        for m in re.finditer(
            r"(?m)^[ \t]+(?:-\s*id:\s*|es-ES:\s*)[^\n]*\n",
            self._s7res,
        ):
            end = m.end()
            if end > last_entry_end:
                last_entry_end = end
        if last_entry_end == 0:
            # Lista vacía o no indentada como esperamos; insertar tras "MultiLingualTexts:".
            m = re.search(r"(?m)^MultiLingualTexts:[^\n]*\n", self._s7res)
            if m is None:
                return 0
            return m.end()
        return last_entry_end

    def _prune_s7res(self, keep_mlcs: set[str]) -> None:
        """Elimina del ``.s7res`` las entradas MLC que no estén en ``keep_mlcs``.

        Conserva siempre las entradas que coincidan con MLCs referenciados.
        """
        # Patrón: bloque completo de una entrada ``- id: ...\n    es-ES: ...``.
        entry_re = re.compile(
            r"(?xm)^[ \t]*-\s*id:\s*(?P<mlc>\S+)\s*\n"
            r"(?:[ \t]+[^\n]*\n)*?"
            r"(?=\s*-\s*id:|\s*MultiLingualTexts:|\Z)"
        )
        removed = 0

        def _repl(m: re.Match[str]) -> str:
            nonlocal removed
            if m.group("mlc") in keep_mlcs:
                return m.group(0)
            removed += 1
            return ""

        new = entry_re.sub(_repl, self._s7res)
        if removed:
            self._s7res = new
            self._modified = True
            _logger.debug(
                f"DispCommentUpdater: {removed} entradas MLC huérfanas eliminadas."
            )

    def _count_s7res_entries(self) -> int:
        return len(re.findall(r"(?m)^\s*-\s*id:\s*MLC_\S+", self._s7res))

    # ── Internals: sanitización ─────────────────────────────────────────

    @staticmethod
    def _sanitize_comment_text(text: str, slot: int) -> str:
        """Limpia el texto del comentario: trim, colapsa saltos, escapa, trunca."""
        if text is None:
            text = ""
        # Trim de espacios extremos.
        s = text.strip()
        # Colapsar saltos de línea a espacio.
        s = re.sub(r"\s+", " ", s)
        # Vacío → ".".
        if not s:
            s = _EMPTY_TEXT
        # Truncar si excede el máximo.
        if len(s) > _MAX_COMMENT_LEN:
            _logger.warning(
                f"Comentario del slot {slot} truncado de {len(s)} a "
                f"{_MAX_COMMENT_LEN} chars."
            )
            s = s[:_MAX_COMMENT_LEN]
        return s

    @staticmethod
    def _escape_s7res_text(text: str) -> str:
        """Escapa el texto para YAML: comillas dobles como ``""``."""
        # En YAML, dentro de un escalar plano, las comillas dobles se duplican.
        return text.replace('"', '""')

    @staticmethod
    def _escape_s7dcl_text(text: str) -> str:
        """Escapa el texto para SCL: comillas dobles como ``\\\"``."""
        return text.replace('"', '\\"')


__all__ = ["DispCommentResult", "DispCommentUpdater"]
