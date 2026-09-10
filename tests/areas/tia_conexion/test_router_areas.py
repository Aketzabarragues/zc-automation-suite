"""Tests de integracion del router de areas (``/api/v1/areas``).

Cubre:
  - ``GET /api/v1/areas`` devuelve el catalogo con el ``AreaSpec``
    registrado por el area ``tia_conexion``.
  - ``GET /api/v1/areas/tia_conexion/manifest`` devuelve el
    manifest del area con la shape esperada.
  - ``GET /api/v1/areas/no_existe/manifest`` responde **404**.
  - El ``AreaSpec`` se OMITE del payload cuando ``description`` es
    vacio (no se manda un string vacio al cliente).

Usa ``TestClient`` de FastAPI. La app se importa con su ``lifespan``
real (que arranca el Engine y un ``WorkerBridge`` stub). Marcados
como ``area_smoke`` (ver ``pytest.ini``).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.application import area_registry as reg
from core.web.app import app

# ─────────────────────────────────────────────────────────────────────
#  Tests del catalogo
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.area_smoke
def test_list_areas_includes_tia_conexion() -> None:
    """``GET /api/v1/areas`` devuelve al menos el area ``tia_conexion``.

    Estrategia:
      - Levantamos la app (``with TestClient(app)``) para ejecutar
        su ``lifespan``, que registra el area durante ``create_app``.
      - Verificamos que el catalogo contiene un item con
        ``key == "tia_conexion"`` y el resto de campos del ``AreaSpec``.
    """
    with TestClient(app) as client:
        response = client.get("/api/v1/areas")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    # Filtramos por ``key`` en vez de indexar (el area se registra
    # al ``create_app``, asi que ya esta en el catalogo al primer
    # request).
    tia = next((a for a in body if a["key"] == "tia_conexion"), None)
    assert tia is not None, f"area 'tia_conexion' no encontrada en {body}"
    assert tia["label"] == "Conexion TIA"
    assert tia["icon"] == "🔌"
    assert tia["available"] is True
    # El ``description`` no es vacio en este area, asi que debe
    # aparecer en el payload.
    assert "description" in tia
    assert tia["description"]  # no vacio


@pytest.mark.area_smoke
def test_list_areas_omits_empty_description() -> None:
    """``GET /api/v1/areas`` OMITE ``description`` si esta vacio.

    Esto valida que el router no manda un string vacio al cliente
    (mantiene el payload limpio). Probamos registrando un area
    adicional con ``description=""`` directamente en el registry
    (no necesitamos que la app la incluya por ``lifespan``).
    """
    # El ``reset()`` lo hace ``_clean_registry`` (autouse).
    reg.register(
        reg.AreaSpec(key="test_sin_desc", label="Test sin desc", description="")
    )
    with TestClient(app) as client:
        response = client.get("/api/v1/areas")

    assert response.status_code == 200
    body = response.json()
    item = next((a for a in body if a["key"] == "test_sin_desc"), None)
    assert item is not None
    # ``description`` NO debe estar en el payload (string vacio se omite).
    assert "description" not in item


# ─────────────────────────────────────────────────────────────────────
#  Tests del manifest
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.area_smoke
def test_get_manifest_tia_conexion_returns_ok() -> None:
    """``GET /api/v1/areas/tia_conexion/manifest`` devuelve el manifest.

    Verifica:
      - Status 200.
      - Shape esperado: ``id``, ``label``, ``icon``, ``components``,
        ``loaders``.
      - El loader del componente principal apunta al path correcto.
    """
    with TestClient(app) as client:
        response = client.get("/api/v1/areas/tia_conexion/manifest")

    assert response.status_code == 200
    body = response.json()
    # Campos top-level.
    assert body["id"] == "tia_conexion"
    assert body["label"] == "Conexion TIA"
    assert body["icon"] == "🔌"
    # Componentes: la SPA necesita esta shape para hacer routing.
    assert "components" in body
    assert body["components"]["landing"] == "ConexionTIAView"
    assert body["components"]["sidebar"] is None
    assert body["components"]["views"]["main"] == "ConexionTIAView"
    # Loaders: URL absoluta al .js que el Agente A crea.
    assert "loaders" in body
    assert "ConexionTIAView" in body["loaders"]
    assert body["loaders"]["ConexionTIAView"] == (
        "/areas/tia_conexion/frontend/components/ConexionTIAView.js"
    )


@pytest.mark.area_smoke
def test_get_manifest_unknown_area_returns_404() -> None:
    """``GET /api/v1/areas/no_existe/manifest`` responde 404."""
    with TestClient(app) as client:
        response = client.get("/api/v1/areas/no_existe/manifest")

    assert response.status_code == 404
    # El detail es informativo para el operario / la SPA.
    body = response.json()
    assert "no_existe" in body.get("detail", "")
