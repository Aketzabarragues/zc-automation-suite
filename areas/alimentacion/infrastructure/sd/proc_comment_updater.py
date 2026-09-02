"""Actualizador offline de comentarios por instancia para DBs de procesos.

Modifica un par de archivos ``.s7dcl`` + ``.s7res`` exportados por
TIA Portal para escribir el comentario de cada slot de los arrays
``PReal[]``, ``PInt[]`` y ``ALM[]`` de un DB de proceso. Es el
hermano "procesos" del ``DispCommentUpdater`` (que cubre los 6 DBs
de dispositivos ED/EA/SA/V/M/M_VF).

Diferencias respecto a ``DispCommentUpdater``
--------------------------------------------
* **Sin slot 0 fijo.** Los arrays de procesos empiezan en ``1``
  (``Array[1..N_MAX_...]``). El slot 0 NO existe en el DB y por
  tanto NO se incluye en el ``slot_map``. Si por error llega un
  ``slot_map`` con slot 0, se acepta pero se ignora.
* **Sin slot 0 "NO USAR" obligatorio.** No hay texto fijo a
  inyectar; cada slot del Excel se mapea directamente.
* **Arrays parametrizados.** En lugar de un único ``db_array_name``
  fijo, el updater recibe ``array_name`` (p. ej. ``"PReal"``) que
  es el nombre del array principal. Los arrays satélite
  (``PReal_Vis``, ``Aux.PReal_ValorAnterior``, etc.) se pasan como
  set en ``satellite_arrays``.
* **Propagación a satélites.** Cuando se actualiza el slot ``N`` del
  array principal, el updater busca en el ``.s7dcl`` la asignación
  del mismo slot en cada array satélite (si existe) y actualiza su
  ``es-ES`` con el mismo texto. Cada satélite tiene su propio MLC
  (distinto del principal), pero el texto debe ser idéntico porque
  son "copias" del comentario.
* **No crea asignaciones nuevas en satélites.** Si el satélite no
  tiene slot ``N`` (caso: N_MAX demasiado bajo), el updater lo
  salta silenciosamente. Crear nuevos slots en satélites sería un
  cambio de cardinalidad, fuera de scope.

Convención de archivos
----------------------
Idéntica a ``DispCommentUpdater`` (ver su docstring para
detalles). Resumido:

``<db_name>.s7dcl`` contiene::

    DATA_BLOCK DB<N>_<PROC>_PARAM
        ...
        { S7_MLC := "MLC_abc" }
        "PReal" : Array[1.._."50100_N_MAX_PREAL"] of _.UDT_ZC_PREAL;
        ...
        { S7_MLC := "MLC_def" }
        PReal[1] := ();
        ...
        { S7_MLC := "MLC_ghi" }
        PReal_Vis[1] := FALSE;
        ...
        { S7_MLC := "MLC_jkl" }
        Aux.PReal_ValorAnterior[1] := ();
    END_DATA_BLOCK

``<db_name>.s7res`` contiene::

    MultiLingualTexts:
      - id: MLC_abc
        es-ES: <texto>
      ...

El cruce entre ambos es el ID ``MLC_xxx``.

Uso típico
----------

::

    updater = ProcesoCommentUpdater(
        s7dcl_path=Path("DB53100_CPR_PARAM.s7dcl"),
        s7res_path=Path("DB53100_CPR_PARAM.s7res"),
        slot_map={1: "Bomba 1", 2: "Bomba 2", 3: "Bomba 3"},
        array_name="PReal",
        satellite_arrays={"PReal_Vis", "Aux.PReal_ValorAnterior"},
        registry=MLCRegistry(),
    )
    result = updater.update()
    updater.save()
    if updater.was_modified():
        ...  # importar el bloque a TIA

Restricción arquitectónica (``.clinerules`` §1): este módulo es
OFFLINE; no importa ``siemens_tia_scripting``. Solo ``pathlib``,
``re``, ``dataclasses``, ``logging``.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from areas.alimentacion.infrastructure.sd.mlc_registry import MLCRegistry


_logger: logging.Logger = logging.getLogger(f"{__name__}.ProcesoCommentUpdater")

# Tamaño máximo permitido para un comentario (límite práctico S7_MLC).
_MAX_COMMENT_LEN: int = 254

# Texto que se escribe cuando ``comentario`` está vacío.
_EMPTY_TEXT: str = "."


# ── Resultado del update ────────────────────────────────────────────────


@dataclass(frozen=True)
class ProcesoCommentResult:
    """Resumen de la actualización de un bloque de proceso.

    Attributes:
        reused: ``{slot: mlc_id}`` para slots cuyo MLC ya existía
                (en el array principal, no en los satélites).
        inserted: ``{slot: mlc_id}`` para slots con MLC nuevo
                generado (en el array principal).
        satellite_reused: ``{slot: mlc_id}`` para MLCs de satélites
                que ya existían y se actualizaron.
        satellite_inserted: ``{slot: mlc_id}`` para MLCs de satélites
                nuevos generados.
        total_mlcs_in_res: número de entradas MultiLingualTexts en
                el ``.s7res`` resultante (post-update).
    """

    reused: dict[int, str]
    inserted: dict[int, str]
    satellite_reused: dict[int, str]  # slot → mlc_id (uno por satélite)
    satellite_inserted: dict[int, str]
    total_mlcs_in_res: int


# ── Codificación ────────────────────────────────────────────────────────

_S7DCL_ENCODING: str = "utf-8"          # sin BOM
_S7RES_ENCODING: str = "utf-8-sig"      # con BOM (lo genera TIA al exportar)


# ── Regex de parsing ────────────────────────────────────────────────────

# Detecta una asignación `<ARRAY>[i] := <RHS>;` (con posibles espacios).
# Soporta nombres de array **anidados con punto** (p. ej.
# ``Aux.PReal_ValorAnterior[5] := ();``). El grupo ``array`` captura
# el nombre completo incluyendo los segmentos ``A.B.C`` que TIA
# utiliza para anidar arrays dentro de STRUCTs (e.g. ``Aux``).
#
# El RHS puede ser:
#   - Una tupla/registro vacío: ``();``  (UDTs)
#   - Un literal escalar: ``FALSE;``, ``0;``, ``0.0;``  (arrays de
#     escalares como Bool, Int, Real que TIA no envuelve en parens).
#   - Una expresión cualquiera no-vacía que termina en ``;``.
_ASSIGNMENT_RE = re.compile(
    r"""(?xm)
    ^(?P<indent>\s*)
    (?P<lhs>"?(?P<array>(?:[A-Za-z_][A-Za-z0-9_]*\.)*[A-Za-z_][A-Za-z0-9_]*)"?\s*\[(?P<idx>\d+)\])
    \s*:=\s*(?:\([^)]*\)|[^;]+)\s*;
    \s*$
    """
)

# Detecta un bloque `{ ... S7_MLC := "MLC_xxx" ... }` (single-line o multi-línea).
_MLC_BLOCK_RE = re.compile(
    r"""(?xm)
    ^(?P<indent>\s*)\{(?P<body>[^}]*)\}\s*$
    """
)

# Captura el `S7_MLC := "MLC_xxx"` dentro del cuerpo de un bloque.
_MLC_INNER_RE = re.compile(
    r"""S7_MLC\s*:=\s*"(?P<mlc>[A-Za-z_][A-Za-z0-9_]*)"\s*;?"""
)


# ── Entry point ─────────────────────────────────────────────────────────


class ProcesoCommentUpdater:
    """Actualiza los comentarios por instancia de un DB de proceso.

    Attributes:
        s7dcl_path: ruta al archivo ``.s7dcl``.
        s7res_path: ruta al archivo ``.s7res``.
        slot_map: ``{slot: texto}`` 1-based. Slots que no están
                  en el map se dejan intactos (comentario histórico
                  del operario conservado).
        array_name: nombre del array principal en el DB
                  (p. ej. ``"PReal"``, ``"PInt"``, ``"ALM"``).
        satellite_arrays: set de nombres de arrays satélite del
                  mismo proceso (p. ej. ``{"PReal_Vis",
                  "Aux.PReal_ValorAnterior"}``). Para cada slot
                  actualizado en el array principal, el updater
                  propaga el texto a los MLCs de los satélites del
                  mismo índice (si existen en el ``.s7dcl``).
        registry: ``MLCRegistry`` con los MLCs ya presentes en el
                  ``.s7res`` reservados.

    Raises:
        ValueError: si ``update()`` se llama con ``array_name`` vacío
                    (es obligatorio en modo escritura; no en modo
                    lectura vía ``read_current_comments``).
        FileNotFoundError: si los archivos no existen.
    """

    def __init__(
        self,
        s7dcl_path: str | Path,
        s7res_path: str | Path,
        slot_map: dict[int, str],
        array_name: str = "",
        satellite_arrays: set[str] | None = None,
        registry: MLCRegistry | None = None,
    ) -> None:
        self._s7dcl_path = Path(s7dcl_path)
        self._s7res_path = Path(s7res_path)

        if not self._s7dcl_path.is_file():
            raise FileNotFoundError(f"No se encontró .s7dcl: '{self._s7dcl_path}'")
        if not self._s7res_path.is_file():
            raise FileNotFoundError(f"No se encontró .s7res: '{self._s7res_path}'")

        # ``array_name`` es opcional en construcción: solo es obligatorio
        # cuando se llama a ``update()`` (modo escritura). ``read_current_comments``
        # recibe el nombre del array por parámetro en cada llamada, así que
        # un updater de solo-lectura (p. ej. usado en el preview de
        # procesos) puede construirse con ``array_name=""``.
        self._array_name: str = (array_name or "").strip()

        # Filtrar el slot 0 (no aplica a procesos). Si está, se ignora
        # silenciosamente con warning (defensivo: podría venir de un
        # caller que reutiliza código de dispositivos).
        filtered = {
            int(k): v for k, v in slot_map.items() if int(k) >= 1
        }
        if 0 in slot_map:
            _logger.warning(
                f"ProcesoCommentUpdater: slot_map contiene slot 0, "
                f"se ignora (los arrays de procesos empiezan en 1)."
            )
        self._slot_map: dict[int, str] = filtered

        self._satellite_arrays: set[str] = set(satellite_arrays or ())

        # Carga en memoria.
        self._s7dcl: str = self._s7dcl_path.read_text(encoding=_S7DCL_ENCODING)
        self._s7res: str = self._s7res_path.read_text(encoding=_S7RES_ENCODING)

        # Estado mutable.
        self._modified: bool = False
        # Inicializa el registry con los MLCs ya presentes en el
        # .s7res (para que next_mlc_id no colisione con ellos).
        if registry is None:
            existing = self._extract_existing_mlcs()
            self._registry: MLCRegistry = MLCRegistry(used_ids=existing)
        else:
            # Si nos pasan uno ya poblado, lo usamos tal cual
            # (reservando también los existentes del .s7res por si
            # el caller olvidó hacerlo).
            registry.reserve(self._extract_existing_mlcs())
            self._registry = registry
        self._result: ProcesoCommentResult | None = None

    # ── API pública ────────────────────────────────────────────────────

    def update(self) -> ProcesoCommentResult:
        """Orquesta la actualización. Retorna ``ProcesoCommentResult``.

        Algoritmo:
          1. Para cada slot del slot_map, localizar el MLC existente
             del array principal o generar uno nuevo.
          2. Para cada slot actualizado, propagar el texto a los
             MLCs de los satélites del mismo índice.
          3. Restaurar MLCs huérfanos referenciados por el .s7dcl.
          4. Equilibrar el .s7res (conservar solo MLCs referenciados).
        """
        if not self._array_name:
            raise ValueError(
                "array_name es obligatorio para update() (no para "
                "read_current_comments)."
            )
        reused: dict[int, str] = {}
        inserted: dict[int, str] = {}
        satellite_reused: dict[int, str] = {}
        satellite_inserted: dict[int, str] = {}

        # 1) Para cada slot del map, asegurar asignación + MLC.
        for slot, raw_text in self._slot_map.items():
            text = _sanitize_comment_text(raw_text, slot)
            existing_mlc = self._find_assignment_mlc(self._array_name, slot)
            if existing_mlc is not None:
                # MLC ya estaba en el .s7dcl; lo respetamos.
                self._registry.reserve([existing_mlc])
                reused[slot] = existing_mlc
                # Si el .s7res perdió esta entrada, la restauramos.
                self._upsert_s7res_entry(existing_mlc, text)
            else:
                # Crear MLC nuevo y asignación.
                new_mlc = self._registry.next_mlc_id()
                self._inject_mlc_block_or_assignment(
                    self._array_name, slot, new_mlc
                )
                self._upsert_s7res_entry(new_mlc, text)
                inserted[slot] = new_mlc

            # 2) Propagación a satélites del mismo slot.
            for sat_array in self._satellite_arrays:
                sat_mlc = self._find_assignment_mlc(sat_array, slot)
                if sat_mlc is None:
                    # El satélite no tiene este slot en el .s7dcl
                    # (caso N_MAX limitado o array no presente).
                    # No creamos asignaciones nuevas para satélites
                    # (eso es cambio de cardinalidad, fuera de scope).
                    continue
                # El satélite ya tenía MLC: lo actualizamos.
                self._registry.reserve([sat_mlc])
                self._upsert_s7res_entry(sat_mlc, text)
                satellite_reused[slot] = sat_mlc

        # 3) Calcular el conjunto de MLCs referenciados por el .s7dcl
        # (cabecera + array principal + todos los satélites) para
        # equilibrar el .s7res. TIA exige que el nº de MLCs en
        # .s7dcl coincida EXACTAMENTE con el del .s7res.
        referenced: set[str] = (
            set(reused.values())
            | set(inserted.values())
            | set(satellite_reused.values())
            | self._extract_all_mlcs_from_s7dcl()
        )

        # 3.bis) Si el .s7dcl referencia MLCs que el .s7res no tiene
        # (caso típico: la exportación de TIA omite los MLCs de
        # cabecera), los añadimos con texto "." (convención TIA).
        existing_in_res = self._extract_existing_mlcs()
        for mlc_id in referenced:
            if mlc_id not in existing_in_res:
                self._upsert_s7res_entry(mlc_id, ".")

        # 4) Podar el .s7res.
        self._prune_s7res(referenced)

        total_mlcs = self._count_s7res_entries()
        self._result = ProcesoCommentResult(
            reused=reused,
            inserted=inserted,
            satellite_reused=satellite_reused,
            satellite_inserted=satellite_inserted,
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
        """Escribe los archivos (in-place si no se pasan rutas)."""
        out_dcl = Path(output_s7dcl_path) if output_s7dcl_path else self._s7dcl_path
        out_res = Path(output_s7res_path) if output_s7res_path else self._s7res_path
        out_dcl.parent.mkdir(parents=True, exist_ok=True)
        out_res.parent.mkdir(parents=True, exist_ok=True)
        out_dcl.write_text(self._s7dcl, encoding=_S7DCL_ENCODING)
        out_res.write_text(self._s7res, encoding=_S7RES_ENCODING)

    # ── Internals: registry ─────────────────────────────────────────────

    def _extract_existing_mlcs(self) -> set[str]:
        """Lee el ``.s7res`` y devuelve el set de IDs ``MLC_*`` presentes."""
        return set(re.findall(r"^\s*-\s*id:\s*(MLC_\S+)\s*$", self._s7res, re.MULTILINE))

    def _build_mlc_text_map(self) -> dict[str, str]:
        """Devuelve ``{MLC_id: es-ES_text}`` con todas las entradas
        del ``.s7res``.

        Cada entrada es un bloque YAML como::

            - id: MLC_xxx
              es-ES: <texto>

        Esta función es la inversa de ``_upsert_s7res_entry`` y se
        usa para leer el estado actual de TIA (sin modificar nada)
        durante la fase de preview / diff.

        Nota sobre comillas envolventes:
          TIA Portal exporta algunos comentarios entre comillas
          literales en el ``.s7res`` (caso típico: texto con
          espacios al final, comillas internas, o caracteres que
          YAML considera "no seguros"). Por ejemplo, un comentario
          ``COMPACTO - FIJOS - `` (con espacio al final) se
          exporta como ``es-ES: 'COMPACTO - FIJOS - '``. Si el
          parser las preservara, el operario vería comillas
          literales en la UI del diff. Las quitamos
          conservadoramente solo si el texto capturado empieza Y
          termina con la MISMA comilla (simples o dobles); un texto
          que legitimamente contiene una sola comilla al inicio o
          al final se queda tal cual.
        """
        result: dict[str, str] = {}
        # Regex: cada entrada es un bloque ``- id: MLC_X\n    es-ES: ...``.
        # El grupo ``inner`` captura las líneas indentadas que siguen
        # al ``- id:`` hasta el siguiente ``- id:`` o fin de bloque.
        pattern = re.compile(
            r"(?xm)^(?P<indent>\s*-\s*id:\s*(?P<mlc>\S+)\s*\n)"
            r"(?P<inner>(?:\s+[^\n]*\n)*?)"
            r"(?=\s*-\s*id:|\s*MultiLingualTexts:|\Z)"
        )
        for m in pattern.finditer(self._s7res):
            mlc_id = m.group("mlc")
            inner = m.group("inner")
            es_match = re.search(r"es-ES:\s*([^\n]*)", inner)
            if es_match is None:
                # MLC sin es-ES (raro pero posible si TIA exportó
                # un comentario vacío). Lo guardamos como string vacío
                # para que el caller lo distinga de "no existe".
                result[mlc_id] = ""
            else:
                raw = es_match.group(1)
                result[mlc_id] = strip_enclosing_quotes(raw)
        return result

    def read_current_comments(
        self, slot_indices: "list[int] | tuple[int, ...]", array_name: str
    ) -> "dict[int, str | None]":
        """Lee el ``es-ES`` actual de los slots dados del array.

        Esta función es la inversa de ``update()`` en modo lectura:
        no modifica ningún archivo, solo consulta el ``.s7res`` y
        devuelve el texto actual para cada slot.

        Args:
            slot_indices: Lista de slots 1-based cuyo ``es-ES`` se
                quiere leer.
            array_name: Nombre del array principal en el DB
                (``"PReal"``, ``"PInt"``, ``"ALM"``). Las entradas del
                array principal son las que se exponen al operario
                en la vista de diff; los satélites son "copias" del
                mismo texto y NO entran en la comparación (se
                propagan automáticamente al aplicar cambios, ver
                ``update()``).

        Returns:
            ``{slot: es-ES_text}`` o ``{slot: None}`` si el slot no
            existe en el ``.s7dcl`` o no tiene MLC adyacente.
            ``es-ES_text`` puede ser ``""`` si el MLC existe pero
            tiene el texto vacío en el ``.s7res`` (caso TIA "sin
            comentario").

        Notas:
            No falla si el archivo no existe: en ese caso, devuelve
            ``{slot: None}`` para todos. El caller decide si abortar
            o marcar la vista como "sin datos de TIA".
        """
        # Si el .s7res no existe (p. ej. el export falló), devolvemos
        # None para todos los slots.
        if not self._s7res_path.is_file():
            return {slot: None for slot in slot_indices}
        mlc_to_text = self._build_mlc_text_map()
        result: dict[int, str | None] = {}
        for slot in slot_indices:
            mlc = self._find_assignment_mlc(array_name, slot)
            if mlc is None:
                result[slot] = None
            else:
                # Si el MLC existe en el .s7dcl pero no en el .s7res,
                # devolvemos string vacío (caso TIA degenerado; el
                # updater lo trataría como "." en la próxima
                # aplicación).
                result[slot] = mlc_to_text.get(mlc, "")
        return result

    def _extract_all_mlcs_from_s7dcl(self) -> set[str]:
        """Extrae TODOS los MLCs referenciados en el ``.s7dcl``.

        Tres formatos soportados (todos producen una referencia MLC
        que TIA cuenta y que DEBE tener su entrada en el .s7res):

        1. **Cabecera del bloque**:
           ``S7_BlockComment := "MLC_32c"``,
           ``S7_BlockTitle := "MLC_wT"``.
        2. **Bloque de declaración de variable/array**:
           ``{ S7_MLC := "MLC_3Vz" }`` antes de
           ``"ED" : Array[...] of _.UDT_...``.
        3. **Bloque adyacente a asignación de instancia**:
           ``{ S7_MLC := "MLC_3vw" }`` antes de ``ED[i] := ();``.

        Si omitimos cualquiera de estos formatos del conjunto de
        ``referenced`` que se pasa a ``_prune_s7res``, el updater
        borra las entradas correspondientes del .s7res y el reimport
        en TIA falla.
        """
        return set(
            re.findall(
                r'S7_(?:BlockComment|BlockTitle|MLC)\s*:=\s*"(MLC_[A-Za-z0-9_]+)"',
                self._s7dcl,
            )
        )

    # ── Internals: .s7dcl ───────────────────────────────────────────────

    def _find_assignment_mlc(self, array_name: str, slot: int) -> str | None:
        """Busca ``<ARRAY>[slot] := ...;`` y devuelve su MLC adyacente.

        El MLC asociado es el bloque ``{ S7_MLC := "..." }`` que
        aparece INMEDIATAMENTE antes de la asignación, sin otra
        asignación ``<ARRAY>[<otro>]:=...;`` del mismo array en
        medio. Esto es importante porque el formato TIA puede tener
        varios bloques ``S7_MLC`` consecutivos (uno por slot) y cada
        uno va con su slot.

        Devuelve ``None`` si la asignación no existe o si existe
        pero sin MLC adyacente.
        """
        match = self._find_assignment(array_name, slot)
        if match is None:
            return None
        assign_start = match.start()
        # Encontrar la asignación previa del mismo array para delimitar
        # el rango de búsqueda.
        prev_assign_end = 0
        for prev in _ASSIGNMENT_RE.finditer(self._s7dcl[:assign_start]):
            if prev.group("array") == array_name:
                prev_assign_end = prev.end()
        search_range = self._s7dcl[prev_assign_end:assign_start]
        last_mlc: str | None = None
        for blk in _MLC_BLOCK_RE.finditer(search_range):
            inner = _MLC_INNER_RE.search(blk.group("body"))
            if inner:
                last_mlc = inner.group("mlc")
        return last_mlc

    def _find_assignment(
        self, array_name: str, slot: int
    ) -> re.Match[str] | None:
        """Localiza la asignación ``<ARRAY>[slot] := ...;`` en el .s7dcl."""
        for m in _ASSIGNMENT_RE.finditer(self._s7dcl):
            array = m.group("array")
            idx = int(m.group("idx"))
            if array == array_name and idx == slot:
                return m
        return None

    def _inject_mlc_block_or_assignment(
        self, array_name: str, slot: int, mlc_id: str
    ) -> None:
        """Inserta la asignación y/o su bloque S7_MLC.

        - Si existe ``<ARRAY>[slot] := ...;`` sin bloque MLC → añade
          el bloque antes.
        - Si no existe la asignación → añade bloque + asignación al
          final del bloque de inicialización (última asignación del
          array). Si no aparece ``END_DATA_BLOCK``, añade al final
          del archivo.
        """
        match = self._find_assignment(array_name, slot)
        if match is not None:
            # Existe la asignación. ¿Tiene MLC? Si no, añadir el bloque.
            existing = self._find_assignment_mlc(array_name, slot)
            if existing is None:
                indent = match.group("indent")
                # Si la indentación del bloque no incluye ya 4 espacios
                # (algunos formatos usan 8), respetamos la del match.
                block = f"{indent}{{\n{indent}    S7_MLC := \"{mlc_id}\";\n{indent}}}\n"
                self._upsert_s7dcl_block(match, block)
            return

        # No existe la asignación. Insertar bloque + asignación.
        # Estrategia: añadir al final del bloque de inicialización,
        # antes de ``END_DATA_BLOCK``. Si no aparece
        # ``END_DATA_BLOCK``, añadir al final del archivo.
        new_block = (
            f'        {{ S7_MLC := "{mlc_id}"; }}\n'
            f'        {array_name}[{slot}] := ();\n'
        )
        marker = "END_DATA_BLOCK"
        idx = self._s7dcl.rfind(marker)
        if idx < 0:
            self._s7dcl = self._s7dcl.rstrip() + "\n\n" + new_block
        else:
            self._s7dcl = self._s7dcl[:idx] + new_block + self._s7dcl[idx:]
        self._modified = True

    def _upsert_s7dcl_block(self, match: re.Match[str], block: str) -> None:
        """Inserta un bloque MLC justo antes de ``match``."""
        before = self._s7dcl
        self._s7dcl = (
            self._s7dcl[: match.start()] + block + self._s7dcl[match.start() :]
        )
        if self._s7dcl != before:
            self._modified = True

    # ── Internals: .s7res ───────────────────────────────────────────────

    def _upsert_s7res_entry(self, mlc_id: str, text: str) -> None:
        """Inserta o actualiza una entrada ``- id: <mlc_id> / es-ES: <text>``."""
        text = _escape_s7res_text(text)
        before = self._s7res

        pattern = re.compile(
            rf"(?xm)^(?P<indent>\s*-\s*id:\s*{re.escape(mlc_id)}\s*\n)"
            rf"(?P<inner>(?:\s+[^\n]*\n)*?)"
            rf"(?=\s*-\s*id:|\s*MultiLingualTexts:|\Z)"
        )
        m = pattern.search(self._s7res)
        if m is not None:
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
            new_entry = f"  - id: {mlc_id}\n    es-ES: {text}\n"
            list_start = re.search(
                r"(?m)^MultiLingualTexts:\s*$", self._s7res
            )
            if list_start is None:
                self._s7res = "MultiLingualTexts:\n" + new_entry + self._s7res
            else:
                insert_pos = self._find_s7res_append_pos()
                self._s7res = (
                    self._s7res[:insert_pos] + new_entry + self._s7res[insert_pos:]
                )

        if self._s7res != before:
            self._modified = True

    def _find_s7res_append_pos(self) -> int:
        """Encuentra la posición donde añadir una nueva entrada.

        Estrategia: encontrar el final de la última entrada YAML de
        la lista y devolver el offset justo después de esa línea.
        """
        last_entry_end = 0
        for m in re.finditer(
            r"(?m)^[ \t]+(?:-\s*id:\s*|es-ES:\s*)[^\n]*\n",
            self._s7res,
        ):
            end = m.end()
            if end > last_entry_end:
                last_entry_end = end
        if last_entry_end == 0:
            m = re.search(r"(?m)^MultiLingualTexts:[^\n]*\n", self._s7res)
            if m is None:
                return 0
            return m.end()
        return last_entry_end

    def _prune_s7res(self, keep_mlcs: set[str]) -> None:
        """Elimina del ``.s7res`` las entradas MLC que no estén en ``keep_mlcs``."""
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
                f"ProcesoCommentUpdater: {removed} entradas MLC huérfanas eliminadas."
            )

    def _count_s7res_entries(self) -> int:
        return len(re.findall(r"(?m)^\s*-\s*id:\s*MLC_\S+", self._s7res))


# ── Helpers de módulo ───────────────────────────────────────────────────


def strip_enclosing_quotes(text: str) -> str:
    """Quita comillas envolventes si el texto empieza Y termina con la misma.

    TIA Portal exporta algunos comentarios entre comillas literales
    en el ``.s7res`` (espacios al final, comillas internas, etc.). Y
    el operario a veces pega textos del Excel con comillas envolventes
    por error. Esta función los limpia de forma conservadora: solo
    actúa si la primera Y la última posición son la MISMA comilla
    (simples o dobles). Un texto con una sola comilla al inicio o al
    final se queda tal cual.

    Además hace ``.strip()`` por si TIA deja espacios colgando
    después de la comilla de cierre (caso raro pero visto en
    exports reales).
    """
    if len(text) < 2:
        return text.strip()
    first = text[0]
    last = text[-1]
    if first == last and first in ("'", '"'):
        return text[1:-1].strip()
    return text.strip()


def _sanitize_comment_text(text: str | None, slot: int) -> str:
    """Limpia el texto del comentario: trim, colapsa saltos, escapa, trunca."""
    if text is None:
        text = ""
    s = text.strip()
    # Si el operario pega el comentario del Excel con comillas
    # envolventes por error (p. ej. ``'COMPACTO - FIJOS - '``), las
    # quitamos antes de colapsar whitespace. Esto evita que el
    # apply escriba comillas literales en el ``.s7res``.
    s = strip_enclosing_quotes(s)
    s = re.sub(r"\s+", " ", s)
    if not s:
        s = _EMPTY_TEXT
    if len(s) > _MAX_COMMENT_LEN:
        _logger.warning(
            f"Comentario del slot {slot} truncado de {len(s)} a "
            f"{_MAX_COMMENT_LEN} chars."
        )
        s = s[:_MAX_COMMENT_LEN]
    return s


def _escape_s7res_text(text: str) -> str:
    """Escapa el texto para YAML: comillas dobles como ``""``."""
    return text.replace('"', '""')


__all__ = [
    "ProcesoCommentResult",
    "ProcesoCommentUpdater",
    "strip_enclosing_quotes",
]
