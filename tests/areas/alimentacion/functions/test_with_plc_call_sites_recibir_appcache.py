"""Regression: los 6 FBs de sync/preview deben pasar ``AppCache`` a ``with_plc``.

Contrato que fija este test (commit 4a, feature/app-cache-unico):

  ``with_plc(app_cache: AppCache, plc_name: str, area_id: str)``
  espera que el primer argumento sea un ``AppCache`` (con ``.get_state()``
  y ``.mutate()``).

Los 6 FBs tienen ``self._state: AppState`` y DEBEN llamar a
``with_plc(self._state.app_cache, ...)`` — no ``with_plc(self._state, ...)``.
``AppState`` no expone ``get_state()``; pasar ``self._state`` lanzaba
``AttributeError`` en produccion al disparar sync/preview.

Los tests existentes mockean ``with_plc`` y no detectaban el bug. Este
test NO mockea ``with_plc``: lo deja pasar al real para que ``self._state``
sea del tipo equivocado y el bug, si vuelve, explote.

Falsos positivos que este test evita:
  - ``validate_plc_in_tia`` y ``validate_plc_in_excel`` se mockean (no-op)
    porque sus dependencias no son objetivo de este test.
  - El ``on_start`` solo llega hasta crear el ctx, no ejecuta los 11 steps.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType
from unittest.mock import MagicMock, patch

import pytest

from areas.alimentacion.data.data_dimensiones import DimensionesPLC
from areas.alimentacion.data.data_plc import DataPLC
from areas.alimentacion.state.area_cache import AlimentacionAreaCache
from core.data.data_excel_cache import DataExcelCache
from core.runtime.app_cache import AppCache
from core.runtime.excel_cache import excel_set_full


_FB_PARAMS = [
    (
        "areas.alimentacion.functions.function_disp_sincronizar.FunctionDispSincronizar",
        "areas.alimentacion.functions.function_disp_sincronizar.with_plc",
        "areas.alimentacion.functions.function_disp_sincronizar.validate_plc_in_tia",
        "areas.alimentacion.functions.function_disp_sincronizar.validate_plc_in_excel",
        {},
    ),
    (
        "areas.alimentacion.functions.function_disp_generar_preview.FunctionDispGenerarPreview",
        "areas.alimentacion.functions.function_disp_generar_preview.with_plc",
        "areas.alimentacion.functions.function_disp_generar_preview.validate_plc_in_tia",
        "areas.alimentacion.functions.function_disp_generar_preview.validate_plc_in_excel",
        {},
    ),
    (
        "areas.alimentacion.functions.function_proc_db_sincronizar.FunctionProcDBSincronizar",
        "areas.alimentacion.functions.function_proc_db_sincronizar.with_plc",
        "areas.alimentacion.functions.function_proc_db_sincronizar.validate_plc_in_tia",
        "areas.alimentacion.functions.function_proc_db_sincronizar.validate_plc_in_excel",
        {"proc_uid": 300},
    ),
    (
        "areas.alimentacion.functions.function_proc_db_generar_preview.FunctionProcDBGenerarPreview",
        "areas.alimentacion.functions.function_proc_db_generar_preview.with_plc",
        "areas.alimentacion.functions.function_proc_db_generar_preview.validate_plc_in_tia",
        "areas.alimentacion.functions.function_proc_db_generar_preview.validate_plc_in_excel",
        {"proc_uid": 300},
    ),
    (
        "areas.alimentacion.functions.function_entidades_sincronizar.FunctionEntidadesSincronizar",
        "areas.alimentacion.functions.function_entidades_sincronizar.with_plc",
        "areas.alimentacion.functions.function_entidades_sincronizar.validate_plc_in_tia",
        "areas.alimentacion.functions.function_entidades_sincronizar.validate_plc_in_excel",
        {},
    ),
    (
        "areas.alimentacion.functions.function_entidades_generar_preview.FunctionEntidadesGenerarPreview",
        "areas.alimentacion.functions.function_entidades_generar_preview.with_plc",
        "areas.alimentacion.functions.function_entidades_generar_preview.validate_plc_in_tia",
        "areas.alimentacion.functions.function_entidades_generar_preview.validate_plc_in_excel",
        {},
    ),
]


def _make_excel_cache_with_plc(plc_name: str) -> DataExcelCache:
    """DataExcelCache con un PLC concreto en ``Tabla_PLC``."""
    return DataExcelCache(
        excel_path="/x.xlsx",
        excel_mtime_ns=1,
        parsed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        dispositivos={"ed": (), "ea": ()},
        n_max=DimensionesPLC(),
        plcs=(DataPLC(uid=1, plc=plc_name),),
        procesos=(),
        parametros_real=(),
        parametros_int=(),
        alarmas=(),
        entidades=(),
        procesos_by_codigo=MappingProxyType({}),
        parametros_real_by_codigo=MappingProxyType({}),
        parametros_int_by_codigo=MappingProxyType({}),
    )


@pytest.fixture
def app_cache() -> AppCache:
    """AppCache real con el area ``alimentacion`` registrada."""
    cache = AppCache()
    cache.register_area("alimentacion", AlimentacionAreaCache())
    return cache


@pytest.fixture
def app_state(app_cache: AppCache):
    """AppState real con un Excel cargado en el area ``alimentacion``.

    Devolvemos un ``MagicMock`` que expone ``.app_cache`` con el real:
    asi el FB ve un AppState de verdad (no MagicMock) pero evitamos
    contaminar el singleton global.
    """
    excel_set_full(app_cache, "alimentacion", _make_excel_cache_with_plc("S7-1500"))
    state = MagicMock()
    state.app_cache = app_cache
    return state


@pytest.mark.parametrize(
    ("fb_path", "with_plc_path", "validate_tia_path", "validate_excel_path", "extra_params"),
    _FB_PARAMS,
    ids=[
        "FunctionDispSincronizar",
        "FunctionDispGenerarPreview",
        "FunctionProcDBSincronizar",
        "FunctionProcDBGenerarPreview",
        "FunctionEntidadesSincronizar",
        "FunctionEntidadesGenerarPreview",
    ],
)
def test_on_start_pasa_appcache_a_with_plc(
    app_state,
    fb_path: str,
    with_plc_path: str,
    validate_tia_path: str,
    validate_excel_path: str,
    extra_params: dict,
) -> None:
    """El FB no debe lanzar ``AttributeError`` cuando ``with_plc`` es REAL.

    Si un FB pasa ``self._state`` (AppState) en vez de ``self._state.app_cache``
    (AppCache), el primer acceso dentro de ``with_plc`` (``app_cache.get_state()``)
    falla con ``AttributeError: 'AppState' object has no attribute 'get_state'``.
    """
    import importlib

    module_path, class_name = fb_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    fb_cls = getattr(module, class_name)

    fb = fb_cls(
        nombre="regression_test",
        config_manager=MagicMock(),
        tia_client=MagicMock(),
        app_state=app_state,
    )

    with patch(validate_tia_path), patch(validate_excel_path):
        # ``with_plc`` NO se mockea. Si el FB le pasa el tipo incorrecto,
        # el real ``with_plc`` lanza ``AttributeError`` y el test falla.
        fb.on_start(plc_name="S7-1500", **extra_params)

    assert fb._plc_name == "S7-1500"


def test_with_plc_real_ejecuta_sin_error(app_cache: AppCache) -> None:
    """Smoke test del helper ``with_plc`` con un AppCache real.

    Confirma que la firma ``with_plc(app_cache, plc_name, area_id)`` funciona
    con el AppCache real (no MagicMock). Si este test pasa y los
    6 tests parametrizados fallan con el bug reintroducido, sabemos
    que el problema es de wiring del FB (pasa ``self._state`` en vez
    de ``self._state.app_cache``).
    """
    from core.helpers.tia.with_plc import with_plc

    excel_set_full(app_cache, "alimentacion", _make_excel_cache_with_plc("S7-1500"))

    # No debe lanzar.
    with_plc(app_cache, "S7-1500", "alimentacion")

    assert app_cache.get_state().selected_plc == "S7-1500"