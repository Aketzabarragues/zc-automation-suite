"""Fixtures compartidas entre tests del refactor de web/REST.

Cubre los tests que mockean el gateway de TIA Portal:
  - ``tests/test_tia_connection_endpoints.py`` (PR 5a)
  - ``tests/test_worker_status.py`` (sept-2026, indicador worker_alive)

Mantener las fixtures aqui (en vez de duplicarlas en cada test)
sigue la convencion estandar de pytest: ``conftest.py`` se
descubre automaticamente sin imports explicitos.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from core.application.progress_buffer import ProgressTracker
from core.infrastructure.gateway import TIAProcessGateway
from interfaces.web_server.app import create_app


@pytest.fixture
def mock_gateway() -> MagicMock:
    """Gateway ``MagicMock(spec=TIAProcessGateway)`` con defaults neutros.

    Los tests especificos sobreescriben lo que necesiten. Los metodos
    que el router invoca (``get_project_info``, ``get_plcs``,
    ``connect``, ``disconnect``) se anaden caso por caso.
    """
    g = MagicMock(spec=TIAProcessGateway)
    # Defaults sensatos: estado inicial ``disconnected`` y atributos
    # del worker persistente presentes. Asi el router nunca ve
    # ``AttributeError`` al hacer ``getattr``.
    g._connection_state = "disconnected"
    g._project_path = None
    g._last_ping_ok = None
    g._last_error = None
    g._last_portal_pid = None
    return g


@pytest.fixture
def client(mock_gateway: MagicMock) -> TestClient:
    """TestClient con la app FastAPI montada y el gateway mockeado."""
    app = create_app(gateway=mock_gateway)
    app.state.progress_tracker = ProgressTracker()
    return TestClient(app)
