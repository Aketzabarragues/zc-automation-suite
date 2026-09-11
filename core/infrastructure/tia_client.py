"""
SyncTIAClient — cliente sync al wrapper siemens_tia_scripting (DA-014).

Skeleton (Fase 4 / paso 4.1.1). Comandos core se migran en 4.1.2.
Areas registran comandos extra en 4.1.3.

Reemplaza gateway.py + worker_tia.py. Vive en el mismo proceso que Flask
y el loop OB1. NO subproceso. NO asyncio. NO IPC.

Modelo OB1:
- Hilo OB1 (main loop) llama dispatch() y dispatch_pending() por ciclo.
- Hilo Flask encola comandos via submit() (thread-safe, queue.Queue).
- Hilo OB1 es el UNICO que llama metodos sobre tia_client.wrapper
  (acceso single-threaded al wrapper .NET, evita RCW races).

Carga del wrapper:
- El skeleton NO carga siemens_tia_scripting.pyd (eso requiere stage en
  tempfile y queda fuera de este paso).
- main.py (4.5.1) hace: tia_client.attach_wrapper(loader.load()).
- Tests inyectan mocks via attach_wrapper().
"""
from __future__ import annotations

import logging
import os
import queue
from typing import Any, Callable

logger = logging.getLogger(__name__)


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
    """Cliente sync al wrapper TIA. OB1-friendly, sin subproceso."""

    def __init__(self) -> None:
        self._handlers: dict[str, HandlerSig] = {}
        self._pending: queue.Queue[tuple[str, dict]] = queue.Queue()
        # Placeholder; main.py attach_wrapper()/attach_ts() lo rellena en
        # arranque. Antes de attach, dispatch() funciona solo con handlers
        # que no tocan el wrapper (util para tests y para el spike).
        self._wrapper = None
        self._ts = None  # modulo siemens_tia_scripting

    # ----------------------------------------------------------- API publica
    def register_command(self, name: str, handler: HandlerSig) -> None:
        """Registra un handler para `name`. Llamado por areas al import."""
        if name in self._handlers:
            raise ValueError(f"command already registered: {name}")
        self._handlers[name] = handler
        logger.debug("registered command: %s", name)

    def dispatch(self, command: str, args: dict | None = None) -> dict:
        """Dispatcher sync. Solo llamado desde el hilo OB1.

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

    def submit(self, command: str, args: dict | None = None) -> None:
        """Encola comando para drenar en el proximo ciclo OB1. Thread-safe.

        Pensado para que el hilo Flask encole sin bloquear.
        """
        self._pending.put((command, args or {}))

    def dispatch_pending(self) -> int:
        """Drena cola FIFO y ejecuta cada comando. Solo hilo OB1.

        Retorna el numero de comandos procesados en este drain.
        """
        processed = 0
        while True:
            try:
                cmd, args = self._pending.get_nowait()
            except queue.Empty:
                return processed
            self.dispatch(cmd, args)
            processed += 1

    # --------------------------------------------------------------- helpers
    def attach_wrapper(self, wrapper) -> None:
        """Adjunta el portal .NET (mock en tests, .pyd real en main).

        Solo el hilo OB1 debe llamarlo.
        """
        self._wrapper = wrapper

    def attach_ts(self, ts_module) -> None:
        """Adjunta el modulo ``siemens_tia_scripting`` (mock o real).

        Lo usan handlers que invocan ``ts.open_portal(...)`` o
        ``ts.Enums.PortalMode.X``. Solo el hilo OB1 debe llamarlo.
        """
        self._ts = ts_module

    @property
    def wrapper(self):
        """Accessor del wrapper siemens_tia_scripting.

        Acceso single-threaded: solo el hilo OB1 debe llamar metodos sobre
        el objeto retornado (los RCW .NET no son thread-safe).
        """
        return self._wrapper

    @property
    def ts(self):
        """Accessor del modulo ``siemens_tia_scripting``.

        Idem wrapper: solo el hilo OB1 debe llamar funciones sobre el
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
def _h_open_new_portal(args: dict, tia_client: "SyncTIAClient") -> dict:
    """Cold start: lanza una instancia NUEVA de TIA Portal y abre proyecto.

    Usa ``tia_client.ts.open_portal(...)`` (modulo siemens_tia_scripting)
    y luego ``new_portal.open_project(...)``. No necesita portal previo:
    crea uno nuevo.
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
    new_portal = ts.open_portal(portal_mode=ts.Enums.PortalMode.AnyUserInterface)
    if new_portal is None:
        raise RuntimeError("Fallo critico: open_portal retorno None.")
    new_portal.open_project(project_file_path=project_file_path)
    # En OB1 el portal pasa a ser el nuevo. main.py lo attach_wrapper().
    # Aqui solo notificamos al caller con el project path abierto.
    return {"opened": True, "project_file_path": project_file_path}


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


def register_core_commands(target: SyncTIAClient) -> None:
    """Registra los comandos core (lifecycle + inspection) en ``target``.

    Idempotente por nombre: si un comando ya esta registrado en el
    target, register_command() lanza ValueError. El caller decide si
    reinstancia o ignora.

    Uso en main.py (4.5.1): ``register_core_commands(tia_client)``.
    Uso en tests: ``register_core_commands(client); client.attach_wrapper(mock)``.

    4.1.2a1a: open_new_portal, open_project.
    4.1.2a1b: save_project, close_project.
    4.1.2a2a (este commit): ping, list_blocks.
    4.1.2a3+: list_plcs, get_project_info, scan_blocks.
    """
    target.register_command("open_new_portal", _h_open_new_portal)
    target.register_command("open_project", _h_open_project)
    target.register_command("save_project", _h_save_project)
    target.register_command("close_project", _h_close_project)
    target.register_command("ping", _h_ping)
    target.register_command("list_blocks", _h_list_blocks)


# Singleton de proceso. main.py (4.5.1) hace tia_client = SyncTIAClient().
# Los modulos que quieran un mock en tests pueden sobreescribirlo.
tia_client = SyncTIAClient()
