"""Tests del FB ``FunctionDiffConstants``.

Fase 2, paso 2.1.8.  Cubren:
  - Happy path: 3 ticks → nStep=99, ambos diffs calculados
    (``nmax_ops`` + ``rename_ops``), ``self.result`` con la shape
    completa y summary correcto.
  - Edge case: ambos estados vacíos → 0 ops, result con listas
    vacías y summary ``{nmax: 0, rename: 0, total: 0}``.
  - Edge case: solo N_MAX cambia, devices ya en sync → ``nmax_ops``
    poblado, ``rename_ops`` vacío.
  - Pre-flight: ``plc_name`` ausente → ``ValueError``.
  - Pre-flight: ``config_table_name`` ausente → ``ValueError``.
  - Pre-flight: cualquiera de los 4 estados ausente o no-dict → ``ValueError``.
  - Terminal: ticks extra sobre ``n_done`` son no-op.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from areas.alimentacion.functions.function_DiffConstants import (
    FunctionDiffConstants,
)
from areas.alimentacion.application.use_cases.disp_diff_constants import (
    DispCalculateConstantsDiffUseCase,
)


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def nmax_state_with_diff() -> dict[str, int]:
    """N_MAX: 2 cambios + 1 ya en valor deseado."""
    return {
        "N_MAX_DISP_ED": {"current": 25, "desired": 30, "changed": True},
        "N_MAX_DISP_EA": {"current": 10, "desired": 10, "changed": False},
        "N_MAX_DISP_SA": {"current": 8, "desired": 12, "changed": True},
    }


@pytest.fixture
def device_state_with_diff() -> dict[str, Any]:
    """Devices: 1 rename + 1 ya correcto + 1 nuevo (ignorado)."""
    return {
        "current": {"1": "V_001", "2": "V_002"},
        "desired": {"V_VA_101": 1, "V_VA_102": 2, "V_VA_103": 3},  # uid 3 no existe en TIA
        "renames": [("V_001", "V_VA_101")],  # uid 1 cambia
    }


def _make_fb_with_mock(nmax_ops, rename_ops) -> FunctionDiffConstants:
    """Helper: crea un FB con ``use_case_factory`` que retorna una
    clase mock con los métodos estáticos devolviendo los ops dados.
    """
    mock_cls = MagicMock()
    mock_cls.calculate_nmax_diff = MagicMock(return_value=nmax_ops)
    mock_cls.calculate_device_rename_diff = MagicMock(return_value=rename_ops)
    return FunctionDiffConstants(
        nombre="diff_constants_test",
        use_case_factory=lambda: mock_cls,
    )


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_diff_constants_happy_path_3_ticks() -> None:
    """Happy path: 3 ticks → nStep=99, ambos diffs calculados,
    ``self.result`` con la shape completa y summary correcto."""
    nmax_ops = [
        {"command": "update_user_constant_value",
         "args": {"plc_name": "S7-1500", "table_name": "N_MAX_DISP",
                  "constant_name": "N_MAX_DISP_ED", "new_value": 30}},
        {"command": "update_user_constant_value",
         "args": {"plc_name": "S7-1500", "table_name": "N_MAX_DISP",
                  "constant_name": "N_MAX_DISP_SA", "new_value": 12}},
    ]
    rename_ops = [
        {"command": "update_user_constant_name",
         "args": {"plc_name": "S7-1500", "table_name": "2000_Disp_ED",
                  "current_name": "V_001", "new_name": "V_VA_101"}},
    ]
    fb = _make_fb_with_mock(nmax_ops, rename_ops)

    ok = await fb.start(
        plc_name="S7-1500",
        config_table_name="2000_Disp_ED",
        current_nmax_state={"N_MAX_DISP_ED": 25, "N_MAX_DISP_SA": 8},
        desired_nmax_state={"N_MAX_DISP_ED": 30, "N_MAX_DISP_SA": 12},
        current_device_state={"1": "V_001", "2": "V_002"},
        desired_device_state={"V_VA_101": 1, "V_VA_102": 2},
    )
    assert ok is True
    assert fb.nStep == 10

    # Tick #1: pre-flight (10 → 20)
    await fb.tick()
    assert fb.nStep == 20

    # Tick #2: computar (20 → 30)
    await fb.tick()
    assert fb.nStep == 30

    # Tick #3: finalizar (30 → 99)
    await fb.tick()
    assert fb.nStep == fb.n_done
    assert fb.is_terminal() is True
    assert fb.error_msg is None
    assert fb.result == {
        "nmax_ops": nmax_ops,
        "rename_ops": rename_ops,
        "summary": {"nmax": 2, "rename": 1, "total": 3},
    }


@pytest.mark.asyncio
async def test_diff_constants_edge_case_empty_states() -> None:
    """Edge: ambos estados vacíos → 0 ops, result con listas
    vacías y summary ``{nmax: 0, rename: 0, total: 0}``."""
    fb = _make_fb_with_mock([], [])

    await fb.start(
        plc_name="S7-1500",
        config_table_name="2000_Disp_ED",
        current_nmax_state={},
        desired_nmax_state={},
        current_device_state={},
        desired_device_state={},
    )
    await fb.tick()  # 10 → 20
    await fb.tick()  # 20 → 30
    await fb.tick()  # 30 → 99

    assert fb.nStep == fb.n_done
    assert fb.result == {
        "nmax_ops": [],
        "rename_ops": [],
        "summary": {"nmax": 0, "rename": 0, "total": 0},
    }


@pytest.mark.asyncio
async def test_diff_constants_real_use_case_end_to_end() -> None:
    """Test end-to-end (sin mock): invoca el use case real
    ``DispCalculateConstantsDiffUseCase`` y verifica que el FB
    produce el output correcto.

    Sirve como smoke test: confirma que la integración FB ↔ use case
    real funciona sin tener que inventar mocks.

    Setup:
      - N_MAX: 1 cambio (ED 25→30), 1 ya en valor (EA 10==10).
      - Device: uid 1 cambia (V_001 → V_VA_101), uid 2 ya está bien
        (V_002 == V_002).  Total esperado: 1 N_MAX + 1 rename.
    """
    fb = FunctionDiffConstants(
        nombre="diff_constants_e2e",
        use_case_factory=lambda: DispCalculateConstantsDiffUseCase,
    )
    await fb.start(
        plc_name="S7-1500",
        config_table_name="2000_Disp_ED",
        current_nmax_state={"N_MAX_DISP_ED": 25, "N_MAX_DISP_EA": 10},
        desired_nmax_state={"N_MAX_DISP_ED": 30, "N_MAX_DISP_EA": 10},
        current_device_state={"1": "V_001", "2": "V_002"},
        # uid 1 → V_VA_101 (cambia), uid 2 → V_002 (ya está)
        desired_device_state={"V_VA_101": 1, "V_002": 2},
    )
    await fb.tick()
    await fb.tick()
    await fb.tick()

    assert fb.nStep == fb.n_done
    # N_MAX: 1 cambio (ED 25→30, EA ya está bien)
    assert fb.result["summary"]["nmax"] == 1
    # Device: 1 rename (uid 1 cambia, uid 2 ya está bien)
    assert fb.result["summary"]["rename"] == 1
    assert fb.result["summary"]["total"] == 2
    # Las ops tienen la shape correcta
    nmax_op = fb.result["nmax_ops"][0]
    assert nmax_op["command"] == "update_user_constant_value"
    assert nmax_op["args"]["constant_name"] == "N_MAX_DISP_ED"
    assert nmax_op["args"]["new_value"] == 30
    rename_op = fb.result["rename_ops"][0]
    assert rename_op["command"] == "update_user_constant_name"
    assert rename_op["args"]["current_name"] == "V_001"
    assert rename_op["args"]["new_name"] == "V_VA_101"


@pytest.mark.asyncio
async def test_diff_constants_sad_no_plc_name() -> None:
    """``start()`` sin ``plc_name`` → el primer tick falla con ValueError."""
    fb = _make_fb_with_mock([], [])
    await fb.start(
        config_table_name="2000_Disp_ED",
        current_nmax_state={}, desired_nmax_state={},
        current_device_state={}, desired_device_state={},
    )
    assert fb.nStep == 10

    await fb.tick()  # 10 → 98

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "plc_name" in fb.error_msg


@pytest.mark.asyncio
async def test_diff_constants_sad_no_config_table_name() -> None:
    """``start()`` sin ``config_table_name`` → el primer tick falla."""
    fb = _make_fb_with_mock([], [])
    await fb.start(
        plc_name="S7-1500",
        current_nmax_state={}, desired_nmax_state={},
        current_device_state={}, desired_device_state={},
    )
    assert fb.nStep == 10

    await fb.tick()  # 10 → 98

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "config_table_name" in fb.error_msg


@pytest.mark.asyncio
async def test_diff_constants_sad_missing_state() -> None:
    """``start()`` sin uno de los 4 estados (no-dict) → ValueError."""
    fb = _make_fb_with_mock([], [])
    await fb.start(
        plc_name="S7-1500",
        config_table_name="2000_Disp_ED",
        current_nmax_state={"N_MAX_DISP_ED": 25},
        desired_nmax_state={"N_MAX_DISP_ED": 30},
        current_device_state={"1": "V_001"},
        # Falta desired_device_state
    )
    assert fb.nStep == 10

    await fb.tick()  # 10 → 98

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "desired_device_state" in fb.error_msg


@pytest.mark.asyncio
async def test_diff_constants_terminal_no_avanza_mas() -> None:
    """Una vez en ``n_done``, ticks adicionales son no-op."""
    fb = _make_fb_with_mock([], [])
    await fb.start(
        plc_name="S7-1500", config_table_name="x",
        current_nmax_state={}, desired_nmax_state={},
        current_device_state={}, desired_device_state={},
    )

    # Forzar n_done
    fb.nStep = fb.n_done
    n_step_before = fb.nStep

    await fb.tick()
    assert fb.nStep == n_step_before
