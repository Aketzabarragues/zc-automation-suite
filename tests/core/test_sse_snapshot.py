"""Tests del snapshot inicial del SSE (DA-011).

DA-001 (sept-2026): el stream SSE queda abierto en ``await queue.get()``
esperando eventos. TestClient/httpx se cuelgan esperando EOF. Por
tanto, estos tests son UNIT del ``_build_snapshot()`` y del
``Engine.snapshot()``, sin HTTP. La validación end-to-end con
``curl -N`` se hace en la demo contra TIA real (DA-007 paso 2).
"""
from __future__ import annotations

import asyncio

from core.plc.engine import Engine
from core.plc.function_base import FunctionBase
from core.sse.stream import _build_snapshot


def test_build_snapshot_sin_engine_devuelve_placeholder() -> None:
    """Si no hay engine (tests sin lifespan), snapshot vacio historico.

    Defensivo: el handler del endpoint nunca debe 500ear si
    ``app.state.engine`` no existe (caso típico: tests con
    ``FastAPI()`` directo sin ``create_app``).
    """
    snap = _build_snapshot(None)
    assert snap == {"type": "snapshot", "dbs": {}, "fbs": {}}


def test_engine_snapshot_incluye_fbs_registrados() -> None:
    """``Engine.snapshot()`` refleja los FBs registrados con
    ``nStep`` y ``error_msg`` (el contrato con el frontend)."""
    eng = Engine(event_bus=None)
    # FB1 arrancado (nStep=10) y FB2 sin arrancar (nStep=0).
    # ``start()`` es async; lo ejecutamos con asyncio.run en este
    # test sync (no usamos pytest-asyncio para no añadir deps).
    fb1 = FunctionBase(nombre="Test1")
    asyncio.run(fb1.start())
    fb2 = FunctionBase(nombre="Test2")
    eng.register_fb("Test1", fb1)
    eng.register_fb("Test2", fb2)

    snap = eng.snapshot()
    assert snap["dbs"] == {}  # DA-011 no toca DBs (eso es 3.3.3.x)
    assert set(snap["fbs"].keys()) == {"Test1", "Test2"}
    # Cada entrada tiene los 2 campos del contrato.
    for _name, data in snap["fbs"].items():
        assert "nStep" in data
        assert "error_msg" in data
    # Estado concreto: fb1 en nStep=10 (start OK), fb2 en 0 (idle).
    assert snap["fbs"]["Test1"]["nStep"] == 10
    assert snap["fbs"]["Test1"]["error_msg"] is None
    assert snap["fbs"]["Test2"]["nStep"] == 0
    assert snap["fbs"]["Test2"]["error_msg"] is None


def test_build_snapshot_con_engine_delega_y_annade_type() -> None:
    """``_build_snapshot(engine)`` usa ``engine.snapshot()`` y le añade
    ``type='snapshot'`` para que el cliente ramifique sin None-checks."""
    eng = Engine(event_bus=None)
    eng.register_fb("X", FunctionBase(nombre="X"))
    snap = _build_snapshot(eng)
    assert snap["type"] == "snapshot"
    assert "X" in snap["fbs"]
    assert snap["fbs"]["X"]["nStep"] == 0
    assert snap["fbs"]["X"]["error_msg"] is None

