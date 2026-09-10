"""Tests del Engine (OB1) en ``core.plc.engine.Engine``.

Pasos 2.0.5, 2.0.6 y 2.0.7.  Cubren:
  - ``register_fb()`` / ``get_fb()`` / ``registered_fb_names()``.
  - ``tick_once()`` invoca ``tick()`` sobre cada FB registrado.
  - ``start_loop()`` / ``stop_loop()`` son idempotentes.
  - El loop real tickea múltiples veces en un periodo corto.
  - Test 4 del .clinerules: el engine NO tickea FBs en estado
    terminal (``n_idle``, ``n_done``, ``n_error``).
  - Paso 2.0.7: el engine publica ``fb_changed`` al ``EventBus`` cuando
    ``nStep`` cambia tras un tick; NO publica si no cambia; NO publica
    sin bus (default ``None``).
"""
from __future__ import annotations

import asyncio

import pytest

from core.plc.engine import Engine
from core.plc.function_base import FunctionBase
from core.sse.event_bus import EventBus


# ---------------------------------------------------------------------
# Helper: FB que cuenta ticks sin cambiar nStep.
# ---------------------------------------------------------------------


class _CountingFB(FunctionBase):
    """FB de test: incrementa ``tick_count`` en cada ``_tick_locked``.

    No cambia ``nStep``, así que tras ``start()`` siempre está en
    nStep=10 (no terminal) y ``tick()`` ejecuta la lógica cada vez.
    """

    def __init__(self, nombre: str) -> None:
        super().__init__(nombre)
        self.tick_count: int = 0

    async def _tick_locked(self) -> None:
        assert self._lock.locked()
        self.tick_count += 1


# ---------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------


def test_register_y_get_fb() -> None:
    """``register_fb()`` añade, ``get_fb()`` recupera, missing → None."""
    engine = Engine()
    fb1 = FunctionBase("fb1")
    fb2 = FunctionBase("fb2")
    engine.register_fb("fb1", fb1)
    engine.register_fb("fb2", fb2)

    assert engine.get_fb("fb1") is fb1
    assert engine.get_fb("fb2") is fb2
    assert engine.get_fb("inexistente") is None
    assert set(engine.registered_fb_names()) == {"fb1", "fb2"}


@pytest.mark.asyncio
async def test_tick_once_llama_tick_de_cada_fb() -> None:
    """``tick_once()`` invoca ``tick()`` sobre cada FB registrado.

    Ambos FBs están en ``nStep=10`` (post-``start()``), así que el
    best-effort no entra en no-op.  Tras dos ``tick_once()``, cada
    contador vale 2.
    """
    engine = Engine()
    fb1 = _CountingFB("fb1")
    fb2 = _CountingFB("fb2")
    await fb1.start()
    await fb2.start()
    engine.register_fb("fb1", fb1)
    engine.register_fb("fb2", fb2)

    await engine.tick_once()
    assert fb1.tick_count == 1
    assert fb2.tick_count == 1

    await engine.tick_once()
    assert fb1.tick_count == 2
    assert fb2.tick_count == 2


@pytest.mark.asyncio
async def test_start_y_stop_loop_son_idempotentes() -> None:
    """``start_loop()`` arranca el task, ``stop_loop()`` lo cancela.
    Ambos se pueden llamar dos veces seguidas sin error.
    """
    engine = Engine(tick_period_s=0.01)
    await engine.start_loop()
    assert engine._task is not None and not engine._task.done()

    await engine.stop_loop()
    assert engine._task is None

    # Segundo stop_loop() no falla (idempotente)
    await engine.stop_loop()
    # Y un start_loop() tras stop funciona (no se queda colgado)
    await engine.start_loop()
    await engine.stop_loop()


@pytest.mark.asyncio
async def test_loop_real_tickea_multiples_veces() -> None:
    """El loop real tickea FBs varias veces en un periodo corto.

    Con ``tick_period_s=0.01`` (10 ms) y ``asyncio.sleep(0.05)``
    (50 ms), esperamos al menos 3 ticks (puede haber jitter).
    """
    engine = Engine(tick_period_s=0.01)
    fb = _CountingFB("fb")
    await fb.start()
    engine.register_fb("fb", fb)

    await engine.start_loop()
    await asyncio.sleep(0.05)
    await engine.stop_loop()

    assert fb.tick_count >= 3, (
        f"esperaba >=3 ticks en 50 ms con periodo 10 ms, "
        f"obtuve {fb.tick_count}"
    )


# ---------------------------------------------------------------------
# Paso 2.0.6 — el engine NO tickea FBs terminales
# ---------------------------------------------------------------------


class _WrapperCountingFB(FunctionBase):
    """FB de test: cuenta llamadas al wrapper ``tick()`` (no a
    ``_tick_locked``).  Sirve para verificar que el engine
    NO invoca ``tick()`` sobre FBs terminales — la base tiene una
    guarda en ``_tick_locked``, pero queremos que el engine los
    filtre ANTES de pagar el lock acquire.
    """

    def __init__(self, nombre: str) -> None:
        super().__init__(nombre)
        self.wrapper_tick_count: int = 0

    async def tick(self) -> None:
        # Override del wrapper público.  No llama a super() a propósito
        # para no contaminar el contador con la lógica de la base.
        self.wrapper_tick_count += 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "n_step,nombre_estado",
    [
        (0, "n_idle"),
        (99, "n_done"),
        (98, "n_error"),
    ],
)
async def test_engine_no_tickea_fb_terminal(
    n_step: int, nombre_estado: str
) -> None:
    """Test 4 del .clinerules: el engine NO llama ``tick()`` sobre
    FBs en estado terminal (``n_idle``, ``n_done``, ``n_error``).
    Filtra antes de pagar el lock acquire.
    """
    engine = Engine()
    fb = _WrapperCountingFB(f"fb_{nombre_estado}")
    fb.nStep = n_step  # fuerzo el estado terminal sin pasar por start()
    engine.register_fb("fb", fb)

    await engine.tick_once()

    assert fb.wrapper_tick_count == 0, (
        f"FB en {nombre_estado} ({n_step}) fue tickeado "
        f"{fb.wrapper_tick_count} veces; esperaba 0"
    )


@pytest.mark.asyncio
async def test_engine_tickea_fb_no_terminal() -> None:
    """FB en ``nStep=10`` (no terminal, post-``start()``) sí es
    tickeado por el engine — sanity check del filtro."""
    engine = Engine()
    fb = _WrapperCountingFB("fb_activo")
    await fb.start()  # nStep=10
    engine.register_fb("fb", fb)

    await engine.tick_once()

    assert fb.wrapper_tick_count == 1


# ---------------------------------------------------------------------
# Paso 2.0.7 — publicación de ``fb_changed`` al EventBus
# ---------------------------------------------------------------------


class _ProgressingFB(FunctionBase):
    """FB de test: avanza ``nStep`` 10→20→30→99 en ticks sucesivos.

    En nStep=99 (``n_done``), ``is_terminal()`` devuelve ``True`` y
    el engine deja de tickearlo.
    """

    async def _tick_locked(self) -> None:
        assert self._lock.locked()
        if self.nStep == 10:
            self.nStep = 20
        elif self.nStep == 20:
            self.nStep = 30
        elif self.nStep == 30:
            self.nStep = self.n_done


@pytest.mark.asyncio
async def test_engine_publica_fb_changed_cuando_nstep_cambia() -> None:
    """El engine publica ``fb_changed`` al bus cuando ``nStep`` cambia.

    Esquema del evento: ``{"type": "fb_changed", "name", "nStep",
    "error_msg"}``.  Verifica las 3 transiciones del FB progresivo
    (10→20, 20→30, 30→99) y que tras ``n_done`` no se publica más
    (el engine filtra terminales).
    """
    bus = EventBus()
    engine = Engine(event_bus=bus)

    fb = _ProgressingFB("progreso")
    await fb.start()  # nStep=10
    engine.register_fb("progreso", fb)

    q = bus.subscribe()

    await engine.tick_once()  # 10 → 20
    e1 = q.get_nowait()
    assert e1 == {
        "type": "fb_changed",
        "name": "progreso",
        "nStep": 20,
        "error_msg": None,
    }

    await engine.tick_once()  # 20 → 30
    e2 = q.get_nowait()
    assert e2["nStep"] == 30 and e2["name"] == "progreso"

    await engine.tick_once()  # 30 → 99 (n_done)
    e3 = q.get_nowait()
    assert e3["nStep"] == 99

    # El FB ya es terminal; no se publican más eventos.
    await engine.tick_once()
    assert q.empty()


@pytest.mark.asyncio
async def test_engine_no_publica_si_nstep_no_cambia() -> None:
    """Si el FB tickea pero ``nStep`` no cambia, el engine NO publica."""
    bus = EventBus()
    engine = Engine(event_bus=bus)

    fb = _CountingFB("estable")  # override _tick_locked sin cambiar nStep
    await fb.start()
    engine.register_fb("estable", fb)
    q = bus.subscribe()

    await engine.tick_once()
    await engine.tick_once()

    assert q.empty()


@pytest.mark.asyncio
async def test_engine_no_publica_sin_event_bus() -> None:
    """Sin ``event_bus`` (default ``None``), el engine no publica nada.

    El cambio de ``nStep`` se sigue produciendo internamente; lo que
    no hay es canal de salida.  No debe lanzar excepción.
    """
    engine = Engine()  # event_bus=None
    fb = _ProgressingFB("sin_bus")
    await fb.start()
    engine.register_fb("sin_bus", fb)

    # Si el engine intentase publicar con bus=None, fallaría.  El
    # test verifica que el flujo termina sin excepciones.
    await engine.tick_once()
    assert fb.nStep == 20
