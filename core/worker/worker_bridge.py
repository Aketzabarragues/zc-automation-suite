"""Fachada async con lock para el worker persistente de TIA Portal.

Este modulo es el **UNICO** punto de contacto entre los Function
Blocks (FBs) del Engine y el subproceso ``worker_tia.py``
(ver ``.clinerules`` seccion 1). Los FBs **solo hablan con
``WorkerBridge``**, nunca directamente con el worker.

Diseno (decisiones duras, no a negociar):
  - **Lock desde la primera linea** (leccion X3,
    ``PLC_IE_61131_GREENFIELD.md`` seccion 0.4 y ``.clinerules``
    seccion 8). ``asyncio.Lock`` no es reentrante: ninguna cadena
    interna lo vuelve a coger. ``_send`` asume el lock cogido y lo
    verifica con ``assert self._lock.locked()`` (no solo un
    comentario: si alguien lo llama sin lock, falla ALTO).
  - **Double-checked locking** en ``attach``/``detach``: un doble
    clic rapido en la UI no debe lanzar dos attaches o dejar el
    bridge en estado inconsistente.
  - **Shutdown handler obligatorio** (leccion X2): ``shutdown()``
    envia ``detach_portal`` + cierra stdin + espera al subproceso.
    Sin esto, el .pyd de Siemens queda en memoria (~200 MB zombi)
    al cerrar la app. Se llama desde el ``lifespan`` de FastAPI.
  - **Convención de respuesta**: cada comando retorna
    ``{"ok": bool, "result"|"error": ...}``. Si ``ok == False``,
    el bridge lanza ``WorkerCommandError`` con el mensaje. Si el
    bridge no puede comunicarse con el worker (subproceso muerto,
    timeout, etc.), lanza ``WorkerBridgeError``.

Protocolo (mismo que ``worker_tia``):
  - Comandos JSON por stdin (un JSON por linea).
  - Respuestas JSON por stdout (un JSON por linea).
  - Logs a stderr.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Logger del modulo. Va a stderr (el bridge no emite JSON; solo el
# worker lo hace).
log = logging.getLogger("core.worker.worker_bridge")

# Estados del bridge (NO del worker; el bridge mantiene su propia
# copia para implementar double-checked locking sin hacer un round-trip
# al worker en cada operacion barata).
_STATE_IDLE = "idle"
_STATE_CONNECTED = "connected"


# ════════════════════════════════════════════════════════════════════════
#  Excepciones
# ════════════════════════════════════════════════════════════════════════


class WorkerBridgeError(Exception):
    """Error de comunicacion con el subproceso worker.

    El bridge no puede enviar o recibir el comando: el subproceso
    esta muerto, el stream se cerro, hubo timeout, etc. **Distinto**
    de ``WorkerCommandError`` (que es un error reportado POR el
    worker; la comunicacion fue exitosa, pero el comando fallo en
    el lado del worker, p.ej. TIA no esta en ejecucion al attach).

    Codigo de llamada esperado: reintentar / propagar / mostrar al
    operario segun el contexto. Nunca asumir que el bridge sigue
    funcional tras un ``WorkerBridgeError``.
    """


class WorkerCommandError(Exception):
    """El worker respondio ``ok=False`` con un mensaje de error.

    La comunicacion fue exitosa (el worker esta vivo y respondio),
    pero el comando fallo en el lado del worker. Por ejemplo: TIA
    Portal no esta en ejecucion cuando se intenta attach, o el
    proyecto activo no tiene PLCs, o un comando todavia no esta
    implementado (TODO).

    Codigo de llamada esperado: mostrar el mensaje al operario
    (``str(exc)`` es legible). Reintentar el mismo comando sin
    cambiar el estado probablemente fallara igual.
    """


# ════════════════════════════════════════════════════════════════════════
#  Bridge
# ════════════════════════════════════════════════════════════════════════


class WorkerBridge:
    """Fachada async con lock para el worker persistente.

    Lifecycle:
        1. ``await bridge.start()`` — en el ``lifespan`` de FastAPI
           al arrancar. Lanza el subproceso ``worker_tia.py``.
        2. ``await bridge.attach(portal_mode="Primary")`` — cuando
           el operario quiere conectar a TIA Portal (instancia YA
           en ejecucion; el attach no lanza TIA).
        3. ``await bridge.list_plcs()`` / ``ping()`` /
           ``get_project_info()`` — y otros comandos.
        4. ``await bridge.detach()`` — al desconectar (idempotente).
        5. ``await bridge.shutdown()`` — en el ``lifespan`` al
           apagar. Libera el .pyd (~200 MB), leccion X2.

    Concurrencia:
        Todos los metodos publicos son ``async def``. **No** son
        thread-safe: el uso normal es desde un event loop asyncio
        (FastAPI). ``asyncio.Lock`` serializa las llamadas para que
        el stream JSON del worker no se corrompa.
    """

    def __init__(
        self,
        worker_path: str | Path | None = None,
        command_timeout: float = 30.0,
        shutdown_timeout: float = 2.0,
    ) -> None:
        """Inicializa el bridge. **NO** arranca el subproceso (usar ``start()``).

        Args:
            worker_path: Path al script ``worker_tia.py``. Si es None,
                se resuelve relativo a este modulo (caso normal en
                desarrollo y en frozen; en ambos casos el worker vive
                junto al bridge en ``core/worker/``).
            command_timeout: Timeout por defecto para ``_send``
                (segundos). Algunos comandos (attach) pueden tardar
                mas si TIA esta ocupado; el caller puede pasar un
                timeout custom por llamada.
            shutdown_timeout: Tiempo maximo para esperar a que el
                worker termine tras cerrar stdin (segundos). Si no
                responde, se llama a ``proc.terminate()``.
        """
        # ── Lock desde la primera linea (leccion X3) ────────────────
        # ``asyncio.Lock`` no es reentrante: ninguna cadena interna
        # lo vuelve a coger. ``_send`` lo verifica con un assert.
        self._lock: asyncio.Lock = asyncio.Lock()

        # Path al script del worker. Se resuelve en ``__init__`` para
        # que errores de path se vean al construir el bridge, no al
        # arrancar (mejor diagnostico).
        if worker_path is None:
            self._worker_path: Path = Path(__file__).parent / "worker_tia.py"
        else:
            self._worker_path = Path(worker_path)

        # Subproceso. None hasta que ``start()`` se llame.
        self._proc: asyncio.subprocess.Process | None = None

        # Tasks de lectura (stdout y stderr). None hasta ``start()``.
        # Tras la muerte del worker, el reader pone estos a None.
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None

        # Futures de respuestas pendientes, indexadas por id de mensaje.
        # El reader las rellena cuando llega la respuesta del worker.
        self._response_futures: dict[int, asyncio.Future[dict[str, Any]]] = {}

        # Proximo id de mensaje (monotonicamente creciente). Wrap-around
        # es teoricamente posible tras 2**31 comandos; en la practica
        # no llegaremos ahi, pero si preocupa se puede usar un
        # ``itertools.count`` con modulo.
        self._next_id: int = 0

        # Estado del bridge. Refleja lo que CREEMOS del worker; el
        # worker tiene su propio state machine. Si el worker muere
        # inesperadamente, el reader loop resetea esto a IDLE.
        self._state: str = _STATE_IDLE
        self._last_attach_pid: int | None = None

        # Flag de shutdown. Para que ``shutdown()`` sea idempotente
        # (se puede llamar varias veces sin efectos adversos).
        self._shutdown_done: bool = False

        # Timeouts configurables.
        self._command_timeout: float = command_timeout
        self._shutdown_timeout: float = shutdown_timeout

    # ── Propiedades publicas de solo lectura ─────────────────────────

    @property
    def is_connected(self) -> bool:
        """``True`` si el bridge cree estar attached a TIA Portal.

        Esto es el estado del BRIDGE (su copia local). Puede
        divergir brevemente del estado real del worker si el
        worker murio y aun no hemos detectado el EOF. Para
        verificar la conexion real, llamar a ``await ping()``.
        """
        return self._state == _STATE_CONNECTED

    @property
    def is_running(self) -> bool:
        """``True`` si el subproceso del worker esta vivo."""
        return (
            self._proc is not None
            and self._proc.returncode is None
        )

    # ── Lifecycle ────────────────────────────────────────────────────

    async def start(self) -> None:
        """Arranca el subproceso del worker. Idempotente.

        Si el worker ya esta corriendo (``self._proc.returncode is None``),
        no hace nada. Si el worker arranco pero ya murio
        (``self._proc.returncode is not None``), re-arranca uno nuevo:
        util para auto-recuperacion tras un crash del subproceso.

        Lanza el worker con el mismo Python que corre la app
        (``sys.executable``) y monta dos background tasks:
          - ``_reader_loop``: lee stdout y dispatcha respuestas a futures.
          - ``_stderr_loop``: lee stderr y lo loggea (no se emite a stdout).

        Raises:
            WorkerBridgeError: Si el script del worker no existe o
                ``asyncio.create_subprocess_exec`` falla.
        """
        # Fast path: si el worker esta vivo, no hacemos nada.
        if self._proc is not None and self._proc.returncode is None:
            log.info(
                "Worker already running (pid=%d), start() is a no-op",
                self._proc.pid,
            )
            return

        if not self._worker_path.is_file():
            raise WorkerBridgeError(
                f"Worker script not found: {self._worker_path}"
            )

        log.info("Starting worker subprocess: %s", self._worker_path)
        try:
            # ``sys.executable`` asegura que usamos el mismo Python
            # que corre la app (importante en frozen: el Python embebido
            # es el que sabe donde estan los modulos del proyecto).
            self._proc = await asyncio.create_subprocess_exec(
                sys.executable,
                str(self._worker_path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as e:
            self._proc = None
            raise WorkerBridgeError(
                f"Failed to spawn worker subprocess: {e}"
            ) from e

        log.info("Worker subprocess started (pid=%d)", self._proc.pid)

        # Lanzar los readers (stdout y stderr). Son tasks asyncio que
        # corren en background hasta que el subproceso muere.
        # ``name=`` para que aparezcan con nombre en ``asyncio.all_tasks()``.
        self._reader_task = asyncio.create_task(
            self._reader_loop(), name="worker_reader"
        )
        self._stderr_task = asyncio.create_task(
            self._stderr_loop(), name="worker_stderr"
        )

    async def shutdown(self) -> None:
        """Shutdown handler. Libera el .pyd de Siemens (leccion X2).

        Pasos:
            1. ``detach_portal`` best-effort (sin pasar por ``_send``,
               para no bloquear si el worker esta colgado).
            2. Cerrar stdin del worker (forzar EOF en su loop).
            3. Esperar al subproceso (``shutdown_timeout`` segundos).
            4. Si no responde, ``proc.terminate()``.
            5. Si terminate no responde, ``proc.kill()``.
            6. Cancelar los reader tasks.

        **Idempotente**: si ya se llamo, no hace nada.

        **CRITICO**: sin este handler, el .pyd de Siemens queda en
        memoria (~200 MB zombi) hasta que se cierre TIA o se mate
        el proceso a mano. Ver ``PLC_IE_61131_GREENFIELD.md``
        leccion X2. Se llama desde el ``lifespan`` de FastAPI al
        apagar.
        """
        if self._shutdown_done:
            log.info("shutdown() already done, no-op")
            return
        self._shutdown_done = True

        proc = self._proc
        if proc is None or proc.returncode is not None:
            # Ya cerrado o nunca arrancado. Solo limpiamos tasks.
            log.info(
                "Worker subprocess not running (proc=%r, returncode=%r), "
                "nothing to shut down",
                proc,
                proc.returncode if proc else None,
            )
            await self._cleanup_tasks()
            return

        # 1. ``detach_portal`` best-effort. NO usamos ``_send`` (que
        # requiere el lock y un worker vivo): el shutdown debe
        # funcionar incluso si el worker esta colgado. Si el stdin ya
        # esta cerrado o el worker no responde, capturamos y seguimos.
        try:
            if proc.stdin and not proc.stdin.is_closing():
                msg_id = self._next_id
                self._next_id += 1
                msg = {"id": msg_id, "cmd": "detach_portal", "args": {}}
                line = json.dumps(msg) + "\n"
                proc.stdin.write(line.encode("utf-8"))
                try:
                    await asyncio.wait_for(
                        proc.stdin.drain(), timeout=1.0
                    )
                except (asyncio.TimeoutError, BrokenPipeError, ConnectionResetError):
                    # Worker ya no escribe, no esperamos respuesta.
                    pass
        except Exception as e:  # noqa: BLE001
            log.warning(
                "Shutdown: detach_portal best-effort send failed: %s", e
            )

        # 2. Cerrar stdin (forzar EOF en el loop del worker). El
        # worker, al recibir EOF, corre ``_cleanup_on_exit()`` que
        # llama a ``portal.detach()`` y libera el RCW.
        try:
            if proc.stdin and not proc.stdin.is_closing():
                proc.stdin.close()
        except Exception as e:  # noqa: BLE001
            log.warning("Shutdown: stdin close failed: %s", e)

        # 3. Esperar al subproceso.
        try:
            await asyncio.wait_for(proc.wait(), timeout=self._shutdown_timeout)
            log.info(
                "Worker subprocess exited cleanly (returncode=%d)",
                proc.returncode,
            )
        except asyncio.TimeoutError:
            # 4. No respondio en ``shutdown_timeout``: terminate.
            log.warning(
                "Worker did not exit in %ss, terminating (pid=%d)",
                self._shutdown_timeout, proc.pid,
            )
            try:
                proc.terminate()
                await asyncio.wait_for(
                    proc.wait(), timeout=self._shutdown_timeout
                )
            except asyncio.TimeoutError:
                # 5. Hasta terminate fallo: kill (forzado).
                log.error(
                    "Worker did not exit after terminate, killing (pid=%d)",
                    proc.pid,
                )
                try:
                    proc.kill()
                    await proc.wait()
                except Exception as e:  # noqa: BLE001
                    log.exception("Worker kill failed: %s", e)
        except Exception as e:  # noqa: BLE001
            log.exception("Worker wait failed: %s", e)

        # 6. Cancelar reader tasks y limpiar futures pendientes.
        await self._cleanup_tasks()
        log.info("Worker shutdown complete")

    async def _cleanup_tasks(self) -> None:
        """Cancela los reader tasks y limpia futures. Usado por ``shutdown()``
        y al detectar la muerte del subproceso.
        """
        for task in (self._reader_task, self._stderr_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    # Cancelados o cualquier excepcion: no nos importa,
                    # estamos cerrando.
                    pass
        self._reader_task = None
        self._stderr_task = None
        # Cualquier future pendiente: marcarla como error.
        for fut in self._response_futures.values():
            if not fut.done():
                fut.set_exception(
                    WorkerBridgeError("Worker bridge is shutting down")
                )
        self._response_futures.clear()

    # ── Comandos publicos (todos async, todos protegidos por el lock) ─

    async def attach(self, portal_mode: str = "WithGraphicalUserInterface") -> int:
        """Attach a una instancia YA en ejecucion de TIA Portal.

        ``ts.attach_portal()`` **NO** lanza TIA Portal (verificado
        contra el manual Openness V1.2.1, ``.clinerules`` seccion 4).
        Si TIA no esta abierto, el worker responde ``ok=False`` y
        este metodo lanza ``WorkerCommandError``.

        **Double-checked locking** (leccion X3, ``.clinerules``
        seccion 8): un doble clic rapido en Conectar no debe
        lanzar dos attaches. El primer check (sin lock) hace
        fast-path si ya estamos connected; el segundo check
        (dentro del lock) protege contra la carrera entre el
        check y el acquire.

        Args:
            portal_mode: Nombre del modo de attach (default
                ``"WithGraphicalUserInterface"``). Se pasa al worker
                como string; el worker lo resuelve a
                ``ts.Enums.PortalMode[portal_mode]`` (verificado
                contra el manual oficial, seccion 2.4.2). Valores
                validos: ``"WithGraphicalUserInterface"``,
                ``"WithoutGraphicalUserInterface"``.

        Returns:
            El PID del proceso de TIA Portal al que se hizo attach.

        Raises:
            WorkerCommandError: Si TIA no esta en ejecucion o el
                attach falla por otra razon (reportado por el worker).
            WorkerBridgeError: Si el subproceso worker no esta
                disponible (no se llamo a ``start()``, o se cayo).
        """
        # ── Primer check (sin lock): fast path ─────────────────────
        # Si ya estamos connected con un PID conocido, lo retornamos
        # directamente. Esto es seguro porque el estado solo cambia
        # dentro del lock (ver ``detach`` y este mismo metodo).
        if (
            self._state == _STATE_CONNECTED
            and self._last_attach_pid is not None
        ):
            return self._last_attach_pid

        async with self._lock:
            # ── Segundo check (dentro del lock) ────────────────────
            # Por si otro caller cambio el estado entre el primer
            # check y el acquire del lock.
            if (
                self._state == _STATE_CONNECTED
                and self._last_attach_pid is not None
            ):
                return self._last_attach_pid

            # Trabajo real: enviar el comando al worker.
            result = await self._send(
                "attach_portal",
                {"portal_mode": portal_mode},
                timeout=self._command_timeout,
            )
            # ``result`` viene del worker; lo esperamos como dict.
            if not isinstance(result, dict) or "pid" not in result:
                raise WorkerBridgeError(
                    f"attach_portal returned unexpected result: {result!r}"
                )
            pid = int(result["pid"])
            self._state = _STATE_CONNECTED
            self._last_attach_pid = pid
            return pid

    async def detach(self) -> None:
        """Detach del portal attached. **Idempotente**.

        Si no estamos connected (estado IDLE), no hace nada y no
        falla. Esto es importante para que el shutdown sea
        robusto: si el worker ya se cerro, ``detach`` no rompe.
        """
        # Primer check (sin lock): si ya estamos idle, fast path.
        if self._state != _STATE_CONNECTED:
            return

        async with self._lock:
            # Segundo check (dentro del lock).
            if self._state != _STATE_CONNECTED:
                return
            await self._send("detach_portal", {}, timeout=10.0)
            self._state = _STATE_IDLE
            self._last_attach_pid = None

    async def list_plcs(self) -> list[dict[str, Any]]:
        """Lista los PLCs del proyecto activo. Devuelve ``list[dict]``.

        Por ahora devuelve error (TODO en ``worker_tia``). Cuando se
        implemente, cada PLC sera un dict con al menos ``name`` y
        ``type`` (mapeo de objetos .NET a primitivos, ``.clinerules``
        seccion 3).

        Raises:
            WorkerCommandError: Si no estamos connected, o si el
                comando no esta implementado todavia (devuelve error
                con mensaje legible).
            WorkerBridgeError: Si el subproceso worker no responde.
        """
        async with self._lock:
            result = await self._send(
                "list_plcs", {}, timeout=self._command_timeout
            )
        if not isinstance(result, list):
            raise WorkerCommandError(
                f"list_plcs expected list, got "
                f"{type(result).__name__}: {result!r}"
            )
        return result

    async def ping(self) -> int:
        """Ping al worker attached. Devuelve el PID de TIA Portal.

        Util para diagnosticar si el attach sigue vivo tras un
        periodo de inactividad (TIA puede haber sido cerrado por
        el operario sin hacer detach; el siguiente ping fallara).

        Raises:
            WorkerCommandError: Si no estamos connected o si el
                portal attached ya no responde (TIA cerrado).
            WorkerBridgeError: Si el subproceso worker no responde.
        """
        async with self._lock:
            result = await self._send("ping", {}, timeout=10.0)
        if not isinstance(result, dict) or "pid" not in result:
            raise WorkerBridgeError(
                f"ping returned unexpected result: {result!r}"
            )
        return int(result["pid"])

    async def get_project_info(self) -> dict[str, Any]:
        """Propiedades del proyecto activo. Devuelve ``dict``.

        Por ahora devuelve error (TODO en ``worker_tia``).

        Raises:
            WorkerCommandError: Si no estamos connected, o si el
                comando no esta implementado todavia.
            WorkerBridgeError: Si el subproceso worker no responde.
        """
        async with self._lock:
            result = await self._send(
                "get_project_info", {}, timeout=self._command_timeout
            )
        if not isinstance(result, dict):
            # Distinto de "no es dict" vs "es dict sin campos esperados":
            # en este caso, si el worker implementa el comando, esperamos
            # un dict. Si devuelve otra cosa, es un bug del worker.
            raise WorkerCommandError(
                f"get_project_info expected dict, got "
                f"{type(result).__name__}: {result!r}"
            )
        return result

    # ── Envio de comandos (asume lock cogido) ────────────────────────

    async def _send(
        self,
        cmd: str,
        args: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Envia un comando al worker y espera la respuesta.

        **ASUME EL LOCK COGIDO**. Verificado con ``assert`` (no solo
        un comentario: si alguien lo llama sin lock, falla ALTO con
        ``AssertionError``, exponiendo el bug inmediatamente).

        Flujo:
            1. Asigna un id unico al mensaje.
            2. Crea una future y la registra en ``_response_futures``.
            3. Escribe el JSON al stdin del worker.
            4. Espera la future (con timeout).
            5. Interpreta la respuesta: ``ok=False`` -> ``WorkerCommandError``;
               ``ok=True`` -> devuelve ``result``.

        La future se **siempre** se desregistra en el ``finally``
        (incluso si hay cancelacion), para no dejar futures zombis.

        Args:
            cmd: Nombre del comando (string).
            args: Argumentos del comando (dict). Se serializa tal
                cual al JSON; el caller es responsable de que solo
                contenga tipos primitivos.
            timeout: Timeout en segundos. Si es None, usa
                ``self._command_timeout``.

        Returns:
            El campo ``result`` de la respuesta del worker (tipo
            variable: dict, list, str, int, bool, None segun el
            comando).

        Raises:
            WorkerBridgeError: Si el subproceso no esta disponible,
                el stream se cerro, hay timeout, o la respuesta es
                malformada.
            WorkerCommandError: Si el worker respondio ``ok=False``.
        """
        # ── Assert duro (no solo un comentario) ─────────────────────
        # ``asyncio.Lock`` no es reentrante; cualquier llamada a
        # ``_send`` sin lock es un bug de programacion, no un
        # error de runtime. Fallar ALTO aqui expone el bug en el
        # sitio exacto donde ocurre, no en un deadlock futuro.
        assert self._lock.locked(), (
            "_send() must be called with the lock held. "
            "This is a programming error, not a runtime error."
        )

        proc = self._proc
        if proc is None or proc.returncode is not None:
            raise WorkerBridgeError(
                "Worker subprocess is not running (call start() first)"
            )
        if proc.stdin is None or proc.stdin.is_closing():
            raise WorkerBridgeError("Worker stdin is closed")

        if timeout is None:
            timeout = self._command_timeout

        # ── Registrar la future ANTES de enviar ────────────────────
        # Asi el reader loop la encuentra cuando llegue la respuesta.
        msg_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._response_futures[msg_id] = future

        try:
            # ── 1. Serializar y enviar ─────────────────────────────
            try:
                payload = {"id": msg_id, "cmd": cmd, "args": args or {}}
                line = json.dumps(payload) + "\n"
                proc.stdin.write(line.encode("utf-8"))
                await proc.stdin.drain()
            except (
                BrokenPipeError,
                ConnectionResetError,
                ConnectionAbortedError,
                OSError,
            ) as e:
                # El worker murio o cerro el pipe entre el start() y
                # este envio. El reader loop detectara la muerte y
                # marcara esta future como error; nosotros
                # simplificamos lanzando WorkerBridgeError.
                raise WorkerBridgeError(
                    f"Failed to send command {cmd!r}: {e}"
                ) from e

            # ── 2. Esperar la respuesta ────────────────────────────
            try:
                response = await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError:
                # La future queda registrada; si llega respuesta
                # tarde, el reader la descartara con un warning.
                raise WorkerBridgeError(
                    f"Timeout after {timeout}s waiting for response "
                    f"to {cmd!r}"
                ) from None

            # ── 3. Interpretar la respuesta ────────────────────────
            if not isinstance(response, dict):
                raise WorkerBridgeError(
                    f"Invalid response from worker for {cmd!r}: "
                    f"{response!r}"
                )
            if not response.get("ok"):
                error_msg = response.get(
                    "error", "Unknown error (no 'error' field)"
                )
                raise WorkerCommandError(f"{cmd!r} failed: {error_msg}")
            return response.get("result")
        finally:
            # ── 4. Cleanup defensivo ───────────────────────────────
            # La future SIEMPRE se desregistra aqui, incluso si hubo
            # cancelacion (``asyncio.CancelledError`` no se captura en
            # los except de arriba, pero el finally corre igual).
            # Esto evita futures zombis que el reader loop tendria
            # que marcar como error al detectar la muerte del worker.
            self._response_futures.pop(msg_id, None)

    # ── Readers (background tasks asyncio) ────────────────────────────

    async def _reader_loop(self) -> None:
        """Lee stdout del worker y dispatcha las respuestas a las futures.

        Corre como background task. Termina cuando el stdout se cierra
        (EOF), lo que ocurre cuando el worker muere (limpio o por
        crash). En ese caso, marca todas las futures pendientes como
        ``WorkerBridgeError`` y resetea el estado del bridge a IDLE.

        Por que un solo reader:
            El worker emite UN JSON por linea a stdout. Si hubiera
            varios readers, cada uno leeria lineas alternas y ambos
            verian respuestas truncadas. Un solo reader garantiza
            que cada linea va a la future correcta por su ``id``.
        """
        proc = self._proc
        if proc is None or proc.stdout is None:
            log.error("Reader loop started without a valid stdout")
            return

        log.info("Reader loop started")
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    # EOF: el worker cerro stdout (limpio via exit/EOF
                    # en stdin, o por crash).
                    log.warning(
                        "Worker stdout EOF (worker exited or crashed)"
                    )
                    break
                try:
                    text = line.decode("utf-8").strip()
                except UnicodeDecodeError as e:
                    # Una linea no UTF-8 del worker es inesperada (el
                    # worker solo escribe JSON). La loggeamos y seguimos.
                    log.warning("Worker emitted non-UTF8 line: %s", e)
                    continue
                if not text:
                    continue
                try:
                    msg = json.loads(text)
                except json.JSONDecodeError as e:
                    log.warning(
                        "Worker emitted invalid JSON: %s (line=%r)",
                        e, text[:200],
                    )
                    continue
                if not isinstance(msg, dict):
                    log.warning("Worker emitted non-dict JSON: %r", msg)
                    continue

                msg_id = msg.get("id")
                if msg_id is None:
                    # Mensaje espontaneo (sin id). Por ahora, loggeamos.
                    # En el futuro, podria ser un evento push del
                    # worker (p.ej. "project_changed") que el Engine
                    # publica al SSE.
                    log.info("Worker unsolicited message: %s", msg)
                    continue

                future = self._response_futures.pop(msg_id, None)
                if future is None:
                    log.warning(
                        "No future registered for response id=%d "
                        "(msg=%r). Possible late response after timeout.",
                        msg_id, msg,
                    )
                    continue
                if future.done():
                    # Esto puede pasar si el caller ya cancelo la
                    # operacion; el resultado llegaria dos veces (no
                    # deberia, pero por si acaso).
                    log.warning(
                        "Future for response id=%d already done", msg_id
                    )
                    continue
                future.set_result(msg)
        except asyncio.CancelledError:
            log.info("Reader loop cancelled")
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("Reader loop crashed: %s", e)
        finally:
            # ── El worker murio (o nosotros): cleanup defensivo ────
            # Cualquier future pendiente recibe un error para que
            # los callers no se queden colgados en ``await future``.
            log.info(
                "Reader loop ending, marking %d pending futures as error",
                len(self._response_futures),
            )
            for fut in self._response_futures.values():
                if not fut.done():
                    fut.set_exception(
                        WorkerBridgeError("Worker subprocess died")
                    )
            self._response_futures.clear()

            # Resetear estado del bridge. Esto NO requiere el lock
            # (asyncio es single-threaded; las asignaciones simples
            # son atomicas y no ceden el control). Permite que el
            # siguiente ``attach()`` funcione tras un crash del
            # worker (previa llamada a ``start()`` para re-arrancar).
            self._state = _STATE_IDLE
            self._last_attach_pid = None

    async def _stderr_loop(self) -> None:
        """Lee stderr del worker y lo loggea al logger del bridge.

        El worker escribe el heartbeat y los logs de aplicacion a
        stderr. Los reenviamos al logger de Python (``log.info``)
        que va a donde diga la config de logging del proceso IT
        (consola, archivo, etc.).

        Por que no pasamos el nivel directamente: el worker usa
        ``logging`` de Python y formatea con timestamp y nivel. Si
        nosotros loggearamos a su nivel, duplicariamos el formato.
        En su lugar, prefixamos con ``[worker]`` para distinguir
        del log del bridge.
        """
        proc = self._proc
        if proc is None or proc.stderr is None:
            log.error("Stderr loop started without a valid stderr")
            return

        log.info("Stderr loop started")
        try:
            while True:
                line = await proc.stderr.readline()
                if not line:
                    log.info("Worker stderr EOF")
                    break
                try:
                    text = line.decode("utf-8", errors="replace").rstrip()
                except Exception:  # noqa: BLE001
                    continue
                if not text:
                    continue
                # Reenviamos al logger del bridge con prefijo para
                # distinguir del log del IT.
                log.info("[worker] %s", text)
        except asyncio.CancelledError:
            log.info("Stderr loop cancelled")
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("Stderr loop crashed: %s", e)
