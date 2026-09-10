"""Test E2E del paso 1.1.5: ``GET /api/v1/stream`` funciona.

Sube la app FastAPI completa (``create_app``) en un thread con un
gateway mockeado y un ``EventBus`` real, después hace una petición
HTTP real con ``httpx`` (el equivalente programático de ``curl -N``)
y verifica:

  - Status 200, ``content-type: text/event-stream``.
  - El primer chunk es el snapshot vacío ``{"type": "snapshot", ...}``.

Por qué uvicorn en thread (y no TestClient/ASGITransport): ya
comprobado en 1.0.4 que los clientes in-process se cuelgan con
streams infinitos. uvicorn es la única forma fiable de verificar
un endpoint SSE end-to-end.

Usa el patrón del proyecto: ``tests/test_web_supervisor.py`` ya
arranca uvicorn en threads reales contra puertos efímeros.
"""
from __future__ import annotations

import socket
import threading
import time
from unittest.mock import MagicMock

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from interfaces.web_server.app import create_app


def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(port: int, timeout_s: float = 5.0) -> None:
    """Bloquea hasta que el puerto acepte conexiones o ``timeout_s``."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError(f"Server no arrancó en puerto {port} en {timeout_s}s")


def test_create_app_incluye_router_sse_y_bus_en_state() -> None:
    """Verificación estática: ``create_app`` monta el router y expone
    el ``event_bus`` en ``app.state``. (No requiere uvicorn.)"""
    mock_gateway = MagicMock()
    app = create_app(gateway=mock_gateway)

    # El bus existe en app.state.
    assert hasattr(app.state, "event_bus")
    assert app.state.event_bus is not None

    # El router está registrado bajo la ruta /api/v1/stream.
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/api/v1/stream" in paths


def test_curl_stream_devuelve_snapshot_en_app_real() -> None:
    """``curl /api/v1/stream`` (vía httpx contra uvicorn real):
    status 200 + content-type correcto + primer chunk = snapshot."""
    mock_gateway = MagicMock()
    app = create_app(gateway=mock_gateway)

    port = _find_free_port()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    _wait_for_server(port)

    try:
        with httpx.Client(timeout=httpx.Timeout(5.0)) as client:
            with client.stream(
                "GET", f"http://127.0.0.1:{port}/api/v1/stream"
            ) as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith(
                    "text/event-stream"
                )

                # Leemos solo el primer chunk (snapshot). El server
                # queda esperando más eventos (eso es el contrato SSE).
                chunks: list[str] = []
                for chunk in response.iter_text():
                    chunks.append(chunk)
                    if "".join(chunks).count("data:") >= 1:
                        break

        body = "".join(chunks)
        assert body.startswith("data: ")
        # El payload del snapshot es exactamente el del plan.
        import json

        payload = body[len("data: "):].rstrip("\n")
        assert json.loads(payload) == {
            "type": "snapshot",
            "dbs": {},
            "fbs": {},
        }
    finally:
        server.should_exit = True
        thread.join(timeout=5)
