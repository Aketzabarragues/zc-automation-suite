"""Tests del handler unificado ``export_blocks``.

Sustituye a ``export_blocks_sd`` (plural sin filtro) y ``export_block``
(singular con filtro). Acepta ``block_names=None`` (todos) o lista (whitelist).

Mantener retro-compat con ``export_block`` legacy: match exacto, case-sensitive.
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


def _block(nombre: str = "X") -> MagicMock:
    b = MagicMock()
    b.get_name.return_value = nombre
    b.export = MagicMock()
    return b


def _setup_with_blocks(block_names: list[str]) -> tuple:
    """Crea portal + project + plc con N bloques (nombres en orden)."""
    plc = MagicMock()
    plc.get_name.return_value = "PLC_1"
    plc.get_program_blocks.return_value = [_block(n) for n in block_names]
    project = MagicMock()
    project.get_plcs.return_value = [plc]
    portal = MagicMock()
    portal.get_project.return_value = project
    return portal, plc


# ---------------------------------------------------------------------------
# Validacion de argumentos
# ---------------------------------------------------------------------------

def test_export_blocks_no_portal_attached_raises():
    with tempfile.TemporaryDirectory() as tmp:
        out = _client().dispatch(
            "export_blocks",
            {"plc_name": "PLC_1", "target_dir": tmp},
        )
    assert out["ok"] is False
    assert "No portal attached" in out["error"]


def test_export_blocks_without_plc_name_raises():
    c = _client()
    c.attach_wrapper(MagicMock())
    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch("export_blocks", {"target_dir": tmp})
    assert out["ok"] is False
    assert "plc_name" in out["error"]


def test_export_blocks_without_target_dir_raises():
    portal, _ = _setup_with_blocks([])
    c = _client()
    c.attach_wrapper(portal)
    out = c.dispatch("export_blocks", {"plc_name": "PLC_1"})
    assert out["ok"] is False
    assert "target_dir" in out["error"]


def test_export_blocks_plc_not_found_raises():
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
            "export_blocks",
            {"plc_name": "PLC_99", "target_dir": tmp},
        )
    assert out["ok"] is False
    assert "PLC" in out["error"]


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------

def test_export_blocks_sin_whitelist_exporta_todos():
    portal, plc = _setup_with_blocks(["DB1", "FC2", "OB1"])
    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_blocks",
            {"plc_name": "PLC_1", "target_dir": tmp},
        )

    assert out["ok"] is True
    assert out["result"]["count"] == 3
    assert sorted(out["result"]["exported_names"]) == ["DB1", "FC2", "OB1"]
    assert out["result"]["skipped_names"] == []
    assert out["result"]["exported_to"] == tmp
    assert plc.get_program_blocks.return_value[0].export.call_count == 1


def test_export_blocks_con_whitelist_exporta_solo_esos():
    portal, plc = _setup_with_blocks(["DB1", "FC2", "OB1", "UDT_X"])
    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_blocks",
            {
                "plc_name": "PLC_1",
                "target_dir": tmp,
                "block_names": ["FC2", "OB1"],
            },
        )

    assert out["ok"] is True
    assert out["result"]["count"] == 2
    assert sorted(out["result"]["exported_names"]) == ["FC2", "OB1"]
    assert out["result"]["skipped_names"] == []
    # Solo FC2 y OB1 deben haber recibido export().
    for block in plc.get_program_blocks.return_value:
        if block.get_name.return_value in ("FC2", "OB1"):
            assert block.export.call_count == 1
        else:
            assert block.export.call_count == 0


def test_export_blocks_whitelist_con_nombre_inexistente_devuelve_skipped():
    portal, _ = _setup_with_blocks(["DB1", "FC2"])
    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_blocks",
            {
                "plc_name": "PLC_1",
                "target_dir": tmp,
                "block_names": ["DB1", "NO_EXISTE"],
            },
        )

    assert out["ok"] is True
    assert out["result"]["count"] == 1
    assert out["result"]["exported_names"] == ["DB1"]
    assert out["result"]["skipped_names"] == ["NO_EXISTE"]


# ---------------------------------------------------------------------------
# Formato SimaticSD
# ---------------------------------------------------------------------------

def test_export_blocks_pasa_export_format_simaticsd():
    portal, plc = _setup_with_blocks(["DB1", "FC2"])
    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_blocks",
            {"plc_name": "PLC_1", "target_dir": tmp},
        )

    assert out["ok"] is True
    for block in plc.get_program_blocks.return_value:
        kwargs = block.export.call_args.kwargs
        assert kwargs.get("export_format") == "SimaticSD"
        assert "target_directory_path" in kwargs
        assert kwargs.get("keep_folder_structure") is False


def test_export_blocks_keep_folder_structure_true_se_preserva():
    portal, plc = _setup_with_blocks(["DB1"])
    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_blocks",
            {
                "plc_name": "PLC_1",
                "target_dir": tmp,
                "keep_folder_structure": True,
            },
        )

    assert out["ok"] is True
    block = plc.get_program_blocks.return_value[0]
    assert block.export.call_args.kwargs.get("keep_folder_structure") is True


# ---------------------------------------------------------------------------
# Retorno
# ---------------------------------------------------------------------------

def test_export_blocks_return_shape():
    portal, _ = _setup_with_blocks(["DB1"])
    c = _client()
    c.attach_wrapper(portal)

    with tempfile.TemporaryDirectory() as tmp:
        out = c.dispatch(
            "export_blocks",
            {"plc_name": "PLC_1", "target_dir": tmp},
        )

    assert out["ok"] is True
    result = out["result"]
    assert set(result.keys()) == {"exported_to", "count", "exported_names", "skipped_names"}
    assert isinstance(result["exported_to"], str)
    assert isinstance(result["count"], int)
    assert isinstance(result["exported_names"], list)
    assert isinstance(result["skipped_names"], list)