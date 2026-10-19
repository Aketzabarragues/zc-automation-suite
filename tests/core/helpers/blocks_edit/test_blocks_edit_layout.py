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


def test_layout_is_frozen() -> None:
    """El dataclass es frozen: reasignar ``root`` levanta ``FrozenInstanceError``."""
    layout = BlocksEditLayout(root=Path("/tmp/test"))
    with pytest.raises(FrozenInstanceError):
        layout.root = Path("/tmp/other")  # type: ignore[misc]


def test_blocks_edit_cache_accepts_injected_root() -> None:
    """El atajo ``blocks_edit_cache(root=...)`` permite inyectar un root custom
    (p.ej. ``tmp_path`` de pytest) sin tocar ``DEFAULT_BLOCKS_EDIT_ROOT``."""
    layout = blocks_edit_cache(root=Path("/tmp/inject"))
    assert layout.preview_dir == Path("/tmp/inject") / "preview"


# ── Limpieza (clean_preview / clean_all) ───────────────────────────


def test_clean_preview_borra_todo_preview(tmp_path: Path) -> None:
    """``clean_preview()`` borra ``preview/`` entero y lo recrea vacio."""
    layout = BlocksEditLayout(root=tmp_path)
    # Sembramos archivos de un prepare anterior (el dir se crea manualmente
    # porque ``preview_dir`` no se auto-crea en el property).
    layout.preview_dir.mkdir(parents=True, exist_ok=True)
    (layout.preview_dir / "DB2000_ED.s7dcl").write_text("x")
    (layout.preview_dir / "DB2000_ED.s7res").write_text("x")
    (layout.preview_dir / "FC2000_ZC_ED.s7dcl").write_text("x")

    layout.clean_preview()

    # preview/ existe pero vacio.
    assert layout.preview_dir.exists()
    assert list(layout.preview_dir.iterdir()) == []


def test_clean_preview_sin_preview_existente_no_falla(tmp_path: Path) -> None:
    """``clean_preview()`` sobre un ``preview/`` inexistente crea el dir vacio."""
    layout = BlocksEditLayout(root=tmp_path)
    # No hay preview/ todavia.
    assert not layout.preview_dir.exists()

    layout.clean_preview()

    assert layout.preview_dir.exists()
    assert list(layout.preview_dir.iterdir()) == []


def test_clean_preview_borra_antes_de_recrear(tmp_path: Path) -> None:
    """``clean_preview()`` borra los archivos antes de recrear el dir vacio.

    Verifica el orden: primero ``shutil.rmtree``, despues ``mkdir``.
    Si el orden se invierte, los archivos viejos sobreviven al siguiente
    prepare.
    """
    layout = BlocksEditLayout(root=tmp_path)
    (layout.preview_dir).mkdir(parents=True)
    stale = layout.preview_dir / "stale.s7dcl"
    stale.write_text("huerfano del prepare anterior")

    layout.clean_preview()

    assert not stale.exists(), (
        "clean_preview debe borrar los huerfanos del prepare anterior"
    )
    assert layout.preview_dir.exists()
    assert list(layout.preview_dir.iterdir()) == []


def test_clean_all_borra_root_y_recrea_preview(tmp_path: Path) -> None:
    """``clean_all()`` borra ``root`` y deja ``preview/`` vacio."""
    layout = BlocksEditLayout(root=tmp_path)
    layout.preview_dir.mkdir(parents=True, exist_ok=True)
    (layout.preview_dir / "DB1.s7dcl").write_text("x")
    # Un archivo suelto en ``root`` que NO deberia sobrevivir.
    (tmp_path / "extra.txt").write_text("noise")

    layout.clean_all()

    assert layout.root.exists()
    assert layout.preview_dir.exists()
    assert list(layout.preview_dir.iterdir()) == []
    assert not (tmp_path / "extra.txt").exists()