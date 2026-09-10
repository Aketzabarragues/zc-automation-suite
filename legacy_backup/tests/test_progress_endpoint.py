"""Tests para los endpoints ``/api/v1/progress/current`` y ``/api/v1/progress/clear``.

Cubre:
  1. ``GET /api/v1/progress/current`` con tracker vacío -> ``active=False``.
  2. ``GET`` con ``begin()`` previo refleja los stages.
  3. ``POST /api/v1/progress/clear`` vacía el tracker.
  4. El snapshot devuelto tiene la forma exacta que la SPA espera
     (todos los campos: active, operation, label, current, total,
     percent, stages, started_at, finished_at, error).

Sigue el mismo patrón que ``test_areas_endpoint.py``: TestClient
de FastAPI + gateway mockeado.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.application.progress_buffer import (  # noqa: E402
    ProgressTracker,
    get_progress_tracker,
)
from core.infrastructure.gateway import TIAProcessGateway  # noqa: E402
from interfaces.web_server.app import create_app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    """TestClient con gateway mockeado y tracker limpio."""
    # Resetear el tracker antes de cada test (orden-independiente).
    get_progress_tracker().clear()
    gateway = MagicMock(spec=TIAProcessGateway)
    app = create_app(gateway)
    return TestClient(app)


def test_get_progress_when_empty_returns_inactive(client: TestClient) -> None:
    """Tracker vacío -> ``active=False`` con stages vacíos."""
    r = client.get("/api/v1/progress/current")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    progress = data["progress"]
    assert progress["active"] is False
    assert progress["operation"] is None
    assert progress["label"] is None
    assert progress["current"] == 0
    assert progress["total"] == 0
    assert progress["percent"] == 0
    assert progress["stages"] == []
    assert progress["started_at"] is None
    assert progress["finished_at"] is None
    assert progress["error"] is None


def test_get_progress_reflects_active_operation(client: TestClient) -> None:
    """Tracker con ``begin()`` y un stage en running -> refleja todo."""
    tracker = get_progress_tracker()
    tracker.begin(
        operation="preview",
        label="Test preview",
        stages=["export", "diff", "nmax"],
    )
    tracker.start_stage("export", "Iniciando...")

    r = client.get("/api/v1/progress/current")
    data = r.json()
    progress = data["progress"]
    assert progress["active"] is True
    assert progress["operation"] == "preview"
    assert progress["label"] == "Test preview"
    assert progress["total"] == 3
    assert progress["current"] == 0  # Ninguno en done/error aún
    assert progress["percent"] == 0
    assert len(progress["stages"]) == 3

    export = next(s for s in progress["stages"] if s["id"] == "export")
    diff = next(s for s in progress["stages"] if s["id"] == "diff")
    nmax = next(s for s in progress["stages"] if s["id"] == "nmax")
    assert export["status"] == "running"
    assert export["detail"] == "Iniciando..."
    assert export["started_at"] is not None
    assert export["finished_at"] is None
    assert diff["status"] == "pending"
    assert nmax["status"] == "pending"


def test_post_progress_clear_empties_tracker(client: TestClient) -> None:
    """``POST /api/v1/progress/clear`` vacía el tracker."""
    tracker = get_progress_tracker()
    tracker.begin("op", "label", ["a", "b"])
    tracker.start_stage("a")
    tracker.finish_stage("a")

    # Confirmar que hay algo.
    r1 = client.get("/api/v1/progress/current")
    assert r1.json()["progress"]["active"] is True

    # Clear.
    r2 = client.post("/api/v1/progress/clear")
    assert r2.status_code == 200
    assert r2.json() == {"cleared": True}

    # Verificar que está vacío.
    r3 = client.get("/api/v1/progress/current")
    progress = r3.json()["progress"]
    assert progress["active"] is False
    assert progress["stages"] == []


def test_progress_response_has_exact_spa_shape(client: TestClient) -> None:
    """El snapshot tiene EXACTAMENTE los campos que ``ProgressOverlay.js``
    espera (defensa contra drift del contrato)."""
    r = client.get("/api/v1/progress/current")
    progress = r.json()["progress"]
    expected_keys = {
        "active",
        "operation",
        "label",
        "current",
        "total",
        "percent",
        "stages",
        "started_at",
        "finished_at",
        "error",
    }
    assert set(progress.keys()) == expected_keys

    # Stages tienen exactamente: id, label, status, detail, started_at, finished_at.
    for s in progress["stages"]:
        assert set(s.keys()) == {
            "id",
            "label",
            "status",
            "detail",
            "started_at",
            "finished_at",
        }
