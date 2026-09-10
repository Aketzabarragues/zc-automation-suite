"""Tests del bus SSE del Engine (subscribe / unsubscribe / publish).

Verifica:
  - Dos suscriptores reciben el mismo evento.
  - Desuscribirse detiene la entrega de eventos.

Estos son parte de los 6 tests obligatorios de ``.clinerules`` §12
(test 3: dos suscriptores SSE reciben el mismo evento; desconectar
uno no afecta al otro).
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from core.plc.plc import Engine, FB_Base

# ─────────────────────────────────────────────────────────────────────
#  Helpers de test
# ─────────────────────────────────────────────────────────────────────


class _StubFB(FB_Base):
    """FB minimo para tests del bus: no implementa ``tick()``.

    Solo lo usamos para invocar ``Engine._publish_fb_state(fb)`` y
    verificar que los suscriptores reciben el payload.
    """

    n_done: int = 30  # no es relevante para el test del bus

    def __init__(self, name: str = "Stub") -> None:
        super().__init__(nombre=name)
        self.tick_count: int = 0

    async def tick(self) -> None:  # pragma: no cover - no se usa
        self.tick_count += 1


# ─────────────────────────────────────────────────────────────────────
#  Tests del bus
# ─────────────────────────────────────────────────────────────────────


def test_two_subscribers_receive_same_event() -> None:
    """Dos suscriptores reciben el mismo evento publicado.

    Verifica el caso principal del bus SSE: el Engine publica a
    TODOS los suscriptores activos. Ninguno se queda sin recibir
    el evento.

    Estrategia:
      1. Crear un Engine limpio (no el singleton, para no
         contaminar el estado global entre tests).
      2. Suscribirse 2 veces -> 2 colas distintas.
      3. Publicar un evento.
      4. Ambas colas tienen el mismo payload.
    """
    engine = Engine()
    q1 = engine.subscribe()
    q2 = engine.subscribe()
    assert q1 is not q2  # cada suscriptor tiene su propia cola

    # Publicamos un payload arbitrario (como haria ``_publish_fb_state``).
    payload = {"type": "fb", "name": "X", "nStep": 10}
    engine._publish_raw(payload)

    # Ambas colas recibieron el evento.
    assert q1.get_nowait() == payload
    assert q2.get_nowait() == payload


def test_unsubscribe_stops_delivery() -> None:
    """Desuscribirse detiene la entrega de eventos.

    Verifica que tras ``unsubscribe()``, el suscriptor NO recibe
    mas eventos. Esto es el comportamiento que el ``try/finally``
    del generador SSE aprovecha al cerrar la conexion.

    Estrategia:
      1. Suscribirse -> cola ``q``.
      2. Publicar un evento: ``q`` lo recibe.
      3. Desuscribirse.
      4. Publicar otro evento: ``q`` NO lo recibe (queda vacia,
         ``get_nowait()`` lanza ``QueueEmpty``).
    """
    engine = Engine()
    q = engine.subscribe()

    # Antes de desuscribir: recibe.
    engine._publish_raw({"type": "fb", "nStep": 10})
    assert q.get_nowait() == {"type": "fb", "nStep": 10}

    # Desuscribirse.
    engine.unsubscribe(q)

    # Despues: NO recibe.
    engine._publish_raw({"type": "fb", "nStep": 20})
    with pytest.raises(asyncio.QueueEmpty):
        q.get_nowait()


def test_publish_via_fb_state_uses_get_state() -> None:
    """``_publish_fb_state(fb)`` envia ``fb.get_state()`` al bus.

    Verifica que el bus entrega el snapshot del FB, no el FB en
    si. El HMI recibe ``dict`` JSON-serializable.
    """
    engine = Engine()
    q = engine.subscribe()

    fb = _StubFB(name="FB_test")
    fb.nStep = 20
    fb.step_name = "haciendo algo"
    engine._publish_fb_state(fb)

    received = q.get_nowait()
    assert received["name"] == "FB_test"
    assert received["nStep"] == 20
    assert received["step_name"] == "haciendo algo"
    assert received["type"] == "fb"  # ni done ni error


def test_unsubscribe_is_idempotent() -> None:
    """``unsubscribe()`` es idempotente: doble unsubscribe no falla.

    Esto es importante porque el ``finally`` del generador SSE
    siempre llama ``unsubscribe``, y un unsubscribe redundante
    no debe romper el bus.
    """
    engine = Engine()
    q = engine.subscribe()
    engine.unsubscribe(q)
    # 2ª llamada: no debe lanzar.
    engine.unsubscribe(q)
    # Publicamos: nada se rompe.
    engine._publish_raw({"type": "x"})
    with pytest.raises(asyncio.QueueEmpty):
        q.get_nowait()


def test_slow_subscriber_does_not_block_engine() -> None:
    """Un suscriptor lento no bloquea al Engine (eventos se descartan).

    Si la cola de un suscriptor esta llena (``maxsize=200``),
    ``put_nowait`` lanza ``QueueFull`` y el Engine lo ignora
    silenciosamente. Asi, un cliente SSE que se cuelga no
    paraliza el loop.

    Estrategia:
      1. Suscribirse.
      2. Llenar la cola con 200 eventos (el ``maxsize``).
      3. Publicar 1 evento mas: el Engine lo descarta; el test
         no se cuelga (verificable con ``timeout``).
    """
    engine = Engine()
    q = engine.subscribe()
    # ``maxsize=200``: lo llenamos directamente con 200 payloads.
    for i in range(200):
        engine._publish_raw({"i": i})
    # Ahora cualquier publicacion adicional se descarta. Publicamos
    # 5 mas y verificamos que no hay excepcion y la cola sigue llena.
    for i in range(200, 205):
        engine._publish_raw({"i": i})
    # La cola sigue llena de los primeros 200.
    assert q.qsize() == 200
    # El primer evento encolado es el primero publicado.
    assert q.get_nowait() == {"i": 0}
