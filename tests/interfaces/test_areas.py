"""Tests del blueprint areas."""
from __future__ import annotations

from unittest.mock import MagicMock

from core.web_server.app_flask import create_app


def _app_with_cm(config_manager):
    app = create_app(config_manager=config_manager)
    app.config["TESTING"] = True
    return app.test_client()


def test_list_areas_returns_dataclass_list():
    """Areas se devuelven como dicts via asdict()."""
    from dataclasses import dataclass

    @dataclass
    class _Area:
        key: str
        label: str
        description: str
        icon: str
        available: bool

    cm = MagicMock()
    # Mockeamos ListAreasUseCase para evitar tocar el registro real.
    import core.composition.app_area_registry as ar_mod
    original_uc = ar_mod.ListAreasUseCase
    ar_mod.ListAreasUseCase = lambda cm: MagicMock(
        execute=lambda: [
            _Area("alimentacion", "Alimentacion", "Area PLCs", "icon1", True),
            _Area("energia", "Energia", "Area energia", "icon2", False),
        ]
    )
    try:
        client = _app_with_cm(cm)
        resp = client.get("/api/v1/areas")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 2
        assert data[0]["key"] == "alimentacion"
        assert data[0]["available"] is True
        assert data[1]["key"] == "energia"
        assert data[1]["available"] is False
    finally:
        ar_mod.ListAreasUseCase = original_uc


def test_list_areas_empty_returns_empty_list():
    cm = MagicMock()
    import core.composition.app_area_registry as ar_mod
    original_uc = ar_mod.ListAreasUseCase
    ar_mod.ListAreasUseCase = lambda cm: MagicMock(execute=lambda: [])
    try:
        client = _app_with_cm(cm)
        resp = client.get("/api/v1/areas")
        assert resp.status_code == 200
        assert resp.get_json() == []
    finally:
        ar_mod.ListAreasUseCase = original_uc
