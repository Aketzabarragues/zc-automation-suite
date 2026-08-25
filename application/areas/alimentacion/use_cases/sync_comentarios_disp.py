"""Caso de uso: aplicar comentarios por instancia en los 6 DBs de dispositivos.

Pieza del flujo post-``apply_disp`` (N_MAX) + ``compile_plc`` (redimensionado):
recibe el AppState con los dispositivos cargados desde el Excel, y para
cada DB de dispositivo (ED/EA/SA/V/M/M_VF) escribe el comentario de
cada instancia (``comentario_db``) en el Source Document correspondiente
(``.s7dcl``/``.s7res``) y reimporta el bloque a TIA Portal, todo bajo
UNA sola transacción COM con rollback atómico.

Restricciones arquitectónicas:
  - NO importa ``siemens_tia_scripting``.
  - Toda interacción con TIA Portal pasa por ``TIAProcessGateway``.
  - Cero rutas hardcodeadas: la carpeta destino, los nombres de los DBs
    y los nombres de los arrays se leen SIEMPRE del ``ConfigManager``.

Stages de progress (alineado con ``.clinerules`` §7):
  ``["read_state", "build_slot_maps", "open_transaction", "done"]``
"""
from __future__ import annotations

import logging
from typing import Any

from application.progress_buffer import ProgressTracker, get_progress_tracker
from application.state import AppState
from infrastructure.config_manager import ConfigManager
from infrastructure.gateway import TIAProcessGateway


_logger = logging.getLogger(f"{__name__}.DispComentariosSyncUseCase")


class DispComentariosSyncUseCase:
    """Caso de uso: sincroniza comentarios por instancia de los 6 DBs.

    Attributes:
        gateway:          gateway asíncrono al motor OT.
        config_manager:   configuración TIA del departamento activo.
        app_state:        estado con los dispositivos cargados del Excel.
        progress:         tracker de progreso (Singleton global si None).
    """

    def __init__(
        self,
        gateway: TIAProcessGateway,
        config_manager: ConfigManager,
        app_state: AppState,
        progress: ProgressTracker | None = None,
    ) -> None:
        self._gateway = gateway
        self._config = config_manager
        self._state = app_state
        self._progress: ProgressTracker = (
            progress if progress is not None else get_progress_tracker()
        )

    # ── API pública ──────────────────────────────────────────────────────

    async def apply_comentarios_disp(self, plc_name: str) -> dict[str, Any]:
        """Aplica los comentarios por instancia a los 6 DBs en 1 transacción TIA.

        Si ``AppState`` está vacío, NO toca TIA: warning accionable + return.
        Si la transacción falla, ``progress.finish(success=False)`` y propaga.

        Returns:
            ``dict`` con::

                {
                  "plc_name":            str,
                  "success":             True,
                  "applied":             True,
                  "operations_executed": int,
                  "summary": {
                    "disp_dbs_updated": int,
                    "total_ops":       int,
                  },
                  "details":  list[dict],   # del worker
                  "warnings": list[str],
                }
        """
        self._progress.begin(
            operation="apply_disp_comentarios",
            label=f"Aplicando comentarios en {plc_name}",
            stages=["read_state", "build_slot_maps", "open_transaction", "done"],
        )
        try:
            warnings: list[str] = self._check_app_state()
            if warnings:
                self._progress.finish(success=True)
                return {
                    "plc_name": plc_name,
                    "success": True,
                    "applied": True,
                    "operations_executed": 0,
                    "summary": {"disp_dbs_updated": 0, "total_ops": 0},
                    "details": [],
                    "warnings": warnings,
                }

            self._progress.start_stage("read_state", "Validando AppState...")
            self._progress.finish_stage("read_state", "AppState OK")

            self._progress.start_stage("build_slot_maps", "Construyendo slot_maps...")
            slot_maps, db_names, db_array_names, build_warnings = (
                self._build_all_slot_maps()
            )
            warnings.extend(build_warnings)
            self._progress.finish_stage(
                "build_slot_maps",
                f"{len(slot_maps)} tipos de dispositivo preparados",
            )

            target_folder = self._config.get_tia_folder_dispositivos()
            undo_text = f"Sync comentarios dispositivos ({plc_name})"

            # Etiqueta honesta: opaca, cubre la transacción COM (1-3 min).
            self._progress.start_stage(
                "open_transaction",
                f"Aplicando {len(slot_maps)} comentarios a TIA — puede tardar 1-3 min",
            )
            result = await self._gateway.update_disp_instance_comments_batch(
                plc_name=plc_name,
                dispositivos_slot_maps=slot_maps,
                target_folder=target_folder,
                db_names=db_names,
                db_array_names=db_array_names,
                undo_text=undo_text,
            )
            ops_executed = result.get("operations_executed", 0)
            self._progress.finish_stage(
                "open_transaction",
                f"{ops_executed} ops aplicadas OK",
            )

            self._progress.finish(success=True)
            return {
                "plc_name": plc_name,
                "success": True,
                "applied": True,
                "operations_executed": ops_executed,
                "summary": {
                    "disp_dbs_updated": ops_executed,
                    "total_ops": ops_executed,
                },
                "details": result.get("details", []),
                "warnings": warnings,
            }
        except Exception as exc:
            self._progress.finish(success=False, error=str(exc))
            raise

    async def preview_comentarios_disp(self, plc_name: str) -> dict[str, Any]:
        """Calcula el diff de comentarios SIN tocar TIA.

        Útil para que la SPA muestre "lo que se va a aplicar" antes del
        commit. No invoca el gateway (no toca TIA).
        """
        self._progress.begin(
            operation="preview_disp_comentarios",
            label=f"Generando preview comentarios para {plc_name}",
            stages=["read_state", "build_slot_maps", "done"],
        )
        try:
            warnings: list[str] = self._check_app_state()
            if warnings:
                self._progress.finish(success=True)
                return {
                    "plc_name": plc_name,
                    "success": True,
                    "has_changes": False,
                    "dispositivos_slot_maps": {},
                    "summary": {"disp_total_slots": 0, "disp_no_usar": 0},
                    "warnings": warnings,
                }

            self._progress.start_stage("read_state")
            self._progress.finish_stage("read_state")

            self._progress.start_stage("build_slot_maps")
            slot_maps, _, _, build_warnings = self._build_all_slot_maps()
            warnings.extend(build_warnings)
            self._progress.finish_stage("build_slot_maps")

            total_slots = sum(max(0, len(m) - 1) for m in slot_maps.values())
            no_usar_count = len(slot_maps)

            self._progress.finish(success=True)
            return {
                "plc_name": plc_name,
                "success": True,
                "has_changes": total_slots > 0,
                "dispositivos_slot_maps": slot_maps,
                "summary": {
                    "disp_total_slots": total_slots,
                    "disp_no_usar": no_usar_count,
                },
                "warnings": warnings,
            }
        except Exception as exc:
            self._progress.finish(success=False, error=str(exc))
            raise

    # ── Helpers privados ────────────────────────────────────────────────

    def _check_app_state(self) -> list[str]:
        """Devuelve warning si AppState no tiene dispositivos cargados.

        Política: si NO hay ningún dispositivo en ningún tipo, asumimos
        que el operario aún no cargó el Excel. NO abortamos: devolvemos
        un warning accionable y dejamos que el caller decida.
        """
        if not self._state.all_devices():
            return [
                "AppState está vacío. Cargue primero el Excel con "
                "POST /api/v1/excel/upload."
            ]
        return []

    def _build_all_slot_maps(
        self,
    ) -> tuple[dict[str, dict[int, str]], dict[str, str], dict[str, str], list[str]]:
        """Construye los slot_maps para todos los tipos activos.

        Returns:
            Tupla ``(slot_maps, db_names, db_array_names, warnings)``.
        """
        slot_maps: dict[str, dict[int, str]] = {}
        db_names: dict[str, str] = {}
        db_array_names: dict[str, str] = {}
        warnings: list[str] = []

        for hw_type in self._config.list_hw_types_active():
            cfg = self._config.get_dispositivo_config(hw_type)
            if cfg is None:
                warnings.append(
                    f"Tipo de dispositivo '{hw_type}' sin config TIA; se omite."
                )
                continue
            db_names[hw_type] = cfg.db_name
            db_array_names[hw_type] = cfg.db_array_name
            slot_maps[hw_type] = self._build_slot_map_for_hw(hw_type)
        return slot_maps, db_names, db_array_names, warnings

    def _build_slot_map_for_hw(self, hw_type: str) -> dict[int, str]:
        """Slot map para un tipo: ``{0: 'NO USAR', i: comentario_db para cada device con numero==i}``.

        El campo de la dataclass se llama ``comentario_db`` (snake_case
        en Python, columna Excel ``ComentarioDB``). Devices con
        ``numero <= 0`` o duplicados se ignoran (warning en ``preview``,
        silencioso en ``apply`` — el caller ya recibe warnings).
        """
        slot_map: dict[int, str] = {0: "NO USAR"}
        seen: set[int] = set()
        for device in self._state.get_devices(hw_type):
            numero = int(getattr(device, "numero", 0) or 0)
            if numero <= 0:
                continue
            if numero in seen:
                _logger.warning(
                    f"[{hw_type}] numero={numero} duplicado; se ignora el segundo."
                )
                continue
            seen.add(numero)
            comentario_db = str(getattr(device, "comentario_db", "") or "")
            slot_map[numero] = comentario_db
        return slot_map
