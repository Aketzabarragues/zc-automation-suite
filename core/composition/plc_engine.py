"""Engine del runtime de FBs: dos caminos de ejecucion.

El Engine es el OB1 del runtime. Expone dos caminos independientes:

  - Tick (async): ``start_loop()`` / ``stop_loop()`` / ``tick_once()`` /
    ``run_cycle()``. El engine llama ``tick()`` a cada FB registrado que
    no sea terminal, un step por invocacion. Cada FB es responsable de
    su propio state machine y de la tolerancia best-effort.
  - Dispatcher (sync, hilo dedicado): ``submit()`` encola un trabajo
    para un FB concreto y devuelve un ``job_id``. El hilo ``plc-ob1``
    consume la cola y ejecuta ``fb.execute(**params)`` en bloque, sin
    event loop. El estado del trabajo se consulta con ``get_job()``,
    ``list_jobs()`` y ``current_job_for()``.

Contrato del camino dispatcher:
  - Un FB solo admite un trabajo en curso: ``submit()`` lanza
    ``FBBusyError`` si el FB no existe o no esta terminal (el router
    web lo traduce a HTTP 409).
  - ``cancel_job()`` pide la cancelacion cooperativa del FB en curso;
    el hilo ejecutor cierra el FB y el job.
  - Un fallo de un FB no mata el dispatcher: el error queda en el job y
    el hilo sigue vivo.
"""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from core.composition.plc_function_base import FunctionBase

logger = logging.getLogger(__name__)

# Periodo por defecto del loop: 100 ms (10 ticks/s). Configurable para tests.
DEFAULT_TICK_PERIOD_S: float = 0.1


class FBBusyError(RuntimeError):
    """El FB ya tiene un trabajo en curso: no se acepta otro.

    El router web la traduce a HTTP 409.
    """


@dataclass
class Job:
    """Un trabajo encolado en el OB1."""

    job_id: str
    fb_name: str
    params: dict[str, Any]
    status: str = "queued"  # queued | running | done | error | cancelled | busy
    submitted_at: float = field(default_factory=time.monotonic)
    started_at: float | None = None
    finished_at: float | None = None
    result: Any = None
    error: str | None = None


class Engine:
    """OB1 del runtime de FBs.

    Dos caminos de ejecucion independientes: el tick legacy (async,
    un step por invocacion) y el dispatcher con cola (sync, un trabajo
    por FB, ejecutado por el hilo ``plc-ob1``).
    """

    def __init__(
        self,
        tick_period_s: float = DEFAULT_TICK_PERIOD_S,
    ) -> None:
        self._fbs: dict[str, FunctionBase] = {}
        self._task: asyncio.Task[None] | None = None
        self._tick_period_s: float = tick_period_s
        self.cycle_count: int = 0
        # Trabajos cerrados por el dispatcher del OB1. Es el contador de
        # ciclos del OB1: cada trabajo procesado es un ciclo.
        self.jobs_processed: int = 0
        # Estado del dispatcher OB1: cola de trabajos + hilo ejecutor.
        self._jobs: dict[str, Job] = {}
        self._job_queue: queue.Queue[str] = queue.Queue()
        self._ob1_thread: threading.Thread | None = None
        self._ob1_stop = threading.Event()
        # Hook opcional: callable(name, fb) invocado tras cada cambio
        # de nStep de cualquier FB. Lo cablea publishers.wire_all() en el
        # arranque, DESPUES de registrar los FBs: por eso es una
        # property que re-cablea los FBs ya registrados.
        self._on_fb_change: Callable[[str, FunctionBase], None] | None = None

    @property
    def on_fb_change(self) -> Callable[[str, FunctionBase], None] | None:
        """Hook de notificacion de cambios de nStep de los FBs."""
        return self._on_fb_change

    @on_fb_change.setter
    def on_fb_change(
        self, value: Callable[[str, FunctionBase], None] | None,
    ) -> None:
        self._on_fb_change = value
        self._wire_fb_hooks()

    def _wire_fb_hooks(self) -> None:
        """Conecta (o desconecta) el hook de cambio de nStep en los FBs.

        Los FBs se registran antes de que exista el bus SSE, asi que el
        cableado tiene que poder rehacerse cuando el hook se asigna.
        """
        for name, fb in self._fbs.items():
            if self._on_fb_change is None:
                fb._on_nstep_change = None
                continue
            fb._on_nstep_change = (
                lambda old, new, _n=name, _fb=fb: self._on_fb_change(_n, _fb)
            )

    # ------------------------------------------------------------------
    # Registro de FBs
    # ------------------------------------------------------------------

    def register_fb(self, name: str, fb: FunctionBase) -> None:
        """Registra ``fb`` bajo ``name``. Si ya existe, lo pisa con warning.

        El hook de cambio de nStep se cablea al registrar: si todavia
        no hay hook (el bus SSE se cablea despues), se cablea cuando se
        asigne.
        """
        if name in self._fbs:
            logger.warning(
                "Engine: FB '%s' ya registrado, pisando con %s",
                name,
                type(fb).__name__,
            )
        self._fbs[name] = fb
        self._wire_fb_hooks()
        logger.info("Engine: FB registrado '%s' (%s)", name, type(fb).__name__)

    def get_fb(self, name: str) -> FunctionBase | None:
        """Lookup por nombre. ``None`` si no existe."""
        return self._fbs.get(name)

    def registered_fb_names(self) -> list[str]:
        """Snapshot de nombres registrados. Para diagnostico y tests."""
        return list(self._fbs.keys())

    def snapshot(self) -> dict[str, Any]:
        """Snapshot JSON-serializable del estado del Engine.

        Consumido por el SSE como contenido del evento inicial
        ``{"type": "snapshot", ...}``. Permite al cliente pintar el
        estado sin esperar al primer ``fb_changed``.

        Shape:
          {
            "dbs": {},   # vacio por ahora; se rellena con bloques TIA
            "fbs": {     # estado de cada FB registrado
              "<nombre>": {"nStep": int, "error_msg": str | None},
              ...
            },
          }
        """
        return {
            "dbs": {},
            "fbs": {
                name: {
                    "nStep": fb.nStep,
                    "error_msg": fb.error_msg,
                }
                for name, fb in self._fbs.items()
            },
        }

    # ------------------------------------------------------------------
    # Loop
    # ------------------------------------------------------------------

    async def start_loop(self) -> None:
        """Arranca el loop como task asyncio. No-op si ya esta corriendo."""
        if self._task is not None and not self._task.done():
            logger.warning("Engine: start_loop() ignorado, ya corriendo")
            return
        self._task = asyncio.create_task(self._run(), name="plc-engine-loop")
        logger.info(
            "Engine: loop arrancado (periodo=%.0f ms)",
            self._tick_period_s * 1000,
        )

    async def stop_loop(self) -> None:
        """Cancela el task. No-op si no esta corriendo. Idempotente."""
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("Engine: loop parado")

    def run_cycle(self) -> None:
        """Version sync de ``tick_once()`` para el OB1 main loop.

        El OB1 main loop es sync (no asyncio). Para integrarse con FBs
        async (``await fb.tick()``), crea un event loop efimero por
        ciclo, ejecuta ``tick_once()`` y lo cierra.

        Overhead aceptable para FBs best-effort sin I/O bloqueante.
        Si en el futuro hacen falta I/O reales, mover a un thread con
        loop persistente.
        """
        asyncio.run(self.tick_once())
        self.cycle_count += 1

    async def tick_once(self) -> None:
        """Un tick: ``await tick()`` sobre cada FB no terminal.

        FBs en n_idle, n_done o n_error se saltan sin pagar el lock acquire.
        La publicacion de cambios de nStep al bus la hace el propio FB
        via ``FunctionBase._on_nstep_change`` (cableado en ``register_fb()``
        si ``self.on_fb_change`` esta definido).

        Itera sobre ``list(self._fbs.items())`` para tolerar
        ``register_fb()`` / ``unregister_fb()`` concurrentes. Cada FB es
        best-effort: traga sus propias excepciones.
        """
        for name, fb in list(self._fbs.items()):
            if fb.is_terminal():
                continue
            await fb.tick()

    # ------------------------------------------------------------------
    # Loop interno
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        """Bucle del OB1: tick + sleep hasta que ``stop_loop()`` cancele."""
        logger.debug("Engine._run: loop arrancado")
        try:
            n_ticks = 0
            while True:
                try:
                    await self.tick_once()
                    n_ticks += 1
                except Exception:
                    # Los FBs son best-effort, pero si algo se cuela
                    # (p. ej. error en ``register_fb`` concurrente),
                    # el loop sigue vivo.
                    logger.exception("Engine: tick_once() lanzo -- loop sigue")
                await asyncio.sleep(self._tick_period_s)
        except asyncio.CancelledError:
            logger.debug("Engine._run: cancelado tras %d ticks", n_ticks)
            raise

    # ------------------------------------------------------------------
    # Dispatcher OB1: cola de trabajos
    # ------------------------------------------------------------------

    def submit(self, fb_name: str, **params: Any) -> str:
        """Encola un trabajo para el FB ``fb_name`` y devuelve su ``job_id``.

        Lanza ``FBBusyError`` si el FB no existe o ya tiene una ejecucion
        en curso (el caller web lo traduce a HTTP 409).
        """
        fb = self._fbs.get(fb_name)
        if fb is None:
            raise FBBusyError(f"FB desconocido: {fb_name}")
        if not fb.is_terminal():
            raise FBBusyError(
                f"FB ocupado: {fb_name} tiene una ejecucion en curso"
            )
        job = Job(
            job_id=uuid.uuid4().hex,
            fb_name=fb_name,
            params=dict(params),
        )
        self._jobs[job.job_id] = job
        self._job_queue.put(job.job_id)
        if not self.ob1_running():
            logger.warning(
                "Engine: job %s encolado pero el dispatcher OB1 no esta "
                "corriendo -- quedara en cola hasta que arranque",
                job.job_id,
            )
        logger.info(
            "Engine: job %s encolado para FB '%s'", job.job_id, fb_name,
        )
        return job.job_id

    def cancel_job(self, job_id: str, reason: str = "cancelled") -> bool:
        """Pide cancelar un trabajo. True si estaba en curso o en cola."""
        job = self._jobs.get(job_id)
        if job is None:
            return False
        if job.status in ("done", "error", "cancelled", "busy"):
            return False
        if job.status == "queued":
            job.status = "cancelled"
            job.finished_at = time.monotonic()
        elif job.status == "running":
            fb = self._fbs.get(job.fb_name)
            if fb is not None:
                fb.request_cancel(reason)
        job.error = reason
        logger.info(
            "Engine: job %s marcado para cancelar (%s)", job_id, reason,
        )
        return True

    def get_job(self, job_id: str) -> Job | None:
        """Job por ``job_id``. ``None`` si no existe."""
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[Job]:
        """Todos los jobs conocidos, en orden de insercion."""
        return list(self._jobs.values())

    def current_job_for(self, fb_name: str) -> Job | None:
        """Job en curso del FB ``fb_name``, o ``None`` si no hay ninguno."""
        for job in self._jobs.values():
            if job.status == "running" and job.fb_name == fb_name:
                return job
        return None

    # ------------------------------------------------------------------
    # Hilo dispatcher del OB1
    # ------------------------------------------------------------------

    def start_ob1(self) -> None:
        """Arranca el hilo dispatcher del OB1. No-op si ya esta corriendo."""
        if self._ob1_thread is not None and self._ob1_thread.is_alive():
            logger.warning("Engine: start_ob1() ignorado, ya corriendo")
            return
        self._ob1_stop.clear()
        self._ob1_thread = threading.Thread(
            target=self._ob1_loop,
            name="plc-ob1",
            daemon=True,
        )
        self._ob1_thread.start()
        logger.info("Engine: dispatcher OB1 arrancado")

    def stop_ob1(self, timeout: float = 5.0) -> None:
        """Para el hilo dispatcher. Idempotente."""
        thread = self._ob1_thread
        if thread is None:
            return
        self._ob1_stop.set()
        thread.join(timeout=timeout)
        if thread.is_alive():
            logger.warning(
                "Engine: dispatcher OB1 no termino en %.1fs -- se deja morir",
                timeout,
            )
        self._ob1_thread = None
        logger.info("Engine: dispatcher OB1 parado")

    def ob1_running(self) -> bool:
        """True si el hilo dispatcher esta vivo."""
        return self._ob1_thread is not None and self._ob1_thread.is_alive()

    def _ob1_loop(self) -> None:
        """Cuerpo del hilo dispatcher: consume la cola y ejecuta los jobs.

        El hilo no usa ``asyncio``: ``fb.execute()`` es sync y no necesita
        event loop. Un trabajo que falla no mata el dispatcher.
        """
        logger.debug("Engine._ob1_loop: dispatcher arrancado")
        while not self._ob1_stop.is_set():
            try:
                job_id = self._job_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._run_job(job_id)
            except Exception:
                logger.exception(
                    "Engine: job %s lanzo -- dispatcher sigue", job_id,
                )
            finally:
                self._job_queue.task_done()

    def _run_job(self, job_id: str) -> None:
        """Ejecuta el trabajo ``job_id`` y deja su estado final."""
        job = self._jobs.get(job_id)
        if job is None:
            return
        if job.status == "cancelled":
            # Cancelado mientras esperaba en la cola: el FB no se toca.
            return
        if job.status != "queued":
            return
        fb = self._fbs.get(job.fb_name)
        if fb is None:
            job.status = "error"
            job.error = f"FB desconocido: {job.fb_name}"
            job.finished_at = time.monotonic()
            return
        if not fb.is_terminal():
            job.status = "busy"
            job.error = "FB ocupado"
            job.finished_at = time.monotonic()
            return
        job.status = "running"
        job.started_at = time.monotonic()
        try:
            result = fb.execute(**job.params)
        except Exception as exc:
            job.status = "error"
            job.error = f"{type(exc).__name__}: {exc}"
        else:
            error_msg = getattr(fb, "error_msg", None)
            if error_msg is not None:
                job.status = "error"
                job.error = error_msg
            else:
                job.status = "done"
                job.result = result
        finally:
            job.finished_at = time.monotonic()
            self.jobs_processed += 1
