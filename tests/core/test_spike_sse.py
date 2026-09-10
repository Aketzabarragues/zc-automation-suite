"""Fase 0.5 spike: smoke tests del endpoint SSE.

Cubren los dos endpoints del router de spike:
  - ``GET /api/v1/ping`` → JSON ``{"ping": "pong"}``.
  - ``GET /api/v1/events`` → ``text/event-stream`` con un primer evento
    ``data: {"ping": "pong"}``.

Marcados como ``integration`` (registrado en ``pytest.ini``): usan
``TestClient`` de FastAPI, no tocan la red, pero ejercitan el ciclo
completo de un endpoint (routing + serialización + streaming).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.web.app import app


@pytest.mark.integration
def test_ping_endpoint() -> None:
    """``GET /api/v1/ping`` responde ``{"ping": "pong"}`` con 200."""
    with TestClient(app) as client:
        response = client.get("/api/v1/ping")

    assert response.status_code == 200
    assert response.json() == {"ping": "pong"}


@pytest.mark.integration
def test_events_endpoint_streams() -> None:
    """``GET /api/v1/events`` emite un primer evento SSE con ``{tick: 0}``.

    Verifica:
      - ``Content-Type: text/event-stream``
      - La primera línea del stream es exactamente
        ``data: {"tick": 0}`` (formato SSE, sin ``\\n`` final).

    IMPORTANTE: el endpoint hace un loop ``while True`` con ticks cada
    500ms, asi que NO usamos ``next(iter_lines())`` que bloquearia
    esperando mas datos. En su lugar, leemos con un break tras la
    primera linea; el ``with client.stream()`` cierra la conexion
    al salir del bloque.
    """
    with TestClient(app) as client:
        # ``max_events=1`` cierra el stream tras el primer evento
        # (modo test). En produccion el endpoint es infinito.
        with client.stream("GET", "/api/v1/events?max_events=1") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            # ``iter_lines`` decodifica bytes → str y separa por '\\n'.
            # El primer chunk es ``data: {"tick": 0}\\n\\n``, por lo
            # que la primera línea (sin newline) es exactamente
            # ``data: {"tick": 0}``. Leemos con break para no quedar
            # atrapados en el bucle ``while True`` del endpoint.
            for line in response.iter_lines():
                assert line == 'data: {"tick": 0}'
                break
