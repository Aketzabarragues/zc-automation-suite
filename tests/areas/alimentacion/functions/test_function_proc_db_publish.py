"""Tests de la publicacion del resultado de los FBs de sync de procesos.

El router ya no bloquea: encola el trabajo y responde ``202 {job_id}``.
El resultado llega al HMI por push, y el canal de datos es el AppCache:
el FB publica el preview (FB de preview) y el resumen del commit +
el preview post-sync (FB de commit) cuando termina (``on_finish``).

Si el FB no publica, la SPA se queda con el preview viejo aunque el
sync haya funcionado.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from areas.alimentacion.functions.function_proc_db_generar_preview import (
    FunctionProcDBGenerarPreview,
)
from areas.alimentacion.functions.function_proc_db_sincronizar import (
    FunctionProcDBSincronizar,
)
from areas.alimentacion.state.area_cache import AlimentacionAreaCache


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset del Singleton ``get_app_cache()`` antes y despues del test."""
    import core.runtime.app_cache as _mod
    _mod._app_cache = None
    yield
    _mod._app_cache = None


def _app_cache_con_area():
    from core.runtime.app_cache import get_app_cache
    cache = get_app_cache()
    cache.register_area("alimentacion", AlimentacionAreaCache())
    return cache


def _make_preview_ctx() -> Any:
    """Ctx del FB de preview con el result final ya relleno."""
    ctx = MagicMock()
    ctx.plc_name = "ZC_PLC_STD"
    ctx.proc_uid = 100
    ctx.result = {
        "proc_uid": 100,
        "proc_codigo": "CPR",
        "precondiciones_ok": True,
        "missing_blocks": [],
        "db_param_name": "DB100_CPR_PARAM",
        "db_alm_name": "DB100_CPR_ALM",
        "table_name": "100_CPR",
        "arrays": {"agregados": ["DB100_S1"]},
        "summary": {"total": 1, "agregados": 1, "renombrados": 0,
                    "eliminados": 0, "sin_cambios": 0},
        "nmax": {"summary": {"actualizar": 2}},
        "warnings": [],
    }
    return ctx


def _make_sync_ctx() -> Any:
    """Ctx del FB de commit con el result final ya relleno."""
    ctx = MagicMock()
    ctx.plc_name = "ZC_PLC_STD"
    ctx.proc_uid = 100
    ctx.result = {
        "proc_uid": 100,
        "plc_name": "ZC_PLC_STD",
        "success": True,
        "applied": True,
        "operations_executed": 4,
        "details": [{"step": 1}],
        "warnings": [],
        "post_sync_preview": {
            "proc_uid": 100,
            "summary": {"agregados": 0, "renombrados": 0, "eliminados": 0},
        },
    }
    return ctx


def _make_preview_fb(app_cache) -> FunctionProcDBGenerarPreview:
    return FunctionProcDBGenerarPreview(
        nombre="proc_db_generar_preview_test",
        config_manager=MagicMock(),
        tia_client=MagicMock(),
        app_cache=app_cache,
    )


def _make_sync_fb(app_cache) -> FunctionProcDBSincronizar:
    return FunctionProcDBSincronizar(
        nombre="proc_db_sincronizar_test",
        config_manager=MagicMock(),
        tia_client=MagicMock(),
        app_cache=app_cache,
    )


# ---------------------------------------------------------------------------
# FB de preview: publica el slot preview_proc
# ---------------------------------------------------------------------------


def test_preview_on_finish_publica_el_preview_en_el_appcache() -> None:
    cache = _app_cache_con_area()
    fb = _make_preview_fb(cache)
    ctx = _make_preview_ctx()
    fb._ctx = ctx

    fb.on_finish()

    area = cache.area("alimentacion")
    assert area.preview_proc == ctx.result


def test_preview_on_finish_sin_ctx_no_publica_nada() -> None:
    """Sin ctx (FB que no llego a ejecutar) no hay nada que publicar."""
    cache = _app_cache_con_area()
    fb = _make_preview_fb(cache)
    fb._ctx = None

    fb.on_finish()

    area = cache.area("alimentacion")
    assert area.preview_proc is None
    assert fb.result["precondiciones_ok"] is False


# ---------------------------------------------------------------------------
# FB de commit: publica last_proc_commit_summary + preview_proc
# ---------------------------------------------------------------------------


def test_commit_on_finish_publica_el_resumen_del_commit() -> None:
    cache = _app_cache_con_area()
    fb = _make_sync_fb(cache)
    ctx = _make_sync_ctx()
    fb._ctx = ctx

    fb.on_finish()

    area = cache.area("alimentacion")
    assert area.last_proc_commit_summary == ctx.result
    assert area.last_proc_commit_summary["operations_executed"] == 4
    assert area.last_sync_proc_at is not None


def test_commit_on_finish_publica_el_preview_post_sync() -> None:
    cache = _app_cache_con_area()
    fb = _make_sync_fb(cache)
    ctx = _make_sync_ctx()
    fb._ctx = ctx

    fb.on_finish()

    area = cache.area("alimentacion")
    assert area.preview_proc == ctx.result["post_sync_preview"]


def test_commit_on_finish_no_publica_preview_si_el_sync_no_lo_trajo() -> None:
    cache = _app_cache_con_area()
    fb = _make_sync_fb(cache)
    ctx = _make_sync_ctx()
    ctx.result["post_sync_preview"] = None
    fb._ctx = ctx

    fb.on_finish()

    area = cache.area("alimentacion")
    assert area.preview_proc is None
    # El resumen si se publica: el commit se hizo.
    assert area.last_proc_commit_summary is not None


def test_commit_on_finish_sin_ctx_no_publica_nada() -> None:
    """Sin ctx (FB que no llego a ejecutar) no hay nada que publicar."""
    cache = _app_cache_con_area()
    fb = _make_sync_fb(cache)
    fb._ctx = None

    fb.on_finish()

    area = cache.area("alimentacion")
    assert area.last_proc_commit_summary is None
    assert area.preview_proc is None
    assert fb.result["success"] is False
