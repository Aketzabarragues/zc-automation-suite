"""Tests de ``DimensionesDispositivos`` y ``DataDimensionesPLC``.

Cobertura (multi-PLC):
  - ``DataDimensionesPLC``: instanciar, ``get(nmax_name)``, ``to_api_dict()``,
    ``n_max_entidades`` (default 0, back-compat con Excels legacy).
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


def test_data_dimensiones_plc_n_max_entidades_default_cero():
    """``n_max_entidades`` default es 0 (back-compat con Excels legacy)."""
    p = DataDimensionesPLC(plc_name="PLC1")
    assert p.n_max_entidades == 0


def test_data_dimensiones_plc_n_max_entidades_custom():
    """``n_max_entidades`` acepta valor positivo custom."""
    p = DataDimensionesPLC(plc_name="PLC1", n_max_entidades=42)
    assert p.n_max_entidades == 42


def test_data_dimensiones_plc_n_max_entidades_no_en_extras():
    """``n_max_entidades`` NO se popula en ``extras`` (separacion limpia)."""
    p = DataDimensionesPLC(
        plc_name="PLC1",
        extras={"N_MAX_DISP_ED": 32},
        n_max_entidades=42,
    )
    assert "N_MAX_ENTIDAD" not in p.extras
    assert p.n_max_entidades == 42


def test_data_dimensiones_plc_get_por_canonico():
    """``get(N_MAX_DISP_ED)`` devuelve el valor o ``None``."""
    p = DataDimensionesPLC(plc_name="PLC1", extras={"N_MAX_DISP_ED": 21})
    assert p.get("N_MAX_DISP_ED") == 21
    assert p.get("N_MAX_DISP_INEXISTENTE") is None
    # ``get()`` solo busca en extras, NO en n_max_entidades.
    p_con_ent = DataDimensionesPLC(plc_name="PLC1", n_max_entidades=42)
    assert p_con_ent.get("N_MAX_ENTIDAD") is None


def test_data_dimensiones_plc_to_api_dict_retorna_copia():
    """``to_api_dict()`` retorna dict plano (copia, no alias)."""
    p = DataDimensionesPLC(plc_name="PLC1", extras={"N_MAX_DISP_ED": 21})
    result = p.to_api_dict()
    assert result == {"N_MAX_DISP_ED": 21, "N_MAX_ENTIDAD": 0}
    result["NUEVA"] = 99
    assert "NUEVA" not in p.extras


def test_data_dimensiones_plc_to_api_dict_incluye_n_max_entidades():
    """``to_api_dict()`` incluye ``N_MAX_ENTIDAD`` (incluso con valor 0)."""
    p = DataDimensionesPLC(plc_name="PLC1", extras={"N_MAX_DISP_ED": 21})
    assert p.to_api_dict() == {"N_MAX_DISP_ED": 21, "N_MAX_ENTIDAD": 0}

    p_con_ent = DataDimensionesPLC(
        plc_name="PLC1",
        extras={"N_MAX_DISP_ED": 21},
        n_max_entidades=50,
    )
    assert p_con_ent.to_api_dict() == {"N_MAX_DISP_ED": 21, "N_MAX_ENTIDAD": 50}


def test_data_dimensiones_plc_frozen():
    """``frozen=True``: asignar un campo levanta FrozenInstanceError."""
    p = DataDimensionesPLC(plc_name="PLC1")
    with pytest.raises(FrozenInstanceError):
        p.plc_name = "PLC2"  # type: ignore[misc]


def test_data_dimensiones_plc_n_max_entidades_frozen():
    """``n_max_entidades`` tambien es frozen."""
    p = DataDimensionesPLC(plc_name="PLC1", n_max_entidades=10)
    with pytest.raises(FrozenInstanceError):
        p.n_max_entidades = 20  # type: ignore[misc]


def test_data_dimensiones_plc_equality_con_n_max_entidades():
    """Equality incluye ``n_max_entidades`` (dataclass eq)."""
    a = DataDimensionesPLC(plc_name="PLC1", n_max_entidades=42)
    b = DataDimensionesPLC(plc_name="PLC1", n_max_entidades=42)
    c = DataDimensionesPLC(plc_name="PLC1", n_max_entidades=99)
    d = DataDimensionesPLC(plc_name="PLC1")
    assert a == b
    assert a != c
    assert a != d  # 42 != 0


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
        "PLC1": {"N_MAX_DISP_ED": 32, "N_MAX_ENTIDAD": 0},
        "PLC2": {"N_MAX_DISP_ED": 64, "N_MAX_ENTIDAD": 0},
    }


def test_dimensiones_to_api_dict_con_n_max_entidades():
    """``to_api_dict()`` propaga ``N_MAX_ENTIDAD`` por PLC."""
    p1 = DataDimensionesPLC(
        plc_name="PLC1",
        extras={"N_MAX_DISP_ED": 32},
        n_max_entidades=15,
    )
    p2 = DataDimensionesPLC(
        plc_name="PLC2",
        extras={"N_MAX_DISP_ED": 64},
        n_max_entidades=50,
    )
    d = DimensionesDispositivos(por_plc=(p1, p2))
    assert d.to_api_dict() == {
        "PLC1": {"N_MAX_DISP_ED": 32, "N_MAX_ENTIDAD": 15},
        "PLC2": {"N_MAX_DISP_ED": 64, "N_MAX_ENTIDAD": 50},
    }


def test_dimensiones_frozen():
    """``frozen=True``: asignar un campo levanta FrozenInstanceError."""
    d = DimensionesDispositivos()
    with pytest.raises(FrozenInstanceError):
        d.por_plc = ()  # type: ignore[misc]