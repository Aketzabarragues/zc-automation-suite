"""Tests del DTO ``DataPLC`` (multi-PLC)."""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from areas.alimentacion.data.data_plc import DataPLC


def test_data_plc_instanciar():
    """DataPLC acepta uid + plc."""
    p = DataPLC(uid=1, plc="PLC1")
    assert p.uid == 1
    assert p.plc == "PLC1"


def test_data_plc_plc_default_vacio():
    """Sin plc, queda vacio (back-compat)."""
    p = DataPLC(uid=1)
    assert p.plc == ""


def test_data_plc_no_acepta_plc_none():
    """plc=None levanta ValueError (defensivo)."""
    with pytest.raises(ValueError):
        DataPLC(uid=1, plc=None)  # type: ignore[arg-type]


def test_data_plc_frozen():
    """frozen=True: asignar plc levanta FrozenInstanceError."""
    p = DataPLC(uid=1, plc="PLC1")
    with pytest.raises(FrozenInstanceError):
        p.plc = "PLC2"  # type: ignore[misc]