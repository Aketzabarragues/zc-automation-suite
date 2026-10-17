"""Tests de _scan_block_group_recursive (Fase 4 / paso 4.1.2a5b).

Walker recursivo que usa scan_blocks para extraer bloques + UDTs.

Oct-2026: el walker ahora delega la clasificacion del tipo en
``classify_block`` (heuristico de huella digital sobre el SDK), no en el
regex ``DataBloquePLC.detect_tipo``. Por tanto, los mocks de bloque deben
exponer ``get_property("ProgrammingLanguage")`` y ``get_properties()``
para que el heuristico pueda clasificar. El helper ``_block`` infiere el
tipo desde el prefijo del nombre y configura los mocks acorde (igual que
hace TIA Portal real segun el smoke oct-2026).
"""
from __future__ import annotations

import re
from unittest.mock import MagicMock

from core.infrastructure.tia.tia_helpers import _scan_block_group_recursive


# Lenguajes de codigo que devuelve TIA para FC/FB/OB (smoke oct-2026).
_LANG_POR_PREF = {"FB": "SCL", "FC": "SCL", "OB": "LAD", "UDT": "SCL"}


def _make_block_with_class(class_name: str, nombre: str, ruta: str = ""):
    """Crea un mock block con una clase Python custom (no MagicMock).

    Necesario para UDTs: ``classify_block`` chequea ``type(b).__name__``,
    y MagicMock protege su ``__class__`` (no se puede asignar). Solucion:
    crear la clase con ``type()`` y delegar via un mock interno.
    """
    inner = MagicMock(spec=["get_property", "get_properties", "get_path"] if ruta else ["get_property", "get_properties"])
    inner.get_property.return_value = None
    inner.get_properties.return_value = []
    if ruta:
        inner.get_path.return_value = ruta

    def get_property(self, *a, **kw):
        return inner.get_property(*a, **kw)

    def get_properties(self):
        return inner.get_properties()

    def get_path(self):
        return inner.get_path()

    cls = type(
        class_name,
        (object,),
        {
            "get_property": get_property,
            "get_properties": get_properties,
            "get_path": get_path,
        },
    )
    instance = cls()
    instance.get_name = lambda: nombre  # MagicMock tambien expone get_name
    instance._inner = inner
    return instance


def _block(nombre: str, ruta: str = ""):
    """Crea un mock block con la spec necesaria para el heuristico.

    Configura ``get_property("ProgrammingLanguage")`` y
    ``get_properties()`` segun el prefijo del nombre, replicando lo que
    hace TIA Portal real:
      - DB:   ProgrammingLanguage == "DB"
      - FB/FC/UDT: ProgrammingLanguage == lenguaje de codigo (SCL/LAD/etc)
      - OB:   ProgrammingLanguage == lenguaje de codigo + SecondaryType en props
      - OTROS: ProgrammingLanguage == None, props == []
    """
    spec = ["get_name", "get_property", "get_properties"]
    if ruta:
        spec.append("get_path")
    b = MagicMock(spec=spec)
    b.get_name.return_value = nombre
    if ruta:
        b.get_path.return_value = ruta

    prefijo = re.match(r"^(DB|FB|FC|OB|UDT)(\d+)", nombre, re.IGNORECASE)
    if prefijo:
        p = prefijo.group(1).upper()
        if p == "DB":
            b.get_property.return_value = "DB"
            b.get_properties.return_value = []
        elif p == "OB":
            b.get_property.return_value = "LAD"
            b.get_properties.return_value = ["SecondaryType"]
        elif p == "FB":
            # FB tiene ISMultiInstanceCapable (unica discriminante vs FC).
            b.get_property.return_value = _LANG_POR_PREF[p]
            b.get_properties.return_value = ["ISMultiInstanceCapable"]
        elif p == "UDT":
            # UDTs tienen clase Python UserDataType (smoke oct-2026).
            # ``classify_block`` distingue por ``type(b).__name__`` asi que
            # hay que recrear el mock con la clase custom (MagicMock
            # protege su ``__class__`` y no se puede asignar).
            return _make_block_with_class("UserDataType_subclass", nombre, ruta)
        else:  # FC
            b.get_property.return_value = _LANG_POR_PREF[p]
            b.get_properties.return_value = []
    else:
        # Nombre sin prefijo estandar (smoke oct-2026: _borrar, Documentacion).
        # El heuristico real resuelve por huella digital; en estos tests lo
        # dejamos como "no clasificado" (OTHER) porque son casos viejos del
        # regex que ahora son defensivos. Tests especificos de la
        # clasificacion real viven en test_tia_block_classifier.py.
        b.get_property.return_value = None
        b.get_properties.return_value = []
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
        {
            "nombre": "DB1",
            "numero": 1,
            "tipo": "DB",
            "ruta": "",
            "title": None,
            "comment": None,
            "author": None,
            "version": None,
            "programming_language": None,
            "memory_layout": None,
        },
        {
            "nombre": "FB2",
            "numero": 2,
            "tipo": "FB",
            "ruta": "/ruta/FB2",
            "title": None,
            "comment": None,
            "author": None,
            "version": None,
            "programming_language": None,
            "memory_layout": None,
        },
        {
            "nombre": "OB1",
            "numero": 1,
            "tipo": "OB",
            "ruta": "",
            "title": None,
            "comment": None,
            "author": None,
            "version": None,
            "programming_language": None,
            "memory_layout": None,
        },
    ]


def test_walker_returns_other_tipo_for_non_prefixed_names():
    """Nombres sin prefijo estandar caen a OTHER (defensivo del heuristico).

    Antes (regex simple) esto era un bug real para bloques como ``_borrar``.
    Ahora (heuristico) se sigue cayendo a OTHER si las props no ayudan,
    pero el helper ``_block`` los mockea sin props para reflejar el caso
    defensivo. Casos como ``_borrar`` (DB por ``ProgrammingLanguage == "DB"``)
    los cubre ``test_tia_block_classifier.py``.
    """
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
    """El prefijo del nombre se matchea case-insensitive.

    db1/Db1/DB1 son bloques del mismo tipo (DB) para TIA, asi que el
    numero se extrae igual. La clasificacion final del tipo depende del
    heuristico (mock props abajo -> DB), no del prefijo.
    """
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
    block_bad = MagicMock(spec=["get_name"])
    block_bad.get_name.side_effect = UnicodeDecodeError("ascii", b"\xff", 0, 1, "x")
    block_good = _block("DB1")

    result = _scan_block_group_recursive(_group([block_bad, block_good]))
    assert result == [
        {
            "nombre": "DB1",
            "numero": 1,
            "tipo": "DB",
            "ruta": "",
            "title": None,
            "comment": None,
            "author": None,
            "version": None,
            "programming_language": None,
            "memory_layout": None,
        }
    ]


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
