"""FB de area: preview de comentarios de un proceso vs PLC (diff read-only).

State machine sobre el helper ``proc_generar_preview``
(areas/alimentacion/helpers/proc/proc_generar_preview.py). El helper
expone funciones independientes (``proc_check_state``,
``proc_check_blocks``, ``proc_build_slot_maps``, ``proc_compute_nmax``,
``proc_export_and_diff``, ``proc_compose_response``) que reciben un
``ProcPreviewContext`` y mutan sus campos. **Aqui en el FB vive la
state machine**: el orden de las 6 llamadas, el mapping step ->
funcion del helper, y la instanciacion del ctx.

Antes: 2 use cases legacy monolíticos
(``generar_prevision`` + ``ejecutar_transaccion``) en
``application/use_cases/proc_sync_comentarios.py``.

Despues: cada step del FB ejecuta una funcion real del
helper contra el ``ProcPreviewContext`` compartido entre los 6 ticks.

Hereda directo de ``FunctionBase`` (no del template). Zona 0 con 5
deps comunes (incluyendo ``bloques_cache`` que el legacy inyectaba
manualmente).

Runtime params via ``start(**kwargs)``:
  - ``proc_uid`` (int): uid del proceso a previsualizar. Obligatorio.
  - ``plc_name`` (str): nombre del PLC destino. Obligatorio.

El ``self.result`` se popula con la shape legacy esperada por la SPA::

    {
      "proc_uid":           int,
      "proc_codigo":        str,
      "precondiciones_ok":  bool,
      "missing_blocks":     list[str],
      "db_param_name":      str,
      "db_alm_name":        str,
      "table_name":         str,
      "arrays":             dict,
      "summary":            dict,
      "nmax":               dict,
      "warnings":           list[str],
    }

Steps (6, mismo orden que el legacy ``generar_prevision``):
  - check_state       -> helper.proc_generar_preview.proc_check_state
  - check_blocks      -> helper.proc_generar_preview.proc_check_blocks
  - build_slot_maps   -> helper.proc_generar_preview.proc_build_slot_maps
  - compute_nmax      -> helper.proc_generar_preview.proc_compute_nmax
  - export_and_diff   -> helper.proc_generar_preview.proc_export_and_diff
  - done              -> (interno: vuelco ``ctx.result`` a ``self.result``)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from core.composition.plc_function_base import FunctionBase
from core.runtime.app_state import AppState, get_app_state

logger = logging.getLogger(__name__)


class FunctionProcGenerarPreview(FunctionBase):
    """FB que calcula el diff completo (comentarios + N_MAX) de un proceso."""

    # ==================================================================
    # CONFIGURACION ESTATICA DEL FB
    # ==================================================================

    # Exporta 2 DBs (.s7dcl + .s7res) + parsea N_MAX de 1 tabla.
    # TIA V21 puede tardar 1-3 min en PLCs grandes. 180s cubre holgadamente.
    STEP_TIMEOUT_S: float = 180.0

    # ==================================================================
    # CONSTRUCTOR
    # ==================================================================

    def __init__(
        self,
        nombre: str = "proc_generar_preview",
        titulo: str = "Generar preview de comentarios del proceso",
        steps: list[dict[str, Any]] | None = None,
        tracker: Any = None,
        # ── ZONA 0: deps comunes ──
        config_manager: Any = None,
        tia_client: Any = None,
        build_cache: Any = None,
        # ── Deps especificas de este FB ──
        app_state: AppState | None = None,
        bloques_cache: Any = None,
    ) -> None:
        super().__init__(
            nombre=nombre,
            titulo=titulo,
            steps=steps if steps is not None else [
                {"nombre": "check_state"},
                {"nombre": "check_blocks"},
                {"nombre": "build_slot_maps"},
                {"nombre": "compute_nmax"},
                {"nombre": "export_and_diff"},
                {"nombre": "done"},
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
        # ``bloques_cache`` viene del gateway (``_bloques_cache`` del
        # TIAProcessGateway, poblado por ``scan_plc_blocks``). El router
        # lo inyecta explicitamente porque el FB no tiene acceso directo
        # al gateway.
        self._bloques_cache = bloques_cache
        # ZONA 3: estado entre ticks.
        self._plc_name: str = ""
        self._proc_uid: int = 0
        # ProcPreviewContext compartido entre los 6 ticks. Se
        # reinicializa en cada on_start() para no arrastrar estado del
        # run anterior (el FB es re-arrancable).
        self._ctx: Any = None

    # ==================================================================
    # HOOK 1: on_start  (ZONA 3: validar params + crear ctx)
    # ==================================================================

    def on_start(self, **params: Any) -> None:
        """Validar deps inyectadas + capturar plc_name + proc_uid + crear ctx.

        ``bloques_cache`` puede inyectarse por constructor (test) o
        leerse del singleton ``TIADataBloqueCache._caches`` (dict de
        clase, acceso sync) si el FB se registro en el engine sin esa
        dep (caso comun en prod).
        """
        if self._config is None:
            raise RuntimeError(
                "FunctionProcGenerarPreview requiere config_manager. "
                "Inyectalo en el constructor al registrar el FB."
            )
        if self._tia_client is None:
            raise RuntimeError(
                "FunctionProcGenerarPreview requiere tia_client. "
                "Inyectalo en el constructor al registrar el FB."
            )
        plc_name = params.get("plc_name")
        if not plc_name:
            raise ValueError(
                "FunctionProcGenerarPreview.start(plc_name=...) es obligatorio"
            )
        proc_uid = params.get("proc_uid")
        if proc_uid is None or not isinstance(proc_uid, int):
            raise ValueError(
                "FunctionProcGenerarPreview.start(proc_uid=int) es obligatorio"
            )
        self._plc_name = str(plc_name)
        self._proc_uid = proc_uid

        # Si bloques_cache no se inyecta por constructor, leemos del
        # singleton sync (acceso directo al dict de clase). Esto permite
        # que el FB funcione tanto en tests (inyeccion directa) como
        # en prod (singleton). El FB se re-arranca por cada operacion,
        # asi que un snapshot al start es suficiente.
        if self._bloques_cache is None:
            from core.infrastructure.tia.tia_bloque_cache import (
                TIADataBloqueCache,
            )
            self._bloques_cache = TIADataBloqueCache._caches.get(
                self._plc_name
            )

        # Crear el ProcPreviewContext que las 5 funciones iran mutando.
        # Lazy import para evitar ciclo con helpers/proc/.
        from areas.alimentacion.helpers.proc.proc_generar_preview import (
            ProcPreviewContext,
        )
        self._ctx = ProcPreviewContext(
            plc_name=self._plc_name,
            proc_uid=self._proc_uid,
            tia_client=self._tia_client,
            config_manager=self._config,
            app_state=self._state,
            build_cache_root=self._build_cache_root,
            bloques_cache=self._bloques_cache,
        )

        logger.debug(
            f"[{self.nombre}] Iniciando preview del proceso "
            f"{self._proc_uid} en {self._plc_name}"
        )

    # ==================================================================
    # HOOK 2: run_step  (ZONA 4: state machine -> dispatch al helper)
    # ==================================================================

    async def run_step(self, idx: int, **params: Any) -> str:
        """Dispatch del FB step ``idx`` a la funcion del helper ``proc_generar_preview``.

        Aqui vive la state machine: cada step del FB llama a UNA
        funcion del helper contra el ``ProcPreviewContext`` compartido.
        El ``case`` es explicito (no dict.get dispatch) para que sea
        visible en stack traces cuando algo falla.
        """
        # Lazy import para evitar ciclo con helpers/proc/.
        from areas.alimentacion.helpers.proc import proc_generar_preview

        if self._ctx is None:
            raise RuntimeError(
                "ProcPreviewContext no inicializado. on_start() no se ejecuto "
                "(o el FB no recibio un plc_name/proc_uid valido)."
            )

        step_nombre = self.steps[idx]["nombre"]
        match step_nombre:
            case "check_state":
                proc_generar_preview.proc_check_state(self._ctx)
            case "check_blocks":
                proc_generar_preview.proc_check_blocks(self._ctx)
            case "build_slot_maps":
                proc_generar_preview.proc_build_slot_maps(self._ctx)
            case "compute_nmax":
                await proc_generar_preview.proc_compute_nmax(self._ctx)
            case "export_and_diff":
                await proc_generar_preview.proc_export_and_diff(self._ctx)
            case "done":
                # ``proc_compose_response`` compone ``ctx.result``; el FB
                # lo vuelca a ``self.result`` en ``on_finish``. Aqui
                # solo aseguramos que se llama.
                proc_generar_preview.proc_compose_response(self._ctx)
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
            # Error temprano: deps no inyectadas o params ausentes.
            self.result = {
                "precondiciones_ok": False,
                "missing_blocks": [
                    "ProcPreviewContext no inicializado. "
                    "Verifica plc_name y proc_uid."
                ],
                "arrays": {},
                "summary": {"total": 0, "agregados": 0, "renombrados": 0,
                            "eliminados": 0, "sin_cambios": 0},
                "warnings": [],
            }
            return

        self.result = self._ctx.result

        # Log de cierre, igual que hacia el use case legacy.
        s = self._ctx.result.get("summary", {})
        nmax_summary = self._ctx.result.get("nmax", {}).get("summary", {})
        logger.debug(
            f"[{self.nombre}] preview calculado para proceso "
            f"{self._ctx.proc_uid} en {self._ctx.plc_name}: "
            f"{s.get('agregados', 0)} agregar, "
            f"{s.get('renombrados', 0)} renombrar, "
            f"{s.get('eliminados', 0)} eliminar, "
            f"{nmax_summary.get('actualizar', 0)} N_MAX actualizar"
        )


def _step_summary(ctx: Any, step_nombre: str) -> str:
    """Resumen legible del step que acaba de correr (aparece en la SPA)."""
    if step_nombre == "check_state":
        return (
            f"{step_nombre}: "
            f"{'OK' if ctx.excel_loaded else 'Excel no cargado'}"
        )
    if step_nombre == "check_blocks":
        return (
            f"{step_nombre}: "
            f"{'OK' if ctx.bloques_loaded else 'Sin cache de bloques'}"
        )
    if step_nombre == "build_slot_maps":
        if ctx.slot_map is None:
            return (
                f"{step_nombre}: "
                f"error: {ctx.slot_map_error or 'sin slot_map'}"
            )
        return (
            f"{step_nombre}: PReal={len(ctx.slot_map.preal)} "
            f"PInt={len(ctx.slot_map.pint)} ALM={len(ctx.slot_map.alm)}"
        )
    if step_nombre == "compute_nmax":
        nmax_summary = ctx.nmax_block.get("summary", {})
        return (
            f"{step_nombre}: {nmax_summary.get('actualizar', 0)} N_MAX "
            f"actualizar, {nmax_summary.get('sin_cambios', 0)} sin cambios"
        )
    if step_nombre == "export_and_diff":
        if ctx.export_error:
            return f"{step_nombre}: error: {ctx.export_error}"
        s = ctx.result.get("summary", {})
        return (
            f"{step_nombre}: {s.get('total', 0)} slots: "
            f"{s.get('renombrados', 0)} renombrar, "
            f"{s.get('agregados', 0)} agregar, "
            f"{s.get('sin_cambios', 0)} sin cambios"
        )
    if step_nombre == "done":
        return f"{step_nombre}: preview compuesto"
    return f"{step_nombre}: OK"


__all__ = ["FunctionProcGenerarPreview"]
