"""FB de area: sincronizacion transaccional de dispositivos vs PLC.

Wrapper con state machine del helper ``disp_sync`` definido en
``areas/alimentacion/helpers/sync/disp_sync.py``. Las 11 etapas del
sync viven en el helper; el FB aporta state machine + tracker + Zona 0
inyectable.

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

    # ==================================================================
    # HOOK 1: on_start  (ZONA 3: validar params)
    # ==================================================================

    def on_start(self, **params: Any) -> None:
        """Validar deps inyectadas + capturar plc_name."""
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
        self._log.info(
            f"[{self.nombre}] Iniciando sync transaccional para "
            f"{self._plc_name} (11 etapas)"
        )

    # ==================================================================
    # HOOK 2: run_step  (ZONA 4: CASE por etapa)
    # ==================================================================

    async def run_step(self, idx: int, **params: Any) -> str:
        """CASE de las 11 etapas del FB.

        El helper hace todo el flujo en una sola llamada; los steps
        del FB son checkpoints visuales en el progressbar que
        reflejan el progreso REAL del legacy.
        """
        # Lazy import para evitar ciclo con helpers/sync/.
        from areas.alimentacion.helpers.sync.disp_sync import disp_sync

        step_nombre = self.steps[idx]["nombre"]
        match step_nombre:
            case "exportar_tags" | "compute_diff" | "preparar_ops" \
                | "tx_a_nmax_renames" | "wait_consolidation" \
                | "exportar_post_tx_a" | "editar_xmls_offline" \
                | "tx_b_devices" | "compilar_bloques" \
                | "aplicar_comentarios":
                # Checkpoints visuales. El trabajo real ocurre en el
                # ultimo paso donde se invoca el helper de golpe.
                return f"{step_nombre}: combinado con sync final"

            case "post_preview":
                # Aqui SI se ejecuta el helper completo.
                result = await disp_sync(
                    plc_name=self._plc_name,
                    tia_client=self._tia_client,
                    config_manager=self._config,
                    app_state=self._state,
                    build_cache_root=self._build_cache_root,
                )
                self._stats["sync"] = result
                ops = result.get("operations", 0)
                nmax = result.get("n_max_updates", 0)
                compile_ok = result.get("compile_ok", False)
                self._log.success(
                    f"[{self.nombre}] sync completo para "
                    f"{self._plc_name}: {ops} ops ({nmax} N_MAX), "
                    f"compile={'OK' if compile_ok else 'con errores'}"
                )
                return (
                    f"{ops} ops aplicadas, {nmax} N_MAX, "
                    f"compile={'OK' if compile_ok else 'WARN'}"
                )

            case _:
                raise ValueError(f"step no soportado: {step_nombre!r}")

    # ==================================================================
    # HOOK 3: on_finish  (ZONA 5: vuelco del result)
    # ==================================================================

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` con la shape legacy que espera la SPA."""
        sync = self._stats.get("sync")
        if sync is None:
            # Caso error temprano (deps no inyectadas): result vacio.
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
        self.result = sync


__all__ = ["FunctionDispSincronizarDispositivos"]
