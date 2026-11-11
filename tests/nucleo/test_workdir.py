"""Tests de la carpeta de trabajo de cada operacion."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from zc_suite import workdir as workdir_modulo
from zc_suite.workdir import Workdir, raiz_build_cache, workdir, workdir_editor_bloques

RAIZ = Path(__file__).resolve().parents[2]


# ── rutas ──────────────────────────────────────────────────────────────────


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


def test_el_workdir_tiene_area_y_contexto() -> None:
    wd = workdir("alimentacion", "disp")

    assert wd.base.name == "disp"
    assert wd.base.parent.name == "alimentacion"
    assert wd.base.parent.parent.name == ".build_cache"


def test_resolver_un_workdir_no_toca_el_disco() -> None:
    wd = workdir("alimentacion", "disp")

    assert not wd.base.exists()


def test_cada_contexto_tiene_su_carpeta() -> None:
    assert workdir("alimentacion", "disp").base != workdir("alimentacion", "proc").base


# ── carpetas ───────────────────────────────────────────────────────────────


def test_el_workdir_tiene_las_tres_carpetas(tmp_path: Path) -> None:
    wd = Workdir(base=tmp_path / "ctx")

    assert wd.exports == tmp_path / "ctx" / "exports"
    assert wd.modified == tmp_path / "ctx" / "modified"
    assert wd.preview == tmp_path / "ctx" / "preview"


def test_crear_mkdir_las_tres_carpetas(tmp_path: Path) -> None:
    wd = Workdir(base=tmp_path / "ctx").crear()

    assert wd.exports.is_dir()
    assert wd.modified.is_dir()
    assert wd.preview.is_dir()


def test_crear_es_idempotente(tmp_path: Path) -> None:
    wd = Workdir(base=tmp_path / "ctx")
    wd.crear()
    (wd.exports / "fichero.txt").write_text("dato", encoding="utf-8")

    wd.crear()

    assert (wd.exports / "fichero.txt").is_file()


def test_crear_devuelve_el_workdir(tmp_path: Path) -> None:
    wd = Workdir(base=tmp_path / "ctx")

    assert wd.crear() is wd


# ── limpieza ───────────────────────────────────────────────────────────────


def test_limpiar_preview_borra_solo_el_preview(tmp_path: Path) -> None:
    wd = Workdir(base=tmp_path / "ctx").crear()
    (wd.exports / "a.txt").write_text("a", encoding="utf-8")
    (wd.modified / "b.txt").write_text("b", encoding="utf-8")
    (wd.preview / "c.txt").write_text("c", encoding="utf-8")

    wd.limpiar_preview()

    assert (wd.exports / "a.txt").is_file()
    assert (wd.modified / "b.txt").is_file()
    assert not (wd.preview / "c.txt").exists()
    assert wd.preview.is_dir()


def test_limpiar_borra_las_tres(tmp_path: Path) -> None:
    wd = Workdir(base=tmp_path / "ctx").crear()
    for carpeta in (wd.exports, wd.modified, wd.preview):
        (carpeta / "fichero.txt").write_text("dato", encoding="utf-8")

    wd.limpiar()

    for carpeta in (wd.exports, wd.modified, wd.preview):
        assert list(carpeta.iterdir()) == []


def test_limpiar_borra_subcarpetas(tmp_path: Path) -> None:
    wd = Workdir(base=tmp_path / "ctx").crear()
    (wd.preview / "bloques" / "sub").mkdir(parents=True)
    (wd.preview / "bloques" / "sub" / "x.txt").write_text("x", encoding="utf-8")

    wd.limpiar_preview()

    assert list(wd.preview.iterdir()) == []


def test_limpiar_una_carpeta_inexistente_no_falla(tmp_path: Path) -> None:
    wd = Workdir(base=tmp_path / "ctx")

    wd.limpiar_preview()
    wd.limpiar()


def test_los_workdirs_de_contextos_distintos_no_se_pisan(tmp_path: Path) -> None:
    uno = Workdir(base=tmp_path / "uno").crear()
    dos = Workdir(base=tmp_path / "dos").crear()
    (uno.exports / "a.txt").write_text("a", encoding="utf-8")

    dos.limpiar()

    assert (uno.exports / "a.txt").is_file()


def test_el_workdir_se_puede_inyectar_en_una_funcion(tmp_path: Path) -> None:
    """Los tests pueden apuntar el build cache a un temporal."""
    wd = Workdir(base=tmp_path / "inyectado").crear()

    resultado: dict[str, Any] = {"ok": wd.exports.is_dir()}

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
