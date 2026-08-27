"""Tests del endpoint REST ``POST /api/v1/alimentacion/aplicar-comentarios-disp``.

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
    g = MagicMock(spec=TIAProcessGateway)
    g.update_disp_instance_comments_batch = AsyncMock(
        return_value={
            "success": True,
            "operations_executed": 6,
            "details": [],
        }
    )
    return g


@pytest.fixture
def mock_config_manager() -> MagicMock:
    cm = MagicMock()
    cm.list_hw_types_active.return_value = ["ed", "ea", "sa", "v", "m", "m_vf"]
    cm.get_tia_folder_dispositivos.return_value = "2000_Dispositivos"
    cm.get_dispositivo_config.side_effect = lambda hw: MagicMock(
        db_name=f"DB20{ord(hw[0]):02d}_{hw.upper()}",
        db_array_name=hw.upper(),
    )
    return cm


@pytest.fixture
def mock_app_state() -> MagicMock:
    state = MagicMock()
    state.all_devices.return_value = [MagicMock()]
    state.get_devices.side_effect = lambda hw: [
        MagicMock(numero=1, plc_comentario="X")
    ]
    return state


@pytest.fixture
def client(
    mock_gateway: MagicMock,
    mock_config_manager: MagicMock,
    mock_app_state: MagicMock,
) -> TestClient:
    app = create_app(gateway=mock_gateway)
    app.state.config_manager = mock_config_manager
    app.state.app_state = mock_app_state
    app.state.progress_tracker = ProgressTracker()
    return TestClient(app)


def test_endpoint_aplica_comentarios(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """POST aplica el use case con el plc_name del body."""
    resp = client.post(
        "/api/v1/alimentacion/aplicar-comentarios-disp",
        json={"plc_name": "PLC_X"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["plc_name"] == "PLC_X"
    assert body["success"] is True
    assert body["operations_executed"] == 6
    mock_gateway.update_disp_instance_comments_batch.assert_called_once()


def test_endpoint_llama_gateway_con_target_folder_del_config(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """El endpoint propaga el target_folder resuelto por ConfigManager."""
    resp = client.post(
        "/api/v1/alimentacion/aplicar-comentarios-disp",
        json={"plc_name": "PLC_X"},
    )
    assert resp.status_code == 200
    call_kwargs = mock_gateway.update_disp_instance_comments_batch.call_args.kwargs
    assert call_kwargs["target_folder"] == "2000_Dispositivos"


def test_endpoint_error_500_si_use_case_falla(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """Si el use case lanza, el endpoint responde 500."""
    mock_gateway.update_disp_instance_comments_batch.side_effect = RuntimeError(
        "Boom"
    )
    resp = client.post(
        "/api/v1/alimentacion/aplicar-comentarios-disp",
        json={"plc_name": "PLC_X"},
    )
    assert resp.status_code == 500
    assert "Boom" in resp.json()["detail"]


def test_endpoint_pide_plc_name(
    client: TestClient,
) -> None:
    """Body sin plc_name → 422 (pydantic)."""
    resp = client.post(
        "/api/v1/alimentacion/aplicar-comentarios-disp", json={}
    )
    assert resp.status_code == 422
