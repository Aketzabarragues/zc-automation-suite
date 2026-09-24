"""FB de area: sincronizacion transaccional de dispositivos vs PLC.

State machine sobre el helper ``disp_Sincronizar`` (areas/alimentacion/
helpers/disp/disp_Sincronizar.py). El helper expone funciones independientes
(``exportar_tags``, ``compute_diff``, ``tx_a_nmax_renames``, etc.) que
reciben un ``DispSyncContext`` y mutan sus campos. **Aqui en el FB vive
la state machine**: el orden de las 11 llamadas, el mapping step ->
funcion del helper, y la instanciacion del ctx.

Cada step del FB ejecuta una funcion real del helper contra un
``DispSyncContext`` compartido. El progressbar muestra 11 etapas
con trabajo y duracion reales.

Hereda directo de ``FunctionBase`` (no del template). Zona 0 con 4 deps
comunes + 1 especifica.

Runtime params via ``start(**kwargs)``:
  - ``plc_name`` (str): nombre del PLC destino. Obligatorio.

El ``self.result`` se popula con la shape legacy esperada por la SPA::

    {
      'success':         True,
      'message':         str,
      'operations':      int,
      'n_max_updates':   int,
      'post_sync_preview': dict | None,
      'compile_ok':      bool,
      'compile_error':   str | None,
      'comments_sync':   dict,
    }

Steps (11, mismo orden que el legacy ``ejecutar_transaccion``):
  - exportar_tags
  - compute_diff
  - preparar_ops
  - tx_a_nmax_renames
  - wait_consolidation
  - exportar_post_tx_a
  - editar_xmls_offline
  - tx_b_devices
  - compilar_bloques
  - aplicar_comentarios
  - post_preview
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.composition.plc_function_base import FunctionBase
from core.helpers.tia import dispatch_async, validate_execute_batch_result
from core.runtime.app_state import AppState, get_app_state
from areas.alimentacion.helpers.build_cache import DEFAULT_BUILD_CACHE_ROOT

logger = logging.getLogger(__name__)


# Sleep para que TIA consolide internamente entre Tx A y Tx B.
TIA_CONSOLIDATION_SLEEP_S: float = 2.0


class FunctionDispSincronizar(FunctionBase):
    """FB que sincroniza dispositivos contra TIA (11 etapas transaccionales)."""

    # ==================================================================
    # CONFIGURACION ESTATICA DEL FB
    # ==================================================================

    # Sync completo: 2 transacciones TIA + compile + apply comentarios
    # + post preview. TIA V21 puede tardar varios minutos para un PLC
    # con 200+ bloques y 6 DBs de dispositivos redimensionados.
    STEP_TIMEOUT_S: float = 600.0

    # Tabla declarativa de stages. Cada tupla: (idx, "nombre_step",
    # "atributo_metodo_en_el_FB"). El ``run_step`` dispatcha contra
    # esta tabla en vez de un ``match``/``case`` inline, para que el
    # flujo sea legible arriba de la clase y los tests puedan
    # mockear ``fb._stage_N_<nombre>`` directamente.
    #
    # Convencion:
    #   - ``idx`` correlativo, 1-based (10 steps normales + 99 para
    #     ``post_preview`` que se ejecuta tras la transaccion).
    #   - ``nombre_step`` debe coincidir con ``self.steps[idx]["nombre"]``
    #     (registrado en __init__). Si cambias uno, cambia el otro.
    #   - ``atributo_metodo`` es un metodo del FB (no externo): un cambio
    #     de signatura requiere actualizar este registro.
    STAGES: list[tuple[int, str, str]] = [
        (1,  "Exportar etiquetas",                 "_stage_1_exportar_tags"),
        (2,  "Calcular diferencias de dispositivos", "_stage_2_compute_diff"),
        (3,  "Preparar operaciones",                "_stage_3_preparar_ops"),
        (4,  "Aplicar N_MAX y renombres",          "_stage_4_tx_a_nmax_renames"),
        (5,  "Esperar consolidación TIA",          "_stage_5_wait_consolidation"),
        (6,  "Re-exportar etiquetas",              "_stage_6_exportar_post_tx_a"),
        (7,  "Editar archivos XML",                "_stage_7_editar_xmls_offline"),
        (8,  "Aplicar dispositivos",               "_stage_8_tx_b_devices"),
        (9,  "Compilar bloques",                   "_stage_9_compilar_bloques"),
        (10, "Aplicar comentarios",                "_stage_10_aplicar_comentarios"),
        (11, "Generar preview post-sincronización", "_stage_11_disp_post_preview"),
    ]

    # ==================================================================
    # CONSTRUCTOR
    # ==================================================================

    def __init__(
        self,
        nombre: str = "disp_sincronizar",
        titulo: str = "Sincronizar dispositivos contra PLC",
        steps: list[dict[str, Any]] | None = None,
        tracker: Any = None,
        # ── ZONA 0: deps comunes ──
        config_manager: Any = None,
        tia_client: Any = None,
        build_cache: Any = None,
        # ── Deps especificas de este FB ──
        app_state: AppState | None = None,
    ) -> None:
        super().__init__(
            nombre=nombre,
            titulo=titulo,
            steps=steps if steps is not None else [
                {"nombre": "Exportar etiquetas"},
                {"nombre": "Calcular diferencias de dispositivos"},
                {"nombre": "Preparar operaciones"},
                {"nombre": "Aplicar N_MAX y renombres"},
                {"nombre": "Esperar consolidación TIA"},
                {"nombre": "Re-exportar etiquetas"},
                {"nombre": "Editar archivos XML"},
                {"nombre": "Aplicar dispositivos"},
                {"nombre": "Compilar bloques"},
                {"nombre": "Aplicar comentarios"},
                {"nombre": "Generar preview post-sincronización"},
            ],
            tracker=tracker,
        )
        # ZONA 0: deps inyectadas.
        self._config = config_manager
        self._tia_client = tia_client
        self._build_cache_root: Path = build_cache or DEFAULT_BUILD_CACHE_ROOT
        # Deps especificas.
        self._state: AppState = (
            app_state if app_state is not None else get_app_state()
        )
        # ZONA 3: estado entre ticks.
        self._plc_name: str = ""
        # DispSyncContext compartido entre los 11 ticks. Se reinicializa
        # en cada on_start() para no arrastrar estado del run anterior.
        self._ctx: Any = None

    # ==================================================================
    # HOOK 1: on_start  (ZONA 3: validar params + crear ctx)
    # ==================================================================

    def on_start(self, **params: Any) -> None:
        """Validar deps inyectadas + capturar plc_name + crear ctx."""
        if self._config is None:
            raise RuntimeError(
                "FunctionDispSincronizar requiere "
                "config_manager. Inyectalo en el constructor."
            )
        if self._tia_client is None:
            raise RuntimeError(
                "FunctionDispSincronizar requiere "
                "tia_client. Inyectalo en el constructor."
            )
        plc_name = params.get("plc_name")
        if not plc_name:
            raise ValueError(
                "FunctionDispSincronizar.start(plc_name=...) "
                "es obligatorio"
            )
        self._plc_name = str(plc_name)

        # Crear el DispSyncContext que las 11 funciones iran mutando.
        # Lazy import para evitar ciclo con helpers/disp/.
        self._ctx = DispSyncContext(
            plc_name=self._plc_name,
            tia_client=self._tia_client,
            config_manager=self._config,
            app_state=self._state,
            build_cache_root=self._build_cache_root,
        )

        logger.debug(
            f"[{self.nombre}] Iniciando sync transaccional para "
            f"{self._plc_name} (11 etapas)"
        )

    # ==================================================================
    # HOOK 2: run_step  (ZONA 4: state machine -> dispatch al helper)
    # ==================================================================

    async def run_step(self, idx: int, **params: Any) -> str:
        """Dispatch del FB step ``idx`` a la funcion del helper ``disp_Sincronizar``.

        Aqui vive la state machine: cada step del FB llama a UNA
        funcion del helper (``exportar_tags``, ``compute_diff``, etc.)
        contra el ``DispSyncContext`` compartido. El ``case`` es
        explicito (no dict.get dispatch) para que sea visible en stack
        traces cuando algo falla.
        """
        if self._ctx is None:
            raise RuntimeError(
                "DispSyncContext no inicializado. on_start() no se ejecuto "
                "(o el FB no recibio un plc_name valido)."
            )

        step_nombre = self.steps[idx]["nombre"]
        # Dispatch declarativo via tabla ``STAGES``: el orden y los
        # nombres de los 11 stages se declaran arriba de la clase.
        # Asi el flujo del FB es visible de un vistazo (modo SFC) y los
        # tests pueden mockear ``fb._stage_N_<nombre>`` directamente sin
        # parchear el ``match`` interno.
        #
        # El lookup es por ``nombre`` (no por ``idx``) porque
        # ``FunctionBase._step_ejecutar`` pasa ``idx`` 0-indexed sobre
        # ``self.steps``. El ``idx`` de la tabla STAGES es 1-based y
        # solo se usa para logging legible ("paso 3/10").
        for _s_idx, s_nombre, s_attr in self.STAGES:
            if s_nombre == step_nombre:
                handler = getattr(self, s_attr)
                await handler()
                # Resumen legible del step que acaba de correr (aparece en la SPA).
                return _step_summary(self._ctx, s_nombre)
        raise ValueError(
            f"step {idx} ({step_nombre!r}) no esta en STAGES "
            f"de FunctionDispSincronizar"
        )

    # ==================================================================
    # HOOK 3: on_finish  (ZONA 5: vuelco del result desde el ctx)
    # ==================================================================

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` con la shape legacy que espera la SPA.

        Lee los resultados finales del ``DispSyncContext``.
        """
        if self._ctx is None:
            # Error temprano: deps no inyectadas o plc_name ausente.
            self.result = {
                "success": False,
                "message": "FB no llego a ejecutar (deps no inyectadas "
                           "o plc_name no proporcionado)",
                "operations": 0,
                "n_max_updates": 0,
                "post_sync_preview": None,
                "compile_ok": False,
                "compile_error": "FB no ejecutado",
                "comments_sync": None,
            }
            return

        # Componer el shape legacy desde el ctx (mismo calculo que el
        # helper monolitico: operations_executed = N_MAX + devices).
        operations_executed = (
            self._ctx.nmax_result.get("operations_executed", 0)
            + self._ctx.devices_result.get("operations_executed", 0)
        )
        details = (
            self._ctx.nmax_result.get("details", [])
            + self._ctx.devices_result.get("details", [])
        )
        self.result = {
            "success": True,
            "message": (
                f"Inyeccion completada. Detalles: {details}"
            ),
            "operations": operations_executed,
            "n_max_updates": len(self._ctx.nmax_ops),
            "post_sync_preview": self._ctx.post_sync_preview,
            "compile_ok": self._ctx.compile_ok,
            "compile_error": self._ctx.compile_error,
            "comments_sync": self._ctx.comments_result,
        }

        # Log de cierre, igual que el helper monolitico.
        compile_label = (
            "OK" if self._ctx.compile_ok else "con errores"
        )
        logger.debug(
            f"[{self.nombre}] sync completo para "
            f"{self._ctx.plc_name}: {operations_executed} ops "
            f"({len(self._ctx.nmax_ops)} N_MAX), "
            f"compile={compile_label}"
        )

    # ==================================================================
    # Stages del FB (ZONA 4: 11 metodos privados numerados).
    #
    # Cada ``_stage_N_<nombre>`` corresponde a UNA entrada de la tabla
    # ``STAGES`` arriba. Si cambias el flujo del stage, cambia la
    # tabla tambien.
    # ==================================================================

    async def _stage_1_exportar_tags(self) -> None:
        """Limpia sync/ y exporta las tablas selectivas al snapshot export."""
        from areas.alimentacion.helpers.build_cache import build_cache

        disp_ctx = build_cache(root=self._ctx.build_cache_root).dispositivos
        # Borra ``sincronizar/{variables,bloques}/{export,modified}``.
        # Conserva ``preview/`` (puede contener artefactos del operario).
        disp_ctx.clean_sincronizar()
        # ``sync_variables_export`` = destino de la exportacion. ``modified``
        # se rellena en ``_stage_7_editar_xmls_offline`` con copytree filtrado.
        self._ctx.tags_base = disp_ctx.sync_variables_export
        self._ctx.tags_modified = disp_ctx.sync_variables_modified
        self._ctx.selective_tables = _selective_table_names(self._ctx.config_manager)
        logger.info(
            f"[{self._ctx.plc_name}] sync export dir: {self._ctx.tags_base}"
        )
        logger.info(
            f"[{self._ctx.plc_name}] sync modified dir (rellenado en stage 7): "
            f"{self._ctx.tags_modified}"
        )
        batch_result = await dispatch_async(
            self._ctx.tia_client,
            "execute_batch",
            {
                "operations": [
                    {
                        "command": "export_plc_tags_xml",
                        "args": {
                            "plc_name": self._ctx.plc_name,
                            "target_dir": str(self._ctx.tags_base),
                            "table_names": self._ctx.selective_tables,
                        },
                    }
                ],
            },
        )
        validate_execute_batch_result(
            batch_result["result"],
            undo_text="Exportar etiquetas",
            plc_name=self._ctx.plc_name,
            log=logger,
        )

    async def _stage_2_compute_diff(self) -> None:
        """Calcula el diff entre los XMLs exportados y el AppState (read-only).

        Migrado sept-2026: usa ``compute_diff_table`` por hw_type
        (funcion pura del nuevo helper). Mantiene el shape del ctx
        (``desired_state_per_table`` etc.) para compatibilidad con
        ``_stage_3_preparar_ops`` y siguientes.
        """
        assert self._ctx.tags_base is not None, (
            "compute_diff requiere exportar_tags previo"
        )
        from areas.alimentacion.helpers.disp.disp_generate_preview import (
            compute_diff_table,
        )

        added_per_table: dict[str, list[str]] = {}
        removed_per_table: dict[str, list[str]] = {}
        renamed_per_table: dict[str, tuple[str, str]] = {}
        base_state_per_table: dict[str, dict[str, str]] = {}
        desired_state_per_table: dict[str, dict[str, str]] = {}

        def _all_diffs() -> None:
            for hw in self._ctx.config_manager.list_hw_types_active():
                cfg = self._ctx.config_manager.get_dispositivo_config(hw)
                if cfg is None:
                    continue
                # El sync exporta con ``keep_folder_structure=True``
                # (Stage 7 necesita la subcarpeta para hacer UPDATE
                # recursivo en TIA V21), asi que el XML vive en
                # ``tags_base/<tia_folder>/<tag_table>.xml``.
                tia_folder = _resolve_tia_folder(
                    self._ctx.config_manager, hw
                )
                xml_path = (
                    self._ctx.tags_base / tia_folder / f"{cfg.tag_table}.xml"
                )
                devices = self._ctx.app_state.get_devices(hw)
                diff = compute_diff_table(
                    table_name=cfg.tag_table,
                    desired_devices=devices,
                    xml_path=xml_path,
                )
                desired_state_per_table[cfg.tag_table] = diff.desired
                base_state_per_table[cfg.tag_table] = diff.base
                if diff.added:
                    added_per_table[cfg.tag_table] = diff.added
                if diff.removed:
                    removed_per_table[cfg.tag_table] = diff.removed
                if diff.renamed:
                    renamed_per_table.update({
                        f"{cfg.tag_table}:{uid}": v
                        for uid, v in diff.renamed.items()
                    })

        await asyncio.to_thread(_all_diffs)

        self._ctx.desired_state_per_table = desired_state_per_table
        self._ctx.base_state_per_table = base_state_per_table
        self._ctx.added_per_table = added_per_table
        self._ctx.removed_per_table = removed_per_table
        self._ctx.renamed_per_table = renamed_per_table

    async def _stage_3_preparar_ops(self) -> None:
        """Calcula nmax_ops + rename_ops + device_changes para los handlers."""
        assert self._ctx.tags_base is not None, (
            "preparar_ops requiere exportar_tags previo"
        )
        self._ctx.nmax_ops = _compute_nmax_ops_for_apply(
            self._ctx.tags_base, self._ctx.config_manager, self._ctx.app_state,
        )

        # Rename ops (shape legacy: {table_name, current_name, new_name}).
        # Tx A las pasa separadas al handler commit_user_constants_online.
        self._ctx.rename_ops = [
            {
                "table_name": uid.split(":", 1)[0],
                "current_name": old,
                "new_name": new,
            }
            for uid, (old, new) in self._ctx.renamed_per_table.items()
        ]

        # Device changes: lista de {table_name, tia_folder, adds, removes}.
        # ``tia_folder`` resuelve la subcarpeta donde vive el XML del device
        # dentro de modified/variables (e.g. "PLC_Tags" o ""). Se necesita
        # tanto en ``editar_xmls_offline`` (para encontrar el XML a editar)
        # como en el copytree filtrado (Stage 7).
        self._ctx.device_changes = []
        nmax_table = self._ctx.config_manager.get_global_config_table_name()
        for table_key in self._ctx.selective_tables:
            if table_key == nmax_table:
                continue  # N_MAX no es device change.
            adds = [
                {"uid": uid, "plc_tag": self._ctx.desired_state_per_table[table_key][uid]}
                for uid in self._ctx.added_per_table.get(table_key, [])
                if uid in self._ctx.desired_state_per_table[table_key]
            ]
            # ``removes`` debe ser lista de strings (uids), NO lista de dicts:
            # ``PlcUserConstantModifier.remove_user_constants`` espera ``set[str]``.
            # ``adds`` si es lista de dicts (``{"uid", "plc_tag"}``) porque
            # ``add_user_constants_by_table`` los desempaqueta como name+value.
            removes = list(self._ctx.removed_per_table.get(table_key, []))
            if adds or removes:
                self._ctx.device_changes.append({
                    "table_name": table_key,
                    "tia_folder": _resolve_tia_folder(self._ctx.config_manager, table_key),
                    "adds": adds,
                    "removes": removes,
                })

    async def _stage_4_tx_a_nmax_renames(self) -> None:
        """Tx A (online puro): dispatch de N_MAX + renames contra TIA."""
        assert self._ctx.tags_base is not None, (
            "tx_a_nmax_renames requiere exportar_tags previo"
        )
        if self._ctx.nmax_ops or self._ctx.rename_ops:
            # Construir la lista de ops para ``execute_transactional_batch``.
            # Cada op es una pareja ``(command, args)`` que el batch
            # dispatche bajo una sola ``start_transaction`` TIA.
            operations: list[dict[str, Any]] = []
            for nmax_op in self._ctx.nmax_ops:
                operations.append({
                    "command": "update_user_constant_value",
                    "args": {
                        "plc_name": self._ctx.plc_name,
                        "table_name": nmax_op["table_name"],
                        "constant_name": nmax_op["constant_name"],
                        "new_value": nmax_op["new_value"],
                    },
                })
            for rename_op in self._ctx.rename_ops:
                operations.append({
                    "command": "update_user_constant_name",
                    "args": {
                        "plc_name": self._ctx.plc_name,
                        "table_name": rename_op["table_name"],
                        "current_name": rename_op["current_name"],
                        "new_name": rename_op["new_name"],
                    },
                })
            logger.info(
                f"[{self._ctx.plc_name}] Tx A (online): "
                f"{len(self._ctx.nmax_ops)} N_MAX + "
                f"{len(self._ctx.rename_ops)} renames via batch"
            )
            nmax_result = await dispatch_async(
                self._ctx.tia_client,
                "execute_transactional_batch",
                {
                    "undo_text": "Sync N_MAX + renames",
                    "operations": operations,
                },
                timeout_s=120.0,
            )
            if not nmax_result.get("ok"):
                raise RuntimeError(
                    f"Tx A (N_MAX renames) fallo: {nmax_result.get('error')}"
                )
            self._ctx.nmax_result = nmax_result
        else:
            self._ctx.nmax_result = {
                "success": True,
                "operations_executed": 0,
                "details": [],
            }

    async def _stage_5_wait_consolidation(self) -> None:
        """Espera 2s para que TIA consolide internamente tras Tx A."""
        await asyncio.to_thread(time.sleep, TIA_CONSOLIDATION_SLEEP_S)

    async def _stage_6_exportar_post_tx_a(self) -> None:
        """Relee los XMLs de los devices tras Tx A (estado ya consolidado)."""
        assert self._ctx.tags_base is not None, (
            "exportar_post_tx_a requiere exportar_tags previo"
        )
        # Re-exportar solo las 6 tablas de devices (NO la N_MAX: ya
        # consolidada en Tx A). El destino es ``sync_variables_export``
        # (snapshot limpio); ``modified`` lo rellena Stage 7 con copytree.
        from areas.alimentacion.helpers.build_cache import build_cache
        disp_ctx = build_cache(root=self._ctx.build_cache_root).dispositivos
        logger.info(
            f"[{self._ctx.plc_name}] sync export re-read post-TxA: "
            f"{disp_ctx.sync_variables_export}"
        )
        batch_result = await dispatch_async(
            self._ctx.tia_client,
            "execute_batch",
            {
                "operations": [
                    {
                        "command": "export_plc_tags_xml",
                        "args": {
                            "plc_name": self._ctx.plc_name,
                            "target_dir": str(disp_ctx.sync_variables_export),
                            "table_names": [dc["table_name"] for dc in self._ctx.device_changes],
                        },
                    }
                ],
            },
        )
        validate_execute_batch_result(
            batch_result["result"],
            undo_text="Re-exportar etiquetas (post Tx A)",
            plc_name=self._ctx.plc_name,
            log=logger,
        )

    async def _stage_7_editar_xmls_offline(self) -> None:
        """Copia filtrada sync export->modified + edita XMLs offline."""
        assert self._ctx.tags_base is not None, (
            "editar_xmls_offline requiere exportar_tags previo"
        )
        await asyncio.to_thread(
            _copy_and_edit_offline,
            self._ctx.build_cache_root, self._ctx.device_changes,
        )

    async def _stage_8_tx_b_devices(self) -> None:
        """Tx B (offline puro): dispatch de import_plc_tags_xml contra TIA."""
        assert self._ctx.tags_base is not None, (
            "tx_b_devices requiere exportar_tags previo"
        )
        if self._ctx.device_changes:
            # NO pasamos ``target_folder`` (TIA Portal V21 escanea
            # ``sync/variables/modified`` recursivamente: si encuentra la
            # estructura interna del PLC (e.g.
            # ``2000_Dispositivos/2000_Disp_ED.xml``), hace match
            # automatico con su PLC tag interno y dispara UPDATE (no
            # CREATE). Pasar ``target_folder`` con un valor explicito
            # fuerza el match a una sola carpeta, lo rompe y causa
            # ``CommitOnDispose``. Import a RAIZ con ``target_folder=""``
            # (default del handler) es el camino feliz.
            from areas.alimentacion.helpers.build_cache import build_cache
            disp_ctx = build_cache(root=self._ctx.build_cache_root).dispositivos
            modified_dir = disp_ctx.sync_variables_modified
            logger.info(
                f"[{self._ctx.plc_name}] Tx B (devices offline): "
                f"import_dir={modified_dir}"
            )
            # Batch con 1 sola op: ``import_plc_tags_xml`` masivo.
            # El batch abre su propia ``start_transaction`` y rollback si falla.
            devices_result = await dispatch_async(
                self._ctx.tia_client,
                "execute_transactional_batch",
                {
                    "undo_text": "Sync devices (offline)",
                    "operations": [{
                        "command": "import_plc_tags_xml",
                        "args": {
                            "plc_name": self._ctx.plc_name,
                            "import_dir": str(modified_dir),
                            "target_folder": "",
                        },
                    }],
                },
                timeout_s=180.0,
            )
            if not devices_result.get("ok"):
                raise RuntimeError(
                    f"Tx B (devices offline) fallo: {devices_result.get('error')}"
                )
            self._ctx.devices_result = devices_result
        else:
            self._ctx.devices_result = {
                "success": True,
                "operations_executed": 0,
                "details": [],
            }

    async def _stage_9_compilar_bloques(self) -> None:
        """Compila los DBs afectados (fuera de tx; el commit ya esta aplicado)."""
        affected_dbs = _get_affected_dbs_for_compile(self._ctx.config_manager)
        try:
            compile_result = await dispatch_async(
                self._ctx.tia_client,
                "compile_blocks",
                {"plc_name": self._ctx.plc_name, "block_names": affected_dbs},
                timeout_s=120.0,
            )
            if not compile_result.get("ok"):
                self._ctx.compile_ok = False
                self._ctx.compile_error = (
                    compile_result.get("error", "compile_blocks fallo")
                )
                return
            data = compile_result.get("result") or {}
            compiled = data.get("compiled", [])
            errors = data.get("errors", [])
            any_had_errors = any(c.get("had_errors") for c in compiled)
            if any_had_errors or errors:
                self._ctx.compile_ok = False
                n_had = sum(1 for c in compiled if c.get("had_errors"))
                n_err = len(errors)
                n_not_found = len(data.get("not_found", []))
                self._ctx.compile_error = (
                    f"TIA reporta errores de compilacion: "
                    f"{n_had} bloque(s) con errores, "
                    f"{n_err} excepcion(es), "
                    f"{n_not_found} no encontrado(s). "
                    f"Revisa el proyecto en TIA Portal: los DBs "
                    f"pueden haber quedado con tamano inconsistente "
                    f"tras el resize de N_MAX."
                )
                logger.warning(
                    f"[{self._ctx.plc_name}] Compilacion parcial con errores "
                    f"(commit ya aplicado): {compile_result}"
                )
            else:
                n_skipped = len(data.get("skipped_unchanged", []))
                logger.info(
                    f"[{self._ctx.plc_name}] Compilacion OK "
                    f"({len(compiled)} compilados, "
                    f"{n_skipped} saltados por consistentes)."
                )
        except Exception as exc:
            self._ctx.compile_ok = False
            self._ctx.compile_error = f"Excepcion durante la compilacion: {exc}"
            logger.warning(
                f"[{self._ctx.plc_name}] Compilacion fallo (commit ya aplicado): {exc}"
            )

    async def _stage_10_aplicar_comentarios(self) -> None:
        """Stage 10 del sync: aplica los comentarios por instancia a los 6 DBs de disp.

        Flujo (replica ``apply_disp_comments`` que vivia en
        ``helpers/sync/disp_comment_sync.py``, borrado al refactorizar A.4
        para consolidarlo aqui):

          1. Validar AppState.
          2. Construir slot_maps (disp_build_slot_maps).
          3. Limpiar modified/bloques/ (defensivo).
          4. Exportar 6 DBs a exports/bloques/ (1 dispatch por DB).
          5. Copytree exports/bloques/ -> modified/bloques/.
          6. Una sola tx transaccional con los 6 imports (atomicidad).
          7. Normalizar return shape en ``self._ctx.comments_result``.

        Si TIA V21 falla en cualquiera de los 6 imports, rollback atomico.
        """
        from areas.alimentacion.helpers.build_cache import build_cache
        from areas.alimentacion.data.data_disp_slot_map import disp_build_slot_maps

        # ── 1. Validar AppState ──
        if not self._ctx.app_state.all_devices():
            warning = (
                "AppState esta vacio. Cargue primero el Excel con "
                "POST /api/v1/excel/upload."
            )
            self._ctx.comments_result = {
                "plc_name": self._ctx.plc_name,
                "success": True,
                "applied": True,
                "operations_executed": 0,
                "summary": {"disp_dbs_updated": 0, "total_ops": 0},
                "details": [],
                "warnings": [warning],
            }
            return

        # ── 2. Construir slot_maps ──
        slot_maps_data = disp_build_slot_maps(self._ctx.app_state, self._ctx.config_manager)
        slot_maps = slot_maps_data.slot_maps
        db_names = slot_maps_data.db_names
        db_array_names = slot_maps_data.db_array_names
        warnings = list(slot_maps_data.warnings)

        target_folder = self._ctx.config_manager.get_tia_folder_dispositivos()

        # ── 3. Resolver paths de bloques ──
        # Stage 1 ya limpio ``sincronizar/`` con ``clean_sincronizar()``;
        # no hace falta ``rmtree`` + ``mkdir`` aqui.
        disp_ctx = build_cache(root=self._ctx.build_cache_root).dispositivos
        exports_bloques = disp_ctx.sync_bloques_export
        modified_bloques = disp_ctx.sync_bloques_modified
        logger.info(
            f"[{self._ctx.plc_name}] sync bloques: "
            f"exports={exports_bloques}, modified={modified_bloques}"
        )

        # ── 4. Export UNA VEZ de los 6 DBs a exports/bloques/ ──
        # Una sola llamada execute_batch agrupa los 6 export_block
        # (mismo target_dir, distintos block_name). Modo read-only.
        # IMPORTANTE: ``keep_folder_structure=True`` para preservar la
        # subcarpeta TIA (e.g. ``<exports>/2000_Dispositivos/DB.s7dcl``).
        # El stage 10 hace ``import_block`` con ``target_folder=None`` =
        # recursivo, y TIA V21 hace match UPDATE preservando el subpath
        # relativo dentro del ``import_root_directory``. Si el .s7dcl
        # queda FLAT, el relative path es vacio y TIA no sabe en que
        # subcarpeta del PLC aplicar el UPDATE.
        batch_result = await dispatch_async(
            self._ctx.tia_client,
            "execute_batch",
            {
                "operations": [
                    {
                        "command": "export_block",
                        "args": {
                            "plc_name": self._ctx.plc_name,
                            "block_name": db_name,
                            "target_dir": str(exports_bloques),
                            "keep_folder_structure": True,
                        },
                    }
                    for hw_type, db_name in db_names.items()
                ],
            },
        )
        validate_execute_batch_result(
            batch_result["result"],
            undo_text="Exportar 6 DBs (sincronizar/bloques/export)",
            plc_name=self._ctx.plc_name,
            log=logger,
        )

        # ── 5. Copytree exports/bloques/ -> modified/bloques/ ──
        if exports_bloques.exists():
            shutil.copytree(
                str(exports_bloques),
                str(modified_bloques),
                dirs_exist_ok=True,
            )

        # 6 commits inline (1 por hw_type) sobre los archivos exportados,
        # y 1 solo ``import_block`` con ``import_dir=modified_bloques``
        # para que TIA importe todos los bloques en una operacion atomica.
        # ``target_folder=""`` (default): TIA escanea recursivamente.
        from core.helpers.simatic_sd import commit_array_comments
        details: list[dict[str, Any]] = []
        total_reused = 0
        total_inserted = 0
        total_modified = 0
        ops_executed = 0
        any_modified = False
        for hw_type, db_name in db_names.items():
            slot_map = slot_maps.get(hw_type, {})
            if not slot_map:
                continue
            db_array_name = db_array_names.get(hw_type, "")
            if not db_array_name:
                continue
            from core.infrastructure.tia.tia_export_paths import SdPair
            # El stage 7 exporta con ``keep_folder_structure=True`` para
            # preservar la subcarpeta TIA
            # (``<modified>/<tia_folder_dispositivos>/DB.s7dcl``).
            # Si la carpeta de config esta vacia (``""``), ``Path / ""``
            # normaliza a la raiz -> FLAT, coherente con el export.
            dcl_path = SdPair(
                Path(modified_bloques) / target_folder, db_name,
            ).dcl
            res_path = SdPair(
                Path(modified_bloques) / target_folder, db_name,
            ).res
            result = commit_array_comments(
                dcl_path, res_path,
                array_name=db_array_name,
                slot_map={int(k): v for k, v in slot_map.items()},
                array_type="Simple",  # disp: slot 0 valido, comillas
                write_to_original=True,
            )
            modified = (
                len(result.injected)
                + len(result.updated)
                + len(result.removed)
            ) > 0
            details.append({
                "hw_type": hw_type,
                "db_name": db_name,
                "array_name": db_array_name,
                "modified": modified,
                "disp_comment_result": result.to_dict(),
            })
            ops_executed += 1
            total_reused += len(result.reused)
            total_inserted += len(result.injected)
            if modified:
                total_modified += 1
                any_modified = True

        # UN SOLO import_block al final: TIA Portal importa todos los
        # .s7dcl del directorio modified_bloques en una sola operacion.
        if any_modified:
            # WRAP en execute_transactional_batch para atomicidad semantica.
            # Si el import_block falla, TIA hace rollback de toda la tx
            # (sin aplicar cambios parciales al PLC). Antes era directo,
            # lo que dejaba al PLC en estado inconsistente si el import
            # fallaba a mitad.
            await dispatch_async(
                self._ctx.tia_client,
                "execute_transactional_batch",
                {
                    "undo_text": "Sync devices comentarios (Tx B2)",
                    "operations": [
                        {
                            "command": "import_block",
                            "args": {
                                "plc_name": self._ctx.plc_name,
                                "import_dir": str(modified_bloques),
                                "target_folder": "",  # default: TIA recursivo
                            },
                        },
                    ],
                },
                timeout_s=600.0,
            )

        self._ctx.comments_result = {
            "plc_name": self._ctx.plc_name,
            "success": True,
            "applied": True,
            "operations_executed": ops_executed,
            "summary": {
                "disp_dbs_updated": ops_executed,
                "total_ops": ops_executed,
                "total_reused": total_reused,
                "total_inserted": total_inserted,
                "total_modified": total_modified,
            },
            "details": details,
            "warnings": warnings,
        }

    async def _stage_11_disp_post_preview(self) -> None:
        """Genera el preview post-sync para que la SPA vea 'todo en sync'.

        Migrado sept-2026: usa las funciones puras
        ``compute_diff_table`` + ``compute_nmax_diff`` del nuevo
        ``disp_generate_preview.py``. Replica el flujo legacy
        (``exportar_tags`` + ``compute_devices`` + ``compute_nmax`` +
        ``build_response``) pero sin state machine externa:
        1. Limpia preview/ + re-exporta FLAT (N_MAX + 6 disp tables).
        2. ``compute_diff_table`` por hw (6 dispatchs).
        3. ``compute_nmax_diff`` (1 dispatch).
        4. Compone ``post_sync_preview`` con shape legacy.
        """
        from pathlib import Path

        from areas.alimentacion.helpers.build_cache import build_cache
        from areas.alimentacion.helpers.disp.disp_generate_preview import (
            compute_diff_table,
            compute_nmax_diff,
        )
        from core.helpers.simatic_ml import PlcUserConstantParser

        cm = self._ctx.config_manager
        state = self._ctx.app_state

        try:
            # 1/4. Limpia preview/ + re-exporta FLAT.
            disp_ctx = build_cache(root=self._ctx.build_cache_root).dispositivos
            disp_ctx.clean_preview()
            preview_config = disp_ctx.preview_config
            preview_disp = disp_ctx.preview_disp
            self._ctx.tags_base = preview_disp

            nmax_table = cm.get_global_config_table_name()
            nmax_table_names = [nmax_table]
            disp_table_names = [
                cm.get_dispositivo_config(hw).tag_table
                for hw in cm.list_hw_types_active()
                if cm.get_dispositivo_config(hw) is not None
            ]

            # 2/4 + 3/4. Exporta FLAT (N_MAX + 6 disp tables) en un execute_batch.
            batch_result = await dispatch_async(
                self._ctx.tia_client,
                "execute_batch",
                {
                    "operations": [
                        {
                            "command": "export_plc_tags_xml",
                            "args": {
                                "plc_name": self._ctx.plc_name,
                                "target_dir": str(preview_config),
                                "table_names": nmax_table_names,
                                "keep_folder_structure": False,
                            },
                        },
                        {
                            "command": "export_plc_tags_xml",
                            "args": {
                                "plc_name": self._ctx.plc_name,
                                "target_dir": str(preview_disp),
                                "table_names": disp_table_names,
                                "keep_folder_structure": False,
                            },
                        },
                    ],
                },
            )
            validate_execute_batch_result(
                batch_result["result"],
                undo_text="Preview post-sync (FLAT export)",
                plc_name=self._ctx.plc_name,
                log=logger,
            )

            # 4/4. Diff por hw.
            all_added: list[dict[str, Any]] = []
            all_removed: list[dict[str, Any]] = []
            all_renamed: list[dict[str, Any]] = []
            all_todos: list[dict[str, Any]] = []
            for hw in cm.list_hw_types_active():
                cfg = cm.get_dispositivo_config(hw)
                if cfg is None:
                    continue
                devices = state.get_devices(hw)
                xml_path = preview_disp / f"{cfg.tag_table}.xml"
                diff = compute_diff_table(
                    table_name=cfg.tag_table,
                    desired_devices=devices,
                    xml_path=xml_path,
                )
                # Map a shape legacy de la SPA.
                for uid in diff.added:
                    all_added.append({
                        "uid": uid,
                        "table": cfg.tag_table,
                        "plc_tag": diff.desired.get(uid, ""),
                    })
                for uid in diff.removed:
                    all_removed.append({
                        "uid": uid,
                        "table": cfg.tag_table,
                        "plc_tag": diff.base.get(uid, ""),
                    })
                for uid, (old, new) in diff.renamed.items():
                    all_renamed.append({
                        "uid": uid,
                        "table": cfg.tag_table,
                        "actual": old,
                        "nuevo": new,
                    })
                # Construir ``todos`` shape legacy (incluye 'sin_cambios').
                base_uids = set(diff.base.keys())
                desired_uids = set(diff.desired.keys())
                for uid in base_uids | desired_uids:
                    numero = int(uid)
                    if uid in diff.added:
                        status, actual, nuevo = "agregar", None, diff.desired[uid]
                    elif uid in diff.removed:
                        status, actual, nuevo = "eliminar", diff.base[uid], None
                    elif uid in diff.renamed:
                        status, actual, nuevo = "renombrar", *diff.renamed[uid]
                    else:
                        status, actual, nuevo = "sin_cambios", diff.base[uid], diff.base[uid]
                    all_todos.append({
                        "table": cfg.tag_table,
                        "type": hw,
                        "uid": uid,
                        "numero": numero,
                        "actual": actual,
                        "nuevo": nuevo,
                        "status": status,
                    })

            # 5/4. N_MAX.
            if hasattr(state.dimensiones, "to_api_dict"):
                desired_nmax = state.dimensiones.to_api_dict()
            else:
                desired_nmax = dict(state.dimensiones or {})
            nmax_diff = compute_nmax_diff(
                table_name=nmax_table,
                desired_nmax=desired_nmax,
                xml_path=preview_config / f"{nmax_table}.xml",
            )

            # 6/4. Componer shape legacy (post_sync_preview).
            nmax_summary = {
                "agregados": 0,
                "eliminados": 0,
                "renombrados": 0,
                "sin_cambios": nmax_diff.summary["sin_cambios"],
                "total": nmax_diff.summary["total"],
            }
            self._ctx.post_sync_preview = {
                "agregados": all_added,
                "eliminados": all_removed,
                "renombrados": all_renamed,
                "todos": all_todos,
                "nmax": {
                    "current": nmax_diff.current,
                    "desired": nmax_diff.desired,
                    "todos": nmax_diff.todos,
                    "summary": nmax_diff.summary,
                    "nmax_error": (
                        f"XML N_MAX no encontrado en {preview_config}"
                        if nmax_diff.missing_xml else None
                    ),
                },
                "summary": {
                    "agregados": len(all_added),
                    "eliminados": len(all_removed),
                    "renombrados": len(all_renamed),
                    "sin_cambios": sum(
                        1 for r in all_todos if r["status"] == "sin_cambios"
                    ),
                    "total": len(all_todos),
                },
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"[{self._ctx.plc_name}] Post-sync preview fallo "
                f"(commit ya aplicado): {exc!r}. "
                f"El operario puede lanzar preview manual desde la SPA."
            )
            self._ctx.post_sync_preview = None


# ============================================================================
# Codigo absorbido de helpers/disp/disp_Sincronizar.py (commit 24, sept-2026).
# Antes era un orquestador separado que el FB llamaba via ``match step_nombre``.
# Ahora los 11 stages viven como metodos del FB (mutando ``self._ctx``). Solo
# permanece aqui el ``DispSyncContext`` (dataclass entre stages) y las helpers
# puras (``_selective_table_names``, ``_compute_nmax_ops_for_apply``,
# ``_resolve_tia_folder``, ``_ignore_non_device_xmls``, ``_copy_and_edit_offline``,
# ``_get_affected_dbs_for_compile``, ``_step_summary``).
# ============================================================================

@dataclass
class DispSyncContext:
    """Estado compartido entre las 11 funciones de ``disp_Sincronizar``.

    Cada funcion toma un ``DispSyncContext`` por argumento, lee las deps
    inyectadas y los resultados de funciones previas, y muta los campos
    que representan resultados de su trabajo. El FB
    ``FunctionDispSincronizar`` instancia uno y lo reusa
    entre sus 11 ticks para que los resultados intermedios esten
    disponibles para las funciones posteriores.
    """

    # ── Deps inyectadas ──
    plc_name: str
    tia_client: Any
    config_manager: Any
    app_state: Any
    build_cache_root: Path

    # ── Resultados de exportar_tags ──
    tags_base: Path | None = None
    tags_modified: Path | None = None
    selective_tables: list[str] = field(default_factory=list)

    # ── Resultados de compute_diff ──
    desired_state_per_table: dict[str, dict[str, str]] = field(default_factory=dict)
    added_per_table: dict[str, list[str]] = field(default_factory=dict)
    removed_per_table: dict[str, list[str]] = field(default_factory=dict)
    renamed_per_table: dict[str, tuple[str, str]] = field(default_factory=dict)
    base_state_per_table: dict[str, dict[str, str]] = field(default_factory=dict)

    # ── Resultados de preparar_ops ──
    nmax_ops: list[dict[str, Any]] = field(default_factory=list)
    rename_ops: list[dict[str, Any]] = field(default_factory=list)
    device_changes: list[dict[str, Any]] = field(default_factory=list)

    # ── Resultados de tx_a_nmax_renames ──
    nmax_result: dict[str, Any] = field(default_factory=dict)

    # ── Resultados de tx_b_devices ──
    devices_result: dict[str, Any] = field(default_factory=dict)

    # ── Resultados de compilar_bloques ──
    compile_ok: bool = True
    compile_error: str | None = None

    # ── Resultados de aplicar_comentarios ──
    comments_result: dict[str, Any] = field(default_factory=dict)

    # ── Resultados de post_preview ──
    post_sync_preview: dict[str, Any] | None = None


# ===========================================================================
# Codigo absorbido de helpers/disp/disp_Sincronizar.py (commit 24, sept-2026).
# Antes era un orquestador separado que el FB llamaba via ``match step_nombre``.
# Ahora los 11 stages viven como metodos del FB (mutando ``self._ctx``). Solo
# permanece aqui el ``DispSyncContext`` (dataclass entre stages) y las helpers
# puras (``_selective_table_names``, ``_compute_nmax_ops_for_apply``,
# ``_resolve_tia_folder``, ``_ignore_non_device_xmls``, ``_copy_and_edit_offline``,
# ``_get_affected_dbs_for_compile``, ``_step_summary``).
# ============================================================================


# ===========================================================================
# Helpers internos privados al modulo
# ===========================================================================

# Nota: ``dispatch_async`` se importa arriba desde
# ``core.helpers.tia.dispatch_async``. Antes vivia
# duplicado aqui (4 copias en total: 2 disp + 2 proc); ahora vive
# como helper compartido.


def _selective_table_names(config_manager: Any) -> list[str]:
    """Lista las tablas que el sync dispositivos toca (data-driven)."""
    nmax_table = config_manager.get_global_config_table_name()
    seen: set[str] = set()
    result: list[str] = []
    for hw_type in config_manager.list_hw_types_active():
        tag_table = config_manager.get_tag_table_name(hw_type)
        if tag_table and tag_table not in seen:
            seen.add(tag_table)
            result.append(tag_table)
    if nmax_table and nmax_table not in seen:
        seen.add(nmax_table)
        result.append(nmax_table)
    return result


def _compute_nmax_ops_for_apply(
    tags_base: Path,
    config_manager: Any,
    app_state: Any,
) -> list[dict[str, Any]]:
    """Calcula la lista de ops N_MAX para el handler online.

    Returns:
        Lista de ``[{"table_name": ..., "constant_name": ...,
        "new_value": int}]`` lista para el dispatch al handler
        ``commit_user_constants_online``.
    """
    from core.helpers.simatic_ml import PlcUserConstantParser

    nmax_folder = config_manager.get_tia_folder_nmax()
    nmax_table = config_manager.get_global_config_table_name()
    xml_path = tags_base / nmax_folder / f"{nmax_table}.xml"

    current: dict[str, int] = {}
    if xml_path.is_file():
        try:
            current = PlcUserConstantParser.parse_user_constants(xml_path)
        except Exception as e:
            logger.error(f"[N_MAX] Parse FAIL {xml_path}: {e}")
    else:
        # Sin este else, current={} lleva al diff a marcar TODAS las
        # dims como "actualizar" enmascarando una falla de export.
        # Si TIA no devolvio nada, NO deberiamos proponer cambios.
        logger.warning(
            f"[N_MAX] XML esperado no encontrado (sync): {xml_path}"
        )

    d = app_state.dimensiones or {}
    desired: dict[str, int] = {}
    for nmax_name in config_manager.list_nmax_active():
        v = d.get(nmax_name)
        if v is None:
            v = 0
        desired[nmax_name] = int(v)

    ops: list[dict[str, Any]] = []
    for name, des_val in desired.items():
        cur_val = current.get(name)
        if cur_val is None or cur_val == des_val:
            continue
        ops.append({
            "table_name": nmax_table,
            "constant_name": name,
            "new_value": des_val,
        })
    return ops


def _resolve_tia_folder(config_manager: Any, table_key: str) -> str:
    """Resuelve la carpeta TIA donde debe guardarse el XML de ``table_key``."""
    nmax_table = config_manager.get_global_config_table_name()
    if table_key == nmax_table:
        return config_manager.get_tia_folder_nmax()
    return config_manager.get_tia_folder_dispositivos()


def _ignore_non_device_xmls(
    device_table_names: set[str],
) -> "callable":
    """Callable para ``shutil.copytree(ignore=...)``.

    Excluye los XMLs cuyo stem NO este en ``device_table_names``.
    Esto evita que se copie ``000_Config_Dispositivos.xml`` (tabla
    N_MAX online-only que NO debe llegar al import offline de Tx B):
    si se copiara, Tx B la re-importaria con sus valores pre-commit,
    sobrescribiendo los N_MAX aplicados online en Tx A.

    ``shutil.copytree`` invoca este callable UNA VEZ POR CADA
    SUBDIRECTORIO del arbol (incluida la raiz). Solo inspeccionamos
    ``files``: la recursion la hace ``copytree`` automaticamente.
    """
    def _ignore(directory: str, files: list[str]) -> set[str]:
        ignored: set[str] = set()
        for name in files:
            if name.endswith(".xml"):
                stem = name[:-4]
                if stem not in device_table_names:
                    ignored.add(name)
        return ignored
    return _ignore


def _copy_and_edit_offline(
    build_cache_root: Path,
    device_changes: list[dict[str, Any]],
) -> None:
    """Stage 7 del sync: copytree filtrado sync export→modified + edits.

    El copytree con filtro excluye ``000_Config_Dispositivos.xml``
    (tabla N_MAX online-only) para que Tx B no la re-importe y anule
    los N_MAX de Tx A.
    """
    from areas.alimentacion.helpers.build_cache import build_cache
    from core.helpers.simatic_ml import PlcUserConstantModifier

    disp_ctx = build_cache(root=build_cache_root).dispositivos
    src = disp_ctx.sync_variables_export
    dst = disp_ctx.sync_variables_modified
    device_table_names = {dc["table_name"] for dc in device_changes}

    logger.info(f"[disp sync] copytree: {src} -> {dst}")

    # 1. Copytree filtrado sync/variables/export -> sync/variables/modified.
    # El filtro es CRITICO: si copiamos la tabla N_MAX, Tx B la
    # re-importaria con sus valores pre-commit, anulando los N_MAX
    # aplicados online en Tx A.
    if src.exists():
        shutil.copytree(
            src,
            dst,
            ignore=_ignore_non_device_xmls(device_table_names),
            dirs_exist_ok=True,
        )
    else:
        logger.warning(
            f"[disp sync] origen no existe: {src}. "
            f"Nada que copiar a modified."
        )
        return

    # 2. Edit offline de cada tabla en sync/variables/modified.
    for dc in device_changes:
        table_name = dc["table_name"]
        tia_folder = dc.get("tia_folder") or ""
        adds = dc.get("adds", []) or []
        removes = set(dc.get("removes", []) or [])
        xml_path = (
            dst
            / tia_folder
            / f"{table_name}.xml"
        )
        if not xml_path.is_file():
            matches = list(dst.rglob(f"{table_name}.xml"))
            if matches:
                xml_path = matches[0]
        if xml_path.is_file():
            logger.debug(
                f"[disp sync] edit offline: tabla={table_name}, "
                f"adds={len(adds)}, removes={len(removes)}, "
                f"xml={xml_path}"
            )
            modifier = PlcUserConstantModifier(xml_path)
            modifier.add_user_constants_by_table(table_name, adds)
            modifier.remove_user_constants(removes)
            if modifier.was_modified():
                modifier.save(xml_path)
        else:
            # El XML del tipo de dispositivo no esta en modified.
            # Saltamos ese tipo pero avisamos al operario: un FB
            # que reporta "0 adds, 0 removes" sin este warning
            # podria hacer creer al operario que ese tipo de
            # dispositivo ya estaba al dia.
            logger.warning(
                f"[disp sync] XML no encontrado para tabla "
                f"'{table_name}' en {dst}. Se omite del sync."
            )


def _get_affected_dbs_for_compile(config_manager: Any) -> list[str]:
    """Lista los 6 DBs de dispositivos que necesitan recompilacion."""
    result: list[str] = []
    for hw in config_manager.list_hw_types_active():
        cfg = config_manager.get_dispositivo_config(hw)
        if cfg is None:
            continue
        # Aqui queremos el NOMBRE DEL DB (``cfg.db_name``), no la
        # PlcTagTable (``cfg.tag_table``): la compilacion opera sobre
        # los DBs de array. El legacy DispSyncInstancesUseCase.
        # _get_affected_dbs_for_compile hacia lo mismo via
        # ``config.get_db_name(hw)``.
        result.append(cfg.db_name)
    return result





def _step_summary(ctx: Any, step_nombre: str) -> str:
    """Resumen legible del step que acaba de correr (aparece en la SPA).

    Mapea cada ``step_nombre`` de la tabla STAGES (humano) a los flags
    que el stage muta en ``ctx``. Si el nombre no encaja, devuelve un
    resumen neutro.
    """
    if step_nombre == "Exportar etiquetas":
        return (
            f"{step_nombre}: {len(ctx.selective_tables)} tablas exportadas"
        )
    if step_nombre == "Calcular diferencias de dispositivos":
        adds = sum(len(v) for v in ctx.added_per_table.values())
        rems = sum(len(v) for v in ctx.removed_per_table.values())
        return (
            f"{step_nombre}: {adds} adds, {rems} removes, "
            f"{len(ctx.renamed_per_table)} renames"
        )
    if step_nombre == "Preparar operaciones":
        return (
            f"{step_nombre}: {len(ctx.nmax_ops)} N_MAX ops, "
            f"{len(ctx.device_changes)} tablas con cambios"
        )
    if step_nombre == "Aplicar N_MAX y renombres":
        ops = ctx.nmax_result.get("operations_executed", 0)
        return f"{step_nombre}: {ops} N_MAX aplicados en TIA"
    if step_nombre == "Esperar consolidación TIA":
        return (
            f"{step_nombre}: TIA consolida (2s)"
        )
    if step_nombre == "Re-exportar etiquetas":
        return f"{step_nombre}: XMLs releidos post-Tx A"
    if step_nombre == "Editar archivos XML":
        return f"{step_nombre}: XMLs offline editados"
    if step_nombre == "Aplicar dispositivos":
        ops = ctx.devices_result.get("operations_executed", 0)
        return f"{step_nombre}: {ops} tablas importadas a TIA"
    if step_nombre == "Compilar bloques":
        label = "OK" if ctx.compile_ok else "WARN"
        return f"{step_nombre}: compile={label}"
    if step_nombre == "Aplicar comentarios":
        s = ctx.comments_result.get("summary") or {}
        return (
            f"{step_nombre}: "
            f"{s.get('total_reused', 0)} reused + "
            f"{s.get('total_inserted', 0)} inserted "
            f"en {s.get('disp_dbs_updated', 0)} DBs"
        )
    if step_nombre == "Generar preview post-sincronización":
        return f"{step_nombre}: preview post-sync generado"
    return f"{step_nombre}: OK"


__all__ = ["FunctionDispSincronizar"]
