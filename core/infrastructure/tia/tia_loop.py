"""core.infrastructure.tia.tia_loop - OB1 del subsistema TIA Portal.

Contiene:
  - SyncTIAClient: state machine + cola FIFO + hilo dedicado + API publica.
  - _execute_one: re-attach defensivo, transicion de state, captura COM/RPC.
  - _tia_loop_main: drena la cola y delega en el dispatcher.

Los 26 comandos (_h_*) viven en core.infrastructure.tia.tia_handlers.
Las 14 utilities defensivas viven en core.infrastructure.tia.tia_helpers.

Single thread para Openness: el tia-loop es el UNICO dueno del wrapper
.NET. El resto de la app pasa por la cola (submit_and_wait / submit_batch).
"""
from __future__ import annotations

import itertools
import logging
import queue
import threading
from typing import Any, Callable

logger = logging.getLogger("zc.tia_loop")


# Estados del subsistema TIA (publicos; los usa /api/v1/tia/connection).
STATE_IDLE = "idle"
STATE_ATTACHING = "attaching"
STATE_CONNECTED = "connected"
STATE_BUSY = "busy"
STATE_DETACHING = "detaching"
STATE_ERROR = "error"

# Sentinela para que stop_tia_loop() ordene al hilo salir limpio
# (queue.put), sin un flag externo que pueda racear.
_SENTINEL_STOP: tuple = ("__STOP__",)

# Firma de un handler de comando. Recibe args JSON + cliente, devuelve dict.
HandlerSig = Callable[[dict, "SyncTIAClient"], dict]


class SyncTIAClient:
    """Cliente + state machine + hilo del subsistema TIA Portal.

    API principal:
      - submit_and_wait / submit_batch: encolar commands y obtener respuesta.
      - start_tia_loop / stop_tia_loop: arrancar/parar el hilo dedicado.
      - state: propiedad de solo lectura (IDLE, CONNECTED, BUSY, ...).
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
        self._cmd_queue: queue.Queue = queue.Queue()
        # Hilo dedicado.
        self._tia_thread: threading.Thread | None = None
        self._tia_stop = threading.Event()
        # Flag explicito de "el tia-loop esta corriendo". El publisher 5
        # (tia_loop_status) lee este flag en lugar de
        # ``_tia_thread.is_alive()``: el join() puede retornar antes de
        # que el finally del hilo publique, dando un False positivo.
        self._loop_running: bool = False
        # Hooks opcionales para la capa SSE. Se cablean desde
        # core.sse.publishers.wire_all() en el arranque.
        self.on_state_change: Callable[[], None] | None = None
        self.on_loop_status: Callable[[], None] | None = None

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
            if self.on_state_change is not None:
                try:
                    self.on_state_change()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "on_state_change hook fallo: %s", exc,
                    )

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
        """Encola un command y BLOQUEA hasta tener respuesta (con timeout)."""
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
        """Encola varios commands en lote y espera a todos."""
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
        """Arranca el hilo dedicado tia-loop (idempotente)."""
        if self._tia_thread is not None and self._tia_thread.is_alive():
            logger.debug("start_tia_loop: ya estaba corriendo; no-op.")
            return self._tia_thread
        if self._ts is None:
            # Carga lazy del wrapper .NET. Solo la primera vez.
            try:
                from core.infrastructure.tia.tia_loader import load_siemenstia
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
        self._loop_running = True
        logger.info("tia-loop arrancado.")
        if self.on_loop_status is not None:
            try:
                self.on_loop_status()
            except Exception as exc:  # noqa: BLE001
                logger.warning("on_loop_status hook fallo: %s", exc)
        return thread

    def stop_tia_loop(self, timeout: float = 5.0) -> None:
        """Senala parada al tia-loop y espera a que termine."""
        if self._tia_thread is None:
            return
        # Marca parada ANTES del join para que el publisher 5 vea
        # running=False de forma determinista.
        self._loop_running = False
        if self.on_loop_status is not None:
            try:
                self.on_loop_status()
            except Exception as exc:  # noqa: BLE001
                logger.warning("on_loop_status hook fallo: %s", exc)
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
        """Adjunta el modulo ``siemens_tia_scripting`` (mock o real)."""
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
# Hilo dedicado: tia-loop
# ---------------------------------------------------------------------------
def _tia_loop_main(
    client: SyncTIAClient, stop_event: threading.Event,
) -> None:
    """Bucle principal del tia-loop (corre en background, daemon=True).

    Drena la cola _cmd_queue y procesa cada item. El wrapper .NET se
    toca UNICAMENTE aqui.
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
        # Si el hilo sale por crash (no por stop_tia_loop), el flag
        # sigue True; lo corregimos y publicamos para que el bus vea
        # running=False.
        if client._loop_running:
            client._loop_running = False
        if client.on_loop_status is not None:
            try:
                client.on_loop_status()
            except Exception as exc:  # noqa: BLE001
                logger.warning("on_loop_status hook fallo: %s", exc)


def _execute_one(
    client: SyncTIAClient,
    name: str,
    args: dict,
    resp_q: queue.Queue | None,
) -> None:
    """Ejecuta un command y publica el resultado en resp_q (si existe).

    Transiciona state segun el command:
      - attach_portal / open_new_portal: IDLE -> ATTACHING -> CONNECTED (o ERROR).
      - detach_portal: CONNECTED -> DETACHING -> IDLE (o ERROR).
      - resto: CONNECTED -> BUSY -> CONNECTED (o ERROR si falla).

    Re-attach defensivo: para comandos distintos de los de ciclo de vida,
    si el wrapper no responde a ``get_process_id()`` se intenta
    ``_try_reattach()`` antes de fallar. Si el handler revienta con
    una excepcion que parece COM/RPC (``_is_com_disconnect``), el wrapper
    se marca como None para forzar re-attach en el siguiente comando.
    """
    # Re-attach defensivo: solo aplica a commands que no son de ciclo de
    # vida. attach/detach/open_new_portal gestionan su propio wrapper.
    if name not in ("attach_portal", "detach_portal", "open_new_portal"):
        if client._wrapper is not None:
            try:
                client._wrapper.get_process_id()
            except Exception:
                if not _try_reattach(client):
                    result = {"ok": False, "error": "Portal no disponible y re-attach fallo"}
                    if resp_q is not None:
                        try:
                            resp_q.put_nowait(result)
                        except queue.Full:
                            logger.warning("resp_q llena; descartando respuesta de %s.", name)
                    client._set_state(STATE_ERROR)
                    return
        else:
            # No hay wrapper: requiere attach previo.
            result = {"ok": False, "error": "Portal no attached. Conectar primero."}
            if resp_q is not None:
                try:
                    resp_q.put_nowait(result)
                except queue.Full:
                    logger.warning("resp_q llena; descartando respuesta de %s.", name)
            client._set_state(STATE_ERROR)
            return

    # Transicion previa segun el command.
    if name in ("attach_portal", "open_new_portal"):
        client._set_state(STATE_ATTACHING)
    elif name == "detach_portal":
        client._set_state(STATE_DETACHING)
    elif client.state == STATE_CONNECTED:
        client._set_state(STATE_BUSY)

    # Ejecutar el handler via dispatch. Capturamos excepciones para
    # distinguir COM/RPC (forzar re-attach) de errores de aplicacion.
    handler_exc: Exception | None = None
    try:
        result = client.dispatch(name, args)
    except Exception as exc:
        handler_exc = exc
        if _is_com_disconnect(exc):
            # Portal parece muerto. Marcamos wrapper = None para forzar
            # re-attach en el siguiente comando y devolvemos error claro.
            client.attach_wrapper(None)
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        else:
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # Transicion posterior segun el resultado y el command.
    if not result.get("ok", False):
        client._set_state(STATE_ERROR)
    elif name in ("attach_portal", "open_new_portal"):
        if client._wrapper is not None:
            client._set_state(STATE_CONNECTED)
        else:
            client._set_state(STATE_IDLE)
    elif name == "detach_portal":
        client._set_state(STATE_IDLE)
    elif client.state == STATE_BUSY:
        if client._wrapper is not None:
            client._set_state(STATE_CONNECTED)
        else:
            client._set_state(STATE_IDLE)

    if handler_exc is not None:
        logger.warning(
            "handler %s lanzo %s: %s",
            name, type(handler_exc).__name__, handler_exc,
        )

    if resp_q is not None:
        try:
            resp_q.put_nowait(result)
        except queue.Full:
            logger.warning("resp_q llena; descartando respuesta de %s.", name)


# ---------------------------------------------------------------------------
# Funciones privadas del loop, movidas desde tia_helpers.py
# (sept-2026, greenfield/tia-worker-simplification).
# Solo el tia-loop las usa, asi que viven como top-level privadas aqui.
# ---------------------------------------------------------------------------

def _is_com_disconnect(exc: BaseException) -> bool:
    """Heuristica: parece que TIA Portal se cerro y hay que re-attachar.

    Detectar esto de forma exacta no es viable (depende del build del
    wrapper, de si murio el subproceso o solo el RCW quedo invalido).
    Aceptamos falsos positivos: re-attachar de mas es mejor que dejar
    al loop usando un portal muerto.
    """
    name = type(exc).__name__
    if "COM" in name or "RPC" in name:
        return True
    if hasattr(exc, "hresult"):
        return True
    return False


def _try_reattach(client: "SyncTIAClient") -> bool:
    """Intenta re-attachar al portal si esta muerto.

    Si ``client._wrapper`` ya responde a ``get_process_id()``, retorna
    True sin tocar nada. Si falla o no hay wrapper, intenta
    ``ts.attach_portal(AnyUserInterface)`` y deja el wrapper listo.
    """
    if client._wrapper is not None:  # noqa: SLF001
        try:
            client._wrapper.get_process_id()
            return True
        except Exception:
            client.attach_wrapper(None)
    ts = client._ts  # noqa: SLF001
    if ts is None:
        return False
    try:
        new_portal = ts.attach_portal(
            portal_mode=ts.Enums.PortalMode.AnyUserInterface,
        )
    except Exception as exc:
        logger.warning(
            "re-attach fallo: %s: %s", type(exc).__name__, exc,
        )
        return False
    if new_portal is None:
        logger.warning("re-attach fallo: attach_portal retorno None.")
        return False
    try:
        new_portal.get_process_id()
    except Exception as exc:
        logger.warning(
            "re-attach: get_process_id fallo tras attach: %s: %s",
            type(exc).__name__, exc,
        )
        client.attach_wrapper(None)
        return False
    client.attach_wrapper(new_portal)
    logger.info("re-attach OK.")
    return True


# IDs unicos monotonos para correlar request/response del worker.
_request_id_counter = itertools.count(1)


def _next_request_id() -> int:
    """IDs unicos monotonos para correlar request/response."""
    return next(_request_id_counter)


# Singleton de proceso. Tests pueden sobreescribirlo con un mock.
tia_client = SyncTIAClient()


# ---------------------------------------------------------------------------
# Re-exports para compat con callers que importaban handlers _h_* desde
# core.infrastructure.tia.tia_loop (tests legacy y callers internos).
#
# NOTA (sept-2026, greenfield/tia-worker-simplification): los _h_* viven
# ahora en core.infrastructure.tia.tia_cmd_*. Este re-export sigue
# activo por compat hasta el commit 11 de la rama, cuando se eliminara
# tia_handlers.py y los callers deberan actualizar a los nuevos paths.
# ---------------------------------------------------------------------------
from core.infrastructure.tia.tia_commands_catalog import (  # noqa: E402, F401
    register_all_commands,
)
