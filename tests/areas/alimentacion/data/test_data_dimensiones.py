"""Tests de ``DimensionesDispositivos`` y ``DataDimensionesPLC``.

Cobertura (multi-PLC, sept-2026):
  - ``DataDimensionesPLC``: instanciar, ``get(nmax_name)``, ``to_api_dict()``.
  - ``DimensionesDispositivos``: contenedor con ``por_plc``,
    ``get_for_plc(plc_name)``, ``to_api_dict()`` con shape anidado.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from areas.alimentacion.data.data_dimensiones import (
    DataDimensionesPLC,
    DimensionesDispositivos,
)


# ---------------------------------------------------------------------------
# DataDimensionesPLC
# ---------------------------------------------------------------------------


def test_data_dimensiones_plc_instanciar():
    """DataDimensionesPLC acepta plc_name + extras."""
    p = DataDimensionesPLC(plc_name="PLC1", extras={"N_MAX_DISP_ED": 32})
    assert p.plc_name == "PLC1"
    assert dict(p.extras) == {"N_MAX_DISP_ED": 32}


def test_data_dimensiones_plc_extras_default_vacio():
    """Sin extras, devuelve dict vacio."""
    p = DataDimensionesPLC(plc_name="PLC1")
    assert dict(p.extras) == {}


def test_data_dimensiones_plc_get_por_canonico():
    """``get(N_MAX_DISP_ED)`` devuelve el valor o ``None``."""
    p = DataDimensionesPLC(plc_name="PLC1", extras={"N_MAX_DISP_ED": 21})
    assert p.get("N_MAX_DISP_ED") == 21
    assert p.get("N_MAX_DISP_INEXISTENTE") is None


def test_data_dimensiones_plc_to_api_dict_retorna_copia():
    """``to_api_dict()`` retorna dict plano (copia, no alias)."""
    p = DataDimensionesPLC(plc_name="PLC1", extras={"N_MAX_DISP_ED": 21})
    result = p.to_api_dict()
    assert result == {"N_MAX_DISP_ED": 21}
    result["NUEVA"] = 99
    assert "NUEVA" not in p.extras


def test_data_dimensiones_plc_frozen():
    """``frozen=True``: asignar un campo levanta FrozenInstanceError."""
    p = DataDimensionesPLC(plc_name="PLC1")
    with pytest.raises(FrozenInstanceError):
        p.plc_name = "PLC2"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# DimensionesDispositivos (contenedor)
# ---------------------------------------------------------------------------


def test_dimensiones_default_por_plc_vacio():
    """Sin argumentos, contenedor vacio."""
    d = DimensionesDispositivos()
    assert d.por_plc == ()


def test_dimensiones_get_for_plc_existente():
    """``get_for_plc("PLC1")`` devuelve el DataDimensionesPLC exacto."""
    p1 = DataDimensionesPLC(plc_name="PLC1", extras={"N_MAX_DISP_ED": 32})
    p2 = DataDimensionesPLC(plc_name="PLC2", extras={"N_MAX_DISP_ED": 64})
    d = DimensionesDispositivos(por_plc=(p1, p2))
    assert d.get_for_plc("PLC1") is p1
    assert d.get_for_plc("PLC2") is p2


def test_dimensiones_get_for_plc_inexistente():
    """``get_for_plc("PLC_FOO")`` devuelve None si no existe."""
    p1 = DataDimensionesPLC(plc_name="PLC1")
    d = DimensionesDispositivos(por_plc=(p1,))
    assert d.get_for_plc("PLC_FOO") is None


def test_dimensiones_to_api_dict_shape_anidado():
    """``to_api_dict()`` retorna ``{plc: {nmax: int}}`` (shape multi-PLC)."""
    p1 = DataDimensionesPLC(plc_name="PLC1", extras={"N_MAX_DISP_ED": 32})
    p2 = DataDimensionesPLC(plc_name="PLC2", extras={"N_MAX_DISP_ED": 64})
    d = DimensionesDispositivos(por_plc=(p1, p2))
    assert d.to_api_dict() == {
        "PLC1": {"N_MAX_DISP_ED": 32},
        "PLC2": {"N_MAX_DISP_ED": 64},
    }


def test_dimensiones_frozen():
    """``frozen=True``: asignar un campo levanta FrozenInstanceError."""
    d = DimensionesDispositivos()
    with pytest.raises(FrozenInstanceError):
        d.por_plc = ()  # type: ignore[misc]