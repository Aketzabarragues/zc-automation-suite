"""Caso de uso: sincronizar comentarios por slot de los DBs de procesos.

Pieza del flujo "procesos" análoga a ``DispComentariosSyncUseCase``
(dispositivos). Selecciona un proceso, genera el diff entre el
Excel y los DBs de TIA (PReal[] + PInt[] + ALM[]), lo muestra en
preview, y al confirmar lo aplica en **UNA sola transacción COM**
con rollback atómico vía ``gateway.execute_transactional_batch``.

Restricciones arquitectónicas:
  - NO importa ``siemens_tia_scripting``.
  - Toda interacción con TIA Portal pasa por ``TIAProcessGateway``.
  - Cero rutas hardcodeadas: la carpeta destino se lee SIEMPRE del
    ``ConfigManager.get_tia_folder_proceso()``.

Stages de progress (alineado con ``.clinerules`` §7):
  - ``generar_prevision``: ``["check_state", "check_blocks",
     "build_slot_maps", "done"]``.
  - ``ejecutar_transaccion``: ``["check_state", "check_blocks",
     "build_slot_maps", "open_transaction", "done"]``.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from areas.alimentacion.application.proc_slot_map_builder import (
    ProcesoSlotMap,
    build_proceso_slot_maps,
)
from core.application.progress_buffer import ProgressTracker, get_progress_tracker
from core.application.state import AppState
from core.infrastructure.config_manager import ConfigManager
from core.infrastructure.gateway import TIAProcessGateway
from core.models.bloque_cache import BloqueCache


_logger = logging.getLogger(f"{__name__}.SyncProcesosComentariosUseCase")


class SyncProcesosComentariosUseCase:
    """Caso de uso: sincronizar comentarios de los 3 arrays de un proceso.

    Attributes:
        gateway: gateway asíncrono al motor OT.
        config_manager: configuración TIA del departamento activo.
        app_state: estado con los procesos / parámetros / alarmas
                   del Excel.
        progress: tracker de progreso (Singleton global si None).
        bloques_cache: cache de bloques del PLC activo. Si es None,
                       el caso de uso asume que la cache está vacía
                       y devuelve ``missing_blocks`` poblado para
                       los 3 nombres esperados.
        build_cache_dir: directorio base del work_dir del worker OT
                       (default: ``<cwd>/.build_cache``). Permite a
                       los tests inyectar ``tmp_path`` directamente
                       en lugar de monkey-patching ``_build_work_dir``.
    """

    _BUILD_CACHE_DIRNAME = ".build_cache"
    _PROC_SUBDIR = "procesos"
    _COMMIT_SUBDIR = "commit"
    _PREVIEW_SUBDIR = "preview"

    def __init__(
        self,
        gateway: TIAProcessGateway,
        config_manager: ConfigManager,
        app_state: AppState,
        progress: ProgressTracker | None = None,
        bloques_cache: BloqueCache | None = None,
        build_cache_dir: Path | None = None,
    ) -> None:
        self._gateway = gateway
        self._config = config_manager
        self._state = app_state
        self._progress: ProgressTracker = (
            progress if progress is not None else get_progress_tracker()
        )
        self._bloques_cache: BloqueCache | None = bloques_cache
        self._build_cache: Path = (
            build_cache_dir
            if build_cache_dir is not None
            else Path(os.getcwd()) / self._BUILD_CACHE_DIRNAME
        )

    # ── API pública ──────────────────────────────────────────────────────

    async def generar_prevision(self, proc_uid: int) -> dict[str, Any]:
        """Calcula el diff de comentarios SIN tocar TIA.

        Stages: ``["check_state", "check_blocks", "build_slot_maps", "done"]``.

        Returns:
            ``dict`` con el shape::

                {
                  "proc_uid":           int,
                  "proc_codigo":        str,
                  "proc_nombre":        str,
                  "precondiciones_ok":  bool,
                  "missing_blocks":     list[str],
                  "arrays": {
                    "PReal": {...},
                    "PInt":  {...},
                    "ALM":   {...},
                  },
                  "summary": {
                    "total_ops":  int,
                    "to_update":  int,
                    "to_insert":  int,
                    "to_prune":   int,
                  },
                  "warnings": list[str],
                }
        """
        self._progress.begin(
            operation="preview_procesos_comentarios",
            label=f"Generando preview comentarios proceso {proc_uid}",
            stages=[
                "check_state", "check_blocks", "build_slot_maps",
                "export_and_diff", "done",
            ],
        )
        try:
            # check_state: validar que excel_cache no esté vacío.
            self._progress.start_stage("check_state", "Validando AppState...")
            if self._state.excel_cache is None:
                self._progress.finish_stage("check_state", "Excel no cargado")
                self._progress.finish_stage("check_blocks")
                self._progress.finish_stage("build_slot_maps")
                self._progress.start_stage("done", "Sin Excel cargado")
                self._progress.finish_stage("done", "Sin Excel cargado")
                return {
                    "proc_uid": proc_uid,
                    "precondiciones_ok": False,
                    "missing_blocks": [
                        "AppState no tiene Excel cargado. Cargue el Excel con "
                        "POST /api/v1/excel/upload."
                    ],
                    "arrays": {},
                    "summary": {"total_ops": 0, "to_update": 0,
                                "to_insert": 0, "to_prune": 0},
                    "warnings": [],
                }
            self._progress.finish_stage("check_state", "AppState OK")

            # check_blocks: cache de bloques del PLC.
            # Distinguimos 2 casos de "sin cache":
            #   1. ``bloques_cache is None`` → el PLC nunca ha sido
            #      escaneado. El operario debe ir al sidebar y
            #      esperar al escaneo. NO fingimos que los 3 bloques
            #      están missing (eso es engañoso).
            #   2. ``bloques_cache`` existe pero está vacío → el PLC
            #      fue escaneado pero el proyecto no tiene bloques.
            #      Esto es un estado válido pero improbable; lo
            #      tratamos como missing_blocks.
            self._progress.start_stage("check_blocks", "Verificando bloques TIA...")
            if self._bloques_cache is None:
                self._progress.finish_stage(
                    "check_blocks", "Cache de bloques no disponible"
                )
                self._progress.start_stage("done", "Sin cache de bloques")
                self._progress.finish_stage("done", "Sin cache de bloques")
                return {
                    "proc_uid": proc_uid,
                    "precondiciones_ok": False,
                    "missing_blocks": [
                        "Cache de bloques del PLC no disponible. "
                        "Selecciona el PLC en el sidebar y espera al "
                        "escaneo de bloques (1-3 min en PLCs grandes)."
                    ],
                    "arrays": {},
                    "summary": {"total_ops": 0, "to_update": 0,
                                "to_insert": 0, "to_prune": 0},
                    "warnings": [],
                }
            bloques = self._bloques_cache
            self._progress.finish_stage(
                "check_blocks",
                f"{len(bloques.blocks)} bloques, {len(bloques.tag_tables)} tablas"
            )

            # build_slot_maps: cruzar Excel + BloqueCache.
            self._progress.start_stage("build_slot_maps", "Cruzando Excel ↔ bloques...")
            try:
                slot_map = build_proceso_slot_maps(
                    self._state, self._config, proc_uid, bloques
                )
            except RuntimeError as exc:
                self._progress.finish_stage("build_slot_maps", f"Error: {exc}")
                self._progress.start_stage("done", "Abortado")
                self._progress.finish_stage("done", "Abortado")
                return {
                    "proc_uid": proc_uid,
                    "precondiciones_ok": False,
                    "missing_blocks": [str(exc)],
                    "arrays": {},
                    "summary": {"total_ops": 0, "to_update": 0,
                                "to_insert": 0, "to_prune": 0},
                    "warnings": [],
                }
            self._progress.finish_stage(
                "build_slot_maps",
                f"PReal={len(slot_map.preal)} PInt={len(slot_map.pint)} "
                f"ALM={len(slot_map.alm)}",
            )

            # done: precondiciones ok?
            if slot_map.missing_blocks:
                self._progress.start_stage(
                    "done",
                    f"Faltan {len(slot_map.missing_blocks)} bloques",
                )
                self._progress.finish_stage(
                    "done",
                    f"Faltan {len(slot_map.missing_blocks)} bloques",
                )
                return {
                    "proc_uid": proc_uid,
                    "proc_codigo": slot_map.db_param_name.split("_")[1]
                                   if "_" in slot_map.db_param_name else "",
                    "precondiciones_ok": False,
                    "missing_blocks": slot_map.missing_blocks,
                    "db_param_name": slot_map.db_param_name,
                    "db_alm_name": slot_map.db_alm_name,
                    "table_name": slot_map.table_name,
                    "arrays": {},
                    "summary": {"total_ops": 0, "to_update": 0,
                                "to_insert": 0, "to_prune": 0},
                    "warnings": slot_map.warnings,
                }

            # Precondiciones OK: exportar los 3 DBs y comparar con
            # el Excel para producir un diff real. Sin este stage
            # el "total_ops" sería fake (= nº de slots del Excel),
            # no el nº de cambios que se aplicarían. Con este
            # stage:
            #   - exportamos DB_PARAM y DB_ALM (1-3 min en PLCs
            #     grandes) a un work_dir.
            #   - leemos los .s7res resultantes y extraemos el
            #     ``es-ES`` actual de cada slot (solo del array
            #     principal, no de los satélites).
            #   - comparamos desired (Excel) con current (TIA) por
            #     slot. action ∈ {equal, update, new}.
            self._progress.start_stage(
                "export_and_diff",
                "Exportando 3 DBs y comparando con Excel...",
            )
            try:
                current_preal, current_pint, current_alm = (
                    await self._export_and_read_current(slot_map)
                )
            except Exception as exc:
                # Si el export falla (TIA no responde, permisos,
                # etc.), NO abortamos el preview: devolvemos un diff
                # con ``current=None`` para todos los slots y un
                # warning. El operario ve que algo falló en el
                # backend pero el preview sigue siendo útil (al
                # menos sabe qué slots quiere actualizar).
                _logger.warning(
                    f"export_and_diff falló: {exc}. Devolviendo "
                    f"current=None para todos los slots."
                )
                self._progress.finish_stage(
                    "export_and_diff",
                    f"Error exportando: {exc}",
                )
                current_preal = current_pint = current_alm = None
                self._progress.start_stage(
                    "done",
                    f"Preview con current=None (export falló)",
                )
                self._progress.finish_stage(
                    "done",
                    f"Preview con current=None (export falló)",
                )
                return self._compose_response(
                    proc_uid, slot_map,
                    preal_current=None, pint_current=None, alm_current=None,
                    extra_warnings=[f"Export falló: {exc}. current=None."],
                )

            arrays = self._compose_arrays(
                slot_map, current_preal, current_pint, current_alm
            )
            summary = self._compute_summary(arrays)
            self._progress.finish_stage(
                "export_and_diff",
                f"{summary['to_update']} updates, "
                f"{summary['to_insert']} nuevos, "
                f"{summary['total_ops'] - summary['to_update'] - summary['to_insert']} iguales",
            )

            self._progress.start_stage(
                "done",
                f"{summary['total_ops']} slots, "
                f"{summary['to_update']} updates, "
                f"{summary['to_insert']} nuevos",
            )
            self._progress.finish_stage(
                "done",
                f"{summary['total_ops']} slots, "
                f"{summary['to_update']} updates, "
                f"{summary['to_insert']} nuevos",
            )
            return self._compose_response(
                proc_uid, slot_map,
                preal_current=current_preal,
                pint_current=current_pint,
                alm_current=current_alm,
            )
        except Exception as exc:
            self._progress.finish(success=False, error=str(exc))
            raise

    async def ejecutar_transaccion(
        self, proc_uid: int, prevision: dict[str, Any]
    ) -> dict[str, Any]:
        """Aplica el diff en UNA transacción TIA atómica.

        Stages: ``["check_state", "check_blocks", "build_slot_maps",
        "open_transaction", "done"]``.

        El lote se ejecuta con ``gateway.execute_transactional_batch``
        (3 sub-ops: PReal + PInt + ALM). El worker abre
        ``start_transaction``, itera los sub-comandos, y cierra con
        ``end_transaction``. Si cualquiera falla, rollback atómico.

        Política: el diff se **recalcula desde el AppState** (no se
        usa la ``prevision`` del body) para evitar race conditions
        con cambios de Excel entre el preview y el commit.
        """
        self._progress.begin(
            operation="commit_procesos_comentarios",
            label=f"Aplicando comentarios proceso {proc_uid}",
            stages=[
                "check_state", "check_blocks", "build_slot_maps",
                "open_transaction", "done",
            ],
        )
        try:
            # check_state.
            self._progress.start_stage("check_state", "Validando AppState...")
            if self._state.excel_cache is None:
                self._progress.finish_stage("check_state", "Excel no cargado")
                raise RuntimeError(
                    "AppState.excel_cache está vacío. Cargue el Excel con "
                    "POST /api/v1/excel/upload."
                )
            self._progress.finish_stage("check_state", "AppState OK")

            # check_blocks.
            self._progress.start_stage("check_blocks", "Verificando bloques TIA...")
            if self._bloques_cache is None:
                self._progress.finish_stage(
                    "check_blocks", "Cache de bloques no disponible"
                )
                raise RuntimeError(
                    "Cache de bloques del PLC no disponible. "
                    "Selecciona el PLC en el sidebar y espera al "
                    "escaneo de bloques (1-3 min en PLCs grandes)."
                )
            bloques = self._bloques_cache
            self._progress.finish_stage(
                "check_blocks",
                f"{len(bloques.blocks)} bloques, {len(bloques.tag_tables)} tablas"
            )

            # build_slot_maps: recalcular desde AppState (NO usar prevision).
            self._progress.start_stage("build_slot_maps", "Recalculando diff...")
            slot_map = build_proceso_slot_maps(
                self._state, self._config, proc_uid, bloques
            )
            if slot_map.missing_blocks:
                raise RuntimeError(
                    f"Faltan bloques en el PLC: {slot_map.missing_blocks}"
                )
            self._progress.finish_stage(
                "build_slot_maps",
                f"PReal={len(slot_map.preal)} PInt={len(slot_map.pint)} "
                f"ALM={len(slot_map.alm)}",
            )

            # Necesitamos el plc_name. En el flujo, viene del front
            # en la prevision dict (lo emite el preview del
            # cliente). Si no, usamos "" y dejamos que el gateway
            # decida (en la práctica esto NO debería pasar).
            plc_name = prevision.get("plc_name", "") or ""
            if not plc_name:
                raise RuntimeError(
                    "plc_name es obligatorio para ejecutar_transaccion."
                )

            # open_transaction: componer las 3 ops y enviar al gateway.
            work_dir = self._build_work_dir()
            target_folder = self._config.get_tia_folder_proceso()
            undo_text = (
                f"Sync comentarios proceso {slot_map.db_param_name.split('_')[1] if '_' in slot_map.db_param_name else proc_uid} "
                f"({plc_name})"
            )

            operations: list[dict[str, Any]] = [
                {
                    "command": "update_proc_comments_db_preal",
                    "args": {
                        "plc_name": plc_name,
                        "db_name": slot_map.db_param_name,
                        "array_name": "PReal",
                        "slot_map": {str(k): v for k, v in slot_map.preal.items()},
                        "work_dir": str(work_dir),
                        "target_folder": target_folder,
                    },
                },
                {
                    "command": "update_proc_comments_db_pint",
                    "args": {
                        "plc_name": plc_name,
                        "db_name": slot_map.db_param_name,
                        "array_name": "PInt",
                        "slot_map": {str(k): v for k, v in slot_map.pint.items()},
                        "work_dir": str(work_dir),
                        "target_folder": target_folder,
                    },
                },
                {
                    "command": "update_proc_comments_db_alm",
                    "args": {
                        "plc_name": plc_name,
                        "db_name": slot_map.db_alm_name,
                        "array_name": "ALM",
                        "slot_map": {str(k): v for k, v in slot_map.alm.items()},
                        "work_dir": str(work_dir),
                        "target_folder": target_folder,
                    },
                },
            ]

            self._progress.start_stage(
                "open_transaction",
                "Aplicando 3 comentarios a TIA — puede tardar 1-3 min",
            )
            result = await self._gateway.execute_transactional_batch(
                operations=operations,
                undo_text=undo_text,
            )
            ops_executed = result.get("operations_executed", 0)
            self._progress.finish_stage(
                "open_transaction",
                f"{ops_executed} ops aplicadas OK",
            )
            self._progress.start_stage("done", f"{ops_executed} ops")
            self._progress.finish_stage("done", f"{ops_executed} ops")

            return {
                "proc_uid": proc_uid,
                "plc_name": plc_name,
                "success": True,
                "applied": True,
                "operations_executed": ops_executed,
                "details": result.get("details", []),
                "warnings": slot_map.warnings,
            }
        except Exception as exc:
            self._progress.finish(success=False, error=str(exc))
            raise

    # ── Internals ────────────────────────────────────────────────────────

    def _build_work_dir(self, suffix: str = "commit") -> Path:
        """Construye el directorio de trabajo del worker.

        Patrón análogo a ``SyncDispositivosInstancesUseCase``:
        ``<build_cache>/procesos/<suffix>/``. El directorio se
        conserva tras la operación para permitir inspección manual
        y ``git diff``.

        Args:
            suffix: ``"commit"`` (default) usa el directorio
                ``procesos/commit/`` que el handler de import_block
                lee después del export + updater. ``"preview"`` usa
                ``procesos/preview/`` separado para que el operario
                pueda inspeccionar los exports del preview sin
                mezclarlos con los del apply.
        """
        subdir = (
            self._COMMIT_SUBDIR if suffix == "commit"
            else self._PREVIEW_SUBDIR if suffix == "preview"
            else suffix
        )
        work_dir = self._build_cache / self._PROC_SUBDIR / subdir
        work_dir.mkdir(parents=True, exist_ok=True)
        return work_dir

    def _compose_arrays(
        self,
        slot_map: ProcesoSlotMap,
        preal_current: "dict[int, str | None] | None" = None,
        pint_current: "dict[int, str | None] | None" = None,
        alm_current: "dict[int, str | None] | None" = None,
    ) -> dict[str, Any]:
        """Compone el dict ``arrays`` con los 3 arrays del proceso.

        Para cada slot, generamos una entrada ``{current, desired,
        action}`` con ``action ∈ {"equal", "update", "new"}``.

        - Si se pasan los mapas ``preal_current`` / ``pint_current``
          / ``alm_current`` (devueltos por
          ``ProcesoCommentUpdater.read_current_comments``), el
          ``current`` es el ``es-ES`` real de TIA y ``action`` se
          computa como:
            - ``"new"`` si el slot no existe en TIA o ``current is None``
              (esto último es raro, indica que el MLC no se encontró
              en el ``.s7res``; lo tratamos como "nuevo" para que
              el apply lo cree).
            - ``"update"`` si ``current != desired``.
            - ``"equal"`` si ``current == desired``.
        - Si los mapas son ``None`` (preview rápido sin export, o
          export falló), ``current`` se emite como ``None`` y
          ``action`` se infiere del desired:
            - ``"new"`` si ``desired == "."`` (convención TIA "sin
              comentario" → sería un slot vacío).
            - ``"update"`` en otro caso.

        La SPA muestra el diff con colores por acción (igual =
        gris, actualizar = ámbar, nuevo = verde).
        """
        arrays: dict[str, Any] = {}
        for arr_name, slot_map_dict, db_name, satellites, current_dict in (
            ("PReal", slot_map.preal, slot_map.db_param_name,
             ["PReal_Vis", "Aux.PReal_ValorAnterior"], preal_current),
            ("PInt",  slot_map.pint,  slot_map.db_param_name,
             ["PInt_Vis",  "Aux.PInt_ValorAnterior"], pint_current),
            ("ALM",   slot_map.alm,   slot_map.db_alm_name,
             [], alm_current),
        ):
            slot_map_serialized: dict[str, Any] = {}
            for slot, desired in slot_map_dict.items():
                if current_dict is not None:
                    # Diff real: comparamos desired vs current.
                    current = current_dict.get(slot)
                    if current is None:
                        # Slot no existe en TIA o MLC no encontrado.
                        # El apply lo creará (insert).
                        action = "new"
                    elif current == desired:
                        action = "equal"
                    else:
                        action = "update"
                else:
                    # Sin export: precondiciones OK pero sin datos
                    # de TIA. Asumimos update/new según desired.
                    current = None
                    action = "new" if desired == "." else "update"
                slot_map_serialized[str(slot)] = {
                    "current": current,
                    "desired": desired,
                    "action": action,
                }
            arrays[arr_name] = {
                "db_name": db_name,
                "array_name": arr_name,
                "satellite_arrays": satellites,
                "current_count": len(slot_map_dict),
                "desired_count": len(slot_map_dict),
                "slot_map": slot_map_serialized,
            }
        return arrays

    def _compute_summary(self, arrays: dict[str, Any]) -> dict[str, int]:
        """Suma el total de slots y cuenta por tipo de acción."""
        total = 0
        to_update = 0
        to_insert = 0
        to_prune = 0
        to_equal = 0
        for arr in arrays.values():
            for entry in arr.get("slot_map", {}).values():
                total += 1
                action = entry.get("action")
                if action == "update":
                    to_update += 1
                elif action == "new":
                    to_insert += 1
                elif action == "prune":
                    to_prune += 1
                elif action == "equal":
                    to_equal += 1
        return {
            "total_ops": total,
            "to_update": to_update,
            "to_insert": to_insert,
            "to_prune": to_prune,
            "to_equal": to_equal,
        }

    def _compose_response(
        self,
        proc_uid: int,
        slot_map: ProcesoSlotMap,
        preal_current: "dict[int, str | None] | None" = None,
        pint_current: "dict[int, str | None] | None" = None,
        alm_current: "dict[int, str | None] | None" = None,
        extra_warnings: "list[str] | None" = None,
    ) -> dict[str, Any]:
        """Compone la respuesta del preview con el diff y los nombres
        TIA resueltos. Usado por la rama de éxito y la de error
        del export (donde ``current`` puede ser ``None``)."""
        arrays = self._compose_arrays(
            slot_map, preal_current, pint_current, alm_current
        )
        summary = self._compute_summary(arrays)
        warnings = list(slot_map.warnings)
        if extra_warnings:
            warnings.extend(extra_warnings)
        return {
            "proc_uid": proc_uid,
            "proc_codigo": _extract_codigo(slot_map.db_param_name),
            "precondiciones_ok": True,
            "missing_blocks": [],
            "db_param_name": slot_map.db_param_name,
            "db_alm_name": slot_map.db_alm_name,
            "table_name": slot_map.table_name,
            "arrays": arrays,
            "summary": summary,
            "warnings": warnings,
        }

    async def _export_and_read_current(
        self, slot_map: ProcesoSlotMap
    ) -> "tuple[dict[int, str | None], dict[int, str | None], dict[int, str | None]]":
        """Exporta los 2 DBs del proceso a un work_dir temporal y
        lee los ``es-ES`` actuales de cada slot de los 3 arrays
        principales (PReal, PInt, ALM).

        Stages internos:
          1. Exporta ``DB_PARAM`` y ``DB_ALM`` a
             ``<build_cache>/procesos_preview/``. Esto puede
             tardar 1-3 min en PLCs grandes.
          2. Crea un ``ProcesoCommentUpdater`` por DB (sin
             ``slot_map``, solo para usar ``read_current_comments``)
             y consulta el ``es-ES`` actual de cada slot.
          3. Devuelve los 3 mapas ``{slot: current_text | None}``.

        Raises:
            Exception: cualquier fallo del export se propaga al
            caller, que decide si abortar el preview o devolver
            un diff con ``current=None``.
        """
        from areas.alimentacion.infrastructure.sd.proc_comment_updater import (
            ProcesoCommentUpdater,
        )
        # Work_dir separado del del commit: el preview es
        # idempotente (no modifica nada en TIA), así que reutilizar
        # el mismo dir que el commit podría confundir al operario
        # que abra los archivos después.
        work_dir = self._build_work_dir(suffix="preview")
        plc_name = (
            self._bloques_cache.plc_name
            if self._bloques_cache is not None
            else ""
        )
        if not plc_name:
            raise RuntimeError(
                "BloqueCache sin plc_name; no se puede exportar."
            )

        # 1. Exportar los 2 DBs (en paralelo sería ideal pero
        # ``export_block`` no es thread-safe a nivel del wrapper .NET;
        # los hacemos secuenciales).
        await self._gateway.export_block(
            plc_name=plc_name,
            block_name=slot_map.db_param_name,
            target_dir=str(work_dir),
        )
        await self._gateway.export_block(
            plc_name=plc_name,
            block_name=slot_map.db_alm_name,
            target_dir=str(work_dir),
        )

        # 2. Leer los comentarios actuales de cada array. Creamos 2
        # updaters en modo solo-lectura (sin slot_map y sin array_name
        # de instancia, porque cada read_current_comments recibe su
        # propio array_name por parámetro).
        updater_param = ProcesoCommentUpdater(
            s7dcl_path=work_dir / f"{slot_map.db_param_name}.s7dcl",
            s7res_path=work_dir / f"{slot_map.db_param_name}.s7res",
            slot_map={},
        )
        updater_alm = ProcesoCommentUpdater(
            s7dcl_path=work_dir / f"{slot_map.db_alm_name}.s7dcl",
            s7res_path=work_dir / f"{slot_map.db_alm_name}.s7res",
            slot_map={},
        )
        current_preal = updater_param.read_current_comments(
            list(slot_map.preal.keys()), "PReal"
        )
        current_pint = updater_param.read_current_comments(
            list(slot_map.pint.keys()), "PInt"
        )
        current_alm = updater_alm.read_current_comments(
            list(slot_map.alm.keys()), "ALM"
        )
        return current_preal, current_pint, current_alm


# ── Helpers de módulo ───────────────────────────────────────────────────


def _extract_codigo(db_param_name: str) -> str:
    """Extrae el ``codigo`` del nombre de DB (``DB53100_CPR_PARAM``
    → ``"CPR"``). Devuelve ``""`` si el formato no encaja."""
    parts = db_param_name.split("_")
    if len(parts) >= 2:
        return parts[1]
    return ""


__all__ = ["SyncProcesosComentariosUseCase"]
