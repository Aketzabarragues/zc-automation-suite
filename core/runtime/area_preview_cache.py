"""core.runtime.area_preview_cache - setters per-area para slots del AppCache.

Wrappers sobre ``AppCache.mutate_area`` con la firma estable
``fn(area) -> area``. Cada uno:

- reemplaza el area bajo el lock del AppCache,
- dispara el hook ``on_change`` con el slot publico correspondiente,
- es lo unico que los routers tocan para publicar previews o
  resumenes de commit en el cache del backend.

Contrato: el ``area_cache`` es la instancia Singleton
(``get_app_cache()``); no se thread-local, no se per-request. La
sustitucion atomica la garantiza ``mutate_area``.

Defensivo: si el ``area_id`` no esta registrado en el cache (p. ej.
en tests que instancian el AppCache sin boot completo), el setter
no-op con ``logger.debug`` en vez de lanzar ``KeyError``. Asi los
routers pueden llamar al setter sin ``try/except`` y los tests que
no necesitan el cache siguen pasando.

Los slots cubiertos:

- ``preview_disp``: dict del FB ``disp_generar_preview``.
- ``preview_proc``: dict del FB ``proc_sync_generar_preview``.
- ``last_disp_commit_summary``: dict resumen de
  ``disp_sync_commit``.
- ``last_proc_commit_summary``: dict resumen de
  ``proc_sync_commit``.
- ``last_sync_disp_at`` / ``last_sync_proc_at``: timestamp ISO
  escrito al aplicar el commit correspondiente.

No se acopla al bounded context ``alimentacion``: el setter opera
sobre cualquier ``AreaCacheProtocol`` que tenga el campo. Las areas
que no tengan el slot relevante lo setean a ``None`` sin error
(debe ser un atributo del dataclass, aunque sea siempre ``None``).
"""
from __future__ import annotations

import dataclasses
import logging
from datetime import datetime as _dt
from datetime import timezone
from typing import Any

from core.runtime.app_cache import AppCache

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return _dt.now(timezone.utc).isoformat()


def _area_exists(app_cache: AppCache, area_id: str) -> bool:
    try:
        app_cache.area(area_id)
        return True
    except KeyError:
        return False


def _safe_mutate(
    app_cache: AppCache,
    area_id: str,
    fn: Any,
    *,
    slot: str,
) -> None:
    """Wrapper defensivo: si no existe el area, no-op + debug log."""
    if not _area_exists(app_cache, area_id):
        logger.debug(
            "area_preview_cache: area %r no registrada; slot=%s no aplicado.",
            area_id, slot,
        )
        return
    app_cache.mutate_area(area_id, fn, slot=slot)


def area_set_preview_disp(
    app_cache: AppCache,
    area_id: str,
    preview: dict[str, Any] | None,
) -> None:
    """Publica el preview de disp/entidades en el cache del area."""
    def _mutate(area: Any) -> Any:
        return dataclasses.replace(area, preview_disp=preview)
    _safe_mutate(app_cache, area_id, _mutate, slot="preview_disp")


def area_set_preview_proc(
    app_cache: AppCache,
    area_id: str,
    preview: dict[str, Any] | None,
) -> None:
    """Publica el preview de sync de comentarios de procesos."""
    def _mutate(area: Any) -> Any:
        return dataclasses.replace(area, preview_proc=preview)
    _safe_mutate(app_cache, area_id, _mutate, slot="preview_proc")


def area_set_disp_commit_summary(
    app_cache: AppCache,
    area_id: str,
    summary: dict[str, Any] | None,
) -> None:
    """Publica el resumen del ultimo commit de disp/entidades."""
    def _mutate(area: Any) -> Any:
        return dataclasses.replace(
            area,
            last_disp_commit_summary=summary,
            last_sync_disp_at=_now_iso(),
        )
    _safe_mutate(app_cache, area_id, _mutate, slot="last_disp_commit_summary")


def area_set_proc_commit_summary(
    app_cache: AppCache,
    area_id: str,
    summary: dict[str, Any] | None,
) -> None:
    """Publica el resumen del ultimo commit de comentarios de procesos."""
    def _mutate(area: Any) -> Any:
        return dataclasses.replace(
            area,
            last_proc_commit_summary=summary,
            last_sync_proc_at=_now_iso(),
        )
    _safe_mutate(app_cache, area_id, _mutate, slot="last_proc_commit_summary")


def area_clear_disp_preview(
    app_cache: AppCache,
    area_id: str,
) -> None:
    """Limpia el preview de disp (operario deselecciona PLC o TIA cae)."""
    area_set_preview_disp(app_cache, area_id, None)


def area_clear_proc_preview(
    app_cache: AppCache,
    area_id: str,
) -> None:
    """Limpia el preview de proc (operario deselecciona PLC o TIA cae)."""
    area_set_preview_proc(app_cache, area_id, None)


__all__ = [
    "area_set_preview_disp",
    "area_set_preview_proc",
    "area_set_disp_commit_summary",
    "area_set_proc_commit_summary",
    "area_clear_disp_preview",
    "area_clear_proc_preview",
]