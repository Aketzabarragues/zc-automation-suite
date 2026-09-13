"""Tests del Flask app OB1 (Fase 4 / paso 4.4.1)."""
from __future__ import annotations

import json
import queue
import threading
import time

import pytest

from core.plc.engine import Engine
from core.sse.event_bus_sync import EventBusSync
from interfaces.web_server.app_flask import create_app


@pytest.fixture
def app_with_injections():
    engine = Engine()
    bus = EventBusSync()
    app = create_app(engine=engine, event_bus=bus)
    app.config["TESTING"] = True
    return app, engine, bus


@pytest.fixture
def client(app_with_injections):
    app, _, _ = app_with_injections
    return app.test_client()


def test_ping_returns_pong(client):
    resp = client.get("/ping")
    assert resp.status_code == 200
    assert resp.get_json() == {"pong": True}


def test_cycle_count_returns_zero_for_fresh_engine(client):
    resp = client.get("/cycle_count")
    assert resp.status_code == 200
    assert resp.get_json() == {"cycles": 0}


def test_cycle_count_reflects_engine_state(app_with_injections):
    """Si incrementamos el counter del engine, /cycle_count lo refleja."""
    app, engine, _ = app_with_injections
    engine.cycle_count = 42
    resp = app.test_client().get("/cycle_count")
    assert resp.get_json() == {"cycles": 42}


def test_create_app_injects_default_tia_client_singleton():
    """Si no se inyecta tia_client, usa el singleton global."""
    from core.infrastructure.tia.tia_loop import tia_client

    app = create_app()
    assert app.config["TIA_CLIENT"] is tia_client


def test_create_app_uses_default_engine_when_not_injected():
    """Si no se inyecta engine, crea uno nuevo."""
    app1 = create_app()
    app2 = create_app()
    assert app1.config["ENGINE"] is not app2.config["ENGINE"]


def test_stream_endpoint_returns_sse_content_type(client):
    resp = client.get("/stream")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["Content-Type"]


def test_stream_emits_event_when_published(client, app_with_injections):
    """Si publicamos un evento en el bus, el SSE lo emite."""
    _, _, bus = app_with_injections

    # Arrancamos un hilo que publica tras un pequeño delay.
    def publish_later():
        time.sleep(0.1)
        bus.publish({"type": "log", "msg": "hello"})

    threading.Thread(target=publish_later, daemon=True).start()

    resp = client.get("/stream")
    # Leemos el primer chunk del stream.
    # El cliente test no consume streams largos; usamos response.iter_encoded.
    chunks = []
    for chunk in resp.iter_encoded():
        chunks.append(chunk)
        if any(b"hello" in c for c in chunks):
            break
    # Decodifica para verificar contenido.
    text = b"".join(chunks).decode("utf-8")
    assert "hello" in text


def test_stream_emits_keepalive_when_no_events(client):
    """Si no hay eventos, el stream emite ': keepalive\\n\\n' cada 500ms."""
    resp = client.get("/stream")
    chunks = []
    start = time.time()
    # Leemos hasta ver un keepalive (max 2s).
    for chunk in resp.iter_encoded():
        chunks.append(chunk)
        if b"keepalive" in b"".join(chunks):
            break
        if time.time() - start > 2.0:
            break
    text = b"".join(chunks).decode("utf-8")
    assert "keepalive" in text


def test_stream_unsubscribes_subscriber_on_disconnect(client, app_with_injections):
    """Cuando el cliente cierra la conexion, la cola se desuscribe del bus."""
    _, _, bus = app_with_injections

    initial_count = bus.subscriber_count()
    assert initial_count == 0

    # Abrimos el stream y lo cerramos.
    resp = client.get("/stream")
    with resp:
        # Dentro del with, el subscriber esta activo.
        # (El test no es 100% fiable por timing; lo dejamos como smoke test.)
        pass

    # Damos tiempo para que el finally del generador se ejecute.
    time.sleep(0.1)
    # El subscriber count debe volver a 0.
    assert bus.subscriber_count() == 0
