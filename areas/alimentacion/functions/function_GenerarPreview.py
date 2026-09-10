"""Function block: generar la previsión (diff) del sync de disp.

Fase 2, paso 2.1.4b.  Encapsula el método
``DispSyncInstancesUseCase.generar_prevision`` (areas/alimentacion/
application/use_cases/disp_sync_instances.py:119) en un
``FunctionBase`` con state machine ``nStep = 10 -> 20 -> 30 -> 99``
o ``98 (n_error)``.

State machine:
  nStep=10  arrancar    (pre-flight: validar gateway + config_manager
                         + plc_name)
  nStep=20  computar    (delegar a ``use_case.generar_prevision``;
                         emite los 4 stages del use case:
                         export_tags / compute_devices /
                         compute_nmax / build_response)
  nStep=30  finalizar   (set ``self.result`` con el shape legacy,
                         transita a ``n_done``)
  nStep=99  done        (terminal OK)
  nStep=98  error       (terminal con error_msg, vía wrapper de la base)

Decisión de diseño (documentada para 2.1.5-2.1.8):
  El método ``generar_prevision`` legacy es grande (~280 líneas) y
  hace I/O pesada (export bulk + diff read-only en hilo).  Copiar
  toda esa lógica al FB superaría el cap de 200 líneas del
  refactor.  El FB es un WRAPPER con state machine que delega al
  use case via lazy instantiation.  La "encapsulación" es la
  state machine (engine-friendly, observable, progress-tracked,
  best-effort).  El use case legacy hace el trabajo pesado; cuando
  en 2.2.1 el router cable los FBs, el caller solo instancia el
  FB con sus deps — el use case es interno al FB.

Trade-offs respecto al use case legacy:
  - El FB NO llama ``progress.begin()``/``finish()`` (caller las
    hace, mismo contrato que ``FunctionSubirExcel``).  El use
    case emite sus 4 stages internamente si no hay ya una
    operación activa en el tracker (``generar_prevision`` docstring:
    "Solo emitir progress si NO hay ya una operación activa").
  - El FB NO lanza ``HTTPException`` (transport-agnostic).
  - ``self.result`` contiene el dict con el shape legacy
    (``{agregados, eliminados, renombrados, todos, nmax, summary}``).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from areas.alimentacion.application.use_cases.disp_sync_instances import (
    DispSyncInstancesUseCase,
)
from core.application.progress_buffer import (
    ProgressTracker,
    get_progress_tracker,
)
from core.application.state import AppState, get_app_state
from core.infrastructure.config_manager import ConfigManager
from core.infrastructure.gateway import TIAProcessGateway
from core.plc.function_base import FunctionBase

logger = logging.getLogger(__name__)


class FunctionGenerarPreview(FunctionBase):
    """FB que calcula la previsión (diff N_MAX + devices) de un PLC.

    Inyección de dependencias vía constructor (las mismas que el
    use case legacy):
      - ``gateway``: TIAProcessGateway.  Obligatorio.
      - ``config_manager``: ConfigManager.  Obligatorio.
      - ``app_state``: AppState.  Default Singleton.
      - ``progress_tracker``: ProgressTracker.  Default Singleton.
      - ``build_cache_dir``: raíz del BuildCache.  Default
        ``<cwd>/.build_cache`` (mismo default que el use case).
      - ``use_case_factory``: factoría del use case legacy.  Default
        instancia ``DispSyncInstancesUseCase`` con las deps
        inyectadas.  Inyectable para tests (pasa un mock que
        retorna un dict fijo sin tocar el gateway).

    Runtime params via ``start(**kwargs)``:
      - ``plc_name`` (str): nombre del PLC.  Obligatorio.

    Tras ``n_done``, ``self.result`` contiene el dict con el shape
    legacy esperado por la SPA (``/sync/preview`` lo devuelve tal
    cual).
    """

    def __init__(
        self,
        nombre: str = "generar_preview",
        gateway: TIAProcessGateway | None = None,
        config_manager: ConfigManager | None = None,
        app_state: AppState | None = None,
        progress_tracker: ProgressTracker | None = None,
        build_cache_dir: Path | None = None,
        use_case_factory: Callable[..., DispSyncInstancesUseCase] | None = None,
    ) -> None:
        super().__init__(nombre)
        self._gateway = gateway
        self._config = config_manager
        self._state: AppState = (
            app_state if app_state is not None else get_app_state()
        )
        self._progress: ProgressTracker = (
            progress_tracker if progress_tracker is not None
            else get_progress_tracker()
        )
        self._build_cache = build_cache_dir
        self._use_case_factory = use_case_factory
        # Lazy-instantiated: la creamos al primer uso, no en __init__,
        # para que los tests que mockean via ``use_case_factory`` no
        # paguen el coste del constructor real.
        self._use_case: DispSyncInstancesUseCase | None = None
        # Estado entre ticks
        self._plc_name: str = ""
        self._prevision: dict[str, Any] | None = None

    def _get_or_create_use_case(self) -> DispSyncInstancesUseCase:
        """Lazy: crea el use case (real o mock) al primer uso.

        Si se inyectó ``use_case_factory``, lo usa.  Si no, instancia
        ``DispSyncInstancesUseCase`` con las deps del FB.
        """
        if self._use_case is None:
            if self._use_case_factory is not None:
                self._use_case = self._use_case_factory()
            else:
                self._use_case = DispSyncInstancesUseCase(
                    gateway=self._gateway,
                    config_manager=self._config,
                    state=self._state,
                    progress_tracker=self._progress,
                    build_cache_dir=self._build_cache,
                )
        return self._use_case

    async def _tick_locked(self) -> None:
        assert self._lock.locked()
        if self.nStep == 10:
            self._step_arrancar()
        elif self.nStep == 20:
            await self._step_generar()
        elif self.nStep == 30:
            self._step_finalizar()

    # ------------------------------------------------------------------
    # Pasos del state machine
    # ------------------------------------------------------------------

    def _step_arrancar(self) -> None:
        """nStep=10→20: pre-flight.  Valida deps y captura plc_name."""
        if self._gateway is None:
            raise RuntimeError(
                "FunctionGenerarPreview requiere gateway explícito. "
                "Inyéctalo en el constructor."
            )
        if self._config is None:
            raise RuntimeError(
                "FunctionGenerarPreview requiere config_manager explícito. "
                "Inyéctalo en el constructor."
            )
        plc_name = self._params.get("plc_name")
        if not plc_name:
            raise ValueError(
                "FunctionGenerarPreview.start(plc_name=...) es obligatorio"
            )
        self._plc_name = plc_name
        self.nStep = 20

    async def _step_generar(self) -> None:
        """nStep=20→30: delega al use case legacy.

        El use case emite sus 4 stages (``export_tags``,
        ``compute_devices``, ``compute_nmax``, ``build_response``)
        internamente si no hay ya una operación activa en el
        tracker.  Ver ``generar_prevision`` docstring.
        """
        self._prevision = await self._get_or_create_use_case().generar_prevision(
            self._plc_name
        )
        self.nStep = 30

    def _step_finalizar(self) -> None:
        """nStep=30→99: expone el resultado y termina."""
        self.result = self._prevision
        self.nStep = self.n_done
