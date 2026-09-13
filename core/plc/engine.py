"""core.plc.engine — OB1: ciclo principal del runtime de FBs.

Fase 2 del refactor.  Analogía con el OB1 de TIA Portal: un loop
asyncio que itera sobre los FBs registrados y llama ``await tick()``
sobre cada uno.  Cada FB es responsable de su propio state machine
y de la tolerancia best-effort (ver ``core.plc.function_base`` y el
paso 2.0.4).

API:
  - ``register_fb(name, fb)`` — asocia un nombre a un FunctionBase.
    Si ``on_fb_change`` esta definido en el engine, cablea el hook
    ``_on_nstep_change`` del FB para que publique al bus en cada
    cambio de nStep.
  - ``get_fb(name)`` — lookup por nombre, ``None`` si no existe.
  - ``start_loop()`` — arranca el loop como task asyncio.  Idempotente.
  - ``stop_loop()`` — cancela el task.  Idempotente.
  - ``tick_once()`` — un tick del loop, sin dormir.  Para tests.
  - ``snapshot()`` — dict JSON-serializable con el estado actual.
  - ``on_fb_change(name, fb)`` — callable opcional. Si esta definida,
    cada cambio de nStep de cualquier FB la invoca. Usado por la capa
    SSE para retransmitir ``{type: "fb_state", ...}``.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from core.plc.function_base import FunctionBase

logger = logging.getLogger(__name__)
_dbg = logging.getLogger("zc.debug.da012")

# Período por defecto del loop: 100 ms (10 ticks/s).  Configurable en
# el constructor para tests rápidos.
DEFAULT_TICK_PERIOD_S: float = 0.1


class Engine:
    """OB1 del runtime de FBs.  Loop asyncio que tickea los registrados.

    SINGLE-INSTANCE por proceso (análogo al OB1 de un PLC real).  Si
    necesitas dos ciclos independientes, crea dos Engines (raro en la
    práctica de Fase 2).
    """

    def __init__(
        self,
        tick_period_s: float = DEFAULT_TICK_PERIOD_S,
    ) -> None:
        self._fbs: dict[str, FunctionBase] = {}
        self._task: asyncio.Task[None] | None = None
        self._tick_period_s: float = tick_period_s
        # Contador de ciclos ejecutado. Se incrementa en run_cycle().
        # Lectura cross-thread es GIL-atomic en CPython.
        self.cycle_count: int = 0
        # Hook opcional: callable(name, fb) invocado tras cada cambio
        # de nStep de cualquier FB. Se cablea desde
        # core.sse.publishers.wire_all() en el arranque.
        self.on_fb_change: Callable[[str, FunctionBase], None] | None = None

    # ------------------------------------------------------------------
    # Registro de FBs
    # ------------------------------------------------------------------

    def register_fb(self, name: str, fb: FunctionBase) -> None:
        """Registra ``fb`` bajo ``name``.  Si ya existe, lo pisa con warning.

        Si ``self.on_fb_change`` esta definido, lo cablea como
        ``fb._on_nstep_change`` para que cada cambio de nStep del FB
        se retransmita automaticamente.
        """
        if name in self._fbs:
            logger.warning(
                "Engine: FB '%s' ya registrado, pisando con %s",
                name,
                type(fb).__name__,
            )
        self._fbs[name] = fb
        if self.on_fb_change is not None:
            fb._on_nstep_change = (
                lambda old, new, _n=name, _fb=fb: self.on_fb_change(_n, _fb)
            )
        logger.info("Engine: FB registrado '%s' (%s)", name, type(fb).__name__)

    def get_fb(self, name: str) -> FunctionBase | None:
        """Lookup por nombre.  ``None`` si no existe."""
        return self._fbs.get(name)

    def registered_fb_names(self) -> list[str]:
        """Snapshot de nombres registrados.  Para diagnóstico y tests."""
        return list(self._fbs.keys())

    def snapshot(self) -> dict[str, Any]:
        """Snapshot JSON-serializable del estado actual del Engine.

        Consumido por el SSE en ``core/sse/stream.py::_build_snapshot``
        como contenido del evento inicial ``{"type": "snapshot", ...}``.
        Permite al cliente pintar el estado del PLC sin esperar al
        primer ``fb_changed``.

        Shape (estable, es contrato con el frontend):
          {
            "dbs": {},                   # vacío por ahora (DA-011 no
                                         #  toca DBs; 3.3.3.x lo rellena)
            "fbs": {
              "<nombre_FB>": {
                "nStep": int,            # nStep actual del FB
                "error_msg": str | None, # None si no hay error
              },
              ...
            },
          }

        NOTA: NO serializa objetos nativos TIA (no hay en este punto,
        pero si llegasen, sería bug: el snapshot cruza el límite
        OT→IT y debe ser JSON-puro). ``fb.nStep`` y ``fb.error_msg``
        son ya tipos primitivos (``int`` y ``Optional[str]``).
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
        """Arranca el loop como task asyncio.  No-op si ya está corriendo."""
        if self._task is not None and not self._task.done():
            logger.warning("Engine: start_loop() ignorado, ya corriendo")
            return
        self._task = asyncio.create_task(self._run(), name="plc-engine-loop")
        _dbg.debug(
            "Engine.start_loop: task 'plc-engine-loop' creado (periodo=%.0f ms, "
            "fbs=%d event_bus=%s)",
            self._tick_period_s * 1000,
            len(self._fbs),
            "yes" if self._event_bus else "no",
        )
        logger.info(
            "Engine: loop arrancado (periodo=%.0f ms)",
            self._tick_period_s * 1000,
        )

    async def stop_loop(self) -> None:
        """Cancela el task.  No-op si no está corriendo.  Idempotente."""
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        _dbg.debug("Engine.stop_loop: task cancelado y esperado")
        logger.info("Engine: loop parado")

    def run_cycle(self) -> None:
        """Version sync de ``tick_once()`` para el loop OB1 (Fase 4 / DA-014).

        El OB1 main loop es sync (no asyncio). Para integrarse con FBs
        async (``await fb.tick()``), esta funcion crea un event loop
        efimero por ciclo, ejecuta ``tick_once()`` y lo cierra.

        Overhead aceptable para FBs best-effort (paso 2.0.4) sin I/O
        bloqueante pesado. Si en el futuro los FBs requieren I/O real,
        mover el engine a un thread dedicado con loop persistente
        (el OB1 main loop ya no lo invoca, se suscribe via event_bus).

        Raises:
            Exception: cualquier excepcion que escape de tick_once
                (los FBs son best-effort internamente; esta excepcion
                solo indica un fallo del propio engine).
        """
        import asyncio

        asyncio.run(self.tick_once())
        self.cycle_count += 1

    async def tick_once(self) -> None:
        """Un tick: ``await tick()`` sobre cada FB NO terminal registrado.

        FBs en ``n_idle``, ``n_done`` o ``n_error`` se saltan (paso 2.0.6):
        no se llama a ``tick()`` siquiera, así no pagan el lock acquire.
        La publicación de cambios de nStep al bus la hace el propio FB
        via ``FunctionBase._on_nstep_change`` (cableado en
        ``register_fb()`` si ``self.on_fb_change`` esta definido).
        Itera sobre ``list(self._fbs.items())`` para tolerar
        ``register_fb()`` / ``unregister_fb()`` concurrentes sin
        ``RuntimeError: dictionary changed size during iteration``.
        Cada FB no terminal es best-effort (paso 2.0.4): traga sus
        propias excepciones, el engine no se entera.
        """
        for name, fb in list(self._fbs.items()):
            if fb.is_terminal():
                continue
            await fb.tick()
            # El cambio de nStep se publica automaticamente via
            # FunctionBase._on_nstep_change (ver _notify_nstep_change).

    # ------------------------------------------------------------------
    # Loop interno
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        """Bucle del OB1: tick + sleep hasta que ``stop_loop()`` cancele."""
        _dbg.debug("Engine._run: loop arrancado")
        try:
            n_ticks = 0
            while True:
                try:
                    await self.tick_once()
                    n_ticks += 1
                except Exception:
                    # Los FBs ya son best-effort, pero si algo se cuela
                    # (p. ej. un error en ``register_fb`` concurrente),
                    # el loop sigue vivo.
                    logger.exception("Engine: tick_once() lanzó — loop sigue")
                await asyncio.sleep(self._tick_period_s)
        except asyncio.CancelledError:
            _dbg.debug("Engine._run: cancelado tras %d ticks", n_ticks)
            logger.debug("Engine: loop cancelado, saliendo")
            raise
