"""Tests del use case ``DispComentariosSyncUseCase``.

Mockea el gateway con ``AsyncMock``. La ``AppState`` y ``ConfigManager``
se sustituyen por ``MagicMock`` simples. Sigue el patrón de
``tests/test_sync_dispositivos_instances.py``.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from areas.alimentacion.application.use_cases.disp_sync_comentarios import (
    DispComentariosSyncUseCase,
)
from core.application.progress_buffer import ProgressTracker


# ── Helpers ──────────────────────────────────────────────────────────────


class _FakeDevice:
    def __init__(self, numero: int, comentario_db: str = "") -> None:
        self.numero = numero
        self.comentario_db = comentario_db


@pytest.fixture
def progress() -> ProgressTracker:
    """Tracker fresco (no el singleton global)."""
    return ProgressTracker()


@pytest.fixture
def config_manager() -> MagicMock:
    cm = MagicMock()
    cm.list_hw_types_active.return_value = ["ed", "ea", "sa", "v", "m", "m_vf"]
    cm.get_tia_folder_dispositivos.return_value = "2000_Dispositivos"
    # get_dispositivo_config devuelve un objeto con db_name y db_array_name.
    def _get_cfg(hw: str) -> MagicMock:
        return MagicMock(
            db_name=f"DB20{ord(hw[0]):02d}_{hw.upper()}",
            db_array_name=hw.upper(),
        )
    cm.get_dispositivo_config.side_effect = _get_cfg
    return cm


@pytest.fixture
def app_state() -> MagicMock:
    state = MagicMock()
    # all_devices() devuelve lista no vacía (simula Excel cargado).
    state.all_devices.return_value = [_FakeDevice(1, "X")]

    # get_devices(hw) → mapeo por tipo.
    devices_by_hw: dict[str, list[_FakeDevice]] = {
        "ed":   [_FakeDevice(1, "Bomba 1"), _FakeDevice(2, "Bomba 2")],
        "ea":   [_FakeDevice(1, "Sensor 1")],
        "sa":   [],
        "v":    [_FakeDevice(1, "")],
        "m":    [],
        "m_vf": [],
    }
    state.get_devices.side_effect = lambda hw: devices_by_hw.get(hw, [])
    return state


@pytest.fixture
def gateway() -> MagicMock:
    g = MagicMock()
    g.update_disp_instance_comments_batch = AsyncMock(
        return_value={
            "success": True,
            "operations_executed": 6,
            "details": [
                {"step": 1, "command": "update_disp_comments_db_ed",
                 "result": {"hw_type": "ed", "modified": True}},
            ],
        }
    )
    return g


@pytest.fixture
def use_case(
    gateway: MagicMock,
    config_manager: MagicMock,
    app_state: MagicMock,
    progress: ProgressTracker,
) -> DispComentariosSyncUseCase:
    return DispComentariosSyncUseCase(
        gateway=gateway,
        config_manager=config_manager,
        app_state=app_state,
        progress=progress,
    )


# ── apply_comentarios_disp ──────────────────────────────────────────────


def test_apply_llama_gateway_con_slot_maps_completos(
    use_case: DispComentariosSyncUseCase,
    gateway: MagicMock,
) -> None:
    """El use case pasa al gateway slot_maps, db_names, db_array_names y target_folder."""
    import asyncio

    asyncio.run(use_case.apply_comentarios_disp("PLC_X"))

    gateway.update_disp_instance_comments_batch.assert_called_once()
    call_kwargs = gateway.update_disp_instance_comments_batch.call_args.kwargs
    assert call_kwargs["plc_name"] == "PLC_X"
    assert call_kwargs["target_folder"] == "2000_Dispositivos"
    # 6 tipos activos → 6 entradas en cada dict.
    assert len(call_kwargs["dispositivos_slot_maps"]) == 6
    assert len(call_kwargs["db_names"]) == 6
    assert len(call_kwargs["db_array_names"]) == 6
    # Slot 0 siempre "NO USAR".
    for hw, smap in call_kwargs["dispositivos_slot_maps"].items():
        assert smap[0] == "NO USAR"
    # Slot 1 del tipo "ed" debe ser "Bomba 1".
    assert call_kwargs["dispositivos_slot_maps"]["ed"][1] == "Bomba 1"


def test_apply_warning_si_app_state_vacio(
    gateway: MagicMock,
    config_manager: MagicMock,
    progress: ProgressTracker,
) -> None:
    """AppState vacío → no se invoca gateway, warning accionable."""
    import asyncio

    state = MagicMock()
    state.all_devices.return_value = []
    state.get_devices.return_value = []

    use_case = DispComentariosSyncUseCase(
        gateway=gateway,
        config_manager=config_manager,
        app_state=state,
        progress=progress,
    )

    result = asyncio.run(use_case.apply_comentarios_disp("PLC_X"))
    assert result["operations_executed"] == 0
    assert any("AppState" in w for w in result["warnings"])
    gateway.update_disp_instance_comments_batch.assert_not_called()


def test_apply_finish_success_false_en_error(
    use_case: DispComentariosSyncUseCase,
    gateway: MagicMock,
    progress: ProgressTracker,
) -> None:
    """Si el gateway lanza, progress.finish(success=False) se llama."""
    import asyncio

    gateway.update_disp_instance_comments_batch.side_effect = RuntimeError(
        "Boom"
    )
    with pytest.raises(RuntimeError, match="Boom"):
        asyncio.run(use_case.apply_comentarios_disp("PLC_X"))
    snap = progress.snapshot()
    assert snap.active is False
    assert snap.error == "Boom"


def test_apply_stage_open_transaction_es_opaco(
    use_case: DispComentariosSyncUseCase,
    progress: ProgressTracker,
) -> None:
    """El stage 'open_transaction' está en el snapshot y se ejecuta."""
    import asyncio

    asyncio.run(use_case.apply_comentarios_disp("PLC_X"))
    snap = progress.snapshot()
    stage_ids = [s["id"] for s in snap.stages]
    assert stage_ids == ["read_state", "build_slot_maps", "open_transaction", "done"]
    # El stage open_transaction debe estar 'done' (no 'pending' ni 'running').
    txn_stage = next(s for s in snap.stages if s["id"] == "open_transaction")
    assert txn_stage["status"] == "done"


# ── preview_comentarios_disp ────────────────────────────────────────────


def test_preview_no_toca_tia(
    use_case: DispComentariosSyncUseCase,
    gateway: MagicMock,
) -> None:
    """El preview NO invoca el gateway (no toca TIA)."""
    import asyncio

    result = asyncio.run(use_case.preview_comentarios_disp("PLC_X"))
    gateway.update_disp_instance_comments_batch.assert_not_called()
    assert result["plc_name"] == "PLC_X"
    assert "dispositivos_slot_maps" in result


def test_preview_warning_si_app_state_vacio(
    gateway: MagicMock,
    config_manager: MagicMock,
    progress: ProgressTracker,
) -> None:
    """AppState vacío → warning en preview, no toca TIA."""
    import asyncio

    state = MagicMock()
    state.all_devices.return_value = []
    state.get_devices.return_value = []
    use_case = DispComentariosSyncUseCase(
        gateway=gateway, config_manager=config_manager,
        app_state=state, progress=progress,
    )
    result = asyncio.run(use_case.preview_comentarios_disp("PLC_X"))
    assert result["has_changes"] is False
    assert result["dispositivos_slot_maps"] == {}
    assert any("AppState" in w for w in result["warnings"])


# ── La lógica de disp_build_slot_map_for_hw vive ahora en disp_slot_map_builder. ──
# Ver tests/test_slot_map_builder.py.
