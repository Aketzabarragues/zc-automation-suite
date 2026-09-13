"""
core.infrastructure.tia_loop — subsistema TIA Portal (OB1-friendly).

Antes: tia_client.py (1250 lineas). Ahora este archivo contiene todo
el subsistema TIA Portal autocontenido:

  - Carga del wrapper .NET (siemens_tia_scripting.pyd) al arrancar.
  - State machine de 6 estados.
  - Hilo dedicado ("tia-loop") que drena la cola de commands.
  - 24 commands core (lifecycle + inspection + mutation).
  - API publica: submit_and_wait / submit_batch / state / start / stop.

El wrapper .NET vive y se usa SOLO desde el tia-loop. El main loop
(OB1) y los FBs NO tocan el wrapper directamente: pasan por la API
publica (submit_and_wait, etc.) que encola en el tia-loop.

State machine (6 estados):
  IDLE        portal cerrado
  ATTACHING   ejecutando attach_portal / open_new_portal
  CONNECTED   portal vivo, listo para commands
  BUSY        command en curso
  DETACHING   ejecutando detach_portal
  ERROR       fallo irrecuperable

Threading model:
  - main-loop (OB1): NO toca el wrapper .NET.
  - tia-loop: UNICO dueno del wrapper, drena _cmd_queue.
  - Flask thread: encola via submit_and_wait (bloquea con timeout).
  - Single thread para Openness: el RCW .NET no es thread-safe.
"""
from __future__ import annotations

import itertools
import logging
import os
import queue
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from core.models.bloque_plc import BloquePLC

logger = logging.getLogger(__name__)


# Estados del subsistema TIA (expuestos publicamente para que el router
# Flask y la SPA consulten /api/v1/tia/connection sin tocar el wrapper).
STATE_IDLE = "idle"
STATE_ATTACHING = "attaching"
STATE_CONNECTED = "connected"
STATE_BUSY = "busy"
STATE_DETACHING = "detaching"
STATE_ERROR = "error"

# Sentinela para que stop_tia_loop() ordene al hilo salir de forma
# limpia (queue.put) sin usar un flag externo que podria racear.
_SENTINEL_STOP: Any = object()


def _next_request_id() -> int:
    """Generador thread-safe de IDs unicos para correlacionar request/response."""
    return next(_REQ_COUNTER)


_REQ_COUNTER = itertools.count(1)


# ---------------------------------------------------------------------------
# Helpers internos (4.1.2a). Migrados desde worker_tia.py sin cambios
# funcionales: extraen y validan el proyecto / PLC / nombre de PLC de
# forma defensiva frente a errores del wrapper .NET.
# ---------------------------------------------------------------------------
def _get_active_project(portal: Any) -> Any:
    """Extrae y valida el proyecto activo del portal.

    Levanta RuntimeError si no hay proyecto abierto.
    """
    project = portal.get_project()
    if not project:
        raise RuntimeError(
            "No hay ningun proyecto abierto en TIA Portal. "
            "Ejecuta 'open_project' primero."
        )
    return project


def _safe_get_plc_name(plc: Any) -> str | None:
    """Lee el nombre de un Plc tolerando errores de encoding.

    Algunos PLCs tienen nombres no-ASCII (Latin-1, acentos) que hacen
    fallar la conversion .NET -> Python str. Devolvemos None en ese
    caso (la comparacion falla y se trata como "no es la que buscamos").
    """
    try:
        return plc.get_name()
    except UnicodeDecodeError:
        return None


def _find_plc(project: Any, plc_name: str) -> Any:
    """Resuelve el objeto Plc por nombre dentro del proyecto activo.

    Levanta ValueError si plc_name vacio; RuntimeError si no existe.
    """
    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")

    for plc in project.get_plcs():
        if _safe_get_plc_name(plc) == plc_name:
            return plc

    raise RuntimeError(
        f"No se encontro ningun PLC con el nombre '{plc_name}' "
        "en el proyecto activo."
    )

# Firma de un handler: recibe args dict, retorna dict serializable.
# Los handlers acceden al wrapper via tia_client.wrapper.
HandlerSig = Callable[[dict], dict]


# Handler signature v2 (Fase 4 / paso 4.1.2): recibe (args, tia_client).
# El dispatcher pasa `self` como segundo argumento para que los handlers
# puedan acceder al wrapper (.NET portal) y al modulo siemens sin
# depender de un singleton global (testable sin monkey-patching).
HandlerSig = Callable[[dict, "SyncTIAClient"], dict]


class SyncTIAClient:
    """Cliente + state machine + hilo del subsistema TIA Portal.

    API principal:
      - submit_and_wait / submit_batch: encolar commands y obtener respuesta.
      - start_tia_loop / stop_tia_loop: arrancar/parar el hilo dedicado.
      - state: propiedad de solo lectura (IDLE, CONNECTED, BUSY, ...).

    Single thread para Openness: el tia-loop es el UNICO dueno del
    wrapper .NET. El resto de la app pasa por la cola.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, HandlerSig] = {}
        # Wrapper + modulo siemens. Se rellenan al start_tia_loop()
        # (carga real) o antes (mock en tests via attach_wrapper/attach_ts).
        self._wrapper: Any = None
        self._ts: Any = None
        # State machine: 6 estados. Ver constantes STATE_* arriba.
        self._state: str = STATE_IDLE
        self._state_lock = threading.Lock()
        # Cola de commands FIFO. Cada item:
        #   (req_id, command_name, args, response_queue)
        # response_queue es None para fire-and-forget o queue.Queue
        # para request/response.
        self._cmd_queue: queue.Queue = queue.Queue()
        # Hilo dedicado.
        self._tia_thread: threading.Thread | None = None
        self._tia_stop = threading.Event()

    # ----------------------------------------------------------- state (lectura)
    @property
    def state(self) -> str:
        """Estado actual del subsistema TIA (thread-safe)."""
        with self._state_lock:
            return self._state

    def _set_state(self, new_state: str) -> None:
        """Transiciona el estado (solo el tia-loop debe llamarlo)."""
        with self._state_lock:
            old = self._state
            self._state = new_state
        if old != new_state:
            logger.info("TIA state: %s -> %s", old, new_state)

    # ----------------------------------------------------------- API publica
    def register_command(self, name: str, handler: HandlerSig) -> None:
        """Registra un handler para `name`. Llamado por areas al import."""
        if name in self._handlers:
            raise ValueError(f"command already registered: {name}")
        self._handlers[name] = handler
        logger.debug("registered command: %s", name)

    def dispatch(self, command: str, args: dict | None = None) -> dict:
        """Dispatcher sync. Solo llamado desde el tia-loop (interno).

        Shape de retorno: {"ok": True, "result": <dict>} o
        {"ok": False, "error": "<msg>"}.

        El handler recibe (args, self) para acceder a wrapper/ts sin
        depender del singleton global.
        """
        handler = self._handlers.get(command)
        if handler is None:
            return {"ok": False, "error": f"unknown_command:{command}"}
        try:
            return {"ok": True, "result": handler(args or {}, self)}
        except Exception as exc:  # noqa: BLE001 - captura cualquier fallo de handler
            logger.exception("dispatch failed: %s", command)
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def submit_and_wait(
        self, command: str, args: dict | None = None, timeout: float = 30.0,
    ) -> dict:
        """Encola un command y BLOQUEA hasta tener respuesta (con timeout).

        Pensado para que el hilo Flask (o el main loop, si necesita
        respuesta sincrona) pida un resultado. El tia-loop procesa el
        command y pone el dict resultante en la response_queue interna.

        Returns:
            ``{"ok": True, "result": <dict>}`` o
            ``{"ok": False, "error": "<msg>"}``.

        Raises:
            TimeoutError: si el tia-loop no responde en ``timeout`` segundos.
            RuntimeError: si el tia-loop no esta corriendo.
        """
        if self._tia_thread is None or not self._tia_thread.is_alive():
            raise RuntimeError(
                "tia-loop no esta corriendo. Llama a start_tia_loop() primero."
            )
        resp_q: queue.Queue = queue.Queue(maxsize=1)
        item = (_next_request_id(), command, args or {}, resp_q)
        self._cmd_queue.put(item)
        try:
            return resp_q.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(
                f"submit_and_wait({command!r}) supero el timeout de {timeout}s."
            )

    def submit_batch(
        self, items: list[tuple[str, dict]], timeout: float = 60.0,
    ) -> list[dict]:
        """Encola varios commands en lote y espera a todos.

        Args:
            items: lista de ``(command_name, args)``.
            timeout: timeout total (suma de todos los commands).

        Returns:
            Lista de respuestas en el mismo orden que ``items``.
        """
        if self._tia_thread is None or not self._tia_thread.is_alive():
            raise RuntimeError("tia-loop no esta corriendo.")
        resp_qs = [queue.Queue(maxsize=1) for _ in items]
        for (name, args), q in zip(items, resp_qs):
            self._cmd_queue.put((_next_request_id(), name, args, q))
        results = []
        for q in resp_qs:
            try:
                results.append(q.get(timeout=timeout))
            except queue.Empty:
                results.append({"ok": False, "error": "timeout"})
        return results

    def start_tia_loop(self) -> threading.Thread:
        """Arranca el hilo dedicado tia-loop (idempotente).

        Si no hay modulo siemens attached (caso normal al arrancar la
        app), lo carga via ``tia_loader.load_siemenstia()``. Si la
        carga falla, levanta ``RuntimeError`` con mensaje accionable.

        Returns:
            El ``Thread`` arrancado (daemon=True).
        """
        if self._tia_thread is not None and self._tia_thread.is_alive():
            logger.debug("start_tia_loop: ya estaba corriendo; no-op.")
            return self._tia_thread
        if self._ts is None:
            # Carga lazy del wrapper .NET. Solo la primera vez.
            try:
                from core.infrastructure.tia_loader import load_siemenstia
                ts_module, _wrapper_module = load_siemenstia()
            except (FileNotFoundError, RuntimeError) as exc:
                logger.error("No se pudo cargar el wrapper TIA: %s", exc)
                raise
            self.attach_ts(ts_module)
        self._tia_stop.clear()
        self._set_state(STATE_IDLE)
        thread = threading.Thread(
            target=_tia_loop_main,
            args=(self, self._tia_stop),
            name="tia-loop",
            daemon=True,
        )
        thread.start()
        self._tia_thread = thread
        logger.info("tia-loop arrancado.")
        return thread

    def stop_tia_loop(self, timeout: float = 5.0) -> None:
        """Senala parada al tia-loop y espera a que termine."""
        if self._tia_thread is None:
            return
        self._cmd_queue.put(_SENTINEL_STOP)
        self._tia_stop.set()
        self._tia_thread.join(timeout=timeout)
        if self._tia_thread.is_alive():
            logger.warning("tia-loop no termino en %.1fs; se abandona.", timeout)
        else:
            logger.info("tia-loop terminado.")
        self._tia_thread = None

    # --------------------------------------------------------------- helpers
    def attach_wrapper(self, wrapper: Any) -> None:
        """Adjunta el portal .NET (mock en tests, .pyd real en main).

        Solo el tia-loop debe llamarlo (o tests que mockean).
        """
        self._wrapper = wrapper

    def attach_ts(self, ts_module: Any) -> None:
        """Adjunta el modulo ``siemens_tia_scripting`` (mock o real).

        Lo usan handlers que invocan ``ts.open_portal(...)`` o
        ``ts.Enums.PortalMode.X``.
        """
        self._ts = ts_module

    @property
    def wrapper(self) -> Any:
        """Accessor del wrapper siemens_tia_scripting.

        Acceso single-threaded: solo el tia-loop debe llamar metodos
        sobre el objeto retornado (los RCW .NET no son thread-safe).
        """
        return self._wrapper

    @property
    def ts(self) -> Any:
        """Accessor del modulo ``siemens_tia_scripting``.

        Idem wrapper: solo el tia-loop debe llamar funciones sobre el
        modulo retornado.
        """
        return self._ts

    def has_command(self, name: str) -> bool:
        return name in self._handlers

    def registered_commands(self) -> list[str]:
        return sorted(self._handlers.keys())


# ---------------------------------------------------------------------------
# Handlers migrados desde worker_tia.py (Fase 4 / paso 4.1.2a1).
# Lifecycle del proyecto: open_new_portal / open_project / save_project /
# close_project. Sin cambios funcionales, solo adaptacion de signature:
# (portal, ts, args) -> (args, tia_client). Acceso a portal/ts via
# tia_client.wrapper / tia_client.ts (acceso single-threaded OB1).
# ---------------------------------------------------------------------------
def _h_attach_portal(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Abre un portal TIA Portal NUEVO y lo attach al client (persistente).

    OB1 model: tras este comando, ``tia_client.wrapper`` queda attached
    y los siguientes dispatch (list_plcs, get_project_info, sync disp,
    compile PLC, etc.) usan el mismo portal sin reconectar. El portal
    vive hasta que se llame ``detach_portal`` (o se reemplace).

    Args:
        args: opcional ``portal_mode`` (default ``AnyUserInterface``).
              Cualquier otro arg depende del wrapper.
    """
    ts = tia_client.ts
    if ts is None:
        raise RuntimeError("Modulo siemens_tia_scripting no attached.")
    if tia_client.wrapper is not None:
        # Idempotente: ya hay portal attached.
        return {
            "attached": True,
            "already_attached": True,
            "state": "connected",
        }
    portal_mode_str = args.get("portal_mode", "AnyUserInterface")
    portal_mode = getattr(ts.Enums.PortalMode, portal_mode_str, None)
    if portal_mode is None:
        raise ValueError(
            f"portal_mode desconocido: '{portal_mode_str}'. "
            f"Validos: {[m for m in dir(ts.Enums.PortalMode) if not m.startswith('_')]}"
        )
    new_portal = ts.open_portal(portal_mode=portal_mode)
    if new_portal is None:
        raise RuntimeError("Fallo critico: open_portal retorno None.")
    tia_client.attach_wrapper(new_portal)
    logger.info("Portal TIA attached (mode=%s)", portal_mode_str)
    return {
        "attached": True,
        "already_attached": False,
        "state": "connected",
    }


def _h_detach_portal(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Detach del portal TIA Portal (lo cierra).

    En OB1 el detach es ``tia_client.attach_wrapper(None)``: los
    siguientes dispatch daran 'No portal attached' hasta un nuevo attach.
    """
    tia_client.attach_wrapper(None)
    logger.info("Portal TIA detached.")
    return {"attached": False, "state": "disconnected"}


def _h_open_new_portal(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Cold start: lanza TIA Portal, abre proyecto Y lo attach.

    Combina ``attach_portal`` + ``open_project`` en un solo paso.
    Util para arrancar desde cero (operario abre proyecto nuevo).
    """
    ts = tia_client.ts
    if ts is None:
        raise RuntimeError("Modulo siemens_tia_scripting no attached.")
    project_file_path: str = args.get("project_file_path", "")
    if not project_file_path:
        raise ValueError(
            "open_new_portal requiere el argumento 'project_file_path'."
        )
    if not os.path.isfile(project_file_path):
        raise RuntimeError(
            f"El archivo de proyecto no existe: '{project_file_path}'."
        )
    # Si ya hay portal attached, lo usamos; si no, abrimos uno nuevo.
    portal = tia_client.wrapper
    if portal is None:
        portal = ts.open_portal(portal_mode=ts.Enums.PortalMode.AnyUserInterface)
        if portal is None:
            raise RuntimeError("Fallo critico: open_portal retorno None.")
        tia_client.attach_wrapper(portal)
    portal.open_project(project_file_path=project_file_path)
    return {
        "opened": True,
        "project_file_path": project_file_path,
        "state": "connected",
    }


def _h_open_project(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Abre un proyecto TIA Portal desde una ruta absoluta.

    PRECONDICION: el portal ya esta conectado (vía attach_portal o
    open_new_portal). Para abrir proyecto desde cero (cold start),
    usar ``open_new_portal``.
    """
    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project_file_path: str = args.get("project_file_path", "")
    if not project_file_path:
        raise ValueError("Se requiere el argumento 'project_file_path'.")
    if not os.path.isfile(project_file_path):
        raise RuntimeError(
            f"El archivo de proyecto no existe: '{project_file_path}'."
        )
    portal.open_project(project_file_path=project_file_path)
    return {"opened": True, "project_file_path": project_file_path}


def _h_save_project(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Guarda los cambios pendientes del proyecto activo."""
    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    project.save()
    return {"saved": True}


def _h_close_project(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Cierra el proyecto activo.

    ADVERTENCIA: project.close() destruye permanentemente todos los
    cambios no guardados. El caller es responsable de haber invocado
    save() antes si la persistencia era necesaria.
    """
    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    project.close()
    return {"closed": True}


def _h_ping(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Verifica si la conexion con TIA Portal sigue activa.

    Retorna ``{"pid": <int>}`` si TIA responde. Levanta RuntimeError si
    no hay portal attached. Deja propagar excepciones COM/RPC (TIA
    cerrado) para que el dispatcher las reporte como
    ``{"ok": False, "error": "COMError: ..."}``.

    Implementacion: ``portal.get_process_id()`` (manual Siemens §2.5.1).
    """
    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError("No hay portal attached")
    pid = portal.get_process_id()
    return {"pid": int(pid)}


def _h_list_blocks(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Lista los nombres de los bloques de programa de un PLC especifico.

    Args:
        plc_name (str): nombre del PLC objetivo.
        folder_path (str, opcional): ruta de carpeta; "" = raiz del PLC.
            Coercion defensiva: el wrapper .NET rechaza None, forzamos "".
    """
    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    plc_name: str = args.get("plc_name", "")
    folder_path: str = args.get("folder_path") or ""

    target_plc = _find_plc(project, plc_name)
    blocks = target_plc.get_program_blocks(folder_path=folder_path)
    names = [block.get_name() for block in blocks]
    return {"blocks": names, "plc_name": plc_name}


def _safe_short_designation(plc: Any) -> str | None:
    """Lee ``ShortDesignation`` del PLC de forma defensiva.

    Cubre 3 casos:
      1. La property no existe en este modelo de PLC.
      2. La property existe pero devuelve None o string vacio.
      3. El read lanza (COM, PermissionDenied, etc.).

    Devuelve None en cualquiera -> la SPA pinta "Modelo: -" cuando es None.

    IMPORTANTE: pasar nombre como named arg (name=). Los metodos .NET
    sobrecargados resuelven mal la overload con positional (ver §list_plcs).
    """
    getter = getattr(plc, "get_property", None)
    if getter is None:
        return None
    try:
        value = getter(name="ShortDesignation")
    except Exception:
        return None
    if value is None:
        return None
    try:
        s = str(value).strip()
    except Exception:
        return None
    return s if s else None


def _h_list_plcs(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Lista los PLCs del proyecto activo con metadatos para la SPA.

    Returns:
        ``{"plcs": [{"name": str, "short_designation": str | None}, ...]}``.
    """
    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    plcs = project.get_plcs()
    result = [
        {"name": plc.get_name(), "short_designation": _safe_short_designation(plc)}
        for plc in plcs
    ]
    return {"plcs": result}


def _h_get_project_info(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Devuelve propiedades basicas del proyecto TIA activo como primitivos.

    Lee un set acotado de propiedades del proyecto que son utiles para
    que la SPA muestre al operario a que proyecto esta enganchado. NO
    devuelve objetos nativos TIA (siempre primitivos, AGENTS.md §Datos).

    Si una property lanza al leerla (PermissionDenied, EncodingError),
    se omite del payload en vez de tumbar el handler: la SPA recibe un
    dict parcial y renderiza solo lo disponible.

    Returns:
        ``dict`` con al menos ``name``. Opcionalmente: ``path``,
        ``author``, ``creation_time``, ``last_modified``,
        ``last_modified_by``, ``version``. Datetimes .NET -> ISO 8601.
    """
    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)

    def _safe_get(name: str) -> Any:
        try:
            return project.get_property(name=name)
        except Exception:
            return None

    result: dict[str, Any] = {"name": _safe_get("Name")}

    for prop_name, out_key in (
        ("Path", "path"),
        ("Author", "author"),
        ("CreationTime", "creation_time"),
        ("LastModified", "last_modified"),
        ("LastModifiedBy", "last_modified_by"),
        ("Version", "version"),
    ):
        value = _safe_get(prop_name)
        if value is None:
            continue
        # Normalizar a primitivo: datetime/DateTime .NET -> ISO 8601 string.
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        result[out_key] = value

    return result


# ---------------------------------------------------------------------------
# Helpers adicionales (4.1.2a5a) para scan_blocks. Leen nombre / ruta /
# nombre de tabla tolerando errores del wrapper .NET (UnicodeDecodeError,
# COM transients).
# ---------------------------------------------------------------------------
def _safe_get_block_name(block: Any) -> str | None:
    """Lee el nombre de un bloque tolerando UnicodeDecodeError y COM."""
    try:
        if hasattr(block, "get_name"):
            return block.get_name()
        if hasattr(block, "Name"):
            return block.Name
    except UnicodeDecodeError:
        return None
    except Exception:
        return None
    return None


def _safe_get_block_path(block: Any) -> str:
    """Lee la ruta jerarquica de un bloque tolerando COM exceptions.

    Devuelve "" si falla (el bloque sigue siendo cacheado con su nombre).
    """
    try:
        if hasattr(block, "get_path"):
            return str(block.get_path())
        if hasattr(block, "Path"):
            return str(block.Path)
    except Exception:
        return ""
    return ""


def _safe_get_table_name(table: Any) -> str | None:
    """Lee el nombre de una PlcTagTable tolerando UnicodeDecodeError."""
    try:
        return table.get_name()
    except UnicodeDecodeError:
        return None
    except Exception:
        return None


def _scan_block_group_recursive(group_or_blocks: Any) -> list[dict]:
    """Recorre recursivamente un grupo o coleccion de bloques -> DTOs dict.

    Estrategia (espejo del legacy scanner._scan_group_recursive):
      1. Extrae la lista plana via get_blocks() (preferred) o .Blocks.
         Si ninguno, intenta __iter__.
      2. Cada bloque: nombre, ruta, tipo derivado, numero del nombre.
      3. Recurre en sub-grupos via get_groups() / .Groups.

    Returns:
        Lista de dicts con shape BloquePLC.to_dict().
        Bloques con nombre inaccesible (UnicodeDecodeError) se omiten.
    """
    blocks_iter: list = []
    try:
        if hasattr(group_or_blocks, "get_blocks"):
            blocks_iter = list(group_or_blocks.get_blocks() or [])
        elif hasattr(group_or_blocks, "Blocks"):
            blocks_iter = list(group_or_blocks.Blocks or [])
        elif hasattr(group_or_blocks, "__iter__"):
            blocks_iter = list(group_or_blocks)
    except Exception:
        blocks_iter = []

    out: list[dict] = []
    for block in blocks_iter:
        nombre = _safe_get_block_name(block)
        if not nombre:
            continue
        ruta = _safe_get_block_path(block)
        tipo = BloquePLC.detect_tipo(nombre)
        match = re.match(r"^(DB|FB|FC|OB|UDT)(\d+)", nombre, re.IGNORECASE)
        numero = int(match.group(2)) if match else 0
        out.append(
            BloquePLC(
                nombre=str(nombre),
                numero=numero,
                tipo=tipo,
                ruta=ruta,
            ).to_dict()
        )

    groups: list = []
    try:
        if hasattr(group_or_blocks, "get_groups"):
            groups = list(group_or_blocks.get_groups() or [])
        elif hasattr(group_or_blocks, "Groups"):
            groups = list(group_or_blocks.Groups or [])
    except Exception:
        groups = []

    for sub in groups:
        out.extend(_scan_block_group_recursive(sub))

    return out


def _h_scan_blocks(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Escanea recursivamente TODOS los bloques, tag tables y UDTs de un PLC.

    Returns:
        ``{
            "plc_name":   str,
            "blocks":     [{nombre, numero, tipo, ruta}, ...],
            "tag_tables": [{nombre, numero, tipo, ruta}, ...],
            "udts":       [{nombre, numero, tipo, ruta}, ...],
            "scanned_at": str (ISO 8601 UTC),
        }``

    Raises:
        ValueError: si ``plc_name`` falta o esta vacio.
        RuntimeError: si no hay proyecto activo o el PLC no existe.
    """
    plc_name: str = args.get("plc_name", "")
    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)

    # Bloques: recorrido recursivo.
    program_blocks = target_plc.get_program_blocks()
    blocks_list = _scan_block_group_recursive(program_blocks)

    # Tag tables: defensivo; si TIA falla, log warning y seguimos.
    tag_tables_objs: list = []
    try:
        tag_tables_objs = list(target_plc.get_plc_tag_tables() or [])
    except Exception as exc:
        logger.warning(
            "No se pudieron listar PlcTagTables del PLC '%s': %s",
            plc_name, exc,
        )

    tag_tables_list: list[dict] = []
    for table in tag_tables_objs:
        nombre = _safe_get_table_name(table)
        if not nombre:
            continue
        ruta = _safe_get_block_path(table)
        tag_tables_list.append(
            BloquePLC(
                nombre=str(nombre),
                numero=0,
                tipo="OTHER",
                ruta=ruta,
            ).to_dict()
        )

    # UDTs: coleccion distinta de program_blocks. Defensivo: si TIA no
    # expone get_user_data_types() o lanza, devolvemos udts=[] y dejamos
    # que blocks/tag_tables sigan devolviendo su contenido.
    udts_list: list[dict] = []
    try:
        user_data_types = target_plc.get_user_data_types()
        udts_list = _scan_block_group_recursive(user_data_types)
    except Exception as exc:
        logger.warning(
            "No se pudieron listar User Data Types del PLC '%s': %s",
            plc_name, exc,
        )
        udts_list = []

    return {
        "plc_name": plc_name,
        "blocks": blocks_list,
        "tag_tables": tag_tables_list,
        "udts": udts_list,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }


def _h_compile_plc(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Compila el software del PLC y retorna el booleano nativo de Siemens.

    Semantica documentada (API V1.2.1, seccion 2.2.11):
      - True  -> La compilacion TIENE errores.
      - False -> La compilacion NO tiene errores (exito).

    Returns:
        ``{"had_errors": bool}``. La capa de presentacion (MCP/SPA)
        traduce este valor a un mensaje humano.
    """
    plc_name: str = args.get("plc_name", "")
    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    had_errors = bool(target_plc.compile_software())
    return {"had_errors": had_errors}


def _ensure_target_dir(target_dir: str) -> Path:
    """Valida que target_dir este presente y devuelve la ruta resuelta.

    Crea el directorio si no existe (parents=True). Usado por todos
    los handlers de export masivo (export_blocks_sd, export_udts_sd,
    export_plc_tags_xml).
    """
    if not target_dir:
        raise ValueError("Se requiere el argumento 'target_dir'.")
    target_path = Path(target_dir)
    target_path.mkdir(parents=True, exist_ok=True)
    return target_path


def _export_objects_sd(
    target_plc: Any,
    target_path: Path,
    collection_key: str,
) -> dict:
    """Exporta una coleccion de objetos TIA (Bloques o UDTs) a .s7dcl.

    Args:
        target_plc: PLC del que exportar.
        target_path: Path resuelto del directorio destino.
        collection_key: 'program_blocks' | 'user_data_types'.

    Returns:
        ``{"exported_to": str, "count": int}``.

    Nota de formato: TIA Portal V21 emite archivos .s7dcl (Simatic
    Source Documents) cuando se solicita ``export_format=SimaticSD``.
    El sufijo ``.s7dcl`` es canonico a partir de V17.
    """
    if collection_key == "program_blocks":
        objects = target_plc.get_program_blocks()
    elif collection_key == "user_data_types":
        objects = target_plc.get_user_data_types()
    else:
        raise ValueError(
            f"collection_key desconocido: '{collection_key}'. "
            "Use 'program_blocks' o 'user_data_types'."
        )

    count = 0
    for obj in objects:
        # El wrapper soporta coercion string->enum (TypeError previo:
        # "export_format must be an Enum or string"). Inyectamos literal
        # "SimaticSD" para evitar depender de ts.Enums.ExportFormats.
        # Manual V1.2.1, secciones 2.10.5 y 2.15.5.
        obj.export(
            target_directory_path=str(target_path),
            export_format="SimaticSD",
            keep_folder_structure=True,
        )
        count += 1

    return {"exported_to": str(target_path), "count": count}


def _h_export_blocks_sd(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Exporta los bloques de programa del PLC como .s7dcl."""
    plc_name: str = args.get("plc_name", "")
    target_dir: str = args.get("target_dir", "")

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    target_path = _ensure_target_dir(target_dir)
    return _export_objects_sd(target_plc, target_path, "program_blocks")


def _h_export_udts_sd(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Exporta los User Data Types del PLC como .s7dcl."""
    plc_name: str = args.get("plc_name", "")
    target_dir: str = args.get("target_dir", "")

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    target_path = _ensure_target_dir(target_dir)
    return _export_objects_sd(target_plc, target_path, "user_data_types")


def _h_export_plc_tags_xml(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Exporta las tablas de variables del PLC como XML SimaticML.

    Args:
        plc_name (str, requerido).
        target_dir (str, requerido).
        table_names (list[str], opcional): whitelist. Si se pasa y no es
            None, solo se exportan las tablas cuyo get_name() este en la
            lista. Si es None / se omite, se exportan TODAS las tablas.

    Returns:
        ``{"exported_to": str, "count": int}``.
    """
    plc_name: str = args.get("plc_name", "")
    target_dir: str = args.get("target_dir", "")
    target_table_names = args.get("table_names")

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    target_path = _ensure_target_dir(target_dir)

    tag_tables = target_plc.get_plc_tag_tables()
    count = 0
    for table in tag_tables:
        if target_table_names is not None:
            name = _safe_get_table_name(table)
            if name not in target_table_names:
                continue
        # Defensivo: wrapper no expone ExportFormats/ExportOptions en este
        # build. Segun manual V1.2.1 §2.10.5, ambos parametros son opcionales;
        # el wrapper C++ subyacente aplica defaults internos (SimaticML, None).
        table.export(
            target_directory_path=str(target_path),
            keep_folder_structure=True,
        )
        count += 1

    return {"exported_to": str(target_path), "count": count}


def _h_import_blocks_sd(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Importa bloques .s7dcl desde el disco al PLC (manual §2.2.23).

    Valida import_dir antes de invocar el metodo COM (TIA lanza excepcion
    grave si el dir no existe).

    Args:
        plc_name (str, requerido).
        import_dir (str, requerido): directorio con archivos .s7dcl.
        target_folder (str, opcional): carpeta destino en el PLC; "" = raiz.
            Coercion defensiva: el wrapper .NET no acepta None.
    """
    plc_name: str = args.get("plc_name", "")
    import_dir: str = args.get("import_dir", "")
    target_folder: str = args.get("target_folder") or ""

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not import_dir:
        raise ValueError("Se requiere el argumento 'import_dir'.")
    if not os.path.isdir(import_dir):
        raise RuntimeError(
            f"El directorio de importacion no existe o no es accesible: "
            f"'{import_dir}'."
        )

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    target_plc.import_blocks(
        import_root_directory=import_dir,
        target_folder_path=target_folder,
    )
    return {"imported_from": import_dir}


def _h_import_plc_tags_xml(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Importa PlcTagTables en formato XML al PLC (manual §2.2.24).

    Valida import_dir antes de invocar el metodo COM.
    """
    plc_name: str = args.get("plc_name", "")
    import_dir: str = args.get("import_dir", "")
    target_folder: str = args.get("target_folder") or ""

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not import_dir:
        raise ValueError("Se requiere el argumento 'import_dir'.")
    if not os.path.isdir(import_dir):
        raise RuntimeError(
            f"El directorio de importacion no existe o no es accesible: "
            f"'{import_dir}'."
        )

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    target_plc.import_plc_tags(
        import_root_directory=import_dir,
        target_folder_path=target_folder,
    )
    return {"imported_from": import_dir}


def _h_export_block(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Exporta un unico bloque de programa como SimaticSD. Manual §2.10.5."""
    plc_name: str = args.get("plc_name", "")
    block_name: str = args.get("block_name", "")
    target_dir: str = args.get("target_dir", "")

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not block_name:
        raise ValueError("Se requiere el argumento 'block_name'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    target_path = _ensure_target_dir(target_dir)

    blocks = target_plc.get_program_blocks()
    for block in blocks:
        # Defensivo: get_name puede lanzar UnicodeDecodeError; usamos helper.
        name = _safe_get_block_name(block)
        if name == block_name:
            block.export(
                target_directory_path=str(target_path),
                export_format="SimaticSD",
                keep_folder_structure=False,
            )
            return {"exported_to": str(target_path), "block_name": block_name}

    raise RuntimeError(
        f"Bloque '{block_name}' no encontrado en PLC '{plc_name}'."
    )


def _h_export_tag_table(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Exporta una unica PlcTagTable como XML SimaticML. Manual §2.10.5/§2.28.3."""
    plc_name: str = args.get("plc_name", "")
    table_name: str = args.get("table_name", "")
    target_dir: str = args.get("target_dir", "")

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not table_name:
        raise ValueError("Se requiere el argumento 'table_name'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    target_path = _ensure_target_dir(target_dir)

    tag_tables = target_plc.get_plc_tag_tables()
    for table in tag_tables:
        name = _safe_get_table_name(table)
        if name == table_name:
            table.export(
                target_directory_path=str(target_path),
                keep_folder_structure=False,
            )
            return {"exported_to": str(target_path), "table_name": table_name}

    raise RuntimeError(
        f"Tabla '{table_name}' no encontrada en PLC '{plc_name}'."
    )


def _h_import_tag_table(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Importa una unica PlcTagTable (XML) desde disco al PLC. Manual §2.2.24."""
    plc_name: str = args.get("plc_name", "")
    import_dir: str = args.get("import_dir", "")
    target_folder: str = args.get("target_folder") or ""

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not import_dir:
        raise ValueError("Se requiere el argumento 'import_dir'.")
    if not os.path.isdir(import_dir):
        raise RuntimeError(f"El directorio no existe: '{import_dir}'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    target_plc.import_plc_tags(
        import_root_directory=import_dir,
        target_folder_path=target_folder,
    )
    return {"imported_from": import_dir}


def _h_import_block(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Importa un unico bloque (.s7dcl) desde disco al PLC. Manual §2.2.23."""
    plc_name: str = args.get("plc_name", "")
    import_dir: str = args.get("import_dir", "")
    target_folder: str = args.get("target_folder") or ""

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not import_dir:
        raise ValueError("Se requiere el argumento 'import_dir'.")
    if not os.path.isdir(import_dir):
        raise RuntimeError(f"El directorio no existe: '{import_dir}'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    target_plc.import_blocks(
        import_root_directory=import_dir,
        target_folder_path=target_folder,
    )
    return {"imported_from": import_dir}


def _find_plc_tag_table(target_plc: Any, table_name: str) -> Any:
    """Resuelve una PlcTagTable por nombre en el PLC objetivo.

    Usa ``_safe_get_table_name`` para tolerar UnicodeDecodeError en
    tablas con caracteres no-ASCII. Levanta RuntimeError si no existe.
    """
    if not table_name:
        raise ValueError("Se requiere el argumento 'table_name'.")
    for table in target_plc.get_plc_tag_tables():
        if _safe_get_table_name(table) == table_name:
            return table
    raise RuntimeError(
        f"Tabla '{table_name}' no encontrada en PLC."
    )


def _h_get_user_constants(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Devuelve {value_str: name} de las PlcUserConstant de una tabla.

    Solo incluye constantes cuyo Value es parseable como int (las
    constantes con Value no-numerico se omiten silenciosamente).
    """
    plc_name: str = args.get("plc_name", "")
    table_name: str = args.get("table_name", "")

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    table = _find_plc_tag_table(target_plc, table_name)

    result: dict[str, str] = {}
    for constant in table.get_user_constants():
        raw_value = constant.get_property(name="Value")
        try:
            int_value = int(str(raw_value).strip())
        except (TypeError, ValueError):
            continue
        name = constant.get_property(name="Name")
        result[str(int_value)] = str(name)
    return {"constants": result}


def _h_delete_user_constant(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Borra una PlcUserConstant. Manual §2.34.4."""
    plc_name: str = args.get("plc_name", "")
    table_name: str = args.get("table_name", "")
    constant_name: str = args.get("constant_name", "")

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not constant_name:
        raise ValueError("Se requiere el argumento 'constant_name'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    table = _find_plc_tag_table(target_plc, table_name)

    for constant in table.get_user_constants():
        if constant.get_property(name="Name") == constant_name:
            constant.delete()
            return {"deleted": True, "constant": constant_name}

    raise RuntimeError(
        f"Constante '{constant_name}' no encontrada en tabla '{table_name}'."
    )


def _h_update_user_constant_value(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Actualiza el valor de una PlcUserConstant (N_MAX). Manual §2.28.

    Doble validacion: set_property puede retornar !=0 sin lanzar excepcion
    en TIA V21 + Pythonnet. Tambien relee para confirmar que el valor real
    coincide (set_property puede retornar 0 OK pero el valor no se aplico).
    """
    plc_name: str = args.get("plc_name", "")
    table_name: str = args.get("table_name", "")
    constant_name: str = args.get("constant_name", "")
    new_value: int = args.get("new_value", 0)

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not constant_name:
        raise ValueError("Se requiere el argumento 'constant_name'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    table = _find_plc_tag_table(target_plc, table_name)

    for constant in table.get_user_constants():
        if constant.get_property(name="Name") == constant_name:
            rc = constant.set_property(name="Value", value=str(new_value))
            if rc != 0:
                raise RuntimeError(
                    f"N_MAX '{constant_name}' en tabla '{table_name}': "
                    f"TIA rechazo la modificacion (codigo de retorno {rc}). "
                    f"Valor intentado: '{new_value}'."
                )
            actual = constant.get_property(name="Value")
            if str(actual).strip() != str(new_value).strip():
                raise RuntimeError(
                    f"N_MAX '{constant_name}' en tabla '{table_name}': "
                    f"set_property retorno 0 (OK) pero el valor real en TIA "
                    f"es '{actual}', no '{new_value}'. Posible fallo "
                    f"silencioso de Pythonnet/TIA V21."
                )
            return {"updated": True, "constant": constant_name, "value": new_value}

    raise RuntimeError(
        f"Constante '{constant_name}' no encontrada en tabla '{table_name}'."
    )


def _h_update_user_constant_name(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Renombra una PlcUserConstant. Manual §2.28.

    Doble validacion analog a update_user_constant_value (set_property
    puede retornar OK sin aplicar el cambio en TIA V21).
    """
    plc_name: str = args.get("plc_name", "")
    table_name: str = args.get("table_name", "")
    current_name: str = args.get("current_name", "")
    new_name: str = args.get("new_name", "")

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not current_name:
        raise ValueError("Se requiere el argumento 'current_name'.")
    if not new_name:
        raise ValueError("Se requiere el argumento 'new_name'.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)
    table = _find_plc_tag_table(target_plc, table_name)

    for constant in table.get_user_constants():
        if constant.get_property(name="Name") == current_name:
            rc = constant.set_property(name="Name", value=new_name)
            if rc != 0:
                raise RuntimeError(
                    f"Rename '{current_name}' -> '{new_name}' en tabla "
                    f"'{table_name}': TIA rechazo la modificacion "
                    f"(codigo de retorno {rc})."
                )
            actual = constant.get_property(name="Name")
            if actual != new_name:
                raise RuntimeError(
                    f"Rename '{current_name}' -> '{new_name}' en tabla "
                    f"'{table_name}': set_property retorno 0 (OK) pero el "
                    f"nombre real en TIA es '{actual}', no '{new_name}'. "
                    f"Posible fallo silencioso de Pythonnet/TIA V21."
                )
            return {
                "updated": True,
                "old_name": current_name,
                "new_name": new_name,
            }

    raise RuntimeError(
        f"Constante '{current_name}' no encontrada en tabla '{table_name}'."
    )


# ---------------------------------------------------------------------------
# Comandos prohibidos dentro de un lote transaccional. Causarían:
#   - open/close_project: destruirían el portal a mitad del lote.
#   - save_project      : forzaría commit parcial fuera de la transacción.
#   - list_plcs         : no es operación, es introspección.
#   - compile_plc / compile_blocks: TIA rechaza compilar dentro de transacción.
#   - execute_transactional_batch: anidamiento no soportado.
#   - attach_portal / open_new_portal: ciclo de vida de la instancia TIA.
# ---------------------------------------------------------------------------
_TRANSACTION_FORBIDDEN_COMMANDS: frozenset[str] = frozenset(
    {
        "open_project",
        "close_project",
        "save_project",
        "list_plcs",
        "compile_plc",
        "compile_blocks",
        "execute_transactional_batch",
        "attach_portal",
        "open_new_portal",
    }
)


def _h_execute_transactional_batch(
    args: dict, tia_client: "SyncTIAClient"
) -> dict:
    """Ejecuta varios comandos bajo una sola transaccion de TIA Portal.

    Si cualquier handler falla se hace rollback de toda la cadena y se
    lanza RuntimeError con el paso que rompio. Captura el retorno de
    cada paso en ``details`` para que la IT vea los resultados intermedios.

    Sub-comandos se ejecutan via ``tia_client.dispatch(cmd, args)``, que
    ya envuelve excepciones y devuelve ``{ok, result|error}``. Aqui solo
    validamos ``ok`` y propagamos / hacemos rollback segun corresponda.
    """
    undo_text: str = args.get("undo_text", "Operacion por lote")
    operations: list[dict] = args.get("operations", [])

    if not operations:
        raise ValueError("La lista de operaciones esta vacia.")

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)

    # Iniciar transaccion nativa (manual §2.37.27).
    project.start_transaction(undo_text=undo_text, dialog_text=undo_text)

    results_list: list[dict] = []
    cmd: str = ""
    cmd_args: dict = {}
    try:
        for idx, op in enumerate(operations):
            cmd = op.get("command", "")
            cmd_args = op.get("args", {})

            if cmd in _TRANSACTION_FORBIDDEN_COMMANDS:
                raise ValueError(
                    f"El comando '{cmd}' esta prohibido dentro de un lote "
                    "transaccional."
                )

            # Ejecutar via el dispatcher del propio tia_client. Si el handler
            # lanza, dispatch captura y devuelve {ok: False, error: ...}.
            dispatch_out = tia_client.dispatch(cmd, cmd_args)

            if not dispatch_out.get("ok"):
                # Traducir el error del sub-comando a excepcion para que el
                # try/except de abajo haga rollback.
                raise RuntimeError(
                    f"sub-comando '{cmd}' fallo: "
                    f"{dispatch_out.get('error', '?')}"
                )

            step_result = dispatch_out.get("result")
            results_list.append({
                "step": idx + 1,
                "command": cmd,
                "result": step_result,
            })

            # Defensa en profundidad (sept-2026): si la op retorno False
            # (fallo no-excepcion), abortar el batch para rollback.
            if step_result is False:
                raise RuntimeError(
                    f"Lote abortado: op '{cmd}' retorno False en paso "
                    f"{idx + 1}. Rollback ejecutado."
                )

        # Confirmar transaccion si no hubo errores (manual §2.37.28).
        project.end_transaction(rollback=False)

        return {
            "success": True,
            "operations_executed": len(operations),
            "details": results_list,
        }

    except Exception as exc:
        # Reversion garantizada ante excepciones (manual §2.37.28).
        # Silenciamos fallos secundarios del rollback para no enmascarar la
        # causa raiz original.
        try:
            project.end_transaction(rollback=True)
        except Exception:
            pass
        # Incluimos los args de la op que fallo (truncados a 500 chars) para
        # diagnostico del operario.
        import json as _json
        try:
            args_str = _json.dumps(cmd_args, ensure_ascii=False, default=str)[:500]
        except Exception:
            args_str = repr(cmd_args)[:500]
        raise RuntimeError(
            f"Lote abortado en el paso {len(results_list) + 1} ('{cmd}'). "
            f"Args: {args_str}. "
            f"Rollback ejecutado. Motivo: {exc}"
        )


def _h_compile_blocks(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Compila una lista explicita de bloques del PLC (no todo el software).

    Caso de uso (sept-2026): tras modificar N_MAX + comentarios de
    dispositivos, el FB de sync necesita que TIA recompile los DataBlocks
    para que el array se redimensione. Compilar todo el PLC
    (``compile_software``) tarda minutos en un S7-1500 con 200+ bloques;
    solo hemos tocado N DBs concretos. Este handler compila SOLO los
    bloques de la lista ``block_names``, saltando los ya consistentes.

    Semantica por bloque:
      - ``is_consistent()=True``  -> se SALTA (sin cambios, ahorra tiempo).
      - ``is_consistent()=False`` -> se COMPILA con ``.compile()``.
      - bloque no encontrado -> se SALTA (no falla el handler entero).

    Args:
        plc_name: nombre del PLC.
        block_names: lista de nombres a compilar. Vacia -> ValueError
            (sept-2026: el caller debe pasar nombres explicitos).

    Returns:
        ``{
            "compiled":         [{"name", "had_errors", "was_inconsistent"}],
            "skipped_unchanged": [name, ...],
            "not_found":        [name, ...],
            "errors":           [{"name", "error"}],
        }``
    """
    plc_name: str = args.get("plc_name", "")
    block_names = args.get("block_names")

    if not plc_name:
        raise ValueError("Se requiere el argumento 'plc_name'.")
    if not block_names:
        raise ValueError(
            "Se requiere 'block_names' (lista no vacia de bloques a compilar). "
            "Si quieres compilar todo el PLC, usa el comando 'compile_plc'."
        )

    portal = tia_client.wrapper
    if portal is None:
        raise RuntimeError(
            "No portal attached. Llama a attach_portal primero."
        )
    project = _get_active_project(portal)
    target_plc = _find_plc(project, plc_name)

    # Indexar bloques del PLC por nombre para busqueda O(1).
    all_blocks = target_plc.get_program_blocks()
    by_name: dict = {}
    for b in all_blocks:
        name = _safe_get_block_name(b)
        if name is not None:
            by_name.setdefault(name, b)  # primero que aparece gana

    compiled: list[dict] = []
    skipped_unchanged: list[str] = []
    not_found: list[str] = []
    errors: list[dict] = []

    for name in block_names:
        block = by_name.get(name)
        if block is None:
            not_found.append(name)
            continue
        # is_consistent(): True si ya esta compilado y sin cambios.
        try:
            is_consistent = bool(block.is_consistent())
        except Exception:
            # Defensivo: si lanza (raro), asumimos NO consistente y compilamos.
            is_consistent = False
        if is_consistent:
            skipped_unchanged.append(name)
            continue
        # .compile() retorna True si hay errores (semantica Siemens §2.2.11).
        try:
            had_errors = bool(block.compile())
            compiled.append({
                "name": name,
                "had_errors": had_errors,
                "was_inconsistent": True,
            })
        except Exception as exc:
            errors.append({
                "name": name,
                "error": f"{type(exc).__name__}: {exc}",
            })

    return {
        "compiled": compiled,
        "skipped_unchanged": skipped_unchanged,
        "not_found": not_found,
        "errors": errors,
    }


def register_core_commands(target: SyncTIAClient) -> None:
    """Registra los comandos core (lifecycle + inspection) en ``target``.

    Idempotente por nombre: si un comando ya esta registrado en el
    target, register_command() lanza ValueError. El caller decide si
    reinstancia o ignora.

    Uso en main.py (4.5.1): ``register_core_commands(tia_client)``.
    Uso en tests: ``register_core_commands(client); client.attach_wrapper(mock)``.

    4.1.2a1: open_new_portal, open_project, save_project, close_project.
    4.1.2a2: ping, list_blocks.
    4.1.2a3: list_plcs.
    4.1.2a4: get_project_info.
    4.1.2a5: scan_blocks.
    4.1.2b1 (este commit): compile_plc.
    4.1.2b2+: compile_blocks, export/import masivo.
    """
    target.register_command("attach_portal", _h_attach_portal)
    target.register_command("detach_portal", _h_detach_portal)
    target.register_command("open_new_portal", _h_open_new_portal)
    target.register_command("open_project", _h_open_project)
    target.register_command("save_project", _h_save_project)
    target.register_command("close_project", _h_close_project)
    target.register_command("ping", _h_ping)
    target.register_command("list_blocks", _h_list_blocks)
    target.register_command("list_plcs", _h_list_plcs)
    target.register_command("get_project_info", _h_get_project_info)
    target.register_command("scan_blocks", _h_scan_blocks)
    target.register_command("compile_plc", _h_compile_plc)
    target.register_command("compile_blocks", _h_compile_blocks)
    target.register_command("export_blocks_sd", _h_export_blocks_sd)
    target.register_command("export_udts_sd", _h_export_udts_sd)
    target.register_command("export_plc_tags_xml", _h_export_plc_tags_xml)
    target.register_command("import_blocks_sd", _h_import_blocks_sd)
    target.register_command("import_plc_tags_xml", _h_import_plc_tags_xml)
    target.register_command("export_block", _h_export_block)
    target.register_command("export_tag_table", _h_export_tag_table)
    target.register_command("import_tag_table", _h_import_tag_table)
    target.register_command("import_block", _h_import_block)
    target.register_command("get_user_constants", _h_get_user_constants)
    target.register_command("update_user_constant_value", _h_update_user_constant_value)
    target.register_command("update_user_constant_name", _h_update_user_constant_name)
    target.register_command("delete_user_constant", _h_delete_user_constant)
    target.register_command(
        "execute_transactional_batch", _h_execute_transactional_batch
    )


# ---------------------------------------------------------------------------
# Hilo dedicado: tia-loop
# ---------------------------------------------------------------------------
def _tia_loop_main(
    client: SyncTIAClient, stop_event: threading.Event,
) -> None:
    """Bucle principal del tia-loop (corre en background, daemon=True).

    Drena la cola _cmd_queue y procesa cada item. El wrapper .NET se
    toca UNICAMENTE aqui. Si el bucle crashea con excepcion no
    capturada, transiciona a ERROR y el operario ve el problema.
    """
    logger.info("tia-loop: arrancando (daemon).")
    try:
        while not stop_event.is_set():
            try:
                item = client._cmd_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is _SENTINEL_STOP:
                break
            _req_id, name, args, resp_q = item
            _execute_one(client, name, args, resp_q)
    except Exception as exc:  # noqa: BLE001
        logger.exception("tia-loop crasheo: %s", exc)
        client._set_state(STATE_ERROR)
    finally:
        client._set_state(STATE_IDLE)
        logger.info("tia-loop: bye.")


def _execute_one(
    client: SyncTIAClient,
    name: str,
    args: dict,
    resp_q: queue.Queue | None,
) -> None:
    """Ejecuta un command y publica el resultado en resp_q (si existe).

    Transiciona state segun el command:
      - attach_portal / open_new_portal: IDLE -> ATTACHING -> CONNECTED.
      - detach_portal: CONNECTED -> DETACHING -> IDLE.
      - resto: CONNECTED -> BUSY -> CONNECTED (o ERROR si falla).
    """
    # Transicion previa segun el command (algunos tienen su propio state).
    if name in ("attach_portal", "open_new_portal"):
        client._set_state(STATE_ATTACHING)
    elif name == "detach_portal":
        client._set_state(STATE_DETACHING)
    elif client.state == STATE_CONNECTED:
        client._set_state(STATE_BUSY)

    # Ejecutar el handler via dispatch (shape {"ok":..., "result"|"error":...}).
    result = client.dispatch(name, args)

    # Post-transicion. Si el handler fallo, vamos a ERROR; si no, dejamos
    # el estado que el propio handler haya establecido (p. ej. attach
    # ya dejo CONNECTED).
    if not result.get("ok", False):
        client._set_state(STATE_ERROR)
    elif client.state in (STATE_BUSY,):
        # Para commands que NO son attach/detach: volver a CONNECTED si
        # wrapper sigue vivo, si no a IDLE.
        if client._wrapper is not None:
            client._set_state(STATE_CONNECTED)
        else:
            client._set_state(STATE_IDLE)

    if resp_q is not None:
        try:
            resp_q.put_nowait(result)
        except queue.Full:
            logger.warning("resp_q llena; descartando respuesta de %s.", name)


# Singleton de proceso. main.py (4.5.1) hace tia_client = SyncTIAClient().
# Los modulos que quieran un mock en tests pueden sobreescribirlo.
tia_client = SyncTIAClient()
