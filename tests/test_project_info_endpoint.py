"""Tests del endpoint REST ``GET /api/v1/portal/project-info``.

Patrón TestClient + ``app.dependency_overrides`` (AGENTS.md §1):
no instanciamos gateways; los mocks se inyectan vía ``Depends``.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from core.application.progress_buffer import ProgressTracker
from core.infrastructure.gateway import TIAProcessGateway
from interfaces.web_server.app import create_app


@pytest.fixture
def mock_gateway() -> MagicMock:
    """Gateway con ``get_project_info`` mockeado (caso OK por defecto)."""
    g = MagicMock(spec=TIAProcessGateway)
    g.get_project_info = AsyncMock(
        return_value={
            "name": "PROYECTO_X",
            "path": r"D:\_PROY\PROYECTO_X\PROYECTO_X.ap18",
            "author": "ABH",
        }
    )
    return g


@pytest.fixture
def client(mock_gateway: MagicMock) -> TestClient:
    app = create_app(gateway=mock_gateway)
    app.state.progress_tracker = ProgressTracker()
    return TestClient(app)


def test_endpoint_devuelve_nombre_del_proyecto(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """GET OK → 200 con ``ok=True`` y ``project_info.name`` poblado."""
    resp = client.get("/api/v1/portal/project-info")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["project_info"]["name"] == "PROYECTO_X"
    assert body["project_info"]["author"] == "ABH"
    mock_gateway.get_project_info.assert_awaited_once()


def test_endpoint_error_si_tia_no_conectado(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """Si ``get_project_info`` lanza (TIA no conectado) → 200 con ``ok=False``.

    El endpoint NUNCA devuelve 500: degrada a ``{"ok": false, "error": ...}``
    para que la SPA pinte la línea vacía sin romper el sidebar.
    """
    mock_gateway.get_project_info.side_effect = RuntimeError(
        "attach falló: no hay TIA Portal abierto"
    )

    resp = client.get("/api/v1/portal/project-info")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "TIA Portal no conectado" in body["error"]
    # El ``detail`` lleva la traza original para diagnóstico.
    assert "attach falló" in body["detail"]


def test_endpoint_llama_gateway_con_force_refresh_true(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """El endpoint pasa SIEMPRE ``force_refresh=True``.

    Si el operario cambia de proyecto en TIA Portal y vuelve a la SPA,
    el endpoint no debe servir caché stale: el gateway invalida en
    ``open_project`` / ``close_project`` pero el endpoint fuerza el
    bypass como doble red de seguridad.
    """
    client.get("/api/v1/portal/project-info")
    call_kwargs = mock_gateway.get_project_info.call_args.kwargs
    assert call_kwargs.get("force_refresh") is True


def test_endpoint_montado_en_create_app(mock_gateway: MagicMock) -> None:
    """La ruta ``/api/v1/portal/project-info`` está registrada en ``create_app``.

    Red de seguridad contra refactors del shell que rompan el wiring
    sin que CI lo detecte. Equivalente a
    ``test_shell_*_is_mounted`` en ``tests/test_app_router_discovery.py``.
    """
    app = create_app(gateway=mock_gateway)
    client = TestClient(app)
    resp = client.get("/api/v1/portal/project-info")
    # 200 o 200+ok=False (si el mock devuelve error), pero NUNCA 404
    # (eso indicaría que la ruta no está montada).
    assert resp.status_code != 404
