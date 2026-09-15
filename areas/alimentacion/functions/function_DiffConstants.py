"""FB de area: diff de PlcUserConstant (N_MAX + Dispositivos).

Wrapper con state machine del motor puro de diffs definido en
``areas/alimentacion/helpers/sync/diff_constants.py``. No hace I/O
contra TIA Portal: ambos metodos del helper son funciones puras.

Hereda directo de ``FunctionBase`` (no del template) porque su logica
es especifica y no aporta Zona 0 generica. La unica dep inyectada
es ``log`` (consistencia con el resto de FBs del area).

Runtime params via ``start(**kwargs)``:
  - ``plc_name`` (str): nombre del PLC. Obligatorio.
  - ``config_table_name`` (str): tabla de PlcUserConstant destino.
  - ``current_nmax_state`` (dict): ``{nombre: valor_int}`` desde TIA.
  - ``desired_nmax_state`` (dict): ``{nombre: valor_int}`` desde Excel.
  - ``current_device_state`` (dict): ``{valor_int_str: nombre}`` desde TIA.
  - ``desired_device_state`` (dict): ``{nombre: valor_int}`` desde Excel.

El ``self.result`` se popula con la shape::
    {
        "nmax_ops":   [{"command": "update_user_constant_value", "args": {...}}],
        "rename_ops": [{"command": "update_user_constant_name", "args": {...}}],
        "summary": {"nmax": N, "rename": M, "total": N+M},
    }
"""
from __future__ import annotations

from typing import Any

from core.composition.plc_function_base import FunctionBase
from core.runtime.log_buffer import LogBuffer, get_log_buffer


class FunctionDiffConstants(FunctionBase):
    """FB que calcula los diffs de PlcUserConstant (N_MAX + devices)."""

    # ==================================================================
    # CONFIGURACION ESTATICA DEL FB
    # ==================================================================

    # Como el helper es CPU puro (sin I/O), un timeout generoso cubre
    # diffs grandes (cientos de PlcUserConstant).
    STEP_TIMEOUT_S: float = 30.0

    # ==================================================================
    # CONSTRUCTOR
    # ==================================================================

    def __init__(
        self,
        nombre: str = "diff_constants",
        titulo: str = "Calcular diffs de PlcUserConstant (N_MAX + dispositivos)",
        steps: list[dict[str, Any]] | None = None,
        tracker: Any = None,
        # ── ZONA 0: deps comunes (minimas, FB puro) ──
        log: Any = None,
    ) -> None:
        super().__init__(
            nombre=nombre,
            titulo=titulo,
            steps=steps if steps is not None else [
                {"nombre": "validar"},
                {"nombre": "computar"},
            ],
            tracker=tracker,
        )
        self._log: LogBuffer = log if log is not None else get_log_buffer()

        # ZONA 3: estado entre ticks.
        self._plc_name: str = ""
        self._config_table_name: str = ""
        self._current_nmax: dict[str, int] = {}
        self._desired_nmax: dict[str, int] = {}
        self._current_device: dict[str, str] = {}
        self._desired_device: dict[str, int] = {}

    # ==================================================================
    # HOOK 1: on_start  (ZONA 3: capturar y validar params)
    # ==================================================================

    def on_start(self, **params: Any) -> None:
        """Capturar y validar los 6 params del FB."""
        plc_name = params.get("plc_name")
        if not plc_name:
            raise ValueError(
                "FunctionDiffConstants.start(plc_name=...) es obligatorio"
            )
        config_table_name = params.get("config_table_name")
        if not config_table_name:
            raise ValueError(
                "FunctionDiffConstants.start(config_table_name=...) "
                "es obligatorio"
            )
        for key in (
            "current_nmax_state",
            "desired_nmax_state",
            "current_device_state",
            "desired_device_state",
        ):
            if not isinstance(params.get(key), dict):
                raise ValueError(
                    f"FunctionDiffConstants.start({key}=dict) es obligatorio"
                )

        self._plc_name = str(plc_name)
        self._config_table_name = str(config_table_name)
        self._current_nmax = params["current_nmax_state"]
        self._desired_nmax = params["desired_nmax_state"]
        self._current_device = params["current_device_state"]
        self._desired_device = params["desired_device_state"]

        self._log.info(
            f"[{self.nombre}] Calculando diffs para {self._plc_name} "
            f"(tabla {self._config_table_name}): "
            f"N_MAX {len(self._current_nmax)}/{len(self._desired_nmax)}, "
            f"devices {len(self._current_device)}/{len(self._desired_device)}"
        )

    # ==================================================================
    # HOOK 2: run_step  (ZONA 4: CASE por etapa)
    # ==================================================================

    async def run_step(self, idx: int, **params: Any) -> str:
        """CASE de los 2 pasos del FB."""
        # Lazy import para evitar ciclo con helpers/sync/diff_constants.
        from areas.alimentacion.helpers.sync.diff_constants import (
            calculate_device_rename_diff,
            calculate_nmax_diff,
        )

        step_nombre = self.steps[idx]["nombre"]
        match step_nombre:
            case "validar":
                # Pre-flight: confirma que los 4 estados no son vacios
                # (puede ser legitimo que lo sean si el Excel esta
                # vacio, pero avisamos al operario).
                if not any([
                    self._current_nmax, self._desired_nmax,
                    self._current_device, self._desired_device,
                ]):
                    self._log.warning(
                        f"[{self.nombre}] los 4 estados estan vacios: "
                        f"diff saldra sin operaciones"
                    )
                return "OK"

            case "computar":
                nmax_ops = calculate_nmax_diff(
                    plc_name=self._plc_name,
                    config_table_name=self._config_table_name,
                    current_state=self._current_nmax,
                    desired_state=self._desired_nmax,
                )
                rename_ops = calculate_device_rename_diff(
                    plc_name=self._plc_name,
                    config_table_name=self._config_table_name,
                    current_state=self._current_device,
                    desired_state=self._desired_device,
                )
                self._stats["computar"] = {
                    "nmax_ops": nmax_ops,
                    "rename_ops": rename_ops,
                    "n_nmax": len(nmax_ops),
                    "n_rename": len(rename_ops),
                }
                self._log.success(
                    f"[{self.nombre}] diff calculado: "
                    f"{len(nmax_ops)} N_MAX + {len(rename_ops)} renames"
                )
                return (
                    f"{len(nmax_ops)} N_MAX + {len(rename_ops)} renames"
                )

            case _:
                raise ValueError(f"step no soportado: {step_nombre!r}")

    # ==================================================================
    # HOOK 3: on_finish  (ZONA 5: vuelco del result)
    # ==================================================================

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` con la lista de ops + summary."""
        stats = self._stats.get("computar", {})
        nmax_ops = stats.get("nmax_ops", [])
        rename_ops = stats.get("rename_ops", [])
        n_nmax = stats.get("n_nmax", len(nmax_ops))
        n_rename = stats.get("n_rename", len(rename_ops))
        self.result = {
            "nmax_ops": nmax_ops,
            "rename_ops": rename_ops,
            "summary": {
                "nmax": n_nmax,
                "rename": n_rename,
                "total": n_nmax + n_rename,
            },
        }


__all__ = ["FunctionDiffConstants"]
