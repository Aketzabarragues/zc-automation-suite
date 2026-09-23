"""Workdir layout privado del area proc_db.

Espejo de DispLayout: misma estructura preview/ FLAT + sincronizar/
estructura TIA. Solo cambia el contenido: proc_db NO separa N_MAX en
preview/config/ (la lee directo de la tabla del proceso en
preview/variables/).

Estructura::

    proc_db/
    +-- preview/
    |   +-- bloques/        # DBs exportados (FLAT)
    |   +-- variables/      # tag tables exportadas (FLAT)
    +-- sincronizar/
        +-- variables/
        |   +-- export/     # estructura TIA
        |   +-- modified/   # estructura TIA (copy + edits)
        +-- bloques/
            +-- export/
            +-- modified/

Convencion: archivo con prefijo ``_`` (privado al area). No se exporta
desde fuera de ``areas/alimentacion/helpers/proc/``.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path


# Subdirs de preview (mismo nivel: bloques y variables).
_PREVIEW_BLOQUES = "bloques"
_PREVIEW_VARIABLES = "variables"

# Subdirs de sincronizar (mismo nivel: variables y bloques).
_SYNC_VARIABLES = "variables"
_SYNC_BLOQUES = "bloques"

# Sub-subdirs dentro de cada tipo de sincronizar.
_EXPORT = "export"
_MODIFIED = "modified"


@dataclass(frozen=True)
class ProcDbLayout:
    """Layout de proc_db en ``.build_cache/alimentacion/proc_db/``.

    Attributes:
        root: raiz del layout (``<build_cache>/alimentacion/proc_db``).
    """

    root: Path

    # ── preview/ ──
    # (FLAT — mismo split bloques/variables que DispLayout.)

    @cached_property
    def preview_bloques(self) -> Path:
        """DBs exportados del proceso (FLAT)."""
        out = self.root / "preview" / _PREVIEW_BLOQUES
        out.mkdir(parents=True, exist_ok=True)
        return out

    @cached_property
    def preview_variables(self) -> Path:
        """Tag tables del proceso exportadas (FLAT). Aqui vive la
        PlcUserConstant N_MAX del proceso."""
        out = self.root / "preview" / _PREVIEW_VARIABLES
        out.mkdir(parents=True, exist_ok=True)
        return out

    # ── sincronizar/variables/ ──

    @cached_property
    def sync_variables_export(self) -> Path:
        """Tag tables exportadas de TIA con estructura original."""
        out = self.root / "sincronizar" / _SYNC_VARIABLES / _EXPORT
        out.mkdir(parents=True, exist_ok=True)
        return out

    @cached_property
    def sync_variables_modified(self) -> Path:
        """Copia de export + edits offline (estructura TIA conservada)."""
        out = self.root / "sincronizar" / _SYNC_VARIABLES / _MODIFIED
        out.mkdir(parents=True, exist_ok=True)
        return out

    # ── sincronizar/bloques/ ──

    @cached_property
    def sync_bloques_export(self) -> Path:
        """DBs exportados de TIA con estructura original."""
        out = self.root / "sincronizar" / _SYNC_BLOQUES / _EXPORT
        out.mkdir(parents=True, exist_ok=True)
        return out

    @cached_property
    def sync_bloques_modified(self) -> Path:
        """Copia de export + edits offline (estructura TIA conservada)."""
        out = self.root / "sincronizar" / _SYNC_BLOQUES / _MODIFIED
        out.mkdir(parents=True, exist_ok=True)
        return out

    # ── Limpieza ──

    def clean_preview(self) -> None:
        """Borra y recrea ``preview/{bloques,variables}``."""
        top = self.root / "preview"
        if top.exists():
            shutil.rmtree(top)
        (top / _PREVIEW_BLOQUES).mkdir(parents=True, exist_ok=True)
        (top / _PREVIEW_VARIABLES).mkdir(parents=True, exist_ok=True)

    def clean_sincronizar(self) -> None:
        """Borra y recrea ``sincronizar/{variables,bloques}/{export,modified}``."""
        top = self.root / "sincronizar"
        if top.exists():
            shutil.rmtree(top)
        for tipo in (_SYNC_VARIABLES, _SYNC_BLOQUES):
            for sub in (_EXPORT, _MODIFIED):
                (top / tipo / sub).mkdir(parents=True, exist_ok=True)

    def clean_all(self) -> None:
        """Borra todo el layout de proc_db y recrea los subdirs vacios."""
        if self.root.exists():
            shutil.rmtree(self.root)
        for sub in (
            self.preview_bloques,
            self.preview_variables,
            self.sync_variables_export,
            self.sync_variables_modified,
            self.sync_bloques_export,
            self.sync_bloques_modified,
        ):
            sub.mkdir(parents=True, exist_ok=True)


def build_proc_db_layout(root: Path | None = None) -> ProcDbLayout:
    """Atajo: devuelve el layout de proc_db.

    Por defecto, ``root = <cwd>/.build_cache/alimentacion/proc_db``.
    Tests pueden inyectar un ``tmp_path`` directamente.

    Returns:
        ``ProcDbLayout`` con los subdirs ``preview/`` y ``sincronizar/``
        listos para usar.
    """
    if root is None:
        root = Path.cwd() / ".build_cache" / "alimentacion" / "proc_db"
    return ProcDbLayout(root=root)


__all__ = ["ProcDbLayout", "build_proc_db_layout"]
