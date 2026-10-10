"""Helpers puros de la carga del Excel corporativo (FB subir_excel).

Funciones puras (sin estado, sin tracker, sin AppState):
  - ``parse_excel_to_cache``: lee el ``.xlsx``, lo escribe al
    ``AppCache`` del area indicado y devuelve el ``DataExcelCache``.

El FB ``FunctionExcelCargar`` orquesta la carga en un unico step
(``parsear_excel``) y emite los progress events via el ``tracker``.

### Fuente de verdad

``AppCache`` (via ``core.runtime.excel_cache``) es la unica fuente de
verdad del cache del Excel. ``parse_excel_to_cache`` escribe
directamente al ``excel_full`` del area y rederiva el ``excel_active``
filtrado por el PLC seleccionado. Cualquier consumidor (FB,
endpoint, helper) lee via ``excel_get_full`` / ``excel_get_active``.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from core.data.data_excel_cache import DataExcelCache
from areas.alimentacion.helpers.excel.excel_loader import ExcelLoader
from core.infrastructure.config.config_manager import ConfigManager
from core.runtime.app_cache import AppCache
from core.runtime.excel_cache import (
    derive_excel_active,
    excel_set_active,
    excel_set_full,
)


async def parse_excel_to_cache(
    config_manager: ConfigManager,
    excel_path: str | Path,
    app_cache: AppCache,
    area_id: str,
    loader_factory: type[ExcelLoader] = ExcelLoader,
) -> DataExcelCache:
    """Parsea el Excel y lo escribe al ``AppCache`` del area.

    Escribe el cache completo via ``excel_set_full`` y rederiva el
    cache activo (filtrado por ``selected_plc``) via
    ``derive_excel_active`` + ``excel_set_active``. Si el area no
    esta registrada en ``app_cache``, ``excel_set_full`` lanza
    ``KeyError`` -- el caller debe haber registrado el area en boot
    (ver ``AreaSpec.contributes_caches``).

    Args:
        config_manager: ConfigManager del departamento activo (necesario
            para que los mini parsers resuelvan su SHEET/TABLE
            data-driven).
        excel_path: ruta al ``.xlsx`` a parsear.
        app_cache: contenedor del proceso.
        area_id: id del area (registrada en ``app_cache``).
        loader_factory: clase del loader (inyectable para tests).
            Default: ``ExcelLoader`` real.

    Returns:
        ``DataExcelCache`` ya escrito en ``app_cache.area(area_id).excel_full``.
    """
    loader = loader_factory(config_manager=config_manager)
    cache = await asyncio.to_thread(loader.load, excel_path)
    excel_set_full(app_cache, area_id, cache)
    derived = derive_excel_active(
        app_cache, area_id, app_cache.get_state().selected_plc,
    )
    if derived is not None:
        excel_set_active(app_cache, area_id, derived)
    return cache


__all__ = ["parse_excel_to_cache"]