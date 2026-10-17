"""Tests para ``core.infrastructure.tia.tia_helpers._find_block_in_plc``.

Mockeamos la jerarquía de ``Plc`` + ``Groups`` + ``PlcBlock`` con
``MagicMock`` siguiendo el patrón de ``_scan_block_group_recursive``.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.infrastructure.tia.tia_helpers import _find_block_in_plc


def _make_block(name):
    b = MagicMock()
    b.name = name
    return b


def _make_group(name, blocks=None, groups=None):
    g = MagicMock()
    g.name = name
    g.get_program_blocks.return_value = list(blocks or [])
    g.get_groups.return_value = list(groups or [])
    return g


def test_happy_path_block_en_raiz():
    """Bloque en nivel raíz del PLC, path vacío."""
    db1 = _make_block("DB1")
    fb2 = _make_block("FB2")
    plc = _make_group("", blocks=[db1, fb2])

    found = _find_block_in_plc(plc, "DB1", "")
    assert found is db1


def test_happy_path_block_en_subcarpeta():
    """Bloque dentro de grupo 'Sistema', path='Sistema'."""
    db1 = _make_block("DB1")
    sistema = _make_group("Sistema", blocks=[db1])
    plc = _make_group("", groups=[sistema])

    found = _find_block_in_plc(plc, "DB1", "Sistema")
    assert found is db1


def test_block_no_encontrado_raises_runtime_error():
    """Bloque que no está en el path indicado → RuntimeError."""
    plc = _make_group("", blocks=[_make_block("DB1")])

    with pytest.raises(RuntimeError, match="no se encontró bloque"):
        _find_block_in_plc(plc, "FB_Fantasma", "")


def test_path_no_encontrado_raises_runtime_error():
    """Path jerárquico donde un segmento intermedio no existe → RuntimeError."""
    plc = _make_group("", groups=[])

    with pytest.raises(RuntimeError, match="no se encontró grupo"):
        _find_block_in_plc(plc, "DB1", "Sistema\\Subsistema")


def test_normaliza_separadores_mixtos():
    """Acepta path con '/' que se normaliza a '\\' (TIA a veces usa ambos)."""
    db1 = _make_block("DB1")
    sistema = _make_group("Sistema", blocks=[db1])
    plc = _make_group("", groups=[sistema])

    with pytest.raises(RuntimeError):
        _find_block_in_plc(plc, "DB1", "Sistema/Subcarpeta")

    found = _find_block_in_plc(plc, "DB1", "/Sistema")
    assert found is db1
