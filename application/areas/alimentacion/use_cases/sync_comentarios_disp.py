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

from application.areas.alimentacion.slot_map_builder import build_slot_maps
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
        """Aplica los comentarios por instancia a los 6 DBs de dispositivos
        en UNA sola transacción TIA con rollback atómico.

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
            result = await self._run_apply(plc_name)
            self._progress.finish(success=True)
            return result
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
            slot_maps, _, _, build_warnings = build_slot_maps(
                self._state, self._config
            )
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

    # ── Internals ────────────────────────────────────────────────────────

    async def _run_apply(self, plc_name: str) -> dict[str, Any]:
        """Lógica de apply: check + build + batch transaccional. Emite progress."""
        self._progress.start_stage("read_state", "Validando AppState...")
        warnings: list[str] = self._check_app_state()
        if warnings:
            self._progress.finish_stage("read_state")
            self._progress.finish_stage("build_slot_maps")
            self._progress.finish_stage("open_transaction", "Sin cambios (no-op)")
            self._progress.finish_stage("done", "Saltado (AppState vacio)")
            return {
                "plc_name": plc_name,
                "success": True,
                "applied": True,
                "operations_executed": 0,
                "summary": {"disp_dbs_updated": 0, "total_ops": 0},
                "details": [],
                "warnings": warnings,
            }
        self._progress.finish_stage("read_state", "AppState OK")

        self._progress.start_stage("build_slot_maps", "Construyendo slot_maps...")
        slot_maps, db_names, db_array_names, build_warnings = build_slot_maps(
            self._state, self._config
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
        self._progress.finish_stage("done", f"{ops_executed} ops")

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

    def _check_app_state(self) -> list[str]:
        """Devuelve warning si AppState no tiene dispositivos cargados.

        Política: si NO hay ningún dispositivo en ningún tipo, asumimos
        que el operario aún no cargó el Excel. NO abortamos: devolvemos
        un warning accionable y dejamos que el caller decida qué hacer.
        """
        if not self._state.all_devices():
            return [
                "AppState está vacío. Cargue primero el Excel con "
                "POST /api/v1/excel/upload."
            ]
        return []
