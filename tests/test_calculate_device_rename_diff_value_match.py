"""Tests de regresión: ``calculate_device_rename_diff`` matchea por value↔numero.

El contrato del usuario (sección §11 del plan) es:

    "los datos de cada dispositivo SOLO se pueden comparar con su
     propia tabla de variables a través del value de la tabla de
     variables y numero del excel (en memoria)"

Es decir:
  - **TIA side (current_state)**: ``{value_str: name}`` (la
    ``<Value>`` del PlcUserConstant es la identidad estable).
  - **Excel side (desired_state)**: ``{name: value_int}`` (el
    ``numero`` del DTO es la identidad estable).

El diff itera el desired_state, extrae el value, lo busca en
current_state por value, y compara nombres. Si el nombre difiere,
emite un ``update_user_constant_name`` (preservando el value).
"""
from __future__ import annotations

from application.use_cases.diff_constants import (
    CalculateConstantsDiffUseCase,
)


# ──────────────────────────────────────────────────────────────────────
# Caso feliz: 1 rename
# ──────────────────────────────────────────────────────────────────────


def test_rename_detected_when_value_matches_but_name_differs() -> None:
    """TIA: value=1, name=V_OLD.  Excel: numero=1, plc_tag=V_NEW."""
    current = {"1": "V_OLD", "2": "V_002"}
    desired = {"V_NEW": 1, "V_002": 2}

    ops = CalculateConstantsDiffUseCase.calculate_device_rename_diff(
        plc_name="PLC1",
        config_table_name="2000_Disp_V",
        current_state=current,
        desired_state=desired,
    )

    assert len(ops) == 1
    op = ops[0]
    assert op["command"] == "update_user_constant_name"
    assert op["args"]["plc_name"] == "PLC1"
    assert op["args"]["table_name"] == "2000_Disp_V"
    assert op["args"]["current_name"] == "V_OLD"
    assert op["args"]["new_name"] == "V_NEW"
    # CRÍTICO: el value NUNCA se incluye en el rename (se preserva).
    assert "new_value" not in op["args"]


# ──────────────────────────────────────────────────────────────────────
# Idempotencia: 0 ops si todo coincide
# ──────────────────────────────────────────────────────────────────────


def test_no_ops_when_current_matches_desired() -> None:
    """TIA y Excel alineados: 0 ops (idempotente)."""
    current = {"1": "V_001", "2": "V_002"}
    desired = {"V_001": 1, "V_002": 2}

    ops = CalculateConstantsDiffUseCase.calculate_device_rename_diff(
        plc_name="PLC1",
        config_table_name="2000_Disp_V",
        current_state=current,
        desired_state=desired,
    )
    assert ops == []


# ──────────────────────────────────────────────────────────────────────
# Política: dispositivo nuevo (value no existe en TIA) → IGNORADO
# ──────────────────────────────────────────────────────────────────────


def test_new_device_value_not_in_tia_is_ignored() -> None:
    """Si el value del Excel no existe en TIA, no se crea nada por COM.

    Esto es coherente con la política "rename es por value, no se
    crean constantes nuevas en este flujo" (ver docstring del diff).
    La creación de PlcUserConstant nuevas se hace por
    ``UserConstantsModifier`` (offline), no por COM.
    """
    current = {"1": "V_001"}
    desired = {"V_NEW": 99}  # value 99 no existe en TIA

    ops = CalculateConstantsDiffUseCase.calculate_device_rename_diff(
        plc_name="PLC1",
        config_table_name="2000_Disp_V",
        current_state=current,
        desired_state=desired,
    )
    assert ops == []


# ──────────────────────────────────────────────────────────────────────
# Política: value tipo str no casteable → IGNORADO (defensivo)
# ──────────────────────────────────────────────────────────────────────


def test_non_int_value_in_desired_is_ignored() -> None:
    """Si el value del Excel no es casteable a int, se ignora."""
    current = {"1": "V_001"}
    desired = {"V_NEW": "no_es_int"}

    ops = CalculateConstantsDiffUseCase.calculate_device_rename_diff(
        plc_name="PLC1",
        config_table_name="2000_Disp_V",
        current_state=current,
        desired_state=desired,
    )
    assert ops == []


# ──────────────────────────────────────────────────────────────────────
# Multiple renames simultáneos
# ──────────────────────────────────────────────────────────────────────


def test_multiple_renames_in_one_pass() -> None:
    """Varios renames en una sola pasada."""
    current = {
        "1": "V_A",
        "2": "V_B",
        "3": "V_C",
    }
    desired = {
        "V_X": 1,   # rename V_A → V_X
        "V_Y": 2,   # rename V_B → V_Y
        "V_C": 3,   # ya está bien
    }

    ops = CalculateConstantsDiffUseCase.calculate_device_rename_diff(
        plc_name="PLC1",
        config_table_name="2000_Disp_V",
        current_state=current,
        desired_state=desired,
    )

    assert len(ops) == 2
    renames = {(o["args"]["current_name"], o["args"]["new_name"]) for o in ops}
    assert renames == {("V_A", "V_X"), ("V_B", "V_Y")}


# ──────────────────────────────────────────────────────────────────────
# Sanity: el value del desired es STRING, el del current también
# ──────────────────────────────────────────────────────────────────────


def test_match_works_with_string_values_in_desired() -> None:
    """El desired puede tener values como string (e.g. ``"1"`` vs ``1``).

    El diff internamente convierte con ``int(desired_value)`` y
    compara con ``str(int_value)``. Verificamos que funcione
    independientemente de si el desired pasa el value como ``int`` o
    como ``str`` numérico.
    """
    current = {"1": "V_001"}

    # desired con int
    ops_int = CalculateConstantsDiffUseCase.calculate_device_rename_diff(
        plc_name="PLC1", config_table_name="t",
        current_state=current, desired_state={"V_NEW": 1},
    )
    assert len(ops_int) == 1
    assert ops_int[0]["args"]["current_name"] == "V_001"
    assert ops_int[0]["args"]["new_name"] == "V_NEW"

    # desired con str
    ops_str = CalculateConstantsDiffUseCase.calculate_device_rename_diff(
        plc_name="PLC1", config_table_name="t",
        current_state=current, desired_state={"V_NEW": "1"},
    )
    assert len(ops_str) == 1
    assert ops_str[0]["args"]["current_name"] == "V_001"
    assert ops_str[0]["args"]["new_name"] == "V_NEW"
