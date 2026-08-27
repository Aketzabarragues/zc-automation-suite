"""Tests para ``GET /api/v1/areas`` y ``ListAreasUseCase``.

Cubre:
  1. Endpoint con config por defecto (1 área: alimentacion).
  2. El área ``alimentacion`` tiene ``available=True`` y un icono
     no vacío.
  3. Endpoint con un config de fixture con 2 departamentos.
  4. Endpoint con config sin bloque ``departments`` → ``[]``.
  5. Estructura exacta de ``AreaOut`` (5 campos, sin extras).

Usa el ``TestClient`` de FastAPI con un gateway mockeado (igual que
``test_sync_router_dependency_injection``) y ``ConfigManager``
apuntando a un ``config.json`` en ``tmp_path``.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from application.areas import AreaInfo, ListAreasUseCase
from core.infrastructure.config_manager import ConfigManager
from core.infrastructure.gateway import TIAProcessGateway
from interfaces.web_server.app import create_app


# ── Fixtures ──────────────────────────────────────────────────────────

_SINGLE_DEPT_CONFIG = {
    "_comment": "Single-department fixture for areas tests.",
    "departments": {
        "alimentacion": {
            "global_config_table_name": "000_Config_Dispositivos",
            "tia_folders": {
                "proceso":      "003_Procesos",
                "dispositivos": "2000_Dispositivos",
                "nmax":         "000_Sistema",
            },
            "Dispositivos": {
                "ed": {
                    "db_name":       "DB2000_ED",
                    "db_array_name": "ED",
                    "tag_table":     "2000_Disp_ED",
                    "config_table":  "000_Config_Dispositivos",
                },
                "ea": {
                    "db_name":       "DB2001_EA",
                    "db_array_name": "EA",
                    "tag_table":     "2000_Disp_EA",
                    "config_table":  "000_Config_Dispositivos",
                },
            },
        },
    },
}


_TWO_DEPTS_CONFIG = {
    "_comment": "Two-department fixture for areas tests.",
    "departments": {
        "alimentacion": {
            "global_config_table_name": "000_Config_Dispositivos",
            "tia_folders": {
                "proceso":      "003_Procesos",
                "dispositivos": "2000_Dispositivos",
                "nmax":         "000_Sistema",
            },
            "Dispositivos": {
                "ed": {
                    "db_name":       "DB2000_ED",
                    "db_array_name": "ED",
                    "tag_table":     "2000_Disp_ED",
                    "config_table":  "000_Config_Dispositivos",
                },
            },
        },
        "envasado": {
            # Dept "en construcción": sin Dispositivos → available=False.
            "_comment": "Dept sin dispositivos aún.",
            "global_config_table_name": "000_Config_Dispositivos",
            "tia_folders": {
                "proceso":      "003_Procesos",
                "dispositivos": "2000_Dispositivos",
                "nmax":         "000_Sistema",
            },
            "Dispositivos": {},
        },
    },
}


_EMPTY_DEPTS_CONFIG = {
    "_comment": "Config vacío para verificar fallback a [].",
    "departments": {},
}


_NO_DEPTS_CONFIG = {
    "_comment": "Config sin el bloque departments en absoluto.",
}


@pytest.fixture
def make_config(tmp_path: Path):
    """Devuelve una factoría que escribe un config.json en tmp_path."""

    def _factory(payload: dict) -> Path:
        path = tmp_path / "config.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    return _factory


@pytest.fixture
def make_client(make_config):
    """Devuelve una factoría de TestClient con un gateway mockeado."""

    def _factory(payload: dict) -> TestClient:
        cfg_path = make_config(payload)
        gw = MagicMock(spec=TIAProcessGateway)
        app = create_app(gateway=gw)
        # Sustituir el config_manager que app.py construye por defecto
        # por uno que apunte a nuestro fixture en tmp_path.
        app.state.config_manager = ConfigManager(config_path=cfg_path)
        return TestClient(app)

    return _factory


# ── Tests del endpoint ────────────────────────────────────────────────


def test_areas_endpoint_returns_alimentacion(make_client) -> None:
    """Caso 1: con config por defecto, devuelve al menos 'alimentacion'."""
    client = make_client(_SINGLE_DEPT_CONFIG)
    response = client.get("/api/v1/areas")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) >= 1
    keys = {a["key"] for a in body}
    assert "alimentacion" in keys


def test_areas_alimentacion_has_icon_and_available(make_client) -> None:
    """Caso 2: alimentacion tiene available=True y un icono no vacío."""
    client = make_client(_SINGLE_DEPT_CONFIG)
    response = client.get("/api/v1/areas")

    assert response.status_code == 200
    body = response.json()
    alimentacion = next(a for a in body if a["key"] == "alimentacion")

    assert alimentacion["available"] is True
    assert isinstance(alimentacion["icon"], str)
    assert alimentacion["icon"].strip() != ""  # icono no vacío
    assert isinstance(alimentacion["label"], str)
    assert alimentacion["label"].strip() != ""  # label no vacío


def test_areas_endpoint_with_two_departments(make_client) -> None:
    """Caso 3: con dos departamentos, devuelve los dos con sus keys."""
    client = make_client(_TWO_DEPTS_CONFIG)
    response = client.get("/api/v1/areas")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 2

    by_key = {a["key"]: a for a in body}
    assert "alimentacion" in by_key
    assert "envasado" in by_key
    assert by_key["alimentacion"]["available"] is True
    assert by_key["envasado"]["available"] is False


def test_areas_endpoint_empty_departments_returns_empty_list(
    make_client,
) -> None:
    """Caso 4: departments={} → [] con HTTP 200, no 500."""
    client = make_client(_EMPTY_DEPTS_CONFIG)
    response = client.get("/api/v1/areas")

    assert response.status_code == 200
    assert response.json() == []


def test_areas_endpoint_no_departments_key_returns_empty_list(
    make_client,
) -> None:
    """Caso 4-bis: sin clave 'departments' → [] con HTTP 200."""
    client = make_client(_NO_DEPTS_CONFIG)
    response = client.get("/api/v1/areas")

    assert response.status_code == 200
    assert response.json() == []


def test_areas_endpoint_response_model_fields(make_client) -> None:
    """Caso 5: cada elemento tiene EXACTAMENTE los 5 campos AreaOut."""
    client = make_client(_TWO_DEPTS_CONFIG)
    response = client.get("/api/v1/areas")

    assert response.status_code == 200
    body = response.json()
    expected = {"key", "label", "description", "icon", "available"}
    for area in body:
        assert set(area.keys()) == expected, (
            f"AreaOut tiene campos {set(area.keys())}, "
            f"esperados {expected}"
        )


# ── Tests unitarios del use case (sin HTTP) ──────────────────────────


def test_list_areas_use_case_handles_missing_departments_block(
    make_config,
) -> None:
    """Use case: departments ausente → []. Defensivo, no lanza."""
    cfg_path = make_config(_NO_DEPTS_CONFIG)
    cm = ConfigManager(config_path=cfg_path)
    uc = ListAreasUseCase(cm)
    assert uc.execute() == []


def test_list_areas_use_case_handles_malformed_department(
    make_config, caplog: pytest.LogCaptureFixture,
) -> None:
    """Use case: un departamento mal formado se omite, no rompe el resto."""
    bad_cfg = {
        "departments": {
            "ok_dept": {
                "Dispositivos": {
                    "ed": {
                        "db_name": "DB2000_ED",
                        "db_array_name": "ED",
                        "tag_table": "2000_Disp_ED",
                        "config_table": "000_Config_Dispositivos",
                    },
                },
            },
            "bad_dept": "esto no es un dict",
        }
    }
    cfg_path = make_config(bad_cfg)
    cm = ConfigManager(config_path=cfg_path)

    with caplog.at_level("WARNING"):
        uc = ListAreasUseCase(cm)
        result = uc.execute()

    keys = {a.key for a in result}
    assert "ok_dept" in keys
    assert "bad_dept" not in keys
    assert any("mal formado" in m for m in caplog.messages)


def test_list_areas_use_case_honors_display_override(make_config) -> None:
    """Use case: el bloque opcional 'display' del JSON tiene prioridad."""
    cfg = {
        "departments": {
            "alimentacion": {
                "Dispositivos": {
                    "ed": {
                        "db_name": "DB2000_ED",
                        "db_array_name": "ED",
                        "tag_table": "2000_Disp_ED",
                        "config_table": "000_Config_Dispositivos",
                    },
                },
                "display": {
                    "label": "Custom Label",
                    "icon": "🥖",
                    "description": "Custom desc",
                },
            },
        }
    }
    cfg_path = make_config(cfg)
    cm = ConfigManager(config_path=cfg_path)
    uc = ListAreasUseCase(cm)
    result = uc.execute()

    assert len(result) == 1
    a = result[0]
    assert a.key == "alimentacion"
    assert a.label == "Custom Label"
    assert a.icon == "🥖"
    assert a.description == "Custom desc"
    assert a.available is True


def test_area_info_is_frozen_dataclass() -> None:
    """AreaInfo es frozen: no se puede mutar (defensa de contrato)."""
    a = AreaInfo(
        key="alimentacion",
        label="X",
        description="",
        icon="🍞",
        available=True,
    )
    with pytest.raises(Exception):  # FrozenInstanceError
        a.key = "otra"  # type: ignore[misc]
