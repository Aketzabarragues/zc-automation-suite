"""Tests para ``core.data.data_bloque_cache.DataBloqueCache``.

Fase 3, paso 3.1.2.  Cobertura:
  - defaults razonables al instanciar sin argumentos.
  - mutabilidad (los campos se pueden reasignar; frozen=False).
  - shape de ``to_dict()``.
  - ``scanned_at`` es timezone-aware UTC.
  - ``default_factory`` produce dicts y timestamps independientes
    entre instancias (no hay estado compartido mutable por
    accidente).
  - ``to_dict()`` con bloques reales: cada BloquePLC se serializa
    via su propio ``to_dict()`` con sus 4 campos.
"""
from __future__ import annotations

from datetime import datetime, timezone

from core.data.data_bloque_cache import DataBloqueCache
from core.data.data_bloque_plc import DataBloquePLC


def test_defaults_vacios():
    """DataBloqueCache() sin argumentos produce un cache vacio valido."""
    cache = DataBloqueCache()

    assert cache.blocks == {}
    assert cache.tag_tables == {}
    assert cache.udts == {}
    assert cache.plc_name == ""


def test_scanned_at_es_utc_timezone_aware():
    """``scanned_at`` por defecto es un datetime UTC con tzinfo."""
    cache = DataBloqueCache()

    assert isinstance(cache.scanned_at, datetime)
    assert cache.scanned_at.tzinfo is not None
    assert cache.scanned_at.utcoffset() == timezone.utc.utcoffset(
        cache.scanned_at
    )


def test_scanned_at_independiente_entre_instancias():
    """``default_factory`` evita compartir timestamp entre instancias."""
    c1 = DataBloqueCache()
    c2 = DataBloqueCache()

    # No exigimos diferencia en nanosegundos, pero en la practica
    # dos llamadas a datetime.now() producen timestamps distintos
    # salvo carrera imposible.  Verificamos que NO comparten
    # identidad (regla de oro de default_factory).
    assert c1.scanned_at is not c2.scanned_at


def test_dictionaries_independientes_entre_instancias():
    """Los 3 dicts son independientes (no se comparten por defecto)."""
    c1 = DataBloqueCache()
    c2 = DataBloqueCache()

    assert c1.blocks is not c2.blocks
    assert c1.tag_tables is not c2.tag_tables
    assert c1.udts is not c2.udts

    # Mutar uno no afecta al otro.
    c1.blocks["DB1"] = DataBloquePLC("DB1", 1, "DB", "Sistema\\DB1")
    assert c2.blocks == {}


def test_mutabilidad_campos_primitivos():
    """``frozen=False``: puedo reasignar campos primitivos."""
    cache = DataBloqueCache()

    cache.plc_name = "PLC_1500_01"
    assert cache.plc_name == "PLC_1500_01"

    nuevo_ts = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)
    cache.scanned_at = nuevo_ts
    assert cache.scanned_at == nuevo_ts


def test_to_dict_shape_vacio():
    """``to_dict()`` de un cache vacio emite los 5 campos esperados."""
    cache = DataBloqueCache()
    snapshot = cache.to_dict()

    assert set(snapshot.keys()) == {
        "plc_name",
        "blocks",
        "tag_tables",
        "udts",
        "scanned_at",
    }
    assert snapshot["plc_name"] == ""
    assert snapshot["blocks"] == []
    assert snapshot["tag_tables"] == []
    assert snapshot["udts"] == []
    # scanned_at se serializa a ISO-8601.
    assert isinstance(snapshot["scanned_at"], str)
    assert "T" in snapshot["scanned_at"]  # separador fecha-hora


def test_to_dict_con_bloques_reales():
    """``to_dict()`` serializa cada DataBloquePLC via su propio to_dict()."""
    bloque = DataBloquePLC("DB1_SYS", 1, "DB", "0_Sistema\\DB1_SYS")
    tag_table = DataBloquePLC("Tags_Motor", 0, "OTHER", "0_Sistema\\Tags_Motor")
    udt = DataBloquePLC("UDT_Motor", 1, "UDT", "Tipos\\UDT_Motor")

    cache = DataBloqueCache(
        blocks={DataBloquePLC.normalize_name(bloque.nombre): bloque},
        tag_tables={DataBloquePLC.normalize_name(tag_table.nombre): tag_table},
        udts={DataBloquePLC.normalize_name(udt.nombre): udt},
        plc_name="PLC_1500_01",
    )

    snapshot = cache.to_dict()

    assert snapshot["plc_name"] == "PLC_1500_01"
    assert snapshot["blocks"] == [bloque.to_dict()]
    assert snapshot["tag_tables"] == [tag_table.to_dict()]
    assert snapshot["udts"] == [udt.to_dict()]
