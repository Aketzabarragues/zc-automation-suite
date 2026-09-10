"""Tests para ``areas.alimentacion.data.data_DispSlotMap.DataDispSlotMap``.

Fase 3, paso 3.2.8.  Cobertura:
  - defaults razonables.
  - ``frozen=True``: no se puede mutar.
  - ``to_dict()`` shape estable: 4 keys.
  - ``to_dict()`` convierte los ``int`` slots a ``str`` (JSON-friendly).
  - copia defensiva en ``to_dict()``.
"""
from __future__ import annotations

import pytest

from areas.alimentacion.data.data_DispSlotMap import DataDispSlotMap


def test_defaults_vacios():
    """DataDispSlotMap() da todos los campos a su valor por defecto."""
    m = DataDispSlotMap()

    assert m.slot_maps == {}
    assert m.db_names == {}
    assert m.db_array_names == {}
    assert m.warnings == []


def test_frozen_no_muta():
    """``frozen=True``: asignar un campo levanta ``FrozenInstanceError``."""
    from dataclasses import FrozenInstanceError

    m = DataDispSlotMap()
    with pytest.raises(FrozenInstanceError):
        m.warnings = ["nuevo"]  # type: ignore[misc]


def test_to_dict_shape():
    """``to_dict()`` emite las 4 keys del shape estable."""
    m = DataDispSlotMap(
        slot_maps={"ed": {0: "NO USAR", 1: "ED_1"}},
        db_names={"ed": "DB100_ED"},
        db_array_names={"ed": "ED_Array"},
        warnings=["warning 1"],
    )
    snapshot = m.to_dict()

    assert set(snapshot.keys()) == {
        "slot_maps", "db_names", "db_array_names", "warnings",
    }


def test_to_dict_convierte_slots_int_a_str():
    """``to_dict()`` convierte los slots ``int`` a ``str`` (JSON-friendly)."""
    m = DataDispSlotMap(
        slot_maps={"ed": {0: "NO USAR", 1: "ED_1", 5: "ED_5"}},
    )
    snapshot = m.to_dict()

    # Los slots se serializan como str.
    assert snapshot["slot_maps"]["ed"] == {
        "0": "NO USAR",
        "1": "ED_1",
        "5": "ED_5",
    }


def test_to_dict_copia_defensiva():
    """``to_dict()`` hace copia defensiva: mutar el snapshot NO afecta al original."""
    m = DataDispSlotMap(
        slot_maps={"ed": {0: "NO USAR", 1: "ED_1"}},
        db_names={"ed": "DB100_ED"},
        warnings=["w1"],
    )

    snapshot = m.to_dict()

    # Mutar el snapshot NO afecta al estado del DB.
    snapshot["slot_maps"]["ed"][2] = "MUTATED"
    snapshot["db_names"]["ea"] = "MUTATED"
    snapshot["warnings"].append("MUTATED")

    assert m.slot_maps == {"ed": {0: "NO USAR", 1: "ED_1"}}
    assert m.db_names == {"ed": "DB100_ED"}
    assert m.warnings == ["w1"]


def test_warnings_entre_instancias_son_independientes():
    """``default_factory``: dos instancias no comparten la lista de warnings."""
    m1 = DataDispSlotMap()
    m2 = DataDispSlotMap()

    assert m1.warnings is not m2.warnings

    m1.warnings.append("solo en m1")
    assert m2.warnings == []
