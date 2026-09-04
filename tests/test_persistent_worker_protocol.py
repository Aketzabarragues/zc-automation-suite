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
      - ``Enums.PortalMode.AnyUserInterface`` / ``WithGraphicalUserInterface``.
      - ``attach_portal(...)`` retorna el portal del caller (o un portal
        con ``detach()`` y ``get_process_id()`` por defecto).
    """
    ts = MagicMock(name="FakeSiemensWrapper")
    if portal is None:
        portal = MagicMock(name="FakePortal")
        portal.detach = MagicMock()
        portal.get_process_id = MagicMock(return_value=12345)
    ts.attach_portal.return_value = portal
    ts.Enums.PortalMode.AnyUserInterface = "AnyUserInterface"
    ts.Enums.PortalMode.WithGraphicalUserInterface = "WithGraphicalUserInterface"
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
        """
        ts = _build_fake_ts()

        def _fake_ping(portal, ts_arg, args):  # noqa: ARG001
            return {"ok": True, "pid": 42}

        payload = json.dumps({"id": 5, "command": "ping", "args": {}})
        stdin = io.StringIO(payload + "\n")
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

        # El worker escribio una unica respuesta (luego salio del
        # loop por EOF de stdin).
        lines = stdout.get_lines()
        assert len(lines) == 1, f"se esperaba 1 linea, got {len(lines)}: {lines!r}"
        response = json.loads(lines[0])
        assert response["id"] == 5, f"id esperado 5, got {response.get('id')!r}"
        assert response["ok"] is True
        assert response["result"] == {"ok": True, "pid": 42}


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
        Verificamos que el estado pasa a ``disconnected`` y que se
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

        # El estado pasa a disconnected tras el timeout.
        assert gateway._connection_state == "disconnected"
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

        Enviamos un ping seguido de un ``exit`` por stdin. El
        handler de ping devuelve un dict; luego ``exit`` rompe el
        loop. El cleanup final invoca ``portal.detach()``.
        """
        ts = _build_fake_ts()
        fake_portal = ts.attach_portal.return_value

        def _fake_ping(portal, ts_arg, args):  # noqa: ARG001
            return {"ok": True, "pid": 99}

        # Stdin con un ping y luego un exit (sin newline final -> EOF al leer).
        payload = (
            json.dumps({"id": 1, "command": "ping", "args": {}}) + "\n"
            + json.dumps({"id": 2, "command": "exit", "args": {}}) + "\n"
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

        # El worker escribio 1 respuesta (la del ping; el ``exit`` no
        # genera respuesta, simplemente rompe el loop).
        lines = stdout.get_lines()
        assert len(lines) == 1, f"se esperaba 1 linea (ping), got {len(lines)}: {lines!r}"
        response = json.loads(lines[0])
        assert response["id"] == 1
        assert response["ok"] is True
        # El cleanup llamo a portal.detach() (best-effort).
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
        los args sin levantar un subproceso real. Mockeamos
        ``_send_to_persistent_worker`` (que es quien ejecuta el
        ping) para evitar que el reader intente leer de un stream
        falso.

        Verificamos que en ``args`` aparece ``"--worker-persistent"``
        y que el ejecutable es ``sys.executable`` (en dev:
        ``python -u main.py --worker-persistent``).
        """
        gateway = TIAProcessGateway(persistent=True)

        fake_proc = MagicMock(name="FakeSubprocess")
        fake_proc.returncode = None
        fake_proc.stdin = MagicMock()
        fake_proc.stdout = MagicMock()
        sentinel = {"ok": True, "pid": 1}
        gateway._send_to_persistent_worker = AsyncMock(return_value=sentinel)

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
        # El estado paso a ``connected`` tras el ping exitoso.
        assert gateway._connection_state == "connected"


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
        """
        ts = _build_fake_ts()

        payload = json.dumps({"id": 7, "command": "no_existe_este_comando", "args": {}})
        stdin = io.StringIO(payload + "\n")
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

        lines = stdout.get_lines()
        assert len(lines) == 1
        response = json.loads(lines[0])
        assert response["id"] == 7
        assert response["ok"] is False
        assert "ValueError" in response["error"]
        assert "no_existe_este_comando" in response["error"]
