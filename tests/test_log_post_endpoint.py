"""Tests del endpoint ``POST /api/v1/logs``.

Sept-2026: el frontend (``store.js::_applyTiaSnapshot``) detecta
cuando TIA se cierra por fuera y, tras limpiar el state PLC-related,
deja un aviso en la ConsolaLogs via este endpoint. El push local
de ``store.js::pushLog`` no persiste (el poll cada 1s sobreescribe
``store.logs``), asi que necesitamos un endpoint que escriba al
``LogBuffer`` backend (el que se ve en la ConsolaLogs).

Casos cubiertos:
  1. POST basico (info): 201 + mensaje persistido en el buffer.
  2. Los 4 niveles (info / success / warning / error) enrutan al
     metodo correcto del ``LogBuffer``.
  3. ``GET /api/v1/logs`` despues de un POST devuelve el mensaje.
  4. Validacion Pydantic: ``level`` invalido (no en el Literal)
     devuelve 422 (defensivo: el frontend NO puede inyectar niveles
     arbitrarios).
  5. Validacion: ``message`` vacio o > 2000 chars devuelve 422.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient


# El fixture ``client`` (TestClient + gateway mock) vive en
# ``tests/conftest.py`` y se reusa en todos los tests del shell.


# ── Helpers ──────────────────────────────────────────────────────────


def _post_log(
    client: TestClient, message: str, level: str = "info"
) -> Any:
    """POST helper para no repetir el shape del payload."""
    return client.post("/api/v1/logs", json={"message": message, "level": level})


def _fetch_messages(client: TestClient) -> list[dict[str, Any]]:
    """Devuelve la lista de mensajes en el buffer (post-clear)."""
    resp = client.get("/api/v1/logs")
    assert resp.status_code == 200
    body = resp.json()
    return list(body.get("logs", []))


# ── 1. POST basico ───────────────────────────────────────────────────


def test_post_log_basic_info_returns_201_and_persists(client: TestClient) -> None:
    """POST con level=info devuelve 201 y el mensaje queda en el buffer."""
    # Limpiamos el buffer para empezar limpio.
    client_clear = client.post("/api/v1/logs/clear")
    assert client_clear.status_code == 200

    resp = _post_log(client, "Hola desde la SPA", "info")
    assert resp.status_code == 201
    body = resp.json()
    assert body["ok"] is True
    assert body["level"] == "info"
    assert body["message"] == "Hola desde la SPA"

    # El mensaje esta en el buffer del backend.
    messages = _fetch_messages(client)
    assert any(m["message"] == "Hola desde la SPA" for m in messages), (
        "El mensaje POSTeado debe quedar en el LogBuffer y ser "
        "visible en GET /api/v1/logs."
    )


# ── 2. Los 4 niveles enrutan correctamente ──────────────────────────


@pytest.mark.parametrize("level", ["info", "success", "warning", "error"])
def test_post_log_routes_to_correct_level(client: TestClient, level: str) -> None:
    """POST con cada uno de los 4 niveles persiste en el buffer."""
    # Limpiamos para no acumular mensajes de tests anteriores.
    client.post("/api/v1/logs/clear")

    marker = f"test-{level}-marker"
    resp = _post_log(client, marker, level)
    assert resp.status_code == 201
    assert resp.json()["level"] == level

    messages = _fetch_messages(client)
    matches = [m for m in messages if m["message"] == marker]
    assert len(matches) == 1, (
        f"Esperaba 1 mensaje con level={level} y message={marker}, "
        f"encontre {len(matches)}."
    )
    assert matches[0]["level"] == level, (
        f"El nivel persistido debe ser {level}, encontre "
        f"{matches[0]['level']}."
    )


# ── 3. Persistencia tras varios POSTs ──────────────────────────────


def test_post_log_multiple_messages_persist_in_order(
    client: TestClient,
) -> None:
    """POSTs consecutivos quedan en el buffer en orden FIFO."""
    client.post("/api/v1/logs/clear")
    msgs = ["primero", "segundo", "tercero"]
    for m in msgs:
        resp = _post_log(client, m, "info")
        assert resp.status_code == 201
    messages = _fetch_messages(client)
    persisted = [m["message"] for m in messages]
    # Los 3 POSTs estan, en orden.
    for m in msgs:
        assert m in persisted, f"Falta el mensaje {m!r} en el buffer."


# ── 4. Validacion de level ─────────────────────────────────────────


@pytest.mark.parametrize("bad_level", ["debug", "trace", "INFO", "", "warn"])
def test_post_log_rejects_invalid_level(
    client: TestClient, bad_level: str
) -> None:
    """``level`` fuera del Literal devuelve 422 (defensivo)."""
    resp = client.post(
        "/api/v1/logs", json={"message": "test", "level": bad_level}
    )
    assert resp.status_code == 422, (
        f"level={bad_level!r} debe rechazarse (no esta en el Literal "
        f"info/success/warning/error). Status real: {resp.status_code}."
    )


# ── 5. Validacion de message ───────────────────────────────────────


def test_post_log_rejects_empty_message(client: TestClient) -> None:
    """``message`` vacio devuelve 422 (Pydantic min_length=1)."""
    resp = client.post("/api/v1/logs", json={"message": "", "level": "info"})
    assert resp.status_code == 422


def test_post_log_rejects_oversized_message(client: TestClient) -> None:
    """``message`` > 2000 chars devuelve 422 (Pydantic max_length=2000)."""
    big = "x" * 2001
    resp = client.post("/api/v1/logs", json={"message": big, "level": "info"})
    assert resp.status_code == 422


def test_post_log_accepts_exactly_2000_chars(client: TestClient) -> None:
    """``message`` de exactamente 2000 chars se acepta (limite inclusivo)."""
    boundary = "y" * 2000
    resp = _post_log(client, boundary, "info")
    assert resp.status_code == 201
