"""Tests del discovery de routers vía ``AreaRegistry`` (PR 4).

Cubre que el shell web (``interfaces/web_server/app.py``) monta los
routers específicos del área de alimentación descubriéndolos vía
``AreaRegistry.for_each("contributes_routers", app=app)``, NO
importándolos directamente.

Estrategia: ``POST`` con body inválido debe devolver ``422`` (pydantic)
— eso prueba que la ruta EXISTE. Si la ruta NO existiera, sería
``404``. La diferencia entre ``422`` y ``404`` es la prueba de que
el router del área está cableado.

Nota sobre GET: el shell monta la SPA en ``/`` (``NoCacheStaticFiles``)
que captura los ``GET`` a paths no manejados por routers y devuelve
``404``. Por eso NO usamos ``GET 405`` como prueba: el comportamiento
real es ``GET → 404`` (la SPA responde con su 404 interno), no
``405`` (que sería lo que devolvería FastAPI si no hubiera mount
capturando). Los ``POST 422`` son la prueba limpia de que la ruta
está montada.

Routers del área que se verifican:
  - ``POST /api/v1/alimentacion/aplicar-comentarios-disp``  → 422 sin body
  - ``POST /api/v1/sync/preview``                          → 422 sin body
  - ``POST /api/v1/sync/commit``                           → 422 sin body
  - ``POST /api/v1/excel/upload``                           → 422 sin file

Routers comunes del shell (sanity check, no cambian en PR 4):
  - ``GET  /api/v1/areas``                                 → 200
  - ``GET  /api/v1/catalog``                               → 200
  - ``GET  /api/v1/logs``                                  → 200
  - ``GET  /api/v1/progress/current``                      → 200
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from core.infrastructure.gateway import TIAProcessGateway
from interfaces.web_server.app import create_app


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def mock_gateway() -> MagicMock:
    """Gateway mockeado: cumple el ``spec`` de ``TIAProcessGateway``
    para que ``create_app`` no se queje, pero no se invoca en estos
    tests (todos los hits del área son ``422`` por body inválido,
    los comunes son ``GET`` que no tocan el gateway)."""
    return MagicMock(spec=TIAProcessGateway)


@pytest.fixture
def client(mock_gateway: MagicMock) -> TestClient:
    """TestClient con un gateway mockeado y la app completa."""
    return TestClient(create_app(gateway=mock_gateway))


# ── Sanity checks: routers comunes del shell siguen montados ──────────


def test_shell_areas_endpoint_is_mounted(client: TestClient) -> None:
    """``GET /api/v1/areas`` responde 200 (router común, intacto)."""
    resp = client.get("/api/v1/areas")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert any(a["key"] == "alimentacion" for a in body)


def test_shell_catalog_endpoint_is_mounted(client: TestClient) -> None:
    """``GET /api/v1/catalog`` responde 200 (router común, intacto)."""
    resp = client.get("/api/v1/catalog")
    assert resp.status_code == 200
    body = resp.json()
    # El área de alimentación aporta sus ``device_tabs`` via
    # ``contributes_catalog``. El shell los envuelve bajo ``catalog``
    # junto con la marca de éxito.
    assert body.get("ok") is True
    assert "catalog" in body
    assert "device_tabs" in body["catalog"]
    assert len(body["catalog"]["device_tabs"]) >= 1


def test_shell_logs_endpoint_is_mounted(client: TestClient) -> None:
    """``GET /api/v1/logs`` responde 200 (router común, intacto)."""
    resp = client.get("/api/v1/logs")
    assert resp.status_code == 200
    assert "logs" in resp.json()


def test_shell_progress_current_is_mounted(client: TestClient) -> None:
    """``GET /api/v1/progress/current`` responde 200 (router común)."""
    resp = client.get("/api/v1/progress/current")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "progress" in body


# ── PR 4: routers del área de alimentación, descubiertos vía registry ─


def test_alimentacion_endpoint_is_mounted(
    client: TestClient,
) -> None:
    """``POST /api/v1/alimentacion/aplicar-comentarios-disp`` está montado.

    Sin body válido, pydantic responde 422. Lo importante: NO es 404
    (lo que probaría que el router del área no se montó).
    """
    resp = client.post(
        "/api/v1/alimentacion/aplicar-comentarios-disp", json={}
    )
    assert resp.status_code == 422
    body = resp.json()
    # El detalle de pydantic menciona el campo faltante ``plc_name``.
    assert "plc_name" in str(body)


def test_sync_preview_endpoint_is_mounted(client: TestClient) -> None:
    """``POST /api/v1/sync/preview`` está montado (sin body → 422)."""
    resp = client.post("/api/v1/sync/preview", json={})
    assert resp.status_code == 422
    assert "plc_name" in str(resp.json())


def test_sync_commit_endpoint_is_mounted(client: TestClient) -> None:
    """``POST /api/v1/sync/commit`` está montado (sin body → 422).

    Faltan ``plc_name`` y ``prevision``.
    """
    resp = client.post("/api/v1/sync/commit", json={})
    assert resp.status_code == 422
    detail_str = str(resp.json())
    assert "plc_name" in detail_str or "prevision" in detail_str


def test_excel_upload_endpoint_is_mounted(client: TestClient) -> None:
    """``POST /api/v1/excel/upload`` está montado (sin file → 422)."""
    resp = client.post("/api/v1/excel/upload")
    assert resp.status_code == 422


# ── Robustez: la app se puede instanciar varias veces ─────────────────


def test_create_app_is_idempotent(mock_gateway: MagicMock) -> None:
    """``create_app(gateway)`` se puede llamar varias veces.

    El ``AreaRegistry`` es Singleton thread-safe; el primer
    ``discover()`` puebla el cache y los siguientes retornan la
    misma instancia. Esto verifica que múltiples ``create_app`` no
    duplican ni pierden routers.
    """
    app1 = create_app(gateway=mock_gateway)
    app2 = create_app(gateway=mock_gateway)
    c1 = TestClient(app1)
    c2 = TestClient(app2)
    # Ambos clientes ven los routers del área.
    assert c1.post(
        "/api/v1/alimentacion/aplicar-comentarios-disp", json={}
    ).status_code == 422
    assert c2.post(
        "/api/v1/alimentacion/aplicar-comentarios-disp", json={}
    ).status_code == 422
    # Y los routers comunes.
    assert c1.get("/api/v1/areas").status_code == 200
    assert c2.get("/api/v1/areas").status_code == 200


# ── Conteo de routers del área ────────────────────────────────────────


def test_area_register_routers_uses_registry_dispatch() -> None:
    """El shell usa ``AreaRegistry.for_each("contributes_routers", app=app)``.

    Verifica que el área de alimentación tiene cableado ese hook
    y que el callable es invocable con un objeto que tenga
    ``include_router``. Esto es una guarda contra regresiones
    donde alguien vuelve a importar el router directamente en
    ``app.py`` y olvida el discovery.
    """
    from core.application.area_registry import AreaRegistry

    spec = AreaRegistry.discover().get("alimentacion")
    assert spec is not None
    assert spec.contributes_routers is not None
    assert callable(spec.contributes_routers)

    # El callable debe ser invocable con un objeto que tenga
    # ``include_router`` (como ``FastAPI``). Mockeamos un app fake
    # para verificar que registra exactamente 3 routers (alimentacion,
    # sync, excel).
    fake_app = MagicMock()
    fake_app.include_router = MagicMock()

    spec.contributes_routers(fake_app)

    # Exactamente 3 routers del área.
    assert fake_app.include_router.call_count == 3
    # Cada llamada recibe un APIRouter de FastAPI (no None, no un mock).
    for call in fake_app.include_router.call_args_list:
        router_arg = call.args[0]
        # El router es un APIRouter real de FastAPI.
        from fastapi import APIRouter
        assert isinstance(router_arg, APIRouter), (
            f"register_routers debe pasar APIRouter a include_router, "
            f"recibió {type(router_arg).__name__}"
        )
