"""tests.core.launcher.test_main_supervisor_cleanup - cobertura del cleanup.

MainServiceSupervisor._cleanup_build_cache() borra ``.build_cache/``
al cerrar la app. Antes cubria solo ``<area_id>/`` registrados en
AreaRegistry; ahora tambien ``blocks_edit/`` (core/, no-área). Estos
tests aíslan el cwd con ``monkeypatch.chdir(tmp_path)`` para no
tocar el workdir real del operario.
"""

from pathlib import Path

import pytest

from core.launcher.main_supervisor import (
    MainServiceSupervisor,
    _CORE_BUILD_CACHE_SUBDIRS,
)


def _seed_build_cache(
    tmp_path: Path,
    blocks_edit_files: list[str],
    other_dirs: list[str] | None = None,
) -> None:
    """Crea ``<tmp_path>/.build_cache/`` con subdirs y archivos seed."""
    build_cache = tmp_path / ".build_cache"
    build_cache.mkdir()
    # blocks_edit: el subdir core que cleanup debe borrar.
    blocks_edit_dir = build_cache / "blocks_edit"
    blocks_edit_dir.mkdir()
    for rel in blocks_edit_files:
        f = blocks_edit_dir / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("seed")
    # Otros subdirs (areas o ruido). El cleanup los ignora si no están
    # en AreaRegistry ni en _CORE_BUILD_CACHE_SUBDIRS.
    for sub in other_dirs or []:
        (build_cache / sub).mkdir()


def test_cleanup_borra_blocks_edit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cleanup borra ``.build_cache/blocks_edit/`` (core/no-área)."""
    monkeypatch.chdir(tmp_path)
    _seed_build_cache(
        tmp_path,
        blocks_edit_files=["preview/DB2000_ED.s7dcl", "preview/DB2000_ED.s7res"],
    )
    blocks_edit_dir = tmp_path / ".build_cache" / "blocks_edit"
    assert blocks_edit_dir.exists()

    sup = MainServiceSupervisor(host="127.0.0.1", port=0)
    sup._cleanup_build_cache()

    assert not blocks_edit_dir.exists(), (
        "cleanup debe borrar .build_cache/blocks_edit/ completo"
    )


def test_cleanup_preserva_raiz_build_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La raíz ``.build_cache/`` se preserva (puede tener otras areas)."""
    monkeypatch.chdir(tmp_path)
    _seed_build_cache(
        tmp_path,
        blocks_edit_files=["preview/DB.s7dcl"],
        other_dirs=["otro_artefacto_del_operario"],
    )

    sup = MainServiceSupervisor(host="127.0.0.1", port=0)
    sup._cleanup_build_cache()

    raiz = tmp_path / ".build_cache"
    assert raiz.exists(), "la raiz .build_cache/ NO debe borrarse"
    assert (raiz / "otro_artefacto_del_operario").exists(), (
        "subdirs no listados en cleanup se preservan tal cual"
    )


def test_cleanup_idempotente_si_no_existe_build_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin ``.build_cache/``, cleanup es no-op silencioso."""
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / ".build_cache").exists()

    sup = MainServiceSupervisor(host="127.0.0.1", port=0)
    # No debe lanzar excepcion.
    sup._cleanup_build_cache()

    assert not (tmp_path / ".build_cache").exists()


def test_cleanup_idempotente_si_blocks_edit_no_existe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si ``.build_cache/blocks_edit/`` no existe, cleanup es no-op."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".build_cache").mkdir()
    # blocks_edit NO se crea.

    sup = MainServiceSupervisor(host="127.0.0.1", port=0)
    sup._cleanup_build_cache()

    raiz = tmp_path / ".build_cache"
    assert raiz.exists()
    assert not (raiz / "blocks_edit").exists()


def test_core_subdirs_incluye_blocks_edit() -> None:
    """_CORE_BUILD_CACHE_SUBDIRS contiene 'blocks_edit' (contrato API)."""
    assert "blocks_edit" in _CORE_BUILD_CACHE_SUBDIRS