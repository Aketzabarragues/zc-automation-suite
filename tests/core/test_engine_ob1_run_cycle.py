"""Tests del run_cycle() sync del Engine (Fase 4 / paso 4.2.1)."""
from __future__ import annotations

from unittest.mock import MagicMock

from core.composition.plc_engine import Engine
from core.composition.plc_function_base import FunctionBase


class _CountingFB(FunctionBase):
    """FB que cuenta ticks para verificar que run_cycle() tickea."""

    def __init__(self, nombre: str = "counter"):
        super().__init__(nombre=nombre)
        self.tick_count = 0

    async def tick(self) -> None:
        self.tick_count += 1
        self.nStep = 1  # constante: tick() lo deja en 1 para que no publique


def test_run_cycle_sync_method_exists():
    """Engine expone run_cycle() sync (no async) para OB1."""
    engine = Engine()
    # Verificar que es callable sync (no necesita await).
    assert callable(engine.run_cycle)


def test_run_cycle_calls_tick_on_each_registered_fb():
    """Cada run_cycle() tickea los FBs no terminales una vez."""
    import asyncio

    async def _start(fb):
        await fb.start()

    engine = Engine(tick_period_s=10.0)
    fb = _CountingFB()
    asyncio.run(_start(fb))  # n_idle (terminal) -> 10 (activo)
    engine.register_fb("counter", fb)

    engine.run_cycle()
    assert fb.tick_count == 1

    engine.run_cycle()
    assert fb.tick_count == 2


def test_run_cycle_skips_terminal_fbs():
    """FBs terminales no se tickean (consistente con tick_once async)."""
    import asyncio

    async def _start(fb):
        await fb.start()

    engine = Engine(tick_period_s=10.0)

    fb = _CountingFB()
    asyncio.run(_start(fb))  # activo
    engine.register_fb("started_fb", fb)
    engine.run_cycle()  # tick 1

    fb.nStep = FunctionBase.n_done  # ahora terminal
    count_after_terminal = fb.tick_count

    engine.run_cycle()  # no debe tickear
    assert fb.tick_count == count_after_terminal


def test_run_cycle_publishes_fb_changed_via_event_bus():
    """run_cycle() publica al event_bus cuando un FB cambia nStep."""
    import asyncio

    engine = Engine(tick_period_s=10.0, event_bus=MagicMock())

    class _ChangingFB(FunctionBase):
        def __init__(self):
            super().__init__(nombre="changer")
            self.first = True

        async def tick(self) -> None:
            if self.first:
                self.nStep = 2  # cambia de 10 (activo) -> 2
                self.first = False

    fb = _ChangingFB()
    asyncio.run(fb.start())  # 0 -> 10 (activo, no terminal)
    engine.register_fb("changer", fb)

    engine.run_cycle()
    engine._event_bus.publish.assert_called_once()
    event = engine._event_bus.publish.call_args[0][0]
    assert event["type"] == "fb_changed"
    assert event["name"] == "changer"
    assert event["nStep"] == 2


def test_run_cycle_is_idempotent_no_args():
    """run_cycle() no requiere argumentos (interface sync pura)."""
    engine = Engine(tick_period_s=10.0)
    # No raise.
    engine.run_cycle()


def test_engine_exposes_both_sync_and_async_apis():
    """Engine sigue exponiendo start_loop/stop_loop/tick_once (async legacy)
    Y ademas run_cycle() (sync OB1). Ambos coexisten.
    """
    engine = Engine()
    import inspect
    # Async API.
    assert inspect.iscoroutinefunction(engine.start_loop)
    assert inspect.iscoroutinefunction(engine.stop_loop)
    assert inspect.iscoroutinefunction(engine.tick_once)
    # Sync API (OB1).
    assert not inspect.iscoroutinefunction(engine.run_cycle)
