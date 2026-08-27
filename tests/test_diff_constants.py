"""Tests para ``CalculateConstantsDiffUseCase``.

Tests PUROS (sin TIA): validan los dos métodos de diff:
  - ``calculate_nmax_diff``: por nombre (key estable).
  - ``calculate_device_rename_diff``: por valor (UID estable).
"""
from __future__ import annotations

from areas.alimentacion.application.use_cases.diff_constants import (
    CalculateConstantsDiffUseCase,
)


# ────────────────────────────────────────────────────────────────────────
# calculate_nmax_diff (cambio de VALOR, key estable = nombre)
# ────────────────────────────────────────────────────────────────────────


def test_nmax_diff_no_changes_returns_empty() -> None:
    """Si TIA y Excel coinciden en valores, no se emiten operaciones."""
    current = {"N_MAX_DISP_ED": 25, "N_MAX_DISP_EA": 10}
    desired = {"N_MAX_DISP_ED": 25, "N_MAX_DISP_EA": 10}

    operations = CalculateConstantsDiffUseCase.calculate_nmax_diff(
        plc_name="PLC1",
        config_table_name="000_Config_Dispositivos",
        current_state=current,
        desired_state=desired,
    )
    assert operations == []


def test_nmax_diff_detects_value_change() -> None:
    """Si el valor de TIA difiere del Excel, emite update_user_constant_value."""
    current = {"N_MAX_DISP_ED": 25, "N_MAX_DISP_EA": 10}
    desired = {"N_MAX_DISP_ED": 30, "N_MAX_DISP_EA": 10}

    operations = CalculateConstantsDiffUseCase.calculate_nmax_diff(
        plc_name="PLC1",
        config_table_name="000_Config_Dispositivos",
        current_state=current,
        desired_state=desired,
    )
    assert len(operations) == 1
    op = operations[0]
    assert op["command"] == "update_user_constant_value"
    assert op["args"]["constant_name"] == "N_MAX_DISP_ED"
    assert op["args"]["new_value"] == 30


def test_nmax_diff_ignores_constants_not_in_tia() -> None:
    """Si una constante deseada no existe en TIA, se ignora (no create)."""
    current = {"N_MAX_DISP_ED": 25}
    desired = {"N_MAX_DISP_ED": 25, "N_MAX_INVENTADO": 50}

    operations = CalculateConstantsDiffUseCase.calculate_nmax_diff(
        plc_name="PLC1",
        config_table_name="000_Config_Dispositivos",
        current_state=current,
        desired_state=desired,
    )
    assert operations == []


# ────────────────────────────────────────────────────────────────────────
# calculate_device_rename_diff (cambio de NOMBRE, key estable = valor)
# ────────────────────────────────────────────────────────────────────────


def test_device_diff_no_changes_returns_empty() -> None:
    """Si los nombres coinciden, no se emiten operaciones."""
    current = {"1": "V_VA_101", "2": "V_VA_102"}
    desired = {"V_VA_101": 1, "V_VA_102": 2}

    operations = CalculateConstantsDiffUseCase.calculate_device_rename_diff(
        plc_name="PLC1",
        config_table_name="2000_Disp_ED",
        current_state=current,
        desired_state=desired,
    )
    assert operations == []


def test_device_diff_detects_name_change() -> None:
    """Si el nombre de TIA difiere del Excel, emite update_user_constant_name."""
    current = {"1": "V_001", "2": "V_002"}
    desired = {"V_VA_101": 1, "V_VA_102": 2}

    operations = CalculateConstantsDiffUseCase.calculate_device_rename_diff(
        plc_name="PLC1",
        config_table_name="2000_Disp_ED",
        current_state=current,
        desired_state=desired,
    )
    assert len(operations) == 2

    op1, op2 = operations[0], operations[1]
    assert op1["command"] == "update_user_constant_name"
    assert op1["args"]["current_name"] == "V_001"
    assert op1["args"]["new_name"] == "V_VA_101"
    # El valor NO se incluye (preservado).
    assert "new_value" not in op1["args"]

    assert op2["args"]["current_name"] == "V_002"
    assert op2["args"]["new_name"] == "V_VA_102"


def test_device_diff_ignores_value_not_in_tia() -> None:
    """Si un valor deseado no existe en TIA, se ignora (no create)."""
    current = {"1": "V_001"}
    desired = {"V_VA_101": 1, "V_VA_999": 99}

    operations = CalculateConstantsDiffUseCase.calculate_device_rename_diff(
        plc_name="PLC1",
        config_table_name="2000_Disp_ED",
        current_state=current,
        desired_state=desired,
    )
    assert len(operations) == 1
    assert operations[0]["args"]["current_name"] == "V_001"


def test_device_diff_preserves_value() -> None:
    """El VALOR nunca debe incluirse en los args del rename."""
    current = {"42": "OldName"}
    desired = {"NewName": 42}

    operations = CalculateConstantsDiffUseCase.calculate_device_rename_diff(
        plc_name="PLC1",
        config_table_name="2000_Disp_ED",
        current_state=current,
        desired_state=desired,
    )
    assert len(operations) == 1
    args = operations[0]["args"]
    assert "new_value" not in args
    assert "plc_name" in args
    assert "table_name" in args
    assert "current_name" in args
    assert "new_name" in args


def test_device_diff_value_change_does_not_emit_rename() -> None:
    """Si solo cambia el VALOR (no el nombre), NO se emite rename.

    Esto valida que el diff de dispositivos NO se confunde con el diff de N_MAX.
    """
    current = {"1": "Dispositivo_X"}
    desired = {"Dispositivo_X": 99}  # valor cambió pero nombre es igual

    operations = CalculateConstantsDiffUseCase.calculate_device_rename_diff(
        plc_name="PLC1",
        config_table_name="2000_Disp_ED",
        current_state=current,
        desired_state=desired,
    )
    assert operations == []
