"""Tests del Engine: el loop OB1 que tickea FBs cada 100 ms.

Verifica:
  - El Engine no tickea FBs en estado terminal
    (``nStep in (0, n_done, n_error)``).

Este es uno de los 6 tests obligatorios de ``.clinerules`` §12
(test 4).
"""
from __future__ import annotations

from typing import Any

import pytest

from core.plc.plc import DB_ESTADO, DB_EstadoConexion, Engine, FB_Base

# ─────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────


class _CountingFB(FB_Base):
    """FB de test que cuenta cuantas veces se llama ``tick()``.

    No avanza etapas por si mismo (a menos que ``advance=True``);
    solo cuenta. Asi podemos verificar que el Engine lo tickea
    (o NO lo tickea) segun su estado.
    """

    n_done: int = 30

    def __init__(self, name: str = "Counting", advance: bool = False) -> None:
        super().__init__(nombre=name)
        self._advance = advance
        self.tick_count: int = 0

    async def tick(self) -> None:
        self.tick_count += 1
        if self._advance:
            # Avanza de 10 en 10 hasta done.
            if self.nStep < 30:
                self.nStep += 10


class _RaisingFB(FB_Base):
    """FB que lanza una excepcion en ``tick()``.

    Usado para verificar que el Engine no se cae por un FB que
    falla, y que el estado del FB se pone en error.
    """

    n_done: int = 30

    def __init__(self, name: str = "Raising") -> None:
        super().__init__(nombre=name)

    async def tick(self) -> None:
        raise RuntimeError("exploto")


# ─────────────────────────────────────────────────────────────────────
#  Tests
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_loop_skips_idle_fbs() -> None:
    """El Engine skipea FBs en ``nStep=0`` (idle): no los tickea.

    Verifica el contrato fundamental del loop: solo se tickean
    FBs en etapas activas. Un FB en idle no se ejecuta aunque
    el Engine este corriendo.

    Estrategia:
      1. Engine limpio.
      2. Registrar un FB en estado idle (``nStep=0``).
      3. Llamar ``_tick_all()`` (el ciclo del loop, sin
         esperar 100 ms).
      4. Verificar que el ``tick_count`` del FB sigue en 0.
    """
    engine = Engine()
    fb = _CountingFB(name="Idle")
    # El FB arranca en ``nStep=0`` (idle) por defecto.
    assert fb.nStep == 0
    engine.register_fb("Idle", fb)

    await engine._tick_all()
    assert fb.tick_count == 0
    assert fb.nStep == 0  # no avanzo


@pytest.mark.asyncio
async def test_engine_loop_skips_done_fbs() -> None:
    """El Engine skipea FBs en ``nStep=n_done``: no los tickea.

    Verifica que un FB que ya termino OK no se vuelve a tickear.
    Es importante para no repetir trabajo y para que el HMI
    no reciba eventos duplicados.
    """
    engine = Engine()
    fb = _CountingFB(name="Done")
    fb.nStep = fb.n_done  # 30
    engine.register_fb("Done", fb)

    await engine._tick_all()
    assert fb.tick_count == 0


@pytest.mark.asyncio
async def test_engine_loop_skips_error_fbs() -> None:
    """El Engine skipea FBs en ``nStep=n_error``: no los tickea.

    Tras un error, el FB queda en estado terminal. Solo un
    nuevo ``start()`` lo rearma. Mientras tanto, el Engine
    no lo molesta.
    """
    engine = Engine()
    fb = _CountingFB(name="Err")
    fb.nStep = fb.n_error  # 99
    engine.register_fb("Err", fb)

    await engine._tick_all()
    assert fb.tick_count == 0


@pytest.mark.asyncio
async def test_engine_loop_ticks_active_fbs() -> None:
    """El Engine tickea FBs en etapas activas (entre idle y done)."""
    engine = Engine()
    fb = _CountingFB(name="Active", advance=True)
    fb.start()  # nStep=10
    assert fb.nStep == 10
    engine.register_fb("Active", fb)

    await engine._tick_all()
    assert fb.tick_count == 1
    # El FB avanza 10 -> 20.
    assert fb.nStep == 20


@pytest.mark.asyncio
async def test_engine_loop_advances_active_fb_to_done() -> None:
    """Varios ticks llevan al FB activo hasta ``n_done`` (30)."""
    engine = Engine()
    fb = _CountingFB(name="Avance", advance=True)
    fb.start()
    engine.register_fb("Avance", fb)

    # 1er tick: 10 -> 20.
    await engine._tick_all()
    assert fb.nStep == 20
    # 2do tick: 20 -> 30 (done). A partir de aqui, el Engine skipea.
    await engine._tick_all()
    assert fb.nStep == 30
    # 3er tick: ya en done, no tickea.
    await engine._tick_all()
    assert fb.tick_count == 2  # solo los 2 primeros


@pytest.mark.asyncio
async def test_engine_loop_handles_fb_exception() -> None:
    """Si un FB lanza en ``tick()``, el Engine lo pone en error y sigue.

    Verifica la captura defensiva en ``_tick_all()``: aunque un
    FB olvide capturar su propia excepcion, el loop no se cae.
    El FB queda en ``n_error`` y los demas FBs siguen tickeando.
    """
    engine = Engine()
    bad = _RaisingFB(name="Bad")
    bad.start()  # nStep=10
    good = _CountingFB(name="Good", advance=True)
    good.start()  # nStep=10
    engine.register_fb("Bad", bad)
    engine.register_fb("Good", good)

    await engine._tick_all()
    # El FB malo quedo en error.
    assert bad.nStep == bad.n_error == 99
    assert bad.nError == 1
    assert "exploto" in bad.error_msg
    # El FB bueno sigue tickeando normalmente (no se vio afectado
    # por la excepcion del otro).
    assert good.tick_count == 1
    assert good.nStep == 20


@pytest.mark.asyncio
async def test_engine_publishes_on_fb_step_change() -> None:
    """El Engine publica al bus SSE cuando un FB cambia de ``nStep``.

    Verifica lazo cerrado Engine -> bus: tras un tick que cambia
    ``nStep``, ``_publish_fb_state()`` envia el estado a los
    suscriptores.

    Estrategia:
      1. Suscribirse al bus.
      2. Registrar un FB activo.
      3. ``_tick_all()`` -> el FB cambia de 10 a 20, el Engine
         publica. La cola recibe el evento con ``nStep=20``.
    """
    engine = Engine()
    q = engine.subscribe()
    fb = _CountingFB(name="Pub", advance=True)
    fb.start()
    engine.register_fb("Pub", fb)

    await engine._tick_all()
    event = q.get_nowait()
    assert event["name"] == "Pub"
    assert event["nStep"] == 20


def test_engine_snapshot_contains_dbs_and_fbs() -> None:
    """``get_snapshot()`` incluye todas las DBs y FBs registrados."""
    engine = Engine()
    engine.register_db("test_db", DB_EstadoConexion(tia_state="connected"))
    fb = _CountingFB(name="Snap")
    engine.register_fb("Snap", fb)

    snap = engine.get_snapshot()
    assert snap["type"] == "snapshot"
    # DBs: estado_conexion (del singleton del modulo) + test_db.
    assert "test_db" in snap["dbs"]
    assert snap["dbs"]["test_db"]["tia_state"] == "connected"
    # FBs.
    assert "Snap" in snap["fbs"]
    assert snap["fbs"]["Snap"]["name"] == "Snap"
    assert snap["fbs"]["Snap"]["nStep"] == 0


@pytest.mark.asyncio
async def test_engine_start_stop_loop_is_idempotent() -> None:
    """``start_loop()`` y ``stop_loop()`` son idempotentes.

    Verifica que el Engine se puede rearrancar despues de pararlo
    (util para tests, y para ``lifespan`` si FastAPI lo invoca
    mas de una vez por error).
    """
    engine = Engine()
    # start_loop crea la task.
    engine.start_loop()
    assert engine._task is not None
    # start_loop de nuevo: no-op (la task sigue viva).
    engine.start_loop()
    assert engine._task is not None
    # stop_loop espera y limpia.
    await engine.stop_loop()
    assert engine._task is None
    # start_loop de nuevo: crea una nueva task.
    engine.start_loop()
    assert engine._task is not None
    await engine.stop_loop()
