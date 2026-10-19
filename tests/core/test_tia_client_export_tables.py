"""Tests del handler unificado ``export_tables`` (FASE 2.6 commit 1).

Sustituye a ``export_plc_tags_xml`` (plural con table_names opcional, usado
por 4 FBs del area) y ``export_tag_table`` (singular legacy, sin
consumidores). Acepta ``table_names=None`` (todas) o lista (whitelist).

Diferencia clave vs blocks/udts: las PlcTagTables NO aceptan
``export_format`` en el wrapper TIA (escriben XML directamente).
"""
from __future__ import annotations

import tempfile
from unittest.mock import MagicMock

from core.infrastructure.tia.tia_loop import SyncTIAClient
from core.infrastructure.tia.tia_commands_catalog import register_all_commands


def _client() -> SyncTIAClient:
    c = SyncTIAClient()
    register_all_commands(c)
    return c


def _table(nombre: str = "X") -> MagicMock:
    t = MagicMock()
    t.get_name.return_value = nombre
    t.export = MagicMock()
    return t


def _setup_with_tables(table_names: list[str]) -> tuple:
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    plc.get_plc_tag_tables.return_value = [_table(n) for n in table_names]
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project
    return portal, plc


# ---------------------------------------------------------------------------
# Validacion de argumentos
# ---------------------------------------------------------------------------

def test_export_tables_no_portal_attached_raises():
    with tempfile.TemporaryDirectory() as tmp:
        out = _client().dispatch(
            "export_tables",
            {"plc_name": "PLC_1", "target_dir": tmp},
        )
    assert out["ok"] is False
    assert "No portal attached" in out["error"]


def test_export_tables_without_plc_name_raises():
    c = _client()
    c.attach_wrapper(MagicMock())
    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch("export_tables", {"target_dir": tmp})
    assert out["ok"] is False
    assert "plc_name" in out["error"]


def test_export_tables_without_target_dir_raises():
    portal, _ = _setup_with_tables([])
    c = _client()
    c.attach_wrapper(portal)
    out = c.dispatch("export_tables", {"plc_name": "PLC_1"})
    assert out["ok"] is False
    assert "target_dir" in out["error"]


def test_export_tables_plc_not_found_raises():
    other = MagicMock(spec=["get_name"])
    other.get_name.return_value = "PLC_OTHER"
    project = MagicMock()
    project.get_plcs.return_value = [other]
    portal = MagicMock()
    portal.get_project.return_value = project

    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_tables",
            {"plc_name": "PLC_99", "target_dir": tmp},
        )
    assert out["ok"] is False
    assert "PLC" in out["error"]


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------

def test_export_tables_sin_whitelist_exporta_todas():
    portal, plc = _setup_with_tables(["T1", "T2", "T3"])
    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_tables",
            {"plc_name": "PLC_1", "target_dir": tmp},
        )

    assert out["ok"] is True
    assert out["result"]["count"] == 3
    assert sorted(out["result"]["exported_names"]) == ["T1", "T2", "T3"]
    assert out["result"]["skipped_names"] == []


def test_export_tables_con_whitelist_exporta_solo_esos():
    portal, plc = _setup_with_tables(["T1", "T2", "T3", "T4"])
    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_tables",
            {
                "plc_name": "PLC_1",
                "target_dir": tmp,
                "table_names": ["T1", "T3"],
            },
        )

    assert out["ok"] is True
    assert out["result"]["count"] == 2
    assert sorted(out["result"]["exported_names"]) == ["T1", "T3"]
    assert out["result"]["skipped_names"] == []
    for table in plc.get_plc_tag_tables.return_value:
        if table.get_name.return_value in ("T1", "T3"):
            assert table.export.call_count == 1
        else:
            assert table.export.call_count == 0


def test_export_tables_whitelist_con_nombre_inexistente_devuelve_skipped():
    portal, _ = _setup_with_tables(["T1", "T2"])
    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_tables",
            {
                "plc_name": "PLC_1",
                "target_dir": tmp,
                "table_names": ["T1", "NO_EXISTE"],
            },
        )

    assert out["ok"] is True
    assert out["result"]["count"] == 1
    assert out["result"]["exported_names"] == ["T1"]
    assert out["result"]["skipped_names"] == ["NO_EXISTE"]


# ---------------------------------------------------------------------------
# Sin export_format (las tablas NO lo aceptan en TIA)
# ---------------------------------------------------------------------------

def test_export_tables_no_pasa_export_format_al_wrapper_tia():
    portal, plc = _setup_with_tables(["T1", "T2"])
    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_tables",
            {"plc_name": "PLC_1", "target_dir": tmp},
        )

    assert out["ok"] is True
    for table in plc.get_plc_tag_tables.return_value:
        kwargs = table.export.call_args.kwargs
        # Tablas no aceptan export_format; verificamos que NO se pasa.
        assert "export_format" not in kwargs, (
            f"export_tables no debe pasar export_format; paso {kwargs}"
        )
        assert "target_directory_path" in kwargs
        assert kwargs.get("keep_folder_structure") is False


def test_export_tables_keep_folder_structure_true_se_preserva():
    portal, plc = _setup_with_tables(["T1"])
    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_tables",
            {
                "plc_name": "PLC_1",
                "target_dir": tmp,
                "keep_folder_structure": True,
            },
        )

    assert out["ok"] is True
    table = plc.get_plc_tag_tables.return_value[0]
    assert table.export.call_args.kwargs.get("keep_folder_structure") is True


# ---------------------------------------------------------------------------
# Retorno
# ---------------------------------------------------------------------------

def test_export_tables_return_shape():
    portal, _ = _setup_with_tables(["T1"])
    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_tables",
            {"plc_name": "PLC_1", "target_dir": tmp},
        )

    assert out["ok"] is True
    result = out["result"]
    assert set(result.keys()) == {"exported_to", "count", "exported_names", "skipped_names"}