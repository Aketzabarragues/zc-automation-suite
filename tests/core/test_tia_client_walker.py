"""Tests de _scan_block_group_recursive (Fase 4 / paso 4.1.2a5b).

Walker recursivo que usa scan_blocks para extraer bloques + UDTs.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from core.infrastructure.tia_client import _scan_block_group_recursive


def _block(nombre: str, ruta: str = ""):
    """Crea un mock block con get_name y opcionalmente get_path.

    Usa spec para no auto-generar atributos no deseados (MagicMock
    auto-proviene cualquier atributo, lo que rompe hasattr checks).
    """
    if ruta:
        b = MagicMock(spec=["get_name", "get_path"])
        b.get_name.return_value = nombre
        b.get_path.return_value = ruta
    else:
        b = MagicMock(spec=["get_name"])
        b.get_name.return_value = nombre
    return b


def _group(blocks=None, sub_groups=None):
    """Crea un mock group con get_blocks y opcionalmente get_groups."""
    if sub_groups is not None:
        g = MagicMock(spec=["get_blocks", "get_groups"])
        g.get_blocks.return_value = blocks or []
        g.get_groups.return_value = sub_groups
    else:
        g = MagicMock(spec=["get_blocks"])
        g.get_blocks.return_value = blocks or []
    return g


def test_walker_returns_empty_when_group_has_no_blocks():
    assert _scan_block_group_recursive(_group()) == []


def test_walker_returns_dicts_in_bloque_plc_shape():
    blocks = [_block("DB1"), _block("FB2", "/ruta/FB2"), _block("OB1")]
    result = _scan_block_group_recursive(_group(blocks))

    assert result == [
        {"nombre": "DB1", "numero": 1, "tipo": "DB", "ruta": ""},
        {"nombre": "FB2", "numero": 2, "tipo": "FB", "ruta": "/ruta/FB2"},
        {"nombre": "OB1", "numero": 1, "tipo": "OB", "ruta": ""},
    ]


def test_walker_returns_other_tipo_for_non_prefixed_names():
    blocks = [_block("MiGrupo"), _block("Custom_Block")]
    result = _scan_block_group_recursive(_group(blocks))

    assert all(b["tipo"] == "OTHER" for b in result)
    assert all(b["numero"] == 0 for b in result)


def test_walker_extracts_numero_from_prefixed_names():
    blocks = [_block("DB100"), _block("FB200"), _block("FC300"), _block("OB1"), _block("UDT50")]
    result = _scan_block_group_recursive(_group(blocks))

    assert [b["numero"] for b in result] == [100, 200, 300, 1, 50]
    assert [b["tipo"] for b in result] == ["DB", "FB", "FC", "OB", "UDT"]


def test_walker_is_case_insensitive_for_tipo_detection():
    blocks = [_block("db1"), _block("Db1"), _block("DB1")]
    result = _scan_block_group_recursive(_group(blocks))
    assert all(b["tipo"] == "DB" for b in result)


def test_walker_recurses_into_subgroups():
    sub_group = _group([_block("FB_Sub")])
    top = _group(blocks=[_block("DB_Top")], sub_groups=[sub_group])

    result = _scan_block_group_recursive(top)
    nombres = [b["nombre"] for b in result]
    assert nombres == ["DB_Top", "FB_Sub"]


def test_walker_skips_blocks_with_unicode_decode_error_in_name():
    block_bad = MagicMock()
    block_bad.get_name.side_effect = UnicodeDecodeError("ascii", b"\xff", 0, 1, "x")
    block_good = _block("DB1")

    result = _scan_block_group_recursive(_group([block_bad, block_good]))
    assert result == [{"nombre": "DB1", "numero": 1, "tipo": "DB", "ruta": ""}]


def test_walker_returns_empty_when_get_blocks_raises():
    """TIA lanza COM/RPC al listar bloques -> walker devuelve []."""
    bad_group = MagicMock()
    bad_group.get_blocks.side_effect = RuntimeError("COM transient")

    assert _scan_block_group_recursive(bad_group) == []


def test_walker_accepts_plain_iterable():
    """Si no hay get_blocks ni Blocks, intenta __iter__."""
    blocks = [_block("DB1"), _block("FB2")]

    class IterGroup:
        def __iter__(self):
            return iter(blocks)

    result = _scan_block_group_recursive(IterGroup())
    assert len(result) == 2
    assert [b["nombre"] for b in result] == ["DB1", "FB2"]


def test_walker_returns_empty_for_unknown_object():
    """Objeto sin get_blocks/Blocks/__iter__ -> [] sin explotar."""
    result = _scan_block_group_recursive(object())
    assert result == []
