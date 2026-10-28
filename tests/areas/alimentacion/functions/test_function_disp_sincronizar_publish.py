"""Tests de la publicacion del resultado del FB de sync de dispositivos.

El router ya no bloquea: encola el trabajo y responde ``202 {job_id}``.
El resultado llega al HMI por push, y el canal de datos es el AppCache:
el FB publica el resumen del commit y el preview post-sync cuando
termina (``on_finish``).

Si el FB no publica, la SPA se queda con el preview viejo aunque el
sync haya funcionado.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from areas.alimentacion.functions.function_disp_sincronizar import (
    FunctionDispSincronizar,
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
    """Ctx del FB con los resultados finales ya rellenos."""
    ctx = MagicMock()
    ctx.plc_name = "ZC_PLC_STD"
    ctx.nmax_result = {"operations_executed": 2, "details": [{"step": 1}]}
    ctx.devices_result = {"operations_executed": 3, "details": [{"step": 2}]}
    ctx.nmax_ops = [{"command": "update_user_constant_value"}]
    ctx.post_sync_preview = {"tabla": {"faltan": 0, "sobran": 0}}
    ctx.compile_ok = True
    ctx.compile_error = None
    ctx.comments_result = {"updated": 2}
    return ctx


def _make_fb(app_cache) -> FunctionDispSincronizar:
    return FunctionDispSincronizar(
        nombre="disp_sincronizar_test",
        config_manager=MagicMock(),
        tia_client=MagicMock(),
        app_cache=app_cache,
    )


def _app_cache_con_area():
    from core.runtime.app_cache import get_app_cache
    cache = get_app_cache()
    cache.register_area("alimentacion", AlimentacionAreaCache())
    return cache


def test_on_finish_publica_el_resumen_del_commit() -> None:
    cache = _app_cache_con_area()
    fb = _make_fb(cache)
    fb._ctx = _make_ctx()

    fb.on_finish()

    area = cache.area("alimentacion")
    summary = area.last_disp_commit_summary
    assert summary is not None
    assert summary["operations"] == 5  # 2 N_MAX + 3 devices
    assert summary["n_max_updates"] == 1
    assert summary["success"] is True
    assert area.last_sync_disp_at is not None


def test_on_finish_publica_el_preview_post_sync() -> None:
    cache = _app_cache_con_area()
    fb = _make_fb(cache)
    fb._ctx = _make_ctx()

    fb.on_finish()

    area = cache.area("alimentacion")
    assert area.preview_disp == {"tabla": {"faltan": 0, "sobran": 0}}


def test_on_finish_no_publica_preview_si_el_sync_no_lo_trajo() -> None:
    cache = _app_cache_con_area()
    fb = _make_fb(cache)
    ctx = _make_ctx()
    ctx.post_sync_preview = None
    fb._ctx = ctx

    fb.on_finish()

    area = cache.area("alimentacion")
    assert area.preview_disp is None
    # El resumen si se publica: el commit se hizo.
    assert area.last_disp_commit_summary is not None


def test_on_finish_sin_ctx_no_publica_nada() -> None:
    """Sin ctx (FB que no llego a ejecutar) no hay nada que publicar."""
    cache = _app_cache_con_area()
    fb = _make_fb(cache)
    fb._ctx = None

    fb.on_finish()

    area = cache.area("alimentacion")
    assert area.last_disp_commit_summary is None
    assert area.preview_disp is None
    assert fb.result["success"] is False
