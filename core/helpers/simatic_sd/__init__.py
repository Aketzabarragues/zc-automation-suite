"""core.helpers.simatic_sd: helpers para trabajar con archivos SimaticSD.

Funciones puras (sin estado) para:
- generar IDs MLC unicos (``simatic_sd_mlc_generator``)
- actualizar comentarios de arrays en DBs (``simatic_sd_db_array_comment_updater``)

Sept-2026 refactor DRY: estos helpers reemplazan al
``SimaticSDDbArrayCommentUpdater`` (viejo, 500+ lineas, con dataclasses
y parser custom) y al ``MLCRegistry`` (viejo, con state machine).
"""
from core.helpers.simatic_sd.simatic_sd_mlc_generator import (
    collect_existing_mlc_ids,
    next_mlc_id,
)

__all__ = [
    "collect_existing_mlc_ids",
    "next_mlc_id",
]


# Imports perezosos para evitar ciclos cuando estos helpers se usan
# desde el codigo viejo (sept-2026: todavia coexisten durante la
# migracion gradual).
def __getattr__(name: str):  # pragma: no cover
    if name in {"commit_array_comments", "ArrayCommitResult"}:
        from core.helpers.simatic_sd import simatic_sd_db_array_comment_updater
        return getattr(simatic_sd_db_array_comment_updater, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
