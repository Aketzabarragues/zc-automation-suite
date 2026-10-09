"""Workdir layout privado del feature ENTIDADES.

Define los paths en ``.build_cache/alimentacion/entidades/`` que usan
los FB del feature (preview en este commit; sync en commit D).

Estructura::

    entidades/
    +-- preview/
    |   +-- config/         # 0_Config_Generales (N_MAX_ENTIDAD) FLAT
    |   +-- disp/           # 6_Entidades (ent_<plc_tag> entries) FLAT
    |   +-- bloques/        # DB6_ENT (.s7dcl + .s7res) FLAT
    +-- sincronizar/
        +-- variables/{export,modified}
        +-- bloques/{export,modified}

Diferencia clave preview vs sync:
  - preview: FLAT, lectura simple para el diff read-only.
  - sync (D): conserva estructura TIA para que el bulk import detecte
    UPDATE por path relativo.

Convencion: archivo con prefijo ``_`` (privado al area). No se exporta
desde fuera de ``areas/alimentacion/helpers/entidades/``.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path


# Subdirs de sincronizar (mismo nivel: variables y bloques).
_SYNC_VARIABLES = "variables"
_SYNC_BLOQUES = "bloques"

# Sub-subdirs dentro de cada tipo de sincronizar.
_EXPORT = "export"
_MODIFIED = "modified"

# Subdirs de preview.
_PREVIEW_CONFIG = "config"
_PREVIEW_DISP = "disp"
_PREVIEW_BLOQUES = "bloques"


@dataclass(frozen=True)
class EntidadesLayout:
    """Layout del feature ENTIDADES en ``.build_cache/alimentacion/entidades/``.

    Attributes:
        root: raiz del layout (``<build_cache>/alimentacion/entidades``).
    """

    root: Path

    # ── preview/ ──

    @cached_property
    def preview_config(self) -> Path:
        """N_MAX_ENTIDAD: ``0_Config_Generales.xml`` (FLAT)."""
        out = self.root / "preview" / _PREVIEW_CONFIG
        out.mkdir(parents=True, exist_ok=True)
        return out

    @cached_property
    def preview_disp(self) -> Path:
        """Tag table de entidades: ``6_Entidades.xml`` (FLAT, 1 archivo)."""
        out = self.root / "preview" / _PREVIEW_DISP
        out.mkdir(parents=True, exist_ok=True)
        return out

    @cached_property
    def preview_bloques(self) -> Path:
        """DB6_ENT (.s7dcl + .s7res) (FLAT)."""
        out = self.root / "preview" / _PREVIEW_BLOQUES
        out.mkdir(parents=True, exist_ok=True)
        return out

    # ── sincronizar/variables/ ──
    # Se usan en commit D (FB sync transaccional). Se crean ya para que
    # el layout este completo y ``clean_all()`` los pueda recrear.

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
        """Borra y recrea ``preview/{config,disp,bloques}``."""
        top = self.root / "preview"
        if top.exists():
            shutil.rmtree(top)
        for sub in (_PREVIEW_CONFIG, _PREVIEW_DISP, _PREVIEW_BLOQUES):
            (top / sub).mkdir(parents=True, exist_ok=True)

    def clean_sincronizar(self) -> None:
        """Borra y recrea ``sincronizar/{variables,bloques}/{export,modified}``."""
        top = self.root / "sincronizar"
        if top.exists():
            shutil.rmtree(top)
        for tipo in (_SYNC_VARIABLES, _SYNC_BLOQUES):
            for sub in (_EXPORT, _MODIFIED):
                (top / tipo / sub).mkdir(parents=True, exist_ok=True)

    def clean_all(self) -> None:
        """Borra todo el layout de entidades y recrea los subdirs vacios."""
        if self.root.exists():
            shutil.rmtree(self.root)
        for sub in (
            self.preview_config,
            self.preview_disp,
            self.preview_bloques,
            self.sync_variables_export,
            self.sync_variables_modified,
            self.sync_bloques_export,
            self.sync_bloques_modified,
        ):
            sub.mkdir(parents=True, exist_ok=True)


def build_entidades_layout(root: Path | None = None) -> EntidadesLayout:
    """Atajo: devuelve el layout del feature ENTIDADES.

    Por defecto, ``root = <cwd>/.build_cache/alimentacion/entidades``.
    Tests pueden inyectar un ``tmp_path`` directamente.

    Returns:
        ``EntidadesLayout`` con los subdirs ``preview/`` y ``sincronizar/``
        listos para usar.
    """
    if root is None:
        root = Path.cwd() / ".build_cache" / "alimentacion" / "entidades"
    return EntidadesLayout(root=root)


__all__ = ["EntidadesLayout", "build_entidades_layout"]