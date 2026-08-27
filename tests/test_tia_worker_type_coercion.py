# -*- coding: utf-8 -*-
"""Tests del helper _coerce_value_for_plc_type (Fix #1 del sync).

TIA Portal V21 es estricto con los tipos en set_property. Si pasamos
str cuando el DataTypeName es numerico, el wrapper .NET lanza una
excepcion interna que corrompe la transaccion (CommitOnDispose).
Estos tests verifican el mapeo DataTypeName -> tipo Python nativo.
"""
from __future__ import annotations

import pytest

from core.infrastructure.tia.worker_tia import _coerce_value_for_plc_type


# ── Tipos enteros ─────────────────────────────────────────────────────
@pytest.mark.parametrize("data_type", ["Int", "DInt", "LInt", "SInt", "USInt",
                                        "UInt", "UDInt", "ULInt", "Byte",
                                        "Word", "DWord", "LWord"])
def test_int_types_return_python_int(data_type):
    result = _coerce_value_for_plc_type(42, data_type)
    assert isinstance(result, int)
    assert result == 42


# ── Tipos reales ──────────────────────────────────────────────────────
@pytest.mark.parametrize("data_type", ["Real", "LReal"])
def test_float_types_return_python_float(data_type):
    result = _coerce_value_for_plc_type(3.14, data_type)
    assert isinstance(result, float)
    assert result == pytest.approx(3.14)


# ── Tipo booleano ─────────────────────────────────────────────────────
def test_bool_type_returns_python_bool():
    result = _coerce_value_for_plc_type(True, "Bool")
    assert isinstance(result, bool)
    assert result is True


# ── Tipos string ──────────────────────────────────────────────────────
@pytest.mark.parametrize("data_type", ["String", "WString", "Char", "WChar"])
def test_string_types_return_python_str(data_type):
    result = _coerce_value_for_plc_type(123, data_type)
    assert isinstance(result, str)
    assert result == "123"


# ── Tipo desconocido: fallback a str (compatibilidad con TIA custom) ──
def test_unknown_type_falls_back_to_str():
    result = _coerce_value_for_plc_type(5, "MiTipoCustom")
    assert isinstance(result, str)
    assert result == "5"


# ── Tipo vacio (caso defensivo) ───────────────────────────────────────
def test_empty_data_type_falls_back_to_str():
    result = _coerce_value_for_plc_type(5, "")
    assert isinstance(result, str)


# ── Conversion invalida: ValueError claro (rollback limpio) ───────────
def test_invalid_int_raises_valueerror_with_context():
    with pytest.raises(ValueError) as exc_info:
        _coerce_value_for_plc_type("no es int", "Int")
    msg = str(exc_info.value)
    assert "Int" in msg
    assert "no es int" in msg


def test_invalid_float_raises_valueerror_with_context():
    with pytest.raises(ValueError) as exc_info:
        _coerce_value_for_plc_type("no es float", "Real")
    msg = str(exc_info.value)
    assert "Real" in msg
    assert "no es float" in msg


# ── Caso de regresion: N_MAX del PLC real ─────────────────────────────
# Bug reportado por Aketza: el N_MAX_DISP_M_VF con DataTypeName=Int y
# new_value=5 fallaba con "CommitOnDispose ... project data corruption"
# porque el codigo pasaba str(5) en vez de int(5). Este test garantiza
# que el caso especifico del PLC real funciona.
def test_n_max_int_with_small_value_returns_int():
    # Caso del log: new_value=5 para N_MAX_DISP_M_VF (Int).
    result = _coerce_value_for_plc_type(5, "Int")
    assert isinstance(result, int)
    assert result == 5
    # Verificamos que NO es str (que era el bug original)
    assert not isinstance(result, str)
