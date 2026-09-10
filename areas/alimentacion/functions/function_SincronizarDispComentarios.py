"""Function block: sincronizar comentarios por instancia de dispositivos.

Fase 2, paso 2.1.6.  Encapsula el método
``DispComentariosSyncUseCase.apply_comentarios_disp`` (areas/alimentacion/
application/use_cases/disp_sync_comentarios.py:80) en un
``FunctionBase`` con state machine ``nStep = 10 -> 20 -> 30 -> 99``
o ``98 (n_error)``.

State machine:
  nStep=10  arrancar    (pre-flight: validar gateway + config_manager
                         + plc_name)
  nStep=20  aplicar     (delegar a ``use_case.apply_comentarios_disp``;
                         el use case emite sus 4 stages internamente:
                         read_state / build_slot_maps / open_transaction
                         / done)
  nStep=30  finalizar   (set ``self.result`` con el shape legacy,
                         transita a ``n_done``)
  nStep=99  done        (terminal OK)
  nStep=98  error       (terminal con error_msg)

Decisión de diseño (mismo patrón que ``FunctionGenerarPreview`` /
``FunctionSincronizarDispositivos``):
  El use case legacy es de 288 líneas con ``_run_apply`` que hace
  I/O pesada (export bulk, copytree, batch de 6 invocaciones al
  gateway, transacción COM).  Copiarlo al FB superaría el cap de
  200 líneas.  El FB es un WRAPPER con state machine que delega
  al use case via lazy instantiation.  La "encapsulación" es la
  state machine (engine-friendly, observable, progress-tracked,
  best-effort).  Cuando en 2.2.1 el router cablee los FBs, el
  caller solo instancia el FB con sus deps; el use case es
  interno al FB.

Trade-offs:
  - El FB NO llama ``progress.begin()``/``finish()`` (caller las
    hace).  El use case emite sus 4 stages internamente.
  - El FB NO lanza ``HTTPException`` (transport-agnostic).
  - ``self.result`` contiene el dict con el shape legacy
    (``{plc_name, success, applied, operations_executed, summary,
    details, warnings}``).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from areas.alimentacion.application.use_cases.disp_sync_comentarios import (
    DispComentariosSyncUseCase,
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


class FunctionSincronizarDispComentarios(FunctionBase):
    """FB que aplica los comentarios por instancia de los 6 DBs de disp.

    Inyección de dependencias vía constructor (las mismas que el
    use case legacy):
      - ``gateway``: TIAProcessGateway.  Obligatorio.
      - ``config_manager``: ConfigManager.  Obligatorio.
      - ``app_state``: AppState.  Default Singleton.
      - ``progress_tracker``: ProgressTracker.  Default Singleton.
      - ``build_cache_dir``: raíz del BuildCache.  Default
        ``<cwd>/.build_cache``.
      - ``use_case_factory``: factoría del use case legacy.  Default
        instancia ``DispComentariosSyncUseCase``.  Inyectable para
        tests.

    Runtime params via ``start(**kwargs)``:
      - ``plc_name`` (str): nombre del PLC.  Obligatorio.

    Tras ``n_done``, ``self.result`` contiene el dict con el shape
    legacy esperado por la SPA (el endpoint ``/api/v1/alimentacion/
    aplicar-comentarios-disp`` lo devuelve tal cual).
    """

    def __init__(
        self,
        nombre: str = "sincronizar_disp_comentarios",
        gateway: TIAProcessGateway | None = None,
        config_manager: ConfigManager | None = None,
        app_state: AppState | None = None,
        progress_tracker: ProgressTracker | None = None,
        build_cache_dir: Path | None = None,
        use_case_factory: Callable[..., DispComentariosSyncUseCase] | None = None,
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
        # Lazy-instantiated: la creamos al primer uso.
        self._use_case: DispComentariosSyncUseCase | None = None
        # Estado entre ticks
        self._plc_name: str = ""
        self._apply_result: dict[str, Any] | None = None

    def _get_or_create_use_case(self) -> DispComentariosSyncUseCase:
        """Lazy: crea el use case (real o mock) al primer uso."""
        if self._use_case is None:
            if self._use_case_factory is not None:
                self._use_case = self._use_case_factory()
            else:
                self._use_case = DispComentariosSyncUseCase(
                    gateway=self._gateway,
                    config_manager=self._config,
                    app_state=self._state,
                    progress=self._progress,
                    build_cache_dir=self._build_cache,
                )
        return self._use_case

    async def _tick_locked(self) -> None:
        assert self._lock.locked()
        if self.nStep == 10:
            self._step_arrancar()
        elif self.nStep == 20:
            await self._step_aplicar()
        elif self.nStep == 30:
            self._step_finalizar()

    # ------------------------------------------------------------------
    # Pasos del state machine
    # ------------------------------------------------------------------

    def _step_arrancar(self) -> None:
        """nStep=10→20: pre-flight.  Valida deps y captura plc_name."""
        if self._gateway is None:
            raise RuntimeError(
                "FunctionSincronizarDispComentarios requiere gateway. "
                "Inyéctalo en el constructor."
            )
        if self._config is None:
            raise RuntimeError(
                "FunctionSincronizarDispComentarios requiere config_manager. "
                "Inyéctalo en el constructor."
            )
        plc_name = self._params.get("plc_name")
        if not plc_name:
            raise ValueError(
                "FunctionSincronizarDispComentarios.start(plc_name=...) "
                "es obligatorio"
            )
        self._plc_name = plc_name
        self.nStep = 20

    async def _step_aplicar(self) -> None:
        """nStep=20→30: delega al use case legacy.

        El use case emite sus 4 stages internamente
        (``read_state``, ``build_slot_maps``, ``open_transaction``,
        ``done``) si no hay ya una operación activa en el tracker.
        """
        self._apply_result = (
            await self._get_or_create_use_case().apply_comentarios_disp(
                self._plc_name
            )
        )
        self.nStep = 30

    def _step_finalizar(self) -> None:
        """nStep=30→99: expone el resultado y termina."""
        self.result = self._apply_result
        self.nStep = self.n_done
