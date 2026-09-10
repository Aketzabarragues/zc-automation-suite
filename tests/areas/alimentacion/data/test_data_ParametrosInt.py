"""Tests para ``areas.alimentacion.data.data_ParametrosInt.DataParamIntPLC``.

Fase 3, paso 3.2.5.  Cobertura:
  - Construccion basica con todos los campos.
  - ``num_lista`` acepta tanto ``int`` como ``str`` (marcadores
    semanticos como ``"N/A"`` o ``"TODOS"``).
  - ``frozen=True``: no se puede mutar.
  - Equality por valor.
"""
from __future__ import annotations

import pytest

from areas.alimentacion.data.data_ParametrosInt import DataParamIntPLC


def test_construccion_completa():
    """DataParamIntPLC acepta los 12 campos del Excel corporativo."""
    p = DataParamIntPLC(
        uid="PI_1_001",
        numero="001",
        proceso="Proceso 1",
        codigo="P1",
        num_db=3000,
        producto="Linea A",
        tipo="Contador",
        descripcion="Contador de piezas",
        comentario_db="DB comentario",
        visibilidad="Si",
        num_lista=5,
        txt_lista="Lista seleccion",
    )

    assert p.uid == "PI_1_001"
    assert p.numero == "001"
    assert p.proceso == "Proceso 1"
    assert p.codigo == "P1"
    assert p.num_db == 3000
    assert p.producto == "Linea A"
    assert p.tipo == "Contador"
    assert p.descripcion == "Contador de piezas"
    assert p.comentario_db == "DB comentario"
    assert p.visibilidad == "Si"
    assert p.num_lista == 5
    assert p.txt_lista == "Lista seleccion"


def test_num_lista_acepta_int():
    """``num_lista`` acepta ``int`` (indice real de la lista HMI)."""
    p = DataParamIntPLC(
        uid="PI_1_001", numero="001", proceso="P", codigo="P",
        num_db=3000, producto="L", tipo="T", descripcion="D",
        comentario_db="C", visibilidad="Si", num_lista=42, txt_lista="X",
    )
    assert p.num_lista == 42
    assert isinstance(p.num_lista, int)


def test_num_lista_acepta_str_marcador():
    """``num_lista`` acepta ``str`` para marcadores semanticos (``"N/A"``)."""
    p = DataParamIntPLC(
        uid="PI_1_001", numero="001", proceso="P", codigo="P",
        num_db=3000, producto="L", tipo="T", descripcion="D",
        comentario_db="C", visibilidad="Si", num_lista="N/A", txt_lista="X",
    )
    assert p.num_lista == "N/A"
    assert isinstance(p.num_lista, str)


def test_num_lista_acepta_todos_marcador():
    """``num_lista`` acepta ``"TODOS"`` (marcador de seleccion multiple)."""
    p = DataParamIntPLC(
        uid="PI_1_001", numero="001", proceso="P", codigo="P",
        num_db=3000, producto="L", tipo="T", descripcion="D",
        comentario_db="C", visibilidad="Si", num_lista="TODOS", txt_lista="X",
    )
    assert p.num_lista == "TODOS"


def test_frozen_no_muta():
    """``frozen=True``: asignar un campo levanta ``FrozenInstanceError``."""
    from dataclasses import FrozenInstanceError

    p = DataParamIntPLC(
        uid="PI_1_001", numero="001", proceso="P", codigo="P",
        num_db=3000, producto="L", tipo="T", descripcion="D",
        comentario_db="C", visibilidad="Si", num_lista=0, txt_lista="X",
    )
    with pytest.raises(FrozenInstanceError):
        p.num_db = 9999  # type: ignore[misc]


def test_equality_por_valor():
    """Dos DataParamIntPLC con los mismos campos son iguales."""
    kwargs = dict(
        uid="PI_1_001", numero="001", proceso="P", codigo="P",
        num_db=3000, producto="L", tipo="T", descripcion="D",
        comentario_db="C", visibilidad="Si", num_lista=5, txt_lista="X",
    )
    p1 = DataParamIntPLC(**kwargs)
    p2 = DataParamIntPLC(**kwargs)

    assert p1 == p2
