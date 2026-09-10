"""core.plc.engine — OB1: ciclo principal del runtime de FBs.

Fase 2 del refactor.  Analogía con el OB1 de TIA Portal: un loop
asyncio que itera sobre los FBs registrados y llama ``await tick()``
sobre cada uno.  Cada FB es responsable de su propio state machine
y de la tolerancia best-effort (ver ``core.plc.function_base`` y el
paso 2.0.4).

API:
  - ``register_fb(name, fb)`` — asocia un nombre a un FunctionBase.
  - ``get_fb(name)`` — lookup por nombre, ``None`` si no existe.
  - ``start_loop()`` — arranca el loop como task asyncio.  Idempotente.
  - ``stop_loop()`` — cancela el task.  Idempotente.
  - ``tick_once()`` — un tick del loop, sin dormir.  Para tests.
  - ``snapshot()`` — dict JSON-serializable con el estado actual
    (``dbs`` vacío + ``fbs`` con ``nStep``/``error_msg`` de cada FB).
    Consumido por el SSE como contenido del evento inicial.

Paso 2.0.5+2.0.6+2.0.7: OB1 con guarda de ``is_terminal()`` y
publicación de ``fb_changed`` al ``EventBus``.  El engine filtra FBs
terminales y, tras tickear uno no terminal, si su ``nStep`` cambió,
publica ``{"type": "fb_changed", "name", "nStep", "error_msg"}``.
Si no se inyecta ``event_bus`` (default ``None``), no publica.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from core.plc.function_base import FunctionBase
from core.sse.event_bus import EventBus

logger = logging.getLogger(__name__)

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
        event_bus: EventBus | None = None,
    ) -> None:
        self._fbs: dict[str, FunctionBase] = {}
        self._task: asyncio.Task[None] | None = None
        self._tick_period_s: float = tick_period_s
        # Bus opcional: si es ``None`` (default), el engine no publica
        # eventos.  Se inyecta en producción desde ``app.state.event_bus``.
        self._event_bus: EventBus | None = event_bus

    # ------------------------------------------------------------------
    # Registro de FBs
    # ------------------------------------------------------------------

    def register_fb(self, name: str, fb: FunctionBase) -> None:
        """Registra ``fb`` bajo ``name``.  Si ya existe, lo pisa con warning."""
        if name in self._fbs:
            logger.warning(
                "Engine: FB '%s' ya registrado, pisando con %s",
                name,
                type(fb).__name__,
            )
        self._fbs[name] = fb
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
        logger.info("Engine: loop parado")

    async def tick_once(self) -> None:
        """Un tick: ``await tick()`` sobre cada FB NO terminal registrado.

        FBs en ``n_idle``, ``n_done`` o ``n_error`` se saltan (paso 2.0.6):
        no se llama a ``tick()`` siquiera, así no pagan el lock acquire.
        Tras tickear un FB no terminal, si su ``nStep`` cambió, el
        engine publica ``fb_changed`` al ``EventBus`` (paso 2.0.7).
        Itera sobre ``list(self._fbs.items())`` para tolerar
        ``register_fb()`` / ``unregister_fb()`` concurrentes sin
        ``RuntimeError: dictionary changed size during iteration``.
        Cada FB no terminal es best-effort (paso 2.0.4): traga sus
        propias excepciones, el engine no se entera.
        """
        for name, fb in list(self._fbs.items()):
            if fb.is_terminal():
                continue
            n_step_before = fb.nStep
            await fb.tick()
            if fb.nStep != n_step_before and self._event_bus is not None:
                self._publish_fb_changed(name, fb)

    def _publish_fb_changed(self, name: str, fb: FunctionBase) -> None:
        """Publica un evento ``fb_changed`` al bus.

        Esquema del evento (consumido por el frontend vía SSE):
          - ``type``: literal ``"fb_changed"``.
          - ``name``: nombre con el que se registró el FB.
          - ``nStep``: nuevo ``nStep`` tras el tick.
          - ``error_msg``: ``None`` en éxito, mensaje de error si
            ``nStep == n_error``.
        """
        self._event_bus.publish({
            "type": "fb_changed",
            "name": name,
            "nStep": fb.nStep,
            "error_msg": fb.error_msg,
        })

    # ------------------------------------------------------------------
    # Loop interno
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        """Bucle del OB1: tick + sleep hasta que ``stop_loop()`` cancele."""
        try:
            while True:
                try:
                    await self.tick_once()
                except Exception:
                    # Los FBs ya son best-effort, pero si algo se cuela
                    # (p. ej. un error en ``register_fb`` concurrente),
                    # el loop sigue vivo.
                    logger.exception("Engine: tick_once() lanzó — loop sigue")
                await asyncio.sleep(self._tick_period_s)
        except asyncio.CancelledError:
            logger.debug("Engine: loop cancelado, saliendo")
            raise
