"""Tests del layout privado de dispositivos."""
from __future__ import annotations

from pathlib import Path

from areas.alimentacion.helpers.disp._workdir_layout import (
    DispLayout,
    build_disp_layout,
)


def test_preview_config_se_crea_al_acceder(tmp_path: Path) -> None:
    """Acceder a ``preview_config`` crea el subdir ``preview/config/``."""
    layout = DispLayout(root=tmp_path)

    assert layout.preview_config == tmp_path / "preview" / "config"
    assert layout.preview_config.is_dir()


def test_preview_disp_se_crea_al_acceder(tmp_path: Path) -> None:
    """Acceder a ``preview_disp`` crea el subdir ``preview/disp/``."""
    layout = DispLayout(root=tmp_path)

    assert layout.preview_disp == tmp_path / "preview" / "disp"
    assert layout.preview_disp.is_dir()


def test_sync_variables_export_se_crea_al_acceder(tmp_path: Path) -> None:
    """Acceder a ``sync_variables_export`` crea ``sincronizar/variables/export/``."""
    layout = DispLayout(root=tmp_path)

    expected = tmp_path / "sincronizar" / "variables" / "export"
    assert layout.sync_variables_export == expected
    assert layout.sync_variables_export.is_dir()


def test_sync_variables_modified_se_crea_al_acceder(tmp_path: Path) -> None:
    """Acceder a ``sync_variables_modified`` crea ``sincronizar/variables/modified/``."""
    layout = DispLayout(root=tmp_path)

    expected = tmp_path / "sincronizar" / "variables" / "modified"
    assert layout.sync_variables_modified == expected
    assert layout.sync_variables_modified.is_dir()


def test_sync_bloques_export_se_crea_al_acceder(tmp_path: Path) -> None:
    """Acceder a ``sync_bloques_export`` crea ``sincronizar/bloques/export/``."""
    layout = DispLayout(root=tmp_path)

    expected = tmp_path / "sincronizar" / "bloques" / "export"
    assert layout.sync_bloques_export == expected
    assert layout.sync_bloques_export.is_dir()


def test_sync_bloques_modified_se_crea_al_acceder(tmp_path: Path) -> None:
    """Acceder a ``sync_bloques_modified`` crea ``sincronizar/bloques/modified/``."""
    layout = DispLayout(root=tmp_path)

    expected = tmp_path / "sincronizar" / "bloques" / "modified"
    assert layout.sync_bloques_modified == expected
    assert layout.sync_bloques_modified.is_dir()


def test_build_disp_layout_default_root(tmp_path: Path, monkeypatch) -> None:
    """Sin ``root`` explicito, usa ``.build_cache/alimentacion/disp/`` bajo cwd."""
    monkeypatch.chdir(tmp_path)

    layout = build_disp_layout()
    assert layout.root == tmp_path / ".build_cache" / "alimentacion" / "disp"


def test_build_disp_layout_custom_root(tmp_path: Path) -> None:
    """Con ``root`` explicito, usa el path dado."""
    layout = build_disp_layout(root=tmp_path)
    assert layout.root == tmp_path


def test_clean_all_borra_contenido_y_recrea_subdirs(tmp_path: Path) -> None:
    """``clean_all`` borra el root y recrea los 6 subdirs vacios."""
    layout = DispLayout(root=tmp_path)

    # Sembrar contenido dummy.
    (layout.preview_config / "test_config.xml").write_text("x", encoding="utf-8")
    (layout.sync_variables_modified / "2000_Dispositivos").mkdir()
    (layout.sync_variables_modified / "2000_Dispositivos" / "2000_Disp_ED.xml").write_text(
        "y", encoding="utf-8",
    )

    layout.clean_all()

    # Contenido borrado.
    assert not (tmp_path / "preview" / "config" / "test_config.xml").exists()
    assert not (tmp_path / "sincronizar" / "variables" / "modified" / "2000_Dispositivos").exists()
    # Subdirs recreados vacios.
    assert layout.preview_config.is_dir()
    assert layout.preview_disp.is_dir()
    assert layout.sync_variables_export.is_dir()
    assert layout.sync_variables_modified.is_dir()
    assert layout.sync_bloques_export.is_dir()
    assert layout.sync_bloques_modified.is_dir()


# ── Aliases legacy NO deben existir (F6) ──────────────────────────


def test_aliases_legacy_no_existen_en_disp_layout(tmp_path: Path) -> None:
    """F6: los aliases legacy fueron borrados del DispLayout.

    Antes de F6 estos atributos existian como @cached_property que
    delegaban en los paths nuevos. Ahora cualquier caller que los use
    falla con AttributeError (fail-fast > compatibilidad silenciosa).
    """
    layout = DispLayout(root=tmp_path)

    for legacy_name in (
        "exports_variables",
        "modified_variables",
        "exports_bloques",
        "modified_bloques",
        "preview_variables",
        "clean",
    ):
        assert not hasattr(layout, legacy_name), (
            f"alias legacy {legacy_name!r} no debe existir en DispLayout "
            f"(F6 los borro; usa los paths nuevos sync_variables_*, "
            f"sync_bloques_*, preview_config, preview_disp, "
            f"clean_preview, clean_sincronizar, clean_all)."
        )


def test_clean_preview_y_clean_sincronizar_siguen_existiendo(tmp_path: Path) -> None:
    """Los metodos de limpieza reales (no aliases) siguen funcionando."""
    layout = DispLayout(root=tmp_path)

    # Sembramos basura en preview y en sincronizar.
    (layout.preview_config / "old.xml").write_text("x", encoding="utf-8")
    (layout.sync_variables_export / "old.xml").write_text("x", encoding="utf-8")

    # clean_preview borra preview/, deja sincronizar/ intacto.
    layout.clean_preview()
    assert not (tmp_path / "preview" / "config" / "old.xml").exists()
    assert (tmp_path / "sincronizar" / "variables" / "export" / "old.xml").exists()

    # clean_sincronizar borra sincronizar/, deja preview/ intacto.
    (layout.preview_config / "otro.xml").write_text("z", encoding="utf-8")
    layout.clean_sincronizar()
    assert not (tmp_path / "sincronizar" / "variables" / "export" / "old.xml").exists()
    assert (tmp_path / "preview" / "config" / "otro.xml").exists()
