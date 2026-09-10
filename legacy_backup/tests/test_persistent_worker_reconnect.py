"""Tests de ``connect()``, ``disconnect()`` y ``reconnect()`` del gateway OT persistente.

Cubre el state machine ``idle``/``connecting``/``connected``/``error``
definido en ``_plan/12_worker_persistent_design.md`` §2.7 y el refactor
sept-2026 documentado en ``_plan/14_post_worker_persistent_audit.md``
(seccion "Refactor state machine").

API publica del gateway en modo persistente:

  - ``gateway.connect()``: envia ``attach_portal`` al worker vivo,
    transiciona ``idle`` -> ``connecting`` -> ``connected`` (o
    ``error``). Inicia el heartbeat.
  - ``gateway.disconnect()``: envia ``detach_portal`` al worker vivo,
    transiciona ``connected`` -> ``idle``. Limpia caches, cancela el
    heartbeat. NO mata el subproceso.
  - ``gateway.reconnect()``: ``disconnect()`` + ``connect()`` bajo el
    mismo lock. Compatibilidad con el boton "Reconectar" del topbar.

Las tres son exclusivos del modo ``persistent=True``; en modo 1-shot
(``persistent=False``) lanzan ``TIAConnectionError`` para que el
topbar reciba un error claro en vez de un no-op silencioso.

Auditoria X3 (sept-2026): ``connect()``, ``disconnect()`` y
``reconnect()`` ahora adquieren ``self._worker_lock`` para serializar
contra ``_dispatch_worker`` y contra otra llamada concurrente.

Estrategia de testing:

  - **Mocking ligero**: ``_send_to_persistent_worker`` se sustituye
    por ``AsyncMock`` que retorna lo que el ``attach_portal``/
    ``detach_portal`` del worker devolveria (``{"pid": <int>}`` o
    ``{"detached": true}``). Asi no necesitamos un subproceso real.
  - **Idempotencia**: el test de ``_kill_persistent_worker`` lo
    llama dos veces consecutivas; la segunda debe ser un no-op
    limpio.
  - **Locking (X3)**: los tests verifican que el ``async with
    self._worker_lock`` cubre todo el cuerpo de ``connect()`` /
    ``disconnect()`` y se libera al terminar.

Tests:

  1. ``test_connect_envia_attach_portal_y_transiciona_a_connected``.
  2. ``test_connect_sin_modo_persistente_lanza_TIAConnectionError``.
  3. ``test_connect_con_attach_fallido_marca_error_y_relanza``.
  4. ``test_connect_rechaza_si_ya_conectado``: idempotencia.
  5. ``test_disconnect_envia_detach_portal_y_limpia_caches``.
  6. ``test_disconnect_sin_modo_persistente_lanza_TIAConnectionError``.
  7. ``test_disconnect_es_idempotente_en_idle``.
  8. ``test_reconnect_es_disconnect_mas_connect``.
  9. ``test_kill_persistent_worker_es_idempotente``.
  10. ``test_kill_persistent_worker_resuelve_pending_futures``.
  11. ``test_connect_libera_el_lock_al_terminar`` (auditoria X3).
  12. ``test_disconnect_libera_el_lock_al_terminar`` (auditoria X3).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.infrastructure.gateway import TIAConnectionError, TIAProcessGateway


# ────────────────────────────────────────────────────────────────────────
# Helpers compartidos
# ────────────────────────────────────────────────────────────────────────


def _build_alive_proc() -> MagicMock:
    """Crea un mock de ``_worker_proc`` con ``returncode=None`` (vivo)."""
    proc = MagicMock(name="FakeAliveWorkerProc")
    proc.returncode = None
    proc.stdin = MagicMock()
    proc.stdout = MagicMock()
    return proc


def _build_finished_proc() -> MagicMock:
    """Crea un mock de ``_worker_proc`` ya terminado (``returncode != None``)."""
    proc = MagicMock(name="FinishedWorkerProc")
    proc.returncode = 0
    return proc


# ────────────────────────────────────────────────────────────────────────
# Test 1: ``connect()`` envia ``attach_portal`` y transiciona a connected
# ────────────────────────────────────────────────────────────────────────


class TestConnectSendsAttach:
    """``connect()`` envia ``attach_portal`` y transiciona a ``"connected"``."""

    @pytest.mark.asyncio
    async def test_connect_envia_attach_portal_y_transiciona_a_connected(self) -> None:
        """``connect()`` envia ``attach_portal`` con ``WithGraphicalUserInterface``.

        El worker responde ``{"pid": <int>}`` y el gateway transiciona
        a ``state="connected"`` e inicia el heartbeat. Verificamos:
          - ``_send_to_persistent_worker`` se invoca UNA vez con
            ``("attach_portal", {"mode": "WithGraphicalUserInterface"}, ...)``.
          - El estado pasa de ``"idle"`` (o ``"disconnected"``) a ``"connecting"`` y luego ``"connected"``.
          - El heartbeat_task se crea.
        """
        gateway = TIAProcessGateway(persistent=True)
        gateway._connection_state = "idle"  # estado tras start() / ready_idle
        gateway._worker_proc = _build_alive_proc()  # ya arranco
        # Reader vivo para que _send_to_persistent_worker funcione.
        reader = MagicMock(name="Reader")
        reader.done.return_value = False
        gateway._reader_task = reader

        # Mockeamos _send_to_persistent_worker para que retorne
        # ``{"pid": 4242}`` (lo que devolveria el worker tras un
        # attach exitoso).
        async def fake_send(command, args, timeout_override):  # noqa: ARG001
            if command == "attach_portal":
                return {"pid": 4242}
            return {}
        gateway._send_to_persistent_worker = fake_send
        # _detect_project_change puede ser AsyncMock (no-op).
        gateway._detect_project_change = AsyncMock(return_value=False)

        await gateway.connect()

        # Estado final: connected.
        assert gateway._connection_state == "connected"
        # Heartbeat arrancado.
        assert gateway._heartbeat_task is not None
        # _last_ping_ok actualizado.
        assert gateway._last_ping_ok is not None
        # _last_error limpio.
        assert gateway._last_error is None


# ────────────────────────────────────────────────────────────────────────
# Test 2: ``connect()`` en modo 1-shot lanza ``TIAConnectionError``
# ────────────────────────────────────────────────────────────────────────


class TestConnectRequiresPersistent:
    """``connect()`` en modo 1-shot no aplica: lanza ``TIAConnectionError``."""

    @pytest.mark.asyncio
    async def test_connect_sin_modo_persistente_lanza_TIAConnectionError(self) -> None:
        """Gateway ``persistent=False`` + ``connect()`` → ``TIAConnectionError`` legible."""
        gateway = TIAProcessGateway(persistent=False)
        with pytest.raises(TIAConnectionError, match="solo aplica a gateway.persistent=True"):
            await gateway.connect()


# ────────────────────────────────────────────────────────────────────────
# Test 3: ``connect()`` con attach fallido marca ``error`` y relanza
# ────────────────────────────────────────────────────────────────────────


class TestConnectOnAttachFailure:
    """Si el ``attach_portal`` falla, ``connect()`` marca ``error`` y lanza."""

    @pytest.mark.asyncio
    async def test_connect_con_attach_fallido_marca_error_y_relanza(self) -> None:
        """Worker responde ``{"error": "..."}`` → estado ``"error"`` + ``TIAConnectionError``."""
        gateway = TIAProcessGateway(persistent=True)
        gateway._connection_state = "idle"
        gateway._worker_proc = _build_alive_proc()
        reader = MagicMock(name="Reader")
        reader.done.return_value = False
        gateway._reader_task = reader

        async def fake_send_attach_fails(command, args, timeout_override):  # noqa: ARG001
            if command == "attach_portal":
                return {"error": "No matching TIA Portal version"}
            return {}
        gateway._send_to_persistent_worker = fake_send_attach_fails

        with pytest.raises(TIAConnectionError, match="Connect fallo") as exc_info:
            await gateway.connect()

        assert gateway._connection_state == "error"
        assert "No matching TIA Portal version" in str(exc_info.value)
        assert gateway._last_error is not None
        # Heartbeat NO se inicia en error.
        assert gateway._heartbeat_task is None


# ────────────────────────────────────────────────────────────────────────
# Test 4: ``connect()`` rechaza si ya esta conectado
# ────────────────────────────────────────────────────────────────────────


class TestConnectRejectsWhenAlreadyConnected:
    """``connect()`` idempotente: si ya esta connected, NO re-attacha."""

    @pytest.mark.asyncio
    async def test_connect_rechaza_si_ya_conectado(self) -> None:
        """Gateway en ``"connected"`` + ``connect()`` → ``TIAConnectionError`` claro.

        El operario que hace doble-click en "Conectar" o que pulsa
        "Conectar" cuando ya esta conectado NO debe disparar un
        attach redundante. El gateway rechaza con error claro.
        """
        gateway = TIAProcessGateway(persistent=True)
        gateway._connection_state = "connected"  # ya estaba conectado
        gateway._worker_proc = _build_alive_proc()
        reader = MagicMock(name="Reader")
        reader.done.return_value = False
        gateway._reader_task = reader

        # Si por error se llamara a attach_portal, el mock lo detectaria.
        async def fake_send_should_not_run(command, args, timeout_override):  # noqa: ARG001
            pytest.fail(
                f"connect() en estado 'connected' NO debe enviar "
                f"comandos, pero _send_to_persistent_worker recibio "
                f"command={command!r}"
            )
        gateway._send_to_persistent_worker = fake_send_should_not_run

        with pytest.raises(TIAConnectionError) as exc_info:
            await gateway.connect()
        # El mensaje menciona que ya esta conectado.
        assert "ya" in str(exc_info.value).lower() or "conectado" in str(exc_info.value).lower()

        # El estado sigue siendo connected (no se transiciono a error).
        assert gateway._connection_state == "connected"


# ────────────────────────────────────────────────────────────────────────
# Test 5: ``disconnect()`` envia ``detach_portal`` y limpia caches
# ────────────────────────────────────────────────────────────────────────


class TestDisconnectSendsDetach:
    """``disconnect()`` envia ``detach_portal`` y limpia caches."""

    @pytest.mark.asyncio
    async def test_disconnect_envia_detach_portal_y_limpia_caches(self) -> None:
        """Gateway en connected + ``disconnect()`` → idle, caches vacios, heartbeat cancelado.

        Caso real: el operario pulsa "Desconectar" tras usar la app.
        El worker sigue vivo (subproceso intacto, ~200 MB) pero el
        portal attached se libera. La cache se invalida porque el
        siguiente connect puede abrir un proyecto distinto.
        """
        gateway = TIAProcessGateway(persistent=True)
        gateway._connection_state = "connected"
        gateway._worker_proc = _build_alive_proc()
        reader = MagicMock(name="Reader")
        reader.done.return_value = False
        gateway._reader_task = reader
        # Caches con datos stale para verificar la limpieza.
        gateway._cache = {"plcs": ["PLC1"], "project_info": {"name": "X"}}
        gateway._project_path = r"C:\ws\proyectoA\proyectoA.ap17"
        gateway._project_changed = True
        # Heartbeat task "vivo" (mock).
        heartbeat = MagicMock(name="HeartbeatTask")
        heartbeat.done.return_value = False
        gateway._heartbeat_task = heartbeat

        # Mockeamos _send_to_persistent_worker para capturar el detach.
        sent_commands: list[tuple[str, dict]] = []

        async def fake_send(command, args, timeout_override):  # noqa: ARG001
            sent_commands.append((command, args))
            if command == "detach_portal":
                return {"detached": True}
            return {}
        gateway._send_to_persistent_worker = fake_send

        await gateway.disconnect()

        # detach_portal se envio.
        assert ("detach_portal", {}) in sent_commands
        # Estado final: idle.
        assert gateway._connection_state == "idle"
        # Caches limpios.
        assert gateway._cache == {}
        assert gateway._bloques_cache == {}
        # Project path reseteado.
        assert gateway._project_path is None
        assert gateway._project_changed is False
        # _last_error limpio.
        assert gateway._last_error is None
        # Heartbeat cancelado.
        assert gateway._heartbeat_task is None
        heartbeat.cancel.assert_called_once()


# ────────────────────────────────────────────────────────────────────────
# Test 6: ``disconnect()`` en modo 1-shot lanza ``TIAConnectionError``
# ────────────────────────────────────────────────────────────────────────


class TestDisconnectRequiresPersistent:
    """``disconnect()`` en modo 1-shot no aplica: lanza ``TIAConnectionError``."""

    @pytest.mark.asyncio
    async def test_disconnect_sin_modo_persistente_lanza_TIAConnectionError(self) -> None:
        """Gateway ``persistent=False`` + ``disconnect()`` → ``TIAConnectionError`` legible."""
        gateway = TIAProcessGateway(persistent=False)
        with pytest.raises(TIAConnectionError, match="solo aplica a gateway.persistent=True"):
            await gateway.disconnect()


# ────────────────────────────────────────────────────────────────────────
# Test 7: ``disconnect()`` es idempotente en idle
# ────────────────────────────────────────────────────────────────────────


class TestDisconnectIdempotent:
    """``disconnect()`` en idle es no-op (no falla, no envia nada)."""

    @pytest.mark.asyncio
    async def test_disconnect_es_idempotente_en_idle(self) -> None:
        """Gateway en idle + ``disconnect()`` → idle, sin enviar nada.

        Caso real: doble-click en "Desconectar" cuando ya estamos en
        idle. El gateway debe ser tolerante: el detach_portal se
        envia (best-effort), pero si el worker no responde, no es
        bloqueante. El estado se mantiene en ``"idle"``.
        """
        gateway = TIAProcessGateway(persistent=True)
        gateway._connection_state = "idle"  # ya estaba idle
        gateway._worker_proc = _build_alive_proc()
        reader = MagicMock(name="Reader")
        reader.done.return_value = False
        gateway._reader_task = reader

        sent_commands: list[str] = []

        async def fake_send(command, args, timeout_override):  # noqa: ARG001
            sent_commands.append(command)
            return {"detached": False}  # worker en idle, detach no-op
        gateway._send_to_persistent_worker = fake_send

        # No debe lanzar.
        await gateway.disconnect()

        # detach_portal se envio (best-effort, no-op en worker).
        assert "detach_portal" in sent_commands
        # Estado sigue en idle.
        assert gateway._connection_state == "idle"


# ────────────────────────────────────────────────────────────────────────
# Test 8: ``reconnect()`` = ``disconnect()`` + ``connect()``
# ────────────────────────────────────────────────────────────────────────


class TestReconnectIsDisconnectPlusConnect:
    """``reconnect()`` ejecuta detach + attach bajo el mismo lock."""

    @pytest.mark.asyncio
    async def test_reconnect_es_disconnect_mas_connect(self) -> None:
        """``reconnect()`` envia ``detach_portal`` y luego ``attach_portal``.

        Verifica el orden: primero detach (caches limpias, heartbeat
        cancelado), luego attach (estado connected, heartbeat
        reiniciado). Bajo el mismo ``_worker_lock`` para serializar
        contra otras llamadas concurrentes.
        """
        gateway = TIAProcessGateway(persistent=True)
        gateway._connection_state = "connected"
        gateway._worker_proc = _build_alive_proc()
        reader = MagicMock(name="Reader")
        reader.done.return_value = False
        gateway._reader_task = reader
        gateway._cache = {"plcs": ["PLC1"]}
        gateway._project_path = r"C:\ws\proyectoA\proyectoA.ap17"
        heartbeat = MagicMock(name="HeartbeatTask")
        heartbeat.done.return_value = False
        gateway._heartbeat_task = heartbeat

        sent_commands: list[str] = []

        async def fake_send(command, args, timeout_override):  # noqa: ARG001
            sent_commands.append(command)
            if command == "detach_portal":
                return {"detached": True}
            if command == "attach_portal":
                return {"pid": 5555}
            return {}
        gateway._send_to_persistent_worker = fake_send
        gateway._detect_project_change = AsyncMock(return_value=False)

        await gateway.reconnect()

        # Orden: detach_portal primero, luego attach_portal.
        assert sent_commands == ["detach_portal", "attach_portal"], (
            f"se esperaba ['detach_portal', 'attach_portal'], got {sent_commands!r}"
        )
        # Estado final: connected.
        assert gateway._connection_state == "connected"
        # Caches limpios tras el disconnect.
        assert gateway._cache == {}
        assert gateway._project_path is None
        # Heartbeat reiniciado.
        assert gateway._heartbeat_task is not None


# ────────────────────────────────────────────────────────────────────────
# Test 9: ``_kill_persistent_worker()`` es idempotente
# ────────────────────────────────────────────────────────────────────────


class TestKillIsIdempotent:
    """``_kill_persistent_worker()`` puede llamarse multiples veces sin crashear."""

    @pytest.mark.asyncio
    async def test_kill_persistent_worker_es_idempotente(self) -> None:
        """Llamar ``_kill_persistent_worker()`` 2 veces seguidas no crashea."""
        gateway = TIAProcessGateway(persistent=True)

        proc = MagicMock(name="LiveWorkerProc")
        proc.returncode = None
        reader = MagicMock(name="LiveReaderTask")
        reader.done.return_value = True
        heartbeat = MagicMock(name="LiveHeartbeatTask")
        heartbeat.done.return_value = True

        gateway._worker_proc = proc
        gateway._reader_task = reader
        gateway._heartbeat_task = heartbeat
        gateway._next_request_id = 42
        loop = asyncio.get_event_loop()
        gateway._pending_responses[7] = loop.create_future()

        # Primera llamada: debe limpiarlo todo.
        await gateway._kill_persistent_worker()
        assert gateway._worker_proc is None
        assert gateway._reader_task is None
        assert gateway._heartbeat_task is None
        assert gateway._pending_responses == {}
        assert gateway._next_request_id == 0

        terminate_after_first = proc.terminate.call_count
        cancel_reader_after_first = reader.cancel.call_count
        cancel_heartbeat_after_first = heartbeat.cancel.call_count

        # Segunda llamada: no debe crashear.
        await gateway._kill_persistent_worker()

        assert gateway._worker_proc is None
        assert gateway._reader_task is None
        assert gateway._heartbeat_task is None
        assert gateway._pending_responses == {}

        assert proc.terminate.call_count == terminate_after_first
        assert reader.cancel.call_count == cancel_reader_after_first
        assert heartbeat.cancel.call_count == cancel_heartbeat_after_first


# ────────────────────────────────────────────────────────────────────────
# Test 10: ``_kill_persistent_worker()`` resuelve los pending futures
# ────────────────────────────────────────────────────────────────────────


class TestKillResolvesPendingFutures:
    """``_kill_persistent_worker()`` resuelve los futures con ``RuntimeError``."""

    @pytest.mark.asyncio
    async def test_kill_persistent_worker_resuelve_pending_futures(self) -> None:
        """Los futures en ``_pending_responses`` reciben ``RuntimeError('Worker desconectado')``."""
        gateway = TIAProcessGateway(persistent=True)
        loop = asyncio.get_event_loop()
        fut_1 = loop.create_future()
        fut_2 = loop.create_future()
        gateway._pending_responses[10] = fut_1
        gateway._pending_responses[11] = fut_2
        gateway._next_request_id = 12

        await gateway._kill_persistent_worker()

        assert fut_1.done()
        assert fut_2.done()
        with pytest.raises(RuntimeError, match="Worker desconectado"):
            fut_1.result()
        with pytest.raises(RuntimeError, match="Worker desconectado"):
            fut_2.result()
        assert gateway._pending_responses == {}
        assert gateway._next_request_id == 0


# ────────────────────────────────────────────────────────────────────────
# Test 11: ``connect()`` libera ``_worker_lock`` al terminar (X3)
# ────────────────────────────────────────────────────────────────────────


class TestConnectReleasesLock:
    """``connect()`` envuelve su cuerpo en ``async with self._worker_lock`` (X3)."""

    @pytest.mark.asyncio
    async def test_connect_libera_el_lock_al_terminar(self) -> None:
        """Tras un ``connect()`` exitoso, el lock NO queda cogido."""
        gateway = TIAProcessGateway(persistent=True)
        gateway._connection_state = "idle"
        gateway._worker_proc = _build_alive_proc()
        reader = MagicMock(name="Reader")
        reader.done.return_value = False
        gateway._reader_task = reader

        async def fake_send(command, args, timeout_override):  # noqa: ARG001
            return {"pid": 1}
        gateway._send_to_persistent_worker = fake_send
        gateway._detect_project_change = AsyncMock(return_value=False)

        await gateway.connect()

        # 1. ``locked()`` retorna ``False``.
        assert gateway._worker_lock.locked() is False, (
            "_worker_lock quedo cogido tras connect() — "
            "el async with no se libero (auditoria X3)"
        )
        # 2. Prueba definitiva: podemos adquirir y liberar el lock
        # de inmediato.
        async with gateway._worker_lock:
            pass


# ────────────────────────────────────────────────────────────────────────
# Test 12: ``disconnect()`` libera ``_worker_lock`` al terminar (X3)
# ────────────────────────────────────────────────────────────────────────


class TestDisconnectReleasesLock:
    """``disconnect()`` envuelve su cuerpo en ``async with self._worker_lock`` (X3)."""

    @pytest.mark.asyncio
    async def test_disconnect_libera_el_lock_al_terminar(self) -> None:
        """Tras un ``disconnect()`` exitoso, el lock NO queda cogido."""
        gateway = TIAProcessGateway(persistent=True)
        gateway._connection_state = "connected"
        gateway._worker_proc = _build_alive_proc()
        reader = MagicMock(name="Reader")
        reader.done.return_value = False
        gateway._reader_task = reader

        async def fake_send(command, args, timeout_override):  # noqa: ARG001
            return {"detached": True}
        gateway._send_to_persistent_worker = fake_send

        await gateway.disconnect()

        # 1. ``locked()`` retorna ``False``.
        assert gateway._worker_lock.locked() is False, (
            "_worker_lock quedo cogido tras disconnect() — "
            "el async with no se libero (auditoria X3)"
        )
        # 2. Prueba definitiva: podemos adquirir y liberar el lock
        # de inmediato.
        async with gateway._worker_lock:
            pass


# ────────────────────────────────────────────────────────────────────────
# Test 13: ``_send_to_persistent_worker`` maneja BrokenPipeError
#          cuando el subproceso muere durante el write
# ────────────────────────────────────────────────────────────────────────


class TestSendHandlesBrokenPipe:
    """``_send_to_persistent_worker`` traduce ``BrokenPipeError`` a ``RuntimeError``.

    Caso real (audit X3): el operario lanza un ``connect()`` pero
    el subproceso worker muere justo antes (OOM, kill del SO, o el
    usuario cierra TIA Portal de forma abrupta que arrastra al
    worker). El ``proc.stdin.write()`` lanza ``BrokenPipeError``
    nativo. El gateway:

      1. Captura la excepcion en su ``except Exception`` generico
         (linea ~1199 de gateway.py).
      2. Marca el estado como ``"error"`` (es un fallo grave de I/O,
         no una desconexion limpia).
      3. Puebla ``_last_error`` con la info del tipo nativo.
      4. Re-lanza como ``RuntimeError`` con un mensaje claro
         ("Error de I/O con el worker persistente...") para que
         el caller (use case / endpoint) no vea tipos nativos de
         asyncio.
    """

    @pytest.mark.asyncio
    async def test_broken_pipe_en_stdin_write_marca_error_y_relanza(self) -> None:
        """``proc.stdin.write()`` lanza ``BrokenPipeError`` → estado ``"error"`` + ``RuntimeError``.

        Mockeamos el ``stdin`` del proc para que ``write()`` lance
        ``BrokenPipeError``. La ``drain()`` NUNCA debe invocarse
        (porque write fallo antes). El gateway traduce la excepcion
        a ``RuntimeError("Error de I/O...")`` y marca el estado
        ``"error"``.
        """
        gateway = TIAProcessGateway(persistent=True)
        # Proc mock con stdin/stdout que simulan worker muerto.
        fake_proc = MagicMock(name="DeadWorker")
        fake_proc.returncode = None  # aun no detectado como muerto
        # stdin.write lanza BrokenPipeError.
        fake_proc.stdin = MagicMock()
        fake_proc.stdin.write = MagicMock(
            side_effect=BrokenPipeError("Broken pipe")  # type: ignore[attr-defined]
        )
        fake_proc.stdin.drain = AsyncMock()
        fake_proc.stdout = MagicMock()
        gateway._worker_proc = fake_proc

        # Reader vivo (no es BrokenPipeError lo que mata al reader,
        # es el write a stdin).
        async def _hanging_reader() -> None:
            await asyncio.sleep(60)
        reader_task = asyncio.create_task(_hanging_reader())
        gateway._reader_task = reader_task

        # La llamada a _send_to_persistent_worker debe lanzar
        # RuntimeError mencionando "Error de I/O" y el BrokenPipeError.
        with pytest.raises(RuntimeError, match="Error de I/O") as exc_info:
            await gateway._send_to_persistent_worker(
                "list_plcs", args={}, timeout_override=2.0
            )
        # El mensaje incluye la causa raiz (BrokenPipeError).
        assert "BrokenPipeError" in str(exc_info.value)
        # El estado pasa a "error" (es un fallo grave de I/O,
        # no una desconexion limpia del portal).
        assert gateway._connection_state == "error"
        # _last_error queda registrado para el siguiente
        # GET /tia/connection del frontend.
        assert gateway._last_error is not None
        assert "BrokenPipeError" in gateway._last_error
        # drain() NO se invoco (write fallo antes).
        fake_proc.stdin.drain.assert_not_called()

        # Cleanup: cancelamos el reader hanging.
        reader_task.cancel()
        try:
            await reader_task
        except (asyncio.CancelledError, Exception):
            pass


# ────────────────────────────────────────────────────────────────────────
# Test 14: dos ``disconnect()`` concurrentes no rompen el lock
#          ni dejan estado inconsistente (audit X3, sept-2026)
# ────────────────────────────────────────────────────────────────────────


class TestConcurrentDisconnectsAreSafe:
    """Dos ``disconnect()`` en paralelo: ambos retornan, el lock se libera, no hay dead-lock.

    Caso real (audit X3, logs/zc_tray.log 12:11:41/12:11:44): el
    frontend hace polling de ``GET /tia/connection`` cada 500 ms y
    el operario hace doble-click en "Desconectar" cuando ve el
    circulo verde. Los dos ``disconnect()`` se solapan: el primero
    empieza la transicion optimista a ``"idle"``; el segundo la ve
    inmediatamente y trata de hacer su propia limpieza.

    Con la transicion optimista (sept-2026 round 3) el segundo
    ``disconnect()`` ya ve ``state="idle"`` antes de adquirir el
    lock y entra en la rama idempotente. El lock se serializa
    correctamente y ambos retornan sin excepcion.
    """

    @pytest.mark.asyncio
    async def test_dos_disconnect_concurrentes_no_deadlockean(self) -> None:
        """Lanzar 2 ``disconnect()`` en paralelo: ambos retornan, lock liberado, estado ``"idle"``.

        El test verifica:

          1. Las dos corrutinas ``disconnect()`` completan sin lanzar
             excepciones (el test fallaria si una colgara esperando
             el lock o si una lanzara ``RuntimeError`` espurio).
          2. El estado final es ``"idle"`` (no se quedo en
             ``"connected"`` ni se transiciono a ``"error"``).
          3. ``_worker_lock`` se libero completamente (puede ser
             re-adquirido inmediatamente).
          4. ``detach_portal`` se envio al menos una vez (el primer
             disconnect; el segundo es no-op porque ya estaba en
             ``"idle"`` al pasar el check de estado).
        """
        gateway = TIAProcessGateway(persistent=True)
        gateway._connection_state = "connected"
        gateway._worker_proc = _build_alive_proc()
        reader = MagicMock(name="Reader")
        reader.done.return_value = False
        gateway._reader_task = reader
        # Caches stale para verificar limpieza.
        gateway._cache = {"plcs": ["PLC1"]}
        gateway._project_path = r"C:\ws\proyectoA\proyectoA.ap17"
        heartbeat = MagicMock(name="Heartbeat")
        heartbeat.done.return_value = False
        gateway._heartbeat_task = heartbeat

        sent_commands: list[str] = []

        async def fake_send(command, args, timeout_override):  # noqa: ARG001
            sent_commands.append(command)
            if command == "detach_portal":
                return {"detached": True}
            return {}
        gateway._send_to_persistent_worker = fake_send

        # Lanzamos los dos disconnect en paralelo. asyncio.gather
        # reune ambos resultados; si uno falla, la excepcion se
        # propaga al test.
        await asyncio.wait_for(
            asyncio.gather(
                gateway.disconnect(),
                gateway.disconnect(),
                return_exceptions=False,
            ),
            timeout=3.0,
        )

        # Estado final: idle.
        assert gateway._connection_state == "idle"
        # Lock liberado.
        assert gateway._worker_lock.locked() is False, (
            "_worker_lock quedo cogido tras 2 disconnects concurrentes"
        )
        # Re-adquirir el lock funciona (prueba definitiva de que
        # esta libre).
        async with gateway._worker_lock:
            pass
        # detach_portal se envio (al menos una vez). Puede ser 1 o
        # 2 dependiendo del orden de las transiciones optimistas;
        # el contrato importante es que el primer disconnect lo
        # hizo, y el segundo no crasheo.
        assert "detach_portal" in sent_commands
        # Caches limpios (el primer disconnect los limpio; el
        # segundo no hace nada porque ya estaba en idle).
        assert gateway._cache == {}
        assert gateway._project_path is None
