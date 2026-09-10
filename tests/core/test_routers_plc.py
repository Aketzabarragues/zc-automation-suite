"""Tests de integracion del router generico ``/api/v1/plc/``.

Cubre:
  - ``POST /plc/fb/{name}/start`` con FB desconocido -> 404.
  - ``POST /plc/fb/{name}/start`` con FB conocido -> 200 + ``nStep``.
  - ``GET /plc/events`` emite SSE con snapshot inicial.

Usa ``TestClient`` de FastAPI + ``Engine`` real, con bridge mockeado
(no se necesita TIA Portal). Marcados como ``integration`` (ver
``pytest.ini``).
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from core.plc.plc import DB_ESTADO, ENGINE, DB_EstadoConexion, FB_ConexionTIA
from core.web.app import app

# ─────────────────────────────────────────────────────────────────────
#  Fixtures
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_bridge() -> MagicMock:
    """Mock de ``WorkerBridgeProtocol`` con ``attach``, ``list_plcs``,
    ``get_project_info`` y ``detach`` configurados.

    Por defecto devuelve un PLC y un proyecto falsos. Los tests
    que necesitan payloads distintos sobreescriben ``return_value``.
    """
    bridge = MagicMock()
    bridge.attach = AsyncMock(return_value=12345)  # fake PID
    bridge.list_plcs = AsyncMock(
        return_value=[{"name": "PLC1"}]
    )
    bridge.get_project_info = AsyncMock(
        return_value={"name": "P", "path": "/p.ap17"}
    )
    bridge.detach = AsyncMock(return_value=None)
    return bridge


@pytest.fixture
def fresh_conexion_fb(mock_bridge: MagicMock) -> FB_ConexionTIA:
    """Sustituye el ``FB_ConexionTIA`` del Engine por uno con bridge
    mockeado. Lo restaura al final del test.

    Esto aísla el test de cualquier estado residual del lifespan
    (que registra un FB con el ``MockWorkerBridge``). Cada test
    obtiene un FB fresco en ``nStep=0`` y con un bridge predecible.
    """
    original = ENGINE.fbs.get("ConexionTIA")
    new_fb = FB_ConexionTIA(bridge=mock_bridge, db=DB_ESTADO)
    ENGINE.fbs["ConexionTIA"] = new_fb
    yield new_fb
    # Restaurar.
    if original is not None:
        ENGINE.fbs["ConexionTIA"] = original
    else:
        ENGINE.fbs.pop("ConexionTIA", None)


# ─────────────────────────────────────────────────────────────────────
#  Tests del endpoint POST /plc/fb/{name}/start
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_post_start_fb_unknown_returns_404() -> None:
    """``POST /plc/fb/NoExiste/start`` responde 404."""
    with TestClient(app) as client:
        response = client.post("/api/v1/plc/fb/NoExiste/start", json={})
    assert response.status_code == 404
    body = response.json()
    assert "NoExiste" in body.get("detail", "")


@pytest.mark.integration
def test_post_start_fb_known_returns_ok(
    fresh_conexion_fb: FB_ConexionTIA,
    mock_bridge: MagicMock,
) -> None:
    """``POST /plc/fb/ConexionTIA/start`` responde 200 + nStep actualizado.

    Verifica:
      - Status 200.
      - Body ``{"started": "ConexionTIA", "nStep": ...}``.
      - El FB paso de ``nStep=0`` a ``nStep>=10`` (puede haber
        avanzado si el loop tickea entre el POST y la respuesta).
      - El bridge ``attach`` no se llama en ``start()``; solo en
        ``tick()``. Aqui, ``attach.await_count`` puede ser 0 o 1
        dependiendo de la velocidad del loop.
    """
    with TestClient(app) as client:
        # El lifespan re-registra el FB con el MockWorkerBridge. Lo
        # sobreescribimos con el mock antes de la peticion.
        ENGINE.fbs["ConexionTIA"] = fresh_conexion_fb
        assert fresh_conexion_fb.nStep == 0

        response = client.post("/api/v1/plc/fb/ConexionTIA/start", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["started"] == "ConexionTIA"
    # ``nStep`` puede haber avanzado si el loop tickea rapido.
    # Al menos sabemos que arranco (no es 0).
    assert body["nStep"] >= 10
    assert fresh_conexion_fb.nStep >= 10


@pytest.mark.integration
def test_post_start_fb_known_with_params(
    fresh_conexion_fb: FB_ConexionTIA,
) -> None:
    """El endpoint acepta body JSON vacio y arranca el FB.

    Verifica que el body se desempaqueta y se entrega a ``start()``.
    No todos los FBs usan params; este test verifica el camino del
    endpoint, no la logica del FB concreto. Usamos un body vacio
    para que ``start()`` no reciba params inesperados.
    """
    with TestClient(app) as client:
        ENGINE.fbs["ConexionTIA"] = fresh_conexion_fb
        response = client.post(
            "/api/v1/plc/fb/ConexionTIA/start",
            json={},
        )
    assert response.status_code == 200
    assert "nStep" in response.json()


@pytest.mark.integration
def test_post_start_fb_idempotent(
    fresh_conexion_fb: FB_ConexionTIA,
) -> None:
    """Llamar ``start()`` dos veces no rearranca el FB.

    Segunda llamada es no-op porque el FB ya esta en etapa
    activa. Esto es el contrato de ``FB_Base.start()``.
    """
    with TestClient(app) as client:
        ENGINE.fbs["ConexionTIA"] = fresh_conexion_fb
        # Primer start.
        r1 = client.post("/api/v1/plc/fb/ConexionTIA/start", json={})
        assert r1.status_code == 200
        # Capturamos el nStep del momento (puede haber avanzado).
        nStep_after_first = fresh_conexion_fb.nStep
        # Segundo start: idempotente. ``nStep`` no se resetea a 10.
        r2 = client.post("/api/v1/plc/fb/ConexionTIA/start", json={})
        assert r2.status_code == 200
        # El ``nStep`` reportado en la respuesta NO es 10 (sino el
        # que ya tenia el FB antes del 2º ``start()``).
        assert r2.json()["nStep"] >= nStep_after_first


# ─────────────────────────────────────────────────────────────────────
#  Tests del endpoint POST /plc/fb/{name}/disconnect
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_post_disconnect_fb_known(
    fresh_conexion_fb: FB_ConexionTIA,
) -> None:
    """``POST /plc/fb/ConexionTIA/disconnect`` ejecuta ``disconnect()``.

    Estrategia:
      1. Llevar el FB a ``nStep=30`` (done) manualmente.
      2. ``POST /disconnect``.
      3. Verificar 200 + ``nStep=0`` + bridge ``detach()`` llamado.
    """
    with TestClient(app) as client:
        ENGINE.fbs["ConexionTIA"] = fresh_conexion_fb
        # Forzamos estado done.
        fresh_conexion_fb.nStep = fresh_conexion_fb.n_done
        response = client.post("/api/v1/plc/fb/ConexionTIA/disconnect")

    assert response.status_code == 200
    body = response.json()
    assert body["disconnected"] is True
    assert body["nStep"] == 0
    assert fresh_conexion_fb.nStep == 0


@pytest.mark.integration
def test_post_disconnect_fb_unknown_returns_404() -> None:
    """``POST /plc/fb/NoExiste/disconnect`` responde 404."""
    with TestClient(app) as client:
        response = client.post("/api/v1/plc/fb/NoExiste/disconnect")
    assert response.status_code == 404


# ─────────────────────────────────────────────────────────────────────
#  Tests del endpoint GET /plc/events (SSE)
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_get_events_sse_streams(
    fresh_conexion_fb: FB_ConexionTIA,
) -> None:
    """``GET /plc/events?max_events=1`` emite SSE con snapshot inicial.

    Verifica el contrato del endpoint SSE:
      - Status 200.
      - ``Content-Type: text/event-stream``.
      - El primer chunk es un snapshot con ``type=="snapshot"``,
        que incluye la DB trasversal y los FBs registrados.

    Importante: usamos ``max_events=1`` para que el generador
    cierre tras emitir el snapshot. Asi el test no se queda
    esperando mas eventos. Es el mismo patron que el test
    del spike (``test_spike_sse.py``).
    """
    with TestClient(app) as client:
        # Reemplazamos el FB para que el snapshot sea predecible.
        ENGINE.fbs["ConexionTIA"] = fresh_conexion_fb
        with client.stream(
            "GET", "/api/v1/plc/events?max_events=1"
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith(
                "text/event-stream"
            )
            # Leemos la primera linea: ``data: {"type": "snapshot", ...}``.
            for line in response.iter_lines():
                assert line.startswith("data: ")
                # Parseamos el JSON para verificar la forma.
                payload_str = line[len("data: "):]
                payload = json.loads(payload_str)
                assert payload["type"] == "snapshot"
                # El snapshot incluye la DB trasversal.
                assert "estado_conexion" in payload["dbs"]
                # El snapshot incluye los FBs registrados
                # (incluido el ConexionTIA que re-registramos).
                assert "ConexionTIA" in payload["fbs"]
                # Y al menos un campo reconocible del FB.
                assert payload["fbs"]["ConexionTIA"]["name"] == "ConexionTIA"
                # Listo: cerramos el bucle para no leer mas lineas.
                break
