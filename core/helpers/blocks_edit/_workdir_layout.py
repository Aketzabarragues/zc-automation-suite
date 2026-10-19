"""core.helpers.blocks_edit._workdir_layout - layout del workdir del editor de bloques.

Sigue la convencion del repo (AGENTS.md): workdirs congelados como
dataclass frozen con paths absolutos derivados de DEFAULT_BUILD_CACHE_ROOT.
Mismo patron que ``SdPair`` / ``XmlTarget`` en ``core/infrastructure/tia/tia_export_paths.py``.

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

    Un solo nivel ``preview/<plc_name>/`` con archivos ``<block_name>.s7dcl``
    (FLAT, ``keep_folder_structure=False`` en ``export_blocks``).

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

    def clean_preview(self, plc_name: str | None = None) -> None:
        """Borra y recrea ``preview/`` (o ``preview/<plc_name>/`` si se pasa).

        Sin ``plc_name``: borra ``preview/`` completo y deja un dir vacio
        listo para nuevos exports (mismo patron que ``DispLayout.clean_preview``
        del area alimentacion).

        Con ``plc_name``: borra solo ``preview/<plc_name>/`` y deja el dir
        vacio. Util para limpiar el workdir de un PLC concreto sin tocar
        los exports de otros PLCs (preparar 2 PLCs preserva sus SD por
        separado).

        El FB ``block_edit_prepare`` invoca la variante con ``plc_name``
        al inicio de ``exportar_sd`` para que cada prepare parta de un
        workdir limpio: si en un prepare previo se exportaron bloques
        que ya no existen en TIA, sus ``.s7dcl``/``.s7res`` no contaminan
        el siguiente prepare.
        """
        if plc_name is not None:
            target = self.preview_dir / plc_name
        else:
            target = self.preview_dir
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)

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
