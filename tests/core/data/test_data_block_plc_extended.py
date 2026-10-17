"""Tests del DTO extendido DataBloquePLC con los 6 campos opcionales."""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from core.data.data_block_plc import DataBloquePLC


def test_construccion_con_campos_extendidos_populados():
    """DataBloquePLC acepta los 10 campos (4 basicos + 6 extendidos populados)."""
    b = DataBloquePLC(
        "DB1_SYS", 1, "DB", "0_Sistema\\DB1_SYS",
        title="Datos del sistema",
        comment="Bloque principal de parametros",
        author="Aketza",
        version="1.4.0",
        programming_language="SCL",
        memory_layout="Optimized",
    )

    assert b.nombre == "DB1_SYS"
    assert b.numero == 1
    assert b.tipo == "DB"
    assert b.ruta == "0_Sistema\\DB1_SYS"
    assert b.title == "Datos del sistema"
    assert b.comment == "Bloque principal de parametros"
    assert b.author == "Aketza"
    assert b.version == "1.4.0"
    assert b.programming_language == "SCL"
    assert b.memory_layout == "Optimized"


def test_campos_extendidos_default_none():
    """Los 6 campos extendidos son ``None`` por default (no se rompen callers viejos)."""
    b = DataBloquePLC("FB_Main", 42, "FB", "Programa\\FB_Main")

    assert b.title is None
    assert b.comment is None
    assert b.author is None
    assert b.version is None
    assert b.programming_language is None
    assert b.memory_layout is None


def test_to_dict_emite_los_10_campos():
    """``to_dict()`` incluye los 6 extendidos aunque sean ``None``; longitud 10."""
    b = DataBloquePLC("OB1", 1, "OB", "")

    snapshot = b.to_dict()

    assert len(snapshot) == 10
    assert snapshot["title"] is None
    assert snapshot["comment"] is None
    assert snapshot["author"] is None
    assert snapshot["version"] is None
    assert snapshot["programming_language"] is None
    assert snapshot["memory_layout"] is None


def test_frozen_con_campos_extendidos():
    """``frozen=True`` sigue valido al intentar mutar campos extendidos."""
    b = DataBloquePLC(
        "FC10", 10, "FC", "Utilidades\\FC10",
        title="Mi titulo",
        comment="Mi comentario",
        author="anonimo",
        version="0.1",
        programming_language="LAD",
        memory_layout="Standard",
    )

    with pytest.raises(FrozenInstanceError):
        b.title = "otro"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        b.programming_language = "STL"  # type: ignore[misc]