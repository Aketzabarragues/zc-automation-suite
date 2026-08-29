"""Tests del router ``/api/v1/plcs/<plc>/blocks`` y ``/refresh``.

Cubre:
  1. ``GET`` devuelve el snapshot cacheado con ``from_cache`` correcto.
  2. ``GET`` con ``plc_name`` vacío → ``400``.
  3. ``POST /refresh`` ignora caché (``force_refresh=True``).
  4. El router está montado vía ``AreaRegistry`` (no por import directo
     en ``app.py``).
  5. El shell ``app.py`` NO importa el router de bloques directamente.

Mockeamos el use case (``_build_use_case``) porque el módulo
``areas.alimentacion.application.use_cases.scan_plc_blocks`` pertenece
a la pista ``tia-ot-worker`` y puede no existir en ramas aisladas
(ver router: el import del use case es perezoso). El gateway que se
inyecta en la app también va mockeado (``MagicMock(spec=TIAProcessGateway)``)
para mantener la coherencia con el resto de tests del repo.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from areas.alimentacion import AREA_SPEC
from areas.alimentacion.interfaces.web import register_routers
from core.infrastructure.gateway import TIAProcessGateway
from interfaces.web_server.app import create_app


# ── Fixtures ──────────────────────────────────────────────────────────


def _make_fake_cache(
    plc_name: str = "PLC_X",
    scanned_at: datetime | None = None,
) -> SimpleNamespace:
    """Construye un fake ``BloqueCache`` con ``to_dict()``."""
    when = scanned_at or datetime.now(timezone.utc)
    blocks = {
        "db1": {"name": "DB1", "type": "DB", "number": 1},
        "fb1": {"name": "FB1", "type": "FB", "number": 2},
    }
    tag_tables = {
        "tt1": {"name": "2000_Disp_ED", "kind": "plc_tag_table"},
    }

    def _to_dict() -> dict:
        return {
            "plc_name": plc_name,
            "blocks": list(blocks.values()),
            "tag_tables": list(tag_tables.values()),
            "scanned_at": when.isoformat(),
        }

    return SimpleNamespace(
        plc_name=plc_name,
        blocks=blocks,
        tag_tables=tag_tables,
        scanned_at=when,
        to_dict=_to_dict,
    )


def _make_fake_use_case(cache: SimpleNamespace) -> MagicMock:
    """Construye un fake ``ScanPlcBlocksUseCase`` con ``ensure_cache`` AsyncMock."""
    uc = MagicMock(name="FakeScanPlcBlocksUseCase")
    uc.ensure_cache = AsyncMock(return_value=cache)
    return uc


@pytest.fixture
def make_client():
    """Factoría de ``TestClient`` con gateway mockeado y un fake use case.

    La fixture monta el ``_build_use_case`` del router con uno que
    devuelve el use case fake provisto. Esto evita depender de que
    ``scan_plc_blocks.py`` exista (pertenece a ``tia-ot-worker``).
    """

    def _factory(
        fake_cache: SimpleNamespace,
    ) -> TestClient:
        gw = MagicMock(spec=TIAProcessGateway)
        app = create_app(gateway=gw)

        # Monkey-patch del constructor del use case en el módulo del
        # router. Usamos ``setattr`` sobre el módulo importado para
        # que el handler ``get_plc_blocks`` vea el fake.
        from areas.alimentacion.interfaces.web import plc_blocks as rb

        fake_uc = _make_fake_use_case(fake_cache)
        rb._build_use_case = lambda g: fake_uc  # noqa: ARG005

        return TestClient(app)

    return _factory


# ── Tests del endpoint ────────────────────────────────────────────────


def test_get_plc_blocks_returns_cache_snapshot(make_client) -> None:
    """GET /blocks devuelve el snapshot con ``ok=True`` y ``from_cache``."""
    recent = datetime.now(timezone.utc) - timedelta(seconds=10)
    fake_cache = _make_fake_cache("PLC_X", scanned_at=recent)
    client = make_client(fake_cache)

    response = client.get("/api/v1/plcs/PLC_X/blocks")

    assert response.status_code == 200
    body = response.json()

    # Shape exacto esperado por la SPA.
    assert body["ok"] is True
    assert body["plc_name"] == "PLC_X"
    assert isinstance(body["blocks"], list)
    assert {b["name"] for b in body["blocks"]} == {"DB1", "FB1"}
    assert isinstance(body["tag_tables"], list)
    assert body["tag_tables"][0]["name"] == "2000_Disp_ED"
    assert "scanned_at" in body
    assert isinstance(body["from_cache"], bool)
    # El cache tiene 10 s (< 5 min) → from_cache=True.
    assert body["from_cache"] is True


def test_get_plc_blocks_with_stale_cache_reports_from_cache_false(
    make_client,
) -> None:
    """GET /blocks con cache > 5 min → ``from_cache=False`` (no re-escanea aquí;
    el use case decide si re-escanear, el router solo reporta)."""
    stale = datetime.now(timezone.utc) - timedelta(minutes=10)
    fake_cache = _make_fake_cache("PLC_X", scanned_at=stale)
    client = make_client(fake_cache)

    response = client.get("/api/v1/plcs/PLC_X/blocks")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    # scanned_at viejo (10 min) → fuera de la ventana de 5 min.
    assert body["from_cache"] is False


def test_get_plc_blocks_with_empty_plc_name_returns_400(make_client) -> None:
    """``plc_name`` vacío (whitespace) → ``HTTP 400`` sin tocar el use case."""
    fake_cache = _make_fake_cache("PLC_X")
    client = make_client(fake_cache)

    # ``%20`` se decodifica como espacio; el validador lo rechaza.
    response = client.get("/api/v1/plcs/%20%20/blocks")

    assert response.status_code == 400
    body = response.json()
    # FastAPI envuelve el detail en ``{"detail": ...}`` por defecto.
    assert "detail" in body
    assert "plc_name" in body["detail"].lower()


def test_post_refresh_bypasses_cache(make_client) -> None:
    """``POST /refresh`` invoca ``ensure_cache(force_refresh=True)``."""
    fake_cache = _make_fake_cache("PLC_X")
    client = make_client(fake_cache)

    response = client.post("/api/v1/plcs/PLC_X/blocks/refresh")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    # POST /refresh SIEMPRE reporta from_cache=False.
    assert body["from_cache"] is False

    # El use case se invocó exactamente una vez con force_refresh=True.
    from areas.alimentacion.interfaces.web import plc_blocks as rb
    fake_uc = rb._build_use_case(None)  # el fake que metimos en make_client
    fake_uc.ensure_cache.assert_awaited_once_with("PLC_X", force_refresh=True)


def test_router_mounted_via_area_registry() -> None:
    """El router está cableado al ``contributes_routers`` del AreaSpec."""
    # 1) El AreaSpec del área apunta a su ``register_routers``.
    assert AREA_SPEC.contributes_routers is register_routers

    # 2) El router nuevo es importable desde el paquete del área.
    from areas.alimentacion.interfaces.web import plc_blocks as rb

    assert rb.router is not None
    # Las dos rutas del router están registradas (path completo,
    # incluyendo el ``prefix`` del APIRouter).
    paths = {r.path for r in rb.router.routes}
    assert "/api/v1/plcs/{plc_name}/blocks" in paths
    assert "/api/v1/plcs/{plc_name}/blocks/refresh" in paths

    # 3) El endpoint es alcanzable a través de ``create_app`` (el shell
    #    descubre el router vía ``AreaRegistry.for_each``).
    from areas.alimentacion.interfaces.web import plc_blocks as rb2

    recent = datetime.now(timezone.utc)
    fake_cache = _make_fake_cache("PLC_Y", scanned_at=recent)
    fake_uc = _make_fake_use_case(fake_cache)
    original_builder = rb2._build_use_case
    rb2._build_use_case = lambda g: fake_uc  # noqa: ARG005
    try:
        gw = MagicMock(spec=TIAProcessGateway)
        app = create_app(gateway=gw)
        client = TestClient(app)
        resp = client.get("/api/v1/plcs/PLC_Y/blocks")
        assert resp.status_code == 200
        assert resp.json()["plc_name"] == "PLC_Y"
    finally:
        rb2._build_use_case = original_builder


def test_shell_does_not_import_plc_blocks_router_directly() -> None:
    """``app.py`` NO debe importar el router nuevo directamente.

    El shell descubre los routers del área vía
    ``AreaRegistry.for_each("contributes_routers", app=app)``; cualquier
    import directo desde el shell rompería el contrato.
    """
    shell_path = (
        Path(__file__).resolve().parents[1]
        / "interfaces"
        / "web_server"
        / "app.py"
    )
    src = shell_path.read_text(encoding="utf-8")

    forbidden_literals = [
        "plc_blocks",
        "from areas.alimentacion.interfaces.web.plc_blocks",
    ]
    for literal in forbidden_literals:
        assert literal not in src, (
            f"El shell web importa '{literal}' directamente. Debe "
            "descubrir el router vía AreaRegistry, no por import."
        )
