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
     "build_slot_maps", "compute_nmax", "export_and_diff", "done"]``.
     ``compute_nmax`` se ejecuta entre ``build_slot_maps`` y
     ``export_and_diff`` y emite las cards de N_MAX del proceso
     (PReal / PInt / ALM). Es **solo visual** (no se aplica en
     el commit actual).
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
                    "total":       int,
                    "agregados":   int,
                    "renombrados": int,
                    "eliminados":  int,
                    "sin_cambios": int,
                  },
                  "warnings": list[str],
                }
        """
        # Solo emitir progress si NO hay ya una operación activa.
        # Si el operario disparó un escaneo de bloques (o un
        # ``generar_prevision`` anterior) que aún está en curso,
        # nuestro ``begin()`` lo sobrescribiría y los ``start_stage``
        # podrían fallar (``ValueError`` si el stage no está en
        # los declarados en el ``begin()`` del otro caller).
        # Patrón análogo a ``sync_dispositivos_instances``.
        _track = not self._progress.active
        if _track:
            self._progress.begin(
                operation="preview_procesos_comentarios",
                label=f"Generando preview comentarios proceso {proc_uid}",
                stages=[
                    "check_state", "check_blocks", "build_slot_maps",
                    "compute_nmax", "export_and_diff", "done",
                ],
            )
        try:
            # check_state: validar que excel_cache no esté vacío.
            if _track:
                self._progress.start_stage("check_state", "Validando AppState...")
            if self._state.excel_cache is None:
                if _track:
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
                    "summary": {"total": 0, "agregados": 0, "renombrados": 0,
                                "eliminados": 0, "sin_cambios": 0},
                    "warnings": [],
                }
            if _track:
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
            if _track:
                self._progress.start_stage("check_blocks", "Verificando bloques TIA...")
            if self._bloques_cache is None:
                if _track:
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
                    "summary": {"total": 0, "agregados": 0, "renombrados": 0,
                                "eliminados": 0, "sin_cambios": 0},
                    "warnings": [],
                }
            bloques = self._bloques_cache
            if _track:
                self._progress.finish_stage(
                    "check_blocks",
                    f"{len(bloques.blocks)} bloques, {len(bloques.tag_tables)} tablas"
                )

            # build_slot_maps: cruzar Excel + BloqueCache.
            if _track:
                self._progress.start_stage("build_slot_maps", "Cruzando Excel ↔ bloques...")
            try:
                slot_map = build_proceso_slot_maps(
                    self._state, self._config, proc_uid, bloques
                )
            except RuntimeError as exc:
                if _track:
                    self._progress.finish_stage("build_slot_maps", f"Error: {exc}")
                    self._progress.start_stage("done", "Abortado")
                    self._progress.finish_stage("done", "Abortado")
                return {
                    "proc_uid": proc_uid,
                    "precondiciones_ok": False,
                    "missing_blocks": [str(exc)],
                    "arrays": {},
                    "summary": {"total": 0, "agregados": 0, "renombrados": 0,
                                "eliminados": 0, "sin_cambios": 0},
                    "warnings": [],
                }
            if _track:
                self._progress.finish_stage(
                    "build_slot_maps",
                    f"PReal={len(slot_map.preal)} PInt={len(slot_map.pint)} "
                    f"ALM={len(slot_map.alm)}",
                )

            # compute_nmax: cards SOLO VISUALES con los N_MAX
            # del proceso (``<uid>_N_MAX_<suffix>``). Compara
            # el desired (de las listas del Excel) contra el
            # current (PlcUserConstant de TIA exportada de la
            # tabla del proceso, ``<uid>_<codigo>``, en
            # ``003_Procesos/``).
            if _track:
                self._progress.start_stage("compute_nmax", "Leyendo N_MAX...")
            nmax_block = await self._compute_nmax_diff(slot_map)
            nmax_summary = nmax_block.get("summary", {})
            if _track:
                self._progress.finish_stage(
                    "compute_nmax",
                    f"{nmax_summary.get('actualizar', 0)} actualizar, "
                    f"{nmax_summary.get('sin_cambios', 0)} sin cambios",
                )

            # done: precondiciones ok?
            if slot_map.missing_blocks:
                if _track:
                    # Saltamos ``export_and_diff`` (no hay nada que
                    # comparar: el proceso no existe en el PLC). Lo
                    # marcamos como DONE con un detalle explicativo
                    # para que el contador del progress bar avance
                    # de 4/6 a 5/6 y no quede pillado.
                    self._progress.start_stage(
                        "export_and_diff",
                        "Saltado (precondiciones no cumplidas)",
                    )
                    self._progress.finish_stage(
                        "export_and_diff",
                        f"Saltado: {len(slot_map.missing_blocks)} "
                        f"bloques ausentes en el PLC",
                    )
                    self._progress.start_stage(
                        "done",
                        f"Faltan {len(slot_map.missing_blocks)} bloques",
                    )
                    self._progress.finish_stage(
                        "done",
                        f"Faltan {len(slot_map.missing_blocks)} bloques",
                    )
                    # Cierra el tracker (``active=False``) para que
                    # la SPA muestre el estado "completado" y no
                    # "En curso" indefinidamente (bug que el operario
                    # reportó el 2026-09-02).
                    self._progress.finish(success=True)
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
                    "summary": {"total": 0, "agregados": 0, "renombrados": 0,
                                "eliminados": 0, "sin_cambios": 0},
                    "warnings": slot_map.warnings,
                }

            # Precondiciones OK: exportar los 3 DBs y comparar con
            # el Excel para producir un diff real. Sin este stage
            # el "total" sería fake (= nº de slots del Excel),
            # no el nº de cambios que se aplicarían. Con este
            # stage:
            #   - exportamos DB_PARAM y DB_ALM (1-3 min en PLCs
            #     grandes) a un work_dir.
            #   - leemos los .s7res resultantes y extraemos el
            #     ``es-ES`` actual de cada slot (solo del array
            #     principal, no de los satélites).
            #   - comparamos desired (Excel) con current (TIA) por
            #     slot. action ∈ {sin_cambios, renombrar, agregar}.
            if _track:
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
                if _track:
                    self._progress.finish_stage(
                        "export_and_diff",
                        f"Error exportando: {exc}",
                    )
                current_preal = current_pint = current_alm = None
                if _track:
                    self._progress.start_stage(
                        "done",
                        f"Preview con current=None (export falló)",
                    )
                    self._progress.finish_stage(
                        "done",
                        f"Preview con current=None (export falló)",
                    )
                response = self._compose_response(
                    proc_uid, slot_map,
                    preal_current=None, pint_current=None, alm_current=None,
                    nmax_block=nmax_block,
                    extra_warnings=[f"Export falló: {exc}. current=None."],
                )
                if _track:
                    self._progress.finish(success=True)
                return response

            arrays = self._compose_arrays(
                slot_map, current_preal, current_pint, current_alm
            )
            summary = self._compute_summary(arrays)
            if _track:
                self._progress.finish_stage(
                    "export_and_diff",
                    f"{summary['renombrados']} renombrar, "
                    f"{summary['agregados']} agregar, "
                    f"{summary['sin_cambios']} sin cambios",
                )

                self._progress.start_stage(
                    "done",
                    f"{summary['total']} slots: "
                    f"{summary['renombrados']} renombrar, "
                    f"{summary['agregados']} agregar, "
                    f"{summary['sin_cambios']} sin cambios",
                )
                self._progress.finish_stage(
                    "done",
                    f"{summary['total']} slots: "
                    f"{summary['renombrados']} renombrar, "
                    f"{summary['agregados']} agregar, "
                    f"{summary['sin_cambios']} sin cambios",
                )
                # Cierra el tracker (``active=False``) para que la SPA
                # muestre el estado "completado" en lugar de "En curso"
                # indefinidamente. ``finish_stage("done")`` solo marca
                # el último stage como DONE, pero el ``ProgressTracker``
                # sigue en ``active=True`` hasta que se llame a
                # ``finish(success=True)``.
                self._progress.finish(success=True)
            return self._compose_response(
                proc_uid, slot_map,
                preal_current=current_preal,
                pint_current=current_pint,
                alm_current=current_alm,
                nmax_block=nmax_block,
            )
        except Exception as exc:
            if _track:
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
        # Solo emitir progress si NO hay ya una operación activa.
        # Patrón análogo a ``sync_dispositivos_instances`` y a
        # ``generar_prevision`` de este mismo módulo.
        _track = not self._progress.active
        if _track:
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
            if _track:
                self._progress.start_stage("check_state", "Validando AppState...")
            if self._state.excel_cache is None:
                if _track:
                    self._progress.finish_stage("check_state", "Excel no cargado")
                raise RuntimeError(
                    "AppState.excel_cache está vacío. Cargue el Excel con "
                    "POST /api/v1/excel/upload."
                )
            if _track:
                self._progress.finish_stage("check_state", "AppState OK")

            # check_blocks.
            if _track:
                self._progress.start_stage("check_blocks", "Verificando bloques TIA...")
            if self._bloques_cache is None:
                if _track:
                    self._progress.finish_stage(
                        "check_blocks", "Cache de bloques no disponible"
                    )
                raise RuntimeError(
                    "Cache de bloques del PLC no disponible. "
                    "Selecciona el PLC en el sidebar y espera al "
                    "escaneo de bloques (1-3 min en PLCs grandes)."
                )
            bloques = self._bloques_cache
            if _track:
                self._progress.finish_stage(
                    "check_blocks",
                    f"{len(bloques.blocks)} bloques, {len(bloques.tag_tables)} tablas"
                )

            # build_slot_maps: recalcular desde AppState (NO usar prevision).
            if _track:
                self._progress.start_stage("build_slot_maps", "Recalculando diff...")
            slot_map = build_proceso_slot_maps(
                self._state, self._config, proc_uid, bloques
            )
            if slot_map.missing_blocks:
                raise RuntimeError(
                    f"Faltan bloques en el PLC: {slot_map.missing_blocks}"
                )
            if _track:
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

            # Slots a "eliminar" (en TIA pero no en el Excel). Para
            # detectarlos, re-leemos el ``current`` de TIA con la
            # misma rutina que el preview. Si el re-export falla (TIA
            # no responde), seguimos solo con los slots del Excel
            # (modo degradado: el operario verá solo "renombrar /
            # agregar", no "eliminar", pero el apply no aborta).
            preal_to_delete: dict[int, str] = {}
            pint_to_delete: dict[int, str] = {}
            alm_to_delete: dict[int, str] = {}
            try:
                current_preal, current_pint, current_alm = (
                    await self._export_and_read_current(slot_map)
                )
                if current_preal:
                    for slot in sorted(
                        set(current_preal.keys()) - set(slot_map.preal.keys())
                    ):
                        text = current_preal[slot]
                        if text:  # solo si hay algo que "borrar"
                            preal_to_delete[slot] = "."
                if current_pint:
                    for slot in sorted(
                        set(current_pint.keys()) - set(slot_map.pint.keys())
                    ):
                        text = current_pint[slot]
                        if text:
                            pint_to_delete[slot] = "."
                if current_alm:
                    for slot in sorted(
                        set(current_alm.keys()) - set(slot_map.alm.keys())
                    ):
                        text = current_alm[slot]
                        if text:
                            alm_to_delete[slot] = "."
            except Exception as exc:
                _logger.warning(
                    f"ejecutar_transaccion: re-lectura de TIA para "
                    f"detectar 'eliminar' falló: {exc}. El apply solo "
                    f"aplicará los slots del Excel (sin 'eliminar')."
                )

            # Mezcla los slot_maps: Excel + "eliminar" (reset a ".").
            preal_apply = {
                **{str(k): v for k, v in slot_map.preal.items()},
                **{str(k): v for k, v in preal_to_delete.items()},
            }
            pint_apply = {
                **{str(k): v for k, v in slot_map.pint.items()},
                **{str(k): v for k, v in pint_to_delete.items()},
            }
            alm_apply = {
                **{str(k): v for k, v in slot_map.alm.items()},
                **{str(k): v for k, v in alm_to_delete.items()},
            }

            operations: list[dict[str, Any]] = [
                {
                    "command": "update_proc_comments_db_preal",
                    "args": {
                        "plc_name": plc_name,
                        "db_name": slot_map.db_param_name,
                        "array_name": "PReal",
                        "slot_map": preal_apply,
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
                        "slot_map": pint_apply,
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
                        "slot_map": alm_apply,
                        "work_dir": str(work_dir),
                        "target_folder": target_folder,
                    },
                },
            ]

            if _track:
                self._progress.start_stage(
                    "open_transaction",
                    "Aplicando 3 comentarios a TIA — puede tardar 1-3 min",
                )
            result = await self._gateway.execute_transactional_batch(
                operations=operations,
                undo_text=undo_text,
            )
            ops_executed = result.get("operations_executed", 0)
            if _track:
                self._progress.finish_stage(
                    "open_transaction",
                    f"{ops_executed} ops aplicadas OK",
                )
                self._progress.start_stage("done", f"{ops_executed} ops")
                self._progress.finish_stage("done", f"{ops_executed} ops")
                # Cierra el tracker (``active=False``) para que la SPA
                # muestre el estado "completado" en lugar de "En curso"
                # indefinidamente.
                self._progress.finish(success=True)

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
            if _track:
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
        action}`` con ``action ∈ {"sin_cambios", "renombrar",
        "agregar", "eliminar"}``.

        Slots del Excel (``slot_map_dict``):
          - Si se pasan los mapas ``*_current`` (devueltos por
            ``ProcesoCommentUpdater.read_current_comments``), el
            ``current`` es el ``es-ES`` real de TIA y ``action``:
              - ``"agregar"`` si el slot no existe en TIA (``current
                is None``) → el apply lo creará.
              - ``"renombrar"`` si ``current != desired``.
              - ``"sin_cambios"`` si ``current == desired``.
          - Si los mapas son ``None`` (export degradado), ``action``
            se infiere del desired (``"."`` → "agregar", otro →
            "renombrar").

        Slots de TIA NO en el Excel (``current_dict \ slot_map_dict``):
          - Caso "eliminar". El slot existe en TIA con un comentario
            histórico pero el operario no lo tiene en su Excel
            (p. ej.Compactado de 60 slots donde el Excel solo trae
            los 20 que el operario quiere gestionar). El apply
            resetea el comentario a ``"."`` (convención TIA "sin
            comentario"). Si el current es ``""`` (ya vacío),
            ``action = "sin_cambios"`` para no molestar al operario.

        Los labels están alineados con ``sync_dispositivos_instances``
        para que la SPA reuse la misma ``STATUS_META``.
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
            # Slots del Excel: comparar desired vs current.
            for slot, desired in slot_map_dict.items():
                if current_dict is not None:
                    current = current_dict.get(slot)
                    if current is None:
                        action = "agregar"
                    elif current == desired:
                        action = "sin_cambios"
                    else:
                        action = "renombrar"
                else:
                    current = None
                    action = "agregar" if desired == "." else "renombrar"
                slot_map_serialized[str(slot)] = {
                    "current": current,
                    "desired": desired,
                    "action": action,
                }
            # Slots de TIA NO en el Excel: "eliminar".
            if current_dict is not None:
                excel_slots = set(slot_map_dict.keys())
                tia_slots = set(current_dict.keys())
                to_remove = sorted(tia_slots - excel_slots)
                for slot in to_remove:
                    current = current_dict[slot]
                    if current is None or current == "":
                        # Slot vacío en TIA, no hay nada que borrar.
                        # Lo reportamos como "sin_cambios" para no
                        # contaminar la UI con falsos positivos.
                        action = "sin_cambios"
                    else:
                        action = "eliminar"
                    slot_map_serialized[str(slot)] = {
                        "current": current,
                        "desired": None,  # no está en el Excel
                        "action": action,
                    }
            arrays[arr_name] = {
                "db_name": db_name,
                "array_name": arr_name,
                "satellite_arrays": satellites,
                "current_count": len(current_dict) if current_dict is not None else 0,
                "desired_count": len(slot_map_dict),
                "slot_map": slot_map_serialized,
            }
        return arrays

    def _compute_summary(self, arrays: dict[str, Any]) -> dict[str, int]:
        """Suma el total de slots y cuenta por tipo de acción.

        Shape del dict (alineado con ``sync_dispositivos_instances``):

        - ``agregados``: nº de slots con ``action == "agregar"``.
        - ``renombrados``: nº de slots con ``action == "renombrar"``.
        - ``eliminados``: nº de slots con ``action == "eliminar"``.
          Slots que están en TIA pero no en el Excel; el apply los
          resetea a ``"."`` (convención TIA "sin comentario").
        - ``sin_cambios``: nº de slots con ``action == "sin_cambios"``.
        - ``total``: suma de los 4 anteriores.
        """
        total = 0
        agregados = 0
        renombrados = 0
        eliminados = 0
        sin_cambios = 0
        for arr in arrays.values():
            for entry in arr.get("slot_map", {}).values():
                total += 1
                action = entry.get("action")
                if action == "agregar":
                    agregados += 1
                elif action == "renombrar":
                    renombrados += 1
                elif action == "eliminar":
                    eliminados += 1
                elif action == "sin_cambios":
                    sin_cambios += 1
        return {
            "total": total,
            "agregados": agregados,
            "renombrados": renombrados,
            "eliminados": eliminados,
            "sin_cambios": sin_cambios,
        }

    def _compose_response(
        self,
        proc_uid: int,
        slot_map: ProcesoSlotMap,
        preal_current: "dict[int, str | None] | None" = None,
        pint_current: "dict[int, str | None] | None" = None,
        alm_current: "dict[int, str | None] | None" = None,
        nmax_block: "dict[str, Any] | None" = None,
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
            "nmax": nmax_block or {},
            "warnings": warnings,
        }

    async def _compute_nmax_diff(
        self, slot_map: ProcesoSlotMap
    ) -> dict[str, Any]:
        """Lee los N_MAX del proceso (cards SOLO VISUALES).

        Convencion del operario (2026-09-02):
          - Las PlcUserConstant N_MAX de un proceso viven en la
            **tabla del proceso** (``<uid>_<codigo>``, p. ej.
            ``100_CPR``), en la carpeta TIA ``003_Procesos/``. NO
            en la tabla ``000_Config_Dispositivos`` (esa es para
            los N_MAX de dispositivos).
          - El nombre completo de cada PlcUserConstant es
            ``f"{proc.uid}_N_MAX_{suffix}"`` (p. ej.
            ``100_N_MAX_PREAL``), con el sufijo del config.

        Compara el desired (de ``ProcesoSlotMap.nmax``,
        ``len()`` de las listas filtradas del Excel) contra el
        current (exportando la tabla del proceso con
        ``gateway.export_plc_tags_xml`` y parseando con
        ``SimaticMLTagParser.parse_user_constants``).

        Mismo shape que el ``nmax_block`` de Dispositivos:
        ``{"current", "desired", "todos", "summary"}``.

        Si el config no aporta ``procesos.n_max_suffixes``
        (departamento sin soporte de N_MAX de procesos), devuelve
        un bloque con ``todos=[]`` y ``summary={actualizar: 0,
        sin_cambios: 0, total: 0}``. La SPA no renderiza las cards
        en ese caso.

        Si el export falla, NO aborta el preview: emite un warning
        y devuelve un bloque con ``current={}`` y
        ``status="sin_cambios"`` para todos los kinds. La SPA
        mostrará las cards con current=desconocido (gris) en lugar
        de romper la vista.

        Raises:
            nada: cualquier excepción se loggea como warning y se
            devuelve un bloque degradado.
        """
        from areas.alimentacion.infrastructure.xml.tag_table_parser import (
            SimaticMLTagParser,
        )

        nmax_names = slot_map.nmax_names
        nmax_desired = slot_map.nmax

        # Sin config: el departamento no soporta N_MAX de procesos.
        if not nmax_names or not nmax_desired:
            return {
                "current": {},
                "desired": {},
                "todos": [],
                "summary": {
                    "actualizar": 0, "sin_cambios": 0, "total": 0,
                },
            }

        # 1. Estado actual en TIA. Las N_MAX del proceso viven en
        # la tabla del proceso (``<uid>_<codigo>``, p. ej. ``100_CPR``)
        # en la carpeta TIA ``003_Procesos/``. NO en la tabla
        # ``000_Config_Dispositivos`` de dispositivos.
        # ``target_dir`` SIN subcarpeta: el worker, con
        # ``keep_folder_structure=True``, crea la jerarquía del PLC
        # (``target_dir/003_Procesos/100_CPR.xml``).
        target_dir = self._build_work_dir(suffix="preview")
        target_dir.mkdir(parents=True, exist_ok=True)
        table_name = slot_map.table_name  # p. ej. "100_CPR"

        current: dict[str, int] = {}
        try:
            await self._gateway.export_plc_tags_xml(
                self._bloques_cache.plc_name,  # type: ignore[union-attr]
                str(target_dir),
                table_names=[table_name],
            )
            # El worker puede haber escrito el XML en
            # ``<target_dir>/<grupo>/<table>.xml`` o directamente en
            # ``<target_dir>/<table>.xml`` según el group structure
            # del PLC. Buscamos en cualquier subdirectorio para
            # ser tolerantes.
            matches = list(target_dir.rglob(f"{table_name}.xml"))
            if matches:
                current = SimaticMLTagParser.parse_user_constants(matches[0])
            else:
                _logger.warning(
                    f"[N_MAX procesos] XML esperado no encontrado en "
                    f"{target_dir} para tabla {table_name}."
                )
        except Exception as exc:
            _logger.warning(
                f"[N_MAX procesos] export/parse falló: {exc}. "
                f"Devolviendo current={{}} para no romper la SPA."
            )
            current = {}

        # 2. Diff unificado: los N_MAX del proceso siempre existen
        # en TIA (son PlcUserConstant con cardinalidad fija por
        # proyecto), así que solo hay ``actualizar`` o ``sin_cambios``.
        todos: list[dict[str, Any]] = []
        for kind, name in nmax_names.items():
            cur_val = current.get(name)
            des_val = nmax_desired.get(kind, 0)
            if cur_val is not None and int(cur_val) == int(des_val):
                status = "sin_cambios"
            else:
                status = "actualizar"
            todos.append({
                "kind": kind,
                "name": name,
                "actual": cur_val,
                "nuevo": des_val,
                "status": status,
            })

        return {
            "current": {nmax_names[k]: v for k, v in current.items()
                        if k in nmax_names},
            "desired": {nmax_names[k]: nmax_desired[k] for k in nmax_names
                        if k in nmax_desired},
            "todos": todos,
            "summary": {
                "actualizar": sum(1 for r in todos if r["status"] == "actualizar"),
                "sin_cambios": sum(1 for r in todos if r["status"] == "sin_cambios"),
                "total": len(todos),
            },
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
        # Slots a leer: los del Excel + los que tienen asignación
        # en el ``.s7dcl`` (slots de TIA no en el Excel → "eliminar"
        # en el preview). Si el ``.s7dcl`` no existe, ``find_array_slots``
        # devuelve set() y solo se leen los del Excel (modo degradado).
        preal_slots = (
            set(slot_map.preal.keys()) | updater_param.find_array_slots("PReal")
        )
        pint_slots = (
            set(slot_map.pint.keys()) | updater_param.find_array_slots("PInt")
        )
        alm_slots = (
            set(slot_map.alm.keys()) | updater_alm.find_array_slots("ALM")
        )
        current_preal = updater_param.read_current_comments(
            sorted(preal_slots), "PReal"
        )
        current_pint = updater_param.read_current_comments(
            sorted(pint_slots), "PInt"
        )
        current_alm = updater_alm.read_current_comments(
            sorted(alm_slots), "ALM"
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
