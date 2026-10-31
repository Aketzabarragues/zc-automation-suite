"""Tests de los contadores del sync de dispositivos.

El worker TIA responde al ``execute_transactional_batch`` con el envelope
``{"ok": True, "result": {"success": True, "operations_executed": N,
"details": [...]}}``. Los contadores viven en ``result``, no en el nivel
superior.

Si el FB guarda el envelope entero, los contadores del resumen y del
``result`` salen a 0: el operario ve "0 ops" tras un sync que ha escrito
116 tags y borrado 83.

Los tests de aqui pasan por los stages de verdad (no mockean el ctx con
el shape interior): si el shape del envelope cambia, fallan.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from areas.alimentacion.functions.function_disp_sincronizar import (
    FunctionDispSincronizar,
    _step_summary,
)

PLCN = "ZC_PLC_STD"


def _envelope(n_ops: int) -> dict:
    """Respuesta real del worker para un batch de ``n_ops`` operaciones."""
    return {
        "ok": True,
        "result": {
            "success": True,
            "operations_executed": n_ops,
            "details": [{"step": i + 1, "command": "op"} for i in range(n_ops)],
        },
    }


def _make_fb() -> FunctionDispSincronizar:
    fb = FunctionDispSincronizar(
        nombre="disp_sincronizar_test",
        config_manager=MagicMock(),
        tia_client=MagicMock(),
        app_cache=MagicMock(),
    )
    ctx = MagicMock()
    ctx.plc_name = PLCN
    ctx.tags_base = Path(".")
    ctx.build_cache_root = Path(".")
    ctx.nmax_ops = [
        {
            "table_name": "0_Config_Dispositivos",
            "constant_name": f"N_MAX_{i}",
            "new_value": i,
        }
        for i in range(10)
    ]
    ctx.rename_ops = [
        {
            "table_name": "2000_Disp_ED",
            "current_name": f"VIEJO_{i}",
            "new_name": f"NUEVO_{i}",
        }
        for i in range(3)
    ]
    ctx.device_changes = [
        {"table_name": f"2000_Disp_{i}", "adds": [], "removes": []}
        for i in range(11)
    ]
    ctx.tia_client.submit_and_wait.return_value = _envelope(13)
    fb._ctx = ctx
    return fb


def test_el_stage_4_guarda_el_result_del_batch() -> None:
    """Tx A guarda el ``result`` del batch, no el envelope."""
    fb = _make_fb()
    fb._stage_4_tx_a_nmax_renames()

    assert fb._ctx.nmax_result["operations_executed"] == 13
    assert len(fb._ctx.nmax_result["details"]) == 13


def test_el_stage_8_guarda_el_result_del_batch() -> None:
    """Tx B guarda el ``result`` del batch, no el envelope."""
    fb = _make_fb()
    fb._ctx.tia_client.submit_and_wait.return_value = _envelope(1)
    with patch(
        "areas.alimentacion.helpers.layout.build_cache.build_cache"
    ) as bc:
        bc.return_value.dispositivos.sync_variables_modified = Path("modified")
        fb._stage_8_tx_b_devices()

    assert fb._ctx.devices_result["operations_executed"] == 1
    assert len(fb._ctx.devices_result["details"]) == 1


def test_el_resumen_del_stage_4_distingue_nmax_de_renames() -> None:
    """El resumen dice cuantas ops se aplicaron y de que tipo eran."""
    fb = _make_fb()
    fb._stage_4_tx_a_nmax_renames()

    resumen = _step_summary(fb._ctx, "Aplicar N_MAX y renombres")

    assert "13 ops aplicadas en TIA" in resumen, resumen
    assert "10 N_MAX + 3 renames" in resumen, resumen


def test_el_resumen_del_stage_8_dice_las_tablas_importadas() -> None:
    """El resumen dice cuantas tablas se importaron a TIA."""
    fb = _make_fb()
    fb._ctx.tia_client.submit_and_wait.return_value = _envelope(1)
    with patch(
        "areas.alimentacion.helpers.layout.build_cache.build_cache"
    ) as bc:
        bc.return_value.dispositivos.sync_variables_modified = Path("modified")
        fb._stage_8_tx_b_devices()

    resumen = _step_summary(fb._ctx, "Aplicar dispositivos")

    assert "11 tablas importadas a TIA" in resumen, resumen


def test_el_result_reporta_las_ops_reales() -> None:
    """El ``result`` del FB lleva las operaciones que se aplicaron."""
    import core.runtime.app_cache as _mod

    _mod._app_cache = None
    try:
        fb = _make_fb()
        fb._stage_4_tx_a_nmax_renames()
        fb._ctx.tia_client.submit_and_wait.return_value = _envelope(1)
        with patch(
            "areas.alimentacion.helpers.layout.build_cache.build_cache"
        ) as bc:
            bc.return_value.dispositivos.sync_variables_modified = Path("modified")
            fb._stage_8_tx_b_devices()

        fb.on_finish()

        assert fb.result["operations"] == 14, fb.result["message"]
        assert "14 operacion(es) aplicadas en TIA" in fb.result["message"]
        assert "10 N_MAX" in fb.result["message"]
        assert "11 tablas de dispositivos" in fb.result["message"]
        assert len(fb.result["details"]) == 14
    finally:
        _mod._app_cache = None
