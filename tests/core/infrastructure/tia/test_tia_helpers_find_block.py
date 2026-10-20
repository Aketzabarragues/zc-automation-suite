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
    # ``_find_block_in_plc`` lee ``b.get_name()`` via ``_safe_get_block_name``
    # (consistente con ``_h_export_block`` y ``_scan_block_group_recursive``).
    # El atributo ``.name`` queda como fallback legacy para wrappers que
    # lo expongan directamente sin el metodo SDK.
    b.get_name.return_value = name
    b.name = name
    return b


def _make_group(name, blocks=None, groups=None):
    g = MagicMock()
    # ``_find_block_in_plc`` lee ``g.get_name()`` via ``_safe_get_block_name``
    # (consistente con la lectura de bloques, mismo fix que commit 8c).
    # ``.name`` se mantiene como fallback legacy.
    g.get_name.return_value = name
    g.name = name
    g.get_program_blocks.return_value = list(blocks or [])
    g.get_groups.return_value = list(groups or [])
    return g


def test_happy_path_block_en_raiz():
    """Bloque en nivel raíz del PLC."""
    db1 = _make_block("DB1")
    fb2 = _make_block("FB2")
    plc = _make_group("", blocks=[db1, fb2])

    found = _find_block_in_plc(plc, "DB1")
    assert found is db1


def test_happy_path_block_en_subcarpeta():
    """Bloque dentro del grupo 'Sistema'."""
    db1 = _make_block("DB1")
    sistema = _make_group("Sistema", blocks=[db1])
    plc = _make_group("", groups=[sistema])

    found = _find_block_in_plc(plc, "DB1")
    assert found is db1


def test_block_no_encontrado_raises_runtime_error():
    """Bloque inexistente -> RuntimeError."""
    plc = _make_group("", blocks=[_make_block("DB1")])

    with pytest.raises(RuntimeError, match="no se encontró bloque"):
        _find_block_in_plc(plc, "FB_Fantasma")


def test_bloque_en_raiz_con_nombre_no_convencional():
    """Bloque en la raiz cuyo nombre no parece una ruta.

    El lookup no navega por grupos, asi que un nombre sin prefijo
    numerico se localiza igual que cualquier otro.
    """
    test_block = _make_block("test")
    plc = _make_group("", blocks=[test_block])

    found = _find_block_in_plc(plc, "test")
    assert found is test_block


def test_nombre_duplicado_devuelve_el_primero():
    """TIA no admite nombres duplicados; si llegan, gana el primero."""
    dup1 = _make_block("DB1")
    dup2 = _make_block("DB1")
    plc = _make_group("", blocks=[dup1, dup2])

    found = _find_block_in_plc(plc, "DB1")
    assert found is dup1


def test_bloque_en_grupo_anidado_profundo():
    """Busqueda recursiva atraviesa varios niveles de grupos."""
    db1 = _make_block("DB1")
    leaf = _make_group("Subsistema", blocks=[db1])
    mid = _make_group("Sistema", groups=[leaf])
    plc = _make_group("", groups=[mid])

    found = _find_block_in_plc(plc, "DB1")
    assert found is db1


def test_bloque_en_hoja_de_arbol_profundo():
    """Bloque al final de una rama profunda, junto a grupos sin bloques."""
    target = _make_block("FC16_CONTROL")
    leaf = _make_group("1_Documentado", blocks=[target])
    mid = _make_group("ZC_Controles", groups=[leaf])
    dead = _make_group("Sin_Bloques", blocks=[], groups=[])
    plc = _make_group("", groups=[dead, mid])

    found = _find_block_in_plc(plc, "FC16_CONTROL")
    assert found is target


def test_no_usa_get_path_del_bloque():
    """El lookup compara solo ``get_name()``.

    ``ProgramBlock.get_path()`` devuelve la jerarquia de grupos (``""``
    en la raiz). Si el lookup la interpretase como grupos a los que
    navegar, un bloque en la raiz no se encontraria nunca.
    """
    db1 = _make_block("DB1")
    db1.get_path.return_value = ""
    plc = _make_group("", blocks=[db1])

    found = _find_block_in_plc(plc, "DB1")
    assert found is db1
    db1.get_path.assert_not_called()