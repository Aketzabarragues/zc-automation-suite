"""FB de area: sincronizar comentarios por instancia de los 6 DBs de disp.

Wrapper con state machine del helper ``apply_disp_comments`` definido
en ``areas/alimentacion/helpers/sync/disp_comment_sync.py``. La logica
pesada (export bulk + copytree + 6 dispatches al worker OT) vive en el
helper; el FB aporta state machine + progress_tracker + Zona 0
inyectable.

Hereda directo de ``FunctionBase`` (no del template) porque su logica
es especifica del area. Zona 0 con 4 deps comunes + 1 especifica.

Runtime params via ``start(**kwargs)``:
  - ``plc_name`` (str): nombre del PLC destino. Obligatorio.
  - ``build_cache_root`` (Path, opcional): raiz del BuildCache.
    Default ``<cwd>/.build_cache``.

El ``self.result`` se popula con la shape legacy esperada por la SPA
(el endpoint ``/api/v1/.../aplicar-comentarios-disp`` lo devuelve tal
cual)::

    {
      "plc_name":            str,
      "success":             True,
      "applied":             True,
      "operations_executed": int,
      "summary": {"disp_dbs_updated": int, "total_ops": int},
      "details":  list[dict],
      "warnings": list[str],
    }
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from core.composition.plc_function_base import FunctionBase
from core.runtime.app_state import AppState, get_app_state
from core.runtime.log_buffer import LogBuffer, get_log_buffer


class FunctionSincronizarDispComentarios(FunctionBase):
    """FB que sincroniza comentarios por instancia de los 6 DBs de disp."""

    # ==================================================================
    # CONFIGURACION ESTATICA DEL FB
    # ==================================================================

    # Apply pesado: export + copytree + 6 dispatches al worker OT.
    # TIA V21 puede tardar varios minutos; el timeout del gateway es
    # mayor que este (5s * n_ops) para cubrir el peor caso.
    STEP_TIMEOUT_S: float = 300.0

    # ==================================================================
    # CONSTRUCTOR
    # ==================================================================

    def __init__(
        self,
        nombre: str = "sincronizar_disp_comentarios",
        titulo: str = "Sincronizar comentarios por instancia (6 DBs)",
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
                {"nombre": "validar"},
                {"nombre": "build_slot_maps"},
                {"nombre": "exportar_bloques"},
                {"nombre": "aplicar_comentarios"},
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
        self._slot_maps_data: Any = None

    # ==================================================================
    # HOOK 1: on_start  (ZONA 3: validar params)
    # ==================================================================

    def on_start(self, **params: Any) -> None:
        """Validar deps inyectadas + capturar params."""
        if self._config is None:
            raise RuntimeError(
                "FunctionSincronizarDispComentarios requiere config_manager. "
                "Inyectalo en el constructor al registrar el FB."
            )
        if self._tia_client is None:
            raise RuntimeError(
                "FunctionSincronizarDispComentarios requiere tia_client. "
                "Inyectalo en el constructor al registrar el FB."
            )
        plc_name = params.get("plc_name")
        if not plc_name:
            raise ValueError(
                "FunctionSincronizarDispComentarios.start(plc_name=...) "
                "es obligatorio"
            )
        self._plc_name = str(plc_name)
        self._log.info(
            f"[{self.nombre}] Iniciando sync comentarios para "
            f"{self._plc_name}"
        )

    # ==================================================================
    # HOOK 2: run_step  (ZONA 4: CASE por etapa)
    # ==================================================================

    async def run_step(self, idx: int, **params: Any) -> str:
        """CASE de los 4 pasos del FB."""
        # Lazy import para evitar ciclo con helpers/sync/.
        from areas.alimentacion.data.data_DispSlotMap import disp_build_slot_maps
        from areas.alimentacion.helpers.sync.disp_comment_sync import (
            apply_disp_comments,
        )

        step_nombre = self.steps[idx]["nombre"]
        match step_nombre:
            case "validar":
                # Validacion ya hecha en on_start. Aqui confirmamos
                # que el AppState tiene dispositivos.
                if not self._state.all_devices():
                    self._log.warning(
                        f"[{self.nombre}] AppState vacio: no hay "
                        f"dispositivos cargados"
                    )
                    return "AppState vacio (no-op)"
                n = sum(
                    len(d) for d in self._state.all_devices().values()
                )
                return f"AppState OK ({n} dispositivos)"

            case "build_slot_maps":
                self._slot_maps_data = disp_build_slot_maps(
                    self._state, self._config,
                )
                n_maps = len(self._slot_maps_data.slot_maps)
                return f"{n_maps} slot_maps construidos"

            case "exportar_bloques":
                # La exportacion real ocurre dentro de apply_disp_comments.
                # Aqui solo marcamos el stage para que el progressbar
                # muestre la fase. La operacion combinada export +
                # apply se hace en el siguiente paso (todo bajo un
                # unico ``submit_and_wait`` al worker OT).
                return "combinado con aplicar (siguiente paso)"

            case "aplicar_comentarios":
                # El helper hace export + copytree + 6 dispatches en
                # una sola llamada. Es CPU/IO pesado (varios minutos).
                # Por eso STEP_TIMEOUT_S=300s y el helper_async usa
                # asyncio.to_thread para no bloquear el event loop.
                result = await apply_disp_comments(
                    plc_name=self._plc_name,
                    app_state=self._state,
                    config_manager=self._config,
                    build_cache_root=self._build_cache_root,
                    tia_client=self._tia_client,
                )
                self._stats["aplicar_comentarios"] = result
                n_ops = result.get("operations_executed", 0)
                self._log.success(
                    f"[{self.nombre}] {n_ops} DBs actualizados en "
                    f"{self._plc_name}"
                )
                return f"{n_ops} DBs actualizados"

            case _:
                raise ValueError(f"step no soportado: {step_nombre!r}")

    # ==================================================================
    # HOOK 3: on_finish  (ZONA 5: vuelco del result)
    # ==================================================================

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` con la shape legacy que espera la SPA."""
        apply_stats = self._stats.get("aplicar_comentarios")
        if apply_stats is None:
            # Caso no-op: AppState vacio o error temprano.
            self.result = {
                "plc_name": self._plc_name,
                "success": True,
                "applied": True,
                "operations_executed": 0,
                "summary": {"disp_dbs_updated": 0, "total_ops": 0},
                "details": [],
                "warnings": ["AppState vacio"],
            }
            return
        self.result = apply_stats


__all__ = ["FunctionSincronizarDispComentarios"]
