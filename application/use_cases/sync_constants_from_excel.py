"""Caso de Uso: sincronizacion desde Excel (AppState) con patron preview/apply.

Orquestador de ALTO NIVEL que combina:
  - AppState (con el Excel ya parseado).
  - TIAProcessGateway (para leer/escribir el PLC via COM).
  - ConfigManager (para resolver hw_type -> tag_table).
  - SyncConstantsUnifiedUseCase (orquestador de bajo nivel con
    metodos preview() y execute()).

Estrategia de lectura del PLC: EXPORT -> PARSE -> DIFF

Modelo **data-driven** (Plan: Base extensible para tablas de
dispositivos y N_MAX): el mapeo ``hw_type ↔ atributo AppState`` ya no
está hardcoded en este módulo; se consulta al ``ConfigManager``.
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from application.state import AppState
from application.use_cases.sync_constants_unified import SyncConstantsUnifiedUseCase
from infrastructure.config_manager import ConfigManager
from infrastructure.gateway import TIAProcessGateway
from infrastructure.xml.tag_table_parser import SimaticMLTagParser


_logger: logging.Logger = logging.getLogger(
    f"{__name__}.SyncConstantsFromExcelUseCase"
)


class SyncConstantsFromExcelUseCase:
    """Orquestador de alto nivel: Excel (AppState) <-> TIA Portal."""

    def __init__(
        self,
        gateway: TIAProcessGateway,
        config_manager: ConfigManager,
        app_state: AppState,
    ) -> None:
        self._gateway = gateway
        self._config = config_manager
        self._state = app_state
        self._sync_unified = SyncConstantsUnifiedUseCase(
            gateway=gateway, config_manager=config_manager
        )

    # --- API publica ---

    async def preview(self, plc_name: str) -> dict[str, Any]:
        """Calcula el diff entre el Excel (AppState) y el PLC. NO toca TIA.

        Short-circuit: si ``AppState`` está vacío (no se cargó el Excel
        o no se encontraron dispositivos/dimensiones), NO se invoca a
        TIA Portal. Se devuelve un preview con ``has_changes=False`` y
        un warning accionable. Esto evita lecturas inútiles del PLC y
        resultados engañosos (comparar el estado real del PLC contra
        un desired vacío siempre produciría un diff con todos los
        N_MAX a 0 y todas las tablas de dispositivos como ``rename``).
        """
        warnings = self._check_app_state()
        if warnings:
            _logger.warning(
                f"[{plc_name}] AppState vacío: preflight sin tocar TIA. "
                f"{warnings[0]}"
            )
            return {
                "success": True,
                "preview": True,
                "warnings": warnings,
                "has_app_state": False,
                "nmax_ops": [],
                "rename_ops": [],
                "device_diffs": {},
                "summary": {
                    "n_max_updates": 0,
                    "device_renames": 0,
                    "total_ops": 0,
                    "has_changes": False,
                },
            }
        try:
            states = await self._read_plc_states(plc_name)
        except Exception as e:
            _logger.error(f"Error leyendo estado del PLC '{plc_name}': {e}")
            raise
        nmax_desired = self._build_nmax_desired_from_appstate()
        device_states_by_type = self._build_device_states_from_appstate(
            states.get("device_current", {})
        )
        result = await self._sync_unified.preview(
            plc_name=plc_name,
            nmax_current_state=states["nmax_current"],
            nmax_desired_state=nmax_desired,
            device_states_by_type=device_states_by_type,
        )
        result.update({
            "success": True,
            "preview": True,
            "warnings": warnings,
            "has_app_state": not warnings,
        })
        return result

    async def execute(self, plc_name: str) -> dict[str, Any]:
        """Calcula el diff Y aplica la transaccion COM unificada."""
        warnings = self._check_app_state()
        states = await self._read_plc_states(plc_name)
        nmax_desired = self._build_nmax_desired_from_appstate()
        device_states_by_type = self._build_device_states_from_appstate(
            states.get("device_current", {})
        )
        result = await self._sync_unified.execute(
            plc_name=plc_name,
            nmax_current_state=states["nmax_current"],
            nmax_desired_state=nmax_desired,
            device_states_by_type=device_states_by_type,
        )
        result.update({
            "applied": True,
            "warnings": warnings,
        })
        return result

    # --- Helpers privados ---

    def _check_app_state(self) -> list[str]:
        warnings: list[str] = []
        d = self._state.dimensiones
        # ``DimensionesDispositivos`` es un dataclass frozen; su
        # ``__bool__`` por defecto es siempre True, por lo que
        # ``not d`` nunca se cumple. Comprobamos explícitamente
        # que todos los N_MAX del catálogo estén a 0 (estado recién
        # inicializado). ``ConfigManager.list_nmax_active()`` siempre
        # devuelve al menos los 6 legacy (fallback defensivo) incluso
        # si el JSON no incluye ``n_max_catalog``.
        nmax_names = self._config.list_nmax_active()
        dimensiones_empty = all(
            int(d.get(n) or 0) == 0 for n in nmax_names
        )
        if not self._state.all_devices() and dimensiones_empty:
            warnings.append(
                "AppState está vacío. Cargue primero el Excel con "
                "'tia_sync_dispositivos_dimensions_from_excel'."
            )
        return warnings

    async def _read_plc_states(self, plc_name: str) -> dict[str, Any]:
        """Lee el estado actual del PLC via export bulk + parse selectivo.

        Estrategia (FIX preflight / comparativa):
          1. UN solo export bulk vía ``export_plc_tags_xml``: el árbol
             completo del PLC con la jerarquía de carpetas preservada
             (``000_Sistema/``, ``2000_Dispositivos/``, ``003_Procesos/``…).
          2. Se localizan los **únicos 7 XMLs** que importan al sync
             unificado (1 N_MAX + 6 dispositivos) según la config:
               - ``{nmax_folder}/{nmax_table}.xml`` para N_MAX.
               - ``{dispositivos_folder}/{tag_table}.xml`` por cada
                 ``hw_type`` configurado.
          3. Se parsean solo esos 7 con ``SimaticMLTagParser``. El
             resto del árbol (``Tabla de variables estándar.xml``,
             ``003_Procesos/*``, ``2000_Disp_SD``, etc.) se ignora.
          4. Si un XML esperado no está en el árbol (p. ej. la
             carpeta ``2000_Dispositivos`` está vacía), se loggea un
             warning y se continúa con ``{}`` para esa tabla. La
             preflight **no** aborta.
        """
        # 1. Resolver paths de los 7 XMLs a leer.
        nmax_folder = self._config.get_tia_folder_nmax()        # "000_Sistema"
        dev_folder = self._config.get_tia_folder_dispositivos()  # "2000_Dispositivos"
        nmax_table = self._config.get_global_config_table_name()  # "000_Config_Dispositivos"

        # 2. Carpeta temporal para los XML exportados.
        temp_dir = Path(
            tempfile.mkdtemp(prefix=f"zc_sync_{plc_name}_")
        )
        _logger.info(
            f"[{plc_name}] Creando carpeta temporal para export: {temp_dir}"
        )
        try:
            # 3. UN solo export bulk con jerarquía preservada.
            try:
                await self._gateway.export_plc_tags_xml(
                    plc_name=plc_name,
                    target_dir=str(temp_dir),
                )
                _logger.debug(
                    f"[{plc_name}] Export bulk OK -> {temp_dir}"
                )
            except Exception as e:
                _logger.error(
                    f"[{plc_name}] Export bulk FAIL: {e}"
                )
                # Si el export falla, devolvemos estados vacíos para
                # no abortar la preflight: la SPA/MCP verá "0 ops"
                # en lugar de un 500.
                return {"nmax_current": {}, "device_current": {}}

            # 4. Lista de XMLs a parsear (N_MAX + 6 dispositivos).
            wanted: list[tuple[str, Path]] = [
                ("nmax", temp_dir / nmax_folder / f"{nmax_table}.xml"),
            ]
            for hw_type in self._config.list_hw_types():
                tag_table = self._config.get_tag_table_name(hw_type)
                if tag_table is None:
                    continue
                wanted.append(
                    (hw_type, temp_dir / dev_folder / f"{tag_table}.xml")
                )
            _logger.info(
                f"[{plc_name}] XMLs objetivo ({len(wanted)}): "
                f"{[str(p) for _, p in wanted]}"
            )

            # 5. Parsear SOLO los 7 XMLs.
            nmax_current: dict[str, int] = {}
            device_current: dict[str, dict[str, str]] = {}

            for kind, xml_path in wanted:
                if not xml_path.is_file():
                    _logger.warning(
                        f"[{plc_name}] XML esperado NO encontrado: {xml_path}"
                    )
                    if kind == "nmax":
                        nmax_current = {}
                    continue
                try:
                    parsed = SimaticMLTagParser.parse_user_constants(xml_path)
                    _logger.info(
                        f"[{plc_name}] Parseado {xml_path.name} ({kind}): "
                        f"{len(parsed)} constantes -> {parsed}"
                    )
                except Exception as e:
                    _logger.error(
                        f"[{plc_name}] Parse FAIL: {xml_path}: {e}"
                    )
                    parsed = {}
                if kind == "nmax":
                    nmax_current = parsed
                else:
                    device_current[kind] = parsed

            _logger.info(
                f"[{plc_name}] Resumen parseo: nmax={len(nmax_current)}, "
                f"devices={ {k: len(v) for k, v in device_current.items()} }"
            )

            return {
                "nmax_current": nmax_current,
                "device_current": device_current,
            }
        finally:
            # 6. Limpiar carpeta temporal siempre.
            shutil.rmtree(temp_dir, ignore_errors=True)
            _logger.debug(f"[{plc_name}] Carpeta temporal limpiada.")

    def _build_nmax_desired_from_appstate(self) -> dict[str, int]:
        """Construye el desired_state de N_MAX desde AppState.dimensiones.

        Itera ``ConfigManager.list_nmax_active()`` (data-driven) y, para
        cada nombre, lee el valor del wrapper. Los 6 legacy funcionan
        idéntico (``d.get("N_MAX_DISP_ED")`` resuelve a la propiedad
        ``num_disp_ed``).
        """
        d = self._state.dimensiones
        desired: dict[str, int] = {}
        for nmax_name in self._config.list_nmax_active():
            v = d.get(nmax_name)
            if v is None:
                v = 0
            desired[nmax_name] = int(v)
        return desired

    def _build_device_states_from_appstate(
        self,
        device_current: dict[str, dict[str, str]],
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """Construye device_states_by_type desde AppState.

        FIX CLAVE: usa ``device.numero`` (slot real del dispositivo en el PLC)
        como VALOR de la constante, NO el indice de la lista.

        Razon: el PLC exporta ``<Value>{numero}</Value>`` en cada
        PlcUserConstant. Si idx+1 != numero, el diff falla.

        Itera ``ConfigManager.list_hw_types_active()`` (data-driven);
        los 6 legacy funcionan idéntico porque el config usa la
        convención ``dispositivos_<hw>``.
        """
        states_by_type: dict[str, dict[str, dict[str, Any]]] = {}
        for hw_type in self._config.list_hw_types_active():
            attr_name = self._config.get_app_state_attr_for(hw_type)
            if attr_name is None:
                continue
            devices = getattr(self._state, attr_name, [])
            if not devices:
                continue
            desired: dict[str, int] = {}
            for device in devices:
                # FIX: usar numero (slot real en PLC), NO idx+1.
                plc_tag = str(getattr(device, "plc_tag", "") or "")
                uid = str(getattr(device, "uid", "") or "")
                numero = int(getattr(device, "numero", 0) or 0)
                # Si numero es 0 o invalido, fallback a uid como texto
                # (no se puede buscar por VALOR en este caso).
                if numero <= 0:
                    if uid and uid.isdigit():
                        numero = int(uid)
                desired_name = plc_tag or uid
                if desired_name and numero > 0:
                    desired[desired_name] = numero
            if desired:
                current = device_current.get(hw_type, {})
                states_by_type[hw_type] = {
                    "current": current,
                    "desired": desired,
                }
                _logger.info(
                    f"[device.{hw_type}] desired ({len(desired)}): "
                    f"{ {k: v for k, v in list(desired.items())[:3]} }..."
                )
                _logger.info(
                    f"[device.{hw_type}] current ({len(current)}): "
                    f"{ {k: v for k, v in list(current.items())[:3]} }..."
                )
        return states_by_type


__all__ = ["SyncConstantsFromExcelUseCase"]
