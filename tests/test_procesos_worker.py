"""Tests de los comandos del worker para sync de comentarios de procesos.

Cubre la integración de ``extra_commands.register(registry)`` con el
``COMMAND_REGISTRY`` del worker genérico: verifica que las 3 keys
``update_proc_comments_db_<kind>`` quedan registradas y que su
handler invoca la cadena esperada (export → updater.update() →
import, con guarda de was_modified).

Patrón de mocking: mockeamos directamente las keys
``"export_block"`` e ``"import_block"`` en el
``COMMAND_REGISTRY`` real (mismo enfoque que
``test_disp_comment_handlers.py``) para evitar el problema del
import-caching de Python con ``patch.dict("sys.modules", ...)``.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from areas.alimentacion.infrastructure.tia import extra_commands
from core.infrastructure.tia import worker_tia


# ── Helpers ──────────────────────────────────────────────────────────────


def _build_minimal_block_files(work_dir: Path, db_name: str) -> None:
    """Escribe un par mínimo .s7dcl + .s7res en ``work_dir`` para que
    el updater no lance FileNotFoundError al invocarse."""
    dcl = work_dir / f"{db_name}.s7dcl"
    res = work_dir / f"{db_name}.s7res"
    dcl.write_text(
        'DATA_BLOCK "DB"\n'
        "    VAR\n"
        '        { S7_MLC := "MLC_arr" }\n'
        "        PReal : Array[1..3] of _.UDT_ZC_PREAL;\n"
        "    END_VAR\n"
        "\n"
        '        { S7_MLC := "MLC_PR_1" }\n'
        "        PReal[1] := ();\n"
        '        { S7_MLC := "MLC_PR_2" }\n'
        "        PReal[2] := ();\n"
        "END_DATA_BLOCK\n",
        encoding="utf-8",
    )
    res.write_text(
        "MultiLingualTexts:\n"
        "  - id: MLC_arr\n"
        "    es-ES: PReal\n"
        "  - id: MLC_PR_1\n"
        "    es-ES: orig_1\n"
        "  - id: MLC_PR_2\n"
        "    es-ES: orig_2\n",
        encoding="utf-8-sig",
    )


# ── Tests ───────────────────────────────────────────────────────────────


def test_register_anhade_las_3_keys_de_procesos() -> None:
    """``register(registry)`` añade las 3 keys ``update_proc_comments_db_<kind>``."""
    registry: dict[str, Any] = {}
    extra_commands.register(registry)
    assert "update_proc_comments_db_preal" in registry
    assert "update_proc_comments_db_pint" in registry
    assert "update_proc_comments_db_alm" in registry
    # También siguen las legacy de dispositivos.
    assert "update_disp_comments_db_ed" in registry
    assert "commit_devices_sync" in registry


def test_handler_preal_invoca_export_updater_import() -> None:
    """Handler de PReal: ``export_block`` → ``ProcesoCommentUpdater.update()
    + save()`` → ``import_block`` (en ese orden, con los args correctos)."""
    COMMAND_REGISTRY = worker_tia.COMMAND_REGISTRY
    with tempfile.TemporaryDirectory() as td:
        work_dir = Path(td)
        _build_minimal_block_files(work_dir, "DB_TEST")

        orig_export = COMMAND_REGISTRY.get("export_block")
        orig_import = COMMAND_REGISTRY.get("import_block")
        mock_export = MagicMock(return_value="ok")
        mock_import = MagicMock(return_value=True)
        COMMAND_REGISTRY["export_block"] = mock_export
        COMMAND_REGISTRY["import_block"] = mock_import

        mock_updater = MagicMock()
        mock_updater.update.return_value.reused = {1: "MLC_PR_1"}
        mock_updater.update.return_value.inserted = {}
        mock_updater.update.return_value.satellite_reused = {}
        mock_updater.update.return_value.satellite_inserted = {}
        mock_updater.update.return_value.total_mlcs_in_res = 5
        mock_updater.was_modified.return_value = True
        mock_updater.save = MagicMock()

        try:
            with patch(
                "areas.alimentacion.infrastructure.sd.proc_comment_updater."
                "ProcesoCommentUpdater",
                return_value=mock_updater,
            ):
                handler = extra_commands.make_cmd_update_proc_comments_db("preal")
                handler(
                    None,  # portal
                    None,  # ts
                    {
                        "plc_name":      "PLC_X",
                        "db_name":       "DB_TEST",
                        "array_name":    "PReal",
                        "slot_map":      {"1": "nuevo_1"},
                        "work_dir":      str(work_dir),
                        "target_folder": "003_Procesos",
                    },
                )
        finally:
            # Restaurar el COMMAND_REGISTRY original.
            if orig_export is None:
                COMMAND_REGISTRY.pop("export_block", None)
            else:
                COMMAND_REGISTRY["export_block"] = orig_export
            if orig_import is None:
                COMMAND_REGISTRY.pop("import_block", None)
            else:
                COMMAND_REGISTRY["import_block"] = orig_import

        # 1) export_block llamado con los args correctos.
        mock_export.assert_called_once()
        exp_args = mock_export.call_args.args[2]
        assert exp_args["plc_name"] == "PLC_X"
        assert exp_args["block_name"] == "DB_TEST"
        assert exp_args["target_dir"] == str(work_dir)
        # 2) ProcesoCommentUpdater construido con array_name correcto.
        assert mock_updater.update.called
        assert mock_updater.save.called
        # 3) import_block llamado (porque was_modified() == True).
        mock_import.assert_called_once()
        imp_args = mock_import.call_args.args[2]
        assert imp_args["plc_name"] == "PLC_X"
        assert imp_args["import_dir"] == str(work_dir)
        assert imp_args["target_folder"] == "003_Procesos"


def test_handler_no_invoca_import_si_no_modified() -> None:
    """Si ``was_modified() == False`` (caso slot_map vacío), el handler
    NO invoca ``import_block`` (evita ensuciar el historial Undo)."""
    COMMAND_REGISTRY = worker_tia.COMMAND_REGISTRY
    with tempfile.TemporaryDirectory() as td:
        work_dir = Path(td)
        _build_minimal_block_files(work_dir, "DB_TEST")

        orig_export = COMMAND_REGISTRY.get("export_block")
        orig_import = COMMAND_REGISTRY.get("import_block")
        mock_export = MagicMock(return_value="ok")
        mock_import = MagicMock(return_value=True)
        COMMAND_REGISTRY["export_block"] = mock_export
        COMMAND_REGISTRY["import_block"] = mock_import

        mock_updater = MagicMock()
        mock_updater.update.return_value.reused = {}
        mock_updater.update.return_value.inserted = {}
        mock_updater.update.return_value.satellite_reused = {}
        mock_updater.update.return_value.satellite_inserted = {}
        mock_updater.update.return_value.total_mlcs_in_res = 5
        mock_updater.was_modified.return_value = False  # NO se modificó
        mock_updater.save = MagicMock()

        try:
            with patch(
                "areas.alimentacion.infrastructure.sd.proc_comment_updater."
                "ProcesoCommentUpdater",
                return_value=mock_updater,
            ):
                handler = extra_commands.make_cmd_update_proc_comments_db("alm")
                handler(
                    None, None,
                    {
                        "plc_name":      "PLC_X",
                        "db_name":       "DB_TEST",
                        "array_name":    "ALM",
                        "slot_map":      {},  # vacío → no hay cambios
                        "work_dir":      str(work_dir),
                        "target_folder": "003_Procesos",
                    },
                )
        finally:
            if orig_export is None:
                COMMAND_REGISTRY.pop("export_block", None)
            else:
                COMMAND_REGISTRY["export_block"] = orig_export
            if orig_import is None:
                COMMAND_REGISTRY.pop("import_block", None)
            else:
                COMMAND_REGISTRY["import_block"] = orig_import

        # export sí se llama (siempre).
        mock_export.assert_called_once()
        # update se llama, save se llama.
        assert mock_updater.update.called
        assert mock_updater.save.called
        # import NO se llama porque was_modified() == False.
        mock_import.assert_not_called()
