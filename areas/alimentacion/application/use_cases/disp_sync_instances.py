"""Application Layer - Sincronizar Instancias de Dispositivos (N_MAX + devices).

Caso de uso: realiza el sync completo entre el Excel corporativo (v\u00eda
``AppState``) y el PLC de TIA Portal en UNA sola transacci\u00f3n COM \u00fanica.

El flujo de ``generar_prevision`` calcula:

  1. **N_MAX** (dimensiones): diff por nombre entre
     ``000_Config_Dispositivos.xml`` (TIA) y ``AppState.dimensiones``
     (Excel). Emite operaciones ``update_user_constant_value`` (online).
  2. **Devices** (instancias): diff por UID (valor) entre las 6 tablas
     ``2000_Disp_*`` (TIA) y ``AppState.dispositivos_*`` (Excel).
     Emite operaciones ``update_user_constant_name`` (online rename)
     y, si hay add/remove, ``import_plc_tags_xml`` (offline XML).

El flujo de ``ejecutar_transaccion`` calcula en el IT process los
``nmax_ops``, ``rename_ops`` y ``device_changes`` (este último solo si
hay adds o removes) y los pasa a ``gateway.commit_devices_sync``, que
ejecuta DENTRO DEL WORKER una única ``start_transaction`` con el orden
estricto del operario:
  1. N_MAX online (``update_user_constant_value`` por cada uno).
  2. Renames online (``update_user_constant_name`` por cada uno).
  3. Por cada ``device_change``: export selectivo + ``TagTableModifier``
     (add/remove) + import selectivo.
  4. ``end_transaction(rollback=False)``.

Si cualquier paso falla, el worker hace ``end_transaction(rollback=True)``
y propaga el error. La fase offline (edit XML) corre DENTRO del worker
para garantizar una sola transacción TIA (no dos). El módulo
``TagTableModifier`` es Python puro (no importa ``siemens_tia_scripting``),
así que no rompe ``.clinerules §1``.

Shape del preview (back-compat con la SPA):
  - ``agregados`` / ``eliminados`` / ``renombrados`` (listas de devices).
  - ``todos`` (lista unificada con ``{table, type, uid, numero, actual,
    nuevo, status}``).
  - ``nmax`` (``{current, desired, todos, summary}`` para la vista N_MAX).
  - ``summary`` (contadores globales).

Restricci\u00f3n:
  - NO importa ``siemens_tia_scripting``.
  - Los nombres de tabla PLC se resuelven v\u00eda ``ConfigManager``.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from areas.alimentacion.application.use_cases.disp_diff_constants import (
    DispCalculateConstantsDiffUseCase,
)
from areas.alimentacion.infrastructure.build_cache import build_cache
from core.application.progress_buffer import ProgressTracker, get_progress_tracker
from core.application.state import AppState, get_app_state
from core.infrastructure.config_manager import ConfigManager
from core.infrastructure.gateway import TIAProcessGateway
from core.infrastructure.tia.export_paths import XmlTarget
from areas.alimentacion.infrastructure.xml.disp_tag_table_modifier import TagTableModifier


_logger = logging.getLogger(
    f"{__name__}.DispSyncInstancesUseCase"
)


class DispSyncInstancesUseCase:
    """Caso de Uso: sincroniza N_MAX + instancias del subdominio alimentacion.

    El mapeo ``hw_type \u2194 atributo AppState`` se obtiene del
    ``ConfigManager`` (v\u00eda ``get_app_state_attr_for(hw)``). Los 6
    legacy (``ed/ea/sa/v/m/m_vf``) siguen funcionando id\u00e9ntico.

    Atributos de la release actual (N_MAX + devices):
      - ``generar_prevision(plc_name)`` \u2192 diff completo (N_MAX + devices).
      - ``ejecutar_transaccion(plc_name, prevision)`` \u2192 transacci\u00f3n \u00fanica.
      - ``execute(plc_name)`` \u2192 helper que encadena ambos.
    """

    def __init__(
        self,
        gateway: TIAProcessGateway,
        config_manager: ConfigManager,
        state: AppState | None = None,
        build_cache_dir: Path | None = None,
        progress: ProgressTracker | None = None,
    ) -> None:
        self._gateway = gateway
        self._config = config_manager
        self._state = state if state is not None else get_app_state()
        # ``build_cache_dir`` es ahora la RA\u00cdZ del ``BuildCache`` del
        # \u00e1rea (no un workdir concreto). Por convenci\u00f3n, apunta a
        # ``<cwd>/.build_cache``. Tests legacy siguen pasando ``tmp_path``
        # o ``tmp_path / ".build_cache"`` aqu\u00ed; ambos funcionan.
        self._build_cache = build_cache_dir or (
            Path(os.getcwd()) / ".build_cache"
        )
        # ``ProgressTracker`` opcional. Si no se inyecta, usamos el
        # Singleton global (Composition Root de ``main.py``). Tests
        # legacy que no lo pasan se siguen comportando idéntico: el
        # tracker emite pero nadie lo lee.
        self._progress: ProgressTracker = (
            progress if progress is not None else get_progress_tracker()
        )

    # ──────────────────────────────────────────────────────────────────
    # API pública
    # ──────────────────────────────────────────────────────────────────

    async def generar_prevision(self, plc_name: str) -> dict[str, Any]:
        """Calcula el diff completo: N_MAX + devices.

        Comportamiento con el ``ProgressTracker``: solo emite los
        4 stages (begin/start_stage/finish) si NO hay ya una
        operación activa en el tracker. Esto permite que
        ``ejecutar_transaccion`` llame internamente a este método
        (para el post-sync preview) sin pisar el tracker del
        commit en curso. La firma pública NO cambia: 100%
        back-compat con tests legacy que monkey-patchean este método.

        Steps:
          1. Export bulk del PLC al directorio
             ``.build_cache/alimentacion/dispositivos/exports/`` (vía
             ``build_cache(root=self._build_cache).dispositivos.exports``).
          2. Calcula el diff de devices (instancias) con
             ``_compute_diff_readonly`` sobre los 6 XMLs
             ``2000_Disp_*``.
          3. Calcula el diff de N_MAX con ``_extract_nmax_diff`` sobre
             ``000_Config_Dispositivos.xml``.
          4. Devuelve el shape legacy esperado por la SPA:
             ``{agregados, eliminados, renombrados, todos, nmax, summary}``.
        """
        # Solo emitir progress si NO hay ya una operación activa
        # (típicamente un commit en curso desde ``ejecutar_transaccion``).
        _track = not self._progress.active
        if _track:
            # ── Progress tracking (overlay SPA) ────────────────
            # 4 stages: export_tags → compute_devices → compute_nmax → build_response.
            self._progress.begin(
                operation="preview",
                label=f"Generando previsión para {plc_name}",
                stages=[
                    "export_tags",
                    "compute_devices",
                    "compute_nmax",
                    "build_response",
                ],
            )
        try:
            # Workdir de export para el diff read-only. Por convenci\u00f3n
            # de la app, vive en ``.build_cache/alimentacion/dispositivos/exports/``.
            tags_base = build_cache(root=self._build_cache).dispositivos.exports
            tags_base.mkdir(parents=True, exist_ok=True)
            if _track:
                self._progress.start_stage(
                "export_tags", "Iniciando export bulk de tags del PLC..."
            )
            # Export SELECTIVO: solo las 7 tablas que el sync toca
            # (6 devices + 1 N_MAX). Deriva de ConfigManager (data-driven).
            selective_tables = self._selective_table_names()
            await self._gateway.export_plc_tags_xml(
                plc_name, str(tags_base), table_names=selective_tables,
            )
            if _track:
                self._progress.finish_stage("export_tags", "Export OK")

            if _track:
                self._progress.start_stage("compute_devices")
            desired_state_per_table = self._build_desired_state_from_app()
            added_p, removed_p, renamed, base_state_per_table = (
                await asyncio.to_thread(
                    self._compute_diff_readonly,
                    tags_base,
                    desired_state_per_table,
                )
            )
            if _track:
                self._progress.finish_stage(
                "compute_devices",
                f"{len(base_state_per_table)} tablas analizadas",
            )

            # N_MAX: lee la tabla de configuración global.
            if _track:
                self._progress.start_stage("compute_nmax")
            nmax_block = await asyncio.to_thread(
                self._extract_nmax_diff, tags_base
            )
            if _track:
                self._progress.finish_stage(
                "compute_nmax",
                f"{len(nmax_block.get('todos', []))} N_MAX evaluadas",
            )

            # Listas legacy (back-compat con la SPA actual).
            if _track:
                self._progress.start_stage("build_response")
            agregados: list[dict[str, Any]] = [
                {"uid": uid, "table": tk, "plc_tag": td.get(uid, "")}
                for tk, td in desired_state_per_table.items()
                for uid in added_p.get(tk, []) if uid in td
            ]
            eliminados: list[dict[str, Any]] = [
                {"uid": uid, "table": tk, "plc_tag": tb.get(uid, "")}
                for tk, tb in base_state_per_table.items()
                for uid in removed_p.get(tk, []) if uid in tb
            ]
            renombrados: list[dict[str, Any]] = [
                {
                    "uid": uid.split(":", 1)[1] if ":" in uid else uid,
                    "table": uid.split(":", 1)[0] if ":" in uid else "",
                    "actual": old,
                    "nuevo": new,
                }
                for uid, (old, new) in renamed.items()
            ]

            # Lista UNIFICADA para la vista de pestañas.
            def _type_from_table(table_key: str) -> str:
                """``2000_Disp_ED`` → ``"ed"``, ``2000_Disp_M_VF`` → ``"m_vf"``."""
                stem = table_key.split("_Disp_", 1)[-1]
                return stem.lower()

            todos: list[dict[str, Any]] = []
            for table_key, base in base_state_per_table.items():
                type_key = _type_from_table(table_key)
                renamed_for_table: dict[str, str] = {}
                for uid, (_old, new) in renamed.items():
                    if uid.startswith(f"{table_key}:"):
                        renamed_for_table[uid.split(":", 1)[1]] = new

                removed_uids = set(removed_p.get(table_key, []))

                for uid_str, plc_tag in base.items():
                    try:
                        numero = int(uid_str)
                    except (TypeError, ValueError):
                        numero = 0
                    if uid_str in renamed_for_table:
                        todos.append({
                            "table": table_key,
                            "type": type_key,
                            "uid": uid_str,
                            "numero": numero,
                            "actual": plc_tag,
                            "nuevo": renamed_for_table[uid_str],
                            "status": "renombrar",
                        })
                    elif uid_str in removed_uids:
                        todos.append({
                            "table": table_key,
                            "type": type_key,
                            "uid": uid_str,
                            "numero": numero,
                            "actual": plc_tag,
                            "nuevo": None,
                            "status": "eliminar",
                        })
                    else:
                        todos.append({
                            "table": table_key,
                            "type": type_key,
                            "uid": uid_str,
                            "numero": numero,
                            "actual": plc_tag,
                            "nuevo": plc_tag,
                            "status": "sin_cambios",
                        })

            for table_key, desired in desired_state_per_table.items():
                type_key = _type_from_table(table_key)
                for uid_str in added_p.get(table_key, []):
                    try:
                        numero = int(uid_str)
                    except (TypeError, ValueError):
                        numero = 0
                    todos.append({
                        "table": table_key,
                        "type": type_key,
                        "uid": uid_str,
                        "numero": numero,
                        "actual": None,
                        "nuevo": desired.get(uid_str, ""),
                        "status": "agregar",
                    })

            todos.sort(
                key=lambda r: (
                    r["type"],
                    r["numero"] if isinstance(r["numero"], int) else 0,
                )
            )

            result = {
                "agregados": agregados,
                "eliminados": eliminados,
                "renombrados": renombrados,
                "todos": todos,
                "nmax": nmax_block,
                "summary": {
                    "agregados": len(agregados),
                    "eliminados": len(eliminados),
                    "renombrados": len(renombrados),
                    "sin_cambios": sum(
                        1 for r in todos if r["status"] == "sin_cambios"
                    ),
                    "total": len(todos),
                },
            }
            if _track:
                self._progress.finish_stage("build_response")
            self._progress.finish(success=True)
            return result
        except Exception as exc:
            self._progress.finish(success=False, error=str(exc))
            raise

    async def ejecutar_transaccion(
        self,
        plc_name: str,
        prevision: dict[str, Any],
    ) -> dict[str, Any]:
        """Ejecuta el diff completo (N_MAX + devices) en UNA transacci\u00f3n \u00fanica.

        Flujo (especificacion del operario, plan 2026-08-28):
          1. Export selectivo de las 7 tablas a ``tags_base/`` (IT process).
          2. ``_compute_diff_readonly`` para detectar adds/removes/renames
             (IT process, sin tocar XMLs).
          3. Construir ``nmax_ops``, ``rename_ops`` y ``device_changes``
             (IT process).
          4. ``gateway.commit_devices_sync`` (worker):
             a. ``project.start_transaction``.
             b. N_MAX online.
             c. Renames online.
             d. Por cada ``device_change``: export selectivo +
                ``TagTableModifier`` (add/remove) + import selectivo.
             e. ``project.end_transaction(rollback=False)``.
          5. Post-commit: preview, compile, comentarios (best-effort,
             fuera de la tx).

        Args:
            plc_name: Nombre del PLC destino.
            prevision: Resultado de ``generar_prevision``. NO se usa
                directamente (se recalcula desde el AppState para
                evitar race conditions); se conserva en la firma por
                back-compat con la SPA.
        """
        # ── Progress tracking (overlay SPA) ────────────────────────
        # 7 stages fijos que reflejan las operaciones reales del flujo
        # (IT process + batch + post-commit). Cada uno se emite solo si
        # tiene sentido (e.g. ``compile_plc`` se marca "Saltado" si
        # no hay nada que commitear).
        self._progress.begin(
            operation="commit",
            label=f"Aplicando cambios en {plc_name}",
            stages=[
                "export_tags",
                "compute_diff",
                "prepare_xml",
                "open_transaction",
                "post_preview",
                "compile_plc",
                "apply_comentarios_disp",
            ],
        )
        try:
            # ── Stage 1: export selectivo ──────────────────────────
            # Workdir de export para el diff. Mismo que en ``generar_prevision``:
            # ``.build_cache/alimentacion/dispositivos/exports/``. Lo limpiamos
            # con ``ctx.clean()`` para evitar XMLs de runs anteriores que
            # ensucien el diff (defensivo: cualquier fallo previo puede haber
            # dejado ``tags_base/`` con contenido parcial).
            disp_ctx = build_cache(root=self._build_cache).dispositivos
            disp_ctx.clean()
            tags_base = disp_ctx.exports
            tags_base.mkdir(parents=True, exist_ok=True)
            self._progress.start_stage(
                "export_tags", "Exportando 7 tablas del PLC (selectivo)..."
            )
            selective_tables = self._selective_table_names()
            await self._gateway.export_plc_tags_xml(
                plc_name, str(tags_base), table_names=selective_tables,
            )
            self._progress.finish_stage(
                "export_tags", f"Export OK ({len(selective_tables)} tablas)"
            )

            # ── Stage 2: compute diff (read-only) ──────────────────
            self._progress.start_stage("compute_diff")
            desired_state_per_table = self._build_desired_state_from_app()
            added_per_table, removed_per_table, renamed, _ = await asyncio.to_thread(
                self._compute_diff_readonly, tags_base, desired_state_per_table,
            )
            total_adds = sum(len(v) for v in added_per_table.values())
            total_removes = sum(len(v) for v in removed_per_table.values())
            self._progress.finish_stage(
                "compute_diff",
                f"{total_adds} adds, {total_removes} removes, "
                f"{len(renamed)} renames",
            )

            # ── Stage 3: prepare (construir ops) ───────────────────
            self._progress.start_stage("prepare_xml")

            # N_MAX: lista de ops online. ``calculate_nmax_diff`` retorna
            # shape ``{command, args}``; aplanamos a ``{table_name,
            # constant_name, new_value}`` que es lo que espera
            # ``commit_devices_sync``.
            nmax_ops_raw = self._compute_nmax_ops_for_apply(
                plc_name, tags_base
            )
            nmax_ops: list[dict[str, Any]] = [
                op["args"] for op in nmax_ops_raw
            ]

            # Renames: lista de ops online (una por rename).
            rename_ops: list[dict[str, Any]] = []
            for uid_with_table, (old, new) in renamed.items():
                # uid_with_table es "table_key:uid_str".
                # Extraemos el table_key para usarlo como ``table_name``.
                table_key, _, _ = uid_with_table.partition(":")
                rename_ops.append({
                    "table_name": table_key,
                    "current_name": old,
                    "new_name": new,
                })

            # device_changes: solo tablas con adds o removes. Si no hay
            # adds ni removes, el bloque devices se salta entero (mas
            # rapido y menos superficie de error).
            device_changes: list[dict[str, Any]] = []
            all_table_keys = set(added_per_table.keys()) | set(
                removed_per_table.keys()
            )
            for table_key in all_table_keys:
                adds = added_per_table.get(table_key, [])
                removes = removed_per_table.get(table_key, [])
                if not adds and not removes:
                    continue
                tia_folder = self._resolve_tia_folder(table_key)
                desired_table = desired_state_per_table.get(table_key, {})
                device_changes.append({
                    "table_name": table_key,
                    "tia_folder": tia_folder,
                    "adds": [
                        {"plc_tag": desired_table[uid], "uid": uid}
                        for uid in adds
                    ],
                    "removes": list(removes),
                })

            self._progress.finish_stage(
                "prepare_xml",
                f"{len(nmax_ops)} N_MAX, {len(rename_ops)} renames, "
                f"{len(device_changes)} device tables",
            )

            # ── Early return: nada que commitear ──────────────────
            if not (nmax_ops or rename_ops or device_changes):
                self._progress.finish_stage(
                    "open_transaction", "Sin cambios (no-op)"
                )
                self._progress.finish_stage("post_preview")
                self._progress.finish_stage(
                    "compile_plc", "Saltado (no-op)"
                )
                # Aun sin cambios, intentamos aplicar comentarios
                # (puede que el usuario solo haya editado la columna
                # comentario_db del Excel sin tocar N_MAX ni devices).
                comments_result = await self._run_apply_comentarios(
                    plc_name
                )
                self._progress.finish(success=True)
                post_sync_preview = await self.generar_prevision(plc_name)
                return {
                    "success": True,
                    "message": "Sin cambios: el PLC ya coincide con el AppState.",
                    "added": [], "removed": [], "renombrados": [],
                    "operations": 0,
                    "n_max_updates": 0,
                    "post_sync_preview": post_sync_preview,
                    "comments_sync": comments_result,
                }

            # ── Stage 4: open_transaction (la unica tx TIA) ────────
            # ``work_dir`` es donde el worker escribe los XML exportados
            # y modificados. En la convención nueva, es el mismo path
            # f\u00edsico que ``tags_base`` (``exports/``): el worker
            # hace export+modify+import en el mismo dir, dentro de la tx
            # TIA. Lo limpiamos de nuevo con ``ctx.clean()`` (idempotente)
            # para que ``commit_devices_sync`` arranque de cero (defensivo
            # ante XMLs stale de un run previo abortado).
            work_dir = disp_ctx.exports
            disp_ctx.clean()

            # Aplicar N_MAX + renames + devices en UNA sola transaccion TIA.
            # Las 3 fases son siempre activas (sin bypass): es un sync atomico
            # por diseno. Si falla una fase, el batch wrapper hace rollback
            # atomico de las 3 y la transaccion queda como si nada.
            self._progress.start_stage(
                "open_transaction",
                f"Aplicando {len(nmax_ops)} N_MAX + {len(rename_ops)} renames "
                f"+ {len(device_changes)} device tables en TIA Portal "
                f"(puede tardar 1-3 min)...",
            )
            result = await self._gateway.commit_devices_sync(
                plc_name=plc_name,
                nmax_ops=nmax_ops,
                rename_ops=rename_ops,
                device_changes=device_changes,
                work_dir=str(work_dir),
                undo_text="Sincronizar N_MAX + Dispositivos",
            )
            self._progress.finish_stage(
                "open_transaction",
                f"{result['operations_executed']} ops aplicadas OK",
            )

            # ── Stage 5: post-sync preview ────────────────────────
            # Despues de end_transaction (sin rollback), re-ejecutamos el
            # preview para que la SPA vea el estado "todo en sync" sin
            # tener que pedirlo de nuevo. Si falla (p.ej. TIA en estado
            # raro), loggeamos warning pero NO fallamos el commit: el
            # apply ya fue exitoso.
            self._progress.start_stage(
                "post_preview", "Generando vista post-sync..."
            )
            try:
                post_sync_preview = await self.generar_prevision(plc_name)
            except Exception as exc:
                _logger.warning(
                    f"[{plc_name}] Post-sync preview fallo "
                    f"(commit ya aplicado): {exc}"
                )
                post_sync_preview = None
            self._progress.finish_stage("post_preview")

            # ── Stage 6: post-commit compile (fuera de la tx) ─────
            # NO va dentro de la transaccion del worker porque:
            # 1. La transaccion ya hizo end_transaction(rollback=False);
            #    el PLC ya esta modificado.
            # 2. La compilacion puede fallar (p.ej. N_MAX cambia dimensiones
            #    de DBs que las referencian) y eso NO debe revertir el sync
            #    (los cambios del Excel ya estan en el PLC).
            # 3. Semantica Siemens: compile_software() retorna True si HAY
            #    errores, False si NO hay errores. Invertimos para que
            #    ``compile_ok`` sea True en el caso feliz.
            self._progress.start_stage(
                "compile_plc", "Compilando software del PLC..."
            )
            compile_ok = True
            compile_error = None
            try:
                has_errors = await self._gateway.compile_plc(plc_name)
                compile_ok = not has_errors
                if not compile_ok:
                    compile_error = (
                        "TIA reporta errores de compilacion. Revisa el "
                        "proyecto en TIA Portal: los DBs pueden haber "
                        "quedado con tamano inconsistente tras el resize "
                        "de N_MAX."
                    )
                    _logger.warning(
                        f"[{plc_name}] Compilacion con errores "
                        f"(commit ya aplicado)."
                    )
                else:
                    _logger.info(f"[{plc_name}] Compilacion OK.")
            except Exception as exc:
                compile_ok = False
                compile_error = f"Excepcion durante la compilacion: {exc}"
                _logger.warning(
                    f"[{plc_name}] Compilacion fallo (commit ya aplicado): {exc}"
                )
            self._progress.finish_stage(
                "compile_plc",
                "Compilacion OK" if compile_ok else "Compilacion con errores",
            )

            # ── Stage 7: apply comentarios (Tx 2, fuera de la tx ppal) ──
            # Se ejecuta DESPUES de la compilacion, que es cuando los DBs
            # ya estan redimensionados y podemos escribir los S7_MLC con
            # confianza. Best-effort: si falla (p.ej. TIA en estado raro),
            # el commit global sigue siendo exitoso (N_MAX+devices ya
            # aplicado); el operario puede reintentar el endpoint de
            # comentarios.
            comments_result = await self._run_apply_comentarios(
                plc_name
            )

            self._progress.finish(success=True)
            return {
                "success": True,
                "message": f"Inyeccion completada. Detalles: {result['details']}",
                "operations": result["operations_executed"],
                "n_max_updates": len(nmax_ops),
                "post_sync_preview": post_sync_preview,
                "compile_ok": compile_ok,
                "compile_error": compile_error,
                "comments_sync": comments_result,
            }
        except Exception as exc:
            # Cualquier fallo (export, diff, build ops, transaccion COM,
            # compilacion) cierra el tracker en estado error. El ultimo
            # stage en ``running`` se marca como ``error`` con el
            # mensaje (lo hace ``finish(success=False)`` internamente).
            self._progress.finish(success=False, error=str(exc))
            raise

    async def execute(self, plc_name: str) -> dict[str, Any]:
        """Helper: generar previsi\u00f3n + ejecutar transacci\u00f3n en una llamada."""
        prevision = await self.generar_prevision(plc_name)
        return await self.ejecutar_transaccion(plc_name, prevision)

    async def _run_apply_comentarios(self, plc_name: str) -> dict[str, Any]:
        """Aplica los comentarios por instancia a los 6 DBs de dispositivos.

        Se ejecuta DESPUES de ``compile_plc`` dentro de ``ejecutar_transaccion``.
        Best-effort: si falla, el commit global sigue siendo exitoso
        (N_MAX + devices ya estan aplicados); el operario puede reintentar
        via POST /api/v1/alimentacion/aplicar-comentarios-disp.

        Returns:
            ``dict`` con shape::

                {
                    "applied":       bool,
                    "operations_executed": int,
                    "warnings":      list[str],
                    "error":         str | None,  # solo si fallo
                }
        """
        self._progress.start_stage(
            "apply_comentarios_disp",
            "Aplicando comentarios por instancia a los 6 DBs...",
        )
        try:
            from areas.alimentacion.application.disp_slot_map_builder import (
                disp_build_slot_maps,
            )
            slot_maps, db_names, db_array_names, build_warnings = disp_build_slot_maps(
                self._state, self._config
            )
            warnings = list(build_warnings)
            target_folder = self._config.get_tia_folder_dispositivos()
            undo_text = f"Sync comentarios dispositivos ({plc_name})"
            result = await self._gateway.update_disp_instance_comments_batch(
                plc_name=plc_name,
                dispositivos_slot_maps=slot_maps,
                target_folder=target_folder,
                db_names=db_names,
                db_array_names=db_array_names,
                undo_text=undo_text,
            )
            applied = True
            ops = int(result.get("operations_executed", 0))
            self._progress.finish_stage(
                "apply_comentarios_disp",
                f"{ops} ops aplicadas OK",
            )
            return {
                "applied": applied,
                "operations_executed": ops,
                "warnings": warnings,
                "error": None,
            }
        except Exception as exc:
            err_msg = f"{type(exc).__name__}: {exc}"
            _logger.warning(
                f"[{plc_name}] apply_comentarios_disp fallo (commit ya aplicado): {err_msg}"
            )
            self._progress.finish_stage(
                "apply_comentarios_disp",
                f"Fallo: {err_msg}",
            )
            return {
                "applied": False,
                "operations_executed": 0,
                "warnings": [],
                "error": err_msg,
            }

    # ──────────────────────────────────────────────────────────────────
    # N_MAX: diff y ops (NUEVO en esta release)
    # ──────────────────────────────────────────────────────────────────

    def _compute_nmax_ops_for_apply(
        self, plc_name: str, tags_base: Path
    ) -> list[dict[str, Any]]:
        """Calcula las ops ``update_user_constant_value`` para N_MAX.

        Reutiliza ``_extract_nmax_diff`` para leer TIA + AppState, y
        ``DispCalculateConstantsDiffUseCase.calculate_nmax_diff`` para
        emitir las ops. Se ejecuta en el hilo del caller (no
        necesita ``asyncio.to_thread`` porque no hay I/O).
        """
        nmax_block = self._extract_nmax_diff(tags_base)
        # Re-leer el estado actual desde el bloque (es idempotente).
        current = nmax_block["current"]
        desired = nmax_block["desired"]
        nmax_table = self._config.get_global_config_table_name()
        return DispCalculateConstantsDiffUseCase.calculate_nmax_diff(
            plc_name=plc_name,
            config_table_name=nmax_table,
            current_state=current,
            desired_state=desired,
        )

    def _extract_nmax_diff(self, tags_base: Path) -> dict[str, Any]:
        """Calcula el diff de N_MAX entre el TIA (export bulk) y ``AppState.dimensiones``.

        Las N_MAX son PlcUserConstant de la tabla
        ``000_Config_Dispositivos`` que **siempre existen** en TIA
        (son las 6 dimensiones: ED, EA, SA, V, M, M_VF). No se crean
        ni se eliminan: solo se **modifica su valor**. Por tanto, los
        \u00fanicos estados posibles son:

          - ``actualizar``  : el valor cambia X \u2192 Y.
          - ``sin_cambios`` : el valor coincide.
        """
        from areas.alimentacion.infrastructure.xml.disp_tag_table_parser import SimaticMLTagParser

        nmax_folder = self._config.get_tia_folder_nmax()
        nmax_table = self._config.get_global_config_table_name()
        xml_path = tags_base / nmax_folder / f"{nmax_table}.xml"

        # 1. Estado actual en TIA.
        current: dict[str, int] = {}
        if xml_path.is_file():
            try:
                current = SimaticMLTagParser.parse_user_constants(xml_path)
            except Exception as e:
                _logger.error(f"[N_MAX] Parse FAIL {xml_path}: {e}")
        else:
            _logger.warning(
                f"[N_MAX] XML esperado no encontrado: {xml_path}"
            )

        # 2. Estado deseado desde AppState.dimensiones (data-driven).
        d = self._state.dimensiones
        desired: dict[str, int] = {}
        for nmax_name in self._config.list_nmax_active():
            v = d.get(nmax_name)
            if v is None:
                v = 0
            desired[nmax_name] = int(v)

        # 3. Diff unificado: las N_MAX siempre existen en ambos lados.
        todos: list[dict[str, Any]] = []
        for name in desired.keys():
            cur_val = current.get(name)
            des_val = desired[name]
            if cur_val is not None and cur_val == des_val:
                status = "sin_cambios"
            else:
                status = "actualizar"
            todos.append({
                "name": name,
                "actual": cur_val,
                "nuevo": des_val,
                "status": status,
            })

        return {
            "current": current,
            "desired": desired,
            "todos": todos,
            "summary": {
                "actualizar": sum(
                    1 for r in todos if r["status"] == "actualizar"
                ),
                "sin_cambios": sum(
                    1 for r in todos if r["status"] == "sin_cambios"
                ),
                "total": len(todos),
            },
        }

    # ──────────────────────────────────────────────────────────────────
    # Diff de devices (helpers internos)
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_diff_readonly(
        tags_base: Path,
        desired_state_per_table: dict[str, dict[str, str]],
    ) -> tuple[
        dict[str, list[str]],
        dict[str, list[str]],
        dict[str, tuple[str, str]],
        dict[str, dict[str, str]],
    ]:
        """Calcula el diff de devices en modo read-only (no modifica XML)."""
        base_state_per_table: dict[str, dict[str, str]] = {}
        for table_key in desired_state_per_table.keys():
            # ``XmlTarget`` resuelve la ruta con fallback rglob integrado
            # (TIA a veces exporta con ``keep_folder_structure`` y crea
            # subdirs como ``Tags/``; el helper lo absorbe).
            try:
                xml_path = XmlTarget(tags_base, table_key).path
            except FileNotFoundError:
                continue
            modifier = TagTableModifier(xml_path)
            table_constants: dict[str, str] = {}
            for value_str, plc_tag in (
                modifier.read_user_constants_with_uids().items()
            ):
                if value_str and plc_tag:
                    table_constants[value_str] = plc_tag
            if table_constants:
                base_state_per_table[table_key] = table_constants

        added_per_table: dict[str, list[str]] = {}
        removed_per_table: dict[str, list[str]] = {}
        renamed_per_table: dict[str, tuple[str, str]] = {}

        for table_key, desired in desired_state_per_table.items():
            base = base_state_per_table.get(table_key, {})
            base_values = set(base.keys())
            desired_values = set(desired.keys())
            added = sorted(desired_values - base_values)
            removed = sorted(base_values - desired_values)
            renamed: dict[str, tuple[str, str]] = {}
            for uid in base_values & desired_values:
                if base[uid] != desired[uid]:
                    renamed[f"{table_key}:{uid}"] = (base[uid], desired[uid])
            if added:
                added_per_table[table_key] = added
            if removed:
                removed_per_table[table_key] = removed
            renamed_per_table.update(renamed)

        return (
            added_per_table,
            removed_per_table,
            renamed_per_table,
            base_state_per_table,
        )


    def _resolve_tia_folder(self, table_key: str) -> str:
        """Resuelve la carpeta TIA donde debe guardarse el XML de ``table_key``.

        El wrapper ``import_plc_tags`` usa la ruta del archivo XML para
        determinar en que carpeta del PLC se importa la tabla. Si la
        ruta no coincide con la carpeta original, TIA interpreta que
        es una tabla nueva y falla con "la tabla ya existe".

        Returns:
            Nombre de la carpeta TIA (de ``config.json: tia_folders``)
            correspondiente a esta tabla.
        """
        nmax_table = self._config.get_global_config_table_name()
        if table_key == nmax_table:
            # Tabla N_MAX (000_Config_Dispositivos) -> carpeta 000_Sistema.
            return self._config.get_tia_folder_nmax()
        # Tablas de devices (2000_Disp_*) -> carpeta 2000_Dispositivos.
        return self._config.get_tia_folder_dispositivos()

    def _selective_table_names(self) -> list[str]:
        """Lista las tablas que el sync dispositivos toca (data-driven)."""

        seen: set[str] = set()
        result: list[str] = []
        for hw_type in self._config.list_hw_types_active():
            tag_table = self._config.get_tag_table_name(hw_type)
            if tag_table and tag_table not in seen:
                seen.add(tag_table)
                result.append(tag_table)
        nmax_table = self._config.get_global_config_table_name()
        if nmax_table and nmax_table not in seen:
            seen.add(nmax_table)
            result.append(nmax_table)
        return result

    def _build_desired_state_from_app(self) -> dict[str, dict[str, str]]:
        """Construye ``{tag_table: {uid: plc_tag}}`` desde el ``AppState``.

        Itera ``ConfigManager.list_hw_types_active()`` (data-driven)
        y usa ``get_app_state_attr_for(hw)`` para acceder a la lista
        de dispositivos del estado.
        """
        result: dict[str, dict[str, str]] = {}
        for hw_type in self._config.list_hw_types_active():
            tag_table = self._config.get_tag_table_name(hw_type)
            if tag_table is None:
                continue
            attr_name = self._config.get_app_state_attr_for(hw_type)
            if attr_name is None:
                continue
            devices = getattr(self._state, attr_name, [])
            table_dict: dict[str, str] = {}
            for device in devices:
                numero = int(getattr(device, "numero", 0) or 0)
                plc_tag = str(getattr(device, "plc_tag", "") or "")
                if numero > 0 and plc_tag:
                    table_dict[str(numero)] = plc_tag
            if table_dict:
                result[tag_table] = table_dict
        return result


__all__ = ["DispSyncInstancesUseCase"]
