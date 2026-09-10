"""Tests para ``areas.alimentacion.data.data_Procesos.DataProcesoPLC``.

Fase 3, paso 3.2.4.  Cobertura:
  - Construccion basica con los 3 campos requeridos (uid, nombre, codigo).
  - Defaults razonables (5 campos con default 0).
  - ``frozen=True``: no se puede mutar.
"""
from __future__ import annotations

import pytest

from areas.alimentacion.data.data_Procesos import DataProcesoPLC


def test_construccion_basica():
    """DataProcesoPLC acepta los 3 campos requeridos."""
    p = DataProcesoPLC(uid=1, nombre="Proceso 1", codigo="P1")

    assert p.uid == 1
    assert p.nombre == "Proceso 1"
    assert p.codigo == "P1"
    # Defaults
    assert p.preal == 0
    assert p.index_preal == 0
    assert p.pint == 0
    assert p.index_pint == 0
    assert p.alarmas == 0


def test_construccion_completa():
    """DataProcesoPLC acepta los 8 campos del Excel corporativo."""
    p = DataProcesoPLC(
        uid=10,
        nombre="Proceso 10",
        codigo="P10",
        preal=5,
        index_preal=100,
        pint=3,
        index_pint=50,
        alarmas=2,
    )

    assert p.uid == 10
    assert p.preal == 5
    assert p.index_preal == 100
    assert p.pint == 3
    assert p.index_pint == 50
    assert p.alarmas == 2


def test_frozen_no_muta():
    """``frozen=True``: asignar un campo levanta ``FrozenInstanceError``."""
    from dataclasses import FrozenInstanceError

    p = DataProcesoPLC(uid=1, nombre="P", codigo="P1")
    with pytest.raises(FrozenInstanceError):
        p.uid = 99  # type: ignore[misc]


def test_equality_por_valor():
    """Dos DataProcesoPLC con los mismos campos son iguales."""
    p1 = DataProcesoPLC(uid=1, nombre="P", codigo="P1", preal=5)
    p2 = DataProcesoPLC(uid=1, nombre="P", codigo="P1", preal=5)

    assert p1 == p2


def test_inequality_si_difieren():
    """Dos DataProcesoPLC con campos diferentes NO son iguales."""
    p1 = DataProcesoPLC(uid=1, nombre="P", codigo="P1")
    p2 = DataProcesoPLC(uid=2, nombre="P", codigo="P2")

    assert p1 != p2
