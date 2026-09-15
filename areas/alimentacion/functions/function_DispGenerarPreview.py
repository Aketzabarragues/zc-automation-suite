"""FB de area: generar la prevision (diff completo) de dispositivos vs PLC.

Wrapper con state machine del helper ``disp_generate_preview``
definido en ``areas/alimentacion/helpers/sync/disp_generate_preview.py``.

El FB aporta state machine + progress_tracker + Zona 0 inyectable. La
logica pesada (export bulk + diff read-only en hilo) vive en el helper.

Hereda directo de ``FunctionBase`` (no del template) porque su logica
es especifica del area. Zona 0 con 4 deps comunes + 1 especifica.

Runtime params via ``start(**kwargs)``:
  - ``plc_name`` (str): nombre del PLC destino. Obligatorio.

El ``self.result`` se popula con la shape legacy esperada por la SPA
(el endpoint ``/api/v1/plcs/<name>/preview`` lo devuelve tal cual)::

    {
      'agregados':   [{uid, table, plc_tag}],
      'eliminados':  [{uid, table, plc_tag}],
      'renombrados': [{uid, table, actual, nuevo}],
      'todos':       [...],
      'nmax':        {current, desired, todos, summary},
      'summary':     {agregados, eliminados, renombrados, sin_cambios, total},
    }

Steps (4, alineados con el legacy):
  - exportar_tags
  - compute_devices
  - compute_nmax
  - build_response
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

    # ==================================================================
    # HOOK 1: on_start  (ZONA 3: validar params)
    # ==================================================================

    def on_start(self, **params: Any) -> None:
        """Validar deps inyectadas + capturar plc_name."""
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
        self._log.info(
            f"[{self.nombre}] Iniciando preview de {self._plc_name}"
        )

    # ==================================================================
    # HOOK 2: run_step  (ZONA 4: CASE por etapa)
    # ==================================================================

    async def run_step(self, idx: int, **params: Any) -> str:
        """CASE de los 4 pasos del FB.

        El helper hace la export + diff + build completo en una sola
        llamada; los steps del FB son checkpoints visuales en el
        progressbar. Esto refleja el progreso REAL que el operador
        quiere ver: primero export, luego devices, luego N_MAX,
        luego respuesta.
        """
        # Lazy import para evitar ciclo con helpers/sync/.
        from areas.alimentacion.helpers.sync.disp_generate_preview import (
            disp_generate_preview,
        )

        step_nombre = self.steps[idx]["nombre"]
        match step_nombre:
            case "exportar_tags":
                # El helper hace el export dentro de la llamada final;
                # aqui solo marcamos el stage.
                return "combinado con compute (siguiente paso)"

            case "compute_devices":
                # Aqui tampoco hay progreso real separado; el helper
                # calcula todo de golpe. Devolvemos el stage para el
                # progressbar.
                return "combinado con compute_nmax (siguiente paso)"

            case "compute_nmax":
                # Unica llamada que ejecuta TODO el helper.
                result = await disp_generate_preview(
                    plc_name=self._plc_name,
                    tia_client=self._tia_client,
                    config_manager=self._config,
                    app_state=self._state,
                    build_cache_root=self._build_cache_root,
                )
                self._stats["preview"] = result
                s = result["summary"]
                self._log.success(
                    f"[{self.nombre}] preview calculado para "
                    f"{self._plc_name}: "
                    f"{s['agregados']} agregados, {s['eliminados']} "
                    f"eliminados, {s['renombrados']} renombrados, "
                    f"{result['nmax']['summary']['actualizar']} N_MAX "
                    f"actualizar"
                )
                return (
                    f"{s['agregados']} agregados, {s['eliminados']} "
                    f"eliminados, {s['renombrados']} renombrados"
                )

            case "build_response":
                # El result ya esta en _stats del paso anterior.
                # Este step es solo para completar el progressbar con
                # 4 etapas (alineado con el legacy).
                preview = self._stats.get("preview")
                if preview is None:
                    raise RuntimeError(
                        "build_response: compute_nmax no dejo preview "
                        "en _stats"
                    )
                s = preview["summary"]
                return (
                    f"{s['total']} entradas en vista unificada"
                )

            case _:
                raise ValueError(f"step no soportado: {step_nombre!r}")

    # ==================================================================
    # HOOK 3: on_finish  (ZONA 5: vuelco del result)
    # ==================================================================

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` con la shape legacy que espera la SPA."""
        preview = self._stats.get("preview")
        if preview is None:
            # Caso error temprano (deps no inyectadas): result vacio.
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
        self.result = preview


__all__ = ["FunctionDispGenerarPreview"]
