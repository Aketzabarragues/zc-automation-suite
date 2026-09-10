"""Tests del wiring de la app (DA-005.5).

Cubre el cableado que activa el ``Engine`` + 7 FBs + ``plc_router``
en el ``lifespan`` del Composition Root:

  1. Tras el ``lifespan``, ``app.state.engine`` tiene exactamente 7
     FBs registrados (uno por use case del área de alimentación).
  2. Cada FB es instancia de ``FunctionBase`` y su nombre en el
     engine es el canónico (sin prefijo ``Function``).
  3. ``GET /api/v1/plc/fb/SubirExcel/status`` responde con
     ``nStep=0`` (idle) — el FB existe, no se ha arrancado.
  4. ``POST /api/v1/plc/fb/SubirExcel/start`` arranca el FB y la
     respuesta refleja ``started=True`` y ``nStep=10``.
  5. Tras el ``lifespan``, el OB1 (``engine._task``) está vivo
     (no terminado). Si ``start_loop()`` falla, este test falla.
  6. Smoke de regresión: la suite completa sigue verde. Se
     valida con ``pytest tests/ -q`` (reporte del commit, no
     de este archivo, para no duplicar el conteo).

Notas operativas:
  * El gateway se mockea con ``persistent=False`` para que el
    ``lifespan`` NO intente arrancar un worker OT real (el
    mock no es un subproceso válido).
  * Los 7 FBs se crean en el ``lifespan`` (startup del TestClient).
    Mientras dura el ``with TestClient(app)``, ``app.state.engine``
    está vivo y el OB1 tickea cada 100 ms; los FBs en ``n_idle``
    no se tickean (``is_terminal()`` incluye idle).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from core.infrastructure.gateway import TIAProcessGateway
from core.plc.function_base import FunctionBase
from interfaces.web_server.app import create_app


# ── Constantes del contrato ─────────────────────────────────────────
# Mantener sincronizadas con ``areas/alimentacion/__init__.py::register``.
EXPECTED_FB_NAMES: tuple[str, ...] = (
    "SubirExcel",
    "ScanPlcBlocks",
    "GenerarPreview",
    "SincronizarDispositivos",
    "SincronizarDispComentarios",
    "SincronizarProcesosComentarios",
    "DiffConstants",
)


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_gateway_non_persistent() -> MagicMock:
    """Gateway ``MagicMock(spec=TIAProcessGateway)`` con
    ``persistent=False``.

    Razón: el ``lifespan`` solo llama ``gateway.start()`` /
    ``gateway.disconnect()`` si ``gateway.persistent is True`` (modo
    web). En tests, un MagicMock no es un subproceso OT válido;
    desactivar el flag evita que el lifespan intente arrancarlo.
    """
    g = MagicMock(spec=TIAProcessGateway)
    g.persistent = False
    g._connection_state = "disconnected"
    return g


@pytest.fixture
def wired_app(mock_gateway_non_persistent: MagicMock):
    """App con el ``lifespan`` ya ejecutado.

    El ``with TestClient(app)`` ejecuta el startup (crea el engine,
    registra los 7 FBs, monta el plc_router, arranca el OB1) y deja
    la app lista. Al salir del ``with``, ejecuta el shutdown (para
    el OB1, desconecta el gateway).
    """
    app = create_app(gateway=mock_gateway_non_persistent)
    with TestClient(app):
        yield app


@pytest.fixture
def wired_client(mock_gateway_non_persistent: MagicMock):
    """TestClient con la app + lifespan arrancado, listo para HTTP."""
    app = create_app(gateway=mock_gateway_non_persistent)
    with TestClient(app) as client:
        yield client


# ── Tests ────────────────────────────────────────────────────────────


def test_wiring_engine_has_exactly_7_fbs_registered(wired_app) -> None:
    """Test 1: tras el lifespan, el engine tiene exactamente 7 FBs."""
    engine = wired_app.state.engine
    assert engine is not None, "app.state.engine no se creo en el lifespan"
    names = engine.registered_fb_names()
    assert len(names) == 7, (
        f"Se esperaban 7 FBs registrados, hay {len(names)}: {names}"
    )
    # El orden de registro está fijado en ``register()`` (estable).
    assert tuple(names) == EXPECTED_FB_NAMES, (
        f"Nombres/orden inesperado. Esperado {EXPECTED_FB_NAMES}, "
        f"obtenido {tuple(names)}"
    )


def test_wiring_each_fb_is_functionbase_with_canonical_name(wired_app) -> None:
    """Test 2: cada FB es ``FunctionBase`` y su nombre canónico
    coincide con la clave de registro (sin prefijo ``Function``)."""
    engine = wired_app.state.engine
    for name in EXPECTED_FB_NAMES:
        fb = engine.get_fb(name)
        assert fb is not None, f"FB '{name}' no registrado en el engine"
        assert isinstance(fb, FunctionBase), (
            f"FB '{name}' no es instancia de FunctionBase: "
            f"{type(fb).__name__}"
        )
        # El nombre de la clase debe empezar por 'Function' (contrato
        # del área) y la clave del engine NO (es el nombre canónico
        # que la SPA y el router usan en la URL).
        assert type(fb).__name__.startswith("Function"), (
            f"Clase del FB '{name}' no sigue la convencion Function*: "
            f"{type(fb).__name__}"
        )
        assert not name.startswith("Function"), (
            f"Nombre en el engine no debe llevar prefijo 'Function': "
            f"'{name}'"
        )


def test_wiring_status_endpoint_returns_idle(wired_client: TestClient) -> None:
    """Test 3: ``GET /status`` de un FB sin arrancar responde
    ``nStep=0`` (n_idle) y ``is_terminal=True``."""
    resp = wired_client.get("/api/v1/plc/fb/SubirExcel/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "SubirExcel"
    assert body["nStep"] == 0, f"Esperado nStep=0 (idle), obtenido {body['nStep']}"
    assert body["is_terminal"] is True
    assert body["error_msg"] is None
    assert body["result"] is None


def test_wiring_post_start_arranca_el_fb(wired_client: TestClient) -> None:
    """Test 4: ``POST /start`` arranca el FB. La respuesta del
    endpoint (capturada inmediatamente tras ``start()``) refleja
    ``started=True`` y ``nStep=10``.

    El engine tickea cada 100 ms; entre el POST y la lectura
    inmediata de la respuesta NO hay ticks porque el handler
    devuelve la lectura de ``fb.nStep`` sincronizada tras
    ``await fb.start()``. Por tanto, la respuesta es estable
    en ``nStep=10`` independientemente del periodo del OB1.
    """
    resp = wired_client.post(
        "/api/v1/plc/fb/SubirExcel/start",
        json={"params": {"xlsx_path": "/tmp/wiring-test.xlsx"}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"started": True, "nStep": 10}, (
        f"start() no devolvio (True, 10). Respuesta: {body}. "
        f"Si nStep!=10, el FB no se arranco correctamente."
    )

    # Verificacion adicional: el estado del FB ha cambiado.
    status = wired_client.get("/api/v1/plc/fb/SubirExcel/status")
    assert status.status_code == 200
    status_body = status.json()
    assert status_body["nStep"] != 0, (
        f"FB sigue en n_idle tras POST /start: {status_body}"
    )
    # nStep debe ser 10, 20, 30, 98 o 99 (todos los estados validos
    # de un FB arrancado). 10 = recien arrancado sin tick; 20/30 =
    # tick en marcha; 98 = error de validacion; 99 = done.
    assert status_body["nStep"] in {10, 20, 30, 98, 99}, (
        f"nStep en estado inesperado tras start: {status_body['nStep']}"
    )


def test_wiring_engine_loop_is_running_after_lifespan(wired_app) -> None:
    """Test 5: tras el ``lifespan``, el OB1 está vivo (task asyncio
    corriendo, no terminado).

    Si el ``start_loop()`` falla o nunca se invoca, el FB nunca
    tickeará en producción. Esta verificación cierra el círculo
    de que el wiring no solo registra FBs sino que también arranca
    el loop que los tickea.

    El test 5 "no rompe la suite" se valida externamente con
    ``pytest tests/ -q`` (reporte del commit, no de este archivo).
    """
    engine = wired_app.state.engine
    assert engine is not None
    assert engine._task is not None, (
        "engine._task es None: start_loop() no se invoco o fallo"
    )
    assert not engine._task.done(), (
        "engine._task termino inesperadamente tras el lifespan. "
        "Revisa el log: el OB1 probablemente crasheo en su primer tick."
    )
