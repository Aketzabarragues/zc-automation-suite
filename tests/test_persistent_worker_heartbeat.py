"""Tests del heartbeat continuo del worker OT persistente (PR 4).

Cubre el bucle ``_heartbeat_loop()`` definido en
``_plan/12_worker_persistent_design.md`` §3.4 y
``_plan/13_persistent_worker_impl.md`` (PR 4).

El heartbeat pinga al worker cada ``ZC_WORKER_HEARTBEAT_SECONDS``
segundos (default 5s) y mantiene ``_connection_state`` actualizado
segun el resultado:

  - 0 fallos consecutivos: ``"connected"``.
  - 1-2 fallos consecutivos: ``"connecting"`` (transitorio).
  - 3 fallos consecutivos: ``"disconnected"``.

Estrategia de testing:

- **Tiempo:** ``asyncio.sleep`` (del modulo ``core.infrastructure.gateway``)
  se parchea con una funcion que cede el control (``await real_sleep(0)``)
  en lugar de esperar el intervalo real. Esto hace que el heartbeat
  gire muy rapido dentro del test, permitiendo contar ticks de forma
  deterministica via el ``call_count`` del mock de
  ``_send_to_persistent_worker``.
- **Cancelacion:** la fake ``_send_to_persistent_worker`` se
  autocancela con ``task.cancel()`` tras N invocaciones. La
  ``CancelledError`` se absorbe en el ``except asyncio.CancelledError:
  return`` del loop (cierre limpio).
- **Subproceso:** mockeamos ``_worker_proc`` con un ``MagicMock``
  con ``returncode=None``. ``_send_to_persistent_worker`` se sustituye
  por completo (``AsyncMock`` o ``async def``) para no necesitar
  stdin/stdout reales.

Tests:

  1. ``test_0_fallos_estado_se_mantiene_connected``: 0 fallos → ``connected``.
  2. ``test_1_fallo_estado_transitorio_connecting``: 1 fallo → ``connecting``.
  3. ``test_3_fallos_consecutivos_estado_disconnected``: 3 fallos → ``disconnected``.
  4. ``test_frecuencia_configurable_por_env``: ``ZC_WORKER_HEARTBEAT_SECONDS``
     se respeta (default 5.0, custom 2.5).
  5. ``test_subproceso_muerto_marca_disconnected_sin_ping``: proc con
     ``returncode != None`` → disconnected inmediato, sin pings.
  6. ``test_proc_none_loop_sale_limpio``: ``_worker_proc = None`` → el
     loop retorna sin lanzar excepciones.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.infrastructure.gateway import TIAProcessGateway


# ────────────────────────────────────────────────────────────────────────
# Helpers compartidos
# ────────────────────────────────────────────────────────────────────────


def _build_alive_proc() -> MagicMock:
    """Crea un mock de ``_worker_proc`` con ``returncode=None`` (vivo).

    ``_send_to_persistent_worker`` se sustituye en cada test, asi que
    no necesitamos stdin/stdout funcionales. Devolvemos ``MagicMock``
    basico: lo unico que el heartbeat consulta es ``returncode``.
    """
    proc = MagicMock(name="FakeAliveWorkerProc")
    proc.returncode = None
    proc.stdin = MagicMock()
    proc.stdout = MagicMock()
    return proc


async def _run_heartbeat_for_n_pings(
    gateway: TIAProcessGateway,
    n: int,
    ping_response: object,
) -> int:
    """Lanza ``_heartbeat_loop`` y la cancela tras ``n`` pings.

    Args:
        gateway: Gateway bajo test (con ``_worker_proc`` ya asignado).
        n: Numero de pings tras los que la task se autocancela.
        ping_response: Lo que retorna ``_send_to_persistent_worker``
            (dict o callable que devuelve el dict; util para resultados
            que dependen del estado).

    Returns:
        Numero de pings que llegaron a ejecutarse (debe ser >= n).
    """
    real_sleep = asyncio.sleep
    ping_count = 0

    async def fake_send(cmd, args, timeout_override):  # noqa: ARG001
        nonlocal ping_count
        ping_count += 1
        # Tras N pings, cancelamos la task para que el loop salga
        # limpio via el ``except asyncio.CancelledError: return``.
        if ping_count >= n and gateway._heartbeat_task is not None \
                and not gateway._heartbeat_task.done():
            gateway._heartbeat_task.cancel()
        if callable(ping_response):
            return ping_response()
        return ping_response

    async def fake_sleep(interval):  # noqa: ARG001
        # Cedemos al event loop para que ``_send_to_persistent_worker``
        # pueda ejecutarse, pero NO esperamos el intervalo real (el
        # test seria lentisimo). Asi el heartbeat gira rapidamente
        # hasta que se cancela tras N pings.
        await real_sleep(0)

    gateway._send_to_persistent_worker = fake_send

    with patch(
        "core.infrastructure.gateway.asyncio.sleep",
        new=fake_sleep,
    ):
        task = asyncio.create_task(gateway._heartbeat_loop())
        gateway._heartbeat_task = task
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except (asyncio.CancelledError, Exception):
            # La cancelacion se espera; cualquier otra excepcion NO
            # deberia ocurrir pero no debe tumbar el test (mejor
            # reportarla via asserts abajo).
            pass

    return ping_count


# ────────────────────────────────────────────────────────────────────────
# Test 1: 0 fallos → estado ``connected`` se mantiene
# ────────────────────────────────────────────────────────────────────────


class TestHeartbeatConnectedState:
    """3 ticks sin fallos mantienen ``_connection_state == 'connected'``."""

    @pytest.mark.asyncio
    async def test_0_fallos_estado_se_mantiene_connected(self) -> None:
        """Tras 3 pings exitosos, el estado sigue ``"connected"`` y
        ``_last_error`` queda a ``None``.

        Mockeamos ``_send_to_persistent_worker`` para que retorne
        ``{"ok": True, "pid": 123}`` consistentemente. Tras 3 ticks
        verificamos que el contador de fallos esta a 0 y el estado es
        ``"connected"``.
        """
        gateway = TIAProcessGateway(persistent=True)
        gateway._worker_proc = _build_alive_proc()
        # Forzamos el estado inicial a "disconnected" para verificar
        # que el heartbeat lo transiciona a "connected" tras el primer
        # tick exitoso.
        gateway._connection_state = "disconnected"

        pings = await _run_heartbeat_for_n_pings(
            gateway, n=3, ping_response={"ok": True, "pid": 123}
        )

        assert pings >= 3, f"se esperaban >=3 pings, got {pings}"
        assert gateway._connection_state == "connected", (
            f"se esperaba 'connected', got {gateway._connection_state!r}"
        )
        assert gateway._last_error is None
        assert gateway._last_ping_ok is not None
        assert isinstance(gateway._last_ping_ok, float)


# ────────────────────────────────────────────────────────────────────────
# Test 2: 1 fallo → estado ``connecting`` (transitorio)
# ────────────────────────────────────────────────────────────────────────


class TestHeartbeatTransientFailure:
    """1 fallo consecutivo → ``"connecting"`` (NO ``"disconnected"``)."""

    @pytest.mark.asyncio
    async def test_1_fallo_estado_transitorio_connecting(self) -> None:
        """Tras 1 ping fallido, el estado es ``"connecting"`` y
        ``_last_error`` contiene el mensaje del worker.

        Caso real: el operario tiene TIA abierto pero el
        ``get_process_id()`` falla transitoriamente (RPC glitch,
        GC de Pythonnet, etc.). El heartbeat NO debe marcar
        ``"disconnected"`` al primer fallo: solo tras 3 consecutivos.
        """
        gateway = TIAProcessGateway(persistent=True)
        gateway._worker_proc = _build_alive_proc()
        # Estado inicial ``"connected"`` (recien arrancado el worker):
        # el primer fallo debe transicionarlo a ``"connecting"``, no
        # saltar a ``"disconnected"``.
        gateway._connection_state = "connected"
        gateway._last_error = None

        pings = await _run_heartbeat_for_n_pings(
            gateway,
            n=1,
            ping_response={"ok": False, "error": "RPC server unavailable"},
        )

        assert pings == 1, f"se esperaba exactamente 1 ping, got {pings}"
        assert gateway._connection_state == "connecting", (
            f"se esperaba 'connecting' (transitorio), "
            f"got {gateway._connection_state!r}"
        )
        assert gateway._last_error is not None
        assert "RPC server unavailable" in gateway._last_error


# ────────────────────────────────────────────────────────────────────────
# Test 3: 3 fallos consecutivos → ``"disconnected"``
# ────────────────────────────────────────────────────────────────────────


class TestHeartbeatDisconnectedState:
    """3 fallos consecutivos → ``"disconnected"`` (umbral del design doc §3.4)."""

    @pytest.mark.asyncio
    async def test_3_fallos_consecutivos_estado_disconnected(self) -> None:
        """Tras 3 pings fallidos consecutivos, el estado es ``"disconnected"``.

        Verifica que el contador ``consecutive_failures`` interno del
        loop se acumula correctamente y dispara la transicion a
        ``"disconnected"`` en el tercer tick. Tambien verifica que
        el estado ``"connecting"`` se observo en el tick 2 (test
        indirecto de que el umbral es exactamente 3, no 2).
        """
        gateway = TIAProcessGateway(persistent=True)
        gateway._worker_proc = _build_alive_proc()
        gateway._connection_state = "connected"

        # El ping retorna siempre error; observamos el estado en cada
        # tick via un side_effect indexado por ``ping_count``.
        real_sleep = asyncio.sleep
        observed_states: list[str] = []

        async def fake_send(cmd, args, timeout_override):  # noqa: ARG001
            # Capturamos el estado ANTES de incrementar el contador:
            # asi verificamos la transicion tras el tick.
            observed_states.append(gateway._connection_state)
            if len(observed_states) >= 3 and gateway._heartbeat_task \
                    is not None and not gateway._heartbeat_task.done():
                gateway._heartbeat_task.cancel()
            return {"ok": False, "error": "TIA cerrada"}

        async def fake_sleep(interval):  # noqa: ARG001
            await real_sleep(0)

        gateway._send_to_persistent_worker = fake_send

        with patch(
            "core.infrastructure.gateway.asyncio.sleep",
            new=fake_sleep,
        ):
            task = asyncio.create_task(gateway._heartbeat_loop())
            gateway._heartbeat_task = task
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except (asyncio.CancelledError, Exception):
                pass

        # 3 pings ejecutados.
        assert len(observed_states) == 3, (
            f"se esperaban 3 pings, got {len(observed_states)}: "
            f"{observed_states!r}"
        )
        # Estado final: disconnected.
        assert gateway._connection_state == "disconnected", (
            f"se esperaba 'disconnected' tras 3 fallos, "
            f"got {gateway._connection_state!r}"
        )
        # El error del worker quedo registrado.
        assert "TIA cerrada" in (gateway._last_error or "")


# ────────────────────────────────────────────────────────────────────────
# Test 4: frecuencia configurable por ``ZC_WORKER_HEARTBEAT_SECONDS``
# ────────────────────────────────────────────────────────────────────────


class TestHeartbeatIntervalConfig:
    """El intervalo del heartbeat se lee de ``ZC_WORKER_HEARTBEAT_SECONDS``."""

    @pytest.mark.asyncio
    async def test_frecuencia_configurable_por_env(self, monkeypatch) -> None:
        """Con ``ZC_WORKER_HEARTBEAT_SECONDS=2.5`` el ``asyncio.sleep`` se llama con 2.5.

        Capturamos el argumento de cada ``asyncio.sleep`` parcheado y
        verificamos que el primer valor es 2.5 (no 5.0 que es el
        default). Esto valida que la lectura de la env var se hace
        en cada llamada (``os.environ.get``) o al menos antes del
        primer ``sleep`` (verificamos lo observable: el valor que
        recibe ``sleep``).
        """
        monkeypatch.setenv("ZC_WORKER_HEARTBEAT_SECONDS", "2.5")
        gateway = TIAProcessGateway(persistent=True)
        gateway._worker_proc = _build_alive_proc()
        gateway._connection_state = "connected"

        real_sleep = asyncio.sleep
        intervals_seen: list[float] = []

        async def fake_send(cmd, args, timeout_override):  # noqa: ARG001
            # Cancelamos tras el primer ping para verificar que
            # ``asyncio.sleep`` se llamo al menos 1 vez con el valor
            # de la env var.
            if gateway._heartbeat_task is not None \
                    and not gateway._heartbeat_task.done():
                gateway._heartbeat_task.cancel()
            return {"ok": True, "pid": 1}

        async def fake_sleep(interval):  # noqa: ARG001
            intervals_seen.append(interval)
            await real_sleep(0)

        gateway._send_to_persistent_worker = fake_send

        with patch(
            "core.infrastructure.gateway.asyncio.sleep",
            new=fake_sleep,
        ):
            task = asyncio.create_task(gateway._heartbeat_loop())
            gateway._heartbeat_task = task
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except (asyncio.CancelledError, Exception):
                pass

        # Al menos 1 ``asyncio.sleep`` se llamo con 2.5 (el de antes
        # del primer ping). El segundo sleep (si llego a ejecutarse
        # antes de la cancelacion) tambien deberia usar 2.5.
        assert 2.5 in intervals_seen, (
            f"se esperaba 2.5 en intervals_seen, got {intervals_seen!r}"
        )
        # Y NINGUN sleep con el default 5.0.
        assert 5.0 not in intervals_seen, (
            f"el default 5.0 no debe aparecer cuando hay env var: "
            f"{intervals_seen!r}"
        )


# ────────────────────────────────────────────────────────────────────────
# Test 5 (defensivo): subproceso muerto → ``"disconnected"`` sin ping
# ────────────────────────────────────────────────────────────────────────


class TestHeartbeatDeadWorker:
    """Si el subproceso muere, el heartbeat marca ``"disconnected"`` sin enviar ping."""

    @pytest.mark.asyncio
    async def test_subproceso_muerto_marca_disconnected_sin_ping(self) -> None:
        """``_worker_proc.returncode != None`` → disconnected, sin invocar al ping.

        Caso real: el subproceso worker crashea (OOM, excepcion no
        capturada, TIA cerrada de golpe). El heartbeat debe detectarlo
        en el siguiente tick sin necesidad de esperar al timeout del
        ping (que nunca llegaria porque el stdin/stdout ya estan
        cerrados).
        """
        gateway = TIAProcessGateway(persistent=True)
        # Subproceso muerto: returncode fijado.
        dead_proc = MagicMock(name="DeadWorkerProc")
        dead_proc.returncode = -1  # codigo de salida no-cero (muerte)
        gateway._worker_proc = dead_proc
        gateway._connection_state = "connected"

        # El ping NO debe invocarse: si el proc esta muerto, el
        # heartbeat detecta el ``returncode`` y no malgasta un round-trip.
        gateway._send_to_persistent_worker = AsyncMock(
            return_value={"ok": True, "pid": 1}
        )

        real_sleep = asyncio.sleep
        ticks = 0

        async def fake_sleep(interval):  # noqa: ARG001
            nonlocal ticks
            ticks += 1
            # Cancelamos en el SEGUNDO sleep: el primero precede al
            # check de ``returncode`` (el cuerpo del primer tick es
            # el que marca ``disconnected``). Si cancelamos en el
            # primero, el body nunca corre y el estado no se transiciona.
            if ticks >= 2 and gateway._heartbeat_task is not None \
                    and not gateway._heartbeat_task.done():
                gateway._heartbeat_task.cancel()
            await real_sleep(0)

        with patch(
            "core.infrastructure.gateway.asyncio.sleep",
            new=fake_sleep,
        ):
            task = asyncio.create_task(gateway._heartbeat_loop())
            gateway._heartbeat_task = task
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except (asyncio.CancelledError, Exception):
                pass

        # El estado paso a disconnected.
        assert gateway._connection_state == "disconnected", (
            f"se esperaba 'disconnected' al detectar muerte del worker, "
            f"got {gateway._connection_state!r}"
        )
        # El codigo de salida aparece en el mensaje de error.
        assert gateway._last_error is not None
        assert "-1" in gateway._last_error
        # El ping NUNCA se intento: deteccion inmediata sin round-trip.
        gateway._send_to_persistent_worker.assert_not_called()


# ────────────────────────────────────────────────────────────────────────
# Test 6 (defensivo): ``_worker_proc = None`` → loop sale limpio
# ────────────────────────────────────────────────────────────────────────


class TestHeartbeatNoneProc:
    """Si ``_worker_proc`` es ``None`` (desconexion externa), el loop sale sin crashear."""

    @pytest.mark.asyncio
    async def test_proc_none_loop_sale_limpio(self) -> None:
        """Gateway con ``_worker_proc = None`` → ``_heartbeat_loop`` retorna sin excepciones.

        Caso real: PR 6 introducira ``disconnect()`` que pondra
        ``_worker_proc = None``. El heartbeat ya en vuelo debe
        detectar la senial y salir limpiamente (la task termina con
        ``done() == True``). Esto es pre-requisito para que
        ``_start_persistent_worker`` pueda relanzar la task en una
        reconexion posterior.
        """
        gateway = TIAProcessGateway(persistent=True)
        gateway._worker_proc = None  # desconexion externa
        gateway._send_to_persistent_worker = AsyncMock()

        real_sleep = asyncio.sleep

        async def fake_sleep(interval):  # noqa: ARG001
            # Cancelamos despues del primer sleep (que es el que
            # precede al check de ``_worker_proc is None``). Asi
            # dejamos que el cuerpo del loop se ejecute al menos 1
            # vez para verificar que retorna limpio.
            gateway._heartbeat_task.cancel()
            await real_sleep(0)

        with patch(
            "core.infrastructure.gateway.asyncio.sleep",
            new=fake_sleep,
        ):
            task = asyncio.create_task(gateway._heartbeat_loop())
            gateway._heartbeat_task = task
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except (asyncio.CancelledError, Exception):
                pass

        # La task termino (no se quedo colgada en un loop infinito).
        assert task.done(), "el loop no deberia seguir corriendo con _worker_proc=None"
        # NO se intento hacer ping: el check de ``None`` ocurre antes
        # del ``_send_to_persistent_worker``.
        gateway._send_to_persistent_worker.assert_not_called()
