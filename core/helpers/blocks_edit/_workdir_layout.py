"""core.helpers.blocks_edit._workdir_layout - layout del workdir del editor de bloques.

Sigue la convencion del repo (AGENTS.md): workdirs congelados como
dataclass frozen con paths absolutos derivados de DEFAULT_BUILD_CACHE_ROOT.
Mismo patron que ``SdPair`` / ``XmlTarget`` en ``core/infrastructure/tia/tia_export_paths.py``.

Estructura::

    .build_cache/blocks_edit/
    +-- preview/
        +-- <block_name>.s7dcl     (FLAT, keep_folder_structure=False)
        +-- <block_name>.s7res

Plano, sin subdir por PLC ni por tipo. Mismo patron que
``DispLayout.clean_preview`` / ``EntidadesLayout.clean_preview`` del area
alimentacion (borra ``preview/`` completo en cada prepare).

El FB ``block_edit_prepare`` consume este layout via inyeccion
(Zona 0 deps), no via path hardcoded.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BLOCKS_EDIT_ROOT: Path = Path(os.getcwd()) / ".build_cache" / "blocks_edit"


@dataclass(frozen=True)
class BlocksEditLayout:
    """Layout inmutable del workdir de exports SD para el editor de bloques.

    Un solo nivel ``preview/`` con archivos ``<block_name>.s7dcl`` /
    ``<block_name>.s7res`` (FLAT, ``keep_folder_structure=False`` en
    ``export_blocks``).

    Solo hay preview: el editor de bloques es READ-then-WRITE, no genera
    artefactos persistentes de sincronizacion.
    """
    area_id: str = "blocks_edit"
    root: Path = DEFAULT_BLOCKS_EDIT_ROOT

    @property
    def preview_dir(self) -> Path:
        return self.root / "preview"

    def clean_preview(self) -> None:
        """Borra y recrea ``preview/`` (vacio, listo para nuevos exports).

        El FB ``block_edit_prepare`` lo invoca al inicio de ``exportar_sd``
        para que cada prepare parta de un workdir limpio: si en un prepare
        previo se exportaron bloques que ya no existen en TIA, sus
        ``.s7dcl``/``.s7res`` no contaminan el siguiente.
        """
        top = self.preview_dir
        if top.exists():
            shutil.rmtree(top)
        top.mkdir(parents=True, exist_ok=True)

    def clean_all(self) -> None:
        """Borra todo el layout (``root``) y deja ``preview/`` vacio."""
        if self.root.exists():
            shutil.rmtree(self.root)
        self.preview_dir.mkdir(parents=True, exist_ok=True)


def blocks_edit_cache(root: Path | None = None) -> BlocksEditLayout:
    """Atajo: devuelve el layout ya configurado. Tests pueden inyectar
    ``root=tmp_path``.
    """
    base = root if root is not None else DEFAULT_BLOCKS_EDIT_ROOT
    return BlocksEditLayout(root=base)


__all__ = [
    "BlocksEditLayout",
    "DEFAULT_BLOCKS_EDIT_ROOT",
    "blocks_edit_cache",
]