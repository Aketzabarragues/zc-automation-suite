"""Tests del blueprint area_manifests (Fase 4 / paso 4.4.4)."""
from __future__ import annotations

from unittest.mock import MagicMock

from interfaces.web_server.app_flask import create_app


def _app_with_registry(registry_mock):
    app = create_app()
    app.config["TESTING"] = True
    # Monkey-patch del AreaRegistry.discover() via sys.modules.
    import core.application.area_registry as ar_mod
    original_discover = ar_mod.AreaRegistry.discover
    ar_mod.AreaRegistry.discover = lambda: registry_mock
    return app.test_client(), ar_mod, original_discover


def _restore(ar_mod, original):
    ar_mod.AreaRegistry.discover = original


def test_get_manifest_returns_payload_when_area_exists():
    registry = MagicMock()
    spec = MagicMock()
    spec.contributes_frontend_manifest = lambda: {"name": "Alimentacion", "routes": []}
    registry.get.return_value = spec

    client, ar_mod, original = _app_with_registry(registry)
    try:
        resp = client.get("/api/v1/areas/alimentacion/manifest")
        assert resp.status_code == 200
        assert resp.get_json() == {"name": "Alimentacion", "routes": []}
    finally:
        _restore(ar_mod, original)


def test_get_manifest_returns_404_when_area_not_found():
    registry = MagicMock()
    registry.get.return_value = None

    client, ar_mod, original = _app_with_registry(registry)
    try:
        resp = client.get("/api/v1/areas/no_existe/manifest")
        assert resp.status_code == 404
        assert "no encontrada" in resp.get_json()["error"]
    finally:
        _restore(ar_mod, original)


def test_get_manifest_returns_404_when_area_has_no_manifest():
    registry = MagicMock()
    spec = MagicMock()
    spec.contributes_frontend_manifest = None  # area sin manifest
    registry.get.return_value = spec

    client, ar_mod, original = _app_with_registry(registry)
    try:
        resp = client.get("/api/v1/areas/sin_manifest/manifest")
        assert resp.status_code == 404
        assert "sin manifest" in resp.get_json()["error"]
    finally:
        _restore(ar_mod, original)
