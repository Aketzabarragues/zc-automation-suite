"""FB de area: preview de dispositivos vs PLC (diff read-only).

State machine sobre el helper ``disp_generate_preview``
(areas/alimentacion/helpers/disp/disp_generate_preview.py). El helper
expone funciones independientes (``exportar_tags``, ``compute_devices``,
``compute_nmax``, ``build_response``) que reciben un
``DispPreviewContext`` y mutan sus campos. **Aqui en el FB vive la
state machine**: el orden de las 4 llamadas, el mapping step ->
funcion del helper, y la instanciacion del ctx.

Antes (sept-2026 -): 2 de los 4 steps eran checkpoints vacios
(combinado con...); el resto ejecutaba el helper monolitico de golpe.

Despues (sept-2026): cada step del FB ejecuta una funcion real del
helper contra el ``DispPreviewContext`` compartido entre los 4 ticks.

Hereda directo de ``FunctionBase`` (no del template). Zona 0 con 4 deps
comunes + 1 especifica.

Runtime params via ``start(**kwargs)``:
  - ``plc_name`` (str): nombre del PLC destino. Obligatorio.

El ``self.result`` se popula con la shape legacy esperada por la SPA::

    {
      'agregados':   list[dict],
      'eliminados':  list[dict],
      'renombrados': list[dict],
      'todos':       list[dict],
      'nmax':        dict,
      'summary':     dict,
    }

Steps (4, mismo orden que el legacy ``generar_prevision``):
  - exportar_tags      -> helper.disp_generate_preview.exportar_tags
  - compute_devices    -> helper.disp_generate_preview.compute_devices
  - compute_nmax       -> helper.disp_generate_preview.compute_nmax
  - build_response     -> helper.disp_generate_preview.build_response
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from core.composition.plc_function_base import FunctionBase
from core.runtime.app_state import AppState, get_app_state
from core.runtime.log_buffer import LogBuffer, get_log_buffer


class FunctionDispGenerarPreview(FunctionBase):
    """FB que calcula el diff completo (N_MAX + devices) de un PLC."""

    # ==================================================================
    # CONFIGURACION ESTATICA DEL FB
    # ==================================================================

    # export_plc_tags_xml sobre 7 tablas puede tardar ~10-30s en S7-1500.
    # 60s cubre holgadamente.
    STEP_TIMEOUT_S: float = 60.0

    # ==================================================================
    # CONSTRUCTOR
    # ==================================================================

    def __init__(
        self,
        nombre: str = "disp_generar_preview",
        titulo: str = "Generar preview de dispositivos vs PLC",
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
                {"nombre": "compute_devices"},
                {"nombre": "compute_nmax"},
                {"nombre": "build_response"},
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
        # DispPreviewContext compartido entre los 4 ticks. Se
        # reinicializa en cada on_start() para no arrastrar estado del
        # run anterior (el FB es re-arrancable).
        self._ctx: Any = None

    # ==================================================================
    # HOOK 1: on_start  (ZONA 3: validar params + crear ctx)
    # ==================================================================

    def on_start(self, **params: Any) -> None:
        """Validar deps inyectadas + capturar plc_name + crear ctx."""
        if self._config is None:
            raise RuntimeError(
                "FunctionDispGenerarPreview requiere config_manager. "
                "Inyectalo en el constructor al registrar el FB."
            )
        if self._tia_client is None:
            raise RuntimeError(
                "FunctionDispGenerarPreview requiere tia_client. "
                "Inyectalo en el constructor al registrar el FB."
            )
        plc_name = params.get("plc_name")
        if not plc_name:
            raise ValueError(
                "FunctionDispGenerarPreview.start(plc_name=...) es obligatorio"
            )
        self._plc_name = str(plc_name)

        # Crear el DispPreviewContext que las 4 funciones iran mutando.
        # Lazy import para evitar ciclo con helpers/sync/.
        from areas.alimentacion.helpers.disp.disp_generate_preview import (
            DispPreviewContext,
        )
        self._ctx = DispPreviewContext(
            plc_name=self._plc_name,
            tia_client=self._tia_client,
            config_manager=self._config,
            app_state=self._state,
            build_cache_root=self._build_cache_root,
        )

        self._log.info(
            f"[{self.nombre}] Iniciando preview de {self._plc_name}"
        )

    # ==================================================================
    # HOOK 2: run_step  (ZONA 4: state machine -> dispatch al helper)
    # ==================================================================

    async def run_step(self, idx: int, **params: Any) -> str:
        """Dispatch del FB step ``idx`` a la funcion del helper ``disp_generate_preview``.

        Aqui vive la state machine: cada step del FB llama a UNA
        funcion del helper contra el ``DispPreviewContext`` compartido.
        El ``case`` es explicito (no dict.get dispatch) para que sea
        visible en stack traces cuando algo falla.
        """
        # Lazy import para evitar ciclo con helpers/disp/.
        from areas.alimentacion.helpers.disp import disp_generate_preview

        if self._ctx is None:
            raise RuntimeError(
                "DispPreviewContext no inicializado. on_start() no se ejecuto "
                "(o el FB no recibio un plc_name valido)."
            )

        step_nombre = self.steps[idx]["nombre"]
        match step_nombre:
            case "exportar_tags":
                await disp_generate_preview.exportar_tags(self._ctx)
            case "compute_devices":
                await disp_generate_preview.compute_devices(self._ctx)
            case "compute_nmax":
                await disp_generate_preview.compute_nmax(self._ctx)
            case "build_response":
                await disp_generate_preview.build_response(self._ctx)
            case _:
                raise ValueError(f"step no soportado: {step_nombre!r}")

        # Resumen legible del step que acaba de correr.
        return _step_summary(self._ctx, step_nombre)

    # ==================================================================
    # HOOK 3: on_finish  (ZONA 5: vuelco del result desde el ctx)
    # ==================================================================

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` con la shape legacy que espera la SPA."""
        if self._ctx is None:
            # Error temprano: deps no inyectadas o plc_name ausente.
            self.result = {
                "agregados": [],
                "eliminados": [],
                "renombrados": [],
                "todos": [],
                "nmax": {"current": {}, "desired": {}, "todos": [],
                         "summary": {"actualizar": 0, "sin_cambios": 0,
                                     "total": 0}},
                "summary": {"agregados": 0, "eliminados": 0,
                            "renombrados": 0, "sin_cambios": 0,
                            "total": 0},
            }
            return

        self.result = self._ctx.result

        # Log de cierre, igual que hacia el helper monolitico.
        s = self._ctx.result["summary"]
        nmax_summary = self._ctx.result["nmax"]["summary"]
        self._log.success(
            f"[{self.nombre}] preview calculado para "
            f"{self._ctx.plc_name}: "
            f"{s['agregados']} agregados, {s['eliminados']} eliminados, "
            f"{s['renombrados']} renombrados, "
            f"{nmax_summary['actualizar']} N_MAX actualizar"
        )


def _step_summary(ctx: Any, step_nombre: str) -> str:
    """Resumen legible del step que acaba de correr (aparece en la SPA)."""
    if step_nombre == "exportar_tags":
        return (
            f"{step_nombre}: {len(ctx.selective_tables)} tablas exportadas"
        )
    if step_nombre == "compute_devices":
        adds = sum(len(v) for v in ctx.added_per_table.values())
        rems = sum(len(v) for v in ctx.removed_per_table.values())
        return (
            f"{step_nombre}: {adds} adds, {rems} removes, "
            f"{len(ctx.renamed_per_table)} renames"
        )
    if step_nombre == "compute_nmax":
        nmax_summary = ctx.nmax_block.get("summary", {})
        return (
            f"{step_nombre}: {nmax_summary.get('actualizar', 0)} N_MAX "
            f"actualizar, {nmax_summary.get('sin_cambios', 0)} sin cambios"
        )
    if step_nombre == "build_response":
        s = ctx.result.get("summary", {})
        return (
            f"{step_nombre}: {s.get('total', 0)} entradas en vista unificada"
        )
    return f"{step_nombre}: OK"


__all__ = ["FunctionDispGenerarPreview"]