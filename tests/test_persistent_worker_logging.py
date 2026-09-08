"""Tests de los eventos estructurados en ``main_persistent_loop``.

Cubre los 6 eventos principales del diseno del PR de observabilidad:

- ``worker_started`` al arrancar el subproceso persistente.
- ``command_received`` (o ``ping_received`` para pings) al llegar un
  comando por stdin.
- ``command_completed`` al terminar OK un handler del ``COMMAND_REGISTRY``.
- ``command_failed`` cuando un handler lanza excepcion.
- ``worker_stopped`` cuando el operario envia ``exit``.
- ``attach`` / ``detach`` / ``reconnect`` / ``error`` (eventos
  secundarios que el operario tambien usa para diagnosticar).

Estrategia de captura:

Los eventos se emiten via ``log_event`` (lazy-imported en
``main_persistent_loop``). Interceptamos las llamadas a esa funcion
con ``unittest.mock.patch.object`` aplicado al modulo
``core.infrastructure.tia.worker_logging`` (que es donde se busca el
simbolo al hacer ``from X import Y``). Asi NO necesitamos configurar
un logger real, no escribimos en ``worker_ot.log``, y los tests son
deterministas y rapidos.

Ademas parchamos ``configure_worker_logger`` para que devuelva un
``MagicMock`` en vez de tocar disco. Asi los tests no contaminan la
carpeta ``<cwd>/logs/`` del operario con artefactos ``worker_ot.log``
de pruebas.

Mockeamos el resto igual que los tests de protocolo existentes
(``_load_siemens_wrapper`` y ``COMMAND_REGISTRY``).
"""
from __future__ import annotations

import io
import json
import logging
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import core.infrastructure.tia.worker_logging as worker_logging_mod
import core.infrastructure.tia.worker_tia as worker_tia
from core.infrastructure.tia.worker_tia import main_persistent_loop


# ────────────────────────────────────────────────────────────────────────
# Helpers compartidos
# ────────────────────────────────────────────────────────────────────────


class _CapturingStdout:
    """Captura ``sys.stdout.write`` para que el test no contamine el output real."""

    def __init__(self) -> None:
        self._buf = io.StringIO()

    def write(self, s: str) -> int:
        return self._buf.write(s)

    def flush(self) -> None:
        pass

    def get_lines(self) -> list[str]:
        text = self._buf.getvalue()
        return [line for line in text.splitlines() if line.strip()]


def _build_fake_ts(portal: MagicMock | None = None) -> MagicMock:
    """Crea un mock de ``siemens_tia_scripting`` para los tests del worker.

    Mismo patron que ``test_persistent_worker_protocol._build_fake_ts``
    para mantener coherencia con el resto de la suite.
    """
    if portal is None:
        portal = MagicMock(name="FakePortal")
        portal.detach = MagicMock()
        portal.get_process_id = MagicMock(return_value=12345)
    ts = MagicMock(name="FakeSiemensWrapper")
    ts.attach_portal.return_value = portal
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


def _run_worker(
    stdin_payload: str,
    ts: MagicMock,
    registry: dict[str, Any],
) -> list[dict[str, Any]]:
    """Ejecuta ``main_persistent_loop`` con el entorno mockeado y captura los eventos.

    Args:
        stdin_payload: JSON lines separados por ``\\n`` con los
            comandos que el operario envia al worker.
        ts: Mock de ``siemens_tia_scripting``.
        registry: Handlers a registrar en el ``COMMAND_REGISTRY``.

    Returns:
        Lista de eventos capturados, cada uno con la forma
        ``{"level": int, "event": str, ...fields}``. El nivel
        ``level`` es el valor numerico de ``logging`` (e.g.
        ``logging.INFO == 20``) para que los asserts sean
        independientes del nombre.
    """
    events: list[dict[str, Any]] = []

    def _fake_log_event(logger, level, event, **fields):  # noqa: ARG001
        events.append({"level": level, "event": event, **fields})

    fake_logger = MagicMock(name="FakeWorkerLogger")
    fake_configure = MagicMock(name="FakeConfigure", return_value=fake_logger)

    stdin = io.StringIO(stdin_payload)
    stdout = _CapturingStdout()
    original_stdin, original_stdout = sys.stdin, sys.stdout
    try:
        sys.stdin = stdin
        sys.stdout = stdout
        with patch.object(worker_logging_mod, "log_event", side_effect=_fake_log_event), \
             patch.object(worker_logging_mod, "configure_worker_logger", fake_configure), \
             patch.object(worker_tia, "_load_siemens_wrapper", return_value=ts), \
             patch.object(worker_tia, "COMMAND_REGISTRY", registry):
            main_persistent_loop()
    finally:
        sys.stdin = original_stdin
        sys.stdout = original_stdout

    return events


def _filter_by_event(events: list[dict[str, Any]], event_name: str) -> list[dict[str, Any]]:
    """Filtra los eventos por nombre (util para asserts focalizados)."""
    return [e for e in events if e["event"] == event_name]


# ────────────────────────────────────────────────────────────────────────
# Test 1: worker_started se loguea al arrancar
# ────────────────────────────────────────────────────────────────────────


class TestWorkerStarted:
    """El primer evento al arrancar el subproceso es ``worker_started``."""

    def test_worker_started_emitted_at_startup(self) -> None:
        """Al invocar ``main_persistent_loop``, lo primero es ``worker_started`` (INFO)."""
        ts = _build_fake_ts()
        # stdin vacio -> el worker lee EOF y sale inmediatamente.
        events = _run_worker(stdin_payload="", ts=ts, registry={})

        started = _filter_by_event(events, "worker_started")
        assert len(started) == 1, (
            f"se esperaba exactamente 1 worker_started, got {len(started)}: {started!r}"
        )
        assert started[0]["level"] == logging.INFO
        # El pid es el del proceso actual (no se mockea, asi que es
        # el PID real del pytest).
        assert "pid" in started[0]
        assert isinstance(started[0]["pid"], int)
        assert started[0]["pid"] > 0
        # La marca ``persistent=True`` distingue este startup del
        # eventual 1-shot (modo MCP), que NO se loguea.
        assert started[0].get("persistent") is True

    def test_worker_stopped_emitted_on_eof(self) -> None:
        """Si stdin se cierra, se emite ``worker_stopped`` con reason='stdin_closed'."""
        ts = _build_fake_ts()
        events = _run_worker(stdin_payload="", ts=ts, registry={})

        stopped = _filter_by_event(events, "worker_stopped")
        assert len(stopped) == 1
        assert stopped[0]["level"] == logging.INFO
        assert stopped[0]["reason"] == "stdin_closed"


# ────────────────────────────────────────────────────────────────────────
# Test 2: command_received (y ping_received) al recibir comandos
# ────────────────────────────────────────────────────────────────────────


class TestCommandReceived:
    """Cada comando por stdin emite un evento de recepcion (DEBUG)."""

    def test_command_received_for_normal_command(self) -> None:
        """Un comando del registry (no ping) emite ``command_received`` con args_keys.

        El diseno dice: "Loguea command_received con request_id,
        command, args_keys" para todo comando que llega por stdin
        (excepto ``ping`` que tiene su propio evento). Por tanto
        ``attach_portal`` TAMBIEN genera un ``command_received``
        (ademas de su evento ``attach`` especifico). Esto da al
        operario una traza completa de TODO lo que llega al worker,
        no solo lo que pasa por el ``COMMAND_REGISTRY``.
        """
        ts = _build_fake_ts()

        def _fake_compile(portal, ts_arg, args):  # noqa: ARG001
            return True  # semantica Siemens: True = hay errores

        payload = (
            json.dumps(
                {"id": 1, "command": "attach_portal", "args": {"mode": "WithGraphicalUserInterface"}}
            )
            + "\n"
            + json.dumps(
                {"id": 2, "command": "compile_plc", "args": {"plc_name": "PLC1"}}
            )
            + "\n"
        )
        events = _run_worker(
            stdin_payload=payload, ts=ts, registry={"compile_plc": _fake_compile}
        )

        received = _filter_by_event(events, "command_received")
        # 2 command_received: uno para attach_portal (que ademas
        # emite su evento ``attach``) y otro para compile_plc.
        assert len(received) == 2
        commands = {e["command"] for e in received}
        assert commands == {"attach_portal", "compile_plc"}
        # El de compile_plc lleva args_keys (no args completas, por
        # info sensible tipo passwords de TIA).
        compile_event = next(e for e in received if e["command"] == "compile_plc")
        assert compile_event["request_id"] == 2
        assert compile_event["args_keys"] == ["plc_name"]
        assert compile_event["level"] == logging.DEBUG
        # El de attach_portal lleva su args (mode).
        attach_event = next(e for e in received if e["command"] == "attach_portal")
        assert attach_event["args_keys"] == ["mode"]

    def test_ping_received_for_heartbeat(self) -> None:
        """Un comando ``ping`` emite ``ping_received`` (NO ``command_received``)."""
        ts = _build_fake_ts()

        def _fake_ping(portal, ts_arg, args):  # noqa: ARG001
            return {"ok": True, "pid": 42}

        payload = (
            json.dumps(
                {"id": 1, "command": "attach_portal", "args": {"mode": "WithGraphicalUserInterface"}}
            )
            + "\n"
            + json.dumps({"id": 7, "command": "ping", "args": {}})
            + "\n"
        )
        events = _run_worker(
            stdin_payload=payload, ts=ts, registry={"ping": _fake_ping}
        )

        ping_received = _filter_by_event(events, "ping_received")
        assert len(ping_received) == 1
        assert ping_received[0]["request_id"] == 7
        assert ping_received[0]["level"] == logging.DEBUG

        # Y NO hay ``command_received`` para el ping (por diseno, ping
        # tiene su propio evento para no inflar el nivel INFO).
        cmd_received = _filter_by_event(events, "command_received")
        assert all(e["command"] != "ping" for e in cmd_received), (
            "ping no debe generar command_received; solo ping_received"
        )


# ────────────────────────────────────────────────────────────────────────
# Test 3: command_completed al terminar OK un handler
# ────────────────────────────────────────────────────────────────────────


class TestCommandCompleted:
    """Al terminar OK un handler del registry, se emite ``command_completed`` (INFO)."""

    def test_command_completed_with_duration_and_result_type(self) -> None:
        """El evento lleva ``duration_ms`` (int) y ``result_type`` (str)."""
        ts = _build_fake_ts()

        def _fake_list_plcs(portal, ts_arg, args):  # noqa: ARG001
            return [{"name": "PLC1", "short_designation": "CPU 1518"}]

        payload = (
            json.dumps(
                {"id": 1, "command": "attach_portal", "args": {"mode": "WithGraphicalUserInterface"}}
            )
            + "\n"
            + json.dumps({"id": 3, "command": "list_plcs", "args": {}})
            + "\n"
        )
        events = _run_worker(
            stdin_payload=payload, ts=ts, registry={"list_plcs": _fake_list_plcs}
        )

        completed = _filter_by_event(events, "command_completed")
        assert len(completed) == 1
        assert completed[0]["command"] == "list_plcs"
        assert completed[0]["request_id"] == 3
        assert completed[0]["level"] == logging.INFO
        # ``duration_ms`` es un entero (no logueamos time.time, usamos
        # time.monotonic, asi que el valor es positivo y razonable).
        assert isinstance(completed[0]["duration_ms"], int)
        assert completed[0]["duration_ms"] >= 0
        # ``result_type`` es el nombre de la clase del retorno.
        assert completed[0]["result_type"] == "list"


# ────────────────────────────────────────────────────────────────────────
# Test 4: command_failed cuando un handler lanza excepcion
# ────────────────────────────────────────────────────────────────────────


class TestCommandFailed:
    """Si el handler lanza, se emite ``command_failed`` (ERROR) con la causa."""

    def test_command_failed_carries_error_class_and_msg(self) -> None:
        """El evento lleva ``error_class`` (nombre de la excepcion) y ``error_msg``."""
        ts = _build_fake_ts()

        def _fake_explode(portal, ts_arg, args):  # noqa: ARG001
            raise ValueError("boom: argumento invalido")

        payload = (
            json.dumps(
                {"id": 1, "command": "attach_portal", "args": {"mode": "WithGraphicalUserInterface"}}
            )
            + "\n"
            + json.dumps({"id": 9, "command": "explode", "args": {}})
            + "\n"
        )
        events = _run_worker(
            stdin_payload=payload, ts=ts, registry={"explode": _fake_explode}
        )

        failed = _filter_by_event(events, "command_failed")
        assert len(failed) == 1
        assert failed[0]["command"] == "explode"
        assert failed[0]["request_id"] == 9
        assert failed[0]["level"] == logging.ERROR
        assert failed[0]["error_class"] == "ValueError"
        assert "boom" in failed[0]["error_msg"]
        assert isinstance(failed[0]["duration_ms"], int)
        # El handler fallo, asi que NO hay command_completed.
        assert len(_filter_by_event(events, "command_completed")) == 0


# ────────────────────────────────────────────────────────────────────────
# Test 5: worker_stopped al recibir "exit"
# ────────────────────────────────────────────────────────────────────────


class TestWorkerStoppedOnExit:
    """``exit`` cierra el loop y emite ``worker_stopped`` con reason='exit_command'."""

    def test_exit_emits_worker_stopped_with_exit_reason(self) -> None:
        ts = _build_fake_ts()
        payload = json.dumps({"id": 0, "command": "exit", "args": {}}) + "\n"
        events = _run_worker(stdin_payload=payload, ts=ts, registry={})

        stopped = _filter_by_event(events, "worker_stopped")
        assert len(stopped) == 1
        assert stopped[0]["level"] == logging.INFO
        assert stopped[0]["reason"] == "exit_command"


# ────────────────────────────────────────────────────────────────────────
# Test 6: attach / detach (eventos secundarios de ciclo de vida)
# ────────────────────────────────────────────────────────────────────────


class TestAttachDetachEvents:
    """``attach_portal`` y ``detach_portal`` emiten sus propios eventos."""

    def test_attach_emitted_with_pid_and_mode(self) -> None:
        """``attach_portal`` exitoso emite ``attach`` (INFO) con pid y portal_mode."""
        ts = _build_fake_ts()
        payload = (
            json.dumps(
                {"id": 1, "command": "attach_portal", "args": {"mode": "WithGraphicalUserInterface"}}
            )
            + "\n"
        )
        events = _run_worker(stdin_payload=payload, ts=ts, registry={})

        attach = _filter_by_event(events, "attach")
        assert len(attach) == 1
        assert attach[0]["level"] == logging.INFO
        assert attach[0]["pid"] == 12345  # el que devuelve el mock
        assert attach[0]["portal_mode"] == "WithGraphicalUserInterface"
        assert isinstance(attach[0]["duration_ms"], int)
        assert attach[0]["duration_ms"] >= 0

    def test_detach_emitted_with_duration(self) -> None:
        """``detach_portal`` emite ``detach`` (INFO) con duration_ms."""
        ts = _build_fake_ts()
        payload = (
            json.dumps(
                {"id": 1, "command": "attach_portal", "args": {"mode": "WithGraphicalUserInterface"}}
            )
            + "\n"
            + json.dumps({"id": 2, "command": "detach_portal", "args": {}})
            + "\n"
        )
        events = _run_worker(stdin_payload=payload, ts=ts, registry={})

        detach = _filter_by_event(events, "detach")
        assert len(detach) == 1
        assert detach[0]["level"] == logging.INFO
        assert isinstance(detach[0]["duration_ms"], int)
        assert detach[0]["duration_ms"] >= 0

    def test_attach_failed_emitted_on_exception(self) -> None:
        """Si ``ts.attach_portal`` lanza, se emite ``attach_failed`` (WARNING)."""
        ts = _build_fake_ts()
        # Forzamos a que attach_portal lance.
        ts.attach_portal.side_effect = RuntimeError("TIA no encontrada")

        payload = (
            json.dumps(
                {"id": 1, "command": "attach_portal", "args": {"mode": "WithGraphicalUserInterface"}}
            )
            + "\n"
        )
        events = _run_worker(stdin_payload=payload, ts=ts, registry={})

        failed = _filter_by_event(events, "attach_failed")
        assert len(failed) == 1
        assert failed[0]["level"] == logging.WARNING
        assert failed[0]["error_class"] == "RuntimeError"
        assert "TIA no encontrada" in failed[0]["error_msg"]
        # Y NO hay attach exitoso.
        assert len(_filter_by_event(events, "attach")) == 0


# ────────────────────────────────────────────────────────────────────────
# Test extra: ping_completed (variante de command_completed para pings)
# ────────────────────────────────────────────────────────────────────────


class TestPingCompleted:
    """``ping`` se loguea con su propio evento (DEBUG), no con command_completed."""

    def test_ping_completed_emitted_with_pid(self) -> None:
        """``ping`` exitoso emite ``ping_completed`` (DEBUG) con pid."""
        ts = _build_fake_ts()

        def _fake_ping(portal, ts_arg, args):  # noqa: ARG001
            return {"ok": True, "pid": 4242}

        payload = (
            json.dumps(
                {"id": 1, "command": "attach_portal", "args": {"mode": "WithGraphicalUserInterface"}}
            )
            + "\n"
            + json.dumps({"id": 4, "command": "ping", "args": {}})
            + "\n"
        )
        events = _run_worker(
            stdin_payload=payload, ts=ts, registry={"ping": _fake_ping}
        )

        ping_completed = _filter_by_event(events, "ping_completed")
        assert len(ping_completed) == 1
        assert ping_completed[0]["request_id"] == 4
        assert ping_completed[0]["level"] == logging.DEBUG
        assert ping_completed[0]["ok"] is True
        assert ping_completed[0]["pid"] == 4242
        assert isinstance(ping_completed[0]["duration_ms"], int)

        # ping no genera command_completed (por diseno).
        assert len(_filter_by_event(events, "command_completed")) == 0


# ────────────────────────────────────────────────────────────────────────
# Test extra: el orden de eventos es coherente
# ────────────────────────────────────────────────────────────────────────


class TestEventOrdering:
    """El orden de los eventos refleja la cronologia del worker."""

    def test_event_order_for_simple_session(self) -> None:
        """Para una sesion attach -> ping -> detach -> exit, los eventos siguen ese orden.

        Cronologia esperada:
          1. worker_started
          2. attach (despues de attach_portal OK)
          3. ping_received
          4. ping_completed
          5. detach (despues de detach_portal OK)
          6. worker_stopped (reason=exit_command)
        """
        ts = _build_fake_ts()

        def _fake_ping(portal, ts_arg, args):  # noqa: ARG001
            return {"ok": True, "pid": 1}

        payload = (
            json.dumps(
                {"id": 1, "command": "attach_portal", "args": {"mode": "WithGraphicalUserInterface"}}
            )
            + "\n"
            + json.dumps({"id": 2, "command": "ping", "args": {}})
            + "\n"
            + json.dumps({"id": 3, "command": "detach_portal", "args": {}})
            + "\n"
            + json.dumps({"id": 4, "command": "exit", "args": {}})
            + "\n"
        )
        events = _run_worker(
            stdin_payload=payload, ts=ts, registry={"ping": _fake_ping}
        )

        # Solo nos interesan los nombres de evento, en orden.
        names = [e["event"] for e in events]
        # worker_started es el primero (sin condiciones).
        assert names[0] == "worker_started", (
            f"el primer evento debe ser worker_started, got {names[0]!r}"
        )
        # worker_stopped es el ultimo.
        assert names[-1] == "worker_stopped", (
            f"el ultimo evento debe ser worker_stopped, got {names[-1]!r}"
        )
        # En medio, attach aparece antes que ping_received, que aparece
        # antes que ping_completed, que aparece antes que detach.
        idx_attach = names.index("attach")
        idx_ping_recv = names.index("ping_received")
        idx_ping_done = names.index("ping_completed")
        idx_detach = names.index("detach")
        assert idx_attach < idx_ping_recv < idx_ping_done < idx_detach, (
            f"orden incorrecto: {names!r}"
        )
