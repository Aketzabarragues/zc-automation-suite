"""Jerarquía canónica de workdirs de export/modificación.

Convención de la app (NO config del proyecto)
=============================================

Cada área (Bounded Context) necesita una matriz 3×3 de subcarpetas
para el ciclo "exportar de TIA → modificar offline → importar a TIA"::

    .build_cache/
    └── <area_id>/                          # área (alimentacion, trazabilidad, ...)
        └── <contexto>/                     # bounded context del área (dispositivos, ...)
            ├── preview/                    # read-only. Lo que se NECESITA para el diff.
            │   ├── variables/              # TAG tables (XML)
            │   ├── bloques/                # Program blocks (.s7dcl/.s7res)
            │   └── udt/                    # User Data Types — convención, vacío por ahora
            ├── exports/                    # snapshot limpio de TIA. SE QUEDA tras commit.
            │   ├── variables/
            │   ├── bloques/
            │   └── udt/
            └── modified/                   # copy de exports/ + edit del updater. SE QUEDA tras commit.
                ├── variables/
                ├── bloques/
                └── udt/

Las 3 carpetas de alto nivel (``preview/``, ``exports/``, ``modified/``)
corresponden a las 3 fases del flujo: dry-run, snapshot pre-commit, y
snapshot listo para importar. Dentro de cada una, las 3 subcarpetas
(``variables/``, ``bloques/``, ``udt/``) separan por tipo de artefacto
TIA, lo que da claridad y deja sitio al futuro updater de UDTs.

Reglas de retención (acordado 2026-09-08, ver ``_plan/16_carpetas_convencion.md``)
---------------------------------------------------------------------------------

* Las 3 carpetas se limpian **solo al inicio** de la operación que las
  regenera. Después se quedan para auditoría hasta el siguiente ciclo.

  - ``preview/``  se limpia al inicio de ``generar_prevision``.
  - ``exports/``  se limpia al inicio de ``ejecutar_transaccion``.
  - ``modified/`` se limpia al inicio de ``ejecutar_transaccion``
    (junto con ``exports/``).

* ``git diff modified/ exports/`` tras un commit muestra exactamente qué
  cambió el updater. ``git diff modified/ preview/`` muestra qué se habría
  aplicado si se hubiera confirmado el preview anterior.

* **Los alias raíz ``preview``, ``exports`` y ``modified`` se
  retiraron en el commit 6 del plan**. Todo el código usa las
  6 subcarpetas explícitas (``preview_variables`` /
  ``preview_bloques`` / ``exports_variables`` / ``exports_bloques``
  / ``modified_variables`` / ``modified_bloques``).

Reglas de arquitectura
----------------------

* El core **NO sabe qué áreas existen**. Por eso ``area_id`` es
  obligatorio (sin default): cada consumer pasa el suyo. El día que
  llegue un 2º área, no hay que tocar este módulo — solo extender
  ``AreaCache`` desde el paquete del área.

* La estructura se mantiene estable durante TODA la vida del proceso
  (cachea ``Path`` en ``@cached_property``). Crear o borrar los
  directorios físicos es responsabilidad de ``ContextCache.clean()``
  (que borra y recrea) o de los consumers (que los crean con
  ``mkdir(parents=True, exist_ok=True)`` cuando los necesitan).

* ``.build_cache/`` está dentro del cwd por convención. Si en el
  futuro hay que moverlo (a ``%LocalAppData%``, etc.), se replica
  el patrón de ``core/application/log_paths.py:ZC_LOG_DIR``. YAGNI
  por ahora (ver ``_plan/08_routes_standardization.md`` §5).

* NO se añade ``ZC_BUILD_CACHE_DIR`` env var todavía (mismo YAGNI).
  Si el operario lo necesita, lo pide y se hace en un PR específico.

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
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path


# Nombre del directorio raíz de la jerarquía. Hardcoded por convención
# (NO config). Si se externaliza algún día, se mete en config.json y
# este módulo lo lee de allí.
_BUILD_CACHE_DIRNAME: str = ".build_cache"

# Tipos de artefacto TIA dentro de cada subcarpeta (preview/, exports/,
# modified/). ``variables`` = TAG tables, ``bloques`` = Program blocks
# (.s7dcl/.s7res), ``udt`` = User Data Types. Por convención, no por
# config: cuando llegue el updater de UDTs, la subcarpeta ya existe.
_TYPE_DIRS: tuple[str, ...] = ("variables", "bloques", "udt")


@dataclass(frozen=True)
class BuildCache:
    """Raíz de los workdirs de export/modificación.

    Estructura canónica::

        <root>/<area_id>/<contexto>/{preview,exports,modified}/{variables,bloques,udt}

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


def _type_path(parent: Path, type_name: str) -> Path:
    """Resuelve ``<parent>/<type_name>`` y se asegura de que existe.

    Idempotente: ``mkdir(parents=True, exist_ok=True)`` no falla si
    el directorio ya existe. Se llama en cada acceso al ``cached_property``
    para que el directorio esté disponible desde el primer momento
    sin requerir un ``clean()`` previo.
    """
    p = parent / type_name
    p.mkdir(parents=True, exist_ok=True)
    return p


@dataclass(frozen=True)
class ContextCache:
    """Matriz 3×3 de subcarpetas: 3 fases × 3 tipos de artefacto TIA.

    Estructura::

        <root>/{preview,exports,modified}/{variables,bloques,udt}

    Attributes:
        root: Directorio del contexto (``<area>/<contexto>``).

    Los call sites usan las 6 subcarpetas explícitas
    (``preview_variables`` / ``preview_bloques`` / ``exports_variables``
    / ``exports_bloques`` / ``modified_variables`` / ``modified_bloques``).
    Los alias raíz ``preview``, ``exports`` y ``modified`` se
    retiraron en el commit 6 del plan (``_plan/16_carpetas_convencion.md``).
    """

    root: Path

    # ── preview/ ────────────────────────────────────────────────────
    @cached_property
    def preview_variables(self) -> Path:
        """TAG tables (XML) para el diff. Read-only."""
        return _type_path(self.root / "preview", "variables")

    @cached_property
    def preview_bloques(self) -> Path:
        """Program blocks (.s7dcl/.s7res) para el diff. Read-only."""
        return _type_path(self.root / "preview", "bloques")

    @cached_property
    def preview_udt(self) -> Path:
        """User Data Types para el diff. Vacío por ahora (convención futura)."""
        return _type_path(self.root / "preview", "udt")

    # ── exports/ ────────────────────────────────────────────────────
    @cached_property
    def exports_variables(self) -> Path:
        """TAG tables (XML). Snapshot limpio de TIA."""
        return _type_path(self.root / "exports", "variables")

    @cached_property
    def exports_bloques(self) -> Path:
        """Program blocks (.s7dcl/.s7res). Snapshot limpio de TIA."""
        return _type_path(self.root / "exports", "bloques")

    @cached_property
    def exports_udt(self) -> Path:
        """User Data Types. Snapshot limpio de TIA. Vacío por ahora."""
        return _type_path(self.root / "exports", "udt")

    # ── modified/ ───────────────────────────────────────────────────
    @cached_property
    def modified_variables(self) -> Path:
        """TAG tables (XML). Copy de exports/ + edit del updater."""
        return _type_path(self.root / "modified", "variables")

    @cached_property
    def modified_bloques(self) -> Path:
        """Program blocks (.s7dcl/.s7res). Copy de exports/ + edit del updater."""
        return _type_path(self.root / "modified", "bloques")

    @cached_property
    def modified_udt(self) -> Path:
        """User Data Types. Copy de exports/ + edit del updater. Vacío por ahora."""
        return _type_path(self.root / "modified", "udt")

    # ── Limpieza ────────────────────────────────────────────────────
    def clean(self) -> None:
        """Borra y recrea ``exports/`` y ``modified/`` con sus 3 subcarpetas.

        Borra las raíces ``<root>/exports/`` y ``<root>/modified/``
        enteras (atrapando archivos sueltos pre-Commit-1) y las
        recrea con las 3 subcarpetas (``variables/``, ``bloques/``,
        ``udt/``) dentro. ``preview/`` NO se toca (puede contener
        dry-runs en curso o artefactos históricos). Para limpiar
        preview, usar ``clean_preview()``.

        Regla de retención: cada operación arranca limpia. Se
        invoca al inicio de ``ejecutar_transaccion``. Para
        ``generar_prevision``, usar ``clean_preview()``.

        Idempotente: si los subdirs no existen, los crea vacíos.
        """
        for top in ("exports", "modified"):
            top_dir = self.root / top
            if top_dir.exists():
                shutil.rmtree(top_dir)
            for type_name in _TYPE_DIRS:
                (top_dir / type_name).mkdir(parents=True, exist_ok=True)

    def clean_preview(self) -> None:
        """Borra y recrea ``preview/`` con sus 3 subcarpetas.

        Se invoca al inicio de ``generar_prevision`` (junto con
        un export fresco de TIA). Análogo a ``clean()`` pero solo
        para la fase read-only.
        """
        top_dir = self.root / "preview"
        if top_dir.exists():
            shutil.rmtree(top_dir)
        for type_name in _TYPE_DIRS:
            (top_dir / type_name).mkdir(parents=True, exist_ok=True)


__all__ = ["BuildCache", "AreaCache", "ContextCache"]
