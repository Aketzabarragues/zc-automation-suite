"""core.helpers.simatic_sd: helpers para trabajar con archivos SimaticSD.

Funciones puras (sin estado) para:
- generar IDs MLC unicos (``simatic_sd_mlc_generator``)
- actualizar comentarios de arrays en DBs (``simatic_sd_db_array_comment_updater``)

 refactor: estos helpers reemplazan al
``SimaticSDDbArrayCommentUpdater`` (viejo, 500+ lineas, con dataclasses
y parser custom) y al ``MLCRegistry`` (viejo, con state machine).
"""
from core.helpers.simatic_sd.simatic_sd_mlc_generator import (
    collect_existing_mlc_ids,
    next_mlc_id,
)
from core.helpers.simatic_sd.simatic_sd_db_array_comment_updater import (
    ArrayCommitResult,
    commit_array_comments,
    find_array_slots,
    read_current_comments,
)

__all__ = [
    "collect_existing_mlc_ids",
    "next_mlc_id",
    "ArrayCommitResult",
    "commit_array_comments",
    "find_array_slots",
    "read_current_comments",
]
