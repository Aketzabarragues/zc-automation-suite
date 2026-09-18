"""Helper simplificado para commit de comentarios de un proceso.

Sept-2026 refactor DRY (sigue a los Commits 18 + 19). Este modulo
orquesta las 6 llamadas a ``commit_array_comments`` (1 por cada
array del proceso) sobre el .s7dcl + .s7res ya exportados.

Antes (sept-2026 -): el handler OT ``update_proc_comments_db_param``
ejecutaba un updater custom (SimaticSDDbArrayCommentUpdater, 500+
lineas) que cubria PReal + PInt + sus 4 satellites en una sola op.
Para ALM habia un handler separado.

Despues (sept-2026): el FB ``proc_sincronizar`` itera los 6 arrays
del proceso (PReal, PReal_Vis, Aux.PReal_ValorAnterior, PInt,
PInt_Vis, Aux.PInt_ValorAnterior) + 1 para ALM, llamando a
``commit_array_comments`` por cada uno. Sin state machine custom,
sin parser regex custom, sin registry de MLCs.

Flujo:
  1. FB hace ``export_block`` del DB PARAM + DB ALM (via tia_client).
  2. FB llama ``commit_proc_simplified(dcl_param, res_param, ...)``
     que itera los 6 arrays del PARAM en modo ``write_to_original``
     (cada llamada acumula cambios sobre el mismo archivo).
  3. FB llama ``commit_proc_simplified(dcl_alm, res_alm, ...)` para
     ALM (1 solo array, sin satellites).
  4. FB hace ``import_block`` del PARAM + ALM (via tia_client).

Si el import falla, TIA hace rollback atomico del DB completo.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from core.helpers.simatic_sd import (
    ArrayCommitResult,
    commit_array_comments,
)

_logger = logging.getLogger(__name__)


# Tipo de dato TIA para cada array del proceso. Los satellites son
# SIEMPRE tipos simples (no UDT), aunque compartan nombre con un
# array principal UDT.
PROC_ARRAYS_PARAM: list[tuple[str, str]] = [
    ("PReal",                   "UDT"),
    ("PReal_Vis",               "Simple"),
    ("Aux.PReal_ValorAnterior", "Simple"),
    ("PInt",                    "UDT"),
    ("PInt_Vis",                "Simple"),
    ("Aux.PInt_ValorAnterior",  "Simple"),
]

PROC_ARRAYS_ALM: list[tuple[str, str]] = [
    ("ALM", "Simple"),
]


@dataclass(frozen=True)
class ProcCommitSummary:
    """Resumen agregado del commit de comentarios del proceso.

    Por cada array: ``ArrayCommitResult`` individual. Para el total:
    ``total_injected`` = suma de slots inyectados, etc.
    """
    dcl_path: Path
    res_path: Path
    per_array: dict[str, ArrayCommitResult] = field(default_factory=dict)

    @property
    def total_injected(self) -> int:
        return sum(len(r.injected) for r in self.per_array.values())

    @property
    def total_reused(self) -> int:
        return sum(len(r.reused) for r in self.per_array.values())

    @property
    def total_updated(self) -> int:
        return sum(len(r.updated) for r in self.per_array.values())

    @property
    def total_removed(self) -> int:
        return sum(len(r.removed) for r in self.per_array.values())

    @property
    def total_noop(self) -> int:
        return sum(len(r.noop) for r in self.per_array.values())


def commit_proc_simplified(
    dcl_path: str | Path,
    res_path: str | Path,
    slot_maps: dict[str, dict[int, str]],
    *,
    array_types: list[tuple[str, str]] | None = None,
) -> ProcCommitSummary:
    """Aplica los slot_maps a un DB SimaticSD llamando ``commit_array_comments``.

    Itera los arrays dados por ``array_types`` (default: 6 arrays
    PARAM) y para cada uno invoca ``commit_array_comments`` con
    ``write_to_original=True`` (cada llamada acumula cambios sobre
    el mismo archivo; al final del bucle los archivos originales
    contienen TODOS los cambios acumulados).

    Args:
        dcl_path: ruta al .s7dcl del DB.
        res_path: ruta al .s7res del DB.
        slot_maps: ``{array_name: {slot: texto}}``. Slots no
            presentes se ignoran (no se eliminan). Si el array
            completo no esta, se procesa como slot_map vacio (no-op).
        array_types: lista de ``(array_name, array_type)`` a iterar.
            Default: ``PROC_ARRAYS_PARAM`` (los 6 arrays del proceso).

    Returns:
        ``ProcCommitSummary`` con los resultados agregados por array.
    """
    dcl_path = Path(dcl_path)
    res_path = Path(res_path)
    array_types = array_types or PROC_ARRAYS_PARAM

    # Acumulamos en dict mutable y devolvemos ProcCommitSummary al final.
    per_array: dict[str, ArrayCommitResult] = {}

    for array_name, array_type in array_types:
        slot_map = slot_maps.get(array_name, {})
        if not slot_map:
            _logger.debug(
                f"commit_proc_simplified: {array_name} sin slot_map, skip."
            )
            continue
        result = commit_array_comments(
            dcl_path, res_path, array_name, slot_map,
            array_type=array_type,
            write_to_original=True,
        )
        per_array[array_name] = result
        _logger.debug(
            f"commit_proc_simplified: {array_name} -> "
            f"injected={len(result.injected)} reused={len(result.reused)} "
            f"updated={len(result.updated)} removed={len(result.removed)} "
            f"noop={len(result.noop)}"
        )

    return ProcCommitSummary(
        dcl_path=dcl_path,
        res_path=res_path,
        per_array=per_array,
    )


__all__ = [
    "PROC_ARRAYS_PARAM",
    "PROC_ARRAYS_ALM",
    "ProcCommitSummary",
    "commit_proc_simplified",
]
