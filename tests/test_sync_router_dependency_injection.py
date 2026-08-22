"""Test de regresión: el router ``/api/v1/sync/*`` inyecta ``config_manager``.

Bug original: ``_build_use_case`` solo pasaba ``gateway`` y ``state`` a
``SyncDispositivosInstancesUseCase``, pero su constructor
**requiere** ``config_manager`` (obligatorio, no opcional).
Resultado: cualquier POST a ``/api/v1/sync/preview`` o
``/api/v1/sync/commit`` fallaba con ``TypeError: __init__() missing
1 required positional argument: 'config_manager'`` → 500.

Este test monta la app con un gateway mock y verifica que el
endpoint NO falle por una excepción de DI.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from infrastructure.gateway import TIAProcessGateway
from interfaces.web_server.app import create_app


def test_sync_preview_does_not_fail_with_di_error() -> None:
    """POST /api/v1/sync/preview no debe fallar por DI de config_manager."""
    gw = MagicMock(spec=TIAProcessGateway)
    gw.get_plcs = AsyncMock(return_value=["PLC1"])
    gw.export_plc_tags_xml = AsyncMock(return_value="/tmp/dummy")

    app = create_app(gateway=gw)
    client = TestClient(app)

    response = client.post(
        "/api/v1/sync/preview", json={"plc_name": "PLC1"}
    )

    # La fix: ya no debe haber 500 por TypeError de DI.
    # El body puede ser cualquier JSON (200 o 500 esperado por
    # fallos de lógica de negocio, pero NO por DI).
    if response.status_code == 500:
        body = response.text
        assert "config_manager" not in body, (
            f"DI regression: {body}"
        )
        assert "missing 1 required positional argument" not in body, (
            f"DI regression: {body}"
        )

    # El endpoint responde con un JSON (éxito o error de negocio).
    assert response.headers.get("content-type", "").startswith(
        "application/json"
    )


def test_sync_commit_does_not_fail_with_di_error() -> None:
    """POST /api/v1/sync/commit no debe fallar por DI de config_manager."""
    gw = MagicMock(spec=TIAProcessGateway)
    gw.get_plcs = AsyncMock(return_value=["PLC1"])
    gw.export_plc_tags_xml = AsyncMock(return_value="/tmp/dummy")
    gw.execute_transactional_batch = AsyncMock(
        return_value={"success": True, "operations_executed": 0, "details": []}
    )

    app = create_app(gateway=gw)
    client = TestClient(app)

    response = client.post(
        "/api/v1/sync/commit",
        json={
            "plc_name": "PLC1",
            "prevision": {
                "agregados": [], "eliminados": [], "renombrados": [],
            },
        },
    )

    if response.status_code == 500:
        body = response.text
        assert "config_manager" not in body, f"DI regression: {body}"
        assert "missing 1 required positional argument" not in body, (
            f"DI regression: {body}"
        )

    assert response.headers.get("content-type", "").startswith(
        "application/json"
    )


def test_app_state_has_config_manager() -> None:
    """El Composition Root debe inyectar ``config_manager`` en ``app.state``.

    Garantiza que el ``get_config_manager`` dependency puede recuperar
    la instancia sin ``AttributeError``.
    """
    gw = MagicMock(spec=TIAProcessGateway)
    app = create_app(gateway=gw)

    assert hasattr(app.state, "config_manager")
    assert app.state.config_manager is not None
    # Sanity: el config_manager expone los getters esperados.
    assert app.state.config_manager.get_tia_folder_nmax() == "000_Sistema"
    assert (
        app.state.config_manager.get_tia_folder_dispositivos()
        == "2000_Dispositivos"
    )
