"""Orquestador de procesos IT de comunicación con TIA Portal.

Garantiza la separación absoluta entre el proceso asíncrono principal (FastMCP)
y el runtime síncrono de Siemens. Maneja la caché de memoria IT y la invocación
de subprocess. Backend headless: sin UI propia.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from core.infrastructure.build_cache import BuildCache
from core.models import BloqueCache, BloquePLC


# Logger de la capa de infraestructura. Los logs de start/connect/
# disconnect/kill aparecen en el root logger (zc_tray) cuando se
# ejecuta via main_tray.py, gracias a que main_tray configura un
# FileHandler en el root logger con nivel INFO. Trazabilidad del
# ciclo de vida del subproceso worker persistente (sept-2026).
_log = logging.getLogger(__name__)


# Timeout por defecto del subproceso OT (segundos).
#
# Una ``execute_transactional_batch`` contra un PLC real puede
# implicar 50-100 operaciones dentro de ``start_transaction`` /
# ``end_transaction``. Con PLCs reales esto puede tardar 1-3 minutos
# (ver `.clinerules` §1: el stage ``open_transaction`` es OPAQUE y
# cubre la transacción COM). El default histórico era 45s, que se
# quedaba corto y forzaba timeouts en operaciones grandes.
#
# Operario en producción: ajustar con la variable de entorno
# ``ZC_GATEWAY_TIMEOUT`` (segundos) sin recompilar. Tests que
# parcheen ``sys.frozen`` no se ven afectados — el valor de la
# env var se evalúa por instancia, en el ``__init__`` del gateway.
DEFAULT_GATEWAY_TIMEOUT: float = float(
    os.environ.get("ZC_GATEWAY_TIMEOUT", "300.0")
)


class TIAConnectionError(RuntimeError):
    """TIA Portal no responde o no se puede adjuntar.

    Se lanza desde ``_dispatch_worker`` cuando el worker subprocess
    reporta un error que matchea con un patrón conocido de
    "TIA no disponible" (portal cerrado, versión no encontrada,
    sin proyecto abierto, etc.). Implica que la cache del gateway
    puede contener datos stale de una sesión anterior y debe
    limpiarse.

    Hereda de ``RuntimeError`` para compatibilidad con call sites
    existentes que capturan ``RuntimeError``.
    """


# Patrones de error que indican que TIA Portal no está disponible
# o el proyecto está cerrado. Matching case-sensitive por substring
# contra el mensaje reportado por el worker OT.
#
# Falsos positivos son aceptables (mejor limpiar cache innecesariamente
# que mantener datos stale); falsos negativos harían que el bug persista.
_CONNECTION_ERROR_PATTERNS: tuple[str, ...] = (
    "No matching TIA Portal version",   # el del log típico
    "no project is open",
    "TIA Portal is not running",
    "Cannot attach",
    "ExclusiveAccess",
    "OpennessAccessException",          # catch-all por si el .NET wrapper añade prefijos
)


def _is_tia_connection_error(message: str) -> bool:
    """True si el mensaje indica que TIA Portal no está disponible.

    Matching case-sensitive por substring contra
    ``_CONNECTION_ERROR_PATTERNS``. Falsos positivos son aceptables
    (mejor limpiar cache innecesariamente que mantener datos stale);
    falsos negativos harían que el bug persista.
    """
    if not message:
        return False
    return any(p in message for p in _CONNECTION_ERROR_PATTERNS)


class TIAProcessGateway:
    """Gateway asíncrono hacia el motor OT mediante subprocesos efímeros.

    Resolución del subproceso:
      - Modo desarrollo: sys.executable es python.exe; se lanza
        'python -u main.py --worker' (main.py enruta al worker OT).
      - Modo empaquetado (PyInstaller --onefile): sys.frozen es True;
        sys.executable es zc_automation_suite.exe, que al recibir --worker
        enruta internamente al worker OT. En este modo los scripts .py
        NO existen físicamente (residen en el PYZ), por lo que NO se
        referencian rutas a .py.
    """

    def __init__(
        self,
        timeout: float | None = None,
        persistent: bool = False,
    ) -> None:
        """Inicializa el gateway IT.

        Args:
            timeout: Timeout (segundos) del subproceso OT. Si es
                ``None`` (default), usa ``DEFAULT_GATEWAY_TIMEOUT``
                (180s, configurable vía ``ZC_GATEWAY_TIMEOUT``). Pasarlo
                explícito tiene prioridad sobre la env var (útil para
                tests con mocks que necesitan un timeout corto).
            persistent: Si es ``True``, el gateway se prepara para usar
                un worker OT persistente (un único subproceso vivo
                durante toda la sesión, un attach al inicio, N comandos
                por el mismo attach). En este PR el flag solo añade
                la infraestructura (campos de estado, lock, dispatcher);
                el comportamiento persistente real se implementa en
                PR 3 (``_plan/13_persistent_worker_impl.md``). Si es
                ``False`` (default), mantiene el comportamiento 1-shot
                actual: 1 subproceso por llamada a ``_dispatch_worker``.
        """
        self._persistent = persistent
        # Atributo público de solo-lectura. Útil para que el código de
        # composición (``main.py``, ``main_tray.py``) y los tests
        # consulten el modo sin tocar el atributo privado.
        # El setter NO se expone: el flag se decide en el composition
        # root y es inmutable durante la vida del gateway.
        self._cache: dict[str, Any] = {}
        # Cache IT especializada de bloques + tag tables escaneados.
        # Separada de ``self._cache`` (que guarda lecturas ligeras como
        # ``list_plcs``) porque su ciclo de vida es distinto: los
        # bloques cambian con mucha menos frecuencia y se reconstruyen
        # con ``scan_plc_blocks``. Se invalida en open/close_project
        # via ``_clear_bloques_cache``.
        self._bloques_cache: dict[str, "BloqueCache"] = {}
        self._timeout = timeout if timeout is not None else DEFAULT_GATEWAY_TIMEOUT
        # Metricas de timing acumuladas por comando (PR de observabilidad).
        # Cada vez que _dispatch_worker termina, acumula el
        # dispatch_total_ms (ciclo end-to-end del subproceso) en la
        # lista del comando. La lectura publica se hace con
        # get_metrics() para no exponer el estado interno. Thread-safety:
        # solo se accede desde el event loop de asyncio (single-thread
        # dentro del proceso IT), por lo que no se anaden locks.
        self._metrics: dict[str, list[float]] = {}

        if persistent:
            # Estado del worker OT persistente (modo web).
            # Inicializado AHORA pero el comportamiento real (subproceso
            # vivo, lock de envío, reader task, heartbeat) se implementa
            # en PR 3 del refactor. Ver ``_plan/12_worker_persistent_design.md``
            # §3.1 y ``_plan/13_persistent_worker_impl.md`` (PR 2/3).
            #
            # Por ahora, los campos están inicializados a sus valores
            # neutros (``None``/``{}``) para que la propiedad ``persistent``
            # y los tests del flag (PR 2) puedan inspeccionarlos sin
            # necesidad de tener un subproceso vivo. ``_dispatch_worker``
            # detecta el flag y lanza ``NotImplementedError`` (ver
            # abajo) — el dispatch real persistente no existe todavía.
            self._worker_proc: asyncio.subprocess.Process | None = None
            self._worker_lock = asyncio.Lock()
            self._next_request_id: int = 0
            self._pending_responses: dict[int, asyncio.Future[Any]] = {}
            self._reader_task: asyncio.Task[None] | None = None
            self._heartbeat_task: asyncio.Task[None] | None = None
            # Estados posibles: "idle" | "connecting" | "connected" |
            # "disconnected" | "error".
            #
            # Cambio sept-2026 (state machine refactor): el estado
            # inicial es ``"idle"`` (NO ``"disconnected"`` como en el
            # round anterior). El worker arranca siempre; el estado
            # ``"idle"`` indica "subproceso vivo, wrapper cargado,
            # pero SIN portal attached todavia". El operario decide
            # cuando conectar via ``connect()`` (que transiciona a
            # "connecting" -> "connected"). ``"disconnected"`` queda
            # reservado para "subproceso muerto o matado" (kill
            # explicito, returncode != None, etc.).
            self._connection_state: str = "idle"
            self._project_path: str | None = None  # para detectar cambios (PR 7)
            # Flag one-shot que el frontend consume via ``/tia/connection``
            # (PR 7). Se pone a ``True`` cuando ``_detect_project_change``
            # detecta que el operario abrio un proyecto distinto en TIA
            # sin pasar por la app. ``consume_project_changed()`` lo lee
            # y lo resetea para que el siguiente poll no vuelva a
            # notificar el mismo cambio.
            self._project_changed: bool = False
            self._last_ping_ok: float | None = None
            self._last_error: str | None = None
            # PID del portal TIA Portal al que estamos attached. Lo setea
            # ``connect()`` tras un ``attach_portal`` exitoso (el worker
            # devuelve ``{"pid": <int>}``) y lo limpia ``disconnect()``
            # (transicion a ``"idle"``). ``None`` en cualquier estado
            # distinto de ``"connected"`` (idle, connecting, error,
            # disconnected). El router ``/tia/connection`` lo expone
            # en la respuesta cuando ``state == "connected"`` para que
            # la SPA muestre el PID al operario (util para diagnostico
            # desde Task Manager: "tengo 3 zombie? mira sus PIDs"). No
            # es el PID del subproceso worker (eso seria ``pid`` del
            # ``_worker_proc``); es el PID de TIA Portal en si. Ver
            # ``worker_tia.attach_portal`` (comando OT que devuelve
            # ``ts.get_process_id()``).
            self._last_portal_pid: int | None = None

    @property
    def persistent(self) -> bool:
        """Modo del gateway: ``True`` para worker persistente (modo web).

        Solo-lectura: el flag lo decide el composition root al construir
        el gateway y es inmutable durante su vida. Acceso público
        estable (los tests y los componentes de UI pueden consultarlo
        sin tocar ``_persistent``).
        """
        return self._persistent

    def _resolve_worker_exec_args(self) -> list[str]:
        """Devuelve los argumentos para lanzar el subproceso worker.

        La diferenciación frozen/dev se evalúa en cada llamada para
        robustez ante tests que parcheen sys.frozen en runtime.
        """
        if getattr(sys, "frozen", False):
            # Entorno de producción (PyInstaller --onefile):
            # sys.executable ES el binario compilado.
            return ["--worker"]

        # Entorno de desarrollo: invocar main.py con el intérprete actual.
        # ``main.py`` vive en la RAÍZ del repo, no dentro de ``core/``.
        # Este módulo está en ``core/infrastructure/gateway.py``:
        #   Path(__file__).parent            = core/infrastructure/
        #   Path(__file__).parent.parent      = core/
        #   Path(__file__).parent.parent.parent = <raíz>
        # (Antes de PR 1, el módulo estaba en ``infrastructure/gateway.py``
        # y bastaba con un solo ``..``. Tras PR 1 se movió un nivel más
        # abajo, hay que subir un nivel adicional.)
        main_script = Path(__file__).parent.parent.parent / "main.py"
        return ["-u", str(main_script), "--worker"]

    async def _dispatch_worker(
        self,
        command: str,
        args: dict[str, Any] | None = None,
        timeout_override: float | None = None,
    ) -> Any:
        """Dispatcher genérico hacia el worker OT según el modo del gateway.

        Si ``self._persistent`` es ``True`` delega en
        ``_send_to_persistent_worker`` (worker OT vivo durante toda
        la sesión, 1 attach al inicio, N comandos por el mismo
        attach, protocolo request-response con IDs). El lock
        ``self._worker_lock`` serializa los requests al worker para
        no corromper el stream stdin/stdout (TIA es single-user y
        el subproceso solo tiene 1 lector; ver §2.4 del design doc).

        Si es ``False`` (default), delega en
        ``_dispatch_ephemeral_worker`` (comportamiento 1-shot
        histórico: 1 subproceso por llamada, completo back-compat).

        Args:
            command: Nombre del comando del COMMAND_REGISTRY del worker.
            args: Argumentos JSON-serializables para el comando.
            timeout_override: Si se pasa, se usa este timeout en lugar
                de ``self._timeout`` (útil para operaciones bulk como
                ``execute_transactional_batch`` que necesitan un timeout
                proporcional al número de operaciones). ``None``
                usa el default del gateway.
        """
        if self._persistent:
            # Modo persistente (PR 3+): 1 subproceso vivo, request
            # matching por ID, asyncio.Lock para serializar. El lock
            # protege TODO el ciclo (envío + espera de respuesta) para
            # que 2 requests concurrentes no se pisen en el stream.
            #
            # Cambio sept-2026 (state machine refactor): la deteccion
            # de cambio de proyecto (PR 7) YA NO se hace aqui en cada
            # dispatch. Se hace en ``connect()`` (cuando se transiciona
            # a connected) y en ``reconnect()``. La justificacion es
            # de state machine: un comando del registry solo se envia
            # si el gateway esta en state="connected", y el chequeo
            # de proyecto ahi es redundante con el de connect.
            #
            # Validacion de estado: ``attach_portal``, ``detach_portal``
            # y ``ping`` se permiten siempre (son los comandos que
            # controlan/transicionan el state machine). El resto de
            # comandos del registry requieren state="connected"; si
            # el gateway esta en idle/connecting/error, lanzamos
            # ``TIAConnectionError`` con mensaje claro para que el
            # frontend muestre el circulo gris y el operario sepa
            # que debe conectar primero.
            if command not in (
                "attach_portal",
                "detach_portal",
                "ping",
                "get_project_info",
            ) and self._connection_state != "connected":
                raise TIAConnectionError(
                    "Worker no conectado a TIA Portal. Conectar primero."
                )
            async with self._worker_lock:
                return await self._send_to_persistent_worker(
                    command, args, timeout_override
                )
        return await self._dispatch_ephemeral_worker(command, args, timeout_override)

    async def _dispatch_ephemeral_worker(
        self,
        command: str,
        args: dict[str, Any] | None = None,
        timeout_override: float | None = None,
    ) -> Any:
        """Lanza main.py (o el .exe congelado) con --worker y le envía el payload por STDIN.

        Modo 1-shot: 1 subproceso por llamada. Es el comportamiento
        histórico del gateway, preservado intacto en este PR; el
        wrapper ``_dispatch_worker`` lo invoca cuando
        ``self._persistent`` es ``False``.

        Args:
            command: Nombre del comando del COMMAND_REGISTRY del worker.
            args: Argumentos JSON-serializables para el comando.
            timeout_override: Si se pasa, se usa este timeout en lugar
                de ``self._timeout`` (útil para operaciones bulk como
                ``execute_transactional_batch`` que necesitan un timeout
                proporcional al número de operaciones). ``None``
                usa el default del gateway.
        """
        # Metricas de timing (observabilidad). Mide el ciclo
        # end-to-end: create_subprocess_exec + envio de payload +
        # proc.communicate() + parsing de respuesta. time.monotonic()
        # es inmune a saltos NTP. Se acumula y se loguea en el
        # `finally` para capturar tambien errores y timeouts.
        t_dispatch_start = time.monotonic()
        _result: Any = None
        try:
            timeout = timeout_override if timeout_override is not None else self._timeout
            exec_args = self._resolve_worker_exec_args()

            # Forzar encoding UTF-8 en el subproceso (heredado del
            # padre). Sin esto, en Windows el worker arranca con
            # cp1252 y Pythonnet revienta al convertir strings de
            # TIA Portal (Latin-1) a Python UTF-8.
            import os as _os
            worker_env = {
                **_os.environ,
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1",
            }

            # Invocación: -u (unbuffered I/O) en desarrollo, solo --worker en frozen.
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                *exec_args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=worker_env,
            )

            payload_bytes = json.dumps({"command": command, "args": args or {}}).encode(
                "utf-8"
            )

            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(input=payload_bytes),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise RuntimeError(
                    f"Timeout tras {timeout}s ejecutando el comando '{command}'. "
                    "El subproceso OT no respondió (posible diálogo modal activo en TIA Portal)."
                )

            stderr_text = stderr_b.decode("utf-8", errors="replace").strip()
            stdout_text = stdout_b.decode("utf-8", errors="replace").strip()

            if proc.returncode != 0 and not stdout_text:
                raise RuntimeError(
                    f"El subproceso OT colapsó (exit code {proc.returncode}). Error: {stderr_text or 'Sin salida'}"
                )

            # Extraer la última línea válida parseable como JSON (filtro contra interferencias)
            json_response = None
            for line in reversed(stdout_text.splitlines()):
                line_str = line.strip()
                if line_str.startswith("{") and line_str.endswith("}"):
                    try:
                        json_response = json.loads(line_str)
                        break
                    except json.JSONDecodeError:
                        continue

            if json_response is None:
                raise RuntimeError(
                    f"Respuesta inválida del worker OT. STDOUT: '{stdout_text}' | STDERR: '{stderr_text}'"
                )

            if not json_response.get("ok"):
                # Incluir stderr del worker para diagnóstico (traceback
                # completo, mensajes de Pythonnet, etc.). Sin esto,
                # solo vemos el error resumido.
                err = json_response.get("error", "Error interno en el worker OT.")
                if stderr_text:
                    full_msg = f"{err} | STDERR: {stderr_text[:2000]}"
                else:
                    full_msg = err

                if _is_tia_connection_error(str(err)):
                    # El worker no puede adjuntar al portal. La cache
                    # puede tener datos stale de un escaneo anterior;
                    # invalidar para forzar al operario a re-seleccionar
                    # el PLC tras reconectar.
                    self._clear_bloques_cache()
                    self._cache.clear()
                    _logger = logging.getLogger(__name__)
                    _logger.warning(
                        "TIA Portal no responde (%s); cache invalidada. "
                        "El frontend deberia resetear store.selectedPlc y "
                        "store.plcBlocksCache tras este error.",
                        err,
                    )
                    raise TIAConnectionError(full_msg)

                raise RuntimeError(full_msg)

            _result = json_response.get("result")
        finally:
            # Metricas de timing: ciclo end-to-end del subproceso.
            # time.monotonic() es inmune a saltos NTP. Se ejecuta
            # SIEMPRE (incluso en TimeoutError o RuntimeError) para
            # que el operario pueda diagnosticar latencias y cuellos
            # de botella reales, no solo los caminos felices.
            _t_dispatch_end = time.monotonic()
            _dispatch_ms = (_t_dispatch_end - t_dispatch_start) * 1000
            self._metrics.setdefault(command, []).append(_dispatch_ms)
            sys.stderr.write(
                f"[GATEWAY TIMING] command={command!r} dispatch_total_ms={round(_dispatch_ms)}\n"
            )

        # Retorno fuera del try/finally: el `return` dentro de un
        # `finally` es un anti-patron (suprime excepciones en vuelo).
        # sys.exc_info() devuelve (None, None, None) si NO hay
        # excepcion en vuelo; la clase de la excepcion si la hay.
        # Si hay excepcion, dejamos que se propague sin retornar.
        if sys.exc_info()[0] is None:
            return _result

    async def _detect_project_change(self) -> bool:
        """Compara el proyecto activo en TIA con el ultimo conocido.

        Si difiere, marca el flag ``_project_changed = True`` (que el
        frontend consume via ``/tia/connection``) e invalida las
        caches (``_cache`` y ``_bloques_cache``) porque un cambio de
        proyecto implica que el estado IT anterior es stale.

        Estrategia (design doc §3.5): consulta ``get_project_info`` al
        worker y compara el campo ``path`` con ``self._project_path``.

        Robustez:
          - Si el gateway no es persistente, retorna ``False`` sin
            hacer nada (no hay worker al que preguntar; la deteccion
            aplica solo al modo web).
          - Si la llamada a ``_send_to_persistent_worker`` falla
            (TIA cerrado, timeout, excepcion COM/RPC), retorna
            ``False`` sin crashear. La deteccion de desconexion la
            hace el heartbeat; este metodo SOLO se ocupa de cambios
            de proyecto cuando el worker esta vivo.
          - Si el resultado no es un dict (caso patologico), se trata
            como ``path=None`` y se compara igual.

        Returns:
            ``True`` si se detecto un cambio de proyecto (y por tanto
            se invalidaron caches); ``False`` en caso contrario
            (mismo proyecto, error de comunicacion, o modo 1-shot).
        """
        if not self._persistent:
            return False

        try:
            async with self._worker_lock:
                info = await asyncio.wait_for(
                    self._send_to_persistent_worker(
                        "get_project_info", {}, timeout_override=10.0
                    ),
                    timeout=10.0,
                )
        except Exception:
            # Worker no responde, TIA cerrado, timeout, COM/RPC, etc.
            # El heartbeat marcara ``disconnected`` si persiste. Aqui
            # solo nos ocupa el cambio de proyecto; si no podemos
            # preguntar, no marcamos nada y dejamos que el siguiente
            # comando reintente.
            return False

        current_path = info.get("path") if isinstance(info, dict) else None

        if current_path != self._project_path:
            # Cambio detectado (o primera deteccion tras arranque:
            # ``_project_path`` empezaba en ``None``). Invalidamos
            # caches: un proyecto distinto implica un PLC distinto,
            # bloques distintos, tags distintos, etc. Lo que teniamos
            # cacheado ya no es valido.
            self._project_path = current_path
            self._project_changed = True
            # ``clear_cache`` ya invalida ``_bloques_cache``; llamamos
            # tambien ``_clear_bloques_cache`` explicitamente por si
            # el operario anade mas caches en el futuro y quiere ver
            # un punto de invalidadcion claro. Envuelto en try/except
            # defensivo: la deteccion de cambio NO debe fallar si
            # limpiar la cache lanza (e.g. un futuro cache que requiera
            # I/O).
            try:
                self.clear_cache()
            except Exception:
                pass
            try:
                self._clear_bloques_cache()
            except Exception:
                pass
            return True

        return False

    def consume_project_changed(self) -> bool:
        """Lee y resetea el flag ``_project_changed`` (one-shot).

        Pensado para que el endpoint ``GET /tia/connection`` (PR 5a)
        exponga al frontend ``project_changed=true`` UNA SOLA VEZ
        por cambio real. Tras un read, el flag vuelve a ``False``
        hasta el siguiente cambio.

        Returns:
            ``True`` si hay un cambio de proyecto pendiente de
            notificar al frontend; ``False`` en caso contrario.
        """
        changed = bool(getattr(self, "_project_changed", False))
        # Reset atomico: si otro caller marco el flag entre el getattr
        # y el set, NO lo pisamos (el False solo se aplica si estaba
        # a True). En la practica no hay concurrencia dentro del
        # proceso IT (single-thread asyncio), pero la lectura es
        # defensiva.
        if changed:
            self._project_changed = False
        return changed

    def _resolve_persistent_worker_exec_args(self) -> list[str]:
        """Args extra para lanzar el subproceso del worker en modo persistente.

        El gateway en modo persistente invoca ``sys.executable`` con
        ``_resolve_worker_exec_args()`` (resuelve ``main.py`` en dev /
        el .exe en frozen) seguido de estos args extra. En este PR
        (PR 2) los args son un único flag ``--worker-persistent``;
        el entry point de ``worker_tia.main()`` lo detecta y enruta
        a ``main_persistent_loop()`` (placeholder en este PR, loop
        real en PR 3).

        Importante: el ``--worker-persistent`` debe ser EXACTAMENTE
        este string (lo busca ``worker_tia.main()`` con
        ``"--worker-persistent" in sys.argv``). Cualquier variante
        (``--persistent``, ``-p``, etc.) NO será detectada y el
        worker caerá al modo 1-shot.
        """
        return ["--worker-persistent"]

    def is_worker_alive(self) -> bool:
        """True si el subproceso del worker persistente esta vivo.

        Estado "vivo" = el subproceso fue lanzado (``_worker_proc is
        not None``) y aun no ha terminado (``returncode is None``).

        Distinto de ``_connection_state`` (que refleja el attach a
        TIA Portal): el worker puede estar VIVO pero DESCONECTADO
        de TIA (e.g. 3 fallos del heartbeat). El ``WorkerStatusIndicator``
        del topbar usa este flag para que el operario vea de un
        vistazo si el subproceso del worker esta en marcha, sin
        confundirlo con el attach a TIA.

        Para gateways en modo 1-shot (MCP, tests legacy), retorna
        ``False`` siempre: no hay worker persistente.
        """
        if not getattr(self, "_persistent", False):
            return False
        proc = getattr(self, "_worker_proc", None)
        if proc is None:
            return False
        return proc.returncode is None

    async def start(self) -> None:
        """Arranca el worker OT persistente y espera al "ready_idle" signal.

        API publica (sept-2026, post-auditoria). Pensada para que el
        ``WebServiceSupervisor`` (modo web) la invoque ANTES de
        ``uvicorn.run``, de forma que cuando la web empiece a aceptar
        requests el worker ya este vivo y con estado ``"idle"``.

        Esto elimina el race condition del flujo anterior: el primer
        comando del frontend (e.g. ``GET /tia/connection``) disparaba
        el lazy start via ``_send_to_persistent_worker``, que enviaba
        un ``ping`` con timeout 15s. Si el attach a TIA Portal tardaba
        mas de 15s (e.g. dialog de seguridad, primera carga del
        wrapper .NET), el ping moria antes de que el worker estuviera
        listo para leer stdin. El frontend quedaba en
        ``state="error"`` durante 15s aunque TIA estuviera bien.

        Con este metodo:
          - El supervisor (o ``main.py --web``) llama a ``await
            gateway.start()`` antes de ``uvicorn.run``.
          - El gateway lanza el subproceso worker, espera al "ready"
            signal (id=0) con timeout 60s, y solo entonces retorna.
          - Si el ready llega OK, ``_connection_state = "idle"``.
          - Si falla, lanza ``TIAConnectionError`` con mensaje claro.
          - La web arranca con el worker ya en estado consistente.

        Modo 1-shot (``persistent=False``): no-op. El gateway se usa
        tal cual en el flujo MCP, sin worker persistente.

        Raises:
            TIAConnectionError: si el worker no emite "ready" en 60s
                (TIA Portal con dialog de seguridad, attach muy lento,
                bug en ``main_persistent_loop``) o si la creacion del
                subproceso falla.

        Nota: este metodo se restauro en sept-2026 tras un refactor
        intermedio que lo habia borrado accidentalmente. El
        ``WebServiceSupervisor._serve_once`` y ``main.py::_run_web_mode_async``
        ya lo invocan; sin el, el primer ``GET /tia/connection`` del
        frontend encuentra ``is_worker_alive() == False`` y el
        ``WorkerStatusIndicator`` se queda gris aunque el subproceso
        este vivo (el lazy start de ``_start_persistent_worker`` se
        dispara tarde, en el primer comando).
        """
        if not self._persistent:
            _log.info("gateway.start(): no-op (persistent=False, modo 1-shot)")
            return  # modo 1-shot: no hay worker persistente que arrancar
        _log.info("gateway.start(): arrancando worker persistente (persistent=True)")
        try:
            await self._start_persistent_worker()
            _log.info(
                "gateway.start(): worker persistente arrancado OK "
                "(state=%r, worker_alive=%s)",
                self._connection_state,
                self.is_worker_alive(),
            )
        except Exception as exc:
            _log.error(
                "gateway.start(): FALLO al arrancar worker: %s: %s",
                type(exc).__name__,
                exc,
            )
            raise

    async def _start_persistent_worker(self) -> None:
        """Lanza el subproceso worker OT en modo persistente (lazy start).

        Idempotente: si ya hay un worker vivo (``returncode is None``),
        retorna sin hacer nada. Si el subproceso existe pero murio
        (returncode != None), lo relanza.

        Flujo:

          1. Resuelve los args de lanzamiento combinando el patron del
             path 1-shot (dev: ``python -u main.py``; frozen: ``.exe``)
             con el flag ``--worker-persistent`` que ``main.py`` enruta
             a ``worker_tia.main_persistent_loop()``.
          2. Lanza el subproceso con ``asyncio.create_subprocess_exec``
             y PIPE para stdin/stdout/stderr (mismo patron que el path
             1-shot en ``_dispatch_ephemeral_worker``).
          3. Inicia ``_read_worker_stdout_forever`` como task asyncio:
             es la unica task que lee stdout del worker y resuelve los
             futures registrados en ``self._pending_responses`` por ID.
          4. Envia un ping inicial con timeout corto. Si el worker
             responde ok, marca ``_connection_state = "connected"``.
             Si falla (timeout, EOF, error), marca ``"error"`` y lanza
             ``TIAConnectionError`` para que el caller decida.

        Side effects:
          - Asigna ``self._worker_proc``.
          - Crea ``self._reader_task``.
          - Puede actualizar ``self._connection_state`` y
            ``self._last_ping_ok`` / ``self._last_error``.
        """
        if self._worker_proc is not None and self._worker_proc.returncode is None:
            _log.info(
                "_start_persistent_worker: no-op (subproceso ya vivo, pid=%d)",
                self._worker_proc.pid,
            )
            return  # ya esta corriendo, no-op

        self._connection_state = "connecting"

        # Resolucion de los args de lanzamiento. Sigue el mismo
        # patron que ``_resolve_worker_exec_args`` (path 1-shot): en
        # dev usa ``python -u main.py`` con el flag CLI; en frozen
        # usa el .exe con el flag. ``main.py`` parsea el flag y
        # enruta a ``worker_tia.main_persistent_loop()``.
        persistent_flag = self._resolve_persistent_worker_exec_args()
        if getattr(sys, "frozen", False):
            launch_args: list[str] = list(persistent_flag)
        else:
            main_script = Path(__file__).parent.parent.parent / "main.py"
            launch_args = ["-u", str(main_script), *persistent_flag]

        # Forzar encoding UTF-8 en el subproceso (mismo patron que
        # ``_dispatch_ephemeral_worker``). PYTHONUTF8=1 para que
        # Pythonnet no reviente con strings Latin-1 de TIA Portal.
        worker_env = {
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            *launch_args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=worker_env,
        )
        self._worker_proc = proc
        _log.info(
            "_start_persistent_worker: subproceso LANZADO (pid=%d, args=%s)",
            proc.pid,
            launch_args,
        )
        # El reader_task es la unica task que consume stdout. Si
        # termina (EOF, excepcion), los futures pendientes se quedan
        # sin resolver; ``_send_to_persistent_worker`` los detecta
        # por timeout y marca el estado como ``disconnected``. El
        # siguiente comando hara lazy start de nuevo.
        self._reader_task = asyncio.create_task(self._read_worker_stdout_forever())

        # Espera al "ready_idle" signal del worker (id=0, sept-2026).
        # Pre-condicion: el caller YA adquirio ``self._worker_lock``
        # (o esta en un path donde no hay lock, como ``start()``).
        # Aqui no se vuelve a coger (seria deadlock). El ready_idle
        # signal es interno: registramos un future con id=0 en
        # ``_pending_responses`` y esperamos con timeout 60s.
        #
        # Cambio sept-2026 (state machine): tras el ready_idle el
        # estado es ``"idle"`` (NO ``"connected"`` como en el round
        # anterior). El attach se hace bajo demanda via ``connect()``,
        # que transiciona idle -> connecting -> connected.
        loop = asyncio.get_event_loop()
        ready_future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending_responses[0] = ready_future
        try:
            ready_payload = await asyncio.wait_for(ready_future, timeout=60.0)
            if not ready_payload.get("ok"):
                # El worker reporto ready_idle con error. Caso raro:
                # el wrapper fallo al cargar pero el subproceso sigue
                # vivo (e.g. error de importacion del wrapper).
                self._connection_state = "error"
                self._last_error = ready_payload.get("error", "Worker no reporto ready_idle")
                raise TIAConnectionError(
                    f"Worker ready_idle reporto error: {self._last_error}"
                )
            # Estado inicial: ``idle`` (NO connected). El operario
            # debe llamar ``connect()`` para transicionar a connected.
            self._connection_state = "idle"
            self._last_ping_ok = time.monotonic()
            self._last_error = None
        except asyncio.TimeoutError:
            # El worker arranco (subproceso vivo) pero no emitio el
            # "ready_idle" en 60s. Posibles causas: carga del wrapper
            # .NET muy lenta (caso raro; ~1-2s tipicamente), o bug en
            # ``main_persistent_loop``.
            self._connection_state = "error"
            self._last_error = (
                "Worker arranco pero no emitio 'ready_idle' en 60s. "
                "Posible causa: carga del wrapper .NET muy lenta o "
                "bug en main_persistent_loop."
            )
            raise TIAConnectionError(self._last_error)
        finally:
            # Quitar el future del dict SIEMPRE. Doble seguridad con
            # el pop en el reader:889 (idempotente).
            self._pending_responses.pop(0, None)

        # NO se inicia el heartbeat aqui. Cambio sept-2026 (state
        # machine): el heartbeat solo corre cuando hay portal
        # attached (state="connected"). En idle (sin portal) el
        # ``get_process_id`` no tiene sentido y solo gastaria
        # round-trips contra el worker. El inicio se hace desde
        # ``connect()`` cuando transiciona a connected.

        # Deteccion del proyecto inicial (PR 7): si el operario ya
        # abrio un proyecto en TIA Portal antes de lanzar la app, este
        # es el primer momento en que podemos preguntar por el path
        # sin penalizar al operario con una operacion extra. Si hay
        # un proyecto activo, ``_project_path`` se popula y
        # ``_project_changed`` queda a ``False`` (no es un cambio,
        # es el estado inicial). Si TIA no tiene proyecto, ambos
        # quedan ``None`` y se detectara en el siguiente comando.
        #
        # Cambio sept-2026 (state machine): la deteccion ya NO se
        # hace en cada dispatch (rompia el contrato del state
        # machine: un comando del registry requiere state=connected
        # y este check seria redundante). Se hace aqui en el
        # startup del worker, en ``connect()`` y al ``reconnect()``.
        # Si TIA no tiene proyecto attached todavia (idle), este
        # check se difiere al primer ``connect()``.
        #
        # NO se hace bajo el lock: ``_detect_project_change`` adquiere
        # su propio ``async with self._worker_lock`` internamente.
        if self._reader_task is not None and not self._reader_task.done():
            # Solo si el reader sigue vivo (en el path del test con
            # fake stdout que devuelve EOF inmediato, el reader ya
            # murio y detectar proyecto fallaria con BrokenPipeError).
            # En produccion el reader vive indefinidamente.
            try:
                await self._detect_project_change()
            except Exception:
                # Best-effort: si falla (e.g. TIA sin proyecto),
                # no es bloqueante. El primer connect() lo reintentara.
                pass

    async def _heartbeat_loop(self) -> None:
        """Heartbeat continuo: ping al worker cada ``ZC_WORKER_HEARTBEAT_SECONDS`` (default 5s).

        Mantiene ``_connection_state`` actualizado segun el resultado
        del ultimo ping:

          - 0 fallos consecutivos: ``"connected"`` (sano).
          - 1-2 fallos consecutivos: ``"connecting"`` (transitorio, el
            proximo tick reintentara).
          - 3 fallos consecutivos: ``"idle"`` (sept-2026 round 3; el
            ``"disconnected"`` anterior se eliminó del state machine
            en el refactor y la rama residual del catch genérico se
            unificó a ``"idle"`` por consistencia).

        Robustez:

          - **No crashea** si el ping falla por timeout, ``RuntimeError``,
            ``TIAConnectionError`` o cualquier otra excepcion. Solo
            incrementa el contador de fallos y actualiza ``_last_error``.
          - **Si el subproceso muere** (``_worker_proc.returncode is not None``)
            marca ``"disconnected"`` inmediatamente sin esperar al
            proximo tick: respuesta del design doc §3.4.
          - **Si ``_worker_proc`` es None** (gateway desconectado
            externamente), sale del loop limpiamente. La task termina
            y queda disponible para un re-lanzamiento.
          - **Cogemos ``self._worker_lock``** alrededor del ping: la
            serializacion contra ``_dispatch_worker`` es necesaria para
            no corromper el stream stdin/stdout. Esto significa que
            comandos largos (p.ej. ``compile_plc`` de 8s) retrasan al
            heartbeat, pero NO lo pausan: el lock se libera entre
            comandos, y el ``async with`` solo bloquea la rafaga
            concurrente. Si un comando tarda mas de
            ``ZC_WORKER_HEARTBEAT_SECONDS``, el siguiente tick del
            heartbeat esperara al lock; esto es aceptable porque
            cualquier ping seria lanzado en paralelo seria serializado
            de todas formas.

        Cancelacion:

          La task se cancela externamente (no hay ``__aexit__`` en
          esta version; PR 6 introducira ``disconnect()`` que la
          cancela). Al recibir ``CancelledError``, simplemente
          retornamos: ``_heartbeat_task.done()`` sera ``True`` y un
          futuro ``_start_persistent_worker`` lanzara uno nuevo.
        """
        interval = float(os.environ.get("ZC_WORKER_HEARTBEAT_SECONDS", "5.0"))
        consecutive_failures = 0

        try:
            while True:
                # ``asyncio.sleep`` cede el control al event loop, lo
                # que permite a ``_dispatch_worker`` adquirir el lock
                # entre ticks. Si el proc muere durante el sleep, lo
                # detectamos al despertar.
                await asyncio.sleep(interval)

                # Salida limpia si el gateway fue desconectado
                # externamente (PR 6 pondra ``_worker_proc = None``).
                if self._worker_proc is None:
                    return

                # Deteccion inmediata de muerte del subproceso (sin
                # esperar al ping): si ``returncode`` ya esta fijado,
                # el worker murio y el ping fallaria igualmente.
                if self._worker_proc.returncode is not None:
                    # El subproceso worker murio. En el state machine
                    # sept-2026 (idle/connecting/connected/error), un
                    # worker muerto se representa como "idle" (subproceso
                    # no attached). El operario puede reintentar connect()
                    # y el gateway hara lazy start de un nuevo worker.
                    self._connection_state = "idle"
                    self._last_error = (
                        f"Worker subproceso termino con codigo "
                        f"{self._worker_proc.returncode}"
                    )
                    consecutive_failures = 3  # corte directo a idle
                    continue

                # Ping bajo el lock para serializar contra
                # ``_dispatch_worker``. ``timeout_override=10.0``
                # porque el ping debe ser una operacion ligera
                # (``portal.get_process_id()``); si tarda mas de 10s
                # algo va muy mal.
                try:
                    async with self._worker_lock:
                        result = await asyncio.wait_for(
                            self._send_to_persistent_worker(
                                "ping", args={}, timeout_override=10.0
                            ),
                            timeout=10.0,
                        )
                    if result and isinstance(result, dict) and result.get("ok"):
                        # Guard (sept-2026 round 3, fix de auditoría):
                        # si el gateway se marcó a ``"idle"`` o
                        # ``"error"`` optimistamente (e.g. desde
                        # ``disconnect()`` mientras el ping estaba en
                        # vuelo), NO pisar a ``"connected"``. Esto
                        # evita que un ping lento sobrescriba una
                        # transición de estado intencional del
                        # operario.
                        if self._connection_state not in ("idle", "error"):
                            self._connection_state = "connected"
                        self._last_ping_ok = time.monotonic()
                        self._last_error = None
                        consecutive_failures = 0
                    else:
                        # El worker respondio pero ``ok=False``: TIA
                        # probablemente cayo (get_process_id fallo).
                        consecutive_failures += 1
                        self._last_error = (
                            (result or {}).get("error")
                            if isinstance(result, dict)
                            else f"Ping retorno payload inesperado: {result!r}"
                        ) or "Ping retorno sin ok"
                        # Idem: respetar transiciones optimistas.
                        if self._connection_state not in ("idle", "error"):
                            self._connection_state = (
                                # 3 fallos consecutivos: "idle" (sept-2026).
                                # El operario puede reintentar connect().
                                "idle"
                                if consecutive_failures >= 3
                                else "connecting"
                            )
                except asyncio.CancelledError:
                    # Cancelacion externa (gateway apagandose): salimos
                    # sin propagar la excepcion (es un cierre limpio).
                    return
                except Exception as exc:
                    # Cualquier fallo (TimeoutError, RuntimeError,
                    # TIAConnectionError, EOF en stdin, ...) cuenta
                    # como un fallo. NO propagamos: la idea es que el
                    # heartbeat NUNCA muera por si solo.
                    #
                    # Cambio sept-2026 round 3 (fix de auditoría):
                    # el estado ``"disconnected"`` ya no existe en el
                    # state machine (se eliminó en el refactor). 3
                    # excepciones consecutivas transicionan a
                    # ``"idle"`` directamente, consistente con el
                    # path de ok=False y con el resto del state
                    # machine. Antes este path producía
                    # ``"disconnected"`` que el frontend no sabe
                    # manejar.
                    consecutive_failures += 1
                    self._last_error = f"{type(exc).__name__}: {exc}"
                    if self._connection_state not in ("idle", "error"):
                        self._connection_state = (
                            "idle"
                            if consecutive_failures >= 3
                            else "connecting"
                        )
        except asyncio.CancelledError:
            # Doble catch: por si la cancelacion llega entre el
            # ``asyncio.sleep`` y el cuerpo del loop.
            return

    async def _read_worker_stdout_forever(self) -> None:
        """Lee stdout del worker linea por linea y resuelve futures por ID.

        Task asyncio unica (lanzada en ``_start_persistent_worker``)
        que consume el stream stdout del subproceso persistente.
        Cada linea JSON incoming tiene la forma ``{"id": int, "ok":
        bool, "result"?: any, "error"?: str}``. Hacemos match por
        ``id`` contra ``self._pending_responses`` y resolvemos el
        future correspondiente.

        Cierre limpio:
          - EOF en stdout (``b''``): el worker murio. Salimos del
            loop. Los futures pendientes NO se resuelven: el caller
            (``_send_to_persistent_worker``) los detecta por timeout
            y marca el estado como ``disconnected``.
          - Linea no parseable como JSON: la saltamos (sigue siendo
            defensivo: si el worker escribe otra cosa a stdout por
            error, no rompemos el reader).
          - Linea sin ``id``: la saltamos (no podemos matchearla).
        """
        # Snapshot local del proc para que un cambio de
        # ``self._worker_proc`` (relanzamiento) no nos haga leer
        # del proc equivocado.
        proc = self._worker_proc
        if proc is None or proc.stdout is None:
            return
        while True:
            try:
                line = await proc.stdout.readline()
            except Exception:
                # Stream roto: salimos y dejamos que los timeouts
                # en ``_send_to_persistent_worker`` manejen la
                # limpieza.
                break
            if not line:
                # EOF: el worker cerro stdout. Salimos.
                break
            try:
                response = json.loads(line.decode("utf-8").strip())
            except Exception:
                # Linea no parseable. Logueamos a stderr pero no
                # rompemos el reader (el worker podria estar
                # emitiendo basura; el match por id es defensivo).
                sys.stderr.write(
                    f"[GATEWAY READER] linea no parseable: {line!r}\n"
                )
                sys.stderr.flush()
                continue
            if not isinstance(response, dict):
                continue
            request_id = response.get("id")
            if request_id is None:
                continue
            future = self._pending_responses.get(request_id)
            if future is not None and not future.done():
                future.set_result(response)
            # Pop defensivo: el reader limpia el dict al resolver el
            # future para evitar memory leaks si el caller ya hizo
            # timeout y su ``finally`` no corrio (caso extremo:
            # ``_send_to_persistent_worker`` cancelado por una
            # excepcion externa). ``_send_to_persistent_worker``
            # tambien hace pop en su ``finally``; el segundo pop es
            # no-op (idempotente) gracias a ``pop(..., None)``.
            self._pending_responses.pop(request_id, None)
            # Si no habia future pendiente para este id, lo descartamos
            # (p.ej. el caller ya hizo timeout y se fue). El reader
            # sigue procesando los siguientes.

    async def _send_to_persistent_worker(
        self,
        command: str,
        args: dict[str, Any] | None,
        timeout_override: float | None,
    ) -> Any:
        """Envia un comando al worker persistente y espera la respuesta.

        Protocolo request-response con IDs (ver §2.5 del design doc):

          1. Asigna ``request_id = self._next_request_id``; incrementa.
          2. Serializa ``{"id": request_id, "command": command,
             "args": args}`` a JSON y lo escribe en ``stdin`` del
             worker seguido de ``b"\\n"``.
          3. Crea un ``asyncio.Future``, lo registra en
             ``self._pending_responses[request_id]``.
          4. Espera ``asyncio.wait_for(future, timeout=...)`` hasta
             que el reader task (que corre en paralelo) resuelva el
             future al leer la linea con ese ``id`` desde stdout.
          5. Si la respuesta es ``{ok: False, error: ...}``, decide
             entre ``RuntimeError`` y ``TIAConnectionError`` segun el
             patron del error (ver §3.1 del design doc: errores de
             conexion marcan ``_connection_state = "idle"``).
          6. Si timeout, marca el estado como ``"disconnected"`` y
             lanza ``RuntimeError`` con mensaje accionable.

        Pre-condicion: el caller YA adquirio ``self._worker_lock``.
        Aqui no se vuelve a coger (seria deadlock).

        Args:
            command: Nombre del comando del COMMAND_REGISTRY.
            args: Argumentos JSON-serializables (dict o None).
            timeout_override: Si no es None, sobrescribe el timeout
                default del gateway para esta llamada concreta.

        Returns:
            El ``result`` de la respuesta del worker (cualquier
            tipo JSON-serializable que el handler retorno).

        Raises:
            TIAConnectionError: si el worker reporta un error de
                conexion (patrones en ``_CONNECTION_ERROR_PATTERNS``).
            RuntimeError: si la respuesta es ``ok=False`` (error
                de aplicacion, no de conexion), si el reader
                falla, o si el timeout expira.
        """
        # Lazy start: si el proc no existe o ya murio, lo relanzamos.
        if self._worker_proc is None or self._worker_proc.returncode is not None:
            await self._start_persistent_worker()

        # El reader_task es quien resuelve futures. Si murio (e.g.
        # EOF inesperado), NO podemos recibir respuestas. Marcamos
        # disconnected y fallamos rapido en vez de esperar al timeout.
        if self._reader_task is None or self._reader_task.done():
            # El reader_task es quien resuelve futures. Si murio (e.g.
            # EOF inesperado), NO podemos recibir respuestas. Marcamos
            # "error" (no "idle", porque un reader muerto es un fallo
            # grave del worker, no una desconexion limpia del portal).
            self._connection_state = "error"
            raise RuntimeError(
                "Reader task del worker persistente no esta vivo. "
                "El subproceso probablemente murio."
            )

        request_id = self._next_request_id
        self._next_request_id += 1
        payload = json.dumps(
            {"id": request_id, "command": command, "args": args or {}}
        ).encode("utf-8")

        loop = asyncio.get_event_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending_responses[request_id] = future

        # En el ``finally`` SIEMPRE quitamos el future del dict
        # (haya habido exito, timeout o excepcion) para no leakear
        # memoria: si el worker responde tarde (despues del timeout)
        # y el future sigue en el dict, el reader_task lo resuelve
        # pero nadie lo consume.
        try:
            assert self._worker_proc.stdin is not None
            self._worker_proc.stdin.write(payload + b"\n")
            await self._worker_proc.stdin.drain()

            timeout = (
                timeout_override if timeout_override is not None else self._timeout
            )
            response = await asyncio.wait_for(future, timeout=timeout)

            if not response.get("ok"):
                err = response.get("error", "Error interno en el worker OT.")
                if _is_tia_connection_error(str(err)):
                    # Patron de error de conexion conocido. Marcamos
                    # "idle" (sept-2026): TIA no responde, el worker
                    # sigue vivo, el operario puede reintentar connect().
                    # La cache IT se invalida para evitar datos stale
                    # de un attach anterior.
                    self._connection_state = "idle"
                    self._clear_bloques_cache()
                    self._cache.clear()
                    _logger = logging.getLogger(__name__)
                    _logger.warning(
                        "Worker persistente: error de conexion TIA (%s); "
                        "cache invalidada.",
                        err,
                    )
                    raise TIAConnectionError(str(err))
                raise RuntimeError(str(err))

            return response.get("result")
        except asyncio.TimeoutError as exc:
            # El worker no respondio al comando en el timeout. En el
            # state machine sept-2026 marcamos "idle" (no "error"):
            # puede ser un comando lento puntual, no un fallo del
            # worker. El operario puede reintentar.
            self._connection_state = "idle"
            self._last_error = (
                f"Worker no respondio en {timeout}s (comando: {command!r})"
            )
            raise RuntimeError(self._last_error) from exc
        except TIAConnectionError:
            # Ya tenemos el estado actualizado; re-propagar.
            raise
        except RuntimeError:
            # Error de aplicacion del worker. NO marcamos disconnected
            # (puede ser un ValueError transitorio del handler). Solo
            # dejamos que el caller lo maneje.
            raise
        except Exception as exc:
            # Cualquier otra excepcion (e.g. BrokenPipeError si el
            # worker muere durante el write) marca "error" (sept-2026):
            # es un fallo grave (I/O con el worker), no una
            # desconexion limpia. Se traduce a RuntimeError para que
            # el caller no vea el tipo nativo de asyncio.
            self._connection_state = "error"
            self._last_error = f"{type(exc).__name__}: {exc}"
            raise RuntimeError(
                f"Error de I/O con el worker persistente "
                f"({type(exc).__name__}): {exc}"
            ) from exc
        finally:
            # Quitar el future del dict SIEMPRE. Si el reader_task
            # lo resuelve tarde (despues del timeout), el set_result
            # en el reader es no-op (future.done() == True).
            self._pending_responses.pop(request_id, None)

    async def _kill_persistent_worker(self) -> None:
        """Mata el subproceso del worker y cancela las tasks asociadas.

        Helper centralizado de cleanup para que ``reconnect()``,
        ``disconnect()`` y un futuro shutdown de la app lo usen
        identico. Robusto a llamadas repetidas (idempotente): si el
        worker ya esta muerto, los tasks cancelados o los futures
        ya resueltos, no hace nada.

        _log.info(
            "_kill_persistent_worker: matando subproceso (proc=%s, returncode=%s)",
            getattr(self._worker_proc, "pid", None) if self._worker_proc else None,
            getattr(self._worker_proc, "returncode", None) if self._worker_proc else None,
        )

        Orden de operaciones (importa):

          1. Cancela ``_reader_task`` (la unica task que consume stdout
             y resuelve futures por ``id``). Si NO se cancela, puede
             quedarse en un ``await`` infinito.
          2. Cancela ``_heartbeat_task``. Esta task se beneficia de la
             cancelacion (sale via ``CancelledError``) y, ademas, si
             la cancelamos despues de poner ``_worker_proc = None``,
             el ``if self._worker_proc is None: return`` ya corto-
             circuita el loop. Cualquier orden funciona; el
             elegido es seguro.
          3. Mata el subproceso con SIGTERM (``terminate()``) y, si
             no responde en 2s, SIGKILL (``kill()``). El timeout
             es defensivo: en Windows, ``terminate()`` ya es
             forzoso (``TerminateProcess``), pero en Linux un
             subproceso que esta bloqueado en un ``attach_portal``
             COM no responde a SIGTERM y necesitamos SIGKILL.
          4. Resuelve los futures pendientes con ``RuntimeError`` para
             que los callers en vuelo (p.ej. ``_send_to_persistent_worker``
             esperando una respuesta) no se queden colgados
             indefinidamente. La excepcion es la misma semantica que
             el timeout del ``asyncio.wait_for``: un error de
             comunicacion con el worker.
          5. Resetea ``_next_request_id`` a 0 para que el proximo
             worker empiece con IDs limpios. Defensivo: los IDs son
             locales al proceso, no hay riesgo de colision, pero
             deja el estado consistente con un gateway recien
             construido.

        Side effects:
          - ``self._reader_task = None``.
          - ``self._heartbeat_task = None``.
          - ``self._worker_proc = None``.
          - ``self._pending_responses`` vacio.
          - ``self._next_request_id = 0``.

        NO modifica ``self._connection_state``: eso es responsabilidad
        del caller (``reconnect()`` lo pone a ``"connecting"`` o
        ``"error"``; ``disconnect()`` lo pone a ``"disconnected"``).
        Asi el helper es reusable y la politica de estado vive en
        la API publica, no en el helper.
        """
        # 1. Cancela el reader_task (consume stdout y resuelve futures).
        if self._reader_task is not None and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                # ``CancelledError`` es el caso normal; cualquier otra
                # excepcion tambien se absorbe (cleanup best-effort:
                # el reader ya no es util, el proc va a morir).
                pass
        self._reader_task = None

        # 2. Cancela el heartbeat_task. El loop ya tiene
        # ``except asyncio.CancelledError: return`` que cierra limpio.
        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except (asyncio.CancelledError, Exception):
                pass
        self._heartbeat_task = None

        # 3. Mata el subproceso. ``returncode is None`` significa que
        # esta vivo; si ya tiene ``returncode`` fijado, el proc ya
        # murio y no hay que hacer nada.
        if self._worker_proc is not None and self._worker_proc.returncode is None:
            try:
                self._worker_proc.terminate()
                try:
                    # Esperamos hasta 2s. Si el proc no responde a
                    # SIGTERM (caso Linux + attach_portal bloqueado),
                    # escalamos a SIGKILL.
                    await asyncio.wait_for(
                        self._worker_proc.wait(), timeout=2.0
                    )
                except asyncio.TimeoutError:
                    self._worker_proc.kill()
                    await self._worker_proc.wait()
            except Exception:
                # best-effort: cualquier fallo en el shutdown del proc
                # (BrokenPipeError, ProcessLookupError, etc.) se
                # ignora. Lo que importa es que el gateway quede en
                # estado consistente para una nueva conexion.
                pass
        self._worker_proc = None
        _log.info("_kill_persistent_worker: subproceso MATADO (self._worker_proc=None)")

        # 4. Resuelve los futures pendientes con RuntimeError. Esto
        # desbloquea a cualquier ``_send_to_persistent_worker`` en vuelo
        # que estuviera esperando respuesta: en lugar de quedarse
        # colgado hasta el timeout (default 180s), recibe una
        # excepcion inmediata y puede relanzar / manejar.
        for fut in self._pending_responses.values():
            if not fut.done():
                fut.set_exception(RuntimeError("Worker desconectado"))
        self._pending_responses.clear()

        # 5. Reset del contador de IDs para que el proximo worker
        # empiece limpio. No afecta a la correccion (los IDs son
        # locales al proceso IT), solo a la consistencia del estado.
        self._next_request_id = 0

    async def connect(self) -> None:
        """Envia ``attach_portal`` al worker vivo y transiciona a ``"connected"``.

        API publica del boton "Conectar" del topbar (sept-2026,
        state machine refactor). El worker persistente esta vivo
        desde el startup (estado ``"idle"``); el operario decide
        cuando conectar via este metodo. El gateway:

          1. Marca el estado como ``"connecting"`` para que el
             frontend muestre el circulo amarillo.
          2. Envia el comando ``attach_portal`` al worker (que
             internamente hace ``ts.attach_portal(...)`` y devuelve
             el PID).
          3. Si OK, transiciona a ``"connected"`` e inicia el
             heartbeat.
          4. Si falla, transiciona a ``"error"`` y lanza
             ``TIAConnectionError``.

        Tras ``connect()`` exitoso, el estado es:
          - ``_connection_state = "connected"``.
          - Heartbeat task arrancado (monitorea ``get_process_id``).
          - ``_last_ping_ok`` actualizado al momento del connect.
          - ``_last_error = None``.

        Locking (auditoria X3, sept-2026): el ciclo set-state +
        send se ejecuta bajo ``self._worker_lock`` para serializar
        contra ``_dispatch_worker`` y contra otro ``connect``/
        ``disconnect`` concurrente. Sin el lock, dos connects
        concurrentes (doble-click del operario) pueden pisar el
        estado: el primero pone ``"connecting"``, el segundo ve
        ``"idle"`` (race) y reintenta, dejando al worker con dos
        attaches colgando.

        Raises:
            TIAConnectionError: si el gateway no es persistente
                (``persistent=False``), si el worker no responde, o
                si el attach inicial falla.
        """
        if not self._persistent:
            raise TIAConnectionError(
                "connect() solo aplica a gateway.persistent=True"
            )

        # Idempotencia: si ya estamos connected, no re-attacheamos.
        # Caso real: doble-click del operario en "Conectar", o el
        # frontend reintenta tras un timeout de UI. Lanzar un error
        # claro es preferible a un attach redundante (que dejaria
        # el RCW anterior colgando en el worker).
        if self._connection_state == "connected":
            raise TIAConnectionError(
                "Worker ya esta conectado a TIA Portal."
            )

        async with self._worker_lock:
            # Doble check bajo el lock: otro connect concurrente
            # pudo haber transicionado a connected entre el check
            # de arriba y la adquisicion del lock. Si pasa,
            # salimos limpio (idempotente).
            if self._connection_state == "connected":
                return  # no-op, ya estaba conectado

            # Limpiar last_error al inicio: si el operario reintenta
            # connect tras un error anterior, el siguiente
            # GET /tia/connection no debe mostrar el error viejo.
            self._last_error = None
            self._connection_state = "connecting"

            # Lazy start del subproceso worker si no esta vivo.
            # Esto cubre el caso ``start()`` no invocado (e.g. el
            # gateway se construyo pero nadie llamo a ``start()``
            # antes que el operario pulsara "Conectar").
            if (
                self._worker_proc is None
                or self._worker_proc.returncode is not None
            ):
                await self._start_persistent_worker()

            # Enviar el comando attach_portal al worker. Usa
            # ``_dispatch_worker`` con bypass de validacion de estado
            # (el attach_portal esta en la lista de comandos siempre
            # permitidos). El lock ya esta cogido aqui.
            try:
                result = await self._send_to_persistent_worker(
                    "attach_portal",
                    args={"mode": "WithGraphicalUserInterface"},
                    timeout_override=60.0,
                )
            except Exception as exc:
                _log.error(
                    "gateway.connect: attach_portal fallo (excepcion): "
                    "%s: %s",
                    type(exc).__name__,
                    exc,
                )
                self._connection_state = "error"
                if not self._last_error:
                    self._last_error = f"{type(exc).__name__}: {exc}"
                raise TIAConnectionError(
                    f"Connect fallo: {exc}"
                ) from exc

            # Validar la respuesta: el worker devuelve
            # ``{"pid": <int>}`` o ``{"error": "..."}``.
            if not isinstance(result, dict) or "error" in result:
                err_msg = (
                    result.get("error", "attach_portal retorno inesperado")
                    if isinstance(result, dict)
                    else f"attach_portal retorno no-dict: {result!r}"
                )
                self._connection_state = "error"
                self._last_error = err_msg
                raise TIAConnectionError(f"Connect fallo: {err_msg}")

            # Transicion a connected e inicio del heartbeat.
            self._connection_state = "connected"
            self._last_ping_ok = time.monotonic()
            _log.info(
                "gateway.connect: attach_portal OK (pid=%r, state=connected)",
                result.get("pid") if isinstance(result, dict) else None,
            )
            self._last_error = None
            # Cachear el PID del portal TIA Portal (lo devuelve el
            # worker en ``attach_portal``). Si la respuesta no trae
            # ``pid`` (worker con un build que no lo expone aun), se
            # queda en ``None`` y el router lo mostrara como ``null``.
            # ``disconnect()`` lo limpia a ``None``.
            self._last_portal_pid = (
                int(result["pid"]) if isinstance(result.get("pid"), int) else None
            )

            # Heartbeat solo se inicia si state == connected. Si ya
            # hay uno corriendo (re-connect rapido), no se duplica.
            if (
                self._heartbeat_task is None
                or self._heartbeat_task.done()
            ):
                self._heartbeat_task = asyncio.create_task(
                    self._heartbeat_loop()
                )

            # Deteccion del proyecto tras el attach (sept-2026).
            # Si el operario ya abrio un proyecto en TIA Portal antes
            # de pulsar "Conectar", este es el momento de preguntar
            # por el path y popular ``_project_path``. Si difiere del
            # ultimo conocido, marca ``_project_changed`` y limpia
            # caches (cambio de proyecto = datos stale).
            #
            # NO se hace bajo el lock: ``_detect_project_change``
            # adquiere su propio ``async with self._worker_lock``
            # internamente. El lock ya esta cogido aqui, asi que
            # ``_detect_project_change`` reentra y se serializa.
            # (La reentrada en ``asyncio.Lock`` es segura: el mismo
            # task que ya lo tiene puede adquirirlo de nuevo sin
            # deadlock.)
            try:
                await self._detect_project_change()
            except Exception:
                # Best-effort: si falla (e.g. TIA sin proyecto
                # abierto, timeout), no es bloqueante. La siguiente
                # operacion del operario reintentara.
                pass

    async def disconnect(self) -> None:
        """Envia ``detach_portal`` al worker vivo y transiciona a ``"idle"``.

        API publica del boton "Desconectar" del topbar (sept-2026,
        state machine refactor). A diferencia del round anterior,
        este metodo NO mata el subproceso worker: el worker sigue
        vivo en estado ``"idle"``, listo para un futuro ``connect()``
        sin pagar el coste de un nuevo subproceso (~200 MB con
        ``siemens_tia_scripting.pyd`` cargado).

        El gateway:

          1. Marca el estado como ``"disconnected"`` (transitorio
             mientras se hace el detach).
          2. Cancela el heartbeat task (en connected no tiene
             sentido, solo gastaria round-trips contra un portal
             muerto).
          3. Envia ``detach_portal`` al worker. El worker hace
             ``portal.detach()`` best-effort y queda en idle.
          4. Limpia caches (``_cache``, ``_bloques_cache``) y
             resetea ``_project_path = None`` (cambio de
             proyecto implicito: el siguiente connect puede abrir
             un proyecto distinto).

        Tras ``disconnect()``, el estado es:
          - ``_connection_state = "idle"``.
          - ``_last_error = None`` (limpiamos errores transitorios).
          - ``_project_path = None``.
          - ``_project_changed = False``.
          - ``_cache`` y ``_bloques_cache`` vacios.
          - Heartbeat task cancelado.
          - ``_worker_proc``, ``_reader_task``, ``_pending_responses``,
            ``_next_request_id``: intactos (el worker sigue vivo).

        Locking (auditoria X3, sept-2026): el ciclo se ejecuta bajo
        ``self._worker_lock`` para serializar contra
        ``_dispatch_worker`` y contra otro ``connect``/``disconnect``
        concurrente.

        Raises:
            TIAConnectionError: si el gateway no es persistente.
        """
        if not self._persistent:
            raise TIAConnectionError(
                "disconnect() solo aplica a gateway.persistent=True"
            )

        _log.info(
            "gateway.disconnect: llamado (state=%r, worker_alive=%s)",
            getattr(self, "_connection_state", None),
            self.is_worker_alive(),
        )

        # Transición OPTIMISTA a ``"idle"`` ANTES del lock (sept-2026
        # round 3, fix de auditoría profunda del worker).
        #
        # Caso real (audit, 12:11:41/12:11:44 en logs/zc_tray.log):
        # el ``_worker_lock`` podía ser retentenido por un comando
        # en vuelo (``get_plcs``/``get_project_info`` con
        # ``ZC_GATEWAY_TIMEOUT=300s``, o un ``compile_plc`` largo).
        # El ``disconnect()`` se quedaba bloqueado en el
        # ``async with self._worker_lock`` durante segundos o minutos.
        # Mientras tanto, el frontend veía ``state="connected"``
        # aunque el disconnect estuviera en cola, y el operario
        # pulsaba "Desconectar" de nuevo (doble disconnect, ambos
        # viendo ``state="connected"``).
        #
        # Ahora: la transición a ``"idle"`` se hace ANTES del lock,
        # de forma que el siguiente ``GET /tia/connection`` la vea
        # inmediatamente, aunque el cleanup tarde. El heartbeat tiene
        # un guard (línea 916) para no pisar ``"idle"`` con
        # ``"connected"`` durante esta ventana.
        #
        # Riesgo: si el ``detach_portal`` falla (worker ya muerto,
        # reader muerto, etc.), el estado queda en ``"idle"`` pero el
        # portal puede seguir attached en el worker. Esto es
        # aceptable porque: (a) el cleanup ya era best-effort
        # (línea 1556-1566 absorbe excepciones), (b) el operario
        # puede reintentar y el heartbeat lo detectaría.
        self._connection_state = "idle"
        self._last_error = None
        # Reset del path: el siguiente connect puede abrir un
        # proyecto distinto. Se hace aquí (fuera del lock) para
        # que el frontend lo vea inmediatamente, no cuando el
        # cleanup termine.
        self._project_path = None
        self._project_changed = False
        # El PID del portal deja de ser válido. (El detach puede
        # aún no haberse enviado, pero la transición optimista ya
        # tiene sentido: el portal YA no es accesible para el
        # gateway desde este momento.)
        self._last_portal_pid = None
        _log.info(
            "gateway.disconnect: state=idle (transicion optimista, "
            "cleanup en background)"
        )

        async with self._worker_lock:
            # Cancela el heartbeat task si esta corriendo. El loop
            # ya tiene ``except asyncio.CancelledError: return`` que
            # cierra limpio. NO tocamos ``_heartbeat_task`` aqui:
            # eso lo hara el lock cleanup abajo o un futuro
            # ``connect()`` (chequea ``done()`` antes de re-lanzar).
            #
            # IMPORTANTE: si la cancelación tarda (heartbeat
            # esperando al lock con un ping en vuelo, hasta 10s),
            # el estado YA está en ``"idle"`` (transición
            # optimista de arriba), así que el frontend ve feedback
            # inmediato. El guard del heartbeat (línea 916) evita
            # que un ping tardío pise el ``"idle"``.
            if (
                self._heartbeat_task is not None
                and not self._heartbeat_task.done()
            ):
                self._heartbeat_task.cancel()
                try:
                    await self._heartbeat_task
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    # Logueamos el warning: una excepción no
                    # esperada en el cancel puede indicar un bug
                    # del heartbeat (antes se absorbía
                    # silenciosamente, perdiendo diagnóstico).
                    _log.warning(
                        "gateway.disconnect: heartbeat task no se "
                        "cancelo limpiamente: %s: %s",
                        type(exc).__name__,
                        exc,
                    )
            self._heartbeat_task = None

            # Envia detach_portal al worker. Usa el bypass de
            # validacion de estado (detach esta en la lista de
            # comandos siempre permitidos). El lock ya esta cogido
            # aqui, asi que la llamada es directa.
            #
            # Si el worker no esta vivo o el reader murio, NO
            # podemos enviar. Es best-effort: el estado ya está
            # en ``"idle"`` (transición optimista), así que el
            # frontend muestra feedback correcto. Aquí solo
            # intentamos hacer el detach limpio por el portal.
            try:
                if (
                    self._worker_proc is not None
                    and self._worker_proc.returncode is None
                    and self._reader_task is not None
                    and not self._reader_task.done()
                ):
                    await self._send_to_persistent_worker(
                        "detach_portal",
                        args={},
                        timeout_override=10.0,
                    )
            except Exception as exc:
                # No propagamos: disconnect() es la operacion
                # inversa de connect() y debe ser robusto a fallos
                # del worker. El estado del gateway refleja "idle"
                # de todos modos (transición optimista de arriba).
                _log.warning(
                    "disconnect(): detach_portal fallo (%s: %s); "
                    "el estado ya esta en idle, cleanup best-effort.",
                    type(exc).__name__,
                    exc,
                )

            # Limpiar caches: cambio de estado del portal invalida
            # todo lo cacheado (los PLCs/bloques pueden ser
            # distintos tras un nuevo connect).
            self._cache.clear()
            try:
                self._clear_bloques_cache()
            except Exception:
                pass

    async def reconnect(self) -> None:
        """Equivalente a ``disconnect()`` seguido de ``connect()``.

        API publica de compatibilidad (sept-2026, state machine
        refactor). Antes este metodo mataba el worker y lo
        relanzaba; ahora es un wrapper de ``disconnect()`` +
        ``connect()`` con lock unico que cubre todo el ciclo para
        serializar contra ``_dispatch_worker`` y contra otro
        ``reconnect``/``disconnect`` concurrente (auditoria X3).

        Si el connect falla, el gateway queda en estado ``"error"``
        con ``_last_error`` poblado, listo para que el frontend
        muestre el circulo rojo y el operario sepa que el
        reconectar no funciono.

        Raises:
            TIAConnectionError: si el gateway no es persistente
                (``persistent=False``) o si el connect falla.
        """
        if not self._persistent:
            raise TIAConnectionError(
                "reconnect() solo aplica a gateway.persistent=True"
            )

        # Adquirimos ``self._worker_lock`` para serializar el ciclo
        # disconnect+connect contra ``_dispatch_worker`` y contra
        # otro ``reconnect``/``disconnect`` concurrente. Ver
        # ``disconnect()`` y ``connect()`` para el detalle de cada
        # fase; aqui solo orquestamos.
        async with self._worker_lock:
            # 1. Disconnect: detach + cache clear + heartbeat cancel.
            #    El subproceso worker sigue vivo.
            #    (El antiguo "disconnected" ya no existe en el state
            #    machine refactorizado; usamos "idle" como transicion
            #    antes de connect() en el mismo lock.)
            self._connection_state = "idle"
            self._last_error = None
            if (
                self._heartbeat_task is not None
                and not self._heartbeat_task.done()
            ):
                self._heartbeat_task.cancel()
                try:
                    await self._heartbeat_task
                except (asyncio.CancelledError, Exception):
                    pass
            self._heartbeat_task = None
            try:
                if (
                    self._worker_proc is not None
                    and self._worker_proc.returncode is None
                    and self._reader_task is not None
                    and not self._reader_task.done()
                ):
                    await self._send_to_persistent_worker(
                        "detach_portal",
                        args={},
                        timeout_override=10.0,
                    )
            except Exception:
                # Best-effort: si el detach falla, el connect
                # siguiente sobrescribira el portal attached de
                # todos modos.
                pass
            self._cache.clear()
            try:
                self._clear_bloques_cache()
            except Exception:
                pass
            self._project_path = None
            self._project_changed = False

            # 2. Connect: attach + heartbeat start + project detect.
            #    Lazy start del subproceso si no esta vivo.
            self._connection_state = "connecting"
            if (
                self._worker_proc is None
                or self._worker_proc.returncode is not None
            ):
                try:
                    await self._start_persistent_worker()
                except Exception as exc:
                    self._connection_state = "error"
                    if not self._last_error:
                        self._last_error = f"{type(exc).__name__}: {exc}"
                    raise TIAConnectionError(
                        f"Reconnect fallo: {exc}"
                    ) from exc

            try:
                result = await self._send_to_persistent_worker(
                    "attach_portal",
                    args={"mode": "WithGraphicalUserInterface"},
                    timeout_override=60.0,
                )
            except Exception as exc:
                self._connection_state = "error"
                if not self._last_error:
                    self._last_error = f"{type(exc).__name__}: {exc}"
                raise TIAConnectionError(
                    f"Reconnect fallo: {exc}"
                ) from exc

            if not isinstance(result, dict) or "error" in result:
                err_msg = (
                    result.get("error", "attach_portal retorno inesperado")
                    if isinstance(result, dict)
                    else f"attach_portal retorno no-dict: {result!r}"
                )
                self._connection_state = "error"
                self._last_error = err_msg
                raise TIAConnectionError(f"Reconnect fallo: {err_msg}")

            self._connection_state = "connected"
            self._last_ping_ok = time.monotonic()
            self._last_error = None
            if (
                self._heartbeat_task is None
                or self._heartbeat_task.done()
            ):
                self._heartbeat_task = asyncio.create_task(
                    self._heartbeat_loop()
                )
            try:
                await self._detect_project_change()
            except Exception:
                pass

    def get_metrics(self) -> dict[str, dict[str, float | int]]:
        """Devuelve estadisticas de timing acumuladas por comando.

        Para cada comando ejecutado por _dispatch_worker, devuelve:
          - count: numero de veces invocado.
          - min_ms: tiempo minimo observado (entero, ms).
          - max_ms: tiempo maximo observado (entero, ms).
          - avg_ms: tiempo medio (entero, ms, redondeado).

        El dict es una COPIA del estado interno: mutar el retorno NO
        afecta a self._metrics. Caso de uso principal: exponer
        las stats en un endpoint de diagnostico o en un comando
        MCP para que el operario pueda confirmar la hipotesis de
        que ts.attach_portal() es la operacion dominante del
        worker OT (audit 1.3, _plan/10).

        El gateway mantiene las metricas por instancia (cada
        TIAProcessGateway tiene su propio dict). Tests que
        crean gateways frescos parten de un dict vacio; en
        produccion las metricas se acumulan durante toda la vida
        del proceso IT.
        """
        return {
            cmd: {
                "count": len(times),
                "min_ms": round(min(times)),
                "max_ms": round(max(times)),
                "avg_ms": round(sum(times) / len(times)),
            }
            for cmd, times in self._metrics.items()
        }

    async def ping(self) -> dict[str, Any]:
        """Health check del worker OT. Retorna ``{ok, pid?, error?}``.

        Primitiva del heartbeat (PR 4) y de la reconexión manual (PR 6)
        del design doc del worker persistente
        (``_plan/12_worker_persistent_design.md`` §3.3).

        Es un wrapper sin caché: cada llamada paga el ciclo end-to-end
        del subproceso (incluso si el portal ya está attached) porque
        el caso de uso es detectar caídas del proceso TIA, no lecturas
        ligeras. El gateway acumula el timing en ``_metrics["ping"]``
        igual que cualquier otro comando.

        Returns:
            ``{"ok": True, "pid": <int>}`` si TIA Portal responde.
            ``{"ok": False, "error": "..."}`` si no hay portal o el
            proceso TIA está cerrado (excepción COM/RPC).
        """
        return await self._dispatch_worker("ping", args={})

    async def get_plcs(self, force_refresh: bool = False) -> list[str]:
        """Obtiene los PLCs disponibles utilizando la caché de memoria IT.

        ``timeout_override=10.0`` (sept-2026 round 3, fix de
        auditoría): el polling del frontend hace ``GET /tia/connection``
        cada 2s, y este método se invoca desde el router para
        enriquecer la respuesta. Sin el override, el default es
        ``ZC_GATEWAY_TIMEOUT=300s``, lo que permitía que un comando
        lento retentuviera el ``_worker_lock`` durante minutos y
        bloqueara el ``disconnect()`` (causa raíz del bug del doble
        disconnect en producción, audit 2026-09-06). 10s es más que
        suficiente para un ``list_plcs`` en condiciones normales.
        """
        cache_key = "plcs"
        if not force_refresh and cache_key in self._cache:
            return self._cache[cache_key]

        plcs = await self._dispatch_worker("list_plcs", timeout_override=10.0)
        self._cache[cache_key] = plcs
        return plcs

    async def get_project_info(self, force_refresh: bool = False) -> dict[str, Any]:
        """Devuelve propiedades básicas del proyecto TIA activo (con caché IT).

        Caché en ``self._cache["project_info"]`` con la misma política que
        ``get_plcs`` (lectura ligera, ``force_refresh=True`` la ignora). Se
        invalida junto con el resto en ``clear_cache()`` (que ya limpia
        ``self._cache`` entero y se invoca en ``open_project`` /
        ``close_project``).

        ``timeout_override=10.0`` (sept-2026 round 3, fix de
        auditoría): ver ``get_plcs()``. Sin este override, un
        ``get_project_info`` lento podía retentener el
        ``_worker_lock`` durante minutos y bloquear el
        ``disconnect()``.

        Args:
            force_refresh: Si es ``True``, ignora la caché y relee de TIA.

        Returns:
            ``dict`` con al menos ``name``; opcionalmente ``path``,
            ``author``, ``creation_time``, ``last_modified``,
            ``last_modified_by`` y ``version`` (omitidas si no están
            disponibles en el proyecto activo o si su lectura lanza).
        """
        cache_key = "project_info"
        if not force_refresh and cache_key in self._cache:
            return self._cache[cache_key]

        info = await self._dispatch_worker("get_project_info", timeout_override=10.0)
        self._cache[cache_key] = info
        return info

    async def get_blocks(
        self, plc_name: str, folder_path: str | None = None, force_refresh: bool = False
    ) -> list[str]:
        """Obtiene los bloques de programa de un PLC con caché dirigida."""
        cache_key = f"blocks::{plc_name}::{folder_path or ''}"
        if not force_refresh and cache_key in self._cache:
            return self._cache[cache_key]

        blocks = await self._dispatch_worker(
            "list_blocks", {"plc_name": plc_name, "folder_path": folder_path}
        )
        self._cache[cache_key] = blocks
        return blocks

    async def scan_plc_blocks(
        self, plc_name: str, force_refresh: bool = False
    ) -> BloqueCache:
        """Escanea recursivamente TODOS los bloques, tag tables y UDTs de un PLC.

        Devuelve un ``BloqueCache`` reconstruido a partir del payload
        primitivo del worker. Cachea en ``self._bloques_cache`` (separado
        de ``self._cache`` por su ciclo de vida distinto: el scan es
        pesado, la lista plana de bloques es ligera).

        Args:
            plc_name: nombre del PLC a escanear.
            force_refresh: si ``True``, ignora el cache y reescanea.

        Returns:
            ``BloqueCache`` con ``blocks``, ``tag_tables`` y ``udts``
            indexados por ``BloquePLC.normalize_name``. Los UDTs viven
            en su propio slot (``udts``) y nunca se mezclan con
            ``blocks`` (invariante del DTO).
        """
        if not force_refresh and plc_name in self._bloques_cache:
            return self._bloques_cache[plc_name]

        result = await self._dispatch_worker(
            "scan_blocks", {"plc_name": plc_name}
        )
        if not isinstance(result, dict):
            raise RuntimeError(
                f"Respuesta inesperada del worker para 'scan_blocks': {type(result).__name__}"
            )

        blocks_raw = result.get("blocks", []) or []
        tag_tables_raw = result.get("tag_tables", []) or []
        udts_raw = result.get("udts", []) or []
        blocks: dict[str, BloquePLC] = {
            BloquePLC.normalize_name(b["nombre"]): BloquePLC(
                nombre=b["nombre"],
                numero=int(b.get("numero", 0)),
                tipo=str(b.get("tipo", "OTHER")),
                ruta=str(b.get("ruta", "")),
            )
            for b in blocks_raw
            if b.get("nombre")
        }
        tag_tables: dict[str, BloquePLC] = {
            BloquePLC.normalize_name(t["nombre"]): BloquePLC(
                nombre=t["nombre"],
                numero=int(t.get("numero", 0)),
                tipo=str(t.get("tipo", "OTHER")),
                ruta=str(t.get("ruta", "")),
            )
            for t in tag_tables_raw
            if t.get("nombre")
        }
        udts: dict[str, BloquePLC] = {
            BloquePLC.normalize_name(u["nombre"]): BloquePLC(
                nombre=u["nombre"],
                numero=int(u.get("numero", 0)),
                tipo=str(u.get("tipo", "OTHER")),
                ruta=str(u.get("ruta", "")),
            )
            for u in udts_raw
            if u.get("nombre")
        }
        # Reconstruimos ``scanned_at`` desde el payload si esta presente
        # (formato ISO-8601). Si no, usamos ``now(UTC)`` como fallback
        # defensivo (no deberia pasar, pero el contrato lo permite).
        scanned_at_raw = result.get("scanned_at")
        if isinstance(scanned_at_raw, str):
            try:
                from datetime import datetime as _dt
                scanned_at = _dt.fromisoformat(scanned_at_raw)
            except ValueError:
                from datetime import datetime as _dt, timezone as _tz
                scanned_at = _dt.now(_tz.utc)
        else:
            from datetime import datetime as _dt, timezone as _tz
            scanned_at = _dt.now(_tz.utc)

        cache = BloqueCache(
            blocks=blocks,
            tag_tables=tag_tables,
            udts=udts,
            plc_name=plc_name,
            scanned_at=scanned_at,
        )
        self._bloques_cache[plc_name] = cache
        return cache

    def get_bloques_cache(self, plc_name: str) -> "BloqueCache | None":
        """Devuelve el ``BloqueCache`` cacheado para ``plc_name`` o
        ``None`` si no se ha escaneado todavía.

        Importante: este método es **lectura pura**. NO triggerea un
        scan contra TIA (eso es responsabilidad de
        ``scan_plc_blocks``). Si el PLC no ha sido escaneado, el
        método devuelve ``None`` para que el caller pueda distinguir
        entre "cache vacía porque se acaba de invalidar" y "cache
        vacía porque el operario no ha escaneado este PLC".

        Uso típico: routers que necesitan validar precondiciones
        (e.g. "existen los DBs X, Y, Z en el PLC?") sin coste de
        red. Si el cache es ``None``, el router puede o bien
        devolver un 409 con mensaje accionable, o bien delegar en
        ``scan_plc_blocks`` para poblarlo (con coste de latencia).

        Si ``plc_name`` es vacío (``""``), devuelve ``None``
        directamente: no tiene sentido buscar en el cache un PLC
        sin nombre.
        """
        if not plc_name:
            return None
        return self._bloques_cache.get(plc_name)

    def _clear_bloques_cache(self, plc_name: str | None = None) -> None:
        """Invalida el cache de bloques de un PLC o todos.

        Llamado en ``open_project`` y ``close_project`` para reflejar
        cambios de proyecto. Tambien desde ``clear_cache`` (que ya
        vacia todo el estado IT).
        """
        if plc_name is None:
            self._bloques_cache.clear()
            return
        self._bloques_cache.pop(plc_name, None)

    def clear_cache(self) -> None:
        """Limpia el estado IT almacenado en memoria."""
        self._cache.clear()
        # Tambien vaciamos el cache especializado de bloques; un
        # ``clear_cache`` global indica "estado del proyecto invalido".
        self._bloques_cache.clear()

    async def compile_plc(self, plc_name: str) -> bool:
        """Compila el software del PLC devolviendo el booleano nativo de Siemens.

        Semántica documentada (TIA Scripting API V1.2.1, sección 2.2.11):
          - True  -> La compilación tiene errores.
          - False -> La compilación NO tiene errores (éxito).
        La evaluación semántica para el usuario final ocurre en la capa MCP.
        """
        return await self._dispatch_worker(
            "compile_plc", {"plc_name": plc_name}
        )

    async def export_blocks_sd(self, plc_name: str, target_dir: str) -> str:
        """Exporta los bloques de programa del PLC a archivos Simatic Source Documents (.s7dcl) en target_dir.

        Fail-Fast: target_dir debe ser una ruta absoluta. No se almacena en caché
        porque es una acción mutable que vuelca contenido a disco.
        """
        if not Path(target_dir).is_absolute():
            raise ValueError(
                f"target_dir debe ser una ruta absoluta. Recibido: '{target_dir}'"
            )

        return await self._dispatch_worker(
            "export_blocks_sd",
            {"plc_name": plc_name, "target_dir": target_dir},
        )

    async def export_udts_sd(self, plc_name: str, target_dir: str) -> str:
        """Exporta los UDTs (User Data Types) del PLC a archivos Simatic Source Documents (.s7dcl) en target_dir.

        Fail-Fast: target_dir debe ser una ruta absoluta. No se almacena en caché.
        """
        if not Path(target_dir).is_absolute():
            raise ValueError(
                f"target_dir debe ser una ruta absoluta. Recibido: '{target_dir}'"
            )

        return await self._dispatch_worker(
            "export_udts_sd",
            {"plc_name": plc_name, "target_dir": target_dir},
        )

    async def export_plc_tags_xml(
        self,
        plc_name: str,
        target_dir: str,
        table_names: list[str] | None = None,
    ) -> str:
        """Exporta las tablas de variables (PLC tags) del PLC como XML SimaticML.

        Fail-Fast: target_dir debe ser una ruta absoluta. No se almacena en caché
        (acción mutable que vuelca archivos a disco).

        Args:
            plc_name: nombre del PLC destino.
            target_dir: ruta absoluta del directorio donde escribir los XML.
            table_names: si se pasa, SOLO se exportan las tablas cuyos
                nombres esten en esta lista. Si es ``None`` (default), se
                exportan TODAS las tablas del PLC (back-compat con el
                comportamiento previo).
        """
        if not Path(target_dir).is_absolute():
            raise ValueError(
                f"target_dir debe ser una ruta absoluta. Recibido: '{target_dir}'"
            )

        args: dict[str, Any] = {"plc_name": plc_name, "target_dir": target_dir}
        if table_names is not None:
            args["table_names"] = list(table_names)

        return await self._dispatch_worker("export_plc_tags_xml", args)

    async def attach_portal(self) -> bool:
        """Hot-attach a una instancia YA EJECUTÁNDOSE de TIA Portal.

        Escenario típico: el operario ya tiene TIA Portal abierto; el
        gateway se acopla a esa instancia vía ``ts.attach_portal()``
        (Manual V1.2.1 §2.4.2). No abre proyecto — solo establece la
        conexión COM.

        Returns:
            ``True`` si el acople fue exitoso.
        """
        return await self._dispatch_worker("attach_portal")

    async def open_new_portal(self, project_file_path: str) -> bool:
        """Cold start: lanza TIA Portal NUEVO y abre un proyecto.

        Sigue el Manual V1.2.1 §2.4.1:
          1. ``ts.open_portal()`` → instancia nueva del portal.
          2. ``portal.open_project(project_file_path)`` → abre proyecto.

        Args:
            project_file_path: Ruta absoluta al archivo ``.apxx``.

        Returns:
            ``True`` si la operación fue exitosa.
        """
        if not Path(project_file_path).is_absolute():
            raise ValueError(
                f"project_file_path debe ser absoluto. Recibido: '{project_file_path}'"
            )
        return await self._dispatch_worker(
            "open_new_portal",
            {"project_file_path": project_file_path},
        )

    async def open_project(self, project_file_path: str) -> None:
        """Abre un proyecto TIA Portal. Invalida caché del gateway (cambio de proyecto)."""
        if not Path(project_file_path).is_absolute():
            raise ValueError(
                f"project_file_path debe ser absoluto. Recibido: '{project_file_path}'"
            )
        await self._dispatch_worker(
            "open_project", {"project_file_path": project_file_path}
        )
        self.clear_cache()  # Cambio de proyecto invalida todo el estado IT cacheado.
        # ``clear_cache`` ya vacia ``self._bloques_cache``; llamada
        # explicita por simetria con la operacion (defensiva ante
        # futuros cambios de ``clear_cache`` que omitan caches
        # especializados).
        self._clear_bloques_cache()

    async def save_project(self) -> None:
        await self._dispatch_worker("save_project", {})

    async def close_project(self) -> None:
        await self._dispatch_worker("close_project", {})
        self.clear_cache()
        self._clear_bloques_cache()

    async def import_blocks_sd(
        self,
        plc_name: str,
        import_dir: str,
        target_folder: str | None = None,
    ) -> bool:
        """Importa bloques de programa en formato Simatic Source Documents (.s7dcl) desde el disco al PLC.

        Fail-Fast: import_dir debe ser una ruta absoluta. La validación
        final de existencia del directorio la hace el worker antes de
        invocar el método COM (TIA Portal lanza excepciones graves si el
        directorio no existe; ver manual §2.2.23).
        """
        if not Path(import_dir).is_absolute():
            raise ValueError(
                f"import_dir debe ser una ruta absoluta. Recibido: '{import_dir}'"
            )

        return await self._dispatch_worker(
            "import_blocks_sd",
            {
                "plc_name": plc_name,
                "import_dir": import_dir,
                "target_folder": target_folder,
            },
        )

    async def import_plc_tags_xml(
        self,
        plc_name: str,
        import_dir: str,
        target_folder: str | None = None,
    ) -> bool:
        """Importa tablas de variables (PLC tags) en formato XML al PLC.

        Fail-Fast: import_dir debe ser una ruta absoluta. La validación
        final de existencia del directorio la hace el worker antes de
        invocar el método COM (manual §2.2.24).
        """
        if not Path(import_dir).is_absolute():
            raise ValueError(
                f"import_dir debe ser una ruta absoluta. Recibido: '{import_dir}'"
            )

        return await self._dispatch_worker(
            "import_plc_tags_xml",
            {
                "plc_name": plc_name,
                "import_dir": import_dir,
                "target_folder": target_folder,
            },
        )

    async def export_block(
        self, plc_name: str, block_name: str, target_dir: str
    ) -> str:
        """Exporta un único bloque como .scl. No cachea (operación mutable)."""
        if not Path(target_dir).is_absolute():
            raise ValueError(
                f"target_dir debe ser absoluto. Recibido: '{target_dir}'"
            )
        return await self._dispatch_worker(
            "export_block",
            {"plc_name": plc_name, "block_name": block_name, "target_dir": target_dir},
        )

    async def import_block(
        self, plc_name: str, import_dir: str, target_folder: str | None = None
    ) -> bool:
        """Importa un único bloque (.scl) al PLC."""
        if not Path(import_dir).is_absolute():
            raise ValueError(
                f"import_dir debe ser absoluto. Recibido: '{import_dir}'"
            )
        return await self._dispatch_worker(
            "import_block",
            {
                "plc_name": plc_name,
                "import_dir": import_dir,
                "target_folder": target_folder,
            },
        )

    async def export_tag_table(
        self, plc_name: str, table_name: str, target_dir: str
    ) -> str:
        """Exporta una única PlcTagTable como XML. No cachea."""
        if not Path(target_dir).is_absolute():
            raise ValueError(
                f"target_dir debe ser absoluto. Recibido: '{target_dir}'"
            )
        return await self._dispatch_worker(
            "export_tag_table",
            {"plc_name": plc_name, "table_name": table_name, "target_dir": target_dir},
        )

    async def import_tag_table(
        self, plc_name: str, import_dir: str, target_folder: str | None = None
    ) -> bool:
        """Importa una única PlcTagTable (XML) al PLC."""
        if not Path(import_dir).is_absolute():
            raise ValueError(
                f"import_dir debe ser absoluto. Recibido: '{import_dir}'"
            )
        return await self._dispatch_worker(
            "import_tag_table",
            {
                "plc_name": plc_name,
                "import_dir": import_dir,
                "target_folder": target_folder,
            },
        )

    async def get_user_constants(
        self, plc_name: str, table_name: str
    ) -> dict[str, str]:
        """Inspecciona PlcUserConstant de una tabla. Devuelve {value: name}."""
        return await self._dispatch_worker(
            "get_user_constants",
            {"plc_name": plc_name, "table_name": table_name},
        )

    async def update_user_constant_value(
        self, plc_name: str, table_name: str, constant_name: str, new_value: int
    ) -> bool:
        """Actualiza el valor de una PlcUserConstant. Invalida caché de bloques."""
        result = await self._dispatch_worker(
            "update_user_constant_value",
            {
                "plc_name": plc_name,
                "table_name": table_name,
                "constant_name": constant_name,
                "new_value": new_value,
            },
        )
        self.clear_cache()  # Cambio de N_MAX puede afectar dimensiones de DBs.
        return result

    async def update_user_constant_name(
        self, plc_name: str, table_name: str, current_name: str, new_name: str
    ) -> bool:
        """Renombra una PlcUserConstant."""
        return await self._dispatch_worker(
            "update_user_constant_name",
            {
                "plc_name": plc_name,
                "table_name": table_name,
                "current_name": current_name,
                "new_name": new_name,
            },
        )

    async def delete_user_constant(
        self, plc_name: str, table_name: str, constant_name: str
    ) -> bool:
        """Borra una PlcUserConstant."""
        return await self._dispatch_worker(
            "delete_user_constant",
            {
                "plc_name": plc_name,
                "table_name": table_name,
                "constant_name": constant_name,
            },
        )

    async def execute_transactional_batch(
        self, operations: list[dict[str, Any]], undo_text: str = "Batch Operation"
    ) -> dict[str, Any]:
        """Ejecuta un lote de comandos en una transacción atómica del motor OT.

        Delega en el worker `_cmd_execute_transactional_batch`, que aísla
        toda la cadena bajo `project.start_transaction()` / `end_transaction`
        y aplica rollback automático si cualquier operación falla. Esto
        garantiza atomicidad en el historial de TIA Portal (Undo) y elimina
        estados intermedios inconsistentes.

        Args:
            operations: Lista de operaciones con la forma
                        [{"command": str, "args": dict}, ...]. El nombre
                        del comando omite el prefijo 'tia_' (uso interno).
            undo_text:  Etiqueta visible en el historial de Undo de TIA Portal.

        Returns:
            dict[str, Any] con {"success": True, "operations_executed": int}.

        Raises:
            RuntimeError: Si la lista está vacía, contiene un comando
                          desconocido o prohibido, o si cualquier operación
                          interna falla (incluye rollback automático).

        Timeout dinámico:
            El stage ``open_transaction`` del worker cubre la transacción
            COM completa. Con 50-100 ops en un PLC real puede tardar
            1-3 min; con 200+ ops, hasta 7-10 min. Aplicamos la fórmula
            ``max(default, num_ops × 5s)`` para cubrirnos las espaldas
            sin pasarnos: 5s por op es ~10× el tiempo medio observado
            en PLCs reales, así que tenemos margen sin pagar timeouts
            absurdos en operaciones pequeñas. El default
            (``DEFAULT_GATEWAY_TIMEOUT``) actúa como suelo: una sola op
            no baja del default.
        """
        per_op_seconds = 5.0
        n_ops = max(1, len(operations))
        dynamic_timeout = max(self._timeout, per_op_seconds * n_ops)
        return await self._dispatch_worker(
            "execute_transactional_batch",
            {"operations": operations, "undo_text": undo_text},
            timeout_override=dynamic_timeout,
        )

    async def commit_devices_sync(
        self,
        plc_name: str,
        nmax_ops: list[dict[str, Any]],
        rename_ops: list[dict[str, Any]],
        device_changes: list[dict[str, Any]],
        work_dir: str,
        undo_text: str = "Sync dispositivos (N_MAX + devices)",
    ) -> dict[str, Any]:
        """Commit atomico N_MAX + renames + devices en UNA sola transaccion TIA.

        Wrapper sobre ``execute_transactional_batch`` que emite UN SOLO op
        (``commit_devices_sync``) el cual, dentro del worker, abre una
        unica ``start_transaction`` y aplica:

          1. N_MAX online (``update_user_constant_value`` por cada uno).
          2. Renames online (``update_user_constant_name`` por cada uno).
          3. Devices: por cada tabla con adds o removes, export selectivo
             → edit XML offline (con ``TagTableModifier``) → import selectivo.

        Si CUALQUIER paso falla, el worker ejecuta
        ``end_transaction(rollback=True)`` y la excepcion se propaga al
        caller. El ``timeout_override`` se calcula como en
        ``execute_transactional_batch`` para cubrir el peor caso de
        N_MAX + renames + devices en un PLC grande.

        Args:
            plc_name: nombre del PLC destino en TIA.
            nmax_ops: lista de ``{table_name, constant_name, new_value}``
                (online).
            rename_ops: lista de ``{table_name, current_name, new_name}``
                (online).
            device_changes: lista de ``{table_name, tia_folder, adds,
                removes}`` (offline, solo tablas con adds o removes).
            work_dir: ruta absoluta del directorio donde el worker escribe
                los XML exportados/modificados.
            undo_text: texto del historial Undo de TIA.

        Returns:
            Dict con shape de ``execute_transactional_batch``:
            ``{"success": True, "operations_executed": int, "details": [...]}``.
        """
        if not Path(work_dir).is_absolute():
            raise ValueError(
                f"work_dir debe ser una ruta absoluta. Recibido: '{work_dir}'"
            )

        # Estimacion de ops para el timeout dinamico: N_MAX + renames +
        # 3 ops por cada device_change (export + edit + import).
        estimated_ops = 2  # start + end transaction
        estimated_ops += len(nmax_ops)
        estimated_ops += len(rename_ops)
        estimated_ops += 3 * len(device_changes)
        per_op_seconds = 5.0
        dynamic_timeout = max(self._timeout, per_op_seconds * estimated_ops)

        return await self._dispatch_worker(
            "execute_transactional_batch",
            {
                "operations": [{
                    "command": "commit_devices_sync",
                    "args": {
                        "plc_name": plc_name,
                        "undo_text": undo_text,
                        "work_dir": work_dir,
                        "nmax_ops": list(nmax_ops),
                        "rename_ops": list(rename_ops),
                        "device_changes": list(device_changes),
                    },
                }],
                "undo_text": undo_text,
            },
            timeout_override=dynamic_timeout,
        )

    async def update_disp_instance_comments_batch(
        self,
        plc_name: str,
        dispositivos_slot_maps: dict[str, dict[int, str]],
        target_folder: str,
        db_names: dict[str, str],
        db_array_names: dict[str, str],
        *,
        area_id: str = "alimentacion",
        contexto: str = "dispositivos",
        subestado: str = "exports",
        build_cache_dir: Path | None = None,
        undo_text: str = "Sync comentarios dispositivos",
    ) -> dict[str, Any]:
        """Aplica los comentarios por instancia a los 6 DBs de dispositivos
        en una sola transacción TIA con rollback atómico.

        Misma convención que ``DispSyncInstancesUseCase``: el directorio
        de trabajo es ``<build_cache>/<area_id>/<contexto>/<subestado>/``
        (con ``build_cache = Path(os.getcwd()) / ".build_cache"`` por
        defecto). El directorio se conserva tras la operación para
        permitir inspección manual y diff con ``git diff``.

        Los parámetros ``area_id``, ``contexto`` y ``subestado`` son
        parametrizables (keyword-only) para que un 2º área pueda
        reutilizar este método apuntando a su propio workdir sin que
        el gateway tenga que saber qué áreas existen. Por defecto
        apuntan al flujo canónico de alimentación/dispositivos/exports/.

        Args:
            plc_name: nombre del PLC en TIA.
            dispositivos_slot_maps: ``{hw_type: {slot: texto}}`` con
                ``slot_map[0] == "NO USAR"`` siempre. Tipos activos:
                ``"ed", "ea", "sa", "v", "m", "m_vf"``.
            target_folder: carpeta destino del import dentro del proyecto
                TIA (resuelta por ``ConfigManager.get_tia_folder_dispositivos()``).
            db_names: ``{hw_type: db_name}`` ya resuelto por ConfigManager.
            db_array_names: ``{hw_type: db_array_name}`` ya resuelto por ConfigManager.
            area_id: id del área para resolver el workdir
                (default ``"alimentacion"``).
            contexto: contexto de dominio dentro del área
                (default ``"dispositivos"``).
            subestado: subestado del ``ContextCache``
                (default ``"exports"``; otros: ``"modified"``, ``"preview"``).
            build_cache_dir: ruta al directorio ``.build_cache``. Si es
                None, se usa ``Path(os.getcwd()) / ".build_cache"``.
            undo_text: etiqueta del historial Undo de TIA Portal.

        Returns:
            Dict con shape de ``execute_transactional_batch``:
            ``{"success": True, "operations_executed": int, "details": [...],
               "work_dir": str}``.

        Raises:
            ValueError: si algún ``slot_map[0] != "NO USAR"`` o si falta info.
        """
        if not dispositivos_slot_maps:
            raise ValueError("dispositivos_slot_maps está vacío.")

        # Workdir de export para los 6 DBs. El gateway vive en
        # ``core/`` (no debe importar áreas), así que construimos el
        # path directamente desde los parámetros, sin pasar por
        # ``AlimentacionAreaCache``. Por defecto, apunta al flujo
        # canónico de alimentación/dispositivos/exports/.
        root = Path(build_cache_dir) if build_cache_dir is not None else Path(os.getcwd()) / ".build_cache"
        work_dir = BuildCache(area_id=area_id, root=root).area.root / contexto / subestado
        work_dir.mkdir(parents=True, exist_ok=True)

        operations: list[dict[str, Any]] = []
        for hw_type, slot_map in dispositivos_slot_maps.items():
            if 0 not in slot_map or slot_map[0] != "NO USAR":
                raise ValueError(
                    f"slot_map[{hw_type!r}][0] debe ser 'NO USAR' "
                    f"(got {slot_map.get(0)!r})."
                )
            operations.append({
                "command": f"update_disp_comments_db_{hw_type}",
                "args": {
                    "plc_name":      plc_name,
                    "db_name":       db_names.get(hw_type, ""),
                    "db_array_name": db_array_names.get(hw_type, ""),
                    "slot_map":      {str(k): v for k, v in slot_map.items()},
                    "work_dir":      str(work_dir),
                    "target_folder": target_folder,
                },
            })
        result = await self.execute_transactional_batch(
            operations, undo_text=undo_text
        )
        self.clear_cache()
        return result
