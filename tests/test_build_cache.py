"""Tests del core BuildCache (genérico, sin saber de áreas).

Cubre:
  * BuildCache(area_id) parametriza la jerarquía por área.
  * BuildCache.area devuelve un AreaCache con root = <root>/<area_id>.
  * ContextCache expone la matriz 3×3 (preview/exports/modified ×
    variables/bloques/udt) más los alias raíz retro-compat
    (``exports``, ``modified``, ``preview`` apuntan a ``*_variables``).
  * ContextCache.clean() borra y recrea las 6 subcarpetas operativas
    (exports + modified × variables/bloques/udt) pero NO toca preview.
  * ContextCache.clean_preview() borra y recrea las 3 subcarpetas de
    preview.

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
    """Los 3 alias raíz (``exports``, ``modified``, ``preview``) apuntan a la RAÍZ de la fase.

    Backward compat: el código actual usa estos paths raíz. Se
    retiran en el commit 6 del plan. Mientras tanto, siguen
    existiendo como alias de la raíz (``<root>/<contexto>/<fase>/``).
    """
    ctx = ContextCache(root=tmp_path / "dispositivos")
    assert ctx.preview == tmp_path / "dispositivos" / "preview"
    assert ctx.exports == tmp_path / "dispositivos" / "exports"
    assert ctx.modified == tmp_path / "dispositivos" / "modified"


def test_context_cache_clean_borra_y_recrea_exports_y_modified(tmp_path: Path) -> None:
    """``clean()`` borra y recrea las subcarpetas de ``exports/`` y ``modified/``.

    Caso típico: el operario hizo un export hace 2 horas, los
    modificadores generaron ``modified/``, pero los .s7dcl/.s7res de
    ``exports/`` ya están stale. ``clean()`` deja el workdir como
    nuevo sin tocar ``preview/`` (que tiene artefactos de un
    dry-run anterior que el operario quiere conservar).
    """
    ctx = ContextCache(root=tmp_path / "disp")
    # Poblamos exports/variables y modified/bloques con contenido "stale"
    # (las subcarpetas ya existen por el cached_property; las usamos
    # directamente sin mkdir).
    (ctx.exports_variables / "sub").mkdir(parents=True, exist_ok=True)
    (ctx.exports_variables / "sub" / "stale.s7dcl").write_text("stale", encoding="utf-8")
    (ctx.modified_bloques / "stale_modified.s7dcl").write_text("stale", encoding="utf-8")

    ctx.clean()

    # exports/variables y modified/bloques existen y están vacíos.
    assert ctx.exports_variables.exists()
    assert ctx.modified_bloques.exists()
    assert list(ctx.exports_variables.iterdir()) == []
    assert list(ctx.modified_bloques.iterdir()) == []


def test_context_cache_clean_no_toca_preview(tmp_path: Path) -> None:
    """``preview/`` NO se borra: dry-runs en curso o artefactos históricos."""
    ctx = ContextCache(root=tmp_path / "proc")
    # preview/variables ya existe (cached_property). Escribimos un artefacto
    # de dry-run en él.
    dry_run_artifact = ctx.preview_variables / "dry_run_report.json"
    dry_run_artifact.write_text('{"dry_run": true}', encoding="utf-8")
    # Poblamos exports/variables con basura.
    (ctx.exports_variables / "stale.s7dcl").write_text("stale", encoding="utf-8")

    ctx.clean()

    # preview/variables intacto con su artefacto.
    assert dry_run_artifact.exists()
    assert dry_run_artifact.read_text(encoding="utf-8") == '{"dry_run": true}'
    # exports/variables limpio.
    assert ctx.exports_variables.exists()
    assert list(ctx.exports_variables.iterdir()) == []


def test_context_cache_clean_idempotente(tmp_path: Path) -> None:
    """``clean()`` es idempotente: se puede llamar varias veces seguidas sin fallar.

    La 1ª vez borra (si existe) y recrea. Las siguientes no hacen
    nada destructivo. Los subdirs quedan vacíos.
    """
    ctx = ContextCache(root=tmp_path / "fresh")
    # Tras instanciar, los subdirs aún no existen físicamente (no se
    # ha accedido a ninguna cached_property).
    assert not (ctx.root / "exports").exists()
    assert not (ctx.root / "modified").exists()

    ctx.clean()  # 1ª vez: crea los 6 subdirs operativos vacíos.
    assert ctx.exports_variables.exists()
    assert ctx.modified_bloques.exists()
    assert list(ctx.exports_variables.iterdir()) == []

    # Escribimos algo y llamamos clean de nuevo.
    (ctx.exports_bloques / "x.s7dcl").write_text("x", encoding="utf-8")
    ctx.clean()
    assert ctx.exports_bloques.exists()
    assert list(ctx.exports_bloques.iterdir()) == []


# ── ContextCache: matriz 3×3 (3 fases × 3 tipos de artefacto) ──────────


def test_context_cache_tiene_9_subcarpetas_explicitas(tmp_path: Path) -> None:
    """Las 9 subcarpetas viven en ``<root>/{fase}/<tipo>``.

    Cada propiedad es ``cached_property`` y crea su directorio al
    primer acceso (``_type_path`` con ``mkdir(parents=True, exist_ok=True)``).
    Por eso tras crear el ``ContextCache`` y acceder a las 9 propiedades,
    el árbol completo existe en disco.
    """
    ctx = ContextCache(root=tmp_path / "matrix")
    # preview/
    assert ctx.preview_variables == tmp_path / "matrix" / "preview" / "variables"
    assert ctx.preview_bloques == tmp_path / "matrix" / "preview" / "bloques"
    assert ctx.preview_udt == tmp_path / "matrix" / "preview" / "udt"
    # exports/
    assert ctx.exports_variables == tmp_path / "matrix" / "exports" / "variables"
    assert ctx.exports_bloques == tmp_path / "matrix" / "exports" / "bloques"
    assert ctx.exports_udt == tmp_path / "matrix" / "exports" / "udt"
    # modified/
    assert ctx.modified_variables == tmp_path / "matrix" / "modified" / "variables"
    assert ctx.modified_bloques == tmp_path / "matrix" / "modified" / "bloques"
    assert ctx.modified_udt == tmp_path / "matrix" / "modified" / "udt"

    # Y los 9 directorios existen físicamente.
    for p in (
        ctx.preview_variables, ctx.preview_bloques, ctx.preview_udt,
        ctx.exports_variables, ctx.exports_bloques, ctx.exports_udt,
        ctx.modified_variables, ctx.modified_bloques, ctx.modified_udt,
    ):
        assert p.exists()
        assert p.is_dir()


def test_alias_raiz_apuntan_a_la_raiz_de_la_fase(tmp_path: Path) -> None:
    """Backward compat: ``exports``, ``modified``, ``preview`` (raíz) son alias de la RAÍZ de la fase.

    Apuntan a ``<root>/<contexto>/{exports,modified,preview}/`` (raíz),
    NO a ``{exports,modified,preview}/variables/``. Esto preserva
    el contrato del Commit 1: el código actual que pasa
    ``work_dir = proc_ctx.exports`` a TIA sigue apuntando al mismo
    path de siempre. Los commits 2-5 migran call sites a las
    subcarpetas explícitas. El commit 6 retira los alias.

    Los alias NO crean el directorio automáticamente (son paths
    puros); las subcarpetas explícitas (``exports_variables``,
    etc.) sí lo hacen vía ``_type_path``.
    """
    ctx = ContextCache(root=tmp_path / "compat")
    assert ctx.preview == tmp_path / "compat" / "preview"
    assert ctx.exports == tmp_path / "compat" / "exports"
    assert ctx.modified == tmp_path / "compat" / "modified"
    # Y NO son las subcarpetas typed.
    assert ctx.exports != ctx.exports_variables
    assert ctx.modified != ctx.modified_variables
    assert ctx.preview != ctx.preview_variables


def test_idempotencia_de_subcarpetas(tmp_path: Path) -> None:
    """Acceder a una subcarpeta varias veces no falla (mkdir exist_ok=True).

    El helper ``_type_path`` es idempotente: ``mkdir(parents=True,
    exist_ok=True)`` no lanza si el directorio ya existe. Esto
    permite que el código llame ``ctx.exports_variables`` cuando
    quiera, sin necesidad de un ``ensure_dirs()`` previo.
    """
    ctx = ContextCache(root=tmp_path / "idem")
    # Primer acceso: crea el directorio.
    p1 = ctx.exports_bloques
    assert p1.exists()
    # Segundo acceso: misma path, no falla.
    p2 = ctx.exports_bloques
    assert p2 == p1
    # Tercer acceso desde otro punto del código: tampoco falla.
    (ctx.exports_bloques / "some_block.s7dcl").write_text("data", encoding="utf-8")
    p3 = ctx.exports_bloques
    assert p3 == p1
    assert (p3 / "some_block.s7dcl").exists()


# ── ContextCache: clean y clean_preview (matriz 3×3) ───────────────────


def test_clean_limpia_las_6_subcarpetas_operativas(tmp_path: Path) -> None:
    """``clean()`` borra y recrea las 6 subcarpetas de exports/ y modified/.

    Caso típico: el operario hizo un export hace 2 horas, los
    modificadores generaron ``modified/``, pero los .s7dcl/.s7res de
    ``exports/`` ya están stale. ``clean()`` deja el workdir como
    nuevo sin tocar ``preview/`` (que tiene artefactos de un
    dry-run anterior que el operario quiere conservar).
    """
    ctx = ContextCache(root=tmp_path / "sixpack")
    # Poblamos las 6 subcarpetas con contenido "stale".
    for sub in (
        ctx.exports_variables, ctx.exports_bloques, ctx.exports_udt,
        ctx.modified_variables, ctx.modified_bloques, ctx.modified_udt,
    ):
        (sub / "stale.s7dcl").parent.mkdir(parents=True, exist_ok=True)
        (sub / "stale.s7dcl").write_text("stale", encoding="utf-8")

    ctx.clean()

    # Las 6 subcarpetas existen y están vacías.
    for sub in (
        ctx.exports_variables, ctx.exports_bloques, ctx.exports_udt,
        ctx.modified_variables, ctx.modified_bloques, ctx.modified_udt,
    ):
        assert sub.exists()
        assert sub.is_dir()
        assert list(sub.iterdir()) == []


def test_clean_no_toca_preview(tmp_path: Path) -> None:
    """``clean()`` NO toca las 3 subcarpetas de ``preview/``.

    Los dry-runs en curso y los artefactos históricos del operario
    en ``preview/`` se preservan intactos. Para limpiar preview,
    usar ``clean_preview()``.
    """
    ctx = ContextCache(root=tmp_path / "preserve_preview")
    # Poblamos preview/ con artefactos valiosos.
    for sub in (ctx.preview_variables, ctx.preview_bloques, ctx.preview_udt):
        (sub / "important.json").write_text('{"keep": true}', encoding="utf-8")
    # Y exports/ con basura.
    (ctx.exports_variables / "stale.s7dcl").write_text("stale", encoding="utf-8")

    ctx.clean()

    # preview/ intacto en sus 3 subcarpetas.
    for sub in (ctx.preview_variables, ctx.preview_bloques, ctx.preview_udt):
        assert (sub / "important.json").exists()
        assert (sub / "important.json").read_text(encoding="utf-8") == '{"keep": true}'
    # exports/ limpio.
    assert ctx.exports_variables.exists()
    assert list(ctx.exports_variables.iterdir()) == []


def test_clean_preview_limpia_las_3_subcarpetas_de_preview(tmp_path: Path) -> None:
    """``clean_preview()`` borra y recrea las 3 subcarpetas de ``preview/``.

    Análogo a ``clean()`` pero solo para la fase read-only. Se
    invoca al inicio de ``generar_prevision``.
    """
    ctx = ContextCache(root=tmp_path / "preview_clean")
    # Poblamos preview/ con artefactos de un dry-run anterior.
    for sub in (ctx.preview_variables, ctx.preview_bloques, ctx.preview_udt):
        (sub / "old_dry_run.xml").write_text("<old/>", encoding="utf-8")

    ctx.clean_preview()

    # Las 3 subcarpetas de preview/ existen y están vacías.
    for sub in (ctx.preview_variables, ctx.preview_bloques, ctx.preview_udt):
        assert sub.exists()
        assert sub.is_dir()
        assert list(sub.iterdir()) == []


def test_clean_preview_no_toca_exports_ni_modified(tmp_path: Path) -> None:
    """``clean_preview()`` deja ``exports/`` y ``modified/`` intactos.

    Los snapshots del último commit aplicado se preservan para
    que ``git diff modified/ exports/`` siga funcionando tras un
    nuevo ``generar_prevision``.
    """
    ctx = ContextCache(root=tmp_path / "isolate_preview")
    # Poblamos todo: preview/, exports/ y modified/.
    (ctx.preview_variables / "old_preview.xml").write_text("preview", encoding="utf-8")
    (ctx.exports_variables / "snapshot.s7dcl").write_text("exports", encoding="utf-8")
    (ctx.modified_bloques / "patched.s7dcl").write_text("modified", encoding="utf-8")

    ctx.clean_preview()

    # preview/ limpio.
    assert ctx.preview_variables.exists()
    assert list(ctx.preview_variables.iterdir()) == []
    # exports/ y modified/ intactos.
    assert (ctx.exports_variables / "snapshot.s7dcl").exists()
    assert (ctx.exports_variables / "snapshot.s7dcl").read_text(encoding="utf-8") == "exports"
    assert (ctx.modified_bloques / "patched.s7dcl").exists()
    assert (ctx.modified_bloques / "patched.s7dcl").read_text(encoding="utf-8") == "modified"


def test_clean_limpia_subcarpeta_bloques_de_procesos_con_subpath(tmp_path: Path) -> None:
    """``clean()`` borra recursivamente subcarpetas de TIA dentro de ``exports/bloques/``.

    Los procesos guardan bloques en ``exports/bloques/<ruta_TIA>/<db>.s7dcl``
    (subpath del DB en TIA Portal). ``clean()`` debe borrar toda la
    jerarquía, no solo el primer nivel.
    """
    ctx = ContextCache(root=tmp_path / "subpath")
    # Simular la estructura de TIA: exports/bloques/003_Procesos/SubA/DB_PReal.s7dcl
    nested = ctx.exports_bloques / "003_Procesos" / "SubA"
    nested.mkdir(parents=True)
    (nested / "DB_PReal.s7dcl").write_text("stale", encoding="utf-8")

    ctx.clean()

    # Toda la jerarquía bajo exports/bloques está borrada y recreada vacía.
    assert ctx.exports_bloques.exists()
    assert not (ctx.exports_bloques / "003_Procesos").exists()
    assert list(ctx.exports_bloques.iterdir()) == []
