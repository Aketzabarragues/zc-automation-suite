"""Tests del handler de comentarios del worker.

Mockeamos ``export_block`` e ``import_block`` en el ``COMMAND_REGISTRY``
para no tocar TIA. El test verifica que el handler:
  - invoca export/import con los args correctos.
  - devuelve el ``DispCommentResult`` populado.
  - falla con args incompletos.
  - propaga excepciones (el batch hará rollback).
  - lee la carpeta del config (no hardcoded).
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Cargar worker_tia sin ejecutar su ``main()`` (que requiere siemens_tia_scripting).
worker_tia = importlib.import_module("core.infrastructure.tia.worker_tia")
COMMAND_REGISTRY: dict = worker_tia.COMMAND_REGISTRY


@pytest.fixture(autouse=True)
def mock_export_import_blocks() -> None:
    """Sustituye ``export_block`` e ``import_block`` con MagicMocks.

    Restaurar el original al final de cada test.
    """
    orig_export = COMMAND_REGISTRY["export_block"]
    orig_import = COMMAND_REGISTRY["import_block"]
    COMMAND_REGISTRY["export_block"] = MagicMock(return_value="C:/work")
    COMMAND_REGISTRY["import_block"] = MagicMock(return_value=True)
    yield
    COMMAND_REGISTRY["export_block"] = orig_export
    COMMAND_REGISTRY["import_block"] = orig_import


def _write_minimal_s7dcl_s7res(work_dir: Path, db_name: str = "DB2000_ED") -> None:
    """Crea un par .s7dcl / .s7res mínimos en ``work_dir``."""
    s7dcl = f"""DATA_BLOCK {db_name}
    VAR
        "X" : Array[0..10] of _.UDT_ZC_DISP_X;
    END_VAR

        "X"[0].Estado_AutoMan := FALSE;
        "X"[0] := ();

END_DATA_BLOCK
"""
    s7res = "MultiLingualTexts:\n"
    (work_dir / f"{db_name}.s7dcl").write_text(s7dcl, encoding="utf-8")
    (work_dir / f"{db_name}.s7res").write_text(s7res, encoding="utf-8-sig")


def test_handler_actualiza_un_db(tmp_path: Path) -> None:
    """Handler invoca export+import con la ruta correcta y devuelve DispCommentResult."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    _write_minimal_s7dcl_s7res(work_dir)

    handler = COMMAND_REGISTRY["update_disp_comments_db_ed"]
    result = handler(
        portal=MagicMock(),
        ts=MagicMock(),
        args={
            "plc_name":      "PLC_X",
            "db_name":       "DB2000_ED",
            "db_array_name": "ED",
            "slot_map":      {"0": "NO USAR", "1": "Bomba 1"},
            "work_dir":      str(work_dir),
            "target_folder": "2000_Dispositivos",
        },
    )

    # export_block se llamó con block_name = db_name.
    COMMAND_REGISTRY["export_block"].assert_called_once()
    call = COMMAND_REGISTRY["export_block"].call_args
    assert call.args[2]["plc_name"] == "PLC_X"
    assert call.args[2]["block_name"] == "DB2000_ED"
    assert call.args[2]["target_dir"] == str(work_dir)

    # import_block se llamó con target_folder.
    COMMAND_REGISTRY["import_block"].assert_called_once()
    call = COMMAND_REGISTRY["import_block"].call_args
    assert call.args[2]["target_folder"] == "2000_Dispositivos"

    # Resultado poblado.
    assert result["hw_type"] == "ed"
    assert result["db_name"] == "DB2000_ED"
    assert result["modified"] is True
    assert "MLC_" in result["disp_comment_result"]["no_usar_mlc"]


def test_handler_falla_si_args_incompletos(tmp_path: Path) -> None:
    """Args incompletos → ValueError."""
    handler = COMMAND_REGISTRY["update_disp_comments_db_ea"]
    with pytest.raises(ValueError, match="args incompletos"):
        handler(
            portal=MagicMock(),
            ts=MagicMock(),
            args={"plc_name": "PLC_X", "db_name": "DB2001_EA"},
        )


def test_handler_no_import_si_no_modificado(tmp_path: Path) -> None:
    """Si el updater no modifica nada, no se invoca ``import_block`` (evita ruido en Undo)."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    # .s7dcl / .s7res ya correctos: slot 0 con MLC + texto NO USAR en s7res.
    s7dcl = """DATA_BLOCK DB2000_ED
    VAR
        "ED" : Array[0..10] of _.UDT_ZC_DISP_ED;
    END_VAR

        "ED"[0].Estado_AutoMan := FALSE;
        { S7_MLC := "MLC_old0" }
        "ED"[0] := ();

END_DATA_BLOCK
"""
    s7res = (
        "MultiLingualTexts:\n"
        "  - id: MLC_old0\n"
        "    es-ES: NO USAR\n"
    )
    (work_dir / "DB2000_ED.s7dcl").write_text(s7dcl, encoding="utf-8")
    (work_dir / "DB2000_ED.s7res").write_text(s7res, encoding="utf-8-sig")

    handler = COMMAND_REGISTRY["update_disp_comments_db_ed"]
    result = handler(
        portal=MagicMock(),
        ts=MagicMock(),
        args={
            "plc_name":      "PLC_X",
            "db_name":       "DB2000_ED",
            "db_array_name": "ED",
            "slot_map":      {"0": "NO USAR"},  # ya coincide, no hay cambios.
            "work_dir":      str(work_dir),
            "target_folder": "2000_Dispositivos",
        },
    )

    assert result["modified"] is False
    COMMAND_REGISTRY["import_block"].assert_not_called()


def test_handler_propagates_exception(tmp_path: Path) -> None:
    """Si export_block lanza, la excepción se propaga (rollback del batch)."""
    COMMAND_REGISTRY["export_block"] = MagicMock(
        side_effect=RuntimeError("TIA no disponible")
    )

    handler = COMMAND_REGISTRY["update_disp_comments_db_sa"]
    with pytest.raises(RuntimeError, match="TIA no disponible"):
        handler(
            portal=MagicMock(),
            ts=MagicMock(),
            args={
                "plc_name":      "PLC_X",
                "db_name":       "DB2006_SA",
                "db_array_name": "SA",
                "slot_map":      {"0": "NO USAR"},
                "work_dir":      str(tmp_path),
                "target_folder": "2000_Dispositivos",
            },
        )


def test_ruta_destino_viene_del_config(tmp_path: Path) -> None:
    """El handler NO debe hardcodear la carpeta TIA; usa el ``target_folder`` de args.

    Si alguien hardcodea ``"2000_Dispositivos"`` en el código del handler,
    este test fallaría porque el ``target_folder`` que pasamos es otro
    (``OTRA_CARPETA``) y el handler debe respetarlo.
    """
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    _write_minimal_s7dcl_s7res(work_dir, db_name="DB2010_V")

    handler = COMMAND_REGISTRY["update_disp_comments_db_v"]
    handler(
        portal=MagicMock(),
        ts=MagicMock(),
        args={
            "plc_name":      "PLC_X",
            "db_name":       "DB2010_V",
            "db_array_name": "V",
            "slot_map":      {"0": "NO USAR", "1": "Valvula 1"},
            "work_dir":      str(work_dir),
            "target_folder": "OTRA_CARPETA",
        },
    )

    call = COMMAND_REGISTRY["import_block"].call_args
    assert call.args[2]["target_folder"] == "OTRA_CARPETA", (
        "El handler debe respetar el target_folder del caller, no hardcodearlo."
    )


def test_handler_todos_los_hw_types_registrados() -> None:
    """Los 6 handlers del dominio dispositivos están en el COMMAND_REGISTRY."""
    expected = [
        "update_disp_comments_db_ed",
        "update_disp_comments_db_ea",
        "update_disp_comments_db_sa",
        "update_disp_comments_db_v",
        "update_disp_comments_db_m",
        "update_disp_comments_db_m_vf",
    ]
    for name in expected:
        assert name in COMMAND_REGISTRY, f"Falta handler {name!r} en COMMAND_REGISTRY"
        assert callable(COMMAND_REGISTRY[name]), f"{name!r} no es callable"
