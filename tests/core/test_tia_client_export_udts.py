"""Tests del handler unificado ``export_udts`` (FASE 2.6 commit 1).

Sustituye a ``export_udts_sd`` (plural sin filtro, sin consumidores en
produccion) y al inline-equivalente del singular legacy. Acepta
``udt_names=None`` (todos) o lista (whitelist).
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


def _udt(nombre: str = "X") -> MagicMock:
    u = MagicMock()
    u.get_name.return_value = nombre
    u.export = MagicMock()
    return u


def _setup_with_udts(udt_names: list[str]) -> tuple:
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    plc.get_user_data_types.return_value = [_udt(n) for n in udt_names]
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project
    return portal, plc


# ---------------------------------------------------------------------------
# Validacion de argumentos
# ---------------------------------------------------------------------------

def test_export_udts_no_portal_attached_raises():
    with tempfile.TemporaryDirectory() as tmp:
        out = _client().dispatch(
            "export_udts",
            {"plc_name": "PLC_1", "target_dir": tmp},
        )
    assert out["ok"] is False
    assert "No portal attached" in out["error"]


def test_export_udts_without_plc_name_raises():
    c = _client()
    c.attach_wrapper(MagicMock())
    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch("export_udts", {"target_dir": tmp})
    assert out["ok"] is False
    assert "plc_name" in out["error"]


def test_export_udts_without_target_dir_raises():
    portal, _ = _setup_with_udts([])
    c = _client()
    c.attach_wrapper(portal)
    out = c.dispatch("export_udts", {"plc_name": "PLC_1"})
    assert out["ok"] is False
    assert "target_dir" in out["error"]


def test_export_udts_plc_not_found_raises():
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
            "export_udts",
            {"plc_name": "PLC_99", "target_dir": tmp},
        )
    assert out["ok"] is False
    assert "PLC" in out["error"]


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------

def test_export_udts_sin_whitelist_exporta_todos():
    portal, plc = _setup_with_udts(["UDT_A", "UDT_B", "UDT_C"])
    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_udts",
            {"plc_name": "PLC_1", "target_dir": tmp},
        )

    assert out["ok"] is True
    assert out["result"]["count"] == 3
    assert sorted(out["result"]["exported_names"]) == ["UDT_A", "UDT_B", "UDT_C"]
    assert out["result"]["skipped_names"] == []


def test_export_udts_con_whitelist_exporta_solo_esos():
    portal, plc = _setup_with_udts(["UDT_A", "UDT_B", "UDT_C"])
    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_udts",
            {
                "plc_name": "PLC_1",
                "target_dir": tmp,
                "udt_names": ["UDT_A", "UDT_C"],
            },
        )

    assert out["ok"] is True
    assert out["result"]["count"] == 2
    assert sorted(out["result"]["exported_names"]) == ["UDT_A", "UDT_C"]
    assert out["result"]["skipped_names"] == []
    for udt in plc.get_user_data_types.return_value:
        if udt.get_name.return_value in ("UDT_A", "UDT_C"):
            assert udt.export.call_count == 1
        else:
            assert udt.export.call_count == 0


def test_export_udts_whitelist_con_nombre_inexistente_devuelve_skipped():
    portal, _ = _setup_with_udts(["UDT_A", "UDT_B"])
    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_udts",
            {
                "plc_name": "PLC_1",
                "target_dir": tmp,
                "udt_names": ["UDT_A", "NO_EXISTE"],
            },
        )

    assert out["ok"] is True
    assert out["result"]["count"] == 1
    assert out["result"]["exported_names"] == ["UDT_A"]
    assert out["result"]["skipped_names"] == ["NO_EXISTE"]


# ---------------------------------------------------------------------------
# Formato SimaticSD
# ---------------------------------------------------------------------------

def test_export_udts_pasa_export_format_simaticsd():
    portal, plc = _setup_with_udts(["UDT_A", "UDT_B"])
    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_udts",
            {"plc_name": "PLC_1", "target_dir": tmp},
        )

    assert out["ok"] is True
    for udt in plc.get_user_data_types.return_value:
        kwargs = udt.export.call_args.kwargs
        assert kwargs.get("export_format") == "SimaticSD"
        assert "target_directory_path" in kwargs
        assert kwargs.get("keep_folder_structure") is False


# ---------------------------------------------------------------------------
# Retorno
# ---------------------------------------------------------------------------

def test_export_udts_return_shape():
    portal, _ = _setup_with_udts(["UDT_A"])
    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_udts",
            {"plc_name": "PLC_1", "target_dir": tmp},
        )

    assert out["ok"] is True
    result = out["result"]
    assert set(result.keys()) == {"exported_to", "count", "exported_names", "skipped_names"}