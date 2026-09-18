"""Updater DRY de comentarios por array en archivos SimaticSD.

Sept-2026: refactor que unifica ``DispCommentUpdater`` (6 tipos de
dispositivos) y ``ProcCommentUpdater`` (PReal/PInt/ALM + 4 arrays
satélite). El 85% del código era idéntico; quedaba parametrizado por:

  - ``quote_array_name=True`` (disp usa ``"PReal"``/``"PReal"`` con
    comillas literales en su .s7dcl; proc usa ``PReal`` sin comillas).
  - ``keep_slot0=False`` (slot 0 es válido en disp, no en proc).
  - ``ensure_slot0_mlc=False`` (disp inyecta Disp[0] si falta; proc omite).
  - ``satellite_arrays=None`` (proc inyecta texto en ``PReal_Vis``,
    ``Aux.PReal_ValorAnterior`` etc.; disp no tiene satélites).

Ademas, sept-2026 fix del gap: si un satellite slot existe en el
``.s7dcl`` pero SIN MLC (caso tipico tras ``compile_proc_blocks``
que redimensiona N_MAX de PReal=1 a PReal=3 TIA crea ``Aux.PReal_ValorAnterior[2..3]``
sin MLC), el updater ahora INYECTA un nuevo MLC en ese slot del
satélite en lugar de hacer skip.

Origen del fix: validado 2026-09-18 con el DB53010_PRO_STD_PARAM
comentado a mano por el operario. El sync auto-generado dejo 25
satélites sin comentar (3 PReal_Vis + 15 PInt_Vis + 2 Aux.PReal_ValorAnterior
+ 5 Aux.PInt_ValorAnterior). Tras este fix, todos se inyectan.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from areas.alimentacion.helpers.simatic_sd.simatic_sd_mlc_registry import (
    MLCRegistry,
)
from areas.alimentacion.helpers.simatic_sd.simatic_sd_s7dcl_mutator import (
    build_assignment_line,
    build_mlc_assignment_block,
    upsert_s7dcl_block,
)
from areas.alimentacion.helpers.simatic_sd.simatic_sd_s7dcl_parser import (
    extract_all_mlcs_from_s7dcl,
    extract_existing_mlcs_from_s7res,
    find_array_slots,
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
    strip_enclosing_quotes,
)
from core.infrastructure.log_web_bridge import install_web_level
from core.infrastructure.tia.tia_export_paths import (
    SD_ENCODING,
    SD_RES_ENCODING,
)

install_web_level()

_logger: logging.Logger = logging.getLogger(
    f"{__name__}.SimaticSDDbArrayCommentUpdater"
)


# Sentinel para kwarg ``quote_array_name``. Cuando True, el regex
# matcheado llevara comillas literales en torno al nombre del array
# (formato disp). Cuando False, sin comillas (formato proc).
_DEFAULT_INDENT = "        "  # 8 espacios, coincide con .s7dcl export.


@dataclass(frozen=True)
class CommentUpdateResult:
    """Resumen de un ``CommentUpdater.update()``.

    Aplicable tanto a Disp (slot 0 con MLC obligatorio) como a Proc
    (PReal/PInt/ALM + 4 arrays satélite).

    Atributos:
      - ``reused`` / ``inserted``: ``{slot: mlc_id}`` del array principal.
        - ``reused``: slot ya tenia MLC en el .s7dcl → solo actualizo texto.
        - ``inserted``: slot sin MLC → inyecto bloque + asignacion nueva.
      - ``satellite_reused`` / ``satellite_inserted``:
        ``{(sat_array, slot): mlc_id}`` de los satellites.
        - ``satellite_reused``: ya existia MLC del satellite → solo actualizo.
        - ``satellite_inserted``: NUEVO MLC inyectado para el satellite
          (sept-2026: este era el gap que dejaba 25 entradas sin
          comentar tras cada resize N_MAX).
      - ``total_mlcs_in_res``: total de entradas ``- id: MLC_*`` en
        el .s7res tras el update.
    """

    reused: dict[int, str] = field(default_factory=dict)
    inserted: dict[int, str] = field(default_factory=dict)
    satellite_reused: dict[tuple[str, int], str] = field(default_factory=dict)
    satellite_inserted: dict[tuple[str, int], str] = field(default_factory=dict)
    total_mlcs_in_res: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serializa a dict JSON-safe.

        Flask ``jsonify`` no acepta tuplas como keys (lanza
        ``TypeError: keys must be str, int, float, bool or None,
        not tuple``). Las claves ``(sat_array_name, slot)`` se aplanan
        a string ``f"{sat}|{slot}"`` para que el resultado atraviese
        el router Flask sin reventar.

        Esta es la UNICA fuente de verdad de la forma JSON del
        resultado: el dataclass mantiene las tuplas internamente
        (representacion canonica, testeable, type-safe), y este
        helper hace la conversion para serializacion.

        Disp usa ``satellite_reused/inserted={}`` (sin satellites),
        proc las usa activamente: en cualquier caso el formato es
        uniforme.
        """
        return {
            "reused": dict(self.reused),
            "inserted": dict(self.inserted),
            "satellite_reused": {
                f"{sat}|{slot}": mlc
                for (sat, slot), mlc in self.satellite_reused.items()
            },
            "satellite_inserted": {
                f"{sat}|{slot}": mlc
                for (sat, slot), mlc in self.satellite_inserted.items()
            },
            "total_mlcs_in_res": self.total_mlcs_in_res,
        }


class SimaticSDDbArrayCommentUpdater:
    """Updater generico de comentarios por array en DB SimaticSD.

    Reemplaza a ``DispCommentUpdater`` (sept-2026 obsoleto) y
    ``ProcCommentUpdater`` (sept-2026 obsoleto). Las diferencias
    entre disp y proc se parametrizan via kwargs:

      - ``quote_array_name``: disp usa ``"PReal"`` con comillas
        literales en su .s7dcl; proc usa ``PReal`` sin comillas.
      - ``keep_slot0``: disp considera el slot 0 valido (Disp[0] es
        la primera instancia fisica); proc lo filtra.
      - ``ensure_slot0_mlc``: disp inyecta MLC en slot 0 si no
        existe; proc omite (los arrays de procesos empiezan en 1).
      - ``satellite_arrays``: lista de arrays satélite del DB
        (proc: ``{"PReal_Vis", "Aux.PReal_ValorAnterior"}``;
        disp: ``set()``).

    Restricción arquitectónica: este modulo NO importa
    ``siemens_tia_scripting``.
    """

    def __init__(
        self,
        s7dcl_path: str | Path,
        s7res_path: str | Path,
        array_name: str,
        slot_map: dict[int, str],
        *,
        quote_array_name: bool = True,           # disp True, proc False
        keep_slot0: bool = False,               # disp True
        ensure_slot0_mlc: bool = False,         # disp True
        satellite_arrays: set[str] | None = None,
        registry: MLCRegistry | None = None,
    ) -> None:
        self._s7dcl_path = Path(s7dcl_path)
        self._s7res_path = Path(s7res_path)

        if not self._s7dcl_path.is_file():
            raise FileNotFoundError(
                f"No se encontró .s7dcl: '{self._s7dcl_path}'"
            )
        if not self._s7res_path.is_file():
            raise FileNotFoundError(
                f"No se encontró .s7res: '{self._s7res_path}'"
            )

        self._array_name: str = (array_name or "").strip()
        self._quote_array_name: bool = quote_array_name
        self._keep_slot0: bool = keep_slot0
        self._ensure_slot0_mlc: bool = ensure_slot0_mlc
        self._satellite_arrays: set[str] = set(satellite_arrays or ())

        # Filtrar slot 0 si no es valido (proc por defecto).
        if not keep_slot0 and 0 in slot_map:
            _logger.warning(
                f"SimaticSDDbArrayCommentUpdater: array={array_name!r} "
                f"contiene slot 0 en slot_map; se ignora (no aplica "
                f"en este dominio)."
            )
            slot_map = {k: v for k, v in slot_map.items() if int(k) >= 1}
        self._slot_map: dict[int, str] = dict(slot_map)

        # Carga en memoria.
        self._s7dcl: str = self._s7dcl_path.read_text(encoding=SD_ENCODING)
        self._s7res: str = self._s7res_path.read_text(
            encoding=SD_RES_ENCODING
        )

        # Estado mutable.
        self._modified: bool = False
        # Inicializa el registry con los MLCs ya presentes (para que
        # ``next_mlc_id`` no colisione). Reutilizado logic compartida
        # con DispCommentUpdater y ProcCommentUpdater.
        if registry is None:
            existing = extract_existing_mlcs_from_s7res(self._s7res)
            self._registry: MLCRegistry = MLCRegistry(used_ids=existing)
        else:
            registry.reserve(
                extract_existing_mlcs_from_s7res(self._s7res)
            )
            self._registry = registry

        self._result: CommentUpdateResult | None = None

    # ── API publica ────────────────────────────────────────────────────────

    def update(self) -> CommentUpdateResult:
        """Orquesta la actualizacion. Retorna ``CommentUpdateResult``.

        Algoritmo unificado (sept-2026):
          1. ``ensure_slot0_mlc`` (opcional, solo disp):
             si el array principal es ``Disp`` y el slot 0 no tiene MLC,
             inyecto uno nuevo. Asi Disp[0] queda con su comentario.
          2. Para cada slot del slot_map, localizar MLC existente del
             array principal o generar uno nuevo.
          3. Para cada slot actualizado, propagar a los satellites:
             a. Si el satellite slot ya tiene MLC → reutilizar y propagar.
             b. Si NO tiene MLC pero tiene asignacion ``<sat>[slot] := ();``
                → INYECTAR bloque + MLC nuevo (sept-2026 fix).
             c. Si NO tiene asignacion → inyeccion bloque + asignacion
                antes de ``END_DATA_BLOCK`` (caso raro).
          4. Restaurar MLCs huerfanos en el .s7res (cabeceras etc.).
          5. Podar el .s7res (quitar entradas no referenciadas).
        """
        reused: dict[int, str] = {}
        inserted: dict[int, str] = {}
        satellite_reused: dict[tuple[str, int], str] = {}
        satellite_inserted: dict[tuple[str, int], str] = {}

        _logger.debug(
            f"SimaticSDDbArrayCommentUpdater: array={self._array_name!r}, "
            f"{len(self._slot_map)} slots, "
            f"satellites={sorted(self._satellite_arrays)}, "
            f"file='{self._s7dcl_path.name}'"
        )

        # 1) ensure_slot0_mlc (solo disp)
        if self._ensure_slot0_mlc:
            self._ensure_slot0()

        # 2) Array principal por slot.
        for slot, raw_text in self._slot_map.items():
            text = sanitize_comment_text(raw_text, slot)
            existing_mlc = find_assignment_mlc(
                self._s7dcl, self._normalize_for_parse(self._array_name), slot
            )
            if existing_mlc is not None:
                self._registry.reserve([existing_mlc])
                reused[slot] = existing_mlc
                self._s7res, mod = upsert_s7res_entry(
                    self._s7res, existing_mlc, text
                )
                if mod:
                    self._modified = True
            else:
                new_mlc = self._registry.next_mlc_id()
                self._inject_for_array(
                    self._array_name, slot, new_mlc,
                )
                self._s7res, mod = upsert_s7res_entry(
                    self._s7res, new_mlc, text
                )
                if mod:
                    self._modified = True
                inserted[slot] = new_mlc

            # 3) Propagacion a satellites del mismo slot.
            for sat_array in sorted(self._satellite_arrays):
                sat_mlc = find_assignment_mlc(
                    self._s7dcl, self._normalize_for_parse(sat_array), slot
                )
                if sat_mlc is not None:
                    # Satellite ya tenia MLC → reutilizar + propagar texto.
                    self._registry.reserve([sat_mlc])
                    self._s7res, mod = upsert_s7res_entry(
                        self._s7res, sat_mlc, text
                    )
                    if mod:
                        self._modified = True
                    satellite_reused[(sat_array, slot)] = sat_mlc
                    continue

                # Sin MLC en este satellite slot. FIX sept-2026: si la
                # asignacion existe en el .s7dcl (creada por TIA tras
                # resize), inyectar bloque antes de la asignacion.
                # Si no existe, inyectar bloque + asignacion antes de
                # END_DATA_BLOCK.
                sat_assign = find_assignment(
                    self._s7dcl, self._normalize_for_parse(sat_array), slot,
                )
                new_sat_mlc = self._registry.next_mlc_id()
                if sat_assign is not None:
                    # Caso tipico: TIA creo ``Aux.PReal_ValorAnterior[N] := ();``
                    # en el resize pero sin MLC. Anadimos el bloque delante.
                    block = build_mlc_assignment_block(
                        sat_assign.group("indent"), new_sat_mlc,
                    )
                    self._s7dcl, mod = upsert_s7dcl_block(
                        self._s7dcl, sat_assign, block,
                    )
                    if mod:
                        self._modified = True
                else:
                    # Caso raro: el satellite slot no existe en el .s7dcl
                    # (TIA lo omitio del export). Anadimos bloque + asignacion
                    # antes de END_DATA_BLOCK.
                    self._append_satellite_assignment(sat_array, slot, new_sat_mlc)

                # Anadir/actualizar entrada en .s7res con el mismo texto.
                self._s7res, mod = upsert_s7res_entry(
                    self._s7res, new_sat_mlc, text
                )
                if mod:
                    self._modified = True
                satellite_inserted[(sat_array, slot)] = new_sat_mlc

        # 4) Calcular el conjunto de MLCs referenciados por el .s7dcl
        # para equilibrar el .s7res.
        referenced: set[str] = (
            set(reused.values())
            | set(inserted.values())
            | set(satellite_reused.values())
            | set(satellite_inserted.values())
            | extract_all_mlcs_from_s7dcl(self._s7dcl)
        )

        # 4.bis) Si el .s7dcl referencia MLCs que el .s7res no tiene
        # (caso tipico: la exportacion de TIA omite los MLCs de
        # cabecera), los añadimos con texto "." (convencion TIA).
        existing_in_res = extract_existing_mlcs_from_s7res(self._s7res)
        for mlc_id in referenced:
            if mlc_id not in existing_in_res:
                self._s7res, mod = upsert_s7res_entry(
                    self._s7res, mlc_id, "."
                )
                if mod:
                    self._modified = True

        # 5) Podar el .s7res.
        new_res, removed = prune_s7res(self._s7res, referenced)
        if removed:
            self._s7res = new_res
            self._modified = True

        total_mlcs = count_s7res_entries(self._s7res)
        self._result = CommentUpdateResult(
            reused=reused,
            inserted=inserted,
            satellite_reused=satellite_reused,
            satellite_inserted=satellite_inserted,
            total_mlcs_in_res=total_mlcs,
        )
        _logger.debug(
            f"SimaticSDDbArrayCommentUpdater: array={self._array_name!r}, "
            f"reused={len(reused)}, inserted={len(inserted)}, "
            f"satellites (reused={len(satellite_reused)}, "
            f"inserted={len(satellite_inserted)}), "
            f"total_mlcs_in_res={total_mlcs}, modified={self._modified}"
        )
        return self._result

    def was_modified(self) -> bool:
        """True si el último ``update()`` modificó el .s7dcl o .s7res."""
        return self._modified

    def save(
        self,
        output_s7dcl_path: str | Path | None = None,
        output_s7res_path: str | Path | None = None,
    ) -> None:
        """Escribe los archivos (in-place si no se pasan rutas de salida)."""
        s7dcl_out = Path(output_s7dcl_path) if output_s7dcl_path else self._s7dcl_path
        s7res_out = Path(output_s7res_path) if output_s7res_path else self._s7res_path
        s7dcl_out.write_text(self._s7dcl, encoding=SD_ENCODING)
        s7res_out.write_text(self._s7res, encoding=SD_RES_ENCODING)

    def read_current_comments(
        self,
        slot_indices: "list[int] | tuple[int, ...] | set[int]",
        array_name: str | None = None,
    ) -> dict[int, str | None]:
        """Lee el ``es-ES`` actual de los slots del array.

        Usado por el detector de "eliminar" en proc (slots que existen
        en TIA pero no en el Excel del operario → se marcan con ``.``
        para "borrar" el comentario).

        Solo expone los MLCs del array principal; los satélites son
        copias del mismo texto y se actualizan al aplicar cambios.

        Args:
            slot_indices: coleccion de slots 1-based a inspeccionar.
            array_name: nombre del array. Por defecto ``self._array_name``.

        Returns:
            ``{slot: es-ES-actual o None}``.
            ``None`` si el slot existe en el .s7dcl pero sin MLC.
        """
        target_array = array_name or self._array_name
        if not target_array:
            raise ValueError(
                "read_current_comments: array_name es obligatorio "
                "(self._array_name esta vacio)."
            )
        mlc_to_text = self._build_mlc_text_map()
        result: dict[int, str | None] = {}
        for slot in slot_indices:
            mlc = find_assignment_mlc(
            self._s7dcl, self._normalize_for_parse(target_array), slot,
        )
            if mlc is None:
                result[slot] = None
            else:
                # Si el MLC existe en el .s7dcl pero no en el .s7res,
                # devolvemos string vacio (caso TIA degenerado).
                result[slot] = mlc_to_text.get(mlc, "")
        return result

    # ── Internos ──────────────────────────────────────────────────────────

    def _inject_for_array(
        self,
        array_name: str,
        slot: int,
        mlc_id: str,
    ) -> None:
        """Inserta bloque + asignacion para el array principal o un satellite.

        Si la asignacion existe en el .s7dcl: anade bloque antes.
        Si no existe: anade bloque + asignacion al final del bloque
        de inicializacion (antes de ``END_DATA_BLOCK``).
        """
        # IMPORTANTE: el parser ``find_assignment`` captura ``array`` SIN
        # comillas envolventes (el regex las marca como opcionales).
        # Si nuestro caller paso ``'"PReal"'`` (disp), normalizamos
        # ANTES de consultar. Mantenemos ``array_name`` CON comillas
        # cuando escribimos (para preservar el formato original del
        # .s7dcl en inyecciones nuevas).
        parse_name = self._normalize_for_parse(array_name)
        match = find_assignment(self._s7dcl, parse_name, slot)
        if match is not None:
            indent = match.group("indent")
            block = build_mlc_assignment_block(indent, mlc_id)
            self._s7dcl, mod = upsert_s7dcl_block(self._s7dcl, match, block)
            if mod:
                self._modified = True
            return

        # Asignacion no existe: inyeccion al final del bloque de
        # inicializacion (antes de ``END_DATA_BLOCK``). Preservamos
        # ``array_name`` LITERAL (con comillas si las tenia) para que
        # la sintaxis del .s7dcl sea consistente con el header.
        new_block = (
            build_mlc_assignment_block(_DEFAULT_INDENT, mlc_id)
            + build_assignment_line(_DEFAULT_INDENT, array_name, slot)
        )
        marker = "END_DATA_BLOCK"
        idx = self._s7dcl.rfind(marker)
        if idx < 0:
            self._s7dcl = self._s7dcl.rstrip() + "\n\n" + new_block
        else:
            self._s7dcl = self._s7dcl[:idx] + new_block + self._s7dcl[idx:]
        self._modified = True

    def _append_satellite_assignment(
        self,
        sat_array: str,
        slot: int,
        mlc_id: str,
    ) -> None:
        """Anade bloque + asignacion del satellite antes de END_DATA_BLOCK."""
        new_block = (
            build_mlc_assignment_block(_DEFAULT_INDENT, mlc_id)
            + build_assignment_line(_DEFAULT_INDENT, sat_array, slot)
        )
        marker = "END_DATA_BLOCK"
        idx = self._s7dcl.rfind(marker)
        if idx < 0:
            self._s7dcl = self._s7dcl.rstrip() + "\n\n" + new_block
        else:
            self._s7dcl = self._s7dcl[:idx] + new_block + self._s7dcl[idx:]
        self._modified = True

    def _ensure_slot0(self) -> None:
        """Inyecta MLC en ``<ARRAY>[0]`` si no existe (solo disp).

        Insercion idempotente: si ``[0]`` ya tiene MLC, no hace nada.
        """
        existing = find_assignment_mlc(
            self._s7dcl, self._normalize_for_parse(self._array_name), 0,
        )
        if existing is not None:
            return
        new_mlc = self._registry.next_mlc_id()
        self._inject_for_array(self._array_name, 0, new_mlc)

    @staticmethod
    def _normalize_for_parse(name: str) -> str:
        """Quita comillas envolventes de un ``array_name``.

        ``find_assignment_mlc`` y ``find_assignment`` capturan el
        grupo ``array`` SIN comillas envolventes (el regex las marca
        como opcionales con ``"?``). Esta funcion centraliza la
        normalizacion para que el updater sea consistente: al
        CONSULTAR el .s7dcl siempre pasamos sin comillas; al ESCRIBIR
        (inyectar nueva asignacion) respetamos el formato original.
        """
        return name.strip('"') if name else name

    # ── Compatibilidad con ProcCommentUpdater.detect_existencias ───────

    def find_array_slots(self, array_name: str) -> set[int]:
        """Delega en el parser (preserva la API previa)."""
        return find_array_slots(self._s7dcl, array_name)

    def _build_mlc_text_map(self) -> dict[str, str]:
        """Devuelve ``{MLC_id: es-ES_text}`` con todas las entradas
        del ``.s7res``.

        Funcion inversa de ``upsert_s7res_entry``: usada por
        ``read_current_comments`` para mapear MLC -> texto sin
        modificar nada.
        """
        result: dict[str, str] = {}
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
                result[mlc_id] = ""
            else:
                raw = es_match.group(1)
                result[mlc_id] = strip_enclosing_quotes(raw)
        return result


__all__ = [
    "CommentUpdateResult",
    "SimaticSDDbArrayCommentUpdater",
]
