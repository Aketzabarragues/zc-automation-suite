"""Tests para ``areas.alimentacion.data.data_ProcSlotMap.DataProcSlotMap``.

Fase 3, paso 3.2.9.  Cobertura:
  - defaults razonables (3 dicts, 3 strs, 2 strs, 2 dicts, 2 lists).
  - ``frozen=True``: no se puede mutar.
  - ``to_dict()`` shape estable: 12 keys.
  - ``to_dict()`` convierte los ``int`` slots a ``str`` (JSON-friendly).
  - copia defensiva en ``to_dict()``.
"""
from __future__ import annotations

import pytest

from areas.alimentacion.data.data_ProcSlotMap import DataProcSlotMap


def test_defaults_vacios():
    """DataProcSlotMap() da todos los campos a su valor por defecto."""
    m = DataProcSlotMap()

    assert m.preal == {}
    assert m.pint == {}
    assert m.alm == {}
    assert m.db_param_name == ""
    assert m.db_alm_name == ""
    assert m.table_name == ""
    assert m.param_subpath == ""
    assert m.alm_subpath == ""
    assert m.nmax == {}
    assert m.nmax_names == {}
    assert m.missing_blocks == []
    assert m.warnings == []


def test_frozen_no_muta():
    """``frozen=True``: asignar un campo levanta ``FrozenInstanceError``."""
    from dataclasses import FrozenInstanceError

    m = DataProcSlotMap()
    with pytest.raises(FrozenInstanceError):
        m.db_param_name = "DB9999_X_PARAM"  # type: ignore[misc]


def test_to_dict_shape():
    """``to_dict()`` emite las 12 keys del shape estable."""
    m = DataProcSlotMap(
        preal={1: "real_1"},
        pint={1: "int_1"},
        alm={1: "alm_1"},
        db_param_name="DB3000_P1_PARAM",
        db_alm_name="DB3001_P1_ALM",
        table_name="1_P1",
    )
    snapshot = m.to_dict()

    assert set(snapshot.keys()) == {
        "preal", "pint", "alm",
        "db_param_name", "db_alm_name", "table_name",
        "param_subpath", "alm_subpath",
        "nmax", "nmax_names",
        "missing_blocks", "warnings",
    }


def test_to_dict_convierte_slots_int_a_str():
    """``to_dict()`` convierte los ``int`` slots a ``str`` (JSON-friendly)."""
    m = DataProcSlotMap(
        preal={1: "real_1", 2: "real_2"},
        pint={1: "int_1"},
        alm={1: "alm_1", 5: "alm_5"},
    )
    snapshot = m.to_dict()

    assert snapshot["preal"] == {"1": "real_1", "2": "real_2"}
    assert snapshot["pint"] == {"1": "int_1"}
    assert snapshot["alm"] == {"1": "alm_1", "5": "alm_5"}


def test_to_dict_copia_defensiva():
    """``to_dict()`` hace copia defensiva: mutar el snapshot NO afecta al original."""
    m = DataProcSlotMap(
        preal={1: "real_1"},
        pint={1: "int_1"},
        nmax={"preal": 5},
        warnings=["w1"],
    )

    snapshot = m.to_dict()

    # Mutar el snapshot NO afecta al estado del DB.
    snapshot["preal"]["2"] = "MUTATED"
    snapshot["nmax"]["MUTATED"] = 0
    snapshot["warnings"].append("MUTATED")

    assert m.preal == {1: "real_1"}
    assert m.nmax == {"preal": 5}
    assert m.warnings == ["w1"]


def test_listas_entre_instancias_son_independientes():
    """``default_factory``: dos instancias no comparten listas ni dicts."""
    m1 = DataProcSlotMap()
    m2 = DataProcSlotMap()

    assert m1.preal is not m2.preal
    assert m1.missing_blocks is not m2.missing_blocks
    assert m1.warnings is not m2.warnings

    m1.missing_blocks.append("solo en m1")
    m1.warnings.append("solo en m1")
    assert m2.missing_blocks == []
    assert m2.warnings == []
