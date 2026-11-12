"""Tests de las carpetas de trabajo de cada operacion."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from zc_suite.nucleo.tia import workdir as workdir_modulo
from zc_suite.nucleo.tia.workdir import (
    Workdir,
    WorkdirPreview,
    raiz_build_cache,
    workdir,
    workdir_editor_bloques,
)

RAIZ = Path(__file__).resolve().parents[2]


# ── la raiz ────────────────────────────────────────────────────────────────


def test_en_desarrollo_la_raiz_va_en_el_repo() -> None:
    assert raiz_build_cache() == RAIZ / ".build_cache"


def test_en_empaquetado_la_raiz_va_junto_al_exe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exe_dir = tmp_path / "instalacion"
    exe_dir.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "zc_automation_suite.exe"))

    assert raiz_build_cache() == exe_dir / ".build_cache"


def test_en_empaquetado_el_workdir_va_junto_al_exe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exe_dir = tmp_path / "instalacion"
    exe_dir.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "zc_automation_suite.exe"))

    wd = workdir("un_area", "un_contexto")

    assert wd.base == exe_dir / ".build_cache" / "un_area" / "un_contexto"


# ── el layout ──────────────────────────────────────────────────────────────


def test_el_workdir_tiene_area_y_contexto() -> None:
    wd = workdir("un_area", "un_contexto")

    assert wd.base.name == "un_contexto"
    assert wd.base.parent.name == "un_area"
    assert wd.base.parent.parent.name == ".build_cache"


def test_cada_contexto_tiene_su_carpeta() -> None:
    assert workdir("un_area", "uno").base != workdir("un_area", "dos").base


def test_resolver_un_workdir_no_toca_el_disco(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workdir_modulo, "RAIZ", tmp_path)
    wd = workdir("un_area", "un_contexto")

    assert not wd.base.exists()


def test_el_preview_es_plano_y_la_sincronizar_tiene_estructura(tmp_path: Path) -> None:
    wd = Workdir(base=tmp_path / "ctx")

    assert wd.preview == tmp_path / "ctx" / "preview"
    assert wd.sincronizar == tmp_path / "ctx" / "sincronizar"


def test_las_variables_y_los_bloques_van_siempre_separados(tmp_path: Path) -> None:
    wd = Workdir(base=tmp_path / "ctx")

    assert wd.variables_export == tmp_path / "ctx" / "sincronizar" / "variables" / "export"
    assert wd.variables_modified == tmp_path / "ctx" / "sincronizar" / "variables" / "modified"
    assert wd.bloques_export == tmp_path / "ctx" / "sincronizar" / "bloques" / "export"
    assert wd.bloques_modified == tmp_path / "ctx" / "sincronizar" / "bloques" / "modified"
    assert wd.variables_export.parent != wd.bloques_export.parent


def test_las_subcarpetas_del_preview_las_declara_el_area(tmp_path: Path) -> None:
    wd = Workdir(base=tmp_path / "ctx", preview_subcarpetas=("uno", "dos"))

    assert wd.preview_de("uno") == tmp_path / "ctx" / "preview" / "uno"
    assert wd.preview_de("dos") == tmp_path / "ctx" / "preview" / "dos"


def test_el_nucleo_no_declara_las_subcarpetas_del_preview() -> None:
    """El area las declara: el nucleo no sabe que hay contextos."""
    assert Workdir(base=Path("x")).preview_subcarpetas == ()


def test_el_nucleo_no_declara_las_carpetas_del_contexto() -> None:
    """Las carpetas propias del contexto las declara el area."""
    assert Workdir(base=Path("x")).carpetas_contexto == ()


def test_el_area_declara_carpetas_propias_del_contexto(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workdir_modulo, "RAIZ", tmp_path)
    wd = workdir("un_area", "proc_crear", carpetas=("plantilla", "nuevo"))

    assert wd.carpeta("plantilla") == tmp_path / ".build_cache" / "un_area" / "proc_crear" / (
        "plantilla"
    )
    assert wd.carpeta("nuevo") == tmp_path / ".build_cache" / "un_area" / "proc_crear" / "nuevo"


def test_crear_mkdir_las_carpetas_propias_del_contexto(tmp_path: Path) -> None:
    wd = Workdir(base=tmp_path / "ctx", carpetas_contexto=("plantilla", "nuevo")).crear()

    assert wd.carpeta("plantilla").is_dir()
    assert wd.carpeta("nuevo").is_dir()


# ── creacion ───────────────────────────────────────────────────────────────


def test_crear_mkdir_las_carpetas(tmp_path: Path) -> None:
    wd = Workdir(base=tmp_path / "ctx", preview_subcarpetas=("uno",)).crear()

    assert wd.preview.is_dir()
    assert wd.preview_de("uno").is_dir()
    assert wd.variables_export.is_dir()
    assert wd.variables_modified.is_dir()
    assert wd.bloques_export.is_dir()
    assert wd.bloques_modified.is_dir()


def test_crear_es_idempotente(tmp_path: Path) -> None:
    wd = Workdir(base=tmp_path / "ctx")
    wd.crear()
    (wd.bloques_export / "fichero.txt").write_text("dato", encoding="utf-8")

    wd.crear()

    assert (wd.bloques_export / "fichero.txt").is_file()


def test_crear_devuelve_el_workdir(tmp_path: Path) -> None:
    wd = Workdir(base=tmp_path / "ctx")

    assert wd.crear() is wd


# ── limpieza ───────────────────────────────────────────────────────────────


def test_limpiar_preview_borra_solo_el_preview(tmp_path: Path) -> None:
    wd = Workdir(base=tmp_path / "ctx").crear()
    (wd.variables_export / "a.txt").write_text("a", encoding="utf-8")
    (wd.bloques_modified / "b.txt").write_text("b", encoding="utf-8")
    (wd.preview / "c.txt").write_text("c", encoding="utf-8")

    wd.limpiar_preview()

    assert (wd.variables_export / "a.txt").is_file()
    assert (wd.bloques_modified / "b.txt").is_file()
    assert not (wd.preview / "c.txt").exists()
    assert wd.preview.is_dir()


def test_limpiar_preview_deja_las_subcarpetas_del_area(tmp_path: Path) -> None:
    wd = Workdir(base=tmp_path / "ctx", preview_subcarpetas=("uno",)).crear()
    (wd.preview_de("uno") / "x.txt").write_text("x", encoding="utf-8")

    wd.limpiar_preview()

    assert wd.preview_de("uno").is_dir()
    assert list(wd.preview_de("uno").iterdir()) == []


def test_limpiar_sincronizar_borra_solo_lo_de_sincronizar(tmp_path: Path) -> None:
    wd = Workdir(base=tmp_path / "ctx").crear()
    (wd.preview / "a.txt").write_text("a", encoding="utf-8")
    (wd.variables_export / "b.txt").write_text("b", encoding="utf-8")
    (wd.bloques_export / "c.txt").write_text("c", encoding="utf-8")

    wd.limpiar_sincronizar()

    assert (wd.preview / "a.txt").is_file()
    assert not (wd.variables_export / "b.txt").exists()
    assert not (wd.bloques_export / "c.txt").exists()
    assert wd.variables_export.is_dir()
    assert wd.bloques_export.is_dir()


def test_limpiar_todo_borra_el_contexto_entero(tmp_path: Path) -> None:
    wd = Workdir(base=tmp_path / "ctx").crear()
    (wd.preview / "a.txt").write_text("a", encoding="utf-8")
    (wd.bloques_export / "b.txt").write_text("b", encoding="utf-8")

    wd.limpiar_todo()

    assert list(wd.preview.iterdir()) == []
    assert list(wd.bloques_export.iterdir()) == []


def test_las_limpiezas_no_se_salen_de_su_contexto(tmp_path: Path) -> None:
    """Limpiar un contexto no toca los demas."""
    uno = Workdir(base=tmp_path / "uno").crear()
    dos = Workdir(base=tmp_path / "dos").crear()
    (uno.preview / "a.txt").write_text("a", encoding="utf-8")
    (dos.preview / "b.txt").write_text("b", encoding="utf-8")
    (dos.bloques_export / "c.txt").write_text("c", encoding="utf-8")

    uno.limpiar_todo()

    assert (dos.preview / "b.txt").is_file()
    assert (dos.bloques_export / "c.txt").is_file()


def test_limpiar_una_carpeta_inexistente_no_falla(tmp_path: Path) -> None:
    wd = Workdir(base=tmp_path / "ctx")

    wd.limpiar_preview()
    wd.limpiar_sincronizar()
    wd.limpiar_todo()


def test_el_workdir_se_puede_inyectar_en_una_funcion(tmp_path: Path) -> None:
    """Los tests pueden apuntar el build cache a un temporal."""
    wd = Workdir(base=tmp_path / "inyectado").crear()

    resultado: dict[str, Any] = {"ok": wd.variables_export.is_dir()}

    assert resultado["ok"] is True


# ── el editor de bloques ───────────────────────────────────────────────────


def test_el_workdir_del_editor_va_a_su_propia_carpeta() -> None:
    wd = workdir_editor_bloques()

    assert wd.base.name == "editor_bloques"
    assert wd.base.parent.name == ".build_cache"
    assert wd.preview == wd.base / "preview"


def test_el_workdir_del_editor_no_toca_el_disco(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workdir_modulo, "RAIZ", tmp_path)
    wd = workdir_editor_bloques()

    assert not wd.base.exists()
    assert not wd.preview.exists()


def test_el_editor_limpia_su_preview(tmp_path: Path) -> None:
    wd = WorkdirPreview(base=tmp_path / "editor_bloques")
    wd.crear()
    (wd.preview / "DB10.s7dcl").write_text("x", encoding="utf-8")

    wd.limpiar_preview()

    assert list(wd.preview.iterdir()) == []
    assert wd.preview.is_dir()
