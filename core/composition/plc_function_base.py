"""Clase base de los Function Blocks (FBs).

State machine discreto ``nStep`` con tolerancia best-effort. Cada FB
es un orquestador async de una operacion del operario contra TIA
Portal (subir excel, escanear bloques, sincronizar dispositivos, etc.).

State machine::

    nStep=0   idle      (FB creado, sin start)
    nStep=10  arrancar  (transicion tras start OK)
    nStep=20  ejecutar  (transicion durante tick si procede)
    nStep=30  finalizar (transicion al completar)
    nStep=99  done      (terminal OK, el engine NO tickea mas)
    nStep=98  error     (terminal con error_msg, el engine NO tickea mas)

Las subclases overridean ``_tick_locked()`` para implementar la logica.
La base lanza ``NotImplementedError`` si se tickea sin override (error
de programacion, no de runtime).

Concurrencia: ``start()`` y ``tick()`` son coroutines que comparten
estado (``nStep``, ``result``, ``error_msg``). Patron "lock del assert":
el wrapper publico adquiere ``self._lock`` y delega en un metodo
privado ``_x_locked`` que asume el lock cogido.

Hook ``_on_nstep_change(old, new)``: invocado tras cada cambio de
``nStep``. La capa SSE lo usa para publicar ``{type: "fb_state", ...}``
al bus. Opcional (no-op si None).
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class FunctionBase:
    """Clase base de un Function Block (state machine async)."""

    # Constantes de estado a nivel de clase: las subclases y el engine
    # las referencian sin necesidad de instanciar.
    n_idle: int = 0
    n_done: int = 99
    n_error: int = 98

    def __init__(self, nombre: str) -> None:
        self.nombre: str = nombre
        self.nStep: int = self.n_idle
        self.error_msg: str | None = None
        self.result: Any = None
        # Parametros del ultimo start() exitoso. Las subclases los leen
        # desde _tick_locked() si los necesitan.
        self._params: dict[str, Any] = {}
        self._lock = asyncio.Lock()
        # Hook opcional: invocado tras cada cambio de nStep con
        # (old_nStep, new_nStep). No-op si None.
        self._on_nstep_change: Callable[[int, int], None] | None = None

    def _notify_nstep_change(self, old: int, new: int) -> None:
        """Dispara el hook si nStep cambio. Llamar tras cualquier mutacion."""
        if self._on_nstep_change is not None and old != new:
            self._on_nstep_change(old, new)

    # ------------------------------------------------------------------
    # API publica (adquiere el lock y delega en el _locked gemelo)
    # ------------------------------------------------------------------

    async def start(self, **params: Any) -> bool:
        """Arranca el FB. Idempotente: si ya esta activo, ignora.

        Devuelve ``True`` si paso ``nStep`` de ``n_idle`` a 10, ``False``
        si ya estaba activo o en estado terminal.
        """
        async with self._lock:
            return await self._start_locked(**params)

    async def tick(self) -> None:
        """Avanza el state machine un paso. Overridear ``_tick_locked``.

        Tolerancia best-effort: si ``_tick_locked()`` lanza una excepcion
        de runtime (no de programacion), el wrapper la captura, hace log,
        fija ``error_msg`` y transita ``nStep`` a ``n_error``. El FB queda
        terminal pero vivo: el operario ve el error y puede resetearlo.
        ``NotImplementedError`` y ``AssertionError`` propagan (errores de
        programacion, no se silencian).
        """
        async with self._lock:
            n_before = self.nStep
            try:
                await self._tick_locked()
            except (NotImplementedError, AssertionError):
                # Programacion: la subclase olvido overridear o el lock
                # no estaba cogido. Propaga para que el dev lo vea en consola.
                raise
            except Exception as e:
                # Runtime: TIA Portal, Excel, red, etc. Degradado pero vivo.
                logger.exception(
                    "FB %s: error en tick() (nStep=%d) -- %s: %s",
                    self.nombre, self.nStep, type(e).__name__, e,
                )
                self.error_msg = f"{type(e).__name__}: {e}"
                self.nStep = self.n_error
            self._notify_nstep_change(n_before, self.nStep)

    def is_terminal(self) -> bool:
        """``True`` si el FB esta en estado terminal y NO debe tickearse.

        Idle (``nStep=0``) tambien cuenta: un FB sin ``start()`` no hace
        nada en ``tick()``. ``n_done`` y ``n_error`` son los finales tras
        una ejecucion.
        """
        return self.nStep in (self.n_idle, self.n_done, self.n_error)

    # ------------------------------------------------------------------
    # Metodos privados (asumen self._lock cogido)
    # ------------------------------------------------------------------

    async def _start_locked(self, **params: Any) -> bool:
        """Asume ``self._lock`` cogido. No llamar directamente.

        Idempotente: si ``nStep != n_idle``, ignora y devuelve ``False``.
        """
        assert self._lock.locked(), "_start_locked() requiere self._lock cogido"
        if self.nStep != self.n_idle:
            logger.warning(
                "FB %s: start() ignorado, ya activo o terminal (nStep=%d)",
                self.nombre,
                self.nStep,
            )
            return False
        self._params = dict(params)
        self.error_msg = None
        self.result = None
        self.nStep = 10
        logger.info("FB %s: start() OK (nStep=%d)", self.nombre, self.nStep)
        self._notify_nstep_change(self.n_idle, 10)
        return True

    async def _tick_locked(self) -> None:
        """Asume ``self._lock`` cogido. Overridear en subclases.

        La base hace dos cosas y se detiene ahi:
          1. Guarda defensiva de ``is_terminal()`` (no-op si terminal).
          2. Si no, lanza ``NotImplementedError`` (la subclase olvido
             overridear).
        """
        assert self._lock.locked(), "_tick_locked() requiere self._lock cogido"
        if self.is_terminal():
            return
        raise NotImplementedError(
            f"FB {self.nombre}: _tick_locked() debe ser implementado por "
            f"la subclase (ver areas/<area>/functions/function_*.py)"
        )
