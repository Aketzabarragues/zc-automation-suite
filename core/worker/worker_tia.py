"""Worker persistente de TIA Portal (subproceso aislado).

Este modulo es el UNICO punto de importacion de
``siemens_tia_scripting`` en todo el proyecto
(ver ``.clinerules`` seccion 1). Vive como subproceso aislado,
comunicandose con el proceso IT (FastAPI) por JSON sobre stdin/stdout,
con logs a stderr.

Convenciones del protocolo (ver ``.clinerules`` secciones 2 y 3):
  - stdin: un JSON por linea. Formato
    ``{"id": <int>, "cmd": "<comando>", "args": {<kwargs>}}``.
  - stdout: un JSON por linea. Formato
    ``{"id": <int>, "ok": <bool>, "result": <any>}`` en exito,
    o ``{"id": <int>, "ok": false, "error": "<str>"}`` en fallo.
  - stderr: logs libres, NUNCA JSON (stdout es exclusivo del
    protocolo).

State machine de 4 estados (definida en ``.clinerules`` seccion 2):
  - idle: estado inicial. ``portal`` es None.
  - connecting: ``attach_portal`` en curso.
  - connected: ``attach_portal`` OK. Los handlers de comandos
    operan contra ``portal``.
  - error: fallo grave de I/O o del wrapper. El worker sigue vivo
    pero los comandos que requieren el portal devuelven error
    hasta el siguiente ``attach_portal``.

Reglas ineludibles:
  - **Lazy import** de ``siemens_tia_scripting`` (dentro de
    ``_load_tia_wrapper``, nunca a nivel de modulo). Si no esta
    disponible, los comandos que lo requieren devuelven error;
    el worker NO muere (la app sigue arrancando).
  - **set_logging(console=False)** justo despues de cargar el
    wrapper. Si no, Siemens escribe a stdout y rompe el parseo
    JSON del padre.
  - **Carga del .pyd en frozen** (PyInstaller): manual via
    ``sys.path`` + ``os.environ["PATH"]`` + ``os.add_dll_directory``
    desde ``sys._MEIPASS``. **NUNCA** ``importlib.util``
    (verificado en produccion, ``.clinerules`` seccion 4).
  - **Cleanup en exit/EOF**: ``portal.detach()`` best-effort.
    Libera el RCW; con el, el .pyd de Siemens (~200 MB).
  - **Mapeo a primitivos**: nunca devolver objetos .NET
    (``Plc``, ``ProgramBlock``, etc.) al padre. Mapear a
    ``dict``/``list``/``str``/``bool``/``int`` antes de emitir
    (``.clinerules`` seccion 3).
  - **No asyncio**: el worker es sincrono. Lee stdin bloqueante,
    ejecuta el handler, escribe a stdout. La asincronia vive
    en el bridge (FastAPI side).
  - **Comandos inline en el loop**, NO en un registry: algunos
    handlers reasignan ``_portal`` (variable del modulo) y eso
    seria fragil con un registry.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

# Logger del modulo. Va a stderr, NUNCA a stdout (stdout es exclusivo
# del JSON del protocolo).
log = logging.getLogger("core.worker.worker_tia")

# ── Constantes del state machine ─────────────────────────────────────────
# Definidas como constantes para que las comparaciones sean robustas
# ante typos. Ver ``.clinerules`` seccion 2.
_STATE_IDLE = "idle"
_STATE_CONNECTING = "connecting"
_STATE_CONNECTED = "connected"
_STATE_ERROR = "error"

# ── Estado del worker ────────────────────────────────────────────────────
# Variables locales del modulo. El worker es un subproceso aislado,
# asi que no hay riesgo de colision con otros modulos del proceso IT.
_state: str = _STATE_IDLE
_portal: Any = None  # Objeto nativo de TIA Openness. None en idle/error.

# ── Cache del wrapper de Siemens ─────────────────────────────────────────
# Se carga perezosamente la primera vez que un handler lo necesita.
# ``_tia_wrapper_loaded`` evita reintentar el import si ya tuvimos exito.
# ``_tia_wrapper_failed`` evita reintentar si ya fallamos (rapido, no
# bloquea al worker).
_tia_wrapper: Any = None
_tia_wrapper_loaded: bool = False
_tia_wrapper_failed: bool = False

# ── Heartbeat ────────────────────────────────────────────────────────────
# Escrito a stderr cada N segundos. NO a stdout (romperia el JSON).
# Es interno: el padre lo lee para diagnostico, no se expone al frontend
# (ver ``.clinerules`` seccion 7).
_HEARTBEAT_INTERVAL_SECONDS = 5.0


# ════════════════════════════════════════════════════════════════════════
#  Helpers de protocolo
# ════════════════════════════════════════════════════════════════════════


def _emit_response(
    message_id: int | None,
    ok: bool,
    result: Any = None,
    error: str | None = None,
) -> None:
    """Escribe una respuesta JSON en stdout. Un unico JSON por llamada.

    Args:
        message_id: El id del comando que origino esta respuesta.
            ``None`` se permite para mensajes espontaneos (no usados
            por ahora, pero el protocolo lo soporta).
        ok: ``True`` si el comando fue exitoso, ``False`` si fallo.
        result: Valor de retorno del comando. Solo se incluye si
            ``ok`` es True y ``result`` no es None. El caller es
            responsable de haber mapeado cualquier objeto nativo .NET
            a primitivos Python (``dict``/``list``/``str``/``bool``/``int``)
            antes de pasar este argumento (````.clinerules`` seccion 3).
        error: Mensaje de error legible. Solo se incluye si ``ok`` es
            False. Default "Unknown error" si no se proporciona.
    """
    if message_id is not None:
        response: dict[str, Any] = {"id": message_id, "ok": ok}
    else:
        response = {"ok": ok}
    if ok:
        if result is not None:
            response["result"] = result
        # Si result es None y ok=True, omitimos el campo "result".
        # El bridge hace ``response.get("result")`` y obtiene None;
        # cada caller decide si None es valido para su comando.
    else:
        response["error"] = error or "Unknown error"
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


def _set_state(new_state: str) -> None:
    """Actualiza el estado del worker. Solo transiciones validas.

    Args:
        new_state: Uno de los 4 estados (``_STATE_IDLE``,
            ``_STATE_CONNECTING``, ``_STATE_CONNECTED``, ``_STATE_ERROR``).
    """
    global _state
    if new_state not in (
        _STATE_IDLE,
        _STATE_CONNECTING,
        _STATE_CONNECTED,
        _STATE_ERROR,
    ):
        log.error("Invalid state transition: %r", new_state)
        return
    if _state != new_state:
        log.info("state -> %s", new_state)
    _state = new_state


# ════════════════════════════════════════════════════════════════════════
#  Heartbeat (thread daemon, no asyncio)
# ════════════════════════════════════════════════════════════════════════


def _heartbeat_loop() -> None:
    """Escribe un heartbeat a stderr cada ``_HEARTBEAT_INTERVAL_SECONDS``.

    Por que un thread daemon y no asyncio:
        El loop principal es sincrono (``for line in sys.stdin``). Un
        task asyncio exigiria改革的 el loop, lo que complicaria el
        modelo. Un thread daemon que solo escribe a stderr es simple,
        no compite por el stdin, y muere con el proceso.

    Por que stderr y no stdout:
        stdout es exclusivo del JSON del protocolo. Si escribimos ahi,
        el padre no podra parsearlo (``json.loads`` falla con texto
        que no es JSON valido).
    """
    while True:
        time.sleep(_HEARTBEAT_INTERVAL_SECONDS)
        try:
            ts = datetime.datetime.now().isoformat()
            portal_str = "Yes" if _portal is not None else "No"
            sys.stderr.write(
                f"[heartbeat] {ts} state={_state} portal={portal_str}\n"
            )
            sys.stderr.flush()
        except Exception as e:  # noqa: BLE001 — el heartbeat NUNCA mata el loop
            # Si stderr se cierra (p.ej. el padre muere), dejamos de
            # escribir en vez de romper el thread.
            log.debug("heartbeat write failed (non-fatal): %s", e)
            return


# ════════════════════════════════════════════════════════════════════════
#  Carga del wrapper de Siemens (lazy)
# ════════════════════════════════════════════════════════════════════════


def _load_tia_wrapper() -> Any:
    """Carga el wrapper ``siemens_tia_scripting`` (lazy import).

    Por que lazy (ver ``.clinerules`` seccion 1):
        El proceso IT (FastAPI) NUNCA debe importar este modulo. Si lo
        hace, el .pyd de Siemens se carga en el proceso IT, el worker
        se reinicia al detectar conflicto y el attach persistente se
        pierde. Por eso este import esta dentro de una funcion y no a
        nivel de modulo: el wrapper solo se toca cuando un handler lo
        necesita.

    Carga del .pyd en frozen (PyInstaller, ver ``.clinerules`` seccion 4):
        Manual via:
          1. ``sys.path.insert(0, sys._MEIPASS)`` — para que el
             ``import`` normal encuentre el .pyd.
          2. ``os.environ["PATH"]`` prepend con el dir de DLLs nativas
             — para que el loader de Windows encuentre las DLLs que
             el .pyd carga dinamicamente.
          3. ``os.add_dll_directory(...)`` — API de Windows 10+ que
             registra el dir en el DLL search path del proceso.
        **NUNCA** ``importlib.util`` para esto: probado contra el manual
        de Openness y la experiencia en produccion.

    Returns:
        El modulo ``siemens_tia_scripting`` ya con el logger nativo
        silenciado (``set_logging(console=False)``).

    Raises:
        RuntimeError: Si la carga falla. El caller (handler) lo
            convierte en una respuesta ``ok=False`` al comando;
            el worker NO muere.
    """
    global _tia_wrapper, _tia_wrapper_loaded, _tia_wrapper_failed

    if _tia_wrapper_loaded:
        return _tia_wrapper
    if _tia_wrapper_failed:
        raise RuntimeError(
            "siemens_tia_scripting previously failed to load; "
            "check stderr for the original error"
        )

    if getattr(sys, "frozen", False):
        # PyInstaller frozen: el .pyd y las DLLs nativas se desempaquetan
        # en ``sys._MEIPASS``. Hay que registrar el path antes del import.
        meipass = getattr(sys, "_MEIPASS", None)
        if not meipass:
            _tia_wrapper_failed = True
            raise RuntimeError("Frozen but sys._MEIPASS is not set")
        meipass_path = Path(meipass)

        # 1. sys.path: para que ``import siemens_tia_scripting`` funcione.
        if str(meipass_path) not in sys.path:
            sys.path.insert(0, str(meipass_path))

        # 2+3. PATH y add_dll_directory: para las DLLs nativas (vienen
        # en un subdirectorio ``tia_native/`` segun el build_exe.py;
        # si no existe, no pasa nada, el path normal puede bastar).
        native_dir = meipass_path / "tia_native"
        if native_dir.is_dir():
            native_str = str(native_dir)
            os.environ["PATH"] = (
                native_str + os.pathsep + os.environ.get("PATH", "")
            )
            try:
                # Windows 10+ / Server 2016+: registra el dir en el
                # DLL search path del proceso. No existe en Windows
                # < 10 ni en POSIX, pero ahi no necesitamos DLLs .NET.
                os.add_dll_directory(native_str)
            except (AttributeError, OSError) as e:
                # No es critico: PATH prepended puede ser suficiente.
                log.debug("os.add_dll_directory failed (non-fatal): %s", e)

    try:
        import siemens_tia_scripting as ts  # type: ignore[import-not-found]
    except ImportError as e:
        _tia_wrapper_failed = True
        log.error(
            "Failed to import siemens_tia_scripting: %s. "
            "The worker will stay alive but TIA commands will fail "
            "until the wrapper is installed in the venv or staged "
            "in sys._MEIPASS (frozen).",
            e,
        )
        raise RuntimeError(f"siemens_tia_scripting not available: {e}")

    # Silenciar el logger nativo de Siemens. **CRITICO**: si no, escribe
    # a stdout y rompe el parseo JSON del padre. Leccion empirica
    # (``PLC_IE_61131_GREENFIELD.md`` leccion X2, ``.clinerules`` seccion 2).
    try:
        ts.set_logging(console=False)
    except Exception as e:  # noqa: BLE001 — el silencio del log no es critico
        log.warning("set_logging(console=False) failed (non-fatal): %s", e)

    _tia_wrapper = ts
    _tia_wrapper_loaded = True
    log.info("siemens_tia_scripting loaded successfully")
    return ts


# ════════════════════════════════════════════════════════════════════════
#  Handlers de comandos (inline en el loop, ver docstring del modulo)
# ════════════════════════════════════════════════════════════════════════


def _handle_attach_portal(args: dict[str, Any], message_id: int) -> None:
    """Handler de ``attach_portal``: ``ts.attach_portal(portal_mode)``.

    Verificado contra el manual Openness V1.2.1
    (``PLC_IE_61131_GREENFIELD.md`` seccion 0.1, ``.clinerules`` seccion 4):
      - ``ts.attach_portal(portal_mode)`` requiere una instancia YA en
        ejecucion. **NO** lanza TIA Portal. Si TIA no esta abierto,
        el comando falla con un error nativo.
      - ``portal_mode`` es un param del frontend (default "Primary").

    **RESOLUCION DEL BUG DEL ENUM** (validado con TIA Portal abierto,
    pid 25448, proyecto ``D:/_PROYECTOS_DESARROLLO/25128 SI...``):
        Pasar ``portal_mode="Primary"`` como string falla con
        ``"Expected an Enum with a '_value_' attribute"``. El wrapper
        de Siemens espera una instancia del Enum
        ``ts.PortalMode.Primary``, NO un string. La resolucion
        canonica es ``ts.PortalMode[portal_mode]`` (lookup por nombre
        del Enum), que devuelve la instancia correcta. Si el nombre
        no existe, capturamos ``KeyError`` y devolvemos un error
        legible con la lista de modos validos.

    Si ya estamos connected, el handler es **idempotente**: responde
    OK con el PID actual y ``already_connected=True``, sin re-attach.
    """
    global _portal

    if _state == _STATE_CONNECTED and _portal is not None:
        # Idempotente: ya hay un portal attached. No re-attach.
        try:
            pid = _portal.get_process_id()
        except Exception as e:  # noqa: BLE001
            log.warning(
                "get_process_id on existing portal failed (will not re-attach): %s",
                e,
            )
            pid = -1
        _emit_response(
            message_id,
            ok=True,
            result={"pid": pid, "already_connected": True},
        )
        return

    portal_mode = args.get("portal_mode", "Primary")
    if not isinstance(portal_mode, str) or not portal_mode:
        _emit_response(
            message_id,
            ok=False,
            error="portal_mode must be a non-empty string",
        )
        return

    _set_state(_STATE_CONNECTING)
    try:
        ts = _load_tia_wrapper()
    except RuntimeError as e:
        _set_state(_STATE_ERROR)
        _emit_response(message_id, ok=False, error=str(e))
        return

    # Resolver el string a la instancia de Enum que espera el wrapper
    # de Siemens. Pasar un string falla con
    # "Expected an Enum with a '_value_' attribute". El lookup por
    # nombre en el Enum (ts.Enums.PortalMode["WithGraphicalUserInterface"]
    # == ts.Enums.PortalMode.WithGraphicalUserInterface) es la forma
    # canonica en siemens_tia_scripting, segun el manual oficial
    # (seccion 2.4.2). El path es ``ts.Enums.PortalMode``, NO
    # ``ts.PortalMode`` (que no existe en el modulo).
    try:
        portal_mode_enum = ts.Enums.PortalMode[portal_mode]
    except (AttributeError, KeyError) as e:
        _portal = None
        _set_state(_STATE_ERROR)
        valid_modes = (
            [m.name for m in ts.Enums.PortalMode]
            if hasattr(ts, "Enums") and hasattr(ts.Enums, "PortalMode")
            else ["(PortalMode no disponible)"]
        )
        _emit_response(
            message_id,
            ok=False,
            error=(
                f"portal_mode '{portal_mode}' no se pudo resolver como "
                f"ts.Enums.PortalMode[...]: {e}. Modos validos: {valid_modes}"
            ),
        )
        return

    try:
        _portal = ts.attach_portal(portal_mode_enum)
        pid = _portal.get_process_id()
    except Exception as e:  # noqa: BLE001
        _portal = None
        _set_state(_STATE_ERROR)
        log.exception("attach_portal failed")
        _emit_response(
            message_id,
            ok=False,
            error=f"attach_portal failed: {e}",
        )
        return

    _set_state(_STATE_CONNECTED)
    _emit_response(
        message_id,
        ok=True,
        result={"pid": pid, "already_connected": False},
    )


def _handle_detach_portal(args: dict[str, Any], message_id: int) -> None:
    """Handler de ``detach_portal``: ``portal.detach()`` best-effort.

    Verificado contra el manual
    (``PLC_IE_61131_GREENFIELD.md`` seccion 0.1):
      - ``portal.detach()`` libera el RCW. **NO** cierra TIA Portal.

    **Idempotente**: si ya esta detached, responde OK igual.

    **Best-effort**: si el detach falla (p.ej. TIA ya se cerro y el
    RCW es invalido), loggeamos el error y seguimos. El objetivo del
    detach es liberar el RCW; si ya esta liberado, el detach fallara
    pero eso es exactamente lo que queremos.
    """
    global _portal

    if _portal is None:
        # Ya detached. Idempotente.
        _set_state(_STATE_IDLE)
        _emit_response(
            message_id,
            ok=True,
            result={"detached": True, "already_detached": True},
        )
        return

    try:
        _portal.detach()
    except Exception as e:  # noqa: BLE001
        # Best-effort: log y sigue. Ver docstring.
        log.warning("portal.detach() failed (best-effort): %s", e)
    finally:
        _portal = None
        _set_state(_STATE_IDLE)

    _emit_response(
        message_id,
        ok=True,
        result={"detached": True, "already_detached": False},
    )


def _handle_list_plcs(args: dict[str, Any], message_id: int) -> None:
    """Handler de ``list_plcs``: lista los PLCs del proyecto activo.

    **TODO**: no conozco la API exacta de TIA Openness V1.2.1 para
    listar los PLCs del proyecto activo. Candidatos a investigar:
      - ``project.get_plcs()`` (probable, patron mas comun en Openness)
      - ``portal.get_active_project().get_plcs()`` (alternativa)
      - Iterar ``project.get_device_tree().get_plcs()`` (legacy)

    Cada PLC deberia mapearse a un dict de primitivos antes de emitir,
    p.ej. ``{"name": str, "type_name": str, "ip_address": str, ...}``.

    Mientras esta sin implementar, el comando devuelve un error claro
    en vez de inventar la firma. **El worker NO se cae** ante comandos
    no implementados (regla de Fase 1): un fallo aqui es un
    ``ok=False`` con mensaje legible, no un crash.

    Aketza validara contra S7-1500 real y ajustaremos la firma.
    """
    if _state != _STATE_CONNECTED or _portal is None:
        _emit_response(
            message_id,
            ok=False,
            error="Not connected. Call attach_portal first.",
        )
        return

    # TODO: implementar la API real de TIA Openness V1.2.1.
    # Firma esperada (a confirmar por Aketza con S7-1500):
    #   project = _portal.get_active_project()  # o project.attached_projects[0]
    #   plcs_native = project.get_plcs()  # coleccion nativa .NET
    #   plcs_mapped = [_plc_to_dict(p) for p in plcs_native]
    #   _emit_response(message_id, ok=True, result=plcs_mapped)
    # donde ``_plc_to_dict`` mapea nombre, tipo, IP, etc. a primitivos.
    _emit_response(
        message_id,
        ok=False,
        error=(
            "TODO: list_plcs not implemented. Requires TIA Openness V1.2.1 "
            "API (candidates: project.get_plcs() or "
            "portal.get_active_project().get_plcs()). "
            "Aketza will validate against S7-1500 real and we'll "
            "adjust the signature."
        ),
    )


def _handle_ping(args: dict[str, Any], message_id: int) -> None:
    """Handler de ``ping``: ``portal.get_process_id()``.

    Usado por el heartbeat externo y por la logica de reconexion
    del bridge: si el operario cierra TIA Portal a mano sin hacer
    detach, el siguiente ping fallara y el bridge puede decidir
    re-attachear o propagar el error.

    Si no estamos connected, devolvemos error claro.
    """
    if _state != _STATE_CONNECTED or _portal is None:
        _emit_response(
            message_id,
            ok=False,
            error="Not connected. Call attach_portal first.",
        )
        return
    try:
        pid = _portal.get_process_id()
    except Exception as e:  # noqa: BLE001
        log.exception("get_process_id failed (portal may have died)")
        _emit_response(
            message_id,
            ok=False,
            error=f"ping failed: {e}",
        )
        return
    _emit_response(message_id, ok=True, result={"pid": pid})


def _handle_get_project_info(args: dict[str, Any], message_id: int) -> None:
    """Handler de ``get_project_info``: propiedades del proyecto activo.

    **TODO**: mismo caso que ``list_plcs``. Candidatos:
      - ``project.get_property(name="Name")``
      - ``project.get_property(name="Path")``
      - ``project.get_property(name="Author")``
      - etc.

    Mapeo esperado: ``{"name": str, "path": str, "author": str, ...}``.

    Mientras esta sin implementar, devuelve error claro.
    """
    if _state != _STATE_CONNECTED or _portal is None:
        _emit_response(
            message_id,
            ok=False,
            error="Not connected. Call attach_portal first.",
        )
        return

    # TODO: implementar la API real. Ver docstring.
    # Firma esperada:
    #   project = _portal.get_active_project()
    #   info = {
    #       "name": project.get_property(name="Name"),
    #       "path": project.get_property(name="Path"),
    #       "author": project.get_property(name="Author"),
    #   }
    #   _emit_response(message_id, ok=True, result=info)
    _emit_response(
        message_id,
        ok=False,
        error=(
            "TODO: get_project_info not implemented. Requires TIA Openness "
            "V1.2.1 API (candidates: project.get_property(name=...)). "
            "Aketza will validate against S7-1500 real."
        ),
    )


# ════════════════════════════════════════════════════════════════════════
#  Cleanup
# ════════════════════════════════════════════════════════════════════════


def _cleanup_on_exit() -> None:
    """Cleanup best-effort al salir del loop (exit, EOF, o senal).

    Objetivo: liberar el RCW de TIA. Con el, el .pyd de Siemens
    (~200 MB) se descarga cuando el proceso del worker termina.

    **NO** garantiza que TIA Portal se cierre: ``detach()`` solo
    libera el RCW desde nuestro lado, no mata el proceso de TIA
    (``PLC_IE_61131_GREENFIELD.md`` seccion 0.1).
    """
    global _portal
    if _portal is not None:
        try:
            _portal.detach()
        except Exception as e:  # noqa: BLE001
            log.warning("Cleanup: detach failed (best-effort): %s", e)
        finally:
            _portal = None
    _set_state(_STATE_IDLE)


# ════════════════════════════════════════════════════════════════════════
#  Loop principal
# ════════════════════════════════════════════════════════════════════════


def main() -> None:
    """Loop principal del worker. Lee JSON de stdin, dispatcha a handlers.

    El loop termina cuando:
      - Se recibe un comando ``exit``.
      - Llega EOF a stdin (el padre cierra el pipe).
      - Una excepcion no manejada rompe el loop (logged a stderr).
      - Llega KeyboardInterrupt (Ctrl+C en el subproceso).

    Convencion del protocolo (ver docstring del modulo):
      - stdin: un JSON por linea.
      - stdout: un JSON por linea.
      - stderr: logs libres, NUNCA JSON.
    """
    # Configurar logging basico a stderr. ``force=True`` para sobrescribir
    # cualquier config previa (importante en frozen, donde PyInstaller
    # puede haber configurado logging a stdout).
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )
    log.info(
        "worker_tia starting (pid=%d, frozen=%s, python=%s)",
        os.getpid(),
        getattr(sys, "frozen", False),
        sys.version.split()[0],
    )
    log.info("initial state: %s", _state)

    # Lanzar el heartbeat daemon. No bloquea el loop principal.
    # ``daemon=True`` asegura que muere con el proceso aunque el loop
    # este bloqueado en ``sys.stdin.readline()``.
    hb_thread = threading.Thread(
        target=_heartbeat_loop,
        daemon=True,
        name="worker_heartbeat",
    )
    hb_thread.start()

    try:
        # Loop principal: lee JSON linea a linea de stdin.
        # ``sys.stdin`` es un file object bloqueante. Usamos ``for`` que
        # itera linea a linea; el padre envia un JSON por linea terminado
        # en ``\n`` (ver ``worker_bridge._send``).
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                # Linea vacia: ignoramos. Util si el padre usa ``flush``
                # tras cada comando.
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError as e:
                # Comando malformado. Respondemos con id=None (el padre
                # lo descartara o lo loggeara). **NO** morimos.
                log.warning(
                    "Invalid JSON from parent: %s (line=%r)", e, line[:200]
                )
                _emit_response(None, ok=False, error=f"Invalid JSON: {e}")
                continue

            if not isinstance(msg, dict):
                _emit_response(
                    None,
                    ok=False,
                    error="Message must be a JSON object",
                )
                continue

            message_id = msg.get("id")
            cmd = msg.get("cmd")
            args = msg.get("args", {})

            if not isinstance(cmd, str):
                _emit_response(
                    message_id,
                    ok=False,
                    error="Missing or invalid 'cmd'",
                )
                continue
            if not isinstance(args, dict):
                _emit_response(
                    message_id,
                    ok=False,
                    error="'args' must be a JSON object",
                )
                continue

            # ── Dispatch inline ────────────────────────────────────
            # NO usamos un registry: algunos handlers reasignan
            # ``_portal`` (variable del modulo) y seria fragil con un
            # registry que pierde la referencia. Inline es mas directo
            # y permite ver todo el flujo en un solo sitio.
            try:
                if cmd == "attach_portal":
                    _handle_attach_portal(args, message_id)
                elif cmd == "detach_portal":
                    _handle_detach_portal(args, message_id)
                elif cmd == "list_plcs":
                    _handle_list_plcs(args, message_id)
                elif cmd == "ping":
                    _handle_ping(args, message_id)
                elif cmd == "get_project_info":
                    _handle_get_project_info(args, message_id)
                elif cmd == "exit":
                    # El padre quiere que salgamos. NO respondemos:
                    # el padre ya esta cerrando el pipe.
                    log.info("Received 'exit', shutting down")
                    break
                else:
                    # Comando desconocido. **NO** morimos: el worker
                    # sigue vivo para futuros comandos validos.
                    log.warning("Unknown command: %s", cmd)
                    _emit_response(
                        message_id,
                        ok=False,
                        error=f"Unknown command: {cmd}",
                    )
            except Exception as e:  # noqa: BLE001
                # Cualquier excepcion no manejada en un handler. La
                # capturamos aqui para que el loop siga vivo
                # (``PLC_IE_61131_GREENFIELD.md`` regla de Fase 1:
                # el worker no se cae ante errores internos).
                log.exception("Unhandled error in command %s", cmd)
                _emit_response(
                    message_id,
                    ok=False,
                    error=f"Internal error: {e}",
                )
    except KeyboardInterrupt:
        # Ctrl+C en el subproceso (raro en produccion, pero posible
        # en debug). Cleanup normal.
        log.info("KeyboardInterrupt, shutting down")
    except Exception as e:  # noqa: BLE001
        # Excepcion a nivel de loop (no de handler). Loggeamos y
        # dejamos que el cleanup corra en el finally.
        log.exception("Fatal error in main loop: %s", e)
    finally:
        _cleanup_on_exit()
        log.info("worker_tia exited (pid=%d)", os.getpid())


# ════════════════════════════════════════════════════════════════════════
#  Entry point
# ════════════════════════════════════════════════════════════════════════


if __name__ == "__main__":
    main()
