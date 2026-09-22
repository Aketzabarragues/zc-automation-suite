"""Workdir layout privado del area de dispositivos.

Define los paths en ``.build_cache/alimentacion/disp/`` que usan
``disp_generate_preview`` y ``disp_Sincronizar``.

Estructura nueva::

    disp/
    +-- preview/
    |   +-- config/    # N_MAX (FLAT, 1 archivo)
    |   +-- disp/      # 6 tag tables (FLAT)
    +-- sincronizar/
        +-- variables/
        |   +-- export/    # de TIA con estructura original
        |   +-- modified/  # copia + edits offline (estructura TIA)
        +-- bloques/
            +-- export/    # de TIA con estructura original
            +-- modified/  # copia + edits offline (estructura TIA)

Diferencia clave preview vs sync:
  - preview: FLAT, nombres en config.json, lectura simple.
  - sync: conserva estructura TIA para que el bulk import detecte UPDATE por path relativo.

Convencion: archivo con prefijo ``_`` (privado al area). No se exporta
desde fuera de ``areas/alimentacion/helpers/disp/``.
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


@dataclass(frozen=True)
class DispLayout:
    """Layout de dispositivos en ``.build_cache/alimentacion/disp/``.

    Attributes:
        root: raiz del layout (``<build_cache>/alimentacion/disp``).
    """

    root: Path

    # ── preview/ ──
    # (Estructura nueva: FLAT, split config vs disp)

    @cached_property
    def preview_config(self) -> Path:
        """N_MAX: ``000_Config_Dispositivos.xml`` (FLAT)."""
        out = self.root / "preview" / _PREVIEW_CONFIG
        out.mkdir(parents=True, exist_ok=True)
        return out

    @cached_property
    def preview_disp(self) -> Path:
        """6 tag tables de dispositivos: ``2000_Disp_*.xml`` (FLAT)."""
        out = self.root / "preview" / _PREVIEW_DISP
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
        """Borra y recrea ``preview/{config,disp}``."""
        top = self.root / "preview"
        if top.exists():
            shutil.rmtree(top)
        (top / _PREVIEW_CONFIG).mkdir(parents=True, exist_ok=True)
        (top / _PREVIEW_DISP).mkdir(parents=True, exist_ok=True)

    def clean_sincronizar(self) -> None:
        """Borra y recrea ``sincronizar/{variables,bloques}/{export,modified}``."""
        top = self.root / "sincronizar"
        if top.exists():
            shutil.rmtree(top)
        for tipo in (_SYNC_VARIABLES, _SYNC_BLOQUES):
            for sub in (_EXPORT, _MODIFIED):
                (top / tipo / sub).mkdir(parents=True, exist_ok=True)

    def clean_all(self) -> None:
        """Borra todo el layout de dispositivos y recrea los subdirs vacios."""
        if self.root.exists():
            shutil.rmtree(self.root)
        for sub in (
            self.preview_config,
            self.preview_disp,
            self.sync_variables_export,
            self.sync_variables_modified,
            self.sync_bloques_export,
            self.sync_bloques_modified,
        ):
            sub.mkdir(parents=True, exist_ok=True)


def build_disp_layout(root: Path | None = None) -> DispLayout:
    """Atajo: devuelve el layout de dispositivos.

    Por defecto, ``root = <cwd>/.build_cache/alimentacion/disp``.
    Tests pueden inyectar un ``tmp_path`` directamente.

    Returns:
        ``DispLayout`` con los subdirs ``preview/`` y ``sincronizar/``
        listos para usar.
    """
    if root is None:
        root = Path.cwd() / ".build_cache" / "alimentacion" / "disp"
    return DispLayout(root=root)


__all__ = ["DispLayout", "build_disp_layout"]
