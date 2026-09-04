"""Jerarquía canónica de workdirs de export/modificación.

Convención de la app (NO config del proyecto)
=============================================

Cada área (Bounded Context) necesita 3 subestados estables de un
mismo workdir para el ciclo "exportar de TIA → modificar offline →
importar a TIA"::

    .build_cache/
    └── <area_id>/                # área (alimentacion, trazabilidad, ...)
        └── <contexto>/           # bounded context del área (dispositivos, ...)
            ├── exports/          # lo recién exportado de TIA (sin tocar)
            ├── modified/         # lo que los modificadores ya tocaron
            └── preview/          # dry-runs, N_MAX preview, diffs

Reglas de arquitectura
----------------------

* El core **NO sabe qué áreas existen**. Por eso ``area_id`` es
  obligatorio (sin default): cada consumer pasa el suyo. El día que
  llegue un 2º área, no hay que tocar este módulo — solo extender
  ``AreaCache`` desde el paquete del área.

* La estructura se mantiene estable durante TODA la vida del proceso
  (cachea ``Path`` en ``@cached_property``). Crear o borrar los
  directorios físicos es responsabilidad de ``ContextCache.clean()``
  (que los borra y recrea) o de los consumers (que los crean con
  ``mkdir(parents=True, exist_ok=True)`` cuando los necesitan).

* ``.build_cache/`` está dentro del cwd por convención. Si en el
  futuro hay que moverlo (a ``%LocalAppData%``, etc.), se replica
  el patrón de ``core/application/log_paths.py:ZC_LOG_DIR``. YAGNI
  por ahora (ver ``_plan/08_routes_standardization.md`` §5).

* NO se añade ``ZC_BUILD_CACHE_DIR`` env var todavía (mismo YAGNI).
  Si el operario lo necesita, lo pide y se hace en un PR específico.

Decisiones diferidas
--------------------

* ``comments/`` del ``update_disp_instance_comments_batch`` (legacy,
  gateway.py:833) no encaja con ``exports/modified/preview``; se
  aborda en Tarea 2.4 con un ``@cached_property`` específico.

* Migración de ``BuildCache(area_id=AREA_ID)`` a DI en el
  composition root (main.py, app.py, mcp_server.py): NO en este
  plan. La construcción con 1 argumento es trivial; se hace
  oportunistamente cuando se toquen esos archivos por otro motivo.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path


# Nombre del directorio raíz de la jerarquía. Hardcoded por convención
# (NO config). Si se externaliza algún día, se mete en config.json y
# este módulo lo lee de allí.
_BUILD_CACHE_DIRNAME: str = ".build_cache"


@dataclass(frozen=True)
class BuildCache:
    """Raíz de los workdirs de export/modificación.

    Estructura canónica::

        <root>/<area_id>/<contexto>/{exports,modified,preview}

    Attributes:
        area_id: Identificador del área (Bounded Context). OBLIGATORIO
                 — el core no sabe qué áreas existen. Cada consumer
                 (área) pasa el suyo (``from areas.<area> import AREA_ID``).
        root:    Directorio raíz de la jerarquía. Por defecto
                 ``<cwd>/.build_cache``. Inyectable para tests
                 (``tmp_path``) y para mover el workdir fuera del cwd
                 en el futuro.
    """

    area_id: str
    root: Path = field(default_factory=lambda: Path(os.getcwd()) / _BUILD_CACHE_DIRNAME)

    @cached_property
    def area(self) -> "AreaCache":
        """Sub-jerarquía del área: ``<root>/<area_id>/``.

        Se delega en ``AreaCache`` (no se devuelve un ``Path`` crudo)
        para que mañana cada área pueda aportar su propio ``AreaCache``
        extendido con los contextos que necesite (dispositivos,
        procesos, lotes, recetas, etc.).
        """
        return AreaCache(self.area_id, self.root / self.area_id)


@dataclass(frozen=True)
class AreaCache:
    """Contenedor base por área.

    El core solo conoce el ``root`` del área. Los **contextos**
    (dispositivos, procesos, etc.) los aporta cada área en su
    propio paquete extendiendo esta clase. Ver
    ``areas/alimentacion/infrastructure/build_cache.py`` para el caso
    concreto de hoy.

    Attributes:
        area_id: Identificador del área (mismo que en ``BuildCache``).
        root:    ``<build_cache.root>/<area_id>``.
    """

    area_id: str
    root: Path


@dataclass(frozen=True)
class ContextCache:
    """3 subestados de un contexto de dominio.

    Attributes:
        root: Directorio del contexto (``<area>/<contexto>``).
    """

    root: Path

    @cached_property
    def exports(self) -> Path:
        """Lo recién exportado de TIA. Inmutable hasta el siguiente apply."""
        return self.root / "exports"

    @cached_property
    def modified(self) -> Path:
        """Lo que los modificadores ya tocaron. Listo para importar."""
        return self.root / "modified"

    @cached_property
    def preview(self) -> Path:
        """Dry-runs, N_MAX preview, diffs. NO se borra en ``clean()``."""
        return self.root / "preview"

    @cached_property
    def comments(self) -> Path:
        """Workdir legacy del flujo ``update_disp_instance_comments_batch``.

        El gateway ``TIAProcessGateway.update_disp_instance_comments_batch``
        constru\u00eda ``<build_cache>/comments/`` como workdir para los
        6 DBs de dispositivos (ED/EA/SA/V/M/M_VF). Este caso NO encaja
        con la convenci\u00f3n ``exports/modified/preview`` (es un flujo
        anterior a la normalizaci\u00f3n) pero se conserva el nombre por
        back-compat con el handler del worker OT
        (``update_disp_comments_db_<hw>``), que recibe ``work_dir`` como
        argumento y lo usa para escribir el ``.s7dcl``/``.s7res``
        modificado.

        Si en el futuro este flujo se unifica con
        ``DispSyncInstancesUseCase`` (que ahora usa ``exports/``), se
        puede eliminar esta propiedad sin tocar el handler del worker
        (es un cambio interno al gateway).
        """
        return self.root / "comments"

    def clean(self) -> None:
        """Borra y recrea ``exports/`` y ``modified/``.

        ``preview/`` NO se toca: puede contener dry-runs en curso o
        artefactos históricos que el operario quiere consultar tras
        el apply.

        Resuelve la asimetría detectada en la research previa:
        ``disp_sync_instances`` ya limpiaba su workdir antes del
        apply, pero ``proc_sync_comentarios`` no — riesgo de
        contaminación de diffs con residuos de runs anteriores.

        Idempotente: si los subdirs no existen, los crea vacíos.
        """
        for sub in (self.exports, self.modified):
            if sub.exists():
                shutil.rmtree(sub)
            sub.mkdir(parents=True, exist_ok=True)


__all__ = ["BuildCache", "AreaCache", "ContextCache"]
