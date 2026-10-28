"""Tests de la publicacion del resultado del FB de preview de dispositivos.

El router ya no bloquea: encola el trabajo y responde ``202 {job_id}``.
El resultado llega al HMI por push, y el canal de datos es el AppCache:
el FB publica el preview en el slot ``preview_disp`` cuando termina
(``on_finish``).

Si el FB no publica, la SPA se queda con el preview viejo aunque el
preview se haya recalculado.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from areas.alimentacion.functions.function_disp_generar_preview import (
    DispPreviewContext,
    FunctionDispGenerarPreview,
)
from areas.alimentacion.state.area_cache import AlimentacionAreaCache


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset del Singleton ``get_app_cache()`` antes y despues del test."""
    import core.runtime.app_cache as _mod
    _mod._app_cache = None
    yield
    _mod._app_cache = None


def _make_ctx() -> DispPreviewContext:
    """Ctx del FB con el resultado final ya relleno."""
    ctx = DispPreviewContext(
        plc_name="ZC_PLC_STD",
        tia_client=MagicMock(),
        config_manager=MagicMock(),
        app_cache=MagicMock(),
        build_cache_root=Path("."),
    )
    ctx.result = {
        "agregados": [{"uid": "1", "table": "2000_Disp_ED"}],
        "eliminados": [],
        "renombrados": [],
        "todos": [{"table": "2000_Disp_ED", "status": "agregar"}],
        "nmax": {
            "current": {},
            "desired": {},
            "todos": [],
            "summary": {"actualizar": 2, "sin_cambios": 3, "total": 5},
        },
        "summary": {
            "agregados": 1, "eliminados": 0, "renombrados": 0,
            "sin_cambios": 0, "total": 1,
        },
    }
    return ctx


def _make_fb(app_cache) -> FunctionDispGenerarPreview:
    return FunctionDispGenerarPreview(
        nombre="disp_generar_preview_test",
        config_manager=MagicMock(),
        tia_client=MagicMock(),
        app_cache=app_cache,
    )


def _app_cache_con_area():
    from core.runtime.app_cache import get_app_cache
    cache = get_app_cache()
    cache.register_area("alimentacion", AlimentacionAreaCache())
    return cache


def test_on_finish_publica_el_preview_en_el_appcache() -> None:
    cache = _app_cache_con_area()
    fb = _make_fb(cache)
    fb._ctx = _make_ctx()

    fb.on_finish()

    area = cache.area("alimentacion")
    assert area.preview_disp is not None
    assert area.preview_disp["summary"]["agregados"] == 1
    assert area.preview_disp["nmax"]["summary"]["actualizar"] == 2


def test_on_finish_deja_el_result_legacy_en_el_fb() -> None:
    cache = _app_cache_con_area()
    fb = _make_fb(cache)
    ctx = _make_ctx()
    fb._ctx = ctx

    fb.on_finish()

    assert fb.result == ctx.result


def test_on_finish_sin_ctx_no_publica_nada() -> None:
    """Sin ctx (FB que no llego a ejecutar) no hay nada que publicar."""
    cache = _app_cache_con_area()
    fb = _make_fb(cache)
    fb._ctx = None

    fb.on_finish()

    area = cache.area("alimentacion")
    assert area.preview_disp is None
    # El result de error temprano mantiene la shape legacy vacia.
    assert fb.result["agregados"] == []
    assert fb.result["summary"]["total"] == 0


def test_publicar_preview_con_area_no_registrada_no_revienta() -> None:
    """Si el area no esta en el AppCache, el setter no-op (no KeyError)."""
    from core.runtime.app_cache import get_app_cache

    cache = get_app_cache()  # sin ``register_area("alimentacion")``
    fb = _make_fb(cache)
    fb._ctx = _make_ctx()

    fb.on_finish()

    assert fb.result["summary"]["agregados"] == 1
