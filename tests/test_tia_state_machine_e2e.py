"""Tests end-to-end del state machine ``idle``/``connecting``/``connected``/``error``.

Cubre el ciclo completo del state machine del worker OT persistente
refactorizado en sept-2026 (post-auditoria). Ver
``_plan/14_post_worker_persistent_audit.md`` (seccion "Refactor
state machine").

El state machine:

  idle  --(gateway.connect() / worker.attach_portal)--> connecting
  connecting  --(worker responde ok)--> connected
  connecting  --(worker responde error)--> error
  connected  --(gateway.disconnect() / worker.detach_portal)--> idle
  connected  --(3 heartbeats fallidos)--> disconnected (TODO: PR futuro)

Este test NO lanza un subproceso real (requeriria TIA Portal
abierto). Mockeamos ``_send_to_persistent_worker`` para simular
las respuestas del worker, y verificamos las transiciones de
estado en el gateway.

Estrategia de testing:

  - **Mocking ligero**: ``_send_to_persistent_worker`` y
    ``_start_persistent_worker`` se sustituyen por ``AsyncMock``
    para no levantar subproceso real. Asi podemos verificar el
    state machine en aislamiento.
  - **Cache limpia**: ``_cache`` y ``_bloques_cache`` parten
    vacios; los tests pueblan datos stale para verificar la
    limpieza en ``disconnect()``.

Tests:

  1. ``test_ciclo_idle_connected_idle_completo``.
  2. ``test_state_machine_idle_a_connected_a_idle`` (alias del 1).
  3. ``test_heartbeat_no_se_inicia_en_idle``.
  4. ``test_dispatch_rechaza_comandos_cuando_state_no_es_connected``.
  5. ``test_connect_es_idempotente``.
  6. ``test_disconnect_limpia_caches_y_resetea_project_path``.
  7. ``test_reconnect_es_disconnect_mas_connect``.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.infrastructure.gateway import TIAConnectionError, TIAProcessGateway


def _build_alive_proc() -> MagicMock:
    """Crea un mock de ``_worker_proc`` con ``returncode=None`` (vivo)."""
    proc = MagicMock(name="FakeAliveWorkerProc")
    proc.returncode = None
    proc.stdin = MagicMock()
    proc.stdout = MagicMock()
    return proc


@pytest.mark.asyncio
async def test_ciclo_idle_connected_idle_completo() -> None:
    """Ciclo completo: ``start()`` -> ``idle`` -> ``connect()`` -> ``connected`` -> ``disconnect()`` -> ``idle``.

    Test de integracion del state machine (sept-2026, post-auditoria):

      1. ``start()`` lanza el worker y espera al ready_idle; el estado
         queda en ``"idle"`` (subproceso vivo, sin portal).
      2. ``connect()`` envia ``attach_portal``; el worker responde
         con ``{"pid": ...}``; el estado transiciona a
         ``"connected"`` y el heartbeat arranca.
      3. Un comando cualquiera (e.g. ``list_plcs``) ahora funciona
         porque el estado es ``"connected"``.
      4. ``disconnect()`` envia ``detach_portal``; el worker responde
         con ``{"detached": True}``; el estado transiciona a
         ``"idle"`` y las caches se limpian.
      5. Un comando cualquiera (e.g. ``list_plcs``) vuelve a fallar
         porque el estado es ``"idle"``.
    """
    gateway = TIAProcessGateway(persistent=True)
    # Subproceso ya vivo (start mockeado).
    gateway._worker_proc = _build_alive_proc()
    reader = MagicMock(name="Reader")
    reader.done.return_value = False
    gateway._reader_task = reader

    # 1. Estado inicial: idle (gateway se construyo con persistent=True).
    assert gateway._connection_state == "idle"

    # 2. connect() → attached.
    async def fake_send_attach(command, args, timeout_override):  # noqa: ARG001
        if command == "attach_portal":
            return {"pid": 12345}
        if command == "detach_portal":
            return {"detached": True}
        return {}
    gateway._send_to_persistent_worker = fake_send_attach
    gateway._detect_project_change = AsyncMock(return_value=False)

    await gateway.connect()
    assert gateway._connection_state == "connected"
    assert gateway._heartbeat_task is not None
    # Project detection se llamo al conectar.
    gateway._detect_project_change.assert_awaited_once()

    # 3. Comando del registry funciona en connected.
    gateway._send_to_persistent_worker = AsyncMock(
        return_value=["PLC1", "PLC2"]
    )
    result = await gateway._dispatch_worker("list_plcs")
    assert result == ["PLC1", "PLC2"]

    # 4. disconnect() → idle.
    gateway._cache = {"plcs": ["PLC1"]}  # cache con datos stale
    gateway._project_path = r"C:\ws\proyectoA\proyectoA.ap17"
    gateway._project_changed = True
    gateway._send_to_persistent_worker = AsyncMock(
        return_value={"detached": True}
    )
    await gateway.disconnect()
    assert gateway._connection_state == "idle"
    assert gateway._cache == {}  # cache limpia
    assert gateway._project_path is None
    assert gateway._project_changed is False
    assert gateway._heartbeat_task is None

    # 5. Comando del registry falla en idle.
    with pytest.raises(TIAConnectionError, match="Conectar primero"):
        await gateway._dispatch_worker("list_plcs")


@pytest.mark.asyncio
async def test_state_machine_idle_a_connected_a_idle() -> None:
    """Test reducido del state machine: verifica solo las transiciones de estado.

    Variante minima del test anterior que se enfoca en el contrato
    del state machine (sin aserciones de caches o heartbeat).
    """
    gateway = TIAProcessGateway(persistent=True)
    gateway._worker_proc = _build_alive_proc()
    reader = MagicMock(name="Reader")
    reader.done.return_value = False
    gateway._reader_task = reader

    async def fake_send(command, args, timeout_override):  # noqa: ARG001
        if command == "attach_portal":
            return {"pid": 99}
        if command == "detach_portal":
            return {"detached": True}
        return {}
    gateway._send_to_persistent_worker = fake_send
    gateway._detect_project_change = AsyncMock(return_value=False)

    # idle → connecting → connected
    assert gateway._connection_state == "idle"
    await gateway.connect()
    assert gateway._connection_state == "connected"

    # connected → disconnected (transitorio) → idle
    await gateway.disconnect()
    assert gateway._connection_state == "idle"


@pytest.mark.asyncio
async def test_dispatch_rechaza_comandos_cuando_state_no_es_connected() -> None:
    """Comandos del registry requieren ``state="connected"``.

    Verifica que la validacion de estado en ``_dispatch_worker``
    (sept-2026) rechaza comandos con ``TIAConnectionError`` claro
    cuando el estado no es connected.
    """
    for state in ("idle", "connecting", "error", "disconnected"):
        gateway = TIAProcessGateway(persistent=True)
        gateway._connection_state = state
        gateway._send_to_persistent_worker = AsyncMock(
            return_value={"ok": True, "result": "should_not_run"}
        )
        with pytest.raises(TIAConnectionError, match="Conectar primero"):
            await gateway._dispatch_worker("list_plcs")


@pytest.mark.asyncio
async def test_connect_es_idempotente() -> None:
    """Doble ``connect()`` no re-attachea; el segundo es no-op o lanza error claro."""
    gateway = TIAProcessGateway(persistent=True)
    gateway._worker_proc = _build_alive_proc()
    reader = MagicMock(name="Reader")
    reader.done.return_value = False
    gateway._reader_task = reader

    sent_commands: list[str] = []

    async def fake_send(command, args, timeout_override):  # noqa: ARG001
        sent_commands.append(command)
        if command == "attach_portal":
            return {"pid": 1}
        return {}
    gateway._send_to_persistent_worker = fake_send
    gateway._detect_project_change = AsyncMock(return_value=False)

    # Primer connect: OK.
    await gateway.connect()
    assert "attach_portal" in sent_commands

    # Segundo connect: rechaza con error claro (ya esta conectado).
    with pytest.raises(TIAConnectionError):
        await gateway.connect()


@pytest.mark.asyncio
async def test_disconnect_limpia_caches_y_resetea_project_path() -> None:
    """``disconnect()`` limpia ``_cache``, ``_bloques_cache`` y ``_project_path``."""
    gateway = TIAProcessGateway(persistent=True)
    gateway._worker_proc = _build_alive_proc()
    reader = MagicMock(name="Reader")
    reader.done.return_value = False
    gateway._reader_task = reader
    # Caches con datos stale.
    gateway._cache = {"plcs": ["PLC1"], "project_info": {"name": "X"}}
    gateway._bloques_cache = {"PLC1.blocks": MagicMock(name="BloqueCache")}
    gateway._project_path = r"C:\ws\proyectoA\proyectoA.ap17"
    gateway._project_changed = True
    gateway._send_to_persistent_worker = AsyncMock(
        return_value={"detached": True}
    )

    await gateway.disconnect()

    assert gateway._cache == {}
    assert gateway._bloques_cache == {}
    assert gateway._project_path is None
    assert gateway._project_changed is False


@pytest.mark.asyncio
async def test_reconnect_es_disconnect_mas_connect() -> None:
    """``reconnect()`` es la composicion: ``disconnect()`` + ``connect()`` bajo el mismo lock.

    Verifica que tras ``reconnect()``, el estado final es
    ``"connected"`` y las caches fueron limpiadas en la fase de
    disconnect.
    """
    gateway = TIAProcessGateway(persistent=True)
    gateway._connection_state = "connected"  # veniamos de un connect previo
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
        if command == "attach_portal":
            return {"pid": 999}
        if command == "detach_portal":
            return {"detached": True}
        return {}
    gateway._send_to_persistent_worker = fake_send
    gateway._detect_project_change = AsyncMock(return_value=False)

    await gateway.reconnect()

    # Orden correcto: detach primero, luego attach.
    assert sent_commands == ["detach_portal", "attach_portal"]
    # Estado final: connected.
    assert gateway._connection_state == "connected"
    # Caches limpiadas.
    assert gateway._cache == {}
    assert gateway._project_path is None
    # Heartbeat reiniciado.
    assert gateway._heartbeat_task is not None


@pytest.mark.asyncio
async def test_disconnect_bajo_lock_contention_actualiza_estado_optimistamente() -> None:
    """Sept-2026 round 3 (fix de auditoría profunda del worker).

    Caso real (logs/zc_tray.log 12:11:41/12:11:44): el
    ``_worker_lock`` se retentiene por un comando en vuelo
    (``get_plcs``/``get_project_info`` con
    ``ZC_GATEWAY_TIMEOUT=300s``, o un ``compile_plc`` largo).
    ``disconnect()`` se queda bloqueado en el
    ``async with self._worker_lock`` durante segundos. Mientras
    tanto, el frontend ve ``state="connected"`` y el operario
    pulsa "Desconectar" de nuevo, generando un segundo disconnect
    que también ve ``state="connected"``.

    El fix: la transición a ``"idle"`` ocurre ANTES del lock
    (transición optimista), de forma que el siguiente
    ``GET /tia/connection`` la vea inmediatamente. El cleanup
    (heartbeat cancel, detach_portal, cache clear) sigue dentro
    del lock, pero el operario ya tiene feedback correcto.

    Este test simula el escenario: un holder retiene el lock
    durante 0.5s mientras se llama a ``disconnect()``. Verifica
    que el state pasa a ``"idle"`` INMEDIATAMENTE (antes de
    que el lock se libere).
    """
    gateway = TIAProcessGateway(persistent=True)
    gateway._connection_state = "connected"
    gateway._worker_proc = _build_alive_proc()
    reader = MagicMock(name="Reader")
    reader.done.return_value = False
    gateway._reader_task = reader
    # _send_to_persistent_worker con respuesta que tarda 0.5s
    # (simula un detach lento por red/IO).
    async def slow_detach(command, args, timeout_override):  # noqa: ARG001
        await asyncio.sleep(0.5)
        if command == "detach_portal":
            return {"detached": True}
        return {}
    gateway._send_to_persistent_worker = slow_detach
    # Heartbeat task "vivo" para que disconnect() intente cancelarlo.
    async def heartbeat_forever():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            return
    gateway._heartbeat_task = asyncio.create_task(heartbeat_forever())

    # 1. Adquirimos el lock manualmente (simula un comando en vuelo
    #    que retiene el lock durante 0.3s).
    await gateway._worker_lock.acquire()
    try:
        # 2. Llamamos a disconnect() en una task. No debe completar
        #    inmediatamente porque el lock está retentenido.
        disconnect_task = asyncio.create_task(gateway.disconnect())
        # 3. Damos tiempo a que la corrutina schedule y ejecute la
        #    transición optimista (que es síncrona, antes del lock).
        await asyncio.sleep(0.05)
        # 4. Verificamos: aunque el lock está retentenido, el estado
        #    YA pasó a "idle" (transición optimista). Esto es lo que
        #    el operario ve en el polling de /tia/connection.
        assert gateway._connection_state == "idle", (
            f"estado deberia ser 'idle' (transicion optimista); "
            f"got {gateway._connection_state!r}. Bug del audit "
            f"2026-09-06 (logs/zc_tray.log 12:11:41) NO esta fixeado."
        )
        assert gateway._last_portal_pid is None
        assert gateway._project_path is None
    finally:
        # 5. Liberamos el lock; el disconnect puede completar.
        gateway._worker_lock.release()
    # 6. Esperamos al disconnect completo.
    await asyncio.wait_for(disconnect_task, timeout=2.0)
    # 7. El estado sigue siendo "idle" (no se revertió).
    assert gateway._connection_state == "idle"
    # 8. El cache se limpió (cleanup dentro del lock).
    assert gateway._cache == {}
    # 9. El heartbeat task fue cancelado.
    assert gateway._heartbeat_task is None or gateway._heartbeat_task.done()
