"""Tests de la publicacion del preview de entidades en el AppCache.

El router ya no bloquea: encola el trabajo y responde ``202 {job_id}``.
El resultado llega al HMI por push, y el canal de datos es el AppCache:
el FB publica el preview de entidades cuando termina (``on_finish``).

Si el FB no publica, la SPA se queda con el preview viejo aunque el
preview se haya recalculado.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from areas.alimentacion.functions.function_entidades_generar_preview import (
    FunctionEntidadesGenerarPreview,
)
from areas.alimentacion.state.area_cache import AlimentacionAreaCache


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset del Singleton ``get_app_cache()`` antes y despues del test."""
    import core.runtime.app_cache as _mod
    _mod._app_cache = None
    yield
    _mod._app_cache = None


def _make_ctx() -> Any:
    """Ctx del FB con el result final ya compuesto."""
    ctx = MagicMock()
    ctx.plc_name = "ZC_PLC_STD"
    ctx.result = {
        "precondiciones_ok": True,
        "missing_blocks":    [],
        "db_name":           "DB6_ENT",
        "db_array_name":     "ENT",
        "tag_table":         "6_Entidades",
        "config_table":      "0_Config_Generales",
        "summary":           {"constants_agregados": 2,
                              "comments_added": 1,
                              "comments_updated": 3},
        "warnings":          [],
    }
    return ctx


def _make_fb(app_cache) -> FunctionEntidadesGenerarPreview:
    return FunctionEntidadesGenerarPreview(
        nombre="entidades_generar_preview_test",
        config_manager=MagicMock(),
        tia_client=MagicMock(),
        app_cache=app_cache,
    )


def _app_cache_con_area():
    from core.runtime.app_cache import get_app_cache
    cache = get_app_cache()
    cache.register_area("alimentacion", AlimentacionAreaCache())
    return cache


def test_on_finish_publica_el_preview_de_entidades() -> None:
    cache = _app_cache_con_area()
    fb = _make_fb(cache)
    fb._ctx = _make_ctx()

    fb.on_finish()

    area = cache.area("alimentacion")
    assert area.preview_disp is not None
    assert area.preview_disp["precondiciones_ok"] is True
    assert area.preview_disp["db_name"] == "DB6_ENT"


def test_on_finish_publica_exactamente_el_result_del_fb() -> None:
    cache = _app_cache_con_area()
    fb = _make_fb(cache)
    ctx = _make_ctx()
    fb._ctx = ctx

    fb.on_finish()

    assert fb.result == ctx.result
    area = cache.area("alimentacion")
    assert area.preview_disp == ctx.result


def test_on_finish_sin_ctx_no_publica_nada() -> None:
    """Sin ctx (FB que no llego a ejecutar) no hay nada que publicar."""
    cache = _app_cache_con_area()
    fb = _make_fb(cache)
    fb._ctx = None

    fb.on_finish()

    area = cache.area("alimentacion")
    assert area.preview_disp is None
    assert fb.result["precondiciones_ok"] is False
