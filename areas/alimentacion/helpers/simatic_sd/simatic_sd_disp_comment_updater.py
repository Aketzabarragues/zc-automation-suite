"""Actualizador offline de comentarios por instancia en Source Documents.

Modifica un par de archivos ``.s7dcl`` + ``.s7res`` exportados por
TIA Portal para escribir el comentario de cada instancia de un array
de UDTs en un DB de dispositivo.

Replica el patron OFFLINE de ``infrastructure/xml/disp_tag_table_modifier.py``
(sin imports de ``siemens_tia_scripting``, solo ``pathlib``,
``dataclasses``).

Este modulo es el orquestador: delega en los helpers de ``simatic_sd/``
para el parseo, la mutacion y la gestion del .s7res.

Convencion de archivos
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

Uso tipico
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
from dataclasses import dataclass
from pathlib import Path

from areas.alimentacion.helpers.simatic_sd.simatic_sd_mlc_registry import MLCRegistry
from areas.alimentacion.helpers.simatic_sd.simatic_sd_s7dcl_mutator import (
    build_assignment_line,
    build_mlc_assignment_block,
    upsert_s7dcl_block,
)
from areas.alimentacion.helpers.simatic_sd.simatic_sd_s7dcl_parser import (
    extract_all_mlcs_from_s7dcl,
    extract_existing_mlcs_from_s7res,
    find_assignment,
    find_assignment_mlc,
)
from areas.alimentacion.helpers.simatic_sd.simatic_sd_s7res_manager import (
    count_s7res_entries,
    prune_s7res,
    upsert_s7res_entry,
)
from areas.alimentacion.helpers.simatic_sd.simatic_sd_text_utils import (
    sanitize_comment_text,
)
from core.infrastructure.tia.tia_export_paths import SD_ENCODING, SD_RES_ENCODING

# Asegura que ``Logger.web/ok`` existen tambien fuera del arranque.
from core.infrastructure.log_web_bridge import install_web_level
install_web_level()


_logger: logging.Logger = logging.getLogger(f"{__name__}.DispCommentUpdater")

# Texto fijo para el slot 0 (siempre "NO USAR" según decisión de diseño).
_NO_USAR_TEXT: str = "NO USAR"


# ── Resultado del update ───────────────────────────────────────────────────


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


# ── Entry point ────────────────────────────────────────────────────────────


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
        self._s7dcl: str = self._s7dcl_path.read_text(encoding=SD_ENCODING)
        self._s7res: str = self._s7res_path.read_text(encoding=SD_RES_ENCODING)

        # Estado mutable.
        self._modified: bool = False
        self._registry: MLCRegistry = MLCRegistry(
            used_ids=extract_existing_mlcs_from_s7res(self._s7res)
        )
        self._result: DispCommentResult | None = None

    # ── API pública ─────────────────────────────────────────────────────────

    def update(self) -> DispCommentResult:
        """Orquesta la actualización. Retorna ``DispCommentResult``.

        Algoritmo:
          1. Para cada i in slot_map: localizar MLC existente o crear uno.
          2. Slot 0: siempre debe tener MLC (respetar o crear).
          3. Reescribir ``.s7res`` (alta/baja de entradas).
          4. Devolver resultado.
        """
        _logger.debug(
            f"DispCommentUpdater: array={self._db_array_name!r}, "
            f"{len(self._slot_map)} slots, "
            f"file='{self._s7dcl_path.name}', res='{self._s7res_path.name}'"
        )
        reused: dict[int, str] = {}
        inserted: dict[int, str] = {}

        # 1) Para cada slot del map, asegurar asignación + MLC.
        for slot, raw_text in self._slot_map.items():
            text = sanitize_comment_text(raw_text, slot)
            existing_mlc = find_assignment_mlc(self._s7dcl, self._db_array_name, slot)
            if existing_mlc is not None:
                # MLC ya estaba en el .s7dcl; lo respetamos.
                self._registry.reserve([existing_mlc])
                reused[slot] = existing_mlc
                # Si el .s7res perdió esta entrada, la restauramos con el texto.
                self._s7res, mod = upsert_s7res_entry(self._s7res, existing_mlc, text)
                if mod:
                    self._modified = True
            else:
                # Crear MLC nuevo.
                new_mlc = self._registry.next_mlc_id()
                self._inject_mlc_block_or_assignment(slot, new_mlc)
                self._s7res, mod = upsert_s7res_entry(self._s7res, new_mlc, text)
                if mod:
                    self._modified = True
                inserted[slot] = new_mlc

        # 2) Slot 0 — siempre debe tener MLC. Si no lo tiene, crearlo.
        no_usar_mlc = reused.get(0) or inserted.get(0) or self._ensure_slot0_mlc()

        # 3) Eliminar MLCs huérfanos del .s7res (los que ya no se referencian).
        # IMPORTANTE: ``referenced`` debe incluir TODOS los MLCs del .s7dcl,
        # no solo los de los slots. TIA exige que el ``count`` de MLCs en el
        # .s7dcl coincida EXACTAMENTE con el del .s7res.
        referenced = (
            set(reused.values())
            | set(inserted.values())
            | {no_usar_mlc}
            | extract_all_mlcs_from_s7dcl(self._s7dcl)
        )

        # 3.bis) Si el .s7dcl referencia MLCs que el .s7res no tiene
        # (caso típico: la exportación de TIA omite los MLCs de cabecera
        # como ``MLC_block_cmt``, ``MLC_arr_cmt``), los añadimos al
        # .s7res con texto ``"."`` (convención TIA "sin comentario").
        existing_in_res = extract_existing_mlcs_from_s7res(self._s7res)
        for mlc_id in referenced:
            if mlc_id not in existing_in_res:
                self._s7res, mod = upsert_s7res_entry(self._s7res, mlc_id, ".")
                if mod:
                    self._modified = True

        new_res, removed = prune_s7res(self._s7res, referenced)
        if removed:
            self._s7res = new_res
            self._modified = True

        # 4) Resultado.
        total_mlcs = count_s7res_entries(self._s7res)
        self._result = DispCommentResult(
            reused=reused,
            inserted=inserted,
            no_usar_mlc=no_usar_mlc,
            total_mlcs_in_res=total_mlcs,
        )
        _logger.debug(
            f"DispCommentUpdater: array={self._db_array_name!r}, "
            f"reused={len(reused)}, inserted={len(inserted)}, "
            f"total_mlcs_in_res={total_mlcs}, modified={self._modified}"
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
        out_dcl.write_text(self._s7dcl, encoding=SD_ENCODING)
        out_res.write_text(self._s7res, encoding=SD_RES_ENCODING)

    # ── Internals: orquestación con state ───────────────────────────────────

    def _ensure_slot0_mlc(self) -> str:
        """Asegura que ``<ARRAY>[0] := ();`` existe con un MLC. Devuelve el MLC.

        Usado como red de seguridad si slot_map no incluye 0 (no debería
        pasar, pero defendámonos).
        """
        existing = find_assignment_mlc(self._s7dcl, self._db_array_name, 0)
        if existing is not None:
            self._registry.reserve([existing])
            return existing
        new_mlc = self._registry.next_mlc_id()
        self._inject_mlc_block_or_assignment(0, new_mlc)
        self._s7res, _ = upsert_s7res_entry(self._s7res, new_mlc, _NO_USAR_TEXT)
        self._modified = True
        return new_mlc

    def _inject_mlc_block_or_assignment(self, slot: int, mlc_id: str) -> None:
        """Inserta la asignación y/o su bloque S7_MLC.

        - Si existe ``<ARRAY>[slot] := ();`` sin bloque MLC → añade el bloque antes.
        - Si no existe la asignación → añade bloque + asignación al final del bloque
          de inicialización (última asignación del array). Si no hay inicialización,
          la añade justo antes de ``END_DATA_BLOCK``.
        """
        match = find_assignment(self._s7dcl, self._db_array_name, slot)
        if match is not None:
            # Existe la asignación. ¿Tiene MLC? Si no, añadir el bloque.
            existing = find_assignment_mlc(self._s7dcl, self._db_array_name, slot)
            if existing is None:
                indent = match.group("indent")
                block = build_mlc_assignment_block(indent, mlc_id)
                self._s7dcl, mod = upsert_s7dcl_block(self._s7dcl, match, block)
                if mod:
                    self._modified = True
            return

        # No existe la asignación. Insertar bloque + asignación.
        # Para una asignación nueva, el nombre del array va entre comillas
        # (formato TIA para arrays cualificados: ``"ED"[3] := ();``).
        new_block = (
            build_mlc_assignment_block("        ", mlc_id)
            + f'        "{self._db_array_name}"[{slot}] := ();\n'
        )
        marker = "END_DATA_BLOCK"
        idx = self._s7dcl.rfind(marker)
        if idx < 0:
            # Sin END_DATA_BLOCK → añadir al final.
            self._s7dcl = self._s7dcl.rstrip() + "\n\n" + new_block
            self._modified = True
            return
        before = self._s7dcl[:idx].rstrip()
        after = self._s7dcl[idx:]
        self._s7dcl = before + "\n\n" + new_block + "\n" + after
        self._modified = True
