"""Tests de ``core.helpers.blocks_edit._workdir_layout``.

Verifica la convencion de paths absolutos del workdir del editor de bloques.
Patron: tests/core/infrastructure/tia/test_tia_export_paths.py.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from core.helpers.blocks_edit import (
    BlocksEditLayout,
    DEFAULT_BLOCKS_EDIT_ROOT,
    blocks_edit_cache,
)


def test_default_root_is_absolute() -> None:
    """``os.getcwd()`` siempre es absoluto, asi que DEFAULT_BLOCKS_EDIT_ROOT
    tambien. Requisito del SDK Openness de TIA."""
    assert Path(str(DEFAULT_BLOCKS_EDIT_ROOT)).is_absolute()


def test_preview_dir_returns_root_preview() -> None:
    """``preview_dir`` cuelga directamente de ``root`` (sin sub-layout)."""
    layout = BlocksEditLayout(root=Path("/tmp/test"))
    assert layout.preview_dir == Path("/tmp/test") / "preview"


def test_preview_for_plc_returns_preview_plc() -> None:
    """``preview_for_plc`` deriva el subdir del PLC bajo ``preview_dir``."""
    layout = BlocksEditLayout(root=Path("/tmp/test"))
    assert layout.preview_for_plc("PLC_1") == Path("/tmp/test") / "preview" / "PLC_1"


def test_layout_is_frozen() -> None:
    """El dataclass es frozen: reasignar ``root`` levanta ``FrozenInstanceError``."""
    layout = BlocksEditLayout(root=Path("/tmp/test"))
    with pytest.raises(FrozenInstanceError):
        layout.root = Path("/tmp/other")  # type: ignore[misc]


def test_blocks_edit_cache_accepts_injected_root() -> None:
    """El atajo ``blocks_edit_cache(root=...)`` permite inyectar un root custom
    (p.ej. ``tmp_path`` de pytest) sin tocar ``DEFAULT_BLOCKS_EDIT_ROOT``."""
    layout = blocks_edit_cache(root=Path("/tmp/inject"))
    assert layout.preview_for_plc("PLC_1") == Path("/tmp/inject") / "preview" / "PLC_1"
