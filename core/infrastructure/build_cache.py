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

* **Default del root del build_cache**: ``tempfile.gettempdir() /
  "zc_build_cache"``, NO ``<cwd>/.build_cache``. Justificación:
  TIA Portal V21 abre el directorio ``exports/`` con un handle de
  lectura para enumerar los ``.s7dcl``/``.s7res`` durante el
  ``import_blocks``. Si la ruta está en una unidad de red (ej.
  ``Z:`` donde la SPA corre), TIA rechaza el import con
  ``UnauthorizedAccessException`` (validado 2026-09-07). La carpeta
  temp del usuario está siempre en una unidad local y ambos procesos
  (worker y TIA) tienen acceso.

* Default del root: ``<tempfile.gettempdir()>/zc_build_cache`` (NO
  ``<cwd>/.build_cache``). Razón: TIA Portal V21 hace
  ``DirectoryInfo.InternalGetFiles`` sobre el ``exports/`` durante
  ``import_blocks``. Si el path está en una unidad de red donde
  TIA no tiene los mismos permisos que la SPA, falla con
  ``UnauthorizedAccessException`` (validado 2026-09-07). El temp
  del usuario está siempre en una unidad local accesible por
  ambos procesos. Override vía ``$ZC_BUILD_CACHE_DIR`` si el
  operario necesita otra ruta.

Decisiones diferidas
--------------------

* Migración de ``BuildCache(area_id=AREA_ID)`` a DI en el
  composition root (main.py, app.py, mcp_server.py): NO en este
  plan. La construcción con 1 argumento es trivial; se hace
  oportunistamente cuando se toquen esos archivos por otro motivo.
"""
from __future__ import annotations

import os
import shutil
import tempfile
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


def get_default_build_cache_dir() -> Path:
    """Resuelve el ``root`` del ``BuildCache`` por defecto.

    Orden de resolución:
      1. ``$ZC_BUILD_CACHE_DIR`` (env var) — el operario puede forzar
         una ruta concreta (ej. ``D:\\zc_build_cache``) si quiere.
      2. ``<tempfile.gettempdir()>/zc_build_cache`` — fallback por
         defecto. SIEMPRE apunta a una unidad local (``%TEMP%`` del
         usuario en Windows, ``/tmp`` en Linux), donde TIA Portal y
         el worker pueden leer/escribir sin problemas de permisos.

    Por qué NO usamos ``<cwd>/.build_cache`` como antes: la SPA
    suele correr en una unidad de red (ej. ``Z:`` en setups con
    VM compartida). TIA Portal V21, al hacer ``import_blocks``,
    intenta listar los archivos del ``exports/`` con un handle de
    lectura. Si el path está en una unidad de red donde TIA no
    tiene los mismos permisos que la SPA, falla con
    ``UnauthorizedAccessException`` (validado 2026-09-07 con crash
    dump de TIA: ``System.UnauthorizedAccessException`` en
    ``DirectoryInfo.InternalGetFiles`` durante
    ``SimaticSDImportStrategy.Validate``).

    Returns:
        Path al directorio root del ``BuildCache``. NO garantiza
        que exista — los consumers deben llamar ``mkdir(parents=True,
        exist_ok=True)`` si lo necesitan (o pasar por ``BuildCache``
        / ``ContextCache`` que lo crean al primer acceso).
    """
    custom = os.environ.get("ZC_BUILD_CACHE_DIR", "").strip()
    if custom:
        return Path(custom)
    return Path(tempfile.gettempdir()) / "zc_build_cache"


__all__ = ["BuildCache", "AreaCache", "ContextCache", "get_default_build_cache_dir"]
