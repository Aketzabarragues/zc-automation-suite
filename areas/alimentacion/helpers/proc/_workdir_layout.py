"""Workdir layout privado del area de procesos.

Replica temporal de la estructura ``WorkdirContextLayout`` que existia
en ``core/infrastructure/tia/tia_workdir_layout.py`` antes del refactor
greenfield (sept-2026). Solo se usa mientras procesos no migra a su
propia estructura nueva.

Estructura::

    proc/
    +-- preview/
    |   +-- variables/    # tag tables exportadas (TIA estructura)
    |   +-- bloques/      # DBs exportados (TIA estructura)
    |   +-- udt/          # vacio (convencion)
    +-- exports/
    |   +-- variables/    # tag tables snapshot pre-sync
    |   +-- bloques/      # DBs snapshot pre-sync
    |   +-- udt/
    +-- modified/
        +-- variables/    # copia + edits offline
        +-- bloques/
        +-- udt/

Convencion: archivo con prefijo ``_`` (privado al area). NO se reexporta
desde fuera de ``areas/alimentacion/helpers/proc/``.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path


_TYPE_DIRS = ("variables", "bloques", "udt")


@dataclass(frozen=True)
class ProcLayout:
    """Layout de procesos en ``<build_cache>/alimentacion/procesos/``.

    Attributes:
        root: raiz del layout.
    """

    root: Path

    # -- preview/ -----------------------------------------------------

    @cached_property
    def preview_variables(self) -> Path:
        """Tag tables exportadas en preview."""
        out = self.root / "preview" / "variables"
        out.mkdir(parents=True, exist_ok=True)
        return out

    @cached_property
    def preview_bloques(self) -> Path:
        """DBs exportados en preview."""
        out = self.root / "preview" / "bloques"
        out.mkdir(parents=True, exist_ok=True)
        return out

    @cached_property
    def preview_udt(self) -> Path:
        """UDTs exportados en preview (vacio por ahora)."""
        out = self.root / "preview" / "udt"
        out.mkdir(parents=True, exist_ok=True)
        return out

    # -- exports/ -----------------------------------------------------

    @cached_property
    def exports_variables(self) -> Path:
        """Tag tables snapshot pre-sync."""
        out = self.root / "exports" / "variables"
        out.mkdir(parents=True, exist_ok=True)
        return out

    @cached_property
    def exports_bloques(self) -> Path:
        """DBs snapshot pre-sync."""
        out = self.root / "exports" / "bloques"
        out.mkdir(parents=True, exist_ok=True)
        return out

    @cached_property
    def exports_udt(self) -> Path:
        """UDTs snapshot pre-sync (vacio)."""
        out = self.root / "exports" / "udt"
        out.mkdir(parents=True, exist_ok=True)
        return out

    # -- modified/ ----------------------------------------------------

    @cached_property
    def modified_variables(self) -> Path:
        """Copia + edits offline de tag tables."""
        out = self.root / "modified" / "variables"
        out.mkdir(parents=True, exist_ok=True)
        return out

    @cached_property
    def modified_bloques(self) -> Path:
        """Copia + edits offline de DBs."""
        out = self.root / "modified" / "bloques"
        out.mkdir(parents=True, exist_ok=True)
        return out

    @cached_property
    def modified_udt(self) -> Path:
        """Copia + edits offline de UDTs (vacio)."""
        out = self.root / "modified" / "udt"
        out.mkdir(parents=True, exist_ok=True)
        return out

    # -- Limpieza ------------------------------------------------------

    def clean(self) -> None:
        """Borra y recrea ``exports/`` y ``modified/`` con sus 3 subcarpetas.

        NO toca ``preview/`` (semantica legacy de WorkdirContextLayout).
        """
        for top in ("exports", "modified"):
            top_dir = self.root / top
            if top_dir.exists():
                shutil.rmtree(top_dir)
            for type_name in _TYPE_DIRS:
                (top_dir / type_name).mkdir(parents=True, exist_ok=True)

    def clean_preview(self) -> None:
        """Borra y recrea ``preview/`` con sus 3 subcarpetas."""
        top = self.root / "preview"
        if top.exists():
            shutil.rmtree(top)
        for type_name in _TYPE_DIRS:
            (top / type_name).mkdir(parents=True, exist_ok=True)

    def clean_all(self) -> None:
        """Borra y recrea ``preview/``, ``exports/`` y ``modified/``."""
        self.clean_preview()
        self.clean()


def build_proc_layout(root: Path | None = None) -> ProcLayout:
    """Atajo: devuelve el layout de procesos.

    Por defecto, ``root = <cwd>/.build_cache/alimentacion/procesos``.
    Tests pueden inyectar un ``tmp_path`` directamente.

    Returns:
        ``ProcLayout`` con los subdirs ``preview/``, ``exports/``
        y ``modified/`` listos para usar.
    """
    if root is None:
        root = Path.cwd() / ".build_cache" / "alimentacion" / "procesos"
    return ProcLayout(root=root)


__all__ = ["ProcLayout", "build_proc_layout"]
