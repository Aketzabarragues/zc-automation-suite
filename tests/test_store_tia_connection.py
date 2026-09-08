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


def test_store_tia_connection_initial_state_is_idle() -> None:
    """El estado inicial de ``tiaConnection.state`` debe ser
    ``"idle"`` (state machine sept-2026: el worker persistente
    arranca en idle, subproceso vivo SIN portal attached, y el
    operario decide cuando pulsar "Conectar" del topbar para
    pedir el attach). Es el mismo valor que el backend expone
    en ``GET /api/v1/tia/connection`` antes del primer attach."""
    text = _read(STORE_JS)
    start = text.find("tiaConnection: {")
    assert start != -1
    # Aumentamos el rango a 500 chars para cubrir el comentario
    # doc del slot (sept-2026, mas extenso que el original).
    body = text[start:start + 500]
    assert 'state: "idle"' in body, (
        "tiaConnection.state debe inicializarse a 'idle' "
        "(state machine sept-2026: worker persistente arranca "
        "en idle, sin attach a TIA Portal)."
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
    ``apiFetchTiaConnection()`` (vía import dinámico de api.js) y
    delegar en ``_applyTiaSnapshot`` para mergear el snapshot
    (DRY, fix audit X1 / sept-2026)."""
    text = _read(STORE_JS)
    start = text.find("export async function refreshTiaConnection")
    assert start != -1
    body = text[start:start + 500]
    assert "apiFetchTiaConnection" in body, (
        "refreshTiaConnection debe llamar a apiFetchTiaConnection() "
        "para traer el snapshot del backend."
    )
    assert "_applyTiaSnapshot" in body, (
        "refreshTiaConnection debe delegar en _applyTiaSnapshot "
        "(helper privado declarado en el mismo archivo) para mergear "
        "el snapshot en store.tiaConnection. El bloque de Object.assign "
        "de 12 lineas que antes se duplicaba en refresh/connect/disconnect "
        "ahora vive SOLO en _applyTiaSnapshot (DRY, fix audit X1). "
        "Es la llamada transitiva a Object.assign dentro del helper "
        "lo que preserva la reactividad de los campos anidados "
        "(project, plcs): reasignar store.tiaConnection = r.data "
        "romperia las refs de los computed que ya lo tenian cacheado."
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
    # Ventana ampliada a 6000 chars (antes 4500) en v3.1
    # (sept-2026 round 3): la rama OK de ``connectTia`` ahora
    # anade la lectura de project info Y la lectura de PLCs
    # (cada una con su try/except defensivo + replicacion en
    # slots), lo que empuja la rama ``else if (r)`` con el
    # ``state: "error"`` mas alla de los 4500 chars del commit
    # anterior. 6000 cubre holgadamente la rama de error
    # completa (medido: ~5800 chars a la primera ``state: error``).
    body = text[start:start + 6000]
    assert "state: \"error\"" in body, (
        "connectTia debe poner state='error' si la respuesta del "
        "backend no es OK."
    )
    assert "last_error" in body, (
        "connectTia debe propagar el last_error del backend en el "
        "store para que el TiaConnectionIndicator lo muestre en el tooltip."
    )


# ── store.js: fix audit X1 (sept-2026) — propagacion de worker_alive
#        y project_changed al store desde la respuesta del backend ──
#
# Hallazgo X1: el ``Object.assign`` de los 3 helpers (refresh, connect,
# disconnect) solo copiaba 5 campos (state, project, plcs,
# last_ping_ok_unix, last_error). Los campos ``worker_alive`` y
# ``project_changed`` que el backend SI expone en la respuesta de
# ``GET /api/v1/tia/connection`` (sept-2026) NUNCA llegaban al store,
# asi que el ``WorkerStatusIndicator`` del topbar siempre veia
# ``worker_alive=false`` (circulo gris aunque el worker estuviera vivo).
#
# Fix: nuevo helper privado ``_applyTiaSnapshot(r)`` que los 3 callers
# invocan, con los 7 campos del snapshot. Los tests de esta seccion
# verifican el contrato textual del fix.


def test_store_tia_connection_includes_project_changed_in_initial_state() -> None:
    """El slot ``tiaConnection`` debe inicializar ``project_changed``
    a ``false`` (igual que ``worker_alive``). Antes del fix audit X1
    el slot ni siquiera estaba declarado, asi que cualquier intento
    de leerlo retornaba ``undefined`` (y el componente
    ``WorkerStatusIndicator`` que lo consultase reventaba con
    ``Cannot read properties of undefined``)."""
    import re
    text = _read(STORE_JS)
    start = text.find("tiaConnection: {")
    assert start != -1
    # El slot tiene 2 comentarios de 6-10 lineas cada uno
    # (worker_alive y project_changed). Cogemos 2000 chars para
    # cubrir holgadamente los comentarios y los 2 campos.
    body = text[start:start + 2000]
    # Buscamos la declaracion EXACTA del campo (con ``: false``)
    # en una linea, no en un comentario.
    match = re.search(r"^\s*project_changed\s*:\s*false\s*,?\s*$",
                      body, re.MULTILINE)
    assert match, (
        "El slot tiaConnection debe inicializar "
        "'project_changed: false' (igual que 'worker_alive'). "
        "Sin esta declaracion en el initial state, el "
        "WorkerStatusIndicator (u otros componentes) leeria "
        "'undefined' y no podria mostrar el aviso de proyecto "
        "cambiado que el backend intenta comunicar."
    )


def test_store_tia_connection_includes_worker_alive_in_initial_state() -> None:
    """Regresion explicita: el slot ``tiaConnection`` debe
    inicializar ``worker_alive`` a ``false`` (comprobado tambien por
    el test_store_has_tia_connection_slot de manera implicita via
    el rango de 600 chars; aqui lo anclamos de forma especifica
    con regex para evitar falsos positivos en comentarios)."""
    import re
    text = _read(STORE_JS)
    start = text.find("tiaConnection: {")
    assert start != -1
    body = text[start:start + 2000]
    # Buscamos la declaracion EXACTA del campo (con ``: false``)
    # en una linea, no en un comentario. Patron linea-sucia.
    match = re.search(r"^\s*worker_alive\s*:\s*false\s*,?\s*$",
                      body, re.MULTILINE)
    assert match, (
        "El slot tiaConnection debe inicializar "
        "'worker_alive: false' (mismo patron que el resto de "
        "campos del slot)."
    )


def test_apply_tia_snapshot_helper_is_declared() -> None:
    """El archivo ``store.js`` debe declarar un helper privado
    ``_applyTiaSnapshot(r)`` que centralice el ``Object.assign`` del
    snapshot (DRY, fix audit X1). Sin él, los 3 helpers de la SPA
    (refresh, connect, disconnect) seguirian duplicando el mismo
    bloque de 12 lineas y los campos ``worker_alive`` /
    ``project_changed`` seguirian sin propagarse al store."""
    text = _read(STORE_JS)
    assert "function _applyTiaSnapshot" in text, (
        "store.js debe declarar el helper privado _applyTiaSnapshot "
        "que aplica el snapshot de GET /tia/connection al store. "
        "Es el punto de entrada unico para que los 3 helpers "
        "propaguen worker_alive y project_changed."
    )


def test_apply_tia_snapshot_propagates_worker_alive() -> None:
    """El helper ``_applyTiaSnapshot`` debe incluir ``worker_alive``
    en su ``Object.assign`` para que el flag del backend llegue al
    store (y de ahi al ``WorkerStatusIndicator`` del topbar).

    Antes del fix audit X1, el ``Object.assign`` original NO tenia
    este campo, asi que el indicador veia siempre ``false``
    (circulo gris aunque el worker estuviera vivo)."""
    text = _read(STORE_JS)
    start = text.find("function _applyTiaSnapshot")
    assert start != -1, (
        "store.js debe declarar _applyTiaSnapshot (ver "
        "test_apply_tia_snapshot_helper_is_declared)."
    )
    # El cuerpo del helper es de ~50 lineas. Cogemos 1500 chars
    # para cubrir el Object.assign + el if de _logTiaStateTransition.
    body = text[start:start + 1500]
    assert "worker_alive" in body, (
        "_applyTiaSnapshot debe propagar el campo 'worker_alive' de "
        "r.data al store. Sin esto, el WorkerStatusIndicator del "
        "topbar queda siempre en 'false' (circulo gris)."
    )
    # El Object.assign es la unica via legal para preservar la
    # reactividad de los campos anidados. Verificamos que worker_alive
    # se asigna DENTRO de un Object.assign sobre store.tiaConnection.
    # Patron: ``worker_alive: r.data.worker_alive === true`` (o
    # equivalente con validacion).
    assert (
        "Object.assign(store.tiaConnection" in body
        and "worker_alive" in body
    ), (
        "_applyTiaSnapshot debe copiar worker_alive desde r.data al "
        "store.tiaConnection via Object.assign (no reasignacion "
        "completa, para preservar la reactividad)."
    )


def test_apply_tia_snapshot_propagates_project_changed() -> None:
    """El helper ``_applyTiaSnapshot`` debe incluir ``project_changed``
    en su ``Object.assign`` para que el flag one-shot del backend
    (que indica que el operario cambio de proyecto en TIA) llegue
    al store. Antes del fix audit X1, el slot no existia siquiera
    en el initial state del store, asi que leerlo retornaba
    ``undefined``."""
    text = _read(STORE_JS)
    start = text.find("function _applyTiaSnapshot")
    assert start != -1
    body = text[start:start + 1500]
    assert "project_changed" in body, (
        "_applyTiaSnapshot debe propagar el campo 'project_changed' "
        "de r.data al store. Sin esto, el frontend no puede mostrar "
        "el aviso 'el proyecto TIA ha cambiado' que el backend "
        "intenta comunicar al operario tras un cambio de proyecto "
        "en TIA Portal."
    )


def test_apply_tia_snapshot_defaults_missing_worker_alive_to_false() -> None:
    """Si el backend NO incluye ``worker_alive`` en la respuesta
    (modo 1-shot / MCP / respuestas sinteticas de tests, donde solo
    expone ``state`` y ``error``), ``_applyTiaSnapshot`` debe
    dejar ``store.tiaConnection.worker_alive`` en ``false``.

    Esto se valida textualmente buscando el patron
    ``worker_alive: r.data.worker_alive === true`` (o equivalente
    con coercion explicita a booleano). Si la asignacion fuese
    ``worker_alive: r.data.worker_alive`` (sin coercion), un
    valor ``undefined`` del backend dejaria el campo en ``undefined``
    y el ``WorkerStatusIndicator`` (que lee
    ``Boolean(tc && tc.worker_alive)``) lo pintaria gris de
    todas formas, pero queremos ser explicitos sobre el default.

    Sept-2026 (fix parpadeo "muerto"): la coercion ahora vive
    dentro de un ternario que PRESERVA el valor previo del store
    si el campo viene ``undefined`` (defensa frontend, complemento
    del fix backend que ahora expone ``worker_alive`` en las
    respuestas POST). La coercion explicita a booleano se
    mantiene: si el backend incluye el campo, se graba el bool
    real; si lo omite, se conserva el valor previo.
    """
    text = _read(STORE_JS)
    start = text.find("function _applyTiaSnapshot")
    assert start != -1
    # Ventana ampliada a 2500 chars (antes 1500) en sept-2026:
    # el ternario del fix parpadeo añade ~12 lineas antes de
    # ``worker_alive`` y ``project_changed`` (comentario
    # explicativo + multi-line ternary). Sigue cubriendo la
    # rama de exito completa de ``_applyTiaSnapshot``.
    body = text[start:start + 2500]
    # Patron esperado: coercion explicita a ``true``. Aceptamos
    # ``=== true`` o ``!!r.data.worker_alive`` como equivalentes.
    # NO aceptamos asignacion directa sin coercion
    # (``worker_alive: r.data.worker_alive``) porque eso dejaria
    # ``undefined`` si el backend omitiese el campo.
    has_explicit_bool = (
        "r.data.worker_alive === true" in body
        or "Boolean(r.data.worker_alive)" in body
        or "!!r.data.worker_alive" in body
    )
    assert has_explicit_bool, (
        "_applyTiaSnapshot debe coercionar worker_alive a booleano "
        "explicito (e.g. 'r.data.worker_alive === true'). Si el "
        "backend omite el campo (modo 1-shot), el store debe "
        "quedar en 'false' (no 'undefined'), para que "
        "WorkerStatusIndicator pinte gris de forma consistente."
    )


def test_apply_tia_snapshot_defaults_missing_project_changed_to_false() -> None:
    """Si el backend NO incluye ``project_changed`` en la respuesta,
    ``_applyTiaSnapshot`` debe dejar el campo en ``false`` (no
    ``undefined``). Mismo motivo que el test anterior: el slot se
    inicializa a ``false`` y debe CONSERVAR ese valor si el backend
    lo omite, no degradarse a ``undefined``."""
    text = _read(STORE_JS)
    start = text.find("function _applyTiaSnapshot")
    assert start != -1
    # Ventana ampliada a 2500 chars (mismo motivo que el test
    # de ``worker_alive`` justo arriba: el fix parpadeo anade
    # lineas extra en la rama de exito de ``_applyTiaSnapshot``).
    body = text[start:start + 2500]
    has_explicit_bool = (
        "r.data.project_changed === true" in body
        or "Boolean(r.data.project_changed)" in body
        or "!!r.data.project_changed" in body
    )
    assert has_explicit_bool, (
        "_applyTiaSnapshot debe coercionar project_changed a "
        "booleano explicito. Si el backend omite el campo, el "
        "store debe quedar en 'false' (no 'undefined')."
    )


def test_apply_tia_snapshot_rejects_non_ok_response() -> None:
    """``_applyTiaSnapshot(r)`` debe retornar ``false`` SIN tocar
    el store si ``r.ok`` es falsy o si ``r.data`` no es un objeto.
    Asi, ``disconnectTia`` (que delega siempre en el helper) no
    pisa el store con una respuesta de error que solo trae
    ``{error: "..."}``."""
    text = _read(STORE_JS)
    start = text.find("function _applyTiaSnapshot")
    assert start != -1
    body = text[start:start + 1500]
    # El helper debe hacer un early-return en la primera linea (o
    # casi) si la respuesta no es OK. Patron esperado:
    # ``if (!r || !r.ok || !r.data || typeof r.data !== "object") return false;``
    assert "!r.ok" in body, (
        "_applyTiaSnapshot debe chequear r.ok y retornar false "
        "para respuestas no-OK (e.g. {ok: false, data: {error: ...}})."
    )
    assert "return false" in body, (
        "_applyTiaSnapshot debe retornar false (no undefined) para "
        "que los callers puedan distinguir 'snapshot aplicado' de "
        "'snapshot descartado'."
    )


def test_apply_tia_snapshot_validates_state_field() -> None:
    """``_applyTiaSnapshot(r)`` debe validar que ``r.data.state`` sea
    uno de los 4 valores estables del state machine sept-2026
    (``connected`` / ``connecting`` / ``idle`` / ``error``). Si
    no lo es, descarta el snapshot (mismo patron que tenia el
    ``refreshTiaConnection`` original antes del refactor, ahora
    centralizado en el helper). El antiguo ``disconnected`` ya
    NO se acepta (el backend no lo emite nunca)."""
    text = _read(STORE_JS)
    start = text.find("function _applyTiaSnapshot")
    assert start != -1
    body = text[start:start + 1500]
    for s in ("connected", "connecting", "idle", "error"):
        assert s in body, (
            f"_applyTiaSnapshot debe aceptar el state {s!r} "
            f"(validacion contra los 4 valores estables del "
            f"state machine sept-2026)."
        )


def test_refresh_tia_connection_delegates_to_apply_tia_snapshot() -> None:
    """``refreshTiaConnection()`` debe delegar SIEMPRE en
    ``_applyTiaSnapshot(r)`` (no reimplementar el ``Object.assign``
    inline). Es el contrato DRY que el fix audit X1 introduce:
    el bloque de 12 lineas que antes se copiaba en los 3 helpers
    ahora vive SOLO en el helper."""
    text = _read(STORE_JS)
    start = text.find("export async function refreshTiaConnection")
    assert start != -1
    body = text[start:start + 500]
    assert "_applyTiaSnapshot" in body, (
        "refreshTiaConnection debe delegar en _applyTiaSnapshot. "
        "Sin esto, el campo worker_alive/project_changed no llega "
        "al store desde el polling cada 2s (caso de uso principal "
        "del bug X1)."
    )


def test_connect_tia_delegates_to_apply_tia_snapshot() -> None:
    """``connectTia()`` debe delegar en ``_applyTiaSnapshot(r)``
    en la rama de exito (respuesta OK). Asi, cuando el worker
    arranca correctamente y el backend devuelve el snapshot con
    ``worker_alive=true``, el store se actualiza."""
    text = _read(STORE_JS)
    start = text.find("export async function connectTia")
    assert start != -1
    body = text[start:start + 1500]
    assert "_applyTiaSnapshot" in body, (
        "connectTia debe delegar en _applyTiaSnapshot en su "
        "rama de exito (respuesta OK). Asi, el snapshot que el "
        "backend devuelve tras el cold-attach (incluidos "
        "worker_alive y project_changed) llega al store."
    )


def test_disconnect_tia_delegates_to_apply_tia_snapshot() -> None:
    """``disconnectTia()`` debe delegar SIEMPRE en
    ``_applyTiaSnapshot(r)``. Es el unico helper que lo hace sin
    guard de estado previo (el de connect guarda el ``prevState``
    para el path de error; el de disconnect no lo necesita porque
    el helper hace su propia deteccion de transicion).

    Sept-2026 round 3 (fix de auditoría): la ventana de búsqueda
    se amplio a 1500 chars (antes 500) porque la función ganó un
    ``store.busy`` guard al inicio (idempotencia anti doble-click),
    que mueve la delegación a ``_applyTiaSnapshot`` más allá de los
    500 chars. La ventana de 1500 sigue cubriendo la rama de éxito
    completa.
    """
    text = _read(STORE_JS)
    start = text.find("export async function disconnectTia")
    assert start != -1
    body = text[start:start + 1500]
    assert "_applyTiaSnapshot" in body, (
        "disconnectTia debe delegar en _applyTiaSnapshot. Aunque "
        "el backend en este endpoint no expone worker_alive ni "
        "project_changed (solo state y error), el helper tolera "
        "que falten y los pone a false (no rompe)."
    )


# ── v2.2 (sept-2026): disconnectTia limpia los slots del PLC ────────
#
# Hallazgo: tras el refactor del state machine, "Desconectar"
# deja el worker en idle (subproceso vivo, sin portal attached).
# Sin limpieza de los slots del PLC, el topbar seguiria
# mostrando la lista de PLCs del attach anterior y el caption
# del proyecto viejo, dando la falsa sensacion de "sigo
# conectado". El operario ve el circulo gris del
# TiaConnectionIndicator pero el <select> sigue lleno de PLCs
# stale.
#
# Fix: disconnectTia() vacia plcs, selectedPlc, plcBlocksCache
# y projectInfo cuando la respuesta del backend es OK.


def test_disconnect_clears_plc_state() -> None:
    """``disconnectTia()`` debe limpiar el state PLC-related tras
    un detach OK. Sin esta limpieza, el topbar mostraria PLCs
    stale y un caption de proyecto antiguo tras un "Conectar /
    Desconectar" rapido.

    Sept-2026 (limpieza reactiva): las asignaciones literales
    ``store.plcs = []`` etc. ya NO viven dentro de ``disconnectTia``
    (ahora se reutiliza ``_clearAllPlcStateOnTiaLoss``, el mismo
    helper que aplica el cleanup reactivo en ``_applyTiaSnapshot``
    cuando TIA se cierra por fuera). Verificamos:
      1. El helper existe y limpia los 4 slots "historicos"
         (plcs, selectedPlc, plcBlocksCache, projectInfo).
      2. ``disconnectTia`` invoca el helper tras un ``r && r.ok``.
    """
    text = _read(STORE_JS)
    # 1) El helper existe y limpia los 4 slots historicos.
    helper_start = text.find("function _clearAllPlcStateOnTiaLoss")
    assert helper_start != -1, (
        "store.js debe declarar el helper _clearAllPlcStateOnTiaLoss "
        "(sept-2026, limpieza reactiva al cierre externo de TIA)."
    )
    # Cogemos 2500 chars del helper: cubre el JSDoc (~30 lineas)
    # Y las asignaciones (~25 lineas). El helper total es ~55
    # lineas (~3000 chars); 2500 cubre las primeras 4
    # asignaciones (plcs, selectedPlc, plcBlocksCache, projectInfo)
    # que son las que este test valida.
    helper_body = text[helper_start:helper_start + 2500]
    for slot, val in (
        ('store.plcs = []',          "plcs (lista)"),
        ('store.selectedPlc = ""',   "selectedPlc (dropdown)"),
        ('store.plcBlocksCache = null', "plcBlocksCache (snapshot bloques)"),
        ('store.projectInfo = null', "projectInfo (caption proyecto)"),
    ):
        assert slot in helper_body, (
            f"_clearAllPlcStateOnTiaLoss debe resetear {val} "
            f"(asignacion esperada: '{slot}'). Sin esta limpieza, "
            f"el topbar mostraria datos stale del attach anterior."
        )

    # 2) disconnectTia invoca el helper tras un r && r.ok.
    disconnect_start = text.find("export async function disconnectTia")
    assert disconnect_start != -1
    # Cogemos un tramo generoso que cubra el body entero.
    body = text[disconnect_start:disconnect_start + 2500]
    assert "_clearAllPlcStateOnTiaLoss" in body, (
        "disconnectTia debe invocar el helper _clearAllPlcStateOnTiaLoss "
        "tras un detach OK (sept-2026, armonizacion con el cierre "
        "externo de TIA)."
    )
    assert "r && r.ok" in body or "r.ok" in body, (
        "disconnectTia debe guardar la llamada al helper detras "
        "de un check 'r && r.ok' (o equivalente) para no "
        "pisar slots en error path."
    )


def test_disconnect_clears_plc_state_only_on_ok_response() -> None:
    """``disconnectTia()`` solo debe limpiar el state PLC-related
    si la respuesta del backend es OK (``r && r.ok``). Si el
    detach fallo, preferimos dejar los slots como estaban
    (un "stale" visible es mejor que un "vacio" confuso cuando
    el operario no sabe si el detach se hizo o no).

    Sept-2026: la limpieza se hace via ``_clearAllPlcStateOnTiaLoss()``
    (helper compartido con el cierre externo). Verificamos que
    la llamada al helper esta detras del guard ``r && r.ok``.
    """
    text = _read(STORE_JS)
    start = text.find("export async function disconnectTia")
    assert start != -1
    body = text[start:start + 2500]
    assert "r && r.ok" in body or "r.ok" in body, (
        "disconnectTia debe guardar la limpieza del PLC detras "
        "de un check 'r && r.ok' (o equivalente) para no "
        "pisar slots en error path."
    )
    # Y la llamada al helper esta dentro de ese guard.
    assert "_clearAllPlcStateOnTiaLoss" in body, (
        "disconnectTia debe invocar el helper _clearAllPlcStateOnTiaLoss "
        "para limpiar el state PLC-related (sept-2026)."
    )


# ── Sept-2026: limpieza REACTIVA al cierre externo de TIA ─────────
#
# Caso: el operario cierra TIA Portal sin pulsar "Desconectar"
# (lo cierra en el SO, o se cae el proceso TIA). El worker
# persistente lo detecta por heartbeat y la SPA transiciona
# ``tiaConnection.state`` a ``"idle"`` o ``"error"``. Hasta
# sept-2026 eso solo actualizaba el circulo del topbar: el
# resto de caches (plcs, selectedPlc, plcBlocksCache, projectInfo,
# previewData, procesosSync) quedaban stale.
#
# Fix: ``_applyTiaSnapshot`` detecta la transicion
# ``connected|connecting -> idle|error`` y aplica el helper
# ``_clearAllPlcStateOnTiaLoss``, dejando ademas un aviso
# "warning" en la ConsolaLogs via ``apiPushLog`` (fire-and-forget,
# no bloquea la SPA).
# ───────────────────────────────────────────────────────────────────


def test_apply_tia_snapshot_clears_plc_state_on_external_close() -> None:
    """``_applyTiaSnapshot`` debe limpiar el state PLC-related
    cuando detecta una transicion ``connected|connecting ->
    idle|error`` (TIA cerrado por fuera).

    El patron textual: dentro del cuerpo de ``_applyTiaSnapshot``
    debe haber un bloque ``if`` que:
      1. Compruebe ``prevState`` (connected o connecting) Y
         ``newState`` (idle o error).
      2. Invoque ``_clearAllPlcStateOnTiaLoss()``.
      3. Haga un push de log al backend via ``apiPushLog``
         con ``level: "warning"`` para que la ConsolaLogs
         muestre el aviso al operario.
    """
    text = _read(STORE_JS)
    start = text.find("function _applyTiaSnapshot")
    assert start != -1
    # Cogemos el cuerpo entero. La funcion crecio con la
    # limpieza reactiva (~80 lineas, ~4500 chars).
    body = text[start:start + 5000]

    # 1) El helper se invoca dentro de _applyTiaSnapshot.
    assert "_clearAllPlcStateOnTiaLoss" in body, (
        "_applyTiaSnapshot debe invocar el helper "
        "_clearAllPlcStateOnTiaLoss en la rama de transicion "
        "connected/connecting -> idle/error (sept-2026)."
    )

    # 2) La condicion de la transicion. Usamos regex para ser
    # robustos a whitespace / saltos de linea.
    import re
    pattern = re.compile(
        r"prevState\s*===\s*[\"']connected[\"']\s*\|\|\s*"
        r"prevState\s*===\s*[\"']connecting[\"']\s*"
        r".*?"
        r"newState\s*===\s*[\"']idle[\"']\s*\|\|\s*"
        r"newState\s*===\s*[\"']error[\"']",
        re.DOTALL,
    )
    assert pattern.search(body), (
        "_applyTiaSnapshot debe tener una condicion que detecte "
        "transicion prevState in {connected, connecting} Y "
        "newState in {idle, error} para disparar la limpieza "
        "reactiva (sept-2026)."
    )

    # 3) Push de log al backend para que la ConsolaLogs muestre
    # el aviso. Usamos apiPushLog con level "warning" (no
    # "info", "success" o "error" — el operario tiene que ver
    # claramente que algo paso).
    assert "apiPushLog" in body, (
        "_applyTiaSnapshot debe pushear un log al backend via "
        "apiPushLog para que la ConsolaLogs muestre el aviso "
        "de cierre externo (sept-2026)."
    )
    assert "warning" in body, (
        "El log pusheado al backend debe ser de nivel 'warning' "
        "para que el operario lo identifique claramente."
    )


def test_apply_tia_snapshot_does_not_clear_on_idle_to_connecting() -> None:
    """``_applyTiaSnapshot`` NO debe limpiar en una transicion
    ``idle -> connecting`` (el operario esta conectando, no
    se ha perdido la conexion).

    Test de regresion: si la condicion de la limpieza es
    demasiado laxa (p.ej. ``newState === "idle"`` sin
    comprobar ``prevState``), se dispararia un cleanup espurio
    en cada intento de conectar. Verificamos que el cleanup
    SOLO se dispara cuando ``prevState`` era
    ``connected|connecting``.
    """
    text = _read(STORE_JS)
    start = text.find("function _applyTiaSnapshot")
    assert start != -1
    body = text[start:start + 5000]

    # Buscamos el patron. Si la condicion es demasiado laxa
    # (solo ``newState === "idle"``), el regex no matchea.
    import re
    pattern = re.compile(
        r"(prevState\s*===\s*[\"']connected[\"']\s*\|\|\s*"
        r"prevState\s*===\s*[\"']connecting[\"'])\s*"
        r".*?"
        r"(newState\s*===\s*[\"']idle[\"']\s*\|\|\s*"
        r"newState\s*===\s*[\"']error[\"'])",
        re.DOTALL,
    )
    assert pattern.search(body), (
        "La limpieza reactiva debe condicionarse a "
        "prevState in {connected, connecting} (no solo a "
        "newState in {idle, error}). Si la condicion es solo "
        "el newState, se dispararia un cleanup espurio en cada "
        "idle->connecting del operario (regression)."
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


# ── BloquesCacheView.js: renderiza el TIA state como texto ──────────
#
# Tras la migración v3.0 (sept-2026), el ``TiaConnectionIndicator``
# visual desapareció de la ``ShellTopbar``. Su información se
# muestra AHORA como texto en el primer card de
# ``BloquesCacheView.js`` (fila de estado, ``TIA: <state>`` con
# color green/amber/red/gray) + un botón "🔌 Conectar" que
# dispara el mismo flujo de antes.


BLOQUES_CACHE_VIEW_JS = (
    REPO_ROOT
    / "areas" / "alimentacion" / "frontend" / "components"
    / "BloquesCacheView.js"
)


def test_bloques_cache_view_renders_tia_state_text() -> None:
    """El primer card de ``BloquesCacheView`` pinta el estado del
    TIA como texto (sin indicator visual): ``TIA: connected |
    connecting… | idle | error``, con la misma paleta de colores
    que el antiguo ``TiaConnectionIndicator``.
    """
    text = _read(BLOQUES_CACHE_VIEW_JS)
    # Setup: computeds que derivan el state + texto + color.
    assert "tiaState" in text, (
        "BloquesCacheView debe declarar un computed 'tiaState' "
        "que lee store.tiaConnection.state."
    )
    assert "tiaStateText" in text, (
        "BloquesCacheView debe declarar un computed 'tiaStateText' "
        "que mapea state a texto (connected/connecting…/idle/error)."
    )
    assert "tiaStateClass" in text, (
        "BloquesCacheView debe declarar un computed 'tiaStateClass' "
        "que mapea state a color (green/amber/red/gray)."
    )
    # Template: caption "TIA:" + texto del state con color.
    assert "TIA:" in text, (
        "BloquesCacheView debe pintar el caption 'TIA:' en su template."
    )
    assert "text-green-600" in text, (
        "El state 'connected' debe pintarse con text-green-600."
    )
    assert "text-amber-600" in text, (
        "El state 'connecting' debe pintarse con text-amber-600."
    )
    assert "text-red-700" in text, (
        "El state 'error' debe pintarse con text-red-700."
    )


def test_bloques_cache_view_handle_connect_calls_connect_tia() -> None:
    """El handler ``handleConnect`` del primer card de
    ``BloquesCacheView`` debe llamar a ``connectTia()`` del store
    (mismo flujo que tenía el antiguo ShellTopbar)."""
    text = _read(BLOQUES_CACHE_VIEW_JS)
    start = text.find("function handleConnect")
    assert start != -1, (
        "BloquesCacheView debe declarar un handler handleConnect "
        "(migrado de ShellTopbar en v3.0) para el botón '🔌 Conectar'."
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
