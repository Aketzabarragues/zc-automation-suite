"""Tests del helper ``validate_plc_in_excel`` (sept-2026, multi-PLC).

Cobertura:
  - ``plc_name=""`` -> ValueError claro.
  - Sin Excel cargado (``excel_cache_full is None``) -> ValueError claro.
  - PLC en Excel -> OK, no raise.
  - PLC NO en Excel -> ValueError con lista de PLCs disponibles.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from core.helpers.tia.validate_plc_in_excel import validate_plc_in_excel


# ── DTOs fake ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class _FakePLC:
    plc: str
    uid: int = 0


@dataclass(frozen=True)
class _FakeCache:
    plcs: tuple = ()


@dataclass
class _FakeState:
    excel_cache_full: _FakeCache | None = None


# ── Tests ──────────────────────────────────────────────────────────


def test_plc_name_vacio_lanza_value_error():
    """plc_name='' -> ValueError claro."""
    state = _FakeState(excel_cache_full=_FakeCache(plcs=("X",)))
    with pytest.raises(ValueError, match="plc_name vacio"):
        validate_plc_in_excel(state, "")


def test_sin_excel_lanzado_lanza_value_error():
    """Si excel_cache_full es None -> ValueError claro."""
    state = _FakeState(excel_cache_full=None)
    with pytest.raises(ValueError, match="No hay Excel cargado"):
        validate_plc_in_excel(state, "PLC1")


def test_plc_en_excel_ok():
    """PLC en Excel -> no raise."""
    state = _FakeState(excel_cache_full=_FakeCache(plcs=(
        _FakePLC(plc="PLC1", uid=0),
        _FakePLC(plc="PLC2", uid=1),
    )))
    # No debe lanzar.
    validate_plc_in_excel(state, "PLC1")
    validate_plc_in_excel(state, "PLC2")


def test_plc_no_en_excel_lanza_value_error():
    """PLC NO en Excel -> ValueError con lista de PLCs disponibles."""
    state = _FakeState(excel_cache_full=_FakeCache(plcs=(
        _FakePLC(plc="PLC1", uid=0),
        _FakePLC(plc="PLC2", uid=1),
    )))
    with pytest.raises(ValueError) as exc_info:
        validate_plc_in_excel(state, "PLC_FANTASMA")
    msg = str(exc_info.value)
    assert "PLC_FANTASMA" in msg
    assert "PLC1" in msg
    assert "PLC2" in msg
    assert "no esta en el Excel" in msg


def test_strict_equality_no_normaliza():
    """Strict equality (D11): 'plc1' != 'PLC1'."""
    state = _FakeState(excel_cache_full=_FakeCache(plcs=(
        _FakePLC(plc="PLC1", uid=0),
    )))
    with pytest.raises(ValueError, match="no esta en el Excel"):
        validate_plc_in_excel(state, "plc1")


def test_excel_con_plcs_vacias_lanza():
    """Excel con Tabla_PLC vacia -> cualquier plc_name falla."""
    state = _FakeState(excel_cache_full=_FakeCache(plcs=()))
    with pytest.raises(ValueError, match=r"\[\]"):
        validate_plc_in_excel(state, "PLC1")
