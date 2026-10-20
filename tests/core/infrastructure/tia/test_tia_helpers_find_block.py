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


def test_block_path_se_ignora_y_encuentra_por_nombre():
    """``block_path`` se ignora: el lookup es por nombre (TIA es unico)."""
    db1 = _make_block("DB1")
    sistema = _make_group("Sistema", blocks=[db1])
    plc = _make_group("", groups=[sistema])

    # Path que NO corresponde a la jerarquia real (ni "Sistema" ni
    # "Sistema\\Subsistema" existen como grupos). Antes esto reventaba
    # con "no se encontro grupo 'Sistema' en path ...". Ahora el nombre
    # basta para encontrarlo.
    found = _find_block_in_plc(plc, "DB1", "Sistema\\Subsistema")
    assert found is db1

    found = _find_block_in_plc(plc, "DB1", "/Sistema/Inventado")
    assert found is db1


def test_ruta_igual_al_nombre_del_bloque():
    """Reproduce el bug en vivo: ``ruta`` == ``nombre`` del bloque.

    ``DataBloquePLC.ruta`` viene de ``ProgramBlock.get_path()``, cuyo
    formato no es una jerarquia de grupos: para un bloque en la raiz
    puede devolver el propio nombre del bloque. La implementacion
    anterior lo interpretaba como un path de grupos y buscaba un grupo
    llamado "test" que no existia.

    Este test fija ese caso: el bloque esta en la raiz del PLC y su
    ``ruta`` dice "test" (igual que su nombre).
    """
    test_block = _make_block("test")
    plc = _make_group("", blocks=[test_block])

    # Antes: RuntimeError "no se encontro grupo 'test' en path 'test'".
    found = _find_block_in_plc(plc, "test", "test")
    assert found is test_block


def test_nombre_duplicado_devuelve_el_primero():
    """TIA no admite nombres duplicados; si llegan, gana el primero."""
    dup1 = _make_block("DB1")
    dup2 = _make_block("DB1")
    plc = _make_group("", blocks=[dup1, dup2])

    found = _find_block_in_plc(plc, "DB1", "")
    assert found is dup1


def test_bloque_en_grupo_anidado_profundo():
    """Busqueda recursiva atraviesa varios niveles de grupos."""
    db1 = _make_block("DB1")
    leaf = _make_group("Subsistema", blocks=[db1])
    mid = _make_group("Sistema", groups=[leaf])
    plc = _make_group("", groups=[mid])

    found = _find_block_in_plc(plc, "DB1", "")
    assert found is db1
