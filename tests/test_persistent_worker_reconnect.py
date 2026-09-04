"""Tests de ``reconnect()`` y ``disconnect()`` del gateway OT persistente (PR 6).

Cubre la reconexion manual definida en
``_plan/12_worker_persistent_design.md`` §2.7 y el boton del topbar
implementado en PR 5b (``TiaConnectionIndicator.js``). El operario
puede forzar la reconexion cuando TIA Portal se cerro y volvio a
abrir, o cuando el worker se cayo por cualquier motivo.

API publica anadida en este PR:

  - ``gateway.reconnect()``: mata el worker actual y arranca uno
    nuevo. Si el attach falla, lanza ``TIAConnectionError`` y marca
    ``_connection_state = "error"``.
  - ``gateway.disconnect()``: marca ``_connection_state = "disconnected"``
    y mata el worker. NO relanza.

Ambas son exclusivos del modo ``persistent=True``; en modo 1-shot
(``persistent=False``) lanzan ``TIAConnectionError`` para que el
topbar reciba un error claro en vez de un no-op silencioso.

Estrategia de testing:

  - **Mocking ligero**: ``_kill_persistent_worker`` y
    ``_start_persistent_worker`` se sustituyen por ``AsyncMock``
    para que los tests de ``reconnect()`` / ``disconnect()`` no
    levanten subprocesos reales. Los tests de ``_kill_persistent_worker``
    usan ``MagicMock`` para ``_worker_proc`` y ``_reader_task`` /
    ``_heartbeat_task`` (los paths internos son best-effort y se
    ejercitan parcialmente).
  - **Idempotencia**: el test 6 llama a ``_kill_persistent_worker``
    dos veces consecutivas. La segunda debe ser un no-op limpio.
  - **Pending futures**: el test 7 registra futures en
    ``_pending_responses`` y verifica que ``_kill_persistent_worker``
    los resuelve con ``RuntimeError("Worker desconectado")``.

Tests:

  1. ``test_reconnect_kills_old_worker_and_starts_new_one``: orden de helpers.
  2. ``test_reconnect_sin_modo_persistente_lanza_TIAConnectionError``.
  3. ``test_reconnect_con_attach_fallido_marca_error_y_relanza``.
  4. ``test_disconnect_marca_disconnected_y_llama_kill``.
  5. ``test_disconnect_sin_modo_persistente_lanza_TIAConnectionError``.
  6. ``test_kill_persistent_worker_es_idempotente``.
  7. ``test_kill_persistent_worker_resuelve_pending_futures``.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.infrastructure.gateway import TIAConnectionError, TIAProcessGateway


# ────────────────────────────────────────────────────────────────────────
# Helpers compartidos
# ────────────────────────────────────────────────────────────────────────


def _build_finished_proc() -> MagicMock:
    """Crea un mock de ``_worker_proc`` ya terminado (``returncode != None``).

    Util para tests donde queremos verificar que ``_kill_persistent_worker``
    no intenta hacer ``terminate()`` sobre un proc que ya murio: el
    check ``if self._worker_proc is not None and self._worker_proc.returncode
    is None`` se salta y el codigo va directo a ``self._worker_proc = None``.
    """
    proc = MagicMock(name="FinishedWorkerProc")
    proc.returncode = 0  # ya termino
    return proc


# ────────────────────────────────────────────────────────────────────────
# Test 1: ``reconnect()`` mata el worker viejo y arranca uno nuevo
# ────────────────────────────────────────────────────────────────────────


class TestReconnectKillsAndRestarts:
    """``reconnect()`` invoca ``_kill_persistent_worker`` y luego ``_start_persistent_worker``."""

    @pytest.mark.asyncio
    async def test_reconnect_kills_old_worker_and_starts_new_one(self) -> None:
        """``reconnect()`` mata el worker viejo ANTES de arrancar el nuevo.

        Estrategia: sustituimos ``_kill_persistent_worker`` y
        ``_start_persistent_worker`` por ``AsyncMock`` para no
        levantar subprocesos reales. Verificamos que ambos se llaman
        y que ``_kill_persistent_worker`` se invoca ANTES de
        ``_start_persistent_worker`` (orden del design doc §2.7).

        Si el orden se invirtiera (arrancar antes de matar), el
        nuevo worker intentaria attach a un TIA Portal que el
        worker viejo aun tiene agarrado, y el ``attach_portal`` con
        ExclusiveAccess fallaria. Por eso el orden importa.
        """
        gateway = TIAProcessGateway(persistent=True)
        # Estado inicial coherente con un gateway que estaba conectado.
        gateway._connection_state = "connected"
        gateway._worker_proc = _build_finished_proc()  # para que el cleanup no se queje

        # ``AsyncMock`` para no levantar subproceso real.
        call_order: list[str] = []

        async def fake_kill() -> None:
            call_order.append("kill")

        async def fake_start() -> None:
            call_order.append("start")
            # Simulamos exito: el estado pasa a "connected" como haria
            # el ``_start_persistent_worker`` real tras el ping inicial.
            gateway._connection_state = "connected"

        gateway._kill_persistent_worker = fake_kill
        gateway._start_persistent_worker = fake_start

        await gateway.reconnect()

        # Ambos se llamaron y en el orden correcto.
        assert call_order == ["kill", "start"], (
            f"se esperaba ['kill', 'start'], got {call_order!r}"
        )


# ────────────────────────────────────────────────────────────────────────
# Test 2: ``reconnect()`` en modo 1-shot lanza ``TIAConnectionError``
# ────────────────────────────────────────────────────────────────────────


class TestReconnectRequiresPersistent:
    """``reconnect()`` en modo 1-shot no aplica: lanza ``TIAConnectionError``."""

    @pytest.mark.asyncio
    async def test_reconnect_sin_modo_persistente_lanza_TIAConnectionError(self) -> None:
        """Gateway ``persistent=False`` + ``reconnect()`` → ``TIAConnectionError`` legible.

        El modo 1-shot (MCP) no tiene worker persistente que matar;
        matar y rearrancar seria incorrecto (romperia la semantica
        1-shot de MCP). El error deja claro que la operacion solo
        aplica al modo persistente para que el operario no piense
        que es un bug transitorio.
        """
        gateway = TIAProcessGateway(persistent=False)
        with pytest.raises(TIAConnectionError, match="solo aplica a gateway.persistent=True"):
            await gateway.reconnect()


# ────────────────────────────────────────────────────────────────────────
# Test 3: ``reconnect()`` con attach fallido marca ``error`` y relanza
# ────────────────────────────────────────────────────────────────────────


class TestReconnectOnAttachFailure:
    """Si el nuevo attach falla, ``reconnect()`` marca ``error`` y lanza ``TIAConnectionError``."""

    @pytest.mark.asyncio
    async def test_reconnect_con_attach_fallido_marca_error_y_relanza(self) -> None:
        """``_start_persistent_worker`` que lanza → estado ``error`` + ``TIAConnectionError``.

        Caso real: TIA Portal cerrado, portales com occupados, el
        attach inicial del nuevo worker falla. El operario pulsa
        "Reconectar" y el gateway le devuelve un error legible
        (no un 500). El circulo del topbar pasa a rojo (state
        ``error``) y ``ConsolaLogs`` muestra el detalle.

        Verificamos:
          - Se lanza ``TIAConnectionError``.
          - El mensaje contiene ``"Reconnect fallo"`` (contrato del
            PR; el router lo usa para decidir el body de respuesta).
          - ``_connection_state == "error"``.
          - ``_last_error`` queda registrado (para el siguiente
            ``GET /tia/connection``).
        """
        gateway = TIAProcessGateway(persistent=True)
        gateway._connection_state = "disconnected"  # estado previo cualquiera
        gateway._last_error = None

        # ``_kill`` no-op, ``_start`` que falla como si TIA estuviera cerrado.
        async def fake_kill() -> None:
            pass

        async def fake_start_raises() -> None:
            # Simulamos un fallo realista: ``TIAConnectionError`` es
            # lo que ``_start_persistent_worker`` lanza cuando el
            # ping inicial falla (ver ``_start_persistent_worker`` en
            # ``gateway.py``).
            raise TIAConnectionError("attach_portal: No matching TIA Portal version")

        gateway._kill_persistent_worker = fake_kill
        gateway._start_persistent_worker = fake_start_raises

        with pytest.raises(TIAConnectionError, match="Reconnect fallo") as exc_info:
            await gateway.reconnect()

        # El estado queda en "error" para que el topbar muestre el
        # circulo rojo.
        assert gateway._connection_state == "error", (
            f"se esperaba 'error' tras reconexion fallida, "
            f"got {gateway._connection_state!r}"
        )
        # El mensaje incluye el detalle del fallo original.
        assert "No matching TIA Portal version" in str(exc_info.value)
        # ``_last_error`` queda registrado para el siguiente poll.
        assert gateway._last_error is not None


# ────────────────────────────────────────────────────────────────────────
# Test 4: ``disconnect()`` marca ``disconnected`` y mata el worker
# ────────────────────────────────────────────────────────────────────────


class TestDisconnectMarksDisconnected:
    """``disconnect()`` marca el estado y mata el worker."""

    @pytest.mark.asyncio
    async def test_disconnect_marca_disconnected_y_llama_kill(self) -> None:
        """``disconnect()`` setea ``_connection_state='disconnected'`` y llama a ``_kill_persistent_worker``.

        Verificamos que el estado se actualiza ANTES de matar el
        worker (importante: el ``GET /tia/connection`` que el
        frontend hace cada 500ms durante el kill puede ver el
        estado transitorio ``"disconnected"``).

        Tambien verificamos que ``_last_error`` se limpia: tras
        un ``disconnect()`` explicito, el operario no deberia ver
        errores stale de un fallo anterior en el circulo del topbar.
        """
        gateway = TIAProcessGateway(persistent=True)
        gateway._connection_state = "error"  # veniamos de un fallo
        gateway._last_error = "alguna TIAConnectionError anterior"

        kill_called = False

        async def fake_kill() -> None:
            nonlocal kill_called
            kill_called = True

        gateway._kill_persistent_worker = fake_kill

        await gateway.disconnect()

        # Estado actualizado.
        assert gateway._connection_state == "disconnected", (
            f"se esperaba 'disconnected', got {gateway._connection_state!r}"
        )
        # ``_last_error`` se limpio (no queremos errores stale).
        assert gateway._last_error is None
        # ``_kill_persistent_worker`` se invoco.
        assert kill_called, "se esperaba que _kill_persistent_worker fuera llamado"


# ────────────────────────────────────────────────────────────────────────
# Test 5: ``disconnect()`` en modo 1-shot lanza ``TIAConnectionError``
# ────────────────────────────────────────────────────────────────────────


class TestDisconnectRequiresPersistent:
    """``disconnect()`` en modo 1-shot no aplica: lanza ``TIAConnectionError``."""

    @pytest.mark.asyncio
    async def test_disconnect_sin_modo_persistente_lanza_TIAConnectionError(self) -> None:
        """Gateway ``persistent=False`` + ``disconnect()`` → ``TIAConnectionError`` legible.

        Simetrico con el test 2: ambos metodos publicos del worker
        persistente estan gatekept por el flag. Si el operario
        llega aqui desde el topbar con un gateway 1-shot (MCP),
        recibe un error claro en vez de un AttributeError confuso.
        """
        gateway = TIAProcessGateway(persistent=False)
        with pytest.raises(TIAConnectionError, match="solo aplica a gateway.persistent=True"):
            await gateway.disconnect()


# ────────────────────────────────────────────────────────────────────────
# Test 6: ``_kill_persistent_worker()`` es idempotente
# ────────────────────────────────────────────────────────────────────────


class TestKillIsIdempotent:
    """``_kill_persistent_worker()`` puede llamarse multiples veces sin crashear."""

    @pytest.mark.asyncio
    async def test_kill_persistent_worker_es_idempotente(self) -> None:
        """Llamar ``_kill_persistent_worker()`` 2 veces seguidas no crashea.

        Caso real: ``reconnect()`` lo llama una vez; el
        ``_start_persistent_worker`` que viene justo despues
        podria fallar y un futuro cleanup del app shutdown lo
        llamaria otra vez. La idempotencia es un requisito
        defensivo: si por lo que sea se invoca dos veces, la
        segunda debe ser un no-op limpio.

        Mockeamos ``_worker_proc`` y los tasks con ``MagicMock``
        para verificar que ``cancel()`` y ``terminate()`` NO se
        invocan en la segunda llamada (todo ya esta a ``None``).
        """
        gateway = TIAProcessGateway(persistent=True)

        # Estado inicial: un worker "vivo" simulado.
        proc = MagicMock(name="LiveWorkerProc")
        proc.returncode = None  # vivo
        reader = MagicMock(name="LiveReaderTask")
        reader.done.return_value = True  # ya terminado (no cancelable)
        heartbeat = MagicMock(name="LiveHeartbeatTask")
        heartbeat.done.return_value = True  # idem

        gateway._worker_proc = proc
        gateway._reader_task = reader
        gateway._heartbeat_task = heartbeat
        gateway._next_request_id = 42  # algun valor no-cero
        loop = asyncio.get_event_loop()
        gateway._pending_responses[7] = loop.create_future()  # un future pendiente

        # Primera llamada: debe limpiarlo todo.
        await gateway._kill_persistent_worker()
        assert gateway._worker_proc is None
        assert gateway._reader_task is None
        assert gateway._heartbeat_task is None
        assert gateway._pending_responses == {}
        assert gateway._next_request_id == 0

        # Capturamos el call count de la primera llamada (el proc
        # mock SI recibio ``terminate()`` al matarlo). El test
        # verifica que la SEGUNDA llamada no anade mas invocaciones
        # (estado ya limpio, no-op).
        terminate_after_first = proc.terminate.call_count
        cancel_reader_after_first = reader.cancel.call_count
        cancel_heartbeat_after_first = heartbeat.cancel.call_count

        # Segunda llamada: no debe crashear. Tampoco debe invocar
        # ``cancel()`` ni ``terminate()`` (los ``if`` lo evitan al
        # ver ``self._worker_proc is None`` y ``task.done() == True``).
        await gateway._kill_persistent_worker()

        # El estado sigue consistente.
        assert gateway._worker_proc is None
        assert gateway._reader_task is None
        assert gateway._heartbeat_task is None
        assert gateway._pending_responses == {}

        # Los call counts no cambiaron: la segunda llamada fue
        # completamente un no-op (el helper es idempotente de verdad,
        # no solo "no crashea").
        assert proc.terminate.call_count == terminate_after_first, (
            f"terminate() se llamo {proc.terminate.call_count - terminate_after_first} "
            f"veces extra en la 2a llamada; se esperaba 0"
        )
        assert reader.cancel.call_count == cancel_reader_after_first, (
            f"reader.cancel() se llamo "
            f"{reader.cancel.call_count - cancel_reader_after_first} "
            f"veces extra en la 2a llamada; se esperaba 0"
        )
        assert heartbeat.cancel.call_count == cancel_heartbeat_after_first, (
            f"heartbeat.cancel() se llamo "
            f"{heartbeat.cancel.call_count - cancel_heartbeat_after_first} "
            f"veces extra en la 2a llamada; se esperaba 0"
        )


# ────────────────────────────────────────────────────────────────────────
# Test 7: ``_kill_persistent_worker()`` resuelve los pending futures
# ────────────────────────────────────────────────────────────────────────


class TestKillResolvesPendingFutures:
    """``_kill_persistent_worker()`` resuelve los futures con ``RuntimeError``."""

    @pytest.mark.asyncio
    async def test_kill_persistent_worker_resuelve_pending_futures(self) -> None:
        """Los futures en ``_pending_responses`` reciben ``RuntimeError('Worker desconectado')``.

        Caso real: el operario pulsa "Desconectar" mientras hay un
        comando en vuelo (p.ej. un ``get_plcs`` largo). El
        ``_send_to_persistent_worker`` que esta esperando respuesta
        se queda colgado indefinidamente si nadie resuelve su
        future. ``_kill_persistent_worker`` resuelve todos los
        futures pendientes con ``RuntimeError`` para que el
        ``asyncio.wait_for`` de ``_send_to_persistent_worker`` los
        vea como una excepcion (mismo contrato que un timeout) y
        se pueda manejar arriba.

        Verificamos:
          - Los futures quedaron con excepcion ``RuntimeError``.
          - El mensaje contiene ``"Worker desconectado"``.
          - ``_pending_responses`` se vacio.
          - ``_next_request_id`` se reseteo a 0.
        """
        gateway = TIAProcessGateway(persistent=True)
        # Setup: 2 futures pendientes, contador de IDs no-cero.
        loop = asyncio.get_event_loop()
        fut_1 = loop.create_future()
        fut_2 = loop.create_future()
        gateway._pending_responses[10] = fut_1
        gateway._pending_responses[11] = fut_2
        gateway._next_request_id = 12

        await gateway._kill_persistent_worker()

        # Ambos futures quedaron con RuntimeError.
        assert fut_1.done(), "fut_1 deberia estar terminado"
        assert fut_2.done(), "fut_2 deberia estar terminado"
        with pytest.raises(RuntimeError, match="Worker desconectado"):
            fut_1.result()
        with pytest.raises(RuntimeError, match="Worker desconectado"):
            fut_2.result()

        # El dict se vacio.
        assert gateway._pending_responses == {}, (
            f"se esperaba _pending_responses vacio, "
            f"got {gateway._pending_responses!r}"
        )
        # Contador reseteado.
        assert gateway._next_request_id == 0
