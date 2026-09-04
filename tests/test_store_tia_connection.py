"""Smoke tests del state ``tiaConnection`` y los helpers
``refreshTiaConnection`` / ``connectTia`` / ``disconnectTia``
del store frontend (PR 5b / §4.3 del design doc).

Sin infra JS (Jest/Vitest): se valida el contrato textual
sobre ``store.js`` y la presencia/forma de las funciones
exportadas. Los call-sites de los helpers (ShellTopbar, main.js)
se verifican con asserts textuales.

Aspectos cubiertos:
  1. ``store.tiaConnection`` existe con la shape esperada
     (``state``, ``project``, ``plcs``, ``last_ping_ok_unix``,
     ``last_error``) y el state inicial es ``"disconnected"``.
  2. ``refreshTiaConnection()`` existe, llama a
     ``apiFetchTiaConnection`` y actualiza ``store.tiaConnection``
     desde la respuesta.
  3. ``connectTia()`` setea ``state="connecting"`` ANTES de
     llamar al endpoint (feedback visual inmediato) y maneja el
     caso de error.
  4. ``disconnectTia()`` existe y llama a ``apiDisconnectTia``.
  5. ``main.js`` arranca el polling cada 2s con
     ``setInterval`` y ``refreshTiaConnection``.
  6. ``ShellTopbar.js`` importa ``connectTia`` del store y
     monta ``<TiaConnectionIndicator>`` con handler ``@connect``.

Marcado con ``@pytest.mark.frontend_smoke`` para permitir
filtrado (``pytest -m frontend_smoke``).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
STORE_JS = REPO_ROOT / "interfaces" / "web_server" / "static" / "js" / "store.js"
API_JS = REPO_ROOT / "interfaces" / "web_server" / "static" / "js" / "api.js"
MAIN_JS = REPO_ROOT / "interfaces" / "web_server" / "static" / "js" / "main.js"
SHELL_TOPBAR_JS = (
    REPO_ROOT
    / "interfaces"
    / "web_server"
    / "static"
    / "js"
    / "components"
    / "ShellTopbar.js"
)


pytestmark = pytest.mark.frontend_smoke


def _read(path: Path) -> str:
    assert path.exists(), f"Missing required SPA file: {path}"
    return path.read_text(encoding="utf-8")


# ── store.js: shape del state tiaConnection ──────────────────────────


def test_store_has_tia_connection_slot() -> None:
    """``store.js`` declara el slot ``tiaConnection`` con la
    shape estable del design doc §4.1 / §4.3."""
    text = _read(STORE_JS)
    # El slot debe estar dentro del ``reactive({...})``. Buscamos
    # la declaración con sus 5 sub-campos en el orden aproximado.
    start = text.find("tiaConnection: {")
    assert start != -1, (
        "store.js debe declarar un slot ``tiaConnection`` dentro "
        "del reactive({...}). Sin él, el TiaConnectionIndicator no "
        "puede leer el estado del worker."
    )
    body = text[start:start + 600]
    for field in ("state:", "project:", "plcs:", "last_ping_ok_unix:", "last_error:"):
        assert field in body, (
            f"El slot tiaConnection debe incluir el campo {field!r}. "
            "Sin él, el TiaConnectionIndicator no puede pintar el "
            "tooltip con info del proyecto."
        )


def test_store_tia_connection_initial_state_is_disconnected() -> None:
    """El estado inicial de ``tiaConnection.state`` debe ser
    ``"disconnected"`` (mismo valor que la respuesta por defecto
    del endpoint ``GET /api/v1/tia/connection``)."""
    text = _read(STORE_JS)
    start = text.find("tiaConnection: {")
    assert start != -1
    body = text[start:start + 200]
    assert 'state: "disconnected"' in body, (
        "tiaConnection.state debe inicializarse a 'disconnected' "
        "(mismo valor que devuelve el backend antes del primer "
        "attach del worker)."
    )


# ── store.js: helpers exportados ────────────────────────────────────


def test_store_exports_refresh_tia_connection() -> None:
    """``store.js`` exporta ``refreshTiaConnection()``."""
    text = _read(STORE_JS)
    assert "export async function refreshTiaConnection" in text, (
        "store.js debe exportar refreshTiaConnection() para que "
        "el polling de main.js pueda llamarlo."
    )


def test_store_exports_connect_tia() -> None:
    """``store.js`` exporta ``connectTia()``."""
    text = _read(STORE_JS)
    assert "export async function connectTia" in text, (
        "store.js debe exportar connectTia() para que el "
        "ShellTopbar (handler de @connect) pueda invocarlo."
    )


def test_store_exports_disconnect_tia() -> None:
    """``store.js`` exporta ``disconnectTia()``."""
    text = _read(STORE_JS)
    assert "export async function disconnectTia" in text, (
        "store.js debe exportar disconnectTia() para desconexiones "
        "explícitas (operación inversa a connectTia)."
    )


# ── store.js: comportamiento de los helpers ─────────────────────────


def test_refresh_tia_connection_calls_api_fetch_tia_connection() -> None:
    """``refreshTiaConnection()`` debe llamar a
    ``apiFetchTiaConnection()`` (vía import dinámico de api.js)."""
    text = _read(STORE_JS)
    start = text.find("export async function refreshTiaConnection")
    assert start != -1
    body = text[start:start + 1500]
    assert "apiFetchTiaConnection" in body, (
        "refreshTiaConnection debe llamar a apiFetchTiaConnection() "
        "para traer el snapshot del backend."
    )
    assert "Object.assign" in body, (
        "refreshTiaConnection debe usar Object.assign sobre "
        "store.tiaConnection (no reasignar la referencia completa, "
        "para preservar la reactividad de los campos anidados)."
    )


def test_refresh_tia_connection_logs_state_transitions() -> None:
    """``refreshTiaConnection()`` debe loguear las transiciones
    de estado en ``ConsolaLogs`` vía ``pushLog`` (PR 5b / §4.4
    del design doc: "[TIA] Conectado a ...", "[TIA]
    Desconectado ...", "[TIA] Error: ...")."""
    text = _read(STORE_JS)
    # El delegate real es la funcion helper ``_logTiaStateTransition``
    # que contiene los pushLog. Verificamos que el helper existe y
    # que es invocado desde refreshTiaConnection.
    assert "function _logTiaStateTransition" in text, (
        "store.js debe declarar un helper _logTiaStateTransition "
        "que contenga los pushLog (DRY entre refreshTiaConnection "
        "y connectTia)."
    )
    start = text.find("export async function refreshTiaConnection")
    assert start != -1
    # Cogemos un tramo generoso que cubra refreshTiaConnection +
    # _logTiaStateTransition (siguientes 4000 chars).
    body = text[start:start + 4000]
    assert "_logTiaStateTransition" in body, (
        "refreshTiaConnection debe invocar _logTiaStateTransition "
        "para loguear la transición."
    )
    # Y el helper debe tener pushLog con los 3 mensajes clave.
    assert "Conectado a" in text, (
        "store.js debe incluir el mensaje '[TIA] Conectado a ...' "
        "para la transición a 'connected'."
    )
    assert "Desconectado" in text, (
        "store.js debe incluir el mensaje '[TIA] Desconectado ...' "
        "para la transición a 'disconnected'."
    )
    assert "Error:" in text, (
        "store.js debe incluir el prefijo '[TIA] Error: ...' para "
        "la transición a 'error'."
    )
    # Y al menos 3 pushLog() en el archivo (uno por cada estado
    # transicionable: connected, disconnected, error).
    pushlog_count = text.count("pushLog(")
    assert pushlog_count >= 3, (
        f"store.js debe contener al menos 3 pushLog() en el helper "
        f"_logTiaStateTransition (uno por estado transicionable). "
        f"Encontrados: {pushlog_count}."
    )


def test_connect_tia_sets_connecting_state_before_api_call() -> None:
    """``connectTia()`` debe setear ``state='connecting'`` ANTES
    de llamar a ``apiConnectTia()`` para que el indicador se
    vuelva ámbar pulsante inmediatamente (feedback visual antes
    de que llegue la respuesta, que puede tardar 5-30s)."""
    text = _read(STORE_JS)
    start = text.find("export async function connectTia")
    assert start != -1
    body = text[start:start + 1500]
    # El set de ``state = "connecting"`` debe aparecer ANTES de
    # la llamada a ``apiConnectTia``.
    pos_state = body.find('state: "connecting"')
    pos_api = body.find("apiConnectTia()")
    assert pos_state != -1, (
        "connectTia debe setear state='connecting' antes de "
        "llamar al backend."
    )
    assert pos_api != -1, (
        "connectTia debe llamar a apiConnectTia() tras setear "
        "el estado intermedio."
    )
    assert pos_state < pos_api, (
        f"connectTia debe setear state='connecting' (pos {pos_state}) "
        f"ANTES de llamar a apiConnectTia() (pos {pos_api}). "
        "Si se hace al revés, el operario no ve feedback visual "
        "durante el cold-attach (5-30s)."
    )


def test_connect_tia_handles_error_response() -> None:
    """``connectTia()`` debe manejar respuestas no-OK poniendo
    ``state='error'`` y propagando el mensaje del backend."""
    text = _read(STORE_JS)
    start = text.find("export async function connectTia")
    assert start != -1
    body = text[start:start + 2000]
    assert "state: \"error\"" in body, (
        "connectTia debe poner state='error' si la respuesta del "
        "backend no es OK."
    )
    assert "last_error" in body, (
        "connectTia debe propagar el last_error del backend en el "
        "store para que el TiaConnectionIndicator lo muestre en el tooltip."
    )


# ── api.js: 3 endpoints nuevos ──────────────────────────────────────


def test_api_exports_tia_connection_functions() -> None:
    """``api.js`` expone las 3 funciones del PR 5a/b:
    ``apiFetchTiaConnection``, ``apiConnectTia``,
    ``apiDisconnectTia``."""
    text = _read(API_JS)
    for fn, endpoint in (
        ("apiFetchTiaConnection", "/api/v1/tia/connection"),
        ("apiConnectTia", "/api/v1/tia/connect"),
        ("apiDisconnectTia", "/api/v1/tia/disconnect"),
    ):
        assert f"export const {fn}" in text or f"export function {fn}" in text, (
            f"api.js debe exportar {fn}() (PR 5a/b)."
        )
        assert endpoint in text, (
            f"api.js debe apuntar a {endpoint} (la URL del backend)."
        )


# ── main.js: polling cada 2s ─────────────────────────────────────────


def test_main_js_has_tia_connection_polling_2s() -> None:
    """``main.js`` arranca un ``setInterval`` cada 2 segundos
    (2000 ms) que llama a ``refreshTiaConnection`` (o
    ``store.refreshTiaConnection``)."""
    text = _read(MAIN_JS)
    # El call real es ``store.refreshTiaConnection?.()`` (acceso
    # defensivo a un helper que puede ser undefined en tests).
    # Buscamos un setInterval dentro de un radio razonable (los
    # siguientes 1500 chars desde el comentario del PR 5b) que
    # mencione refreshTiaConnection y termine con 2000.
    import re
    # Estrategia: anclar cerca del comentario del PR 5b para
    # evitar matchear los otros 2 setInterval (logs 1s, progress 500ms).
    anchor = text.find("Polling del estado de conexi")
    if anchor == -1:
        # Fallback: aceptar el primer setInterval(... 2000 ...) del archivo.
        pattern = re.compile(
            r"setInterval\(\s*[\s\S]{0,200}refreshTiaConnection[\s\S]{0,200}2000\s*\)",
        )
        matches = pattern.findall(text)
    else:
        # Buscar solo en los siguientes 1500 chars desde el ancla.
        chunk = text[anchor:anchor + 1500]
        pattern = re.compile(
            r"setInterval\(\s*[\s\S]{0,200}refreshTiaConnection[\s\S]{0,200}2000\s*\)",
        )
        matches = pattern.findall(chunk)
    assert len(matches) >= 1, (
        "main.js debe llamar a refreshTiaConnection con "
        "setInterval(..., 2000) (polling cada 2s del estado TIA). "
        "El call esperado es store.refreshTiaConnection?.() o "
        "refreshTiaConnection()."
    )


def test_main_js_imports_refresh_tia_connection() -> None:
    """``main.js`` importa ``refreshTiaConnection`` del store."""
    text = _read(MAIN_JS)
    assert "refreshTiaConnection" in text, (
        "main.js debe importar y usar refreshTiaConnection del store."
    )


# ── ShellTopbar.js: renderiza el indicador ──────────────────────────


def test_shell_topbar_imports_tia_connection_indicator() -> None:
    """``ShellTopbar.js`` importa ``TiaConnectionIndicator``."""
    text = _read(SHELL_TOPBAR_JS)
    assert "TiaConnectionIndicator" in text, (
        "ShellTopbar.js debe importar el componente TiaConnectionIndicator "
        "para renderizar el círculo de estado en el topbar."
    )


def test_shell_topbar_renders_tia_connection_indicator_in_template() -> None:
    """El template del ShellTopbar monta
    ``<TiaConnectionIndicator>`` con handler ``@connect``."""
    text = _read(SHELL_TOPBAR_JS)
    # Buscamos el tag en el template.
    assert "<TiaConnectionIndicator" in text, (
        "ShellTopbar.js debe renderizar <TiaConnectionIndicator> "
        "en su template."
    )
    assert "@connect" in text, (
        "ShellTopbar.js debe capturar el evento @connect del "
        "indicador para reconectar cuando el operario pulse el círculo."
    )


def test_shell_topbar_handle_connect_calls_connect_tia() -> None:
    """El handler ``handleConnect`` del ShellTopbar debe llamar a
    ``connectTia()`` del store."""
    text = _read(SHELL_TOPBAR_JS)
    start = text.find("function handleConnect")
    assert start != -1, (
        "ShellTopbar.js debe declarar un handler handleConnect para "
        "el evento @connect del TiaConnectionIndicator."
    )
    body = text[start:start + 400]
    assert "connectTia()" in body, (
        "handleConnect debe llamar a connectTia() para forzar la "
        "reconexión del worker TIA persistente."
    )


# ── Sanity: el JS se puede parsear ──────────────────────────────────


def test_store_js_is_syntactically_valid() -> None:
    """Sanity check: el ``store.js`` modificado por PR 5b sigue
    siendo JS válido (llaves balanceadas, node --check OK)."""
    text = _read(STORE_JS)
    assert text.count("{") == text.count("}"), (
        f"Llaves desbalanceadas en store.js: {text.count('{')} '{{' vs "
        f"{text.count('}')} '}}'. Probablemente hay un typo en los "
        "helpers refreshTiaConnection/connectTia/disconnectTia."
    )
    # node --check
    try:
        result = subprocess.run(
            ["node", "--check", str(STORE_JS)],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        pytest.skip("node no disponible en este entorno")
    except subprocess.TimeoutExpired:
        pytest.fail("node --check tardó demasiado en store.js")
    if result.returncode != 0:
        pytest.fail(
            f"store.js no parsea con node --check:\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )


def test_api_js_is_syntactically_valid() -> None:
    """Sanity check: el ``api.js`` modificado por PR 5b sigue
    siendo JS válido."""
    text = _read(API_JS)
    assert text.count("{") == text.count("}"), (
        f"Llaves desbalanceadas en api.js: {text.count('{')} '{{' vs "
        f"{text.count('}')} '}}'."
    )
    try:
        result = subprocess.run(
            ["node", "--check", str(API_JS)],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        pytest.skip("node no disponible en este entorno")
    except subprocess.TimeoutExpired:
        pytest.fail("node --check tardó demasiado en api.js")
    if result.returncode != 0:
        pytest.fail(
            f"api.js no parsea con node --check:\n"
            f"stderr: {result.stderr}"
        )


def test_main_js_is_syntactically_valid() -> None:
    """Sanity check: el ``main.js`` modificado por PR 5b sigue
    siendo JS válido."""
    text = _read(MAIN_JS)
    assert text.count("{") == text.count("}"), (
        f"Llaves desbalanceadas en main.js: {text.count('{')} '{{' vs "
        f"{text.count('}')} '}}'."
    )
    try:
        result = subprocess.run(
            ["node", "--check", str(MAIN_JS)],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        pytest.skip("node no disponible en este entorno")
    except subprocess.TimeoutExpired:
        pytest.fail("node --check tardó demasiado en main.js")
    if result.returncode != 0:
        pytest.fail(
            f"main.js no parsea con node --check:\n"
            f"stderr: {result.stderr}"
        )


def test_shell_topbar_js_is_syntactically_valid() -> None:
    """Sanity check: el ``ShellTopbar.js`` modificado por PR 5b
    sigue siendo JS válido."""
    text = _read(SHELL_TOPBAR_JS)
    assert text.count("{") == text.count("}"), (
        f"Llaves desbalanceadas en ShellTopbar.js: {text.count('{')} '{{' vs "
        f"{text.count('}')} '}}'."
    )
    try:
        result = subprocess.run(
            ["node", "--check", str(SHELL_TOPBAR_JS)],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        pytest.skip("node no disponible en este entorno")
    except subprocess.TimeoutExpired:
        pytest.fail("node --check tardó demasiado en ShellTopbar.js")
    if result.returncode != 0:
        pytest.fail(
            f"ShellTopbar.js no parsea con node --check:\n"
            f"stderr: {result.stderr}"
        )
