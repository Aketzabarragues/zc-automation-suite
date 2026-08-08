"""Application Layer - Sincronizar Instancias de Hardware.

Orquesta la instanciación masiva de variables (PlcTag) y llamadas a
bloques desde un Excel, manteniendo separada la responsabilidad de
redimensionamiento (N_MAX) que vive en ``sync_hardware_dimensions``.

Flujo:
  1. Lee el Excel (``ExcelParser.extraer_dtos``) -> DTOs por tipo.
  2. Exporta la base actual del PLC (``export_plc_tags_xml``,
     ``export_blocks_sd``) -> ``.build_cache/base/``.
  3. Modifica las plantillas offline (XML/.s7dcl) -> ``.build_cache/ready_to_import/``.
  4. Emite operaciones transaccionales ``import_plc_tags_xml`` /
     ``import_blocks_sd`` apuntando a ``ready_to_import``.
  5. Ejecuta el lote en el motor OT con rollback automático.

Las operaciones de modificación offline (XML y SD) se ejecutan en
hilos separados vía ``asyncio.to_thread`` para no bloquear el Event
Loop del servidor MCP.

Restricción arquitectónica: este módulo NO importa ``siemens_tia_scripting``;
toda la comunicación con TIA Portal pasa por ``TIAProcessGateway``.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from infrastructure.gateway import TIAProcessGateway
from infrastructure.parsers.excel_parser import ExcelParser
from infrastructure.sd.modifiers import SDModifier, collect_call_names
from infrastructure.xml.modifiers import TagTableModifier


class SyncHardwareInstancesUseCase:
    """Sincroniza instancias de hardware (DispED, DispV, Motores, etc.)
    declaradas en el Excel contra el PLC, vía modificadores offline
    XML/SD y un lote transaccional de importación."""

    _BUILD_CACHE_DIRNAME = ".build_cache"
    _BASE_SUBDIR = "base"
    _READY_SUBDIR = "ready_to_import"

    def __init__(
        self,
        gateway: TIAProcessGateway,
        excel_parser: ExcelParser | None = None,
        build_cache_dir: Path | None = None,
    ) -> None:
        self._gateway = gateway
        self._excel_parser = excel_parser or ExcelParser()
        self._build_cache = build_cache_dir or (
            Path.cwd() / self._BUILD_CACHE_DIRNAME
        )

    async def execute(self, plc_name: str, excel_path: str) -> dict[str, Any]:
        """Ejecuta el ciclo completo de instanciación.

        Args:
            plc_name:  Nombre exacto del PLC.
            excel_path: Ruta absoluta al Excel con DTOs por hoja.

        Returns:
            dict ``{success, message, operations}``.

        Raises:
            FileNotFoundError: Si ``excel_path`` no existe.
        """
        if not Path(excel_path).is_file():
            raise FileNotFoundError(
                f"El archivo Excel no existe: {excel_path}"
            )

        # 1) Estructura de directorios cacheada.
        base_dir = self._build_cache / self._BASE_SUBDIR
        ready_dir = self._build_cache / self._READY_SUBDIR
        tags_base = base_dir / "tags"
        blocks_base = base_dir / "blocks"
        tags_ready = ready_dir / "tags"
        blocks_ready = ready_dir / "blocks"
        tags_ready.mkdir(parents=True, exist_ok=True)
        blocks_ready.mkdir(parents=True, exist_ok=True)

        # 2) Leer DTOs desde el Excel (CPU-bound -> hilo).
        dtos_by_type: dict[str, list[dict[str, Any]]] = await asyncio.to_thread(
            self._excel_parser.extraer_dtos, excel_path
        )
        if not dtos_by_type:
            return {
                "success": True,
                "message": "El Excel no contiene DTOs de hardware.",
                "operations": 0,
            }

        # 3) Exportación masiva base del PLC (async, vía subprocess OT).
        tags_base.mkdir(parents=True, exist_ok=True)
        blocks_base.mkdir(parents=True, exist_ok=True)
        await self._gateway.export_plc_tags_xml(plc_name, str(tags_base))
        await self._gateway.export_blocks_sd(plc_name, str(blocks_base))

        # 4) Modificación offline (CPU-bound -> hilo).
        modified_tags, modified_blocks = await asyncio.to_thread(
            self._apply_modifications,
            tags_base,
            tags_ready,
            blocks_base,
            blocks_ready,
            dtos_by_type,
        )

        # 5) Construir payload transaccional.
        operations: list[dict[str, Any]] = []
        if modified_tags:
            operations.append(
                {
                    "command": "import_plc_tags_xml",
                    "args": {
                        "plc_name": plc_name,
                        "import_dir": str(tags_ready),
                        "target_folder": "",
                    },
                }
            )
        if modified_blocks:
            operations.append(
                {
                    "command": "import_blocks_sd",
                    "args": {
                        "plc_name": plc_name,
                        "import_dir": str(blocks_ready),
                        "target_folder": "",
                    },
                }
            )

        if not operations:
            return {
                "success": True,
                "message": (
                    "Sin cambios: PLC ya contiene todas las instancias "
                    "declaradas en el Excel (idempotencia)."
                ),
                "operations": 0,
            }

        # 6) Inyección transaccional en el autómata.
        result = await self._gateway.execute_transactional_batch(
            operations, undo_text="Sincronizar Instancias de Hardware"
        )
        return {
            "success": True,
            "message": (
                f"Inyección completada. Detalles: {result['details']}"
            ),
            "operations": result["operations_executed"],
        }

    # ── Lógica offline (síncrona, ejecutada dentro de asyncio.to_thread)
    @staticmethod
    def _apply_modifications(
        tags_base: Path,
        tags_ready: Path,
        blocks_base: Path,
        blocks_ready: Path,
        dtos_by_type: dict[str, list[dict[str, Any]]],
    ) -> tuple[bool, bool]:
        """Modifica cada plantilla XML/SD con los DTOs correspondientes.

        Returns:
            Tupla ``(modified_tags, modified_blocks)``.
        """
        modified_tags = _modify_tags_in_dir(tags_base, tags_ready, dtos_by_type)
        modified_blocks = _modify_sd_in_dir(
            blocks_base, blocks_ready, dtos_by_type
        )
        return modified_tags, modified_blocks


def _modify_tags_in_dir(
    tags_base: Path,
    tags_ready: Path,
    dtos_by_type: dict[str, list[dict[str, Any]]],
) -> bool:
    """Procesa cada ``.xml`` en ``tags_base`` con los DTOs del tipo
    cuyo nombre coincida con el stem del archivo."""
    modified = False
    for xml_file in sorted(tags_base.glob("*.xml")):
        stem = xml_file.stem
        dtos = dtos_by_type.get(stem, [])
        if not dtos:
            continue
        modifier = TagTableModifier(xml_file)
        if modifier.add_tags(dtos) > 0:
            modifier.save(tags_ready / xml_file.name)
            modified = True
    return modified


def _modify_sd_in_dir(
    blocks_base: Path,
    blocks_ready: Path,
    dtos_by_type: dict[str, list[dict[str, Any]]],
) -> bool:
    """Procesa cada ``.s7dcl`` en ``blocks_base`` insertando las llamadas
    recolectadas de todos los DTOs (idempotente por nombre de instancia).

    Corrección crítica del ticket: el glob busca la extensión ``.s7dcl``
    que es la que emite TIA Portal V21 al usar ``export_format=SimaticSD``.
    """
    call_names = collect_call_names(dtos_by_type)
    if not call_names:
        return False
    modified = False
    for sd_file in sorted(blocks_base.glob("*.s7dcl")):
        modifier = SDModifier(sd_file)
        if modifier.insert_calls(call_names):
            modifier.save(blocks_ready / sd_file.name)
            modified = True
    return modified
