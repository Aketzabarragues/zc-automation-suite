"""Helpers puros de la carga del Excel corporativo (FB subir_excel).

Extraido del use case legacy ``application/use_cases/upload_excel.py`` para que el FB ``FunctionExcelCargar``
quede con la state machine sola y delegue la logica aqui.

Funciones puras (sin estado, sin tracker, sin AppState):
  - ``parse_excel_to_cache``: lee el ``.xlsx`` y guarda el resultado
    en el ``ExcelCacheManager`` global.
  - ``dump_cache_to_state``: volca el cache al ``AppState`` y devuelve
    el ``summary`` con la shape legacy.

El FB orquesta las 2 funciones en 2 steps (``parsear_excel`` /
``volcar_appstate``) y emite los progress events via el ``tracker``.
"""
from __future__ import annotations

import asyncio
from typing import Any

from areas.alimentacion.data.data_excel_cache import DataExcelCache
from areas.alimentacion.helpers.excel.excel_cache_manager import (
    ExcelCacheManager,
)
from areas.alimentacion.helpers.excel.excel_loader import ExcelLoader
from core.infrastructure.config.config_manager import ConfigManager
from core.runtime.app_state import AppState


async def parse_excel_to_cache(
    config_manager: ConfigManager,
    excel_path: str | Path,
    cache_cls: type[ExcelCacheManager] = ExcelCacheManager,
    loader_factory: type[ExcelLoader] = ExcelLoader,
) -> DataExcelCache:
    """Parsea el Excel en thread y guarda el resultado en el cache global.

    Args:
        config_manager: ConfigManager del departamento activo (necesario
            para que los mini parsers resuelvan su SHEET/TABLE
            data-driven).
        excel_path: ruta al ``.xlsx`` a parsear.
        cache_cls: clase del cache manager (inyectable para tests).
            Default: ``ExcelCacheManager`` real.
        loader_factory: clase del loader (inyectable para tests).
            Default: ``ExcelLoader`` real.

    Returns:
        ``DataExcelCache`` ya cacheado en ``ExcelCacheManager.put``.
    """
    loader = loader_factory(config_manager=config_manager)
    cache = await asyncio.to_thread(loader.load, excel_path)
    await cache_cls.put(cache)
    return cache


def dump_cache_to_state(
    cache: DataExcelCache,
    app_state: AppState,
    config_manager: ConfigManager,
) -> dict[str, Any]:
    """Volca el cache al ``AppState`` y devuelve el ``summary`` legacy.

    Args:
        cache: ``DataExcelCache`` parseado.
        app_state: estado de la app (Singleton global).
        config_manager: ConfigManager del departamento (para derivar
            el ``summary`` con claves canonicas).

    Returns:
        ``dict`` con la shape::

            {
                "ok": True,
                "summary": {"DispED": N, "DispEA": M, ...},
                "total_dispositivos": int,
                "dimensiones": <api_dict de n_max>,
            }
    """
    # Back-compat con la SPA: poblar ``state.dispositivos_<hw>`` desde
    # ``cache.dispositivos`` (la SPA espera ``list``, no ``tuple``).
    # NOTA: esto se eliminara cuando los FB y routers dejen de usar
    # ``state.get_devices(hw)`` y pasen a ``state.excel_cache_active``.
    for hw, devices_tuple in cache.dispositivos.items():
        app_state.set_devices(hw, list(devices_tuple))
    app_state.dimensiones = cache.n_max

    # Cache COMPLETO (datos UI / "definicion programacion"). Siempre
    # sin filtrar; lo consume el endpoint ``/api/v1/state/dispositivos``
    # para mostrar TODO el Excel al operario.
    app_state.excel_cache_full = cache
    # Cache FILTRADO por selected_plc (datos que consumen los FB). Si
    # selected_plc == "" es identico al completo. Se regenera tambien
    # en cada ``with_plc()`` cuando cambia la seleccion.
    from core.runtime.filter_excel_cache import filter_cache_by_plc
    # ``getattr(..., "")`` defensivo: tests con MagicMock(spec=AppState)
    # no exponen ``selected_plc`` (es atributo de instancia, no de clase).
    selected_plc = getattr(app_state, "selected_plc", "")
    app_state.excel_cache_active = filter_cache_by_plc(cache, selected_plc)

    # ``cache.plcs`` es la lista INFORMATIVA de PLCs del Excel (hoja
    # CONFIG, Tabla_PLC). NO se vuelca a ``app_state.plcs``: la fuente
    # de verdad para la selección de PLC es TIA Portal (``list_plcs``
    # vía /api/v1/tia/connection), que la SPA ya consume directamente.
    # Mantener ``app_state.plcs`` poblado desde el Excel contaminaba
    # el backend con una lista que nadie leía (código muerto).
    # El cache vive en el area de alimentacion, pero AppState lo expone
    # como placeholder ``Any`` (ver ``state.py``).
    app_state.excel_cache = cache
    app_state.excel_path = cache.excel_path

    # Summary con la shape legacy: ``{tipo_canonica: count}``.
    # Derivamos las claves canonicas desde el config_manager
    # (el cache no expone directamente ``DispED``, ``DispEA``, ...).
    summary: dict[str, int] = {}
    for hw in config_manager.list_hw_types_active():
        target = config_manager.get_excel_target_for(hw)
        if target is None:
            continue
        canonica = target.get("canonical", "")
        if not canonica:
            continue
        devices_tuple = cache.dispositivos.get(hw, ())
        summary[canonica] = len(devices_tuple)

    return {
        "ok": True,
        "summary": summary,
        "total_dispositivos": sum(summary.values()),
        # ``to_api_dict()`` en vez de ``dataclasses.asdict``: oculta
        # el campo ``extras`` (interno / futuro) de la respuesta.
        "dimensiones": cache.n_max.to_api_dict(),
    }


__all__ = ["parse_excel_to_cache", "dump_cache_to_state"]
