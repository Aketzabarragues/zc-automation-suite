"""Tests del router ``/api/v1/tia/connection``, ``/tia/connect`` y ``/tia/disconnect``.

Patrón TestClient + ``MagicMock(spec=TIAProcessGateway)`` (mismo que
``tests/test_project_info_endpoint.py``). Los 3 endpoints exponen
el estado del worker OT persistente del design doc
``_plan/12_worker_persistent_design.md`` §4.1 + ext. sept-2026 (state
machine refactor):

  - GET  /api/v1/tia/connection  -> estado actual (incluye ``pid`` si connected).
  - POST /api/v1/tia/connect     -> ``gateway.connect()`` (attach al portal).
  - POST /api/v1/tia/disconnect  -> ``gateway.disconnect()`` (detach, NO kill).

Shape del GET (contrato con la SPA)::

    {
      "state": "idle" | "connecting" | "connected" | "disconnected" | "error",
      "project": {"name", "path", "version"} | None,
      "plcs": [str, ...],
      "last_ping_ok_unix": float | None,
      "last_error": str | None,
      "project_changed": bool,
      "worker_alive": bool,
      "pid": int | None   # solo presente cuando state == "connected"
    }

Notas:
  * ``gateway.connect`` y ``gateway.disconnect`` SI existen en la clase
    (definidos en el state machine refactor de sept-2026). Los tests los
    monkey-patchean como ``AsyncMock`` para validar la llamada del router.
  * ``getattr(gateway, "_connection_state", "disconnected")`` en el
    router es defensivo: los atributos de estado del worker
    persistente solo se inicializan si el gateway se construyo con
    ``persistent=True`` (ver ``core/infrastructure/gateway.py``).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from core.application.progress_buffer import ProgressTracker
from core.infrastructure.gateway import TIAConnectionError, TIAProcessGateway
from interfaces.web_server.app import create_app


# Las fixtures ``mock_gateway`` y ``client`` viven en
# ``tests/conftest.py`` (compartidas con ``test_worker_status.py``).


# ── Test 1: GET /connection con state=connected → shape completo ────


def test_get_connection_connected_devuelve_shape_completo(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """GET /connection con state=connected expone todos los campos incluido ``pid``.

    El router enriquece con ``get_project_info`` y ``get_plcs`` solo
    si el state es ``"connected"``. Verifica el shape exacto del
    design doc §4.1 + ext. sept-2026 (``pid`` del portal TIA).
    """
    mock_gateway._connection_state = "connected"
    mock_gateway._project_path = r"C:\ws\proj\proj.ap17"
    mock_gateway._last_ping_ok = 1234.5
    mock_gateway._last_error = None
    mock_gateway._last_portal_pid = 4242
    mock_gateway.is_worker_alive = MagicMock(return_value=True)
    mock_gateway.get_project_info = AsyncMock(
        return_value={
            "name": "MiProyecto",
            "path": r"C:\ws\proj\proj.ap17",
            "version": "18.0",
        }
    )
    mock_gateway.get_plcs = AsyncMock(return_value=["PLC1", "PLC2"])

    resp = client.get("/api/v1/tia/connection")
    assert resp.status_code == 200
    body = resp.json()

    # Shape exacto (sin campos extra). ``pid`` ahora forma parte del
    # contrato (sept-2026 state machine refactor).
    assert set(body.keys()) == {
        "state",
        "project",
        "plcs",
        "last_ping_ok_unix",
        "last_error",
        "project_changed",
        "worker_alive",
        "pid",
    }
    assert body["state"] == "connected"
    assert body["project"] == {
        "name": "MiProyecto",
        "path": r"C:\ws\proj\proj.ap17",
        "version": "18.0",
    }
    assert body["plcs"] == ["PLC1", "PLC2"]
    assert body["last_ping_ok_unix"] == 1234.5
    assert body["last_error"] is None
    assert body["worker_alive"] is True
    # PID del portal TIA Portal al que estamos attached. Lo cacheo
    # ``connect()`` tras el ``attach_portal`` exitoso.
    assert body["pid"] == 4242

    # El router consulta project_info y plcs porque el state es "connected"
    mock_gateway.get_project_info.assert_awaited_once()
    mock_gateway.get_plcs.assert_awaited_once()


# ── Test 2: GET /connection con state=idle → shape completo, pid=null ──


def test_state_idle_is_valid_in_get_connection(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """GET /connection con state=idle es valido y expone ``pid: null``.

    Estado inicial del worker tras el refactor de sept-2026: el
    worker arranca en ``"idle"`` (subproceso vivo pero sin attach
    a TIA). El router debe aceptarlo sin errores y devolver
    ``pid: null`` (no hay portal attached, el PID no significa nada).
    Verifica tambien que NO se consulta ``get_project_info`` ni
    ``get_plcs`` (latencia innecesaria; la cache puede estar stale).
    """
    mock_gateway._connection_state = "idle"
    mock_gateway._project_path = None
    mock_gateway._last_ping_ok = None
    mock_gateway._last_error = None
    mock_gateway._last_portal_pid = None
    mock_gateway.is_worker_alive = MagicMock(return_value=True)
    mock_gateway.get_project_info = AsyncMock()
    mock_gateway.get_plcs = AsyncMock()

    resp = client.get("/api/v1/tia/connection")
    assert resp.status_code == 200
    body = resp.json()

    assert body["state"] == "idle"
    assert body["project"] is None
    assert body["plcs"] == []
    assert body["last_ping_ok_unix"] is None
    assert body["last_error"] is None
    assert body["worker_alive"] is True
    # Sin attach, no hay PID del portal: ``null``.
    assert body["pid"] is None

    # Red de seguridad: en estado idle el router NO debe enriquecer
    # (no hay attach, las lecturas fallarian con COMException).
    mock_gateway.get_project_info.assert_not_called()
    mock_gateway.get_plcs.assert_not_called()


# ── Test 3: GET /connection expone ``pid`` cuando state=connected ─────


def test_get_connection_includes_pid_when_connected(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """GET /connection expone el PID del portal TIA cuando state=connected.

    Sept-2026: ``connect()`` cachea el PID que devuelve el worker
    OT tras un ``attach_portal`` exitoso en ``gateway._last_portal_pid``.
    El router lo expone al frontend para que el operario pueda
    identificar el proceso TIA Portal en Task Manager (util cuando
    hay zombies tras reconexiones fallidas).
    """
    mock_gateway._connection_state = "connected"
    mock_gateway._project_path = r"C:\ws\proj\proj.ap17"
    mock_gateway._last_portal_pid = 9999
    mock_gateway.is_worker_alive = MagicMock(return_value=True)
    mock_gateway.get_project_info = AsyncMock(
        return_value={
            "name": "P",
            "path": r"C:\ws\proj\proj.ap17",
            "version": "18.0",
        }
    )
    mock_gateway.get_plcs = AsyncMock(return_value=["PLC1"])

    resp = client.get("/api/v1/tia/connection")
    assert resp.status_code == 200
    body = resp.json()

    assert body["state"] == "connected"
    # El campo ``pid`` esta presente y refleja lo que cacheo ``connect()``.
    assert "pid" in body
    assert body["pid"] == 9999


# ── Test 4: GET /connection con state=connecting → pid=null ───────────


def test_get_connection_pid_is_null_when_not_connected(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """GET /connection expone ``pid: null`` en estados sin attach.

    El PID solo tiene sentido cuando estamos attached a TIA Portal.
    En ``"idle"`` (sin attach), ``"connecting"`` (attach en curso),
    ``"disconnected"`` (portal liberado) o ``"error"`` (attach
    fallo), el router expone ``pid: null`` (no se cacheo, o se
    limpio en disconnect). Asi la SPA no muestra un PID obsoleto
    que confunda al operario.
    """
    # Caso: ``connecting`` con un PID cacheado "fantasma" (que en la
    # realidad ``connect()`` solo setea tras la transicion). El
    # router debe ignorarlo porque state != "connected".
    mock_gateway._connection_state = "connecting"
    mock_gateway._last_portal_pid = 12345  # no deberia aparecer
    mock_gateway.is_worker_alive = MagicMock(return_value=True)

    resp = client.get("/api/v1/tia/connection")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "connecting"
    # Sin attach confirmado, PID es ``null`` aunque el atributo
    # tenga un valor stale.
    assert body["pid"] is None


# ── Test 5: POST /connect llama a gateway.connect() ─────────────────


def test_post_connect_calls_gateway_connect(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """POST /connect llama a ``gateway.connect()`` (NO ``reconnect()``).

    Sept-2026 (state machine refactor): el worker arranca en
    ``"idle"`` y el operario decide cuando attach via este endpoint.
    Se delega en ``gateway.connect()``, no en ``reconnect()`` (esa
    API queda para back-compat externa, pero el router no la usa:
    matar+relanzar el subproceso seria overkill y pagariamos ~200 MB
    de overhead cada vez).
    """
    mock_gateway._connection_state = "connected"
    mock_gateway._last_portal_pid = 7777
    mock_gateway.connect = AsyncMock()

    resp = client.post("/api/v1/tia/connect")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["state"] == "connected"
    # El router expone el PID cacheado por ``connect()``.
    assert body["pid"] == 7777
    # Y llamo a ``connect()``, NO a ``reconnect()``.
    mock_gateway.connect.assert_awaited_once()
    # ``reconnect()`` NO debe invocarse desde el router; si alguien
    # lo aniade por error, este assert lo cazaria.
    assert not hasattr(mock_gateway, "reconnect") or not getattr(
        mock_gateway.reconnect, "await_count", 0
    ), "router no debe llamar a gateway.reconnect()"


# ── Test 6: POST /connect sin PID cacheado → pid=null en response ─


def test_post_connect_returns_null_pid_if_not_cached(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """POST /connect devuelve ``pid: null`` si el gateway no cacheo el PID.

    Caso real: el worker puede devolver ``{"pid": ...}`` solo en
    builds que soporten esa clave; builds anteriores no lo hacen y
    ``connect()`` deja ``_last_portal_pid = None``. El router
    expone ``pid: null`` para que la SPA no rompa al desestructurar.
    """
    mock_gateway._connection_state = "connected"
    mock_gateway._last_portal_pid = None  # build sin soporte de pid
    mock_gateway.connect = AsyncMock()

    resp = client.post("/api/v1/tia/connect")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["state"] == "connected"
    assert body["pid"] is None


# ── Test 7: POST /connect que falla → error legible ─────────────────


def test_post_connect_failure_devuelve_error_legible(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """POST /connect con ``connect()`` que lanza → 200 con ok=False, state=error.

    El router NO propaga la excepcion (eso daria 500 inutil al
    frontend). Devuelve un error legible con el tipo y el mensaje
    para que el operario sepa que ha pasado (TIA cerrado, ya
    conectado, gateway no persistente, etc.).
    """
    mock_gateway._connection_state = "error"
    mock_gateway.connect = AsyncMock(
        side_effect=RuntimeError("TIA Portal no responde")
    )

    resp = client.post("/api/v1/tia/connect")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["state"] == "error"
    assert "RuntimeError" in body["error"]
    assert "TIA Portal no responde" in body["error"]
    mock_gateway.connect.assert_awaited_once()


# ── Test 8: POST /disconnect llama a gateway.disconnect() ───────────


def test_post_disconnect_calls_gateway_disconnect(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """POST /disconnect llama a ``gateway.disconnect()`` y devuelve state=idle.

    Sept-2026: ``disconnect()`` solo hace ``detach_portal`` (no
    mata el subproceso). El worker sigue vivo en estado ``"idle"``
    listo para un futuro ``connect()`` sin pagar el coste de un
    nuevo subproceso.
    """
    mock_gateway._connection_state = "idle"
    mock_gateway.disconnect = AsyncMock()

    resp = client.post("/api/v1/tia/disconnect")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["state"] == "idle"
    mock_gateway.disconnect.assert_awaited_once()


# ── Test 9: POST /disconnect que falla → error legible ─────────────


def test_post_disconnect_failure_devuelve_error_legible(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """POST /disconnect con ``disconnect()`` que lanza → 200 con ok=False, state=error.

    Caso real: ``disconnect()`` solo aplica a gateway.persistent=True.
    En modo 1-shot (MCP) lanza ``TIAConnectionError``; el frontend
    lo recibe como error legible en vez de un 500. Tambien cubre
    fallos del worker (subproceso ya muerto, detach_portal falla).
    """
    mock_gateway._connection_state = "error"
    mock_gateway.disconnect = AsyncMock(
        side_effect=TIAConnectionError(
            "disconnect() solo aplica a gateway.persistent=True"
        )
    )

    resp = client.post("/api/v1/tia/disconnect")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["state"] == "error"
    assert "persistent" in body["error"]
    mock_gateway.disconnect.assert_awaited_once()


# ── Test 10: GET /connection con state=disconnected → project=null ─


def test_get_connection_disconnected_no_consulta_gateway(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """GET /connection con state=disconnected NO llama a ``get_project_info`` ni ``get_plcs``.

    En estado no-conectado la cache del gateway puede estar stale
    (TIA cerrado, proyecto distinto) y forzar la lectura empeoraria
    la experiencia. El router devuelve ``project=None`` y ``plcs=[]``
    sin tocar el OT. El ``pid`` tambien es ``null`` (no hay attach).
    """
    mock_gateway._connection_state = "disconnected"
    mock_gateway._project_path = None
    mock_gateway._last_ping_ok = None
    mock_gateway._last_portal_pid = None
    mock_gateway._last_error = "Last ping failed: TIA cerrado"
    # Anadimos los AsyncMock para poder verificar que NO se llaman
    mock_gateway.get_project_info = AsyncMock()
    mock_gateway.get_plcs = AsyncMock()

    resp = client.get("/api/v1/tia/connection")
    assert resp.status_code == 200
    body = resp.json()

    assert body["state"] == "disconnected"
    assert body["project"] is None
    assert body["plcs"] == []
    assert body["last_ping_ok_unix"] is None
    assert body["last_error"] == "Last ping failed: TIA cerrado"
    # Sin attach, ``pid`` es ``null``.
    assert body["pid"] is None

    # Red de seguridad: si el router llamara a estos metodos en estado
    # disconnected, el frontend sufriria latencia innecesaria y posibles
    # excepciones COM/RPC.
    mock_gateway.get_project_info.assert_not_called()
    mock_gateway.get_plcs.assert_not_called()


# ── Test 11: GET /connection con get_project_info que lanza → degrada ──


def test_get_connection_get_project_info_falla_degrada_a_vacio(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """GET /connection con ``get_project_info`` que lanza excepcion → state preservado, project=null, plcs=[].

    El estado de conexion (``state``) es la verdad: si el router
    enriquece y falla, NO debe tumbar la respuesta. El frontend ve
    el state real y campos vacios hasta el siguiente polling.
    """
    mock_gateway._connection_state = "connected"
    mock_gateway._project_path = r"C:\ws\proj\proj.ap17"
    mock_gateway._last_ping_ok = 1234.5
    mock_gateway._last_error = None
    mock_gateway._last_portal_pid = 5555
    mock_gateway.get_project_info = AsyncMock(
        side_effect=RuntimeError("attach perdido durante la lectura")
    )
    mock_gateway.get_plcs = AsyncMock(
        side_effect=RuntimeError("attach perdido durante la lectura")
    )

    resp = client.get("/api/v1/tia/connection")
    # Estado 200: el router degrada en vez de explotar.
    assert resp.status_code == 200
    body = resp.json()
    # El state se preserva: NO bajamos a "disconnected" porque
    # ``get_project_info`` fallara — el state es la verdad y los
    # siguientes pings lo actualizaran si aplica.
    assert body["state"] == "connected"
    assert body["project"] is None
    assert body["plcs"] == []
    assert body["last_ping_ok_unix"] == 1234.5
    assert body["last_error"] is None
    # El router intento enriquecer y la excepcion se absorbio.
    # El ``pid`` se mantiene (es ortogonal a ``get_project_info``):
    # el portal attached responde, lo que falla es el enriquecimiento.
    assert body["pid"] == 5555
    mock_gateway.get_project_info.assert_awaited_once()
    mock_gateway.get_plcs.assert_awaited_once()


# ── Test 12 (regresion PR 7): GET /connection expone ``project_changed`` ─


def test_get_connection_expone_project_changed_consumiendo_flag(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """GET /connection expone ``project_changed`` y consume el flag (one-shot).

    PR 7 anade el flag ``_project_changed`` al gateway: ``True`` tras
    detectar un cambio de proyecto en TIA, ``False`` despues de un
    ``consume_project_changed()``. El router lo lee y lo expone en la
    respuesta para que la SPA notifique al operario UNA SOLA VEZ por
    cambio real.

    Verificamos:
      - La respuesta incluye el campo ``project_changed``.
      - Cuando el flag esta a ``True`` en el gateway, la respuesta
        lo refleja (``True``) y el flag se resetea (``False``) tras
        el read (semantica one-shot).
      - El siguiente GET devuelve ``project_changed=False`` (el
        cambio ya fue notificado).
    """
    # El gateway expone un flag ``project_changed`` que el operario
    # acaba de cambiar en TIA. ``consume_project_changed`` lo lee
    # y resetea (mockspec=False para que ``getattr`` no se queje).
    mock_gateway.consume_project_changed = MagicMock(
        side_effect=[True, False]
    )
    mock_gateway._connection_state = "disconnected"  # no enriquecer

    resp1 = client.get("/api/v1/tia/connection")
    assert resp1.status_code == 200
    body1 = resp1.json()
    assert body1["project_changed"] is True
    # ``consume_project_changed`` se llamo (read-and-reset).
    assert mock_gateway.consume_project_changed.call_count == 1

    # Segundo GET: el flag ya esta consumido, debe ser ``False``.
    resp2 = client.get("/api/v1/tia/connection")
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body2["project_changed"] is False
    assert mock_gateway.consume_project_changed.call_count == 2


# ── Sept-2026: POST /connect y /disconnect exponen worker_alive ─────
#
# Antes (pre-sept-2026): las respuestas POST de connect y
# disconnect NO incluían ``worker_alive``. El frontend recibía
# ``undefined`` y ``_applyTiaSnapshot`` lo grababa como
# ``false``, haciendo que el círculo del worker parpadease
# "muerto" (gris) durante ~1s tras cada click hasta el
# siguiente poll del GET.
#
# Tras el fix: las respuestas POST incluyen ``worker_alive``
# (leído del gateway con ``is_worker_alive()``), y el frontend
# hace un merge defensivo (store.js) para preservar el valor
# anterior si el campo falta. Cero parpadeo.


def test_post_connect_includes_worker_alive(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """POST /connect expone ``worker_alive`` en la respuesta.

    Sept-2026 (fix parpadeo "muerto"): el backend incluye
    ``worker_alive`` (chequeo barato de ``is_worker_alive()``)
    para que la SPA actualice el ``WorkerStatusIndicator``
    inmediatamente, sin esperar al próximo poll del GET.
    """
    mock_gateway._connection_state = "connected"
    mock_gateway._last_portal_pid = 4242
    mock_gateway.connect = AsyncMock()
    mock_gateway.is_worker_alive = MagicMock(return_value=True)

    resp = client.post("/api/v1/tia/connect")
    assert resp.status_code == 200
    body = resp.json()

    assert body["ok"] is True
    assert "worker_alive" in body, (
        "POST /connect debe incluir ``worker_alive`` en la "
        "respuesta (sept-2026, fix parpadeo 'muerto' al click)."
    )
    assert body["worker_alive"] is True
    mock_gateway.is_worker_alive.assert_called()


def test_post_disconnect_includes_worker_alive(
    client: TestClient, mock_gateway: MagicMock
) -> None:
    """POST /disconnect expone ``worker_alive`` en la respuesta.

    Mismo motivo que el test de connect: tras el detach el
    worker sigue vivo (estado ``"idle"``), y la SPA necesita
    ver el indicador verde inmediatamente, no 1s después.
    """
    mock_gateway._connection_state = "idle"
    mock_gateway.disconnect = AsyncMock()
    mock_gateway.is_worker_alive = MagicMock(return_value=True)

    resp = client.post("/api/v1/tia/disconnect")
    assert resp.status_code == 200
    body = resp.json()

    assert body["ok"] is True
    assert "worker_alive" in body, (
        "POST /disconnect debe incluir ``worker_alive`` en la "
        "respuesta (sept-2026, fix parpadeo 'muerto' al click)."
    )
    assert body["worker_alive"] is True
    mock_gateway.is_worker_alive.assert_called()
