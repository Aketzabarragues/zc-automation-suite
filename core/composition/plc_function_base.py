"""Function Base con progress_tracker integrado, steps declarativos y timeout.

State machine discreto ``nStep`` con tolerancia best-effort. Cada FB
es un orquestador async de una operacion del operario contra TIA
Portal (subir excel, escanear bloques, sincronizar dispositivos, etc.).

A diferencia de un FB "pelado", este base lleva integrado el HMI
(progress_tracker): begin al arrancar, start/finish/error por cada
step, finish al cerrar. Las subclases solo aportan declaracion
estatica de steps y la logica de cada step.

State machine::

    nStep=0   idle      (FB creado, sin start)
    nStep=10  arrancar  (on_start + tracker.begin)
    nStep=20  ejecutar  (loop de steps: start_stage -> run_step -> finish/error)
    nStep=95  finalizar (on_finish + tracker.finish(success=True))
    nStep=99  done      (terminal OK, el engine NO tickea mas)
    nStep=98  error     (terminal con error_msg, el engine NO tickea mas)

Concurrencia: ``start()``/``tick()``/``cancel()`` son coroutines que
comparten estado (``nStep``, ``result``, ``error_msg``). Patron "lock
del assert": el wrapper publico adquiere ``self._lock`` y delega en un
metodo privado ``_x_locked`` que asume el lock cogido.

Hooks overridables por las subclases (FBs reales):
  - ``on_start(**params)``         pre-flight SYNC. Validar params.
  - ``run_step(idx, **params)``    logica del step N. Async.
  - ``on_finish(**params)``        post-flight SYNC. Vuelca self.result.

Cancelacion cooperativa: ``cancel(reason)`` marca un flag; el step en
curso propaga ``CancelledError`` y el base cierra con
``tracker.finish(success=False)`` + ``nStep = n_error``.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from core.runtime.progress_buffer import ProgressTracker, get_progress_tracker

logger = logging.getLogger(__name__)


class FunctionBase:
    """FB base con HMI (progress_tracker) integrado y cancel cooperativo."""

    # Constantes de estado a nivel de clase: las subclases y el engine
    # las referencian sin necesidad de instanciar.
    n_idle: int = 0
    n_arrancar: int = 10
    n_ejecutar: int = 20
    n_finalizar: int = 95
    n_done: int = 99
    n_error: int = 98

    # Timeout por defecto por step (segundos). Las subclases pueden
    # overridear si su logica lo requiere (p. ej. I/O de red).
    STEP_TIMEOUT_S: float = 300.0

    def __init__(
        self,
        nombre: str,
        titulo: str,
        steps: list[dict[str, Any]],
        tracker: ProgressTracker | None = None,
        step_timeout_s: float | None = None,
    ) -> None:
        self.nombre = nombre
        self.titulo = titulo
        # Normaliza a list[dict]. Acepta strings por ergonomia (los
        # FBs simples no necesitan dicts), pero la representacion
        # interna siempre es dict para admitir metadata futura
        # (descripcion, timeout propio, etc.).
        self.steps: list[dict[str, Any]] = [
            s if isinstance(s, dict) else {"nombre": s}
            for s in steps
        ]
        # Tracker: inyeccion obligatoria en FBs reales. Default al
        # singleton global solo para tests basicos y smoke (mismo
        # patron que LogBuffer).
        self._tracker = tracker if tracker is not None else get_progress_tracker()
        self._step_timeout_s = (
            step_timeout_s if step_timeout_s is not None else self.STEP_TIMEOUT_S
        )
        self._step_idx: int = 0
        self._cancelled = asyncio.Event()

        # Estado publico del FB (mismo shape que antes para compatibilidad
        # con publishers SSE y endpoints REST).
        self.nStep: int = self.n_idle
        self.error_msg: str | None = None
        self.result: Any = None
        self._params: dict[str, Any] = {}
        self._lock = asyncio.Lock()
        # Hook opcional: invocado tras cada cambio de nStep con
        # (old_nStep, new_nStep). No-op si None. Lo cablea publishers
        # para retransmitir fb_state al bus SSE.
        self._on_nstep_change: Callable[[int, int], None] | None = None

    # ------------------------------------------------------------------
    # Hooks overridables (los FBs reales solo aportan estos)
    # ------------------------------------------------------------------

    def on_start(self, **params: Any) -> None:
        """Pre-flight SYNC. Validar params, preparar estado interno.

        Lanzar ``ValueError`` si falta algun param obligatorio; el
        ``tick()`` lo captura y transiciona a ``n_error`` con
        ``tracker.error_stage(...)``. Default: no-op.
        """
        pass

    async def run_step(self, idx: int, **params: Any) -> str:
        """Logica del step ``idx``. Devuelve un detail (string) para el HMI.

        Default: ``NotImplementedError`` (la subclase olvido overridear).
        Lanzar cualquier excepcion aborta el step actual; el base
        emite ``tracker.error_stage(...)`` y transiciona a ``n_error``.
        """
        raise NotImplementedError(
            f"FB {self.nombre}: run_step() debe ser implementado por la subclase"
        )

    def on_finish(self, **params: Any) -> None:
        """Post-flight SYNC. Vuelca ``self.result`` con la shape que
        el caller espera. Default: ``{"ok": True}``.
        """
        self.result = {"ok": True}

    # ------------------------------------------------------------------
    # Estado y notificacion
    # ------------------------------------------------------------------

    def _notify_nstep_change(self, old: int, new: int) -> None:
        """Dispara el hook si nStep cambio. Llamar tras cualquier mutacion."""
        if self._on_nstep_change is not None and old != new:
            self._on_nstep_change(old, new)

    def is_terminal(self) -> bool:
        """``True`` si el FB esta en estado terminal y NO debe tickearse."""
        return self.nStep in (self.n_idle, self.n_done, self.n_error)

    # ------------------------------------------------------------------
    # API publica (adquiere el lock y delega en el _locked gemelo)
    # ------------------------------------------------------------------

    async def start(self, **params: Any) -> bool:
        """Arranca el FB. Idempotente: si ya esta activo, ignora."""
        async with self._lock:
            if self.nStep != self.n_idle:
                logger.warning(
                    "FB %s: start() ignorado, ya activo o terminal (nStep=%d)",
                    self.nombre, self.nStep,
                )
                return False
            self._params = dict(params)
            self.error_msg = None
            self.result = None
            self._step_idx = 0
            self._cancelled.clear()
            n_before = self.nStep
            self.nStep = self.n_arrancar
            logger.info("FB %s: start() OK (nStep=%d)", self.nombre, self.nStep)
            self._notify_nstep_change(n_before, self.nStep)
            return True

    async def tick(self) -> None:
        """Avanza el state machine un paso. Lo llama el engine.

        Tolerancia best-effort: si la logica lanza una excepcion de
        runtime, el wrapper la captura, fija ``error_msg``, cierra
        ``tracker.finish(success=False)`` y transita a ``n_error``.
        ``NotImplementedError`` y ``AssertionError`` propagan (errores
        de programacion, no se silencian).
        """
        async with self._lock:
            n_before = self.nStep
            try:
                await self._tick_locked()
            except (NotImplementedError, AssertionError):
                raise
            except Exception as e:
                logger.exception(
                    "FB %s: error en tick() (nStep=%d) -- %s: %s",
                    self.nombre, self.nStep, type(e).__name__, e,
                )
                self.error_msg = f"{type(e).__name__}: {e}"
                self._close_tracker_on_error()
                self.nStep = self.n_error
            self._notify_nstep_change(n_before, self.nStep)

    async def cancel(self, reason: str = "cancelled") -> None:
        """Paro cooperativo. Marca flag y transiciona a ``n_error``.

        Si el FB esta en un step awaitable, el siguiente tick propaga
        la cancelacion (``asyncio.CancelledError``) y el base cierra
        el tracker con ``success=False``. No-op si ya esta terminal.
        """
        async with self._lock:
            if self.is_terminal():
                return
            logger.info("FB %s: cancel() solicitado (%s)", self.nombre, reason)
            self._cancelled.set()
            self.error_msg = reason
            n_before = self.nStep
            self._close_tracker_on_error()
            self.nStep = self.n_error
            self._notify_nstep_change(n_before, self.nStep)

    # ------------------------------------------------------------------
    # State machine (privado; asume self._lock cogido)
    # ------------------------------------------------------------------

    async def _tick_locked(self) -> None:
        assert self._lock.locked()
        if self.nStep == self.n_idle:
            return
        if self.nStep == self.n_arrancar:
            self._step_arrancar()
        elif self.nStep == self.n_ejecutar:
            await self._step_ejecutar()
        elif self.nStep == self.n_finalizar:
            self._step_finalizar()
        # n_done / n_error: no-op. El engine ya los skipea.

    def _step_arrancar(self) -> None:
        """nStep 10 -> 20. ``on_start`` + ``tracker.begin``.

        Si ``on_start`` lanza (p. ej. ``ValueError`` por params
        invalidos), el ``tick()`` lo captura, cierra el tracker y va
        a ``n_error``.
        """
        self.on_start(**self._params)
        self._tracker.begin(
            operation=self.nombre,
            label=self.titulo,
            stages=[s["nombre"] for s in self.steps],
        )
        self.nStep = self.n_ejecutar

    async def _step_ejecutar(self) -> None:
        """nStep 20: ejecuta el step ``_step_idx`` o transiciona a 95."""
        if self._cancelled.is_set():
            raise RuntimeError(self.error_msg or "cancelled")
        idx = self._step_idx
        if idx >= len(self.steps):
            self.nStep = self.n_finalizar
            return
        step_nombre = self.steps[idx]["nombre"]
        self._tracker.start_stage(step_nombre)
        try:
            detail = await asyncio.wait_for(
                self.run_step(idx, **self._params),
                timeout=self._step_timeout_s,
            )
        except TimeoutError:
            self._tracker.error_stage(
                step_nombre, f"timeout >{self._step_timeout_s}s",
            )
            raise
        except asyncio.CancelledError:
            self._tracker.error_stage(step_nombre, "cancelled")
            raise
        except Exception:
            # El detail del error lo captura el tick() en self.error_msg.
            self._tracker.error_stage(step_nombre, self.error_msg or "error")
            raise
        self._tracker.finish_stage(
            step_nombre, detail=str(detail) if detail else None,
        )
        self._step_idx += 1
        if self._step_idx >= len(self.steps):
            self.nStep = self.n_finalizar

    def _step_finalizar(self) -> None:
        """nStep 95 -> 99. ``on_finish`` + ``tracker.finish(success=True)``."""
        self.on_finish(**self._params)
        self._tracker.finish(success=True)
        self.nStep = self.n_done

    def _close_tracker_on_error(self) -> None:
        """Cierra el tracker con ``success=False``. Asume lock cogido.

        Usado por ``tick()`` (tras excepcion) y ``cancel()``. Deja el
        tracker en estado inactivo para que la SPA no muestre la barra
        "pegada".
        """
        try:
            # Marca el stage en curso (si lo hay) como error para que la
            # SPA lo vea enrojecido. No-op si ya esta terminal.
            if 0 <= self._step_idx < len(self.steps):
                stage_nombre = self.steps[self._step_idx]["nombre"]
                # Solo emitimos error_stage si el tracker sigue activo.
                if getattr(self._tracker, "active", False):
                    self._tracker.error_stage(
                        stage_nombre, self.error_msg or "error",
                    )
            if getattr(self._tracker, "active", False):
                self._tracker.finish(success=False, error=self.error_msg)
        except Exception as exc:  # noqa: BLE001
            # Nunca rompemos el cierre del FB por un fallo del tracker.
            logger.debug("FB %s: cierre de tracker fallo: %s", self.nombre, exc)


__all__ = ["FunctionBase"]
