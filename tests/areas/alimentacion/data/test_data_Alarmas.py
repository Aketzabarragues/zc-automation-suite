"""Tests para ``areas.alimentacion.data.data_Alarmas.DataAlarmaPLC``.

Fase 3, paso 3.2.7.  Cobertura:
  - Construccion basica con los 6 campos.
  - ``frozen=True``: no se puede mutar.
  - R-F4.1: NO tiene atributo ``visibilidad`` (defensa contra schema drift).
  - Equality por valor.
"""
from __future__ import annotations

import pytest

from areas.alimentacion.data.data_Alarmas import DataAlarmaPLC


def test_construccion_completa():
    """DataAlarmaPLC acepta los 6 campos del Excel corporativo."""
    a = DataAlarmaPLC(
        uid="AL_1_001",
        numero="001",
        proceso="Proceso 1",
        num_db=3001,
        descripcion="Alarma nivel alto",
        comentario_db="DB comentario",
    )

    assert a.uid == "AL_1_001"
    assert a.numero == "001"
    assert a.proceso == "Proceso 1"
    assert a.num_db == 3001
    assert a.descripcion == "Alarma nivel alto"
    assert a.comentario_db == "DB comentario"


def test_frozen_no_muta():
    """``frozen=True``: asignar un campo levanta ``FrozenInstanceError``."""
    from dataclasses import FrozenInstanceError

    a = DataAlarmaPLC(
        uid="AL_1_001", numero="001", proceso="P",
        num_db=3001, descripcion="D", comentario_db="C",
    )
    with pytest.raises(FrozenInstanceError):
        a.num_db = 9999  # type: ignore[misc]


def test_no_tiene_atributo_visibilidad_rf4():
    """R-F4.1: ``DataAlarmaPLC`` NO tiene atributo ``visibilidad`` por diseno.

    Defensa contra schema drift: si el Excel del corporativo incluye
    en el futuro una columna ``Visibilidad`` en ``Tabla_Alarmas``, el
    parser la ignora silenciosamente y el DTO sigue sin ese campo.
    """
    a = DataAlarmaPLC(
        uid="AL_1_001", numero="001", proceso="P",
        num_db=3001, descripcion="D", comentario_db="C",
    )

    assert not hasattr(a, "visibilidad")


def test_equality_por_valor():
    """Dos DataAlarmaPLC con los mismos campos son iguales."""
    kwargs = dict(
        uid="AL_1_001", numero="001", proceso="P",
        num_db=3001, descripcion="D", comentario_db="C",
    )
    a1 = DataAlarmaPLC(**kwargs)
    a2 = DataAlarmaPLC(**kwargs)

    assert a1 == a2
