"""Function block: sincronizar comentarios de los 3 arrays de un proceso.

Fase 2, paso 2.1.7.  Encapsula el método
``ProcSyncComentariosUseCase.ejecutar_transaccion`` (areas/alimentacion/
application/use_cases/proc_sync_comentarios.py:408) en un
``FunctionBase`` con state machine ``nStep = 10 -> 20 -> 30 -> 99``
o ``98 (n_error)``.

State machine:
  nStep=10  arrancar    (pre-flight: validar gateway + config_manager
                         + proc_uid + prevision)
  nStep=20  ejecutar    (delegar a ``use_case.ejecutar_transaccion``;
                         el use case emite sus 5 stages internamente:
                         check_state / check_blocks / build_slot_maps /
                         open_transaction / done)
  nStep=30  finalizar   (set ``self.result`` con el shape legacy,
                         transita a ``n_done``)
  nStep=99  done        (terminal OK)
  nStep=98  error       (terminal con error_msg)

Decisión de diseño (mismo patrón que el resto de FBs wrapper de
Fase 2): el use case legacy es de 1073 líneas con ``_compose_*``,
``_compute_*`` y ``_export_and_read_current`` que hacen I/O pesada
(transacción COM con 2 sub-ops, export bulk).  El FB es un WRAPPER
con state machine que delega al use case via lazy instantiation.

Detalle del flow: el use case **recalcula el diff desde el AppState**
(no usa la ``prevision`` del body) para evitar race conditions con
cambios de Excel entre el preview y el commit.  El FB pasa la
``prevision`` por contrato de la API pero el use case puede
ignorarla; se mantiene por back-compat con la firma del endpoint
``/alimentacion/aplicar-comentarios-proc``.

Trade-offs:
  - El FB NO llama ``progress.begin()``/``finish()`` (caller las
    hace).  El use case emite sus 5 stages internamente.
  - El FB NO lanza ``HTTPException`` (transport-agnostic).
  - ``self.result`` contiene el dict con el shape legacy
    (``{success, message, applied, operations_executed, summary,
    warnings, proc_uid}``).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from areas.alimentacion.application.use_cases.proc_sync_comentarios import (
    ProcSyncComentariosUseCase,
)
from core.application.progress_buffer import (
    ProgressTracker,
    get_progress_tracker,
)
from core.application.state import AppState, get_app_state
from core.infrastructure.config_manager import ConfigManager
from core.infrastructure.gateway import TIAProcessGateway
from core.models import BloqueCache
from core.plc.function_base import FunctionBase

logger = logging.getLogger(__name__)


class FunctionSincronizarProcesosComentarios(FunctionBase):
    """FB que aplica comentarios de los 3 arrays de un proceso.

    Inyección de dependencias vía constructor (las mismas que el
    use case legacy):
      - ``gateway``: TIAProcessGateway.  Obligatorio.
      - ``config_manager``: ConfigManager.  Obligatorio.
      - ``app_state``: AppState.  Default Singleton.
      - ``progress_tracker``: ProgressTracker.  Default Singleton.
      - ``bloques_cache``: BloqueCache del PLC activo.  Default
        ``None`` (el use case asume cache vacía y devuelve
        ``missing_blocks`` poblado).
      - ``build_cache_dir``: raíz del BuildCache.  Default
        ``<cwd>/.build_cache``.
      - ``use_case_factory``: factoría del use case legacy.  Default
        instancia ``ProcSyncComentariosUseCase``.  Inyectable para
        tests.

    Runtime params via ``start(**kwargs)``:
      - ``proc_uid`` (int): UID del proceso.  Obligatorio.
      - ``prevision`` (dict): output de ``generar_prevision``
        (o del método legacy).  Obligatorio.  El use case lo recibe
        por contrato de API pero lo recalcula desde AppState
        internamente (política anti-race-condition).

    Tras ``n_done``, ``self.result`` contiene el dict con el shape
    legacy esperado por la SPA (el endpoint
    ``/api/v1/alimentacion/aplicar-comentarios-proc`` lo devuelve
    tal cual).
    """

    def __init__(
        self,
        nombre: str = "sincronizar_procesos_comentarios",
        gateway: TIAProcessGateway | None = None,
        config_manager: ConfigManager | None = None,
        app_state: AppState | None = None,
        progress_tracker: ProgressTracker | None = None,
        bloques_cache: BloqueCache | None = None,
        build_cache_dir: Path | None = None,
        use_case_factory: Callable[..., ProcSyncComentariosUseCase] | None = None,
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
        self._bloques_cache = bloques_cache
        self._build_cache = build_cache_dir
        self._use_case_factory = use_case_factory
        # Lazy-instantiated: la creamos al primer uso.
        self._use_case: ProcSyncComentariosUseCase | None = None
        # Estado entre ticks
        self._proc_uid: int = 0
        self._prevision: dict[str, Any] | None = None
        self._tx_result: dict[str, Any] | None = None

    def _get_or_create_use_case(self) -> ProcSyncComentariosUseCase:
        """Lazy: crea el use case (real o mock) al primer uso."""
        if self._use_case is None:
            if self._use_case_factory is not None:
                self._use_case = self._use_case_factory()
            else:
                self._use_case = ProcSyncComentariosUseCase(
                    gateway=self._gateway,
                    config_manager=self._config,
                    app_state=self._state,
                    progress=self._progress,
                    bloques_cache=self._bloques_cache,
                    build_cache_dir=self._build_cache,
                )
        return self._use_case

    async def _tick_locked(self) -> None:
        assert self._lock.locked()
        if self.nStep == 10:
            self._step_arrancar()
        elif self.nStep == 20:
            await self._step_ejecutar()
        elif self.nStep == 30:
            self._step_finalizar()

    # ------------------------------------------------------------------
    # Pasos del state machine
    # ------------------------------------------------------------------

    def _step_arrancar(self) -> None:
        """nStep=10→20: pre-flight.  Valida deps y captura params."""
        if self._gateway is None:
            raise RuntimeError(
                "FunctionSincronizarProcesosComentarios requiere gateway. "
                "Inyéctalo en el constructor."
            )
        if self._config is None:
            raise RuntimeError(
                "FunctionSincronizarProcesosComentarios requiere config_manager. "
                "Inyéctalo en el constructor."
            )
        proc_uid = self._params.get("proc_uid")
        if not isinstance(proc_uid, int) or proc_uid <= 0:
            raise ValueError(
                "FunctionSincronizarProcesosComentarios.start(proc_uid=int>0) "
                "es obligatorio"
            )
        prevision = self._params.get("prevision")
        if not isinstance(prevision, dict):
            raise ValueError(
                "FunctionSincronizarProcesosComentarios.start(prevision=dict) "
                "es obligatorio"
            )
        self._proc_uid = proc_uid
        self._prevision = prevision
        self.nStep = 20

    async def _step_ejecutar(self) -> None:
        """nStep=20→30: delega al use case legacy.

        El use case emite sus 5 stages internamente (``check_state``,
        ``check_blocks``, ``build_slot_maps``, ``open_transaction``,
        ``done``) si no hay ya una operación activa en el tracker.
        Recalcula el diff desde AppState (ignora la ``prevision``
        del body, política anti-race-condition documentada en
        ``ejecutar_transaccion``).
        """
        self._tx_result = (
            await self._get_or_create_use_case().ejecutar_transaccion(
                self._proc_uid, self._prevision
            )
        )
        self.nStep = 30

    def _step_finalizar(self) -> None:
        """nStep=30→99: expone el resultado y termina."""
        self.result = self._tx_result
        self.nStep = self.n_done
