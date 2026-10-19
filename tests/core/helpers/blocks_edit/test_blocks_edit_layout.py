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


# ── Limpieza (clean_preview / clean_all) ───────────────────────────


def test_clean_preview_sin_plc_borra_todo(tmp_path: Path) -> None:
    """``clean_preview()`` (sin plc_name) borra ``preview/`` entero."""
    layout = BlocksEditLayout(root=tmp_path)
    # Sembramos 2 PLCs con archivos.
    (layout.preview_dir / "PLC_A").mkdir(parents=True)
    (layout.preview_dir / "PLC_A" / "A.s7dcl").write_text("x")
    (layout.preview_dir / "PLC_B").mkdir(parents=True)
    (layout.preview_dir / "PLC_B" / "B.s7dcl").write_text("x")

    layout.clean_preview()

    # preview/ existe pero vacio (no quedan subdirs).
    assert layout.preview_dir.exists()
    assert list(layout.preview_dir.iterdir()) == []


def test_clean_preview_con_plc_borra_solo_ese_plc(tmp_path: Path) -> None:
    """``clean_preview(plc_name)`` borra solo ``preview/<plc_name>/``."""
    layout = BlocksEditLayout(root=tmp_path)
    (layout.preview_dir / "PLC_A").mkdir(parents=True)
    (layout.preview_dir / "PLC_A" / "A.s7dcl").write_text("x")
    (layout.preview_dir / "PLC_B").mkdir(parents=True)
    (layout.preview_dir / "PLC_B" / "B.s7dcl").write_text("x")

    layout.clean_preview("PLC_A")

    # PLC_A limpio y vacio, PLC_B intacto.
    assert layout.preview_dir.exists()
    assert (layout.preview_dir / "PLC_A").exists()
    assert list((layout.preview_dir / "PLC_A").iterdir()) == []
    assert (layout.preview_dir / "PLC_B" / "B.s7dcl").exists()


def test_clean_preview_con_plc_inexistente_no_falla(tmp_path: Path) -> None:
    """``clean_preview(plc_name)`` sobre un PLC sin dir previo no rompe."""
    layout = BlocksEditLayout(root=tmp_path)
    # No hay PLC_X todavia.
    layout.clean_preview("PLC_X")
    # El dir se crea vacio (siguiente export puede escribir directamente).
    assert (layout.preview_dir / "PLC_X").exists()
    assert list((layout.preview_dir / "PLC_X").iterdir()) == []


def test_clean_all_borra_root_y_recrea_preview(tmp_path: Path) -> None:
    """``clean_all()`` borra ``root`` y deja ``preview/`` vacio."""
    layout = BlocksEditLayout(root=tmp_path)
    (layout.preview_dir / "PLC_A").mkdir(parents=True)
    (layout.preview_dir / "PLC_A" / "A.s7dcl").write_text("x")
    # Un archivo suelto en ``root`` que NO deberia sobrevivir.
    (tmp_path / "extra.txt").write_text("noise")

    layout.clean_all()

    assert layout.root.exists()
    assert layout.preview_dir.exists()
    assert list(layout.preview_dir.iterdir()) == []
    assert not (tmp_path / "extra.txt").exists()
