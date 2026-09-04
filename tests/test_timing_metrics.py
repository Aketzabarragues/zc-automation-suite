"""Tests de las métricas de timing del gateway y del worker OT.

Cubre el PR de observabilidad (``_plan/10``-driven):

- **Gateway:** ``_dispatch_worker`` acumula el ``dispatch_total_ms``
  en ``self._metrics`` y loguea una línea ``[GATEWAY TIMING]`` a
  stderr. ``get_metrics()`` devuelve min/max/avg/count por comando.
  Los errores también se miden (el ``finally`` siempre corre).

- **Worker:** ``main()`` emite al stderr un JSON ``worker_timing``
  con los 4 campos (``load_dll_ms``, ``attach_portal_ms``,
  ``handler_ms``, ``detach_ms``) usando ``time.monotonic()`` (NO
  ``time.time()``, inmune a saltos NTP). Comandos que no hacen
  attach (``attach_portal``, ``open_new_portal``) reportan
  ``attach_portal_ms: null``.

Estrategia de testing:

- Gateway: mockeamos ``asyncio.create_subprocess_exec`` a nivel de
  módulo (mismo patrón que ``test_gateway_connection_error.py``).
  Capturamos stderr y parseamos las líneas ``[GATEWAY TIMING]``.

- Worker: ejecutamos ``worker_tia.main()`` en el mismo proceso con
  ``_load_siemens_wrapper`` y ``COMMAND_REGISTRY`` mockeados
  (mismo patrón que ``test_procesos_worker.py`` y
  ``test_disp_comment_handlers.py``). Así NO lanzamos subproceso
  real (sería muy lento y frágil) pero verificamos que el
  instrumentado emite el JSON correcto.
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


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_fake_subprocess(
    json_response: dict,
    stderr_text: str = "",
    returncode: int = 0,
    delay_s: float = 0.0,
) -> MagicMock:
    """Crea un mock de ``Process`` que devuelve ``json_response`` por stdout.

    ``delay_s`` permite simular latencia real (la ``proc.communicate``
    esperará ese tiempo antes de devolver), útil para verificar
    que el timing del gateway se aproxima al wall-clock del mock.
    """
    import asyncio as _asyncio

    proc = MagicMock(name="FakeSubprocess")
    proc.returncode = returncode
    proc.kill = MagicMock()

    async def _communicate(input=None):  # noqa: ARG001
        if delay_s > 0:
            await _asyncio.sleep(delay_s)
        return (
            (json.dumps(json_response) + "\n").encode("utf-8"),
            stderr_text.encode("utf-8"),
        )

    proc.communicate = _communicate

    async def _wait():
        return None

    proc.wait = _wait
    return proc


def _extract_timing_lines(stderr_text: str, prefix: str) -> list[str]:
    """Devuelve las líneas ``[PREFIX] ...`` en stderr (sin parsear).

    El gateway usa formato ``key=value`` plano y el worker usa JSON.
    Esta función devuelve las líneas crudas; el caller decide cómo
    parsearlas.
    """
    out: list[str] = []
    for line in stderr_text.splitlines():
        line = line.strip()
        if line.startswith(prefix + " "):
            out.append(line[len(prefix) + 1 :])
    return out


def _extract_worker_timing_json(stderr_text: str) -> list[dict]:
    """Devuelve los payloads JSON de las líneas ``[WORKER TIMING] {...}``."""
    out: list[dict] = []
    for raw in _extract_timing_lines(stderr_text, "[WORKER TIMING]"):
        out.append(json.loads(raw))
    return out


def _extract_gateway_timing_kv(stderr_text: str) -> list[dict]:
    """Devuelve los payloads ``key=value`` de las líneas ``[GATEWAY TIMING]``."""
    out: list[dict] = []
    for raw in _extract_timing_lines(stderr_text, "[GATEWAY TIMING]"):
        # Formato: command='X' dispatch_total_ms=N
        import re

        m = re.match(r"command='([^']*)'\s+dispatch_total_ms=(-?\d+)", raw)
        assert m, f"unexpected gateway timing line: {raw!r}"
        out.append({"command": m.group(1), "dispatch_total_ms": int(m.group(2))})
    return out


# ── Tests del gateway: instrumentación de _dispatch_worker ───────────────


class TestDispatchWorkerTiming:
    """Verifica que ``_dispatch_worker`` mide y acumula el timing."""

    @pytest.mark.asyncio
    async def test_dispatch_worker_acumula_metricas_en_exito(self) -> None:
        """Tras 1 dispatch exitoso, ``_metrics`` tiene 1 entrada."""
        gateway = TIAProcessGateway()
        fake_proc = _make_fake_subprocess({"ok": True, "result": ["PLC1"]})

        stderr_capture = io.StringIO()
        with patch(
            "core.infrastructure.gateway.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=fake_proc),
        ):
            with patch("sys.stderr", stderr_capture):
                result = await gateway._dispatch_worker("list_plcs")

        assert result == ["PLC1"]
        assert "list_plcs" in gateway._metrics
        assert len(gateway._metrics["list_plcs"]) == 1
        # El timing debe ser >= 0 y < 5s (test wall-clock).
        ms = gateway._metrics["list_plcs"][0]
        assert 0 <= ms < 5000

    @pytest.mark.asyncio
    async def test_dispatch_worker_tambien_mide_en_error(self) -> None:
        """Errores del subproceso también se miden (el finally siempre corre)."""
        gateway = TIAProcessGateway()
        fake_proc = _make_fake_subprocess({
            "ok": False,
            "error": "ValueError: division by zero",
        })

        stderr_capture = io.StringIO()
        with patch(
            "core.infrastructure.gateway.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=fake_proc),
        ):
            with patch("sys.stderr", stderr_capture):
                with pytest.raises(RuntimeError, match="ValueError"):
                    await gateway._dispatch_worker("list_plcs")

        # Métrica registrada aunque haya habido error.
        assert "list_plcs" in gateway._metrics
        assert len(gateway._metrics["list_plcs"]) == 1

    @pytest.mark.asyncio
    async def test_dispatch_worker_tambien_mide_en_timeout(self) -> None:
        """TimeoutError también se mide (caso común en operaciones largas)."""
        gateway = TIAProcessGateway(timeout=0.05)  # 50ms

        proc = MagicMock(name="SlowSubprocess")
        proc.returncode = -1
        proc.kill = MagicMock()
        proc.wait = AsyncMock()

        async def _slow_communicate(input=None):  # noqa: ARG001
            await asyncio.sleep(1.0)  # más que el timeout
            return (b"", b"")

        proc.communicate = _slow_communicate

        stderr_capture = io.StringIO()
        with patch(
            "core.infrastructure.gateway.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=proc),
        ):
            with patch("sys.stderr", stderr_capture):
                with pytest.raises(RuntimeError, match="Timeout"):
                    await gateway._dispatch_worker("slow_op")

        # El timing se acumuló pese al timeout.
        assert "slow_op" in gateway._metrics
        assert len(gateway._metrics["slow_op"]) == 1
        # Y el log stderr también salió.
        timing_lines = _extract_gateway_timing_kv(
            stderr_capture.getvalue()
        )
        assert len(timing_lines) == 1
        assert timing_lines[0]["command"] == "slow_op"

    @pytest.mark.asyncio
    async def test_dispatch_worker_loguea_timing_en_stderr(self) -> None:
        """El formato del log es ``[GATEWAY TIMING] command=... dispatch_total_ms=...``."""
        gateway = TIAProcessGateway()
        fake_proc = _make_fake_subprocess({"ok": True, "result": None})

        stderr_capture = io.StringIO()
        with patch(
            "core.infrastructure.gateway.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=fake_proc),
        ):
            with patch("sys.stderr", stderr_capture):
                await gateway._dispatch_worker("list_plcs")

        lines = _extract_gateway_timing_kv(stderr_capture.getvalue())
        assert len(lines) == 1
        assert lines[0]["command"] == "list_plcs"
        assert "dispatch_total_ms" in lines[0]
        # Verificación adicional del formato crudo.
        raw = stderr_capture.getvalue()
        assert "[GATEWAY TIMING] command='list_plcs'" in raw
        assert "dispatch_total_ms=" in raw

    @pytest.mark.asyncio
    async def test_multiples_invocaciones_acumulan(self) -> None:
        """N invocaciones del mismo comando → N entradas en la lista."""
        gateway = TIAProcessGateway()
        fake_proc = _make_fake_subprocess({"ok": True, "result": []})

        stderr_capture = io.StringIO()
        with patch(
            "core.infrastructure.gateway.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=fake_proc),
        ):
            with patch("sys.stderr", stderr_capture):
                for _ in range(5):
                    await gateway._dispatch_worker("list_plcs")

        assert gateway._metrics["list_plcs"] == pytest.approx(
            gateway._metrics["list_plcs"], rel=0  # solo verificamos la longitud
        )
        assert len(gateway._metrics["list_plcs"]) == 5

    @pytest.mark.asyncio
    async def test_comandos_distintos_tienen_keys_distintas(self) -> None:
        """Cada comando tiene su propia lista de timings."""
        gateway = TIAProcessGateway()

        async def _one(cmd, payload):
            p = _make_fake_subprocess(payload)
            with patch(
                "core.infrastructure.gateway.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=p),
            ):
                with patch("sys.stderr", io.StringIO()):
                    await gateway._dispatch_worker(cmd)

        await _one("list_plcs", {"ok": True, "result": []})
        await _one("compile_plc", {"ok": True, "result": None})
        await _one("list_plcs", {"ok": True, "result": []})

        assert "list_plcs" in gateway._metrics
        assert "compile_plc" in gateway._metrics
        assert len(gateway._metrics["list_plcs"]) == 2
        assert len(gateway._metrics["compile_plc"]) == 1


# ── Tests del gateway: get_metrics() ─────────────────────────────────────


class TestGetMetrics:
    """Verifica la forma de las stats públicas."""

    @pytest.mark.asyncio
    async def test_get_metrics_vacio_sin_invocaciones(self) -> None:
        """Sin dispatch, devuelve dict vacío."""
        gateway = TIAProcessGateway()
        assert gateway.get_metrics() == {}

    @pytest.mark.asyncio
    async def test_get_metrics_shape_basico(self) -> None:
        """Cada comando tiene count/min_ms/max_ms/avg_ms."""
        gateway = TIAProcessGateway()
        fake_proc = _make_fake_subprocess({"ok": True, "result": []})

        with patch(
            "core.infrastructure.gateway.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=fake_proc),
        ):
            with patch("sys.stderr", io.StringIO()):
                for _ in range(3):
                    await gateway._dispatch_worker("list_plcs")

        metrics = gateway.get_metrics()
        assert "list_plcs" in metrics
        stats = metrics["list_plcs"]
        assert stats["count"] == 3
        assert stats["min_ms"] >= 0
        assert stats["max_ms"] >= stats["min_ms"]
        # avg está entre min y max (inclusive).
        assert stats["min_ms"] <= stats["avg_ms"] <= stats["max_ms"]

    @pytest.mark.asyncio
    async def test_get_metrics_con_delays_simulados(self) -> None:
        """Stats reflejan los delays del mock (min <= max)."""
        gateway = TIAProcessGateway()

        async def _one(delay):
            p = _make_fake_subprocess(
                {"ok": True, "result": []}, delay_s=delay
            )
            with patch(
                "core.infrastructure.gateway.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=p),
            ):
                with patch("sys.stderr", io.StringIO()):
                    await gateway._dispatch_worker("slow_op")

        await _one(0.001)  # ~1ms
        await _one(0.010)  # ~10ms
        await _one(0.100)  # ~100ms

        stats = gateway.get_metrics()["slow_op"]
        assert stats["count"] == 3
        # min debe ser claramente menor que max (los delays son 10x y 100x).
        assert stats["min_ms"] < stats["max_ms"] / 5

    def test_get_metrics_devuelve_copia(self) -> None:
        """Mutar el resultado NO afecta al estado interno."""
        gateway = TIAProcessGateway()
        gateway._metrics["list_plcs"] = [10.0, 20.0, 30.0]
        snapshot = gateway.get_metrics()
        snapshot["list_plcs"]["count"] = 999
        snapshot["injected"] = {"count": 1}
        # El estado interno intacto.
        assert gateway._metrics["list_plcs"] == [10.0, 20.0, 30.0]
        assert "injected" not in gateway._metrics


# ── Tests del worker: instrumentación de main() ──────────────────────────


def _build_fake_ts() -> MagicMock:
    """Crea un mock de ``siemens_tia_scripting`` para los tests de main().

    El mock implementa lo mínimo que ``main()`` necesita:
      - ``Enums.PortalMode.AnyUserInterface`` (cualquier valor sirve).
      - ``attach_portal(...)`` retorna un portal con ``detach()``.
      - ``set_logging(path=..., console=...)`` es no-op.
    """
    ts = MagicMock(name="FakeSiemensWrapper")
    # Portal mock con detach() síncrono.
    portal = MagicMock(name="FakePortal")
    portal.detach = MagicMock()
    ts.attach_portal.return_value = portal
    ts.Enums.PortalMode.AnyUserInterface = "AnyUserInterface"
    return ts


class TestWorkerMainTiming:
    """Verifica que ``main()`` emite el JSON ``worker_timing`` a stderr."""

    def test_main_emite_worker_timing_json_en_stderr(self) -> None:
        """Comando normal: 4 campos + command + event en stderr."""
        ts = _build_fake_ts()
        fake_portal = ts.attach_portal.return_value

        def _handler(portal, ts_arg, handler_args):  # noqa: ARG001
            return ["PLC1"]

        stdin_payload = json.dumps({"command": "list_plcs", "args": {}})

        original_stdin, original_stdout, original_stderr = sys.stdin, sys.stdout, sys.stderr
        stdout_capture, stderr_capture = io.StringIO(), io.StringIO()
        try:
            sys.stdin = io.StringIO(stdin_payload)
            sys.stdout = stdout_capture
            sys.stderr = stderr_capture
            with patch.object(worker_tia, "_load_siemens_wrapper", return_value=ts), \
                 patch.object(worker_tia, "COMMAND_REGISTRY", {"list_plcs": _handler}), \
                 patch.object(worker_tia, "_write_json_and_exit") as mock_exit:
                worker_tia.main()
        finally:
            sys.stdin, sys.stdout, sys.stderr = original_stdin, original_stdout, original_stderr

        # Verificar que ts.attach_portal fue invocado.
        ts.attach_portal.assert_called_once()
        # Verificar que portal.detach fue invocado.
        fake_portal.detach.assert_called_once()
        # Verificar el JSON de timing.
        timing_lines = _extract_worker_timing_json(
            stderr_capture.getvalue()
        )
        assert len(timing_lines) == 1
        timing = timing_lines[0]
        assert timing["event"] == "worker_timing"
        assert timing["command"] == "list_plcs"
        assert set(timing.keys()) == {
            "event", "command",
            "load_dll_ms", "attach_portal_ms", "handler_ms", "detach_ms",
        }
        # Los 4 campos son enteros (ms) o None.
        for key in ("load_dll_ms", "attach_portal_ms", "handler_ms", "detach_ms"):
            assert timing[key] is None or isinstance(timing[key], int)
        # El comando hizo attach → attach_portal_ms NO es None.
        assert timing["attach_portal_ms"] is not None
        assert timing["handler_ms"] is not None
        assert timing["detach_ms"] is not None

    def test_main_attach_portal_no_hace_attach_previo(self) -> None:
        """Comandos ``attach_portal`` / ``open_new_portal`` saltan el attach previo.

        En ese caso, ``attach_portal_ms`` debe ser ``null`` en el JSON
        (campo no aplicable).
        """
        ts = _build_fake_ts()
        ts.attach_portal.return_value = None  # el handler falla pero el attach previo se salta

        def _handler(portal, ts_arg, handler_args):  # noqa: ARG001
            # El handler hace su propio attach, devolvemos un portal dummy.
            return {"ok": True}

        stdin_payload = json.dumps({"command": "attach_portal", "args": {}})

        original_stdin, original_stdout, original_stderr = sys.stdin, sys.stdout, sys.stderr
        stdout_capture, stderr_capture = io.StringIO(), io.StringIO()
        try:
            sys.stdin = io.StringIO(stdin_payload)
            sys.stdout = stdout_capture
            sys.stderr = stderr_capture
            with patch.object(worker_tia, "_load_siemens_wrapper", return_value=ts), \
                 patch.object(worker_tia, "COMMAND_REGISTRY", {"attach_portal": _handler}), \
                 patch.object(worker_tia, "_write_json_and_exit") as mock_exit:
                worker_tia.main()
        finally:
            sys.stdin, sys.stdout, sys.stderr = original_stdin, original_stdout, original_stderr

        # El attach_portal global NO se llamó (lo hace el handler).
        ts.attach_portal.assert_not_called()
        # Pero el JSON de timing sí se emitió.
        timing_lines = _extract_worker_timing_json(
            stderr_capture.getvalue()
        )
        assert len(timing_lines) == 1
        timing = timing_lines[0]
        assert timing["command"] == "attach_portal"
        # attach_portal_ms y detach_ms son null (no se ejecutaron).
        assert timing["attach_portal_ms"] is None
        assert timing["detach_ms"] is None
        # load_dll_ms y handler_ms sí se emitieron.
        assert timing["load_dll_ms"] is not None
        assert timing["handler_ms"] is not None

    def test_main_emite_timing_incluso_si_handler_falla(self) -> None:
        """Errores del handler también emiten el JSON (el finally siempre corre)."""
        ts = _build_fake_ts()
        fake_portal = ts.attach_portal.return_value

        def _handler(portal, ts_arg, handler_args):  # noqa: ARG001
            raise RuntimeError("handler boom")

        stdin_payload = json.dumps({"command": "list_plcs", "args": {}})

        original_stdin, original_stdout, original_stderr = sys.stdin, sys.stdout, sys.stderr
        stdout_capture, stderr_capture = io.StringIO(), io.StringIO()
        try:
            sys.stdin = io.StringIO(stdin_payload)
            sys.stdout = stdout_capture
            sys.stderr = stderr_capture
            with patch.object(worker_tia, "_load_siemens_wrapper", return_value=ts), \
                 patch.object(worker_tia, "COMMAND_REGISTRY", {"list_plcs": _handler}), \
                 patch.object(worker_tia, "_write_json_and_exit") as mock_exit:
                worker_tia.main()
        finally:
            sys.stdin, sys.stdout, sys.stderr = original_stdin, original_stdout, original_stderr

        # El detach se llamó (finally).
        fake_portal.detach.assert_called_once()
        # El JSON de timing se emitió.
        timing_lines = _extract_worker_timing_json(
            stderr_capture.getvalue()
        )
        assert len(timing_lines) == 1
        assert timing_lines[0]["command"] == "list_plcs"
        # handler_ms es null (handler lanzó antes de finalizar).
        assert timing_lines[0]["handler_ms"] is None
        # Pero attach sí terminó, y detach también.
        assert timing_lines[0]["attach_portal_ms"] is not None
        assert timing_lines[0]["detach_ms"] is not None
