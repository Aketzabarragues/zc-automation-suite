"""Tests de helpers _ensure_target_dir y _export_objects_sd (4.1.2b3-helpers).

Tests de los handlers export_blocks_sd/export_udts_sd van en
test_tia_client_export_sd.py (4.1.2b3-handlers).
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from core.infrastructure.tia.tia_loop import (
    _ensure_target_dir,
    _export_objects_sd,
)


def _block():
    b = MagicMock()
    b.export = MagicMock()
    return b


# ------------------------------------------------------------ _ensure_target_dir
def test_ensure_target_dir_raises_on_empty_string():
    try:
        _ensure_target_dir("")
    except ValueError as exc:
        assert "target_dir" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_ensure_target_dir_creates_directory_if_missing():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "exports" / "sd"
        result = _ensure_target_dir(str(target))
        assert result == target
        assert target.is_dir()


def test_ensure_target_dir_accepts_existing_directory():
    with tempfile.TemporaryDirectory() as tmp:
        result = _ensure_target_dir(tmp)
        assert result == Path(tmp)


# ------------------------------------------------------------ _export_objects_sd
def test_export_objects_sd_exports_program_blocks():
    plc = MagicMock()
    b1, b2 = _block(), _block()
    plc.get_program_blocks.return_value = [b1, b2]

    with tempfile.TemporaryDirectory() as tmp:
        result = _export_objects_sd(plc, Path(tmp), "program_blocks")

    assert result == {"exported_to": tmp, "count": 2}
    b1.export.assert_called_once_with(
        target_directory_path=tmp,
        export_format="SimaticSD",
        keep_folder_structure=True,
    )
    b2.export.assert_called_once_with(
        target_directory_path=tmp,
        export_format="SimaticSD",
        keep_folder_structure=True,
    )


def test_export_objects_sd_exports_user_data_types():
    plc = MagicMock()
    udt1 = _block()
    plc.get_user_data_types.return_value = [udt1]

    with tempfile.TemporaryDirectory() as tmp:
        result = _export_objects_sd(plc, Path(tmp), "user_data_types")

    assert result == {"exported_to": tmp, "count": 1}
    udt1.export.assert_called_once()


def test_export_objects_sd_raises_on_unknown_collection_key():
    plc = MagicMock()
    try:
        _export_objects_sd(plc, Path("/tmp"), "wrong_key")
    except ValueError as exc:
        assert "collection_key" in str(exc)
        assert "wrong_key" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_export_objects_sd_handles_empty_collection():
    plc = MagicMock()
    plc.get_program_blocks.return_value = []

    with tempfile.TemporaryDirectory() as tmp:
        result = _export_objects_sd(plc, Path(tmp), "program_blocks")

    assert result == {"exported_to": tmp, "count": 0}
