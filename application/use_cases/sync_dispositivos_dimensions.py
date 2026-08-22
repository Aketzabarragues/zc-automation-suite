"""Application Layer - Sincronizar Dimensiones y DTOs de Dispositivos.

Caso de uso: sincroniza el número de dispositivos (N_MAX por tipo) Y
los DTOs de las ListObjects entre un Excel corporativo y el ``AppState``
global.

Flujo (orden deliberado para evitar workbooks simultáneos sobre el
mismo ``.xlsx``):
  1. Lee los DTOs vía ``AlimentacionExcelParser.extraer_dtos`` (abre
     el workbook con ``read_only=False`` para localizar las
     ``ListObjects``; lo cierra en ``finally``).
  2. Actualiza ``AppState.dispositivos_*`` (las 6 listas por tipo) y
     resetea cualquier contenido previo.
  3. Lee las dimensiones vía ``AlimentacionExcelParser.extraer_dimensiones``
     (vuelve a abrir el workbook en ``read_only=True``).
  4. Actualiza ``AppState.dimensiones`` con el valor leído.
  5. Devuelve un resumen del estado.

Este caso de uso es el "cargador maestro" del AppState desde el
Excel; el caso de uso de inyección posterior
(``sync_dispositivos_instances``) es el que finalmente traduce los
DTOs del ``AppState`` en PlcTags reales en TIA Portal.

Restricciones:
  - Esta capa NO importa ``siemens_tia_scripting`` directamente.
  - Los nombres de tabla PLC se resuelven vía ``ConfigManager``.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from application.state import AppState, get_app_state
from infrastructure.alimentacion.parsers.alimentacion_excel_parser import (
    AlimentacionExcelParser,
)


# Mapeo explícito atributo AppState ← clave canónica devuelta por
# ``AlimentacionExcelParser.extraer_dtos``. Mantener sincronizado con
# ``_EXCEL_TARGETS`` del parser.
_DTOS_TARGETS: dict[str, str] = {
    "dispositivos_ed":    "DispED",
    "dispositivos_ea":    "DispEA",
    "dispositivos_sa":    "DispSA",
    "dispositivos_v":     "DispV",
    "dispositivos_m":     "DispM",
    "dispositivos_m_vf":  "DispM_VF",
}


class SyncDispositivosDimensionsUseCase:
    """Caso de Uso: sincroniza N_MAX + DTOs del subdominio alimentación.

    Lee el Excel corporativo y actualiza **tanto** ``AppState.dimensiones``
    como las 6 listas de ``AppState.dispositivos_*``. Este era el bug
    principal del flujo MCP: la versión anterior solo cargaba
    dimensiones, por lo que el preview (``tia_preview_sync_from_excel``)
    veía listas vacías y generaba 0 cambios aun con Excel cargado.
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
        """Lee el Excel y actualiza ``AppState`` (dimensiones + DTOs).

        Args:
            excel_path: Ruta absoluta al archivo Excel corporativo (.xlsx).

        Returns:
            dict ``{success, message, dimensiones, dispositivos}``.

        Raises:
            FileNotFoundError: Si el archivo no existe.
        """
        if not Path(excel_path).is_file():
            raise FileNotFoundError(
                f"El archivo Excel no existe: {excel_path}"
            )

        # 1) DTOs PRIMERO. ``extraer_dtos`` abre el workbook con
        #    ``read_only=False`` (necesario para localizar las
        #    ``ListObjects``) y lo cierra en ``finally``. El orden
        #    está unificado con el router web
        #    ``/api/v1/excel/upload`` para evitar abrir dos
        #    workbooks simultáneos sobre el mismo ``.xlsx``.
        dispositivos_por_tipo = self._excel_parser.extraer_dtos(excel_path)
        for attr_name, canonica in _DTOS_TARGETS.items():
            setattr(
                self._state,
                attr_name,
                list(dispositivos_por_tipo.get(canonica, [])),
            )

        # 2) Dimensiones DESPUÉS. ``extraer_dimensiones`` re-abre el
        #    workbook (``read_only=True``) para resolver los named
        #    ranges ``N_MAX_*`` / ``Num_Disp_*``.
        dimensiones = self._excel_parser.extraer_dimensiones(excel_path)
        self._state.dimensiones = dimensiones

        total_dtos = sum(len(v) for v in dispositivos_por_tipo.values())
        summary_dtos = {
            canonica: len(lista)
            for canonica, lista in dispositivos_por_tipo.items()
        }
        return {
            "success": True,
            "message": (
                f"Excel cargado: {total_dtos} dispositivos en "
                f"{len(summary_dtos)} tipos + dimensiones en AppState."
            ),
            "dimensiones": dataclasses.asdict(dimensiones),
            "dispositivos": summary_dtos,
        }
