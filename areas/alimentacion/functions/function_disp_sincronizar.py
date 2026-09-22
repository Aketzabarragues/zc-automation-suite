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

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.composition.plc_function_base import FunctionBase
from core.runtime.app_state import AppState, get_app_state

logger = logging.getLogger(__name__)


class FunctionDispSincronizar(FunctionBase):
    """FB que sincroniza dispositivos contra TIA (11 etapas transaccionales)."""

    # ==================================================================
    # CONFIGURACION ESTATICA DEL FB
    # ==================================================================

    # Sync completo: 2 transacciones TIA + compile + apply comentarios
    # + post preview. TIA V21 puede tardar varios minutos para un PLC
    # con 200+ bloques y 6 DBs de dispositivos redimensionados.
    STEP_TIMEOUT_S: float = 600.0

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
                {"nombre": "exportar_tags"},
                {"nombre": "compute_diff"},
                {"nombre": "preparar_ops"},
                {"nombre": "tx_a_nmax_renames"},
                {"nombre": "wait_consolidation"},
                {"nombre": "exportar_post_tx_a"},
                {"nombre": "editar_xmls_offline"},
                {"nombre": "tx_b_devices"},
                {"nombre": "compilar_bloques"},
                {"nombre": "aplicar_comentarios"},
                {"nombre": "post_preview"},
            ],
            tracker=tracker,
        )
        # ZONA 0: deps inyectadas.
        self._config = config_manager
        self._tia_client = tia_client
        self._build_cache_root: Path = (
            build_cache if build_cache is not None
            else Path(os.getcwd()) / ".build_cache"
        )
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
        # Lazy import para evitar ciclo con helpers/disp/.
        from areas.alimentacion.helpers.disp import disp_Sincronizar as helper

        if self._ctx is None:
            raise RuntimeError(
                "DispSyncContext no inicializado. on_start() no se ejecuto "
                "(o el FB no recibio un plc_name valido)."
            )

        step_nombre = self.steps[idx]["nombre"]
        match step_nombre:
            case "exportar_tags":
                await self._stage_1_exportar_tags(self._ctx)
            case "compute_diff":
                await self._stage_2_compute_diff(self._ctx)
            case "preparar_ops":
                await self._stage_3_preparar_ops(self._ctx)
            case "tx_a_nmax_renames":
                await self._stage_4_tx_a_nmax_renames(self._ctx)
            case "wait_consolidation":
                await self._stage_5_wait_consolidation(self._ctx)
            case "exportar_post_tx_a":
                await self._stage_6_exportar_post_tx_a(self._ctx)
            case "editar_xmls_offline":
                await self._stage_7_editar_xmls_offline(self._ctx)
            case "tx_b_devices":
                await self._stage_8_tx_b_devices(self._ctx)
            case "compilar_bloques":
                await self._stage_9_compilar_bloques(self._ctx)
            case "aplicar_comentarios":
                await self._stage_10_aplicar_comentarios(self._ctx)
            case "post_preview":
                await self._stage_99_disp_post_preview(self._ctx)
            case _:
                raise ValueError(f"step no soportado: {step_nombre!r}")

        # Resumen legible del step que acaba de correr (aparece en la SPA).
        return _step_summary(self._ctx, step_nombre)

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



# ============================================================================
# Codigo absorbido de helpers/disp/disp_Sincronizar.py (commit 24, sept-2026).
# Antes era un orquestador separado que el FB llamaba via ``match step_nombre``.
# Ahora vive como metodos del FB (mutando ``self._ctx``).
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
# 11 funciones puras (cada una muta ``ctx``; sin state machine aqui)
# ===========================================================================



async def _stage_1_exportar_tags(self) -> None:
    """Limpia modified/ y exporta las tablas selectivas al snapshot."""
    from areas.alimentacion.helpers.build_cache import build_cache

    disp_ctx = build_cache(root=self._ctx.build_cache_root).dispositivos
    disp_ctx.clean()
    # El snapshot limpio vive en ``exports_variables`` (convencion de 9
    # carpetas). ``modified_variables`` se rellena en ``editar_xmls_offline``
    # via ``shutil.copytree`` filtrado (que excluye ``000_Config_Dispositivos``
    # para no re-importar la N_MAX online en Tx B).
    self._ctx.tags_base = disp_ctx.exports_variables
    self._ctx.selective_tables = _selective_table_names(self._ctx.config_manager)
    logger.debug(f"workdir (exports): {self._ctx.tags_base}")
    await dispatch_async(
        self._ctx.tia_client,
        "export_plc_tags_xml",
        {
            "plc_name": self._ctx.plc_name,
            "target_dir": str(self._ctx.tags_base),
            "table_names": self._ctx.selective_tables,
        },
    )


async def _stage_2_compute_diff(self) -> None:
    """Calcula el diff entre los XMLs exportados y el AppState (read-only)."""
    assert self._ctx.tags_base is not None, (
        "compute_diff requiere exportar_tags previo"
    )
    from areas.alimentacion.helpers.disp.disp_generate_preview import (
        _build_desired_state_from_app,
        _compute_diff_readonly,
    )
    self._ctx.desired_state_per_table = _build_desired_state_from_app(
        self._ctx.app_state, self._ctx.config_manager,
    )
    (
        self._ctx.added_per_table,
        self._ctx.removed_per_table,
        self._ctx.renamed_per_table,
        self._ctx.base_state_per_table,
    ) = await asyncio.to_thread(
        _compute_diff_readonly,
        self._ctx.tags_base, self._ctx.desired_state_per_table,
    )


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
        nmax_result = await dispatch_async(
            self._ctx.tia_client,
            "commit_user_constants_online",
            {
                "plc_name": self._ctx.plc_name,
                "nmax_ops": self._ctx.nmax_ops,
                # Key ``rename_ops`` + items con ``table_name``,
                # ``current_name``, ``new_name``: shape que espera el
                # handler ``commit_user_constants_online``. Antes
                # pasabamos ``renames`` con keys ``table`` y
                # ``current_value``: el handler las ignoraba
                # silenciosamente y los renames NUNCA se aplicaban.
                "rename_ops": self._ctx.rename_ops,
                "undo_text": "Sync N_MAX + renames",
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
    # Re-exportar solo las 6 tablas de devices (NO la N_MAX: ya esta
    # consolidada en Tx A). El destino es ``exports_variables``
    # (snapshot limpio), no ``modified_variables``: el copytree de
    # Stage 7 hace la copia filtrada.
    from areas.alimentacion.helpers.build_cache import build_cache
    disp_ctx = build_cache(root=self._ctx.build_cache_root).dispositivos
    logger.debug(f"workdir (exports re-read post-TxA): {disp_ctx.exports_variables}")
    await dispatch_async(
        self._ctx.tia_client,
        "export_plc_tags_xml",
        {
            "plc_name": self._ctx.plc_name,
            "target_dir": str(disp_ctx.exports_variables),
            "table_names": [dc["table_name"] for dc in self._ctx.device_changes],
        },
    )


async def _stage_7_editar_xmls_offline(self) -> None:
    """Copia filtrada exports->modified + edita XMLs offline (adds/removes)."""
    assert self._ctx.tags_base is not None, (
        "editar_xmls_offline requiere exportar_tags previo"
    )
    from areas.alimentacion.helpers.build_cache import build_cache
    disp_ctx = build_cache(root=self._ctx.build_cache_root).dispositivos
    logger.debug(f"workdir (modified): {disp_ctx.modified_variables}")
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
        # ``modified_variables/`` recursivamente: si encuentra la
        # estructura interna del PLC (e.g.
        # ``2000_Dispositivos/2000_Disp_ED.xml``), hace match
        # automatico con su PLC tag interno y dispara UPDATE (no
        # CREATE). Pasar ``target_folder`` con un valor explicito
        # fuer.a el match a una sola carpeta, lo rompe y causa
        # ``CommitOnDispose``. Import a RAIZ con ``target_folder=""``
        # (default del handler) es el camino feliz.
        from areas.alimentacion.helpers.build_cache import build_cache
        disp_ctx = build_cache(root=self._ctx.build_cache_root).dispositivos
        devices_result = await dispatch_async(
            self._ctx.tia_client,
            "commit_disp_devices_offline",
            {
                "plc_name": self._ctx.plc_name,
                "device_changes": self._ctx.device_changes,
                "modified_dir": str(disp_ctx.modified_variables),
                "undo_text": "Sync devices",
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
    from areas.alimentacion.data.data_DispSlotMap import disp_build_slot_maps

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

    # ── 3. Limpiar modified/bloques/ ──
    # Aunque Stage 1 del sync ya limpio modified/, forzamos aqui
    # por idempotencia si este stage se invoca standalone.
    disp_ctx = build_cache(root=self._ctx.build_cache_root).dispositivos
    modified_bloques = disp_ctx.modified_bloques
    if modified_bloques.exists():
        shutil.rmtree(modified_bloques)
    modified_bloques.mkdir(parents=True, exist_ok=True)
    exports_bloques = disp_ctx.exports_bloques
    logger.debug(
        f"workdir (comentarios): exports={exports_bloques}, "
        f"modified={modified_bloques}"
    )

    # ── 4. Export UNA VEZ de los 6 DBs a exports/bloques/ ──
    for hw_type, db_name in db_names.items():
        await dispatch_async(
            self._ctx.tia_client,
            "export_block",
            {
                "plc_name": self._ctx.plc_name,
                "block_name": db_name,
                "target_dir": str(exports_bloques),
            },
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
        dcl_path = SdPair(Path(modified_bloques), db_name).dcl
        res_path = SdPair(Path(modified_bloques), db_name).res
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
        await dispatch_async(
            self._ctx.tia_client,
            "import_block",
            {
                "plc_name": self._ctx.plc_name,
                "import_dir": str(modified_bloques),
                "target_folder": "",  # default: TIA escanea recursivo
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


async def _stage_99_disp_post_preview(self) -> None:
    """Genera el preview post-sync para que la SPA vea 'todo en sync'.

    Reusa las 4 funciones puras de ``disp_generate_preview``
    (``exportar_tags``, ``compute_devices``, ``compute_nmax`` y
    ``build_response``). Crea un ``DispPreviewContext`` con las
    mismas deps y lo ejecuta en orden. El
    ``build_response`` final popula ``self._ctx.post_sync_preview`` con la
    shape legacy (agregados, eliminados, renombrados, todos, nmax,
    summary).
    """
    from areas.alimentacion.helpers.disp.disp_generate_preview import (
        DispPreviewContext,
        build_response as pv_build_response,
        compute_devices as pv_compute_devices,
        compute_nmax as pv_compute_nmax,
        exportar_tags as pv_exportar_tags,
    )

    pv_ctx = DispPreviewContext(
        plc_name=self._ctx.plc_name,
        tia_client=self._ctx.tia_client,
        config_manager=self._ctx.config_manager,
        app_state=self._ctx.app_state,
        build_cache_root=self._ctx.build_cache_root,
    )

    try:
        await pv_exportar_tags(pv_ctx)
        await pv_compute_devices(pv_ctx)
        await pv_compute_nmax(pv_ctx)
        await pv_build_response(pv_ctx)
        self._ctx.post_sync_preview = pv_ctx.result
    except Exception as exc:
        logger.warning(
            f"[{self._ctx.plc_name}] Post-sync preview fallo "
            f"(commit ya aplicado): {exc}"
        )
        self._ctx.post_sync_preview = None


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
    """Stage 7 del sync: copytree filtrado exports→modified + edits.

    El copytree con filtro excluye ``000_Config_Dispositivos.xml``
    (tabla N_MAX online-only) para que Tx B no la re-importe y anule
    los N_MAX de Tx A.
    """
    from areas.alimentacion.helpers.build_cache import build_cache
    from core.helpers.simatic_ml import PlcUserConstantModifier

    disp_ctx = build_cache(root=build_cache_root).dispositivos
    device_table_names = {dc["table_name"] for dc in device_changes}

    # 1. Copytree filtrado exports/variables -> modified/variables.
    # El filtro es CRITICO: si copiamos la tabla N_MAX, Tx B la
    # re-importaria con sus valores pre-commit, anulando los N_MAX
    # aplicados online en Tx A.
    if disp_ctx.exports_variables.exists():
        shutil.copytree(
            disp_ctx.exports_variables,
            disp_ctx.modified_variables,
            ignore=_ignore_non_device_xmls(device_table_names),
            dirs_exist_ok=True,
        )

    # 2. Edit offline de cada tabla en modified_variables.
    for dc in device_changes:
        table_name = dc["table_name"]
        tia_folder = dc.get("tia_folder") or ""
        adds = dc.get("adds", []) or []
        removes = set(dc.get("removes", []) or [])
        xml_path = (
            disp_ctx.modified_variables
            / tia_folder
            / f"{table_name}.xml"
        )
        if not xml_path.is_file():
            matches = list(
                disp_ctx.modified_variables.rglob(f"{table_name}.xml")
            )
            if matches:
                xml_path = matches[0]
        if xml_path.is_file():
            modifier = PlcUserConstantModifier(xml_path)
            modifier.add_user_constants_by_table(table_name, adds)
            modifier.remove_user_constants(removes)
        else:
            # El XML del tipo de dispositivo no esta en
            # modified_variables (ni ruta directa ni rglob
            # fallback). Saltamos ese tipo pero avisamos al
            # operario: un FB que reporta "0 adds, 0 removes"
            # sin este warning podria hacer creer al operario
            # que ese tipo de dispositivo ya estaba al dia.
            logger.warning(
                f"[disp sync] XML no encontrado para tabla "
                f"'{table_name}' en {disp_ctx.modified_variables}. "
                f"Se omite del sync."
            )
            # NO llamamos ``modifier.regenerate_root_table_id()``:
            # cambiar el ID del PlcTagTable root de ``0`` a un valor alto
            # hace que TIA Portal V21 interprete el import como CREATE
            # (no UPDATE) y reviente con ``CommitOnDispose`` al intentar
            # commit/rollback. El root debe mantener su ID original.
            if modifier.was_modified():
                modifier.save(xml_path)


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


__all__ = [
    "DispSyncContext",
    "TIA_CONSOLIDATION_SLEEP_S",
    # 11 funciones puras (sin state machine, sin orden; eso vive en el FB)
    "exportar_tags",
    "compute_diff",
    "preparar_ops",
    "tx_a_nmax_renames",
    "wait_consolidation",
    "exportar_post_tx_a",
    "editar_xmls_offline",
    "tx_b_devices",
    "compilar_bloques",
    "aplicar_comentarios",
    "post_preview",
]


def _step_summary(ctx: Any, step_nombre: str) -> str:
    """Resumen legible del step que acaba de correr (aparece en la SPA)."""
    if step_nombre == "exportar_tags":
        return (
            f"{step_nombre}: {len(ctx.selective_tables)} tablas exportadas"
        )
    if step_nombre == "compute_diff":
        adds = sum(len(v) for v in ctx.added_per_table.values())
        rems = sum(len(v) for v in ctx.removed_per_table.values())
        return (
            f"{step_nombre}: {adds} adds, {rems} removes, "
            f"{len(ctx.renamed_per_table)} renames"
        )
    if step_nombre == "preparar_ops":
        return (
            f"{step_nombre}: {len(ctx.nmax_ops)} N_MAX ops, "
            f"{len(ctx.device_changes)} tablas con cambios"
        )
    if step_nombre == "tx_a_nmax_renames":
        ops = ctx.nmax_result.get("operations_executed", 0)
        return f"{step_nombre}: {ops} N_MAX aplicados en TIA"
    if step_nombre == "wait_consolidation":
        return (
            f"{step_nombre}: TIA consolida (2s)"
        )
    if step_nombre == "exportar_post_tx_a":
        return f"{step_nombre}: XMLs releidos post-Tx A"
    if step_nombre == "editar_xmls_offline":
        return f"{step_nombre}: XMLs offline editados"
    if step_nombre == "tx_b_devices":
        ops = ctx.devices_result.get("operations_executed", 0)
        return f"{step_nombre}: {ops} tablas importadas a TIA"
    if step_nombre == "compilar_bloques":
        label = "OK" if ctx.compile_ok else "WARN"
        return f"{step_nombre}: compile={label}"
    if step_nombre == "aplicar_comentarios":
        # N3: agregados reused/inserted por los 6 DBs de dispositivos.
        s = ctx.comments_result.get("summary") or {}
        return (
            f"{step_nombre}: "
            f"{s.get('total_reused', 0)} reused + "
            f"{s.get('total_inserted', 0)} inserted "
            f"en {s.get('disp_dbs_updated', 0)} DBs"
        )
    if step_nombre == "post_preview":
        return f"{step_nombre}: preview post-sync generado"
    return f"{step_nombre}: OK"


__all__ = ["FunctionDispSincronizar"]
