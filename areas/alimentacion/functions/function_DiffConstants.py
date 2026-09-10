"""Function block: diff de PlcUserConstant (N_MAX + Dispositivos).

Fase 2, paso 2.1.8.  Encapsula la clase
``DispCalculateConstantsDiffUseCase`` (areas/alimentacion/application/
use_cases/disp_diff_constants.py:38) — motor puro de diffs para
PlcUserConstant del área de alimentación.

A diferencia del resto de FBs de Fase 2, este NO hace I/O contra
TIA Portal: los métodos del use case son ``@staticmethod`` puros.
El FB es un wrapper con state machine para mantener la coherencia
con el patrón (engine-friendly, observable, best-effort).

State machine:
  nStep=10  arrancar    (pre-flight: validar plc_name +
                         config_table_name + los 4 estados
                         current/desired de N_MAX y devices)
  nStep=20  computar    (delegar a ``use_case.calculate_nmax_diff`` y
                         ``use_case.calculate_device_rename_diff``;
                         método sync, await innecesario pero la firma
                         es ``async def`` para mantener interfaz
                         uniforme con el resto de FBs)
  nStep=30  finalizar   (set ``self.result`` con la lista de ops +
                         summary, transita a ``n_done``)
  nStep=99  done        (terminal OK)
  nStep=98  error       (terminal con error_msg)

Decisión de diseño:
  El use case expone DOS métodos (``calculate_nmax_diff`` y
  ``calculate_device_rename_diff``) que comparten firma.  El FB
  encapsula AMBOS en una sola invocación: ``start()`` recibe los
  4 estados (current_nmax, desired_nmax, current_devices,
  desired_devices) y ``self.result`` es un dict con
  ``{nmax_ops, rename_ops, summary}``.  Esto da al router
  (2.2.1) un único punto de entrada para "calcular todos los
  diffs de constantes de un PLC".

Trade-offs:
  - El FB NO llama ``progress.begin()``/``finish()`` (caller las
    hace).  Como no hay I/O, los stages son opcionales.
  - El FB NO lanza ``HTTPException`` (transport-agnostic).
  - ``self.result`` es::

        {
            "nmax_ops":   [{"command": "update_user_constant_value", "args": {...}}],
            "rename_ops": [{"command": "update_user_constant_name", "args": {...}}],
            "summary": {"nmax": N, "rename": M, "total": N+M},
        }
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from areas.alimentacion.application.use_cases.disp_diff_constants import (
    DispCalculateConstantsDiffUseCase,
)
from core.plc.function_base import FunctionBase

logger = logging.getLogger(__name__)


class FunctionDiffConstants(FunctionBase):
    """FB que calcula los diffs de PlcUserConstant (N_MAX + devices).

    API:
      - ``start(**kwargs)`` con:
          - ``plc_name`` (str): nombre del PLC.
          - ``config_table_name`` (str): tabla donde residen las
            PlcUserConstant (ej. ``2000_Disp_ED``).
          - ``current_nmax_state`` (dict): ``{nombre: valor_int}`` desde TIA.
          - ``desired_nmax_state`` (dict): ``{nombre: valor_int}`` desde el Excel.
          - ``current_device_state`` (dict): ``{valor_int_str: nombre}`` desde TIA.
          - ``desired_device_state`` (dict): ``{nombre: valor_int}`` desde el Excel.
      - Tras ``n_done``, ``self.result`` tiene::

            {
                "nmax_ops":   [op, ...],
                "rename_ops": [op, ...],
                "summary": {"nmax": N, "rename": M, "total": N+M},
            }

    El FB es puro (sin I/O, sin gateway, sin TIA).  ``use_case_factory``
    permite inyectar un use case mock para tests.
    """

    def __init__(
        self,
        nombre: str = "diff_constants",
        use_case_factory: Callable[[], type[DispCalculateConstantsDiffUseCase]] | None = None,
    ) -> None:
        super().__init__(nombre)
        # ``use_case_factory`` (si se inyecta) es un callable que retorna
        # la clase del use case (con sus métodos estáticos).  Eager: lo
        # llamamos una vez en ``__init__`` para tener la clase lista.
        # Si es ``None``, usamos la clase real.
        self._use_case_cls: type[DispCalculateConstantsDiffUseCase] = (
            use_case_factory() if use_case_factory is not None
            else DispCalculateConstantsDiffUseCase
        )
        # Estado entre ticks
        self._plc_name: str = ""
        self._config_table_name: str = ""
        self._current_nmax: dict[str, int] = {}
        self._desired_nmax: dict[str, int] = {}
        self._current_device: dict[str, str] = {}
        self._desired_device: dict[str, int] = {}
        self._nmax_ops: list[dict[str, Any]] = []
        self._rename_ops: list[dict[str, Any]] = []

    async def _tick_locked(self) -> None:
        assert self._lock.locked()
        if self.nStep == 10:
            self._step_arrancar()
        elif self.nStep == 20:
            self._step_computar()
        elif self.nStep == 30:
            self._step_finalizar()

    # ------------------------------------------------------------------
    # Pasos del state machine
    # ------------------------------------------------------------------

    def _step_arrancar(self) -> None:
        """nStep=10→20: pre-flight.  Valida params y captura estados."""
        plc_name = self._params.get("plc_name")
        if not plc_name:
            raise ValueError(
                "FunctionDiffConstants.start(plc_name=...) es obligatorio"
            )
        config_table_name = self._params.get("config_table_name")
        if not config_table_name:
            raise ValueError(
                "FunctionDiffConstants.start(config_table_name=...) "
                "es obligatorio"
            )
        for key in (
            "current_nmax_state", "desired_nmax_state",
            "current_device_state", "desired_device_state",
        ):
            if not isinstance(self._params.get(key), dict):
                raise ValueError(
                    f"FunctionDiffConstants.start({key}=dict) es obligatorio"
                )

        self._plc_name = plc_name
        self._config_table_name = config_table_name
        self._current_nmax = self._params["current_nmax_state"]
        self._desired_nmax = self._params["desired_nmax_state"]
        self._current_device = self._params["current_device_state"]
        self._desired_device = self._params["desired_device_state"]
        self.nStep = 20

    def _step_computar(self) -> None:
        """nStep=20→30: calcula ambos diffs vía los métodos estáticos
        del use case legacy.

        Como los métodos son ``@staticmethod``, NO instanciamos el
        use case: los llamamos directamente sobre la clase.  La
        ``use_case_factory`` (si se inyecta) reemplaza la clase
        entera, lo cual es la forma natural de mockear métodos
        estáticos en Python.
        """
        self._nmax_ops = self._use_case_cls.calculate_nmax_diff(
            plc_name=self._plc_name,
            config_table_name=self._config_table_name,
            current_state=self._current_nmax,
            desired_state=self._desired_nmax,
        )
        self._rename_ops = self._use_case_cls.calculate_device_rename_diff(
            plc_name=self._plc_name,
            config_table_name=self._config_table_name,
            current_state=self._current_device,
            desired_state=self._desired_device,
        )
        self.nStep = 30

    def _step_finalizar(self) -> None:
        """nStep=30→99: set ``self.result`` con la lista de ops + summary."""
        n_nmax = len(self._nmax_ops)
        n_rename = len(self._rename_ops)
        self.result = {
            "nmax_ops": self._nmax_ops,
            "rename_ops": self._rename_ops,
            "summary": {"nmax": n_nmax, "rename": n_rename, "total": n_nmax + n_rename},
        }
        self.nStep = self.n_done
