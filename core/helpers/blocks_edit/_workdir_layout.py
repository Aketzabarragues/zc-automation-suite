"""core.helpers.blocks_edit._workdir_layout - layout del workdir del editor de bloques.

Sigue la convencion del repo (AGENTS.md): workdirs congelados como
dataclass frozen con paths absolutos derivados de DEFAULT_BUILD_CACHE_ROOT.
Mismo patron que ``SdPair`` / ``XmlTarget`` en ``core/infrastructure/tia/tia_export_paths.py``.

El FB ``block_edit_prepare`` consumira este layout via inyeccion (Zona 0 deps),
en lugar del path hardcoded que tenia el commit 8b (bee21af).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BLOCKS_EDIT_ROOT: Path = Path(os.getcwd()) / ".build_cache" / "blocks_edit"


@dataclass(frozen=True)
class BlocksEditLayout:
    """Layout inmutable del workdir de exports SD para el editor de bloques.

    Un solo nivel ``preview/<plc_name>/`` con archivos ``<block_name>.s7dcl``
    (FLAT, ``keep_folder_structure=False`` en ``export_block``).

    A diferencia de los layouts de alimentacion (que tienen preview/sincronizar),
    aqui solo hay preview: el editor de bloques es READ-then-WRITE, no genera
    artefactos persistentes de sincronizacion.
    """
    area_id: str = "blocks_edit"
    root: Path = DEFAULT_BLOCKS_EDIT_ROOT

    @property
    def preview_dir(self) -> Path:
        return self.root / "preview"

    def preview_for_plc(self, plc_name: str) -> Path:
        """Directorio de exports SD para un PLC concreto."""
        return self.preview_dir / plc_name


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
