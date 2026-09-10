"""Tests para ``areas.alimentacion.data.data_ParametrosReal.DataParamRealPLC``.

Fase 3, paso 3.2.6.  Cobertura:
  - Construccion basica con los 12 campos.
  - ``num_lista`` acepta tanto ``int`` como ``str`` (marcadores).
  - ``frozen=True``: no se puede mutar.
  - ``DataParamRealPLC`` y ``DataParamIntPLC`` son nominalmente
    distintos (R4): ``isinstance`` los trata por separado aunque
    tengan los mismos campos.
"""
from __future__ import annotations

import pytest

from areas.alimentacion.data.data_ParametrosInt import DataParamIntPLC
from areas.alimentacion.data.data_ParametrosReal import DataParamRealPLC


def test_construccion_completa():
    """DataParamRealPLC acepta los 12 campos del Excel corporativo."""
    p = DataParamRealPLC(
        uid="PR_1_001",
        numero="001",
        proceso="Proceso 1",
        codigo="P1",
        num_db=3000,
        producto="Linea A",
        tipo="Setpoint",
        descripcion="Setpoint temperatura",
        comentario_db="DB comentario",
        visibilidad="Si",
        num_lista=3,
        txt_lista="Lista seleccion",
    )

    assert p.uid == "PR_1_001"
    assert p.numero == "001"
    assert p.proceso == "Proceso 1"
    assert p.codigo == "P1"
    assert p.num_db == 3000
    assert p.producto == "Linea A"
    assert p.tipo == "Setpoint"
    assert p.descripcion == "Setpoint temperatura"
    assert p.comentario_db == "DB comentario"
    assert p.visibilidad == "Si"
    assert p.num_lista == 3
    assert p.txt_lista == "Lista seleccion"


def test_num_lista_acepta_int():
    """``num_lista`` acepta ``int``."""
    p = DataParamRealPLC(
        uid="PR_1_001", numero="001", proceso="P", codigo="P",
        num_db=3000, producto="L", tipo="T", descripcion="D",
        comentario_db="C", visibilidad="Si", num_lista=7, txt_lista="X",
    )
    assert p.num_lista == 7
    assert isinstance(p.num_lista, int)


def test_num_lista_acepta_str_marcador():
    """``num_lista`` acepta ``str`` para marcadores (``"N/A"``)."""
    p = DataParamRealPLC(
        uid="PR_1_001", numero="001", proceso="P", codigo="P",
        num_db=3000, producto="L", tipo="T", descripcion="D",
        comentario_db="C", visibilidad="Si", num_lista="N/A", txt_lista="X",
    )
    assert p.num_lista == "N/A"
    assert isinstance(p.num_lista, str)


def test_frozen_no_muta():
    """``frozen=True``: asignar un campo levanta ``FrozenInstanceError``."""
    from dataclasses import FrozenInstanceError

    p = DataParamRealPLC(
        uid="PR_1_001", numero="001", proceso="P", codigo="P",
        num_db=3000, producto="L", tipo="T", descripcion="D",
        comentario_db="C", visibilidad="Si", num_lista=0, txt_lista="X",
    )
    with pytest.raises(FrozenInstanceError):
        p.num_db = 9999  # type: ignore[misc]


def test_distinto_de_data_param_int_r4():
    """R4: ``DataParamRealPLC`` y ``DataParamIntPLC`` son nominalmente distintos.

    Aunque tengan los mismos campos, ``isinstance`` los trata por
    separado.  Verificamos creando uno de cada con los MISMOS campos:
    NO son la misma clase.
    """
    kwargs = dict(
        uid="X", numero="001", proceso="P", codigo="P",
        num_db=3000, producto="L", tipo="T", descripcion="D",
        comentario_db="C", visibilidad="Si", num_lista=0, txt_lista="X",
    )
    pr = DataParamRealPLC(**kwargs)
    pi = DataParamIntPLC(**kwargs)

    # NO son la misma clase.
    assert type(pr) is not type(pi)
    # ``isinstance`` los distingue.
    assert not isinstance(pr, DataParamIntPLC)
    assert not isinstance(pi, DataParamRealPLC)
