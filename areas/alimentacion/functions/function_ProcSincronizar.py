"""FB de area: sincronizacion transaccional de comentarios de un
proceso contra TIA Portal (DB_PARAM + DB_ALM).

State machine sobre el helper ``proc_sincronizar``
(areas/alimentacion/helpers/proc/proc_sincronizar.py). El helper
expone funciones independientes (``proc_check_state_commit``,
``proc_check_blocks_commit``, ``proc_build_slot_maps_commit``,
``proc_open_transaction``, ``proc_done_summary_commit``) que
reciben un ``ProcSyncContext`` y mutan sus campos. **Aqui en el FB
vive la state machine**: el orden de las 5 llamadas, el mapping
step -> funcion del helper, y la instanciacion del ctx.

Antes (sept-2026 -): 1 use case legacy monolitico
(``ejecutar_transaccion``) en
``application/use_cases/proc_sync_comentarios.py``.

Despues (sept-2026): cada step del FB ejecuta una funcion real del
helper contra el ``ProcSyncContext`` compartido entre los 5 ticks.

Hereda directo de ``FunctionBase`` (no del template). Zona 0 con 5
deps comunes (incluyendo ``bloques_cache`` que el legacy inyectaba
manualmente).

Runtime params via ``start(**kwargs)``:
  - ``proc_uid`` (int): uid del proceso. Obligatorio.
  - ``plc_name`` (str): nombre del PLC destino. Obligatorio.

El ``self.result`` se popula con la shape legacy esperada por la SPA::

    {
      "proc_uid":             int,
      "plc_name":             str,
      "success":              True,
      "applied":              True,
      "operations_executed":  int,
      "details":              list[dict],
      "warnings":             list[str],
    }

Steps (8, orden nuevo sept-2026 con Tx A N_MAX + compile previo):
  - check_state_commit       -> helper.proc_sincronizar.proc_check_state_commit
  - check_blocks_commit      -> helper.proc_sincronizar.proc_check_blocks_commit
  - build_slot_maps_commit   -> helper.proc_sincronizar.proc_build_slot_maps_commit
  - sync_nmax                -> helper.proc_sincronizar.proc_sync_nmax
                                (Tx A N_MAX online, INCONDICIONAL)
  - wait_consolidation       -> helper.proc_sincronizar.proc_wait_consolidation
                                (sleep 2s; TIA consolida tras Tx A)
  - compile_proc_blocks      -> helper.proc_sincronizar.proc_compile_blocks
                                (resize de DBs PARAM/ALM en TIA)
  - open_transaction         -> helper.proc_sincronizar.proc_open_transaction
                                (Tx B: comentarios sobre DBs ya redimensionados)
  - done                     -> (interno: vuelco ``ctx.result`` a ``self.result``)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from core.composition.plc_function_base import FunctionBase
from core.runtime.app_state import AppState, get_app_state

logger = logging.getLogger(__name__)


class FunctionProcSincronizar(FunctionBase):
    """FB que aplica comentarios del proceso contra TIA en una sola TX."""

    # ==================================================================
    # CONFIGURACION ESTATICA DEL FB
    # ==================================================================

    # Sync completo: 1 transaccion TIA con 2 sub-comandos
    # (``update_proc_comments_db_param`` + ``update_proc_comments_db_alm``).
    # TIA V21 puede tardar 1-3 min en PLCs grandes.
    STEP_TIMEOUT_S: float = 300.0

    # ==================================================================
    # CONSTRUCTOR
    # ==================================================================

    def __init__(
        self,
        nombre: str = "proc_sincronizar",
        titulo: str = "Sincronizar comentarios del proceso contra PLC",
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
                {"nombre": "check_state_commit"},
                {"nombre": "check_blocks_commit"},
                {"nombre": "build_slot_maps_commit"},
                {"nombre": "sync_nmax"},
                {"nombre": "wait_consolidation"},
                {"nombre": "compile_proc_blocks"},
                {"nombre": "open_transaction"},
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
        # ``bloques_cache`` viene del gateway; el router lo inyecta.
        self._bloques_cache = bloques_cache
        # ZONA 3: estado entre ticks.
        self._plc_name: str = ""
        self._proc_uid: int = 0
        # ProcSyncContext compartido entre los 5 ticks. Se
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
                "FunctionProcSincronizar requiere config_manager. "
                "Inyectalo en el constructor al registrar el FB."
            )
        if self._tia_client is None:
            raise RuntimeError(
                "FunctionProcSincronizar requiere tia_client. "
                "Inyectalo en el constructor al registrar el FB."
            )
        plc_name = params.get("plc_name")
        if not plc_name:
            raise ValueError(
                "FunctionProcSincronizar.start(plc_name=...) es obligatorio"
            )
        proc_uid = params.get("proc_uid")
        if proc_uid is None or not isinstance(proc_uid, int):
            raise ValueError(
                "FunctionProcSincronizar.start(proc_uid=int) es obligatorio"
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

        # Crear el ProcSyncContext que las 4 funciones iran mutando.
        # Lazy import para evitar ciclo con helpers/proc/.
        from areas.alimentacion.helpers.proc.proc_sincronizar import (
            ProcSyncContext,
        )
        self._ctx = ProcSyncContext(
            plc_name=self._plc_name,
            proc_uid=self._proc_uid,
            tia_client=self._tia_client,
            config_manager=self._config,
            app_state=self._state,
            build_cache_root=self._build_cache_root,
            bloques_cache=self._bloques_cache,
        )

        logger.debug(
            f"[{self.nombre}] Iniciando sync del proceso "
            f"{self._proc_uid} en {self._plc_name}"
        )

    # ==================================================================
    # HOOK 2: run_step  (ZONA 4: state machine -> dispatch al helper)
    # ==================================================================

    async def run_step(self, idx: int, **params: Any) -> str:
        """Dispatch del FB step ``idx`` a la funcion del helper ``proc_sincronizar``.

        Aqui vive la state machine: cada step del FB llama a UNA
        funcion del helper contra el ``ProcSyncContext`` compartido.
        El ``case`` es explicito (no dict.get dispatch) para que sea
        visible en stack traces cuando algo falla.
        """
        # Lazy import para evitar ciclo con helpers/proc/.
        from areas.alimentacion.helpers.proc import proc_sincronizar

        if self._ctx is None:
            raise RuntimeError(
                "ProcSyncContext no inicializado. on_start() no se ejecuto "
                "(o el FB no recibio un plc_name/proc_uid valido)."
            )

        step_nombre = self.steps[idx]["nombre"]
        match step_nombre:
            case "check_state_commit":
                proc_sincronizar.proc_check_state_commit(self._ctx)
                # Pre-flight: abortar con RuntimeError si no hay excel.
                if not self._ctx.excel_loaded:
                    raise RuntimeError(
                        "AppState.excel_cache esta vacio. "
                        "Cargue el Excel con POST /api/v1/excel/upload."
                    )
            case "check_blocks_commit":
                proc_sincronizar.proc_check_blocks_commit(self._ctx)
                if not self._ctx.bloques_loaded:
                    raise RuntimeError(
                        "Cache de bloques del PLC no disponible. "
                        "Selecciona el PLC en el sidebar y espera al "
                        "escaneo de bloques (1-3 min en PLCs grandes)."
                    )
            case "build_slot_maps_commit":
                proc_sincronizar.proc_build_slot_maps_commit(self._ctx)
                if self._ctx.slot_map is None:
                    raise RuntimeError(
                        "proc_build_slot_maps_commit no inicializo "
                        "ctx.slot_map. El helper fallo silenciosamente."
                    )
                if self._ctx.slot_map.missing_blocks:
                    raise RuntimeError(
                        f"Faltan bloques en el PLC: "
                        f"{self._ctx.slot_map.missing_blocks}"
                    )
                # Calcular nmax_ops ANTES del step sync_nmax. El helper
                # necesita slot_map (resuelto arriba) y dimensiones (en
                # app_state). Separamos el calculo del dispatch para
                # poder loguear el resultado del diff y abortar si
                # falla el parser, sin abrir Tx A.
                proc_sincronizar.proc_compute_nmax_ops(self._ctx)
                logger.debug(
                    f"[{self.nombre}] N_MAX diff: "
                    f"{len(self._ctx.nmax_ops)} ops a aplicar"
                )
            case "sync_nmax":
                # INCONDICIONAL (requisito del operario): aunque
                # ``ctx.nmax_ops=[]``, se despacha el handler. Asi el
                # flujo se ejecuta completo aunque ya estuvieran
                # aplicados.
                await proc_sincronizar.proc_sync_nmax(self._ctx)
            case "wait_consolidation":
                await proc_sincronizar.proc_wait_consolidation(self._ctx)
            case "compile_proc_blocks":
                await proc_sincronizar.proc_compile_blocks(self._ctx)
                if not self._ctx.compile_ok:
                    raise RuntimeError(
                        f"compile_proc_blocks reporto error: "
                        f"{self._ctx.compile_error}"
                    )
            case "open_transaction":
                await proc_sincronizar.proc_open_transaction(self._ctx)
            case "done":
                # ``proc_done_summary_commit`` compone ``ctx.result``;
                # el FB lo vuelca a ``self.result`` en ``on_finish``.
                proc_sincronizar.proc_done_summary_commit(self._ctx)
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
                "success": False,
                "applied": False,
                "operations_executed": 0,
                "details": [],
                "warnings": [
                    "ProcSyncContext no inicializado. "
                    "Verifica plc_name y proc_uid."
                ],
            }
            return

        self.result = self._ctx.result

        # Log de cierre, igual que hacia el use case legacy.
        ops_executed = self.result.get("operations_executed", 0)
        logger.debug(
            f"[{self.nombre}] sync completo para proceso "
            f"{self._ctx.proc_uid} en {self._ctx.plc_name}: "
            f"{ops_executed} ops aplicadas"
        )


def _step_summary(ctx: Any, step_nombre: str) -> str:
    """Resumen legible del step que acaba de correr (aparece en la SPA)."""
    if step_nombre == "check_state_commit":
        return (
            f"{step_nombre}: "
            f"{'OK' if ctx.excel_loaded else 'Excel no cargado'}"
        )
    if step_nombre == "check_blocks_commit":
        return (
            f"{step_nombre}: "
            f"{'OK' if ctx.bloques_loaded else 'Sin cache de bloques'}"
        )
    if step_nombre == "build_slot_maps_commit":
        if ctx.slot_map is None:
            return f"{step_nombre}: slot_map no inicializado"
        return (
            f"{step_nombre}: PReal={len(ctx.slot_map.preal)} "
            f"PInt={len(ctx.slot_map.pint)} ALM={len(ctx.slot_map.alm)}"
            f" N_MAX_ops={len(ctx.nmax_ops)}"
        )
    if step_nombre == "sync_nmax":
        ops = len(ctx.nmax_ops or [])
        return f"{step_nombre}: {ops} N_MAX aplicadas (incondicional)"
    if step_nombre == "wait_consolidation":
        return f"{step_nombre}: 2s sleep OK"
    if step_nombre == "compile_proc_blocks":
        if ctx.compile_ok:
            return f"{step_nombre}: OK"
        return f"{step_nombre}: ERROR ({ctx.compile_error})"
    if step_nombre == "open_transaction":
        ops = (ctx.tx_result or {}).get("operations_executed", 0)
        return f"{step_nombre}: {ops} ops aplicadas OK"
    if step_nombre == "done":
        return f"{step_nombre}: sync compuesto"
    return f"{step_nombre}: OK"


__all__ = ["FunctionProcSincronizar"]
