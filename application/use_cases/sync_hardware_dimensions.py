"""Application Layer - Sincronizar Dimensiones de Hardware.

Orquesta la lectura del Excel (estado *deseado*), la exportación del
estado actual de TIA Portal, el cálculo de diferencias offline y la
inyección transaccional en el autómata.

Arquitectura:
  - Lectura del Excel y parseo del XML se ejecutan en hilos separados
    vía ``asyncio.to_thread`` para no bloquear el Event Loop del
    servidor MCP (criterio de aceptación del ticket).
  - La inyección se delega en ``gateway.execute_transactional_batch``,
    que aísla toda la cadena bajo ``start_transaction`` /
    ``end_transaction(rollback=True)`` en el worker OT.

Restricciones:
  - Esta capa NO importa ``siemens_tia_scripting`` directamente; toda
    la comunicación con TIA Portal pasa por ``TIAProcessGateway``.
  - Los nombres de tabla PLC se resuelven vía ``ConfigManager`` (no se
    hardcodean nombres como ``"000_Config_Dispositivos"``).
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from infrastructure.config_manager import ConfigManager
from infrastructure.gateway import TIAProcessGateway
from infrastructure.parsers.excel_parser import ExcelParser
from infrastructure.xml.tag_table_parser import SimaticMLTagParser

from application.use_cases.diff_constants import CalculateConstantsDiffUseCase


class SyncHardwareDimensionsUseCase:
    """Caso de Uso: sincroniza N_MAX/constantes PLC desde un Excel.

    Flujo:
      1. Lee el Excel (estado *deseado*).
      2. Exporta la tabla de configuración del PLC a XML (estado *actual*).
      3. Parsea el XML y calcula el diff offline.
      4. Si hay diferencias, las inyecta en una transacción atómica.
    """

    _BUILD_CACHE_DIRNAME = ".build_cache"

    def __init__(
        self,
        gateway: TIAProcessGateway,
        config_manager: ConfigManager,
        excel_parser: ExcelParser | None = None,
        build_cache_dir: Path | None = None,
    ) -> None:
        self._gateway = gateway
        self._config = config_manager
        # Inyección opcional para tests / sustitución futura.
        self._excel_parser = excel_parser or ExcelParser()
        self._build_cache_dir = build_cache_dir or (
            Path(os.getcwd()) / self._BUILD_CACHE_DIRNAME
        )

    async def execute(self, plc_name: str, excel_path: str) -> dict[str, Any]:
        """Ejecuta el ciclo completo de sincronización.

        Args:
            plc_name:  Nombre exacto del PLC en el proyecto TIA Portal.
            excel_path: Ruta absoluta al archivo Excel corporativo (.xlsx).

        Returns:
            dict con ``{success, message, operations}``.

        Raises:
            FileNotFoundError: Si ``excel_path`` no existe.
        """
        if not Path(excel_path).is_file():
            raise FileNotFoundError(
                f"El archivo Excel no existe: {excel_path}"
            )

        # 1) Estado deseado desde Excel.
        # El parseo es CPU-bound; lo aislamos en un hilo para no
        # bloquear el Event Loop (criterio de aceptación del ticket).
        desired_state: dict[str, int] = await asyncio.to_thread(
            self._excel_parser.extraer_dimensiones, excel_path
        )

        if not desired_state:
            return {
                "success": True,
                "message": "El Excel no contiene dimensiones definidas.",
                "operations": 0,
            }

        # 2) Resolver el nombre de la tabla de configuración desde
        #    config.json (sin hardcodear nombres en este archivo).
        config_table_name = self._config.get_global_config_table_name()

        # 3) Exportar estado actual de TIA Portal → XML offline.
        #    Esta llamada es async: cruza el boundary del subproceso OT.
        self._build_cache_dir.mkdir(parents=True, exist_ok=True)
        await self._gateway.export_tag_table(
            plc_name, config_table_name, str(self._build_cache_dir)
        )
        xml_file_path = self._build_cache_dir / f"{config_table_name}.xml"

        # 4) Parsear XML offline. CPU-bound → hilo separado.
        current_state: dict[str, str] = await asyncio.to_thread(
            SimaticMLTagParser.parse_user_constants, xml_file_path
        )

        # 5) Calcular el batch de operaciones (diff desired vs. current).
        operations = CalculateConstantsDiffUseCase.execute(
            plc_name, config_table_name, current_state, desired_state
        )

        if not operations:
            return {
                "success": True,
                "message": (
                    "Sincronización omitida: El PLC ya coincide con el Excel."
                ),
                "operations": 0,
            }

        # 6) Inyección transaccional en TIA Portal.
        undo_text = f"Sincronizar Dimensiones ({len(operations)} cambios)"
        result = await self._gateway.execute_transactional_batch(
            operations, undo_text
        )

        return {
            "success": True,
            "message": (
                f"Sincronización completada. Detalles: {result['details']}"
            ),
            "operations": result["operations_executed"],
        }
