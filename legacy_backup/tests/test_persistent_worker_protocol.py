"""Tests del protocolo request-response del worker OT persistente (PR 3).

Cubre el protocolo definido en ``_plan/12_worker_persistent_design.md``
§2.5 (request-response con IDs) y §3.1/§3.2 (gateway + worker):

- **Worker (Test 1, 4):** ``main_persistent_loop()`` lee comandos de
  stdin, los despacha al ``COMMAND_REGISTRY`` y escribe respuestas
  con el mismo ``id`` a stdout. El comando ``exit`` cierra el loop
  limpiamente (``portal.detach()`` se invoca).

- **Gateway (Test 2, 3, 5, 6):** el reader task (``_read_worker_stdout_forever``)
  hace match por ``id`` y resuelve los futures registrados en
  ``_pending_responses``. ``_send_to_persistent_worker`` espera con
  timeout; respuestas desordenadas se matchearan correctamente; EOF
  en stdout cierra el reader limpiamente. ``_start_persistent_worker``
  lanza el subproceso con los args correctos (incluido
  ``--worker-persistent``).

Estrategia de testing:

- **Worker (Tests 1 y 4):** mockeamos ``sys.stdin`` / ``sys.stdout``
  con ``io.StringIO`` y parchamos ``_load_siemens_wrapper`` para
  que devuelva un fake ``siemens_tia_scripting``. ``COMMAND_REGISTRY``
  se sustituye por un dict de handlers controlados. Asi NO
  necesitamos TIA Portal real.

- **Gateway (Tests 2, 3, 5):** mockeamos ``_worker_proc`` (con
  ``MagicMock`` que expone ``stdin.write`` async-friendly y
  ``stdout.readline`` que devuelve lineas predefinidas). El
  ``_send_to_persistent_worker`` se prueba con ``asyncio.wait_for``
  + patching del reader.

- **Gateway start (Test 6):** mockeamos
  ``asyncio.create_subprocess_exec`` para capturar los args y
  mockeamos ``_send_to_persistent_worker`` para evitar el ping
  real. Asi verificamos que los args de lanzamiento son correctos
  sin levantar un subproceso de verdad.

Nota: los handlers del ``COMMAND_REGISTRY`` reciben la firma
``(portal, ts, args) -> Any``. En los tests del worker pasamos
``portal=None`` o un ``MagicMock`` segun el caso (los handlers de
test ignoran el portal o lo usan para nada).
"""
from __future__ import annotations

import asyncio
import io
import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.infrastructure.gateway import TIAProcessGateway
from core.infrastructure.tia import worker_tia


# ────────────────────────────────────────────────────────────────────────
# Helpers compartidos
# ────────────────────────────────────────────────────────────────────────


def _build_fake_ts(portal: MagicMock | None = None) -> MagicMock:
    """Crea un mock de ``siemens_tia_scripting`` para los tests del worker.

    El mock expone lo minimo que ``main_persistent_loop()`` necesita:
      - ``Enums.PortalMode.AnyUserInterface`` / ``WithGraphicalUserInterface`` /
        ``WithoutGraphicalUserInterface`` (creado con ``spec=`` para que
        ``getattr(...)`` lance ``AttributeError`` ante nombres invalidos;
        asi el codepath defensivo de ``_handle_attach`` se ejercita en
        los tests, no solo en produccion).
      - ``attach_portal(...)`` retorna el portal del caller (o un portal
        con ``detach()`` y ``get_process_id()`` por defecto).
    """
    ts = MagicMock(name="FakeSiemensWrapper")
    if portal is None:
        portal = MagicMock(name="FakePortal")
        portal.detach = MagicMock()
        portal.get_process_id = MagicMock(return_value=12345)
    ts.attach_portal.return_value = portal
    # ``spec=`` restringe los atributos validos. Si el codigo bajo
    # test pide un nombre que NO esta en la lista (e.g.
    # ``WithHiddenMainWindow``), ``getattr`` lanza ``AttributeError``
    # y el codepath defensivo de ``_handle_attach`` se ejecuta.
    # Sin ``spec=``, MagicMock auto-crea el atributo y el bug del
    # PortalMode invalido seria invisible a los tests.
    ts.Enums.PortalMode = MagicMock(
        spec=["AnyUserInterface", "WithGraphicalUserInterface",
              "WithoutGraphicalUserInterface"],
        name="FakePortalModeEnum",
    )
    ts.Enums.PortalMode.AnyUserInterface = "AnyUserInterface"
    ts.Enums.PortalMode.WithGraphicalUserInterface = "WithGraphicalUserInterface"
    ts.Enums.PortalMode.WithoutGraphicalUserInterface = (
        "WithoutGraphicalUserInterface"
    )
    return ts


class _CapturingStdout:
    """Captura ``sys.stdout.write`` en una lista de strings.

    Mas amigable que ``io.StringIO`` porque expone ``get_lines()`` con
    solo lineas terminadas en ``\\n`` (las respuestas del worker).
    """

    def __init__(self) -> None:
        self._buf = io.StringIO()

    def write(self, s: str) -> int:
        return self._buf.write(s)

    def flush(self) -> None:
        pass

    def get_lines(self) -> list[str]:
        text = self._buf.getvalue()
        return [line for line in text.splitlines() if line.strip()]

    def get_value(self) -> str:
        return self._buf.getvalue()


# ────────────────────────────────────────────────────────────────────────
# Test 1: el worker responde con el mismo ``id`` que recibe
# ────────────────────────────────────────────────────────────────────────


class TestWorkerIdMatching:
    """El worker escribe la respuesta con el ``id`` del request."""

    def test_worker_responde_con_mismo_id(self) -> None:
        """Para un payload ``{"id": 5, "command": "ping"}`` la respuesta tiene ``id": 5``.

        Mockeamos stdin con un payload valido y stdout con un
        capturador. Tras invocar ``main_persistent_loop()`` (que sale
        tras leer el comando porque stdin se cierra), la respuesta
        escrita a stdout debe tener ``id: 5``.

        Cambio sept-2026 (post-auditoria): el worker arranca en
        estado idle, asi que el test primero envia ``attach_portal``
        para que el portal este attached, y luego el ``ping`` (un
        comando del ``COMMAND_REGISTRY``) ya puede ejecutarse.
        """
        ts = _build_fake_ts()

        def _fake_ping(portal, ts_arg, args):  # noqa: ARG001
            return {"ok": True, "pid": 42}

        # 1. attach_portal (id=1) — lleva al estado connected.
        # 2. ping (id=5) — el handler del COMMAND_REGISTRY que probamos.
        payload = (
            json.dumps(
                {"id": 1, "command": "attach_portal", "args": {"mode": "WithGraphicalUserInterface"}}
            )
            + "\n"
            + json.dumps({"id": 5, "command": "ping", "args": {}})
            + "\n"
        )
        stdin = io.StringIO(payload)
        stdout = _CapturingStdout()

        original_stdin, original_stdout = sys.stdin, sys.stdout
        try:
            sys.stdin = stdin
            sys.stdout = stdout
            with patch.object(worker_tia, "_load_siemens_wrapper", return_value=ts), \
                 patch.object(worker_tia, "COMMAND_REGISTRY", {"ping": _fake_ping}):
                worker_tia.main_persistent_loop()
        finally:
            sys.stdin = original_stdin
            sys.stdout = original_stdout

        # El worker escribio 3 lineas: el "ready_idle" signal (id=0),
        # la respuesta al attach_portal (id=1) y la respuesta al ping
        # (id=5). Filtramos la respuesta al ping por su id; el resto
        # se ignora en este test.
        lines = stdout.get_lines()
        assert len(lines) == 3, f"se esperaban 3 lineas, got {len(lines)}: {lines!r}"
        ping_response = next(
            (json.loads(l) for l in lines if json.loads(l).get("id") == 5),
            None,
        )
        assert ping_response is not None, f"no se encontro respuesta a id=5 en {lines!r}"
        assert ping_response["ok"] is True
        assert ping_response["result"] == {"ok": True, "pid": 42}


# ────────────────────────────────────────────────────────────────────────
# Test 2: respuestas desordenadas se matchearan correctamente
# ────────────────────────────────────────────────────────────────────────


class TestUnorderedResponseMatching:
    """El reader del gateway matchea respuestas por ``id`` aunque lleguen desordenadas."""

    @pytest.mark.asyncio
    async def test_pending_responses_se_vacia_y_matchea_por_id(self) -> None:
        """Simula 2 requests concurrentes; las respuestas llegan en orden inverso.

        Cada future en ``_pending_responses`` debe recibir su propia
        respuesta (no la del otro request). El dict se vacia al
        resolver cada future.
        """
        gateway = TIAProcessGateway(persistent=True)

        # Mockeamos el proc para que stdout.readline() devuelva las
        # respuestas en orden inverso al de los requests.
        # Requests: id=10, id=11.
        # Responses (orden inverso en stdout): id=11 primero, luego id=10.

        responses_bytes = [
            (json.dumps({"id": 11, "ok": True, "result": "result_for_11"}) + "\n").encode("utf-8"),
            (json.dumps({"id": 10, "ok": True, "result": "result_for_10"}) + "\n").encode("utf-8"),
            b"",  # EOF para cerrar el reader.
        ]

        stdout_iter = iter(responses_bytes)

        class _FakeStream:
            async def readline(self):
                return next(stdout_iter, b"")

        class _FakeStdin:
            def __init__(self):
                self.written: list[bytes] = []

            def write(self, data: bytes) -> None:
                self.written.append(data)

            async def drain(self) -> None:
                pass

        fake_stdin = _FakeStdin()
        fake_stdout = _FakeStream()

        fake_proc = MagicMock(name="FakeSubprocess")
        fake_proc.stdin = fake_stdin
        fake_proc.stdout = fake_stdout
        fake_proc.returncode = None

        gateway._worker_proc = fake_proc
        gateway._next_request_id = 10

        # Creamos 2 futures manualmente (saltamos _send_to_persistent_worker
        # para no lanzar el subproceso; aqui probamos solo el reader).
        loop = asyncio.get_event_loop()
        fut_10 = loop.create_future()
        fut_11 = loop.create_future()
        gateway._pending_responses[10] = fut_10
        gateway._pending_responses[11] = fut_11

        # Lanzamos el reader. Procesa 2 lineas, luego EOF.
        reader_task = asyncio.create_task(gateway._read_worker_stdout_forever())
        # Esperamos a que ambas futures se resuelvan o a que el reader termine.
        try:
            results = await asyncio.wait_for(
                asyncio.gather(fut_10, fut_11, return_exceptions=True),
                timeout=2.0,
            )
        finally:
            # Cancelamos el reader si sigue vivo (puede haber leido EOF y salido).
            if not reader_task.done():
                reader_task.cancel()
                try:
                    await reader_task
                except (asyncio.CancelledError, Exception):
                    pass

        # Verificacion: cada future recibio SU respuesta (no la del otro).
        assert fut_10.result()["id"] == 10
        assert fut_10.result()["result"] == "result_for_10"
        assert fut_11.result()["id"] == 11
        assert fut_11.result()["result"] == "result_for_11"

        # El dict de pendientes se vacio.
        assert 10 not in gateway._pending_responses
        assert 11 not in gateway._pending_responses


# ────────────────────────────────────────────────────────────────────────
# Test 3: timeout si el worker no responde
# ────────────────────────────────────────────────────────────────────────


class TestSendTimeout:
    """``_send_to_persistent_worker`` lanza ``RuntimeError`` con mensaje de timeout."""

    @pytest.mark.asyncio
    async def test_send_to_persistent_worker_timeout(self) -> None:
        """Si el reader no resuelve el future, la llamada lanza ``RuntimeError`` con texto de timeout.

        Mockeamos el reader para que NO resuelva el future, y usamos
        un timeout muy corto (0.1s) para que el test sea rapido.
        Verificamos que el estado pasa a ``"idle"`` (sept-2026,
        el antiguo ``"disconnected"`` ya no existe) y que se
        lanza ``RuntimeError`` mencionando el timeout.
        """
        gateway = TIAProcessGateway(persistent=True)
        # Proc mock con stdin/stdout validos para evitar errores
        # de I/O antes del timeout.
        fake_proc = MagicMock(name="FakeSubprocess")
        fake_proc.stdin = MagicMock()
        fake_proc.stdin.write = MagicMock()
        fake_proc.stdin.drain = AsyncMock()
        fake_proc.stdout = MagicMock()
        fake_proc.returncode = None
        gateway._worker_proc = fake_proc

        # Reader mock que NO resuelve el future. Lo registramos
        # como task vivo para que ``_send_to_persistent_worker`` no
        # lo considere muerto.
        async def _hanging_reader() -> None:
            await asyncio.sleep(60)  # nunca termina en este test

        reader_task = asyncio.create_task(_hanging_reader())
        gateway._reader_task = reader_task

        # Llamamos con timeout_override muy corto.
        with pytest.raises(RuntimeError, match="no respondio") as exc_info:
            await gateway._send_to_persistent_worker(
                "slow_op", args={}, timeout_override=0.1
            )

        # El estado pasa a "idle" tras el timeout (sept-2026; el
        # antiguo "disconnected" ya no existe en el state machine).
        assert gateway._connection_state == "idle"
        # El mensaje incluye el comando y el timeout.
        msg = str(exc_info.value)
        assert "slow_op" in msg
        assert "0.1" in msg

        # Cleanup: cancelamos el reader hanging.
        reader_task.cancel()
        try:
            await reader_task
        except (asyncio.CancelledError, Exception):
            pass


# ────────────────────────────────────────────────────────────────────────
# Test 4: el comando ``exit`` cierra el worker limpiamente
# ────────────────────────────────────────────────────────────────────────


class TestExitCommand:
    """El comando ``exit`` cierra el loop y llama a ``portal.detach()``."""

    def test_exit_command_cierra_loop_y_llama_detach(self) -> None:
        """Tras ``exit`` el loop termina y ``portal.detach()`` se invoca.

        Enviamos un attach, un ping y un ``exit`` por stdin. El
        handler de ping devuelve un dict; luego ``exit`` rompe el
        loop. El cleanup final invoca ``portal.detach()``.

        Cambio sept-2026 (post-auditoria): el worker arranca en
        estado idle, asi que el test primero envia ``attach_portal``
        para que el portal este attached. El ``exit`` NO genera
        respuesta (simplemente rompe el loop), por lo que solo
        esperamos 3 lineas: ready_idle, attach, ping.
        """
        ts = _build_fake_ts()
        fake_portal = ts.attach_portal.return_value

        def _fake_ping(portal, ts_arg, args):  # noqa: ARG001
            return {"ok": True, "pid": 99}

        # Stdin con attach, ping, exit (sin newline final -> EOF al leer).
        payload = (
            json.dumps(
                {"id": 1, "command": "attach_portal", "args": {"mode": "WithGraphicalUserInterface"}}
            )
            + "\n"
            + json.dumps({"id": 2, "command": "ping", "args": {}}) + "\n"
            + json.dumps({"id": 3, "command": "exit", "args": {}}) + "\n"
        )
        stdin = io.StringIO(payload)
        stdout = _CapturingStdout()

        original_stdin, original_stdout = sys.stdin, sys.stdout
        try:
            sys.stdin = stdin
            sys.stdout = stdout
            with patch.object(worker_tia, "_load_siemens_wrapper", return_value=ts), \
                 patch.object(worker_tia, "COMMAND_REGISTRY", {"ping": _fake_ping}):
                worker_tia.main_persistent_loop()
        finally:
            sys.stdin = original_stdin
            sys.stdout = original_stdout

        # El worker escribio 3 lineas: el "ready_idle" (id=0), la
        # respuesta al attach (id=1) y la respuesta al ping (id=2).
        # El ``exit`` no genera respuesta, simplemente rompe el loop.
        # Filtramos la respuesta al ping por id.
        lines = stdout.get_lines()
        assert len(lines) == 3, f"se esperaban 3 lineas (ready_idle + attach + ping), got {len(lines)}: {lines!r}"
        ping_response = next(
            (json.loads(l) for l in lines if json.loads(l).get("id") == 2),
            None,
        )
        assert ping_response is not None, f"no se encontro respuesta a id=2 en {lines!r}"
        assert ping_response["ok"] is True
        # El cleanup llamo a portal.detach() (best-effort) porque el
        # portal estaba attached cuando salio del loop.
        fake_portal.detach.assert_called_once()


# ────────────────────────────────────────────────────────────────────────
# Test 5: el reader termina limpio si el worker muere (EOF en stdout)
# ────────────────────────────────────────────────────────────────────────


class TestReaderEof:
    """El reader sale limpio cuando ``stdout.readline()`` retorna ``b""`` (EOF)."""

    @pytest.mark.asyncio
    async def test_reader_termina_limpio_en_eof(self) -> None:
        """EOF en stdout hace que el reader salga sin lanzar excepciones.

        El reader es defensivo: un EOF o un error de stream NO debe
        tumbar el reader (el caller ``_send_to_persistent_worker``
        detecta el timeout y maneja la limpieza). Aqui solo
        verificamos que el reader retorna (no propaga excepciones).
        """
        gateway = TIAProcessGateway(persistent=True)

        # Stream que devuelve siempre ``b""`` (EOF permanente).
        class _EofStream:
            async def readline(self) -> bytes:
                return b""

        fake_proc = MagicMock(name="FakeSubprocess")
        fake_proc.stdout = _EofStream()
        fake_proc.returncode = None
        gateway._worker_proc = fake_proc

        # El reader debe retornar (no lanzar) en EOF.
        await asyncio.wait_for(
            gateway._read_worker_stdout_forever(),
            timeout=1.0,
        )


# ────────────────────────────────────────────────────────────────────────
# Test 6: ``_start_persistent_worker`` lanza el subproceso con los args correctos
# ────────────────────────────────────────────────────────────────────────


class TestStartPersistentWorkerArgs:
    """El subproceso se lanza con los args que enrutan a ``main_persistent_loop()``."""

    @pytest.mark.asyncio
    async def test_start_persistent_worker_lanza_subproceso_con_args_correctos(self) -> None:
        """El subproceso se invoca con ``--worker-persistent`` (junto con el script en dev).

        Mockeamos ``asyncio.create_subprocess_exec`` para capturar
        los args sin levantar un subproceso real. Para simular el
        "ready_idle" signal (sept-2026) equipamos el fake stdout
        con una linea JSON que el reader_task consumira, resolviendo
        el future en ``_pending_responses[0]`` registrado por
        ``_start_persistent_worker``.

        Verificamos que en ``args`` aparece ``"--worker-persistent"``
        y que el ejecutable es ``sys.executable`` (en dev:
        ``python -u main.py --worker-persistent``).

        Cambio sept-2026 (state machine refactor): tras el ready_idle
        el estado del gateway queda en ``"idle"`` (NO ``"connected"``
        como en el round anterior). El connect explicito via
        ``attach_portal`` es lo que transiciona a ``"connected"``.
        """
        gateway = TIAProcessGateway(persistent=True)

        fake_proc = MagicMock(name="FakeSubprocess")
        fake_proc.returncode = None
        fake_proc.stdin = MagicMock()
        # stdout: emite el ready_idle (id=0) y luego EOF. El reader_task
        # leera el ready_idle, resolvera el future registrado en
        # ``_pending_responses[0]`` y saldra del loop.
        ready_line = (
            json.dumps({"id": 0, "ok": True, "result": "ready_idle"}) + "\n"
        ).encode("utf-8")
        stdout_iter = iter([ready_line, b""])

        class _FakeStream:
            async def readline(self):
                return next(stdout_iter, b"")

        fake_proc.stdout = _FakeStream()

        with patch(
            "core.infrastructure.gateway.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=fake_proc),
        ) as mock_exec:
            await gateway._start_persistent_worker()

        # Capturamos los args con los que se invoco create_subprocess_exec.
        call = mock_exec.await_args
        # call.args es la tupla posicional: (sys.executable, *launch_args).
        positional_args = list(call.args)
        assert positional_args[0] == sys.executable
        # El flag ``--worker-persistent`` debe estar presente, junto
        # con el path a main.py (en dev) o solo el flag (en frozen).
        joined = " ".join(str(a) for a in positional_args)
        assert "--worker-persistent" in joined
        # El subproceso se registro en ``_worker_proc``.
        assert gateway._worker_proc is fake_proc
        # El reader_task se creo.
        assert gateway._reader_task is not None
        # El estado queda en ``idle`` tras el ready_idle exitoso
        # (NO connected; el connect explicito via attach_portal es
        # lo que transiciona a connected).
        assert gateway._connection_state == "idle"


# ────────────────────────────────────────────────────────────────────────
# Test extra (defensivo): un comando desconocido devuelve ``{ok: False, error: ...}``
# ────────────────────────────────────────────────────────────────────────


class TestWorkerUnknownCommand:
    """Comando no registrado devuelve error sin tumbar el loop."""

    def test_comando_desconocido_devuelve_error(self) -> None:
        """Si el registry no contiene el comando, la respuesta es ``{ok: False, error: ...}``.

        Verifica que el handler de ``COMMAND_REGISTRY.get(command)``
        maneja el caso ``None`` lanzando ``ValueError`` con un
        mensaje util, y que el loop lo captura y escribe la
        respuesta de error con el ``id`` correcto.

        Cambio sept-2026 (post-auditoria): el worker arranca en
        estado idle, asi que el test primero envia ``attach_portal``
        para llegar al codepath del registry. Si no lo hicieramos,
        el check de ``portal is None`` cortaria antes y devolveria
        "Portal no attached" en vez del ValueError del registry.
        """
        ts = _build_fake_ts()

        payload = (
            json.dumps(
                {"id": 1, "command": "attach_portal", "args": {"mode": "WithGraphicalUserInterface"}}
            )
            + "\n"
            + json.dumps({"id": 7, "command": "no_existe_este_comando", "args": {}})
            + "\n"
        )
        stdin = io.StringIO(payload)
        stdout = _CapturingStdout()

        original_stdin, original_stdout = sys.stdin, sys.stdout
        try:
            sys.stdin = stdin
            sys.stdout = stdout
            with patch.object(worker_tia, "_load_siemens_wrapper", return_value=ts), \
                 patch.object(worker_tia, "COMMAND_REGISTRY", {}):
                worker_tia.main_persistent_loop()
        finally:
            sys.stdin = original_stdin
            sys.stdout = original_stdout

        # 3 lineas: ready_idle (id=0) + attach (id=1) + error (id=7).
        lines = stdout.get_lines()
        assert len(lines) == 3, f"se esperaban 3 lineas, got {len(lines)}: {lines!r}"
        error_response = next(
            (json.loads(l) for l in lines if json.loads(l).get("id") == 7),
            None,
        )
        assert error_response is not None, f"no se encontro respuesta a id=7 en {lines!r}"
        assert error_response["ok"] is False
        assert "ValueError" in error_response["error"]
        assert "no_existe_este_comando" in error_response["error"]



# ───────────────────────────────────────────────────────────────────────────
# Tests del state machine del worker (commit 1, sept-2026 post-auditoria).
#
# Cubre el refactor que desacopla la vida del subproceso worker de la
# vida del portal TIA: el worker arranca en idle, NO hace attach al
# inicio, y los comandos ``attach_portal``/``detach_portal`` controlan
# el estado del portal. El resto de comandos requieren portal attached.
# ───────────────────────────────────────────────────────────────────────────


class TestWorkerIdleAtStartup:
    """El worker arranca en estado idle: emite ``ready_idle`` y NO hace attach."""

    def test_worker_no_llama_attach_portal_al_inicio(self) -> None:
        """``ts.attach_portal`` NO se invoca durante el startup del loop.

        Caso real (sept-2026): el worker arranca en milisegundos sin
        pagar el coste de attach (~5s). El gateway le envia un
        ``attach_portal`` explicito cuando el operario decide conectar.

        Verificamos:
          1. ``ts.attach_portal`` NO se llama durante el startup.
          2. La primera linea de stdout es el ``ready_idle`` con
             ``result="ready_idle"`` y ``ok=True``.
        """
        ts = _build_fake_ts()
        stdin = io.StringIO("")
        stdout = _CapturingStdout()

        original_stdin, original_stdout = sys.stdin, sys.stdout
        try:
            sys.stdin = stdin
            sys.stdout = stdout
            with patch.object(worker_tia, "_load_siemens_wrapper", return_value=ts):
                worker_tia.main_persistent_loop()
        finally:
            sys.stdin = original_stdin
            sys.stdout = original_stdout

        # 1. ``attach_portal`` NO se llamo al inicio.
        ts.attach_portal.assert_not_called()

        # 2. La unica linea de stdout es el ready_idle signal.
        lines = stdout.get_lines()
        assert len(lines) == 1, f"se esperaba 1 linea (ready_idle), got {len(lines)}: {lines!r}"
        ready = json.loads(lines[0])
        assert ready["id"] == 0
        assert ready["ok"] is True
        assert ready["result"] == "ready_idle"


class TestWorkerAttachCommand:
    """El comando ``attach_portal`` attacha el portal y devuelve ``{"pid": int}``."""

    def test_attach_portal_con_mode_explicito_devuelve_pid(self) -> None:
        """``attach_portal`` con mode ``WithGraphicalUserInterface`` devuelve ``{"pid": <int>}``."""
        ts = _build_fake_ts()
        fake_portal = ts.attach_portal.return_value
        fake_portal.get_process_id.return_value = 54321

        payload = json.dumps(
            {
                "id": 1,
                "command": "attach_portal",
                "args": {"mode": "WithGraphicalUserInterface"},
            }
        )
        stdin = io.StringIO(payload + "\n")
        stdout = _CapturingStdout()

        original_stdin, original_stdout = sys.stdin, sys.stdout
        try:
            sys.stdin = stdin
            sys.stdout = stdout
            with patch.object(worker_tia, "_load_siemens_wrapper", return_value=ts):
                worker_tia.main_persistent_loop()
        finally:
            sys.stdin = original_stdin
            sys.stdout = original_stdout

        ts.attach_portal.assert_called_once()
        call_kwargs = ts.attach_portal.call_args.kwargs
        assert call_kwargs.get("portal_mode") == "WithGraphicalUserInterface"

        lines = stdout.get_lines()
        attach_response = next(
            (json.loads(l) for l in lines if json.loads(l).get("id") == 1),
            None,
        )
        assert attach_response is not None
        assert attach_response["ok"] is True
        assert attach_response["result"] == {"pid": 54321}

    def test_attach_portal_con_mode_por_defecto(self) -> None:
        """``attach_portal`` sin ``args["mode"]`` usa ``WithGraphicalUserInterface``."""
        ts = _build_fake_ts()
        fake_portal = ts.attach_portal.return_value
        fake_portal.get_process_id.return_value = 11111

        payload = json.dumps({"id": 1, "command": "attach_portal", "args": {}})
        stdin = io.StringIO(payload + "\n")
        stdout = _CapturingStdout()

        original_stdin, original_stdout = sys.stdin, sys.stdout
        try:
            sys.stdin = stdin
            sys.stdout = stdout
            with patch.object(worker_tia, "_load_siemens_wrapper", return_value=ts):
                worker_tia.main_persistent_loop()
        finally:
            sys.stdin = original_stdin
            sys.stdout = original_stdout

        ts.attach_portal.assert_called_once()
        call_kwargs = ts.attach_portal.call_args.kwargs
        assert call_kwargs.get("portal_mode") == "WithGraphicalUserInterface"

    def test_attach_portal_falla_devuelve_error(self) -> None:
        """Si ``ts.attach_portal`` lanza, el worker responde con error."""
        ts = _build_fake_ts()
        ts.attach_portal.side_effect = RuntimeError(
            "No matching TIA Portal version"
        )

        payload = json.dumps(
            {
                "id": 1,
                "command": "attach_portal",
                "args": {"mode": "WithGraphicalUserInterface"},
            }
        )
        stdin = io.StringIO(payload + "\n")
        stdout = _CapturingStdout()

        original_stdin, original_stdout = sys.stdin, sys.stdout
        try:
            sys.stdin = stdin
            sys.stdout = stdout
            with patch.object(worker_tia, "_load_siemens_wrapper", return_value=ts):
                worker_tia.main_persistent_loop()
        finally:
            sys.stdin = original_stdin
            sys.stdout = original_stdout

        lines = stdout.get_lines()
        attach_response = next(
            (json.loads(l) for l in lines if json.loads(l).get("id") == 1),
            None,
        )
        assert attach_response is not None
        assert attach_response["ok"] is False
        assert "No matching TIA Portal version" in attach_response["error"]
        assert "RuntimeError" in attach_response["error"]


class TestWorkerDetachCommand:
    """El comando ``detach_portal`` detacha el portal attached."""

    def test_detach_portal_llama_a_portal_detach(self) -> None:
        """``detach_portal`` con portal attached -> ``portal.detach()`` y ``{"detached": true}``."""
        ts = _build_fake_ts()
        fake_portal = ts.attach_portal.return_value
        fake_portal.get_process_id.return_value = 12345

        # 1. attach_portal (id=1) -> estado connected.
        # 2. detach_portal (id=2) -> vuelve a idle.
        payload = (
            json.dumps(
                {
                    "id": 1,
                    "command": "attach_portal",
                    "args": {"mode": "WithGraphicalUserInterface"},
                }
            )
            + "\n"
            + json.dumps({"id": 2, "command": "detach_portal", "args": {}})
            + "\n"
        )
        stdin = io.StringIO(payload)
        stdout = _CapturingStdout()

        original_stdin, original_stdout = sys.stdin, sys.stdout
        try:
            sys.stdin = stdin
            sys.stdout = stdout
            with patch.object(worker_tia, "_load_siemens_wrapper", return_value=ts):
                worker_tia.main_persistent_loop()
        finally:
            sys.stdin = original_stdin
            sys.stdout = original_stdout

        fake_portal.detach.assert_called_once()

        lines = stdout.get_lines()
        detach_response = next(
            (json.loads(l) for l in lines if json.loads(l).get("id") == 2),
            None,
        )
        assert detach_response is not None
        assert detach_response["ok"] is True
        assert detach_response["result"] == {"detached": True}

    def test_detach_portal_en_idle_es_idempotente(self) -> None:
        """``detach_portal`` sin portal attached -> ``{"detached": false}`` (no error)."""
        ts = _build_fake_ts()
        fake_portal = ts.attach_portal.return_value

        payload = json.dumps(
            {"id": 1, "command": "detach_portal", "args": {}}
        )
        stdin = io.StringIO(payload + "\n")
        stdout = _CapturingStdout()

        original_stdin, original_stdout = sys.stdin, sys.stdout
        try:
            sys.stdin = stdin
            sys.stdout = stdout
            with patch.object(worker_tia, "_load_siemens_wrapper", return_value=ts):
                worker_tia.main_persistent_loop()
        finally:
            sys.stdin = original_stdin
            sys.stdout = original_stdout

        fake_portal.detach.assert_not_called()
        lines = stdout.get_lines()
        detach_response = next(
            (json.loads(l) for l in lines if json.loads(l).get("id") == 1),
            None,
        )
        assert detach_response is not None
        assert detach_response["ok"] is True
        assert detach_response["result"] == {"detached": False}


class TestWorkerRejectsOperationsWhenIdle:
    """Los comandos del ``COMMAND_REGISTRY`` requieren portal attached."""

    def test_list_plcs_sin_attach_devuelve_error_claro(self) -> None:
        """``list_plcs`` en estado idle -> error claro (Portal no attached)."""
        ts = _build_fake_ts()
        fake_portal = ts.attach_portal.return_value
        fake_portal.get_process_id.return_value = 12345

        def _fake_list_plcs(portal, ts_arg, args):  # noqa: ARG001
            # sept-2026: ``_cmd_list_plcs`` ahora devuelve una
            # lista de dicts ``{name, short_designation}``. Esta
            # _fake_ reemplaza al comando del registry en este
            # test, asi que usamos la nueva forma para que el
            # round-trip JSON refleje el contrato real.
            return [
                {"name": "PLC1", "short_designation": None},
                {"name": "PLC2", "short_designation": None},
            ]

        payload = json.dumps(
            {"id": 1, "command": "list_plcs", "args": {}}
        )
        stdin = io.StringIO(payload + "\n")
        stdout = _CapturingStdout()

        original_stdin, original_stdout = sys.stdin, sys.stdout
        try:
            sys.stdin = stdin
            sys.stdout = stdout
            with patch.object(worker_tia, "_load_siemens_wrapper", return_value=ts), \
                 patch.object(
                     worker_tia, "COMMAND_REGISTRY", {"list_plcs": _fake_list_plcs}
                 ):
                worker_tia.main_persistent_loop()
        finally:
            sys.stdin = original_stdin
            sys.stdout = original_stdout

        ts.attach_portal.assert_not_called()
        lines = stdout.get_lines()
        response = next(
            (json.loads(l) for l in lines if json.loads(l).get("id") == 1),
            None,
        )
        assert response is not None
        assert response["ok"] is False
        assert "Portal no attached" in response["error"]
        assert "Conectar primero" in response["error"]


# ────────────────────────────────────────────────────────────────────────
# Tests del handler ``_handle_attach`` inline (audit X3, sept-2026)
#
# Cubre las dos ramas defensivas de ``_handle_attach`` (worker_tia.py
# ~1399): el codepath del PortalMode invalido y el codepath de
# ``attach_portal`` retornando ``None``. El handler es un closure
# dentro de ``main_persistent_loop``; lo testeamos indirectamente
# enviando el comando ``attach_portal`` por stdin y observando la
# respuesta JSON.
# ────────────────────────────────────────────────────────────────────────


class TestHandleAttachInvalidPortalMode:
    """``_handle_attach`` devuelve error claro cuando el ``PortalMode`` no existe en ``ts.Enums``."""

    def test_attach_portal_con_mode_invalido_devuelve_error_claro(self) -> None:
        """``mode="WithHiddenMainWindow"`` (no existe en ``ts.Enums.PortalMode``) → error ``"PortalMode invalido"``.

        Caso real (audit X3, sept-2026): si el gateway envia un
        mode que el build concreto del wrapper de Siemens no
        expone, el ``getattr(ts.Enums.PortalMode, mode_name)``
        lanza ``AttributeError``. El handler lo captura y devuelve
        un dict con ``error`` que el loop traduce a
        ``ok=False``. El gateway ve el error y no transiciona a
        ``"connected"``.
        """
        ts = _build_fake_ts()  # expone WithGraphicalUserInterface y WithoutGraphicalUserInterface
        # NO anadimos WithHiddenMainWindow a proposito: queremos
        # que el getattr() falle con AttributeError.

        payload = json.dumps(
            {
                "id": 1,
                "command": "attach_portal",
                "args": {"mode": "WithHiddenMainWindow"},
            }
        )
        stdin = io.StringIO(payload + "\n")
        stdout = _CapturingStdout()

        original_stdin, original_stdout = sys.stdin, sys.stdout
        try:
            sys.stdin = stdin
            sys.stdout = stdout
            with patch.object(worker_tia, "_load_siemens_wrapper", return_value=ts):
                worker_tia.main_persistent_loop()
        finally:
            sys.stdin = original_stdin
            sys.stdout = original_stdout

        # 1. ``ts.attach_portal`` NO se llamo (el getattr fallo antes).
        ts.attach_portal.assert_not_called()
        # 2. La respuesta tiene ``ok=False`` y un mensaje claro.
        lines = stdout.get_lines()
        attach_response = next(
            (json.loads(l) for l in lines if json.loads(l).get("id") == 1),
            None,
        )
        assert attach_response is not None, (
            f"no se encontro respuesta a id=1 en {lines!r}"
        )
        assert attach_response["ok"] is False
        assert "PortalMode invalido" in attach_response["error"]
        assert "WithHiddenMainWindow" in attach_response["error"]
        # El mensaje sugiere los valores validos.
        assert "WithGraphicalUserInterface" in attach_response["error"]


class TestHandleAttachReturnsNone:
    """``_handle_attach`` devuelve error claro cuando ``ts.attach_portal`` retorna ``None``."""

    def test_attach_portal_retornando_none_devuelve_error_claro(self) -> None:
        """``ts.attach_portal.return_value = None`` → error ``"attach_portal retorno None"``.

        Caso real (audit X3, sept-2026): ``ts.attach_portal(...)``
        retorna ``None`` cuando TIA Portal no esta abierto o el
        usuario no pertenece al grupo Openness de Windows. El
        handler lo detecta y devuelve un error con un mensaje
        util para el operario (en vez de un ``AttributeError``
        al intentar ``None.get_process_id()``).
        """
        ts = _build_fake_ts()
        # Sobrescribimos el return_value (el helper lo dejo apuntando
        # al portal por defecto). Esto es lo que el wrapper de
        # Siemens hace cuando TIA no esta abierto.
        ts.attach_portal.return_value = None

        payload = json.dumps(
            {
                "id": 1,
                "command": "attach_portal",
                "args": {"mode": "WithGraphicalUserInterface"},
            }
        )
        stdin = io.StringIO(payload + "\n")
        stdout = _CapturingStdout()

        original_stdin, original_stdout = sys.stdin, sys.stdout
        try:
            sys.stdin = stdin
            sys.stdout = stdout
            with patch.object(worker_tia, "_load_siemens_wrapper", return_value=ts):
                worker_tia.main_persistent_loop()
        finally:
            sys.stdin = original_stdin
            sys.stdout = original_stdout

        # 1. ``ts.attach_portal`` se llamo UNA vez con el mode correcto.
        ts.attach_portal.assert_called_once()
        call_kwargs = ts.attach_portal.call_args.kwargs
        assert call_kwargs.get("portal_mode") == "WithGraphicalUserInterface"
        # 2. La respuesta tiene ``ok=False`` y un mensaje util.
        lines = stdout.get_lines()
        attach_response = next(
            (json.loads(l) for l in lines if json.loads(l).get("id") == 1),
            None,
        )
        assert attach_response is not None, (
            f"no se encontro respuesta a id=1 en {lines!r}"
        )
        assert attach_response["ok"] is False
        # El mensaje diagnostica las dos causas mas probables.
        assert "attach_portal retorno None" in attach_response["error"]
        assert "TIA Portal" in attach_response["error"]
        assert "Openness" in attach_response["error"]


# ────────────────────────────────────────────────────────────────────────
# Tests del fix A2 (audit de robustez, sept-2026).
#
# Cubre el helper ``_drain_pending_responses`` del gateway y la
# rama ``finally`` del reader ``_read_worker_stdout_forever`` que
# ahora resuelve los futures en vuelo con ``RuntimeError`` cuando
# el reader sale por EOF o stream roto.
#
# Caso de uso real: el operario envia un comando lento, el worker
# muere a mitad de la operacion (EOF en stdout). Antes (pre-A2) el
# future se quedaba colgado hasta el timeout (180s). Ahora se
# resuelve inmediatamente y el caller recibe ``RuntimeError``
# sin pagar el timeout entero.
# ────────────────────────────────────────────────────────────────────────


class TestDrainPendingResponses:
    """El helper ``_drain_pending_responses`` resuelve futures con ``RuntimeError``."""

    @pytest.mark.asyncio
    async def test_drain_resuelve_future_pendiente_con_runtimeerror(self) -> None:
        """Un future registrado en ``_pending_responses`` se resuelve con ``RuntimeError`` al drenar.

        Pre-A2 el reader NO llamaba al drain; el future quedaba
        colgado hasta que el ``asyncio.wait_for`` del caller
        disparaba ``asyncio.TimeoutError`` despues de 180s.
        Post-A2 el reader invoca ``_drain_pending_responses`` en
        su ``finally``, y el caller recibe ``RuntimeError`` al
        instante.
        """
        gateway = TIAProcessGateway(persistent=True)

        # Registramos un future pendiente (id=42) simulando un
        # comando en vuelo que aun no recibio respuesta.
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        gateway._pending_responses[42] = fut

        # El future esta pendiente y el dict tiene la entrada.
        assert not fut.done()
        assert 42 in gateway._pending_responses

        # El drain resuelve con RuntimeError.
        gateway._drain_pending_responses("Worker desconectado durante lectura")

        # El future ahora tiene la excepcion (no un resultado).
        assert fut.done()
        with pytest.raises(RuntimeError, match="Worker desconectado durante lectura"):
            fut.result()
        # El dict se vacio.
        assert 42 not in gateway._pending_responses
        assert gateway._pending_responses == {}

    @pytest.mark.asyncio
    async def test_drain_idempotente_con_dict_vacio(self) -> None:
        """Drenar con dict vacio es no-op (no falla)."""
        gateway = TIAProcessGateway(persistent=True)
        assert gateway._pending_responses == {}
        # No debe lanzar.
        gateway._drain_pending_responses("cualquier motivo")
        assert gateway._pending_responses == {}

    @pytest.mark.asyncio
    async def test_drain_no_pisa_future_ya_resuelto(self) -> None:
        """Si un future ya esta done (lector lo resolvio antes de salir), NO se sobreescribe."""
        gateway = TIAProcessGateway(persistent=True)
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        fut.set_result({"id": 99, "ok": True, "result": "ya_resuelto"})
        gateway._pending_responses[99] = fut

        gateway._drain_pending_responses("motivo X")

        # El resultado previo (NO la excepcion) se preserva.
        assert fut.result() == {"id": 99, "ok": True, "result": "ya_resuelto"}


class TestReaderResolvesPendingOnEof:
    """El reader task resuelve los futures en vuelo cuando sale por EOF (fix A2)."""

    @pytest.mark.asyncio
    async def test_eof_en_stdout_resuelve_futures_pendientes(self) -> None:
        """Si el reader sale por EOF, los futures en ``_pending_responses`` se resuelven con ``RuntimeError``.

        Caso end-to-end del fix A2. Mockeamos el stdout para que
        devuelva EOF inmediato, registramos un future pendiente
        en el gateway, y verificamos que tras correr el reader
        el future se resuelve con ``RuntimeError`` y el dict se
        vacia.

        Antes (pre-A2) el future quedaba ``pending`` y el
        ``asyncio.wait_for`` del caller tenia que esperar al
        timeout entero. Ahora (sept-2026) se resuelve al
        instante gracias al ``finally`` del reader que invoca
        ``_drain_pending_responses``.
        """
        gateway = TIAProcessGateway(persistent=True)

        # Stream que devuelve EOF permanente (b'' en el primer readline).
        class _EofStream:
            async def readline(self) -> bytes:
                return b""

        fake_proc = MagicMock(name="FakeSubprocess")
        fake_proc.stdout = _EofStream()
        fake_proc.returncode = None
        gateway._worker_proc = fake_proc

        # Registramos un future pendiente (simula un comando en vuelo).
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        gateway._pending_responses[99] = fut
        assert not fut.done()

        # Corremos el reader. Como el stream es EOF inmediato,
        # sale del loop, ejecuta el ``finally`` y drena.
        await asyncio.wait_for(
            gateway._read_worker_stdout_forever(),
            timeout=1.0,
        )

        # Verificaciones post-EOF:
        # 1. El future se resolvio con RuntimeError (no pending).
        assert fut.done()
        with pytest.raises(RuntimeError, match="Worker desconectado durante lectura"):
            fut.result()
        # 2. El dict se vacio.
        assert 99 not in gateway._pending_responses
        assert gateway._pending_responses == {}

    @pytest.mark.asyncio
    async def test_eof_con_multiples_futures_pendientes(self) -> None:
        """Multiples futures en vuelo al EOF → todos se resuelven con RuntimeError."""
        gateway = TIAProcessGateway(persistent=True)

        class _EofStream:
            async def readline(self) -> bytes:
                return b""

        fake_proc = MagicMock(name="FakeSubprocess")
        fake_proc.stdout = _EofStream()
        fake_proc.returncode = None
        gateway._worker_proc = fake_proc

        loop = asyncio.get_event_loop()
        futs = {i: loop.create_future() for i in (1, 2, 3)}
        for k, v in futs.items():
            gateway._pending_responses[k] = v

        await asyncio.wait_for(
            gateway._read_worker_stdout_forever(),
            timeout=1.0,
        )

        # Todos los futures tienen la misma excepcion (mismo motivo).
        for k, fut in futs.items():
            assert fut.done()
            with pytest.raises(RuntimeError, match="Worker desconectado durante lectura"):
                fut.result()
        assert gateway._pending_responses == {}


# ────────────────────────────────────────────────────────────────────────
# Tests del fix A7 (audit de robustez, sept-2026).
#
# Cubre el cambio en ``_handle_detach`` del worker: cuando
# ``portal.detach()`` lanza (RCW stale, TIA ya cerrada, etc.) el
# handler ahora emite un WARNING con la excepcion (antes era un
# ``pass`` silencioso que engañaba al operario).
# ────────────────────────────────────────────────────────────────────────


class TestHandleDetachBestEffortLog:
    """``_handle_detach`` loguea WARNING si ``portal.detach()`` lanza (fix A7)."""

    def test_detach_con_rcw_stale_emite_warning(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Si ``portal.detach()`` lanza, se loguea WARNING con la excepcion.

        Caso real (audit A7, sept-2026): el operario tenia
        TIA cerrado de forma abrupta, los RCW quedan stale y
        ``portal.detach()`` lanza ``COMError`` o similar. Antes
        (pre-A7) el handler absorbia con ``pass`` silencioso y
        el frontend veia "Desconectado" en verde sin que el
        operario supiera POR QUE. Ahora (sept-2026) dejamos
        rastro en los logs: un WARNING con
        ``"detach_portal best-effort fallo: <Tipo>: <msg>"``.

        El ``return`` sigue siendo ``{"detached": True}`` (el
        best-effort sigue siendo el contrato) pero el log
        permite al operario correlacionar el evento con TIA
        cerrandose o dialogos colgados.
        """
        import logging
        ts = _build_fake_ts()
        fake_portal = ts.attach_portal.return_value
        fake_portal.get_process_id.return_value = 12345

        # Forzamos que detach() lance: caso real de RCW stale.
        fake_portal.detach.side_effect = RuntimeError("RCW stale")

        # attach_portal (id=1) + detach_portal (id=2).
        payload = (
            json.dumps(
                {
                    "id": 1,
                    "command": "attach_portal",
                    "args": {"mode": "WithGraphicalUserInterface"},
                }
            )
            + "\n"
            + json.dumps({"id": 2, "command": "detach_portal", "args": {}})
            + "\n"
        )
        stdin = io.StringIO(payload)
        stdout = _CapturingStdout()

        original_stdin, original_stdout = sys.stdin, sys.stdout
        try:
            sys.stdin = stdin
            sys.stdout = stdout
            with caplog.at_level(
                logging.WARNING, logger="core.infrastructure.tia.worker_tia"
            ):
                with patch.object(worker_tia, "_load_siemens_wrapper", return_value=ts):
                    worker_tia.main_persistent_loop()
        finally:
            sys.stdin = original_stdin
            sys.stdout = original_stdout

        # 1. La respuesta del detach sigue siendo ``{"detached": true}``
        # (best-effort contract preservado).
        lines = stdout.get_lines()
        detach_response = next(
            (json.loads(l) for l in lines if json.loads(l).get("id") == 2),
            None,
        )
        assert detach_response is not None
        assert detach_response["ok"] is True
        assert detach_response["result"] == {"detached": True}

        # 2. El WARNING con la excepcion se emitio.
        warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "detach_portal best-effort fallo" in r.getMessage()
        ]
        assert len(warnings) == 1, (
            f"se esperaba 1 WARNING, got {len(warnings)}: "
            f"{[r.getMessage() for r in caplog.records]}"
        )
        msg = warnings[0].getMessage()
        assert "RuntimeError" in msg
        assert "RCW stale" in msg

    def test_detach_exitoso_no_emite_warning(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Si ``portal.detach()`` NO lanza, NO se emite WARNING (caso feliz)."""
        import logging
        ts = _build_fake_ts()
        fake_portal = ts.attach_portal.return_value
        fake_portal.get_process_id.return_value = 12345
        # detach NO lanza (default MagicMock).

        payload = (
            json.dumps(
                {
                    "id": 1,
                    "command": "attach_portal",
                    "args": {"mode": "WithGraphicalUserInterface"},
                }
            )
            + "\n"
            + json.dumps({"id": 2, "command": "detach_portal", "args": {}})
            + "\n"
        )
        stdin = io.StringIO(payload)
        stdout = _CapturingStdout()

        original_stdin, original_stdout = sys.stdin, sys.stdout
        try:
            sys.stdin = stdin
            sys.stdout = stdout
            with caplog.at_level(
                logging.WARNING, logger="core.infrastructure.tia.worker_tia"
            ):
                with patch.object(worker_tia, "_load_siemens_wrapper", return_value=ts):
                    worker_tia.main_persistent_loop()
        finally:
            sys.stdin = original_stdin
            sys.stdout = original_stdout

        # Sin WARNINGs de detach_portal.
        warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "detach_portal best-effort fallo" in r.getMessage()
        ]
        assert len(warnings) == 0, (
            f"NO se esperaba WARNING, got: {[r.getMessage() for r in warnings]}"
        )
