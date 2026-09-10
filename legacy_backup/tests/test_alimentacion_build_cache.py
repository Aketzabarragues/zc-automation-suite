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
    """``dispositivos`` expone las 6 subcarpetas typed bajo ``<root>/alimentacion/dispositivos/``.

    Tras Commit 6, los alias raíz ``preview``, ``exports`` y
    ``modified`` se retiraron. El código usa las 6 subcarpetas
    explícitas (``preview_variables`` / ``preview_bloques`` /
    ``exports_variables`` / ``exports_bloques`` /
    ``modified_variables`` / ``modified_bloques``).
    """
    area = build_cache(root=tmp_path)
    disp = area.dispositivos

    # Alias raíz NO existen (retirados en Commit 6).
    assert not hasattr(disp, "exports")
    assert not hasattr(disp, "modified")
    assert not hasattr(disp, "preview")
    # Subcarpetas typed existen y apuntan donde deben.
    assert disp.exports_variables == tmp_path / "alimentacion" / "dispositivos" / "exports" / "variables"
    assert disp.exports_bloques == tmp_path / "alimentacion" / "dispositivos" / "exports" / "bloques"
    assert disp.modified_variables == tmp_path / "alimentacion" / "dispositivos" / "modified" / "variables"
    assert disp.modified_bloques == tmp_path / "alimentacion" / "dispositivos" / "modified" / "bloques"
    assert disp.preview_variables == tmp_path / "alimentacion" / "dispositivos" / "preview" / "variables"
    assert disp.preview_bloques == tmp_path / "alimentacion" / "dispositivos" / "preview" / "bloques"


def test_jerarquia_completa_de_procesos(tmp_path: Path) -> None:
    """``procesos`` expone las 6 subcarpetas typed bajo ``<root>/alimentacion/procesos/``."""
    area = build_cache(root=tmp_path)
    proc = area.procesos

    # Alias raíz NO existen (retirados en Commit 6).
    assert not hasattr(proc, "exports")
    assert not hasattr(proc, "modified")
    assert not hasattr(proc, "preview")
    # Subcarpetas typed existen y apuntan donde deben.
    assert proc.exports_variables == tmp_path / "alimentacion" / "procesos" / "exports" / "variables"
    assert proc.exports_bloques == tmp_path / "alimentacion" / "procesos" / "exports" / "bloques"
    assert proc.modified_variables == tmp_path / "alimentacion" / "procesos" / "modified" / "variables"
    assert proc.modified_bloques == tmp_path / "alimentacion" / "procesos" / "modified" / "bloques"
    assert proc.preview_variables == tmp_path / "alimentacion" / "procesos" / "preview" / "variables"
    assert proc.preview_bloques == tmp_path / "alimentacion" / "procesos" / "preview" / "bloques"


def test_clean_resuelve_asimetria(tmp_path: Path) -> None:
    """``clean()`` en dispositivos o procesos limpia exports/ y modified/ por igual.

    Esto cierra la asimetría previa: ``disp_sync_instances`` ya
    limpiaba su workdir, ``proc_sync_comentarios`` no. Ahora ambos
    comparten el mismo helper.

    Tras ``clean()`` las raíces ``exports/`` y ``modified/`` se
    borran enteras y se recrean con las 3 subcarpetas
    (``variables/``, ``bloques/``, ``udt/``) dentro. Para
    verificar "limpio" se comprueba que las subcarpetas typed
    están vacías.
    """
    area = build_cache(root=tmp_path)

    # Stale en ambos contextos (en las subcarpetas typed).
    (area.dispositivos.exports_variables / "old.xml").write_text("old", encoding="utf-8")
    (area.procesos.modified_variables / "old_modified.s7dcl").write_text("old", encoding="utf-8")
    # Y un artefacto de dry-run en preview/ que NO debe ser tocado.
    (area.procesos.preview_variables).mkdir(parents=True, exist_ok=True)
    preview_artifact = area.procesos.preview_variables / "dry_run.json"
    preview_artifact.write_text('{"dry": true}', encoding="utf-8")

    area.dispositivos.clean()
    area.procesos.clean()

    # Las raíces exports/ y modified/ existen (con sus 3 subcarpetas vacías).
    assert area.dispositivos.exports_variables.exists()
    assert area.procesos.modified_variables.exists()
    # Y las subcarpetas typed están vacías.
    assert not list(area.dispositivos.exports_variables.iterdir())
    assert not list(area.procesos.modified_variables.iterdir())
    # Y el preview de procesos sigue intacto.
    assert preview_artifact.exists()
