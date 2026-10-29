"""Tests de happy paths y defensive fallbacks de _h_scan_blocks (4.1.2a5c2)."""
from __future__ import annotations

import re
from unittest.mock import MagicMock

from core.infrastructure.tia.tia_loop import (
    SyncTIAClient)
from core.infrastructure.tia.tia_commands_catalog import register_all_commands


def _client():
    c = SyncTIAClient()
    register_all_commands(c)
    return c


def _block(nombre: str):
    """Mock de bloque TIA con la spec necesaria para el heuristico de clasificacion.

    Configura ``get_property("ProgrammingLanguage")`` y
    ``get_properties()`` segun el prefijo del nombre (smoke).
    Para nombres sin prefijo estandar, deja props vacias (clasifica OTHER).

    Importante: usa ``side_effect`` para ``get_property`` (no ``return_value``
    crudo) porque ``_extract_extended_properties`` llama con varios nombres
    (``HeaderName``/``HeaderAuthor``/etc). Solo devolvemos valor para
    ``ProgrammingLanguage`` (la unica que el heuristico de ``classify_block``
    lee); el resto retorna ``None`` (header nunca release), igual que el
    walker test de ``test_tia_client_walker.py``.
    """
    import re as _re
    b = MagicMock(spec=["get_name", "get_property", "get_properties"])
    b.get_name.return_value = nombre
    prefijo = _re.match(r"^(DB|FB|FC|OB|UDT)(\d+)", nombre, _re.IGNORECASE)

    def _prop_getter(v):
        def _get(name, **kw):
            return v if name == "ProgrammingLanguage" else None
        return _get

    if prefijo:
        p = prefijo.group(1).upper()
        if p == "DB":
            b.get_property.side_effect = _prop_getter("DB")
            b.get_properties.return_value = []
        elif p == "OB":
            b.get_property.side_effect = _prop_getter("LAD")
            b.get_properties.return_value = ["SecondaryType"]
        elif p == "FB":
            # FB tiene ISMultiInstanceCapable (unica discriminante vs FC).
            b.get_property.side_effect = _prop_getter("SCL")
            b.get_properties.return_value = ["ISMultiInstanceCapable"]
        elif p == "UDT":
            # UDTs tienen clase Python UserDataType (smoke).
            b = MagicMock(spec=["get_name", "get_property", "get_properties"])
            b.__class__ = type("UserDataType_subclass", (object,), {})
            b.get_name.return_value = nombre
            b.get_property.side_effect = _prop_getter(None)
            b.get_properties.return_value = []
            return b
        else:  # FC
            b.get_property.side_effect = _prop_getter("SCL")
            b.get_properties.return_value = []
    else:
        b.get_property.side_effect = _prop_getter(None)
        b.get_properties.return_value = []
    return b


def test_scan_blocks_happy_path_returns_full_payload():
    target_plc = MagicMock()
    target_plc.get_program_blocks.return_value = [_block("DB1"), _block("FB2")]
    target_plc.get_plc_tag_tables.return_value = [_block("TablaTags_1"), _block("TablaTags_2")]
    target_plc.get_user_data_types.return_value = [_block("UDT10")]

    project = MagicMock()
    project.get_plcs.return_value = [target_plc]
    target_plc.get_name.return_value = "PLC_1"

    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("scan_blocks", {"plc_name": "PLC_1"})
    assert out["ok"] is True
    result = out["result"]

    assert result["plc_name"] == "PLC_1"
    assert len(result["blocks"]) == 2
    assert result["blocks"][0]["nombre"] == "DB1"
    assert result["blocks"][1]["nombre"] == "FB2"
    assert len(result["tag_tables"]) == 2
    assert result["tag_tables"][0]["nombre"] == "TablaTags_1"
    assert len(result["udts"]) == 1
    assert result["udts"][0]["nombre"] == "UDT10"

    # scanned_at es ISO 8601.
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", result["scanned_at"])


def test_scan_blocks_tag_tables_failure_returns_empty_not_error():
    target_plc = MagicMock()
    target_plc.get_program_blocks.return_value = [_block("DB1")]
    target_plc.get_plc_tag_tables.side_effect = RuntimeError("COM transient")
    target_plc.get_user_data_types.return_value = []

    project = MagicMock()
    project.get_plcs.return_value = [target_plc]
    target_plc.get_name.return_value = "PLC_1"

    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("scan_blocks", {"plc_name": "PLC_1"})
    assert out["ok"] is True
    assert out["result"]["blocks"] == [
        {
            "nombre": "DB1",
            "numero": 1,
            "tipo": "DB",
            "ruta": "",
            "title": None,
            "comment": None,
            "author": None,
            "version": None,
            "programming_language": "DB",
            "memory_layout": None,
        }
    ]
    assert out["result"]["tag_tables"] == []
    assert out["result"]["udts"] == []


def test_scan_blocks_udts_failure_returns_empty_not_error():
    """Si TIA no expone get_user_data_types -> udts=[] y sigue."""
    target_plc = MagicMock()
    target_plc.get_program_blocks.return_value = [_block("DB1")]
    target_plc.get_plc_tag_tables.return_value = []
    target_plc.get_user_data_types.side_effect = AttributeError(
        "method not exposed"
    )

    project = MagicMock()
    project.get_plcs.return_value = [target_plc]
    target_plc.get_name.return_value = "PLC_1"

    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("scan_blocks", {"plc_name": "PLC_1"})
    assert out["ok"] is True
    assert out["result"]["udts"] == []


def test_scan_blocks_empty_plc_returns_empty_lists():
    target_plc = MagicMock()
    target_plc.get_program_blocks.return_value = []
    target_plc.get_plc_tag_tables.return_value = []
    target_plc.get_user_data_types.return_value = []

    project = MagicMock()
    project.get_plcs.return_value = [target_plc]
    target_plc.get_name.return_value = "PLC_1"

    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("scan_blocks", {"plc_name": "PLC_1"})
    assert out["ok"] is True
    assert out["result"]["blocks"] == []
    assert out["result"]["tag_tables"] == []
    assert out["result"]["udts"] == []


def test_scan_blocks_extrae_5_props_extendidas_desde_get_property():
    """El scan extrae las 5 props extendidas via ``_extract_extended_properties``.

    Caso real (smoke): un bloque DB1_SYS con Author/Version/Lang/
    MemLayout pobladas en TIA debe llegar al payload con esas 5 props
    NO-Nulas. Antes del fix, el handler ``_h_scan_blocks`` usaba una
    copia de ``_scan_block_group_recursive`` que omitia esa llamada;
    las 4 props salian como ``None`` y la UI mostraba ``---``.
    """
    block_real = MagicMock(spec=["get_name", "get_property", "get_properties"])
    block_real.get_name.return_value = "DB1_SYS"
    # ``_extract_extended_properties`` llama con name=HeaderName/
    # HeaderAuthor/HeaderVersion/ProgrammingLanguage/MemoryLayout.
    props = {
        "HeaderName": "Datos de sistema",
        "HeaderAuthor": "ABH",
        "HeaderVersion": "0.1",
        "ProgrammingLanguage": "LAD",
        "MemoryLayout": "Optimized",
    }
    block_real.get_property.side_effect = lambda name, **kw: props.get(name)
    block_real.get_properties.return_value = []

    target_plc = MagicMock()
    target_plc.get_program_blocks.return_value = [block_real]
    target_plc.get_plc_tag_tables.return_value = []
    target_plc.get_user_data_types.return_value = []

    project = MagicMock()
    project.get_plcs.return_value = [target_plc]
    target_plc.get_name.return_value = "PLC_1"

    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    out = c.dispatch("scan_blocks", {"plc_name": "PLC_1"})
    assert out["ok"] is True

    block = out["result"]["blocks"][0]
    assert block["nombre"] == "DB1_SYS"
    assert block["author"] == "ABH"
    assert block["version"] == "0.1"
    assert block["programming_language"] == "LAD"
    assert block["memory_layout"] == "Optimized"
    assert block["title"] == "Datos de sistema"
