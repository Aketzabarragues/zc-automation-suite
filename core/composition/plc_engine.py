"""OB1 del runtime de FBs.

Analogia con el OB1 de TIA Portal: un loop que itera sobre los FBs
registrados y llama ``tick()`` sobre cada uno. Cada FB es responsable
de su propio state machine y de la tolerancia best-effort.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from core.composition.plc_function_base import FunctionBase

logger = logging.getLogger(__name__)

# Periodo por defecto del loop: 100 ms (10 ticks/s). Configurable para tests.
DEFAULT_TICK_PERIOD_S: float = 0.1


class Engine:
    """OB1 del runtime de FBs. Loop asyncio que tickea los registrados."""

    def __init__(
        self,
        tick_period_s: float = DEFAULT_TICK_PERIOD_S,
    ) -> None:
        self._fbs: dict[str, FunctionBase] = {}
        self._task: asyncio.Task[None] | None = None
        self._tick_period_s: float = tick_period_s
        self.cycle_count: int = 0
        # Hook opcional: callable(name, fb) invocado tras cada cambio
        # de nStep de cualquier FB. Lo cablea publishers.wire_all() en el arranque.
        self.on_fb_change: Callable[[str, FunctionBase], None] | None = None

    # ------------------------------------------------------------------
    # Registro de FBs
    # ------------------------------------------------------------------

    def register_fb(self, name: str, fb: FunctionBase) -> None:
        """Registra ``fb`` bajo ``name``. Si ya existe, lo pisa con warning.

        Si ``self.on_fb_change`` esta definido, lo cablea como
        ``fb._on_nstep_change`` para que cada cambio de nStep se
        retransmita automaticamente.
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
