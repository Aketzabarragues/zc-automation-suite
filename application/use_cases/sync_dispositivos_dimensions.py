"""Application Layer - Sincronizar Dimensiones y DTOs de Dispositivos.

Caso de uso: sincroniza el número de dispositivos (N_MAX por tipo) Y
los DTOs de las ListObjects entre un Excel corporativo y el ``AppState``
global.

Flujo (orden deliberado para evitar workbooks simultáneos sobre el
mismo ``.xlsx``):
  1. Lee los DTOs vía ``AlimentacionExcelParser.extraer_dtos`` (abre
     el workbook con ``read_only=False`` para localizar las
     ``ListObjects``; lo cierra en ``finally``).
  2. Actualiza ``AppState.dispositivos_*`` (las listas por tipo) y
     resetea cualquier contenido previo. **Data-driven** vía
     ``ConfigManager``: para cada ``hw_type`` activo se obtiene el
     ``app_state_attr`` y el ``canonical`` del Excel.
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
from infrastructure.config_manager import ConfigManager


class SyncDispositivosDimensionsUseCase:
    """Caso de Uso: sincroniza N_MAX + DTOs del subdominio alimentación.

    Lee el Excel corporativo y actualiza **tanto** ``AppState.dimensiones``
    como las listas de ``AppState.dispositivos_*`` (6 legacy + futuras
    data-driven). Este era el bug principal del flujo MCP: la versión
    anterior solo cargaba dimensiones, por lo que el preview
    (``tia_preview_sync_from_excel``) veía listas vacías y generaba
    0 cambios aun con Excel cargado.

    El mapeo ``app_state_attr ↔ excel_canonical`` ya no es
    hardcoded: se consulta ``ConfigManager`` (inyectado o
    instanciado en el constructor). Los 6 legacy siguen
    funcionando idéntico porque las convenciones del
    ``ConfigManager`` (``dispositivos_<hw>`` y ``Disp<HW>``)
    coinciden con los nombres que el código legacy usaba.
    """

    def __init__(
        self,
        excel_parser: AlimentacionExcelParser | None = None,
        state: AppState | None = None,
        config_manager: ConfigManager | None = None,
    ) -> None:
        # Si nos pasan parser, NO construimos uno nuevo para no romper
        # la inyección de tests. El parser puede no llevar CM dentro;
        # si no lo lleva, instanciamos uno por defecto.
        self._excel_parser = excel_parser or AlimentacionExcelParser()
        # Resolvedor único: si no se inyecta, instanciamos el default
        # apuntando al JSON del repo.
        self._config = config_manager or ConfigManager()
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
        self._apply_dtos_to_state(dispositivos_por_tipo)

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

    # ── Helpers privados ────────────────────────────────────────────────

    def _apply_dtos_to_state(
        self,
        dispositivos_por_tipo: dict[str, list[Any]],
    ) -> None:
        """Aplica ``{canonical: [Disp*]}`` al ``AppState``.

        Recorre los ``hw_type`` activos del ``ConfigManager`` y, para
        cada uno, lee su ``app_state_attr`` y su ``canonical``. El
        atributo del ``AppState`` se actualiza con la lista del
        Excel (o ``[]`` si la tabla no estaba en el libro).

        Los tipos legacy (``ed/ea/sa/v/m/m_vf``) usan la propiedad
        concreta (``state.dispositivos_ed = ...``), que AppState
        sincroniza automáticamente con ``_dispositivos`` vía
        ``__setattr__``. Los tipos nuevos (futuros) usan
        ``state.set_devices(hw, devices)`` directamente.
        """
        for hw in self._config.list_hw_types_active():
            target = self._config.get_excel_target_for(hw)
            if target is None:
                continue
            canonica = target.get("canonical", "")
            if not canonica:
                continue
            devices = list(dispositivos_por_tipo.get(canonica, []))
            attr_name = self._config.get_app_state_attr_for(hw)
            if attr_name is None:
                continue
            # ``AppState.__setattr__`` ya sincroniza ``_dispositivos``.
            setattr(self._state, attr_name, devices)


__all__ = ["SyncDispositivosDimensionsUseCase"]
