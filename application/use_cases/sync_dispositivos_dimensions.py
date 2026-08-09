"""Application Layer - Sincronizar Dimensiones de Dispositivos.

Caso de uso: sincroniza el número de dispositivos (N_MAX por tipo)
entre un Excel corporativo y el ``AppState`` global.

Flujo:
  1. Lee el Excel vía ``AlimentacionExcelParser.extraer_dimensiones`` →
     ``DimensionesDispositivos`` (tipado fuerte).
  2. Actualiza ``AppState.dimensiones`` con el valor leído.
  3. Devuelve un resumen del estado.

El Caso de Uso de "injection" posterior (``sync_dispositivos_instances``)
es el que finalmente traduce los conteos del ``AppState`` en PlcTags
reales en TIA Portal.

Restricciones:
  - Esta capa NO importa ``siemens_tia_scripting`` directamente.
  - Los nombres de tabla PLC se resuelven vía ``ConfigManager``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from application.state import AppState, get_app_state
from infrastructure.alimentacion.parsers.alimentacion_excel_parser import (
    AlimentacionExcelParser,
)


class SyncDispositivosDimensionsUseCase:
    """Caso de Uso: sincroniza N_MAX (conteos) del subdominio alimentación.

    Lee el Excel corporativo y actualiza el ``AppState.dimensiones``.
    """

    def __init__(
        self,
        excel_parser: AlimentacionExcelParser | None = None,
        state: AppState | None = None,
    ) -> None:
        self._excel_parser = excel_parser or AlimentacionExcelParser()
        # Inyección opcional para tests.
        self._state = state if state is not None else get_app_state()

    async def execute(self, excel_path: str) -> dict[str, Any]:
        """Lee el Excel y actualiza ``AppState.dimensiones``.

        Args:
            excel_path: Ruta absoluta al archivo Excel corporativo (.xlsx).

        Returns:
            dict ``{success, message, dimensiones: {campo: valor}}``.
        """
        if not Path(excel_path).is_file():
            raise FileNotFoundError(
                f"El archivo Excel no existe: {excel_path}"
            )

        # 1) Parsear el Excel (lectura CPU-bound: delegamos a quien
        #    invoque este caso de uso en ``asyncio.to_thread`` si va
        #    por el adaptador MCP).
        dimensiones = self._excel_parser.extraer_dimensiones(excel_path)

        # 2) Actualizar el AppState global.
        self._state.dimensiones = dimensiones

        return {
            "success": True,
            "message": "Dimensiones de dispositivos actualizadas en AppState.",
            "dimensiones": {
                "num_disp_ed": dimensiones.num_disp_ed,
                "num_disp_ea": dimensiones.num_disp_ea,
                "num_disp_sa": dimensiones.num_disp_sa,
                "num_disp_v": dimensiones.num_disp_v,
                "num_disp_m": dimensiones.num_disp_m,
                "num_disp_m_vf": dimensiones.num_disp_m_vf,
            },
        }
