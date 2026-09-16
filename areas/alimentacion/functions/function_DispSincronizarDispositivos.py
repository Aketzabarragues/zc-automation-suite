"""FB de area: sincronizacion transaccional de dispositivos vs PLC.

State machine sobre el helper ``disp_sync`` (areas/alimentacion/helpers
/disp/disp_sync.py). El helper expone funciones independientes
(``exportar_tags``, ``compute_diff``, ``tx_a_nmax_renames``, etc.) que
reciben un ``DispSyncContext`` y mutan sus campos. **Aqui en el FB vive
la state machine**: el orden de las 11 llamadas, el mapping step ->
funcion del helper, y la instanciacion del ctx.

Antes (sept-2026 -): 10 de los 11 steps del FB eran checkpoints
vacios; solo el ultimo invocaba el helper monolitico de golpe. Esto
provocaba que el progressbar saltara al ultimo step sin transicion
visible.

Ahora (sept-2026): cada step del FB ejecuta 1 funcion real del helper
contra un ``DispSyncContext`` compartido entre los 11 ticks. El
progressbar muestra 11 etapas con trabajo real y duracion real.

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

import os
from pathlib import Path
from typing import Any

from core.composition.plc_function_base import FunctionBase
from core.runtime.app_state import AppState, get_app_state
from core.runtime.log_buffer import LogBuffer, get_log_buffer


class FunctionDispSincronizarDispositivos(FunctionBase):
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
        log: Any = None,
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
        self._log: LogBuffer = log if log is not None else get_log_buffer()
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
                "FunctionDispSincronizarDispositivos requiere "
                "config_manager. Inyectalo en el constructor."
            )
        if self._tia_client is None:
            raise RuntimeError(
                "FunctionDispSincronizarDispositivos requiere "
                "tia_client. Inyectalo en el constructor."
            )
        plc_name = params.get("plc_name")
        if not plc_name:
            raise ValueError(
                "FunctionDispSincronizarDispositivos.start(plc_name=...) "
                "es obligatorio"
            )
        self._plc_name = str(plc_name)

        # Crear el DispSyncContext que las 11 funciones iran mutando.
        # Lazy import para evitar ciclo con helpers/sync/.
        from areas.alimentacion.helpers.disp.disp_sync import DispSyncContext
        self._ctx = DispSyncContext(
            plc_name=self._plc_name,
            tia_client=self._tia_client,
            config_manager=self._config,
            app_state=self._state,
            build_cache_root=self._build_cache_root,
        )

        self._log.info(
            f"[{self.nombre}] Iniciando sync transaccional para "
            f"{self._plc_name} (11 etapas)"
        )

    # ==================================================================
    # HOOK 2: run_step  (ZONA 4: state machine -> dispatch al helper)
    # ==================================================================

    async def run_step(self, idx: int, **params: Any) -> str:
        """Dispatch del FB step ``idx`` a la funcion del helper ``disp_sync``.

        Aqui vive la state machine: cada step del FB llama a UNA
        funcion del helper (``exportar_tags``, ``compute_diff``, etc.)
        contra el ``DispSyncContext`` compartido. El ``case`` es
        explicito (no dict.get dispatch) para que sea visible en stack
        traces cuando algo falla.
        """
        # Lazy import para evitar ciclo con helpers/sync/.
        from areas.alimentacion.helpers.sync import disp_sync

        if self._ctx is None:
            raise RuntimeError(
                "DispSyncContext no inicializado. on_start() no se ejecuto "
                "(o el FB no recibio un plc_name valido)."
            )

        step_nombre = self.steps[idx]["nombre"]
        match step_nombre:
            case "exportar_tags":
                await disp_sync.exportar_tags(self._ctx)
            case "compute_diff":
                await disp_sync.compute_diff(self._ctx)
            case "preparar_ops":
                await disp_sync.preparar_ops(self._ctx)
            case "tx_a_nmax_renames":
                await disp_sync.tx_a_nmax_renames(self._ctx)
            case "wait_consolidation":
                await disp_sync.wait_consolidation(self._ctx)
            case "exportar_post_tx_a":
                await disp_sync.exportar_post_tx_a(self._ctx)
            case "editar_xmls_offline":
                await disp_sync.editar_xmls_offline(self._ctx)
            case "tx_b_devices":
                await disp_sync.tx_b_devices(self._ctx)
            case "compilar_bloques":
                await disp_sync.compilar_bloques(self._ctx)
            case "aplicar_comentarios":
                await disp_sync.aplicar_comentarios(self._ctx)
            case "post_preview":
                await disp_sync.post_preview(self._ctx)
            case _:
                raise ValueError(f"step no soportado: {step_nombre!r}")

        # Resumen legible del step que acaba de correr (aparece en la SPA).
        return _step_summary(self._ctx, step_nombre)

    # ==================================================================
    # HOOK 3: on_finish  (ZONA 5: vuelco del result desde el ctx)
    # ==================================================================

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` con la shape legacy que espera la SPA.

        Lee los resultados finales del ``DispSyncContext`` (mismos campos
        que el helper monolitico ``disp_sync`` retornaba, sept-2026 -).
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
        self._log.success(
            f"[{self.nombre}] sync completo para "
            f"{self._ctx.plc_name}: {operations_executed} ops "
            f"({len(self._ctx.nmax_ops)} N_MAX), "
            f"compile={compile_label}"
        )


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
        return f"{step_nombre}: {ops} device ops aplicados en TIA"
    if step_nombre == "compilar_bloques":
        label = "OK" if ctx.compile_ok else "WARN"
        return f"{step_nombre}: compile={label}"
    if step_nombre == "aplicar_comentarios":
        return f"{step_nombre}: comentarios aplicados"
    if step_nombre == "post_preview":
        return f"{step_nombre}: preview post-sync generado"
    return f"{step_nombre}: OK"


__all__ = ["FunctionDispSincronizarDispositivos"]
