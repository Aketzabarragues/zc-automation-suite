"""Tests del core BuildCache (genérico, sin saber de áreas).

Cubre:
  * BuildCache(area_id) parametriza la jerarquía por área.
  * BuildCache.area devuelve un AreaCache con root = <root>/<area_id>.
  * ContextCache expone exports/modified/preview como subdirs.
  * ContextCache.clean() borra y recrea exports/ y modified/ pero
    NO toca preview/.

NO se mockea nada: tmp_path de pytest aísla cada test del filesystem
real.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.infrastructure.build_cache import AreaCache, BuildCache, ContextCache


# ── BuildCache (raíz) ─────────────────────────────────────────────────────


def test_build_cache_root_por_defecto_es_cwd_build_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Con ``root`` por defecto, apunta a ``<cwd>/.build_cache``."""
    monkeypatch.chdir(tmp_path)
    bc = BuildCache(area_id="alimentacion")
    assert bc.root == tmp_path / ".build_cache"


def test_build_cache_area_id_es_obligatorio(tmp_path: Path) -> None:
    """``area_id`` es parámetro posicional obligatorio (sin default)."""
    bc = BuildCache(area_id="trazabilidad", root=tmp_path)
    # El área vive en <root>/<area_id>
    assert bc.area.root == tmp_path / "trazabilidad"


def test_build_cache_area_para_cada_area_id(tmp_path: Path) -> None:
    """Mismo ``root``, distinto ``area_id`` → sub-jerarquías distintas."""
    bc_alim = BuildCache(area_id="alimentacion", root=tmp_path)
    bc_traz = BuildCache(area_id="trazabilidad", root=tmp_path)
    assert bc_alim.area.root == tmp_path / "alimentacion"
    assert bc_traz.area.root == tmp_path / "trazabilidad"
    # Y NO colisionan:
    assert bc_alim.area.root != bc_traz.area.root


# ── AreaCache (base) ─────────────────────────────────────────────────────


def test_area_cache_es_solo_un_contenedor(tmp_path: Path) -> None:
    """El core NO aporta contextos: AreaCache base solo tiene area_id y root.

    Los contextos los aporta cada área extendiendo ``AreaCache``.
    """
    area = AreaCache(area_id="alimentacion", root=tmp_path / "alimentacion")
    assert area.area_id == "alimentacion"
    assert area.root == tmp_path / "alimentacion"
    # Y no tiene .dispositivos / .procesos (eso es de la extensión del área).
    assert not hasattr(area, "dispositivos")
    assert not hasattr(area, "procesos")


# ── ContextCache (3 subestados + clean) ──────────────────────────────────


def test_context_cache_subestados(tmp_path: Path) -> None:
    """Los 3 subestados viven dentro del root del contexto."""
    ctx = ContextCache(root=tmp_path / "dispositivos")
    assert ctx.exports == tmp_path / "dispositivos" / "exports"
    assert ctx.modified == tmp_path / "dispositivos" / "modified"
    assert ctx.preview == tmp_path / "dispositivos" / "preview"


def test_context_cache_clean_borra_y_recrea_exports_y_modified(tmp_path: Path) -> None:
    """``clean()`` borra y recrea ``exports/`` y ``modified/``.

    Caso típico: el operario hizo un export hace 2 horas, los
    modificadores generaron ``modified/``, pero los .s7dcl/.s7res de
    ``exports/`` ya están stale. ``clean()`` deja el workdir como
    nuevo sin tocar ``preview/`` (que tiene artefactos de un
    dry-run anterior que el operario quiere conservar).
    """
    ctx = ContextCache(root=tmp_path / "disp")
    # Poblamos exports/ y modified/ con contenido "stale".
    (ctx.exports / "sub").mkdir(parents=True)
    (ctx.exports / "sub" / "stale.s7dcl").write_text("stale", encoding="utf-8")
    (ctx.modified).mkdir(parents=True)
    (ctx.modified / "stale_modified.s7dcl").write_text("stale", encoding="utf-8")

    ctx.clean()

    # exports/ y modified/ existen y están vacíos.
    assert ctx.exports.exists()
    assert ctx.modified.exists()
    assert list(ctx.exports.iterdir()) == []
    assert list(ctx.modified.iterdir()) == []


def test_context_cache_clean_no_toca_preview(tmp_path: Path) -> None:
    """``preview/`` NO se borra: dry-runs en curso o artefactos históricos."""
    ctx = ContextCache(root=tmp_path / "proc")
    (ctx.preview).mkdir(parents=True)
    dry_run_artifact = ctx.preview / "dry_run_report.json"
    dry_run_artifact.write_text('{"dry_run": true}', encoding="utf-8")
    (ctx.exports).mkdir(parents=True)
    (ctx.exports / "stale.s7dcl").write_text("stale", encoding="utf-8")

    ctx.clean()

    # preview/ intacto con su artefacto.
    assert dry_run_artifact.exists()
    assert dry_run_artifact.read_text(encoding="utf-8") == '{"dry_run": true}'
    # exports/ limpio.
    assert ctx.exports.exists()
    assert list(ctx.exports.iterdir()) == []


def test_context_cache_clean_idempotente(tmp_path: Path) -> None:
    """``clean()`` es idempotente: si los subdirs no existen, los crea vacíos."""
    ctx = ContextCache(root=tmp_path / "fresh")
    # Ni exports/ ni modified/ existen aún.
    assert not ctx.exports.exists()
    assert not ctx.modified.exists()

    ctx.clean()  # Primera vez: los crea.
    assert ctx.exports.exists()
    assert ctx.modified.exists()

    ctx.clean()  # Segunda vez: los borra y los vuelve a crear.
    assert ctx.exports.exists()
    assert ctx.modified.exists()
    assert list(ctx.exports.iterdir()) == []
    assert list(ctx.modified.iterdir()) == []
