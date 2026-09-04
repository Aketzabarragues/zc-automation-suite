"""Tests de la extensión de BuildCache para el área alimentación.

Cubre:
  * ``build_cache()`` devuelve ``AlimentacionAreaCache`` con los 2
    contextos del área (dispositivos y procesos).
  * La jerarquía física es ``<root>/alimentacion/<contexto>/<subestado>``.
  * ``build_cache(root=tmp_path)`` permite inyectar un root distinto
    al cwd para tests aislados.
"""
from __future__ import annotations

from pathlib import Path

from areas.alimentacion.infrastructure.build_cache import (
    AlimentacionAreaCache,
    build_cache,
)


def test_build_cache_devuelve_alimentacion_area_cache(tmp_path: Path) -> None:
    """``build_cache()`` instancia un ``AlimentacionAreaCache`` válido."""
    area = build_cache(root=tmp_path)
    assert isinstance(area, AlimentacionAreaCache)
    assert area.area_id == "alimentacion"
    assert area.root == tmp_path / "alimentacion"


def test_alimentacion_tiene_dispositivos_y_procesos(tmp_path: Path) -> None:
    """El área aporta 2 contextos: dispositivos y procesos."""
    area = build_cache(root=tmp_path)

    assert area.dispositivos.root == tmp_path / "alimentacion" / "dispositivos"
    assert area.procesos.root == tmp_path / "alimentacion" / "procesos"


def test_jerarquia_completa_de_dispositivos(tmp_path: Path) -> None:
    """``dispositivos`` expone los 3 subestados bajo ``<root>/alimentacion/dispositivos/``."""
    area = build_cache(root=tmp_path)
    disp = area.dispositivos

    assert disp.exports == tmp_path / "alimentacion" / "dispositivos" / "exports"
    assert disp.modified == tmp_path / "alimentacion" / "dispositivos" / "modified"
    assert disp.preview == tmp_path / "alimentacion" / "dispositivos" / "preview"


def test_jerarquia_completa_de_procesos(tmp_path: Path) -> None:
    """``procesos`` expone los 3 subestados bajo ``<root>/alimentacion/procesos/``."""
    area = build_cache(root=tmp_path)
    proc = area.procesos

    assert proc.exports == tmp_path / "alimentacion" / "procesos" / "exports"
    assert proc.modified == tmp_path / "alimentacion" / "procesos" / "modified"
    assert proc.preview == tmp_path / "alimentacion" / "procesos" / "preview"


def test_clean_resuelve_asimetria(tmp_path: Path) -> None:
    """``clean()`` en dispositivos o procesos limpia exports/ y modified/ por igual.

    Esto cierra la asimetría previa: ``disp_sync_instances`` ya
    limpiaba su workdir, ``proc_sync_comentarios`` no. Ahora ambos
    comparten el mismo helper.
    """
    area = build_cache(root=tmp_path)

    # Stale en ambos contextos.
    (area.dispositivos.exports / "old.s7dcl").parent.mkdir(parents=True)
    (area.dispositivos.exports / "old.s7dcl").write_text("old", encoding="utf-8")
    (area.procesos.modified).mkdir(parents=True)
    (area.procesos.modified / "old_modified.s7dcl").write_text("old", encoding="utf-8")
    (area.procesos.preview).mkdir(parents=True)
    preview_artifact = area.procesos.preview / "dry_run.json"
    preview_artifact.write_text('{"dry": true}', encoding="utf-8")

    area.dispositivos.clean()
    area.procesos.clean()

    # Ambos contextos limpios en exports/ y modified/.
    assert not list(area.dispositivos.exports.iterdir())
    assert not list(area.procesos.modified.iterdir())
    # Y el preview de procesos sigue intacto.
    assert preview_artifact.exists()
