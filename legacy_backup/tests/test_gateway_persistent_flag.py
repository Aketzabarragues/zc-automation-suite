"""Tests del flag ``persistent`` en ``TIAProcessGateway`` (PR 2).

Cubre el esqueleto del worker OT persistente introducido en
PR 2 del refactor (``_plan/13_persistent_worker_impl.md``,
sección "PR 2"):

- **Constructor**: ``persistent: bool = False`` es el default. Si se
  pasa ``persistent=True``, se inicializan los campos de estado del
  worker persistente (``_worker_proc``, ``_worker_lock``,
  ``_next_request_id``, ``_pending_responses``, ``_reader_task``,
  ``_heartbeat_task``, ``_connection_state``, ``_project_path``,
  ``_last_ping_ok``, ``_last_error``). Si es ``False`` (default),
  esos atributos NO existen en la instancia (cero overhead para el
  modo 1-shot histórico).

- **Dispatcher**: ``_dispatch_worker`` se convierte en un switch
  genérico que delega según el flag. En este PR el caso persistente
  lanza ``NotImplementedError`` con la referencia a "PR 3"; el 1-shot
  mantiene su comportamiento intacto (delegación a
  ``_dispatch_ephemeral_worker``).

- **Helpers de wiring**: ``_resolve_persistent_worker_exec_args()``
  retorna los args para lanzar el subproceso del worker en modo
  persistente (``["--worker-persistent"]``). ``_start_persistent_worker()``
  es un placeholder que también lanza ``NotImplementedError``.

Estrategia de testing:

- Para el default (``persistent=False``) y la inicialización del estado
  (``persistent=True``): tests síncronos que solo construyen el
  gateway e inspeccionan atributos. Sin mocks.

- Para ``_dispatch_worker`` en modo persistente: ``pytest.raises``
  sobre ``NotImplementedError`` con ``match="PR 3"`` (verifica que
  el mensaje apunta al PR correcto, no a un fallo genérico).

- Para ``_dispatch_worker`` en modo 1-shot: mockeamos
  ``_dispatch_ephemeral_worker`` (vía ``AsyncMock``) y verificamos
  que el dispatcher delega y propaga el resultado. NO lanzamos
  subproceso real (sería lento y frágil, y este PR no quiere probar
  el comportamiento 1-shot — eso ya está cubierto por
  ``test_timing_metrics.py`` y ``test_gateway_connection_error.py``).

- Para ``_start_persistent_worker``: ``pytest.raises`` con
  ``match="PR 3"``.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from core.infrastructure.gateway import TIAProcessGateway


# ─────────────────────────────────────────────────────────────────────
# Tests del constructor y la propiedad ``persistent``.
# ─────────────────────────────────────────────────────────────────────


def test_default_persistent_is_false() -> None:
    """``TIAProcessGateway()`` sin args tiene ``persistent=False``.

    Back-compat: cualquier caller existente que construya el gateway
    sin el nuevo kwarg sigue funcionando idéntico (1-shot).
    """
    gateway = TIAProcessGateway()
    assert gateway.persistent is False
    # El atributo privado existe en ambos modos (necesario para el switch).
    assert gateway._persistent is False


def test_persistent_true_initializes_state_fields() -> None:
    """``TIAProcessGateway(persistent=True)`` inicializa el estado del worker persistente.

    Verifica los 10 campos documentados en §3.1 del design doc:
    - ``_worker_proc``: None (aún no hay subproceso).
    - ``_worker_lock``: ``asyncio.Lock`` (para serializar requests).
    - ``_next_request_id``: 0 (contador inicial).
    - ``_pending_responses``: ``{}`` (sin futures pendientes).
    - ``_reader_task``: None (el task se crea en PR 3).
    - ``_heartbeat_task``: None (el task se crea en PR 4).
    - ``_connection_state``: ``"idle"`` (estado inicial sept-2026,
      subproceso logico todavia no arrancado, pero wrapper pronto;
      ``"disconnected"`` queda reservado para proc muerto).
    - ``_project_path``: None (para detectar cambios en PR 7).
    - ``_last_ping_ok``: None (último ping exitoso).
    - ``_last_error``: None (último error).
    """
    gateway = TIAProcessGateway(persistent=True)
    assert gateway.persistent is True
    assert gateway._worker_proc is None
    assert isinstance(gateway._worker_lock, asyncio.Lock)
    assert gateway._next_request_id == 0
    assert gateway._pending_responses == {}
    assert gateway._reader_task is None
    assert gateway._heartbeat_task is None
    assert gateway._connection_state == "idle"
    assert gateway._project_path is None
    assert gateway._last_ping_ok is None
    assert gateway._last_error is None


def test_persistent_false_does_not_initialize_state_fields() -> None:
    """``TIAProcessGateway(persistent=False)`` NO inicializa el estado del worker persistente.

    Overhead cero para el modo 1-shot: los atributos del worker
    persistente (``_worker_proc``, ``_worker_lock``, etc.) NO existen
    en absoluto. Si un caller del modo 1-shot intentara acceder a
    uno, recibiría ``AttributeError`` (a propósito: el modo 1-shot
    no debe tocar esas estructuras).
    """
    gateway = TIAProcessGateway(persistent=False)
    assert gateway.persistent is False
    # Ninguno de los atributos del estado persistente existe.
    assert not hasattr(gateway, "_worker_proc")
    assert not hasattr(gateway, "_worker_lock")
    assert not hasattr(gateway, "_next_request_id")
    assert not hasattr(gateway, "_pending_responses")
    assert not hasattr(gateway, "_reader_task")
    assert not hasattr(gateway, "_heartbeat_task")
    assert not hasattr(gateway, "_connection_state")
    assert not hasattr(gateway, "_project_path")
    assert not hasattr(gateway, "_last_ping_ok")
    assert not hasattr(gateway, "_last_error")


# ─────────────────────────────────────────────────────────────────────
# Tests del dispatcher ``_dispatch_worker`` con flag persistente.
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_worker_persistent_raises_not_implemented() -> None:
    """``_dispatch_worker`` con ``persistent=True`` delega en el path persistente (PR 3).

    Cambio sept-2026 (state machine refactor): el dispatcher YA NO
    delega libremente — primero valida que el comando sea
    ``attach_portal``/``detach_portal``/``ping``/``get_project_info``
    o que el estado sea ``"connected"``. Como el gateway arranca
    en ``"idle"``, un comando cualquiera (e.g. ``any_command``)
    rechaza con ``TIAConnectionError`` claro. Este test verifica
    ese rechazo (que ES la API del state machine).
    """
    from core.infrastructure.gateway import TIAConnectionError
    gateway = TIAProcessGateway(persistent=True)
    # Estado inicial: ``"idle"`` (sept-2026, no se ha hecho connect).
    gateway._connection_state = "idle"
    gateway._send_to_persistent_worker = AsyncMock(
        return_value={"ok": True, "result": "should_not_run"}
    )
    gateway._dispatch_ephemeral_worker = AsyncMock(
        return_value={"ok": True, "result": "ephemeral_should_not_run"}
    )

    # ``any_command`` no esta en la lista de permitidos y el estado
    # es ``"idle"``: el dispatcher rechaza con ``TIAConnectionError``.
    with pytest.raises(TIAConnectionError, match="Conectar primero"):
        await gateway._dispatch_worker("any_command", args={"k": "v"})

    # Ninguno de los metodos se invoco (el rechazo es temprano).
    gateway._send_to_persistent_worker.assert_not_awaited()
    gateway._dispatch_ephemeral_worker.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_worker_persistent_does_not_call_ephemeral() -> None:
    """``_dispatch_worker`` con ``persistent=True`` NO cae al path 1-shot (PR 3).

    Si el dispatcher se cayera al ``else`` cuando ``persistent=True``
    (p.ej. por un bug en el switch), la llamada a
    ``_dispatch_ephemeral_worker`` intentaria lanzar un subproceso
    real. Verificamos que el path persistente delega en
    ``_send_to_persistent_worker`` (PR 3) y que
    ``_dispatch_ephemeral_worker`` NO se invoca.

    Cambio sept-2026 (state machine refactor): el dispatcher valida
    estado antes de delegar. Aqui ponemos el gateway en
    ``"connected"`` (simulando un connect exitoso) para verificar
    la delegacion.
    """
    gateway = TIAProcessGateway(persistent=True)
    gateway._connection_state = "connected"  # simular connect exitoso
    sentinel = {"ok": True, "result": "persistent"}
    gateway._send_to_persistent_worker = AsyncMock(return_value=sentinel)
    gateway._dispatch_ephemeral_worker = AsyncMock(
        return_value={"ok": True, "result": "should_not_run"}
    )

    result = await gateway._dispatch_worker("any_command", args={})

    assert result is sentinel
    gateway._send_to_persistent_worker.assert_awaited_once_with(
        "any_command", {}, None
    )
    gateway._dispatch_ephemeral_worker.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_worker_ephemeral_delegates_to_ephemeral_method() -> None:
    """``_dispatch_worker`` con ``persistent=False`` delega en ``_dispatch_ephemeral_worker``.

    Mockeamos el método 1-shot con ``AsyncMock`` para verificar la
    delegación y la propagación del resultado sin lanzar subproceso
    real. La cobertura del comportamiento 1-shot real ya está en
    ``test_timing_metrics.py`` y ``test_gateway_connection_error.py``.
    """
    gateway = TIAProcessGateway(persistent=False)
    expected = {"ok": True, "result": "fake"}
    gateway._dispatch_ephemeral_worker = AsyncMock(return_value=expected)

    result = await gateway._dispatch_worker("ping", args={})

    assert result == expected
    gateway._dispatch_ephemeral_worker.assert_awaited_once_with(
        "ping", {}, None
    )


@pytest.mark.asyncio
async def test_dispatch_worker_ephemeral_propagates_timeout_override() -> None:
    """``_dispatch_worker`` propaga ``timeout_override`` al 1-shot.

    Verifica que el dispatcher genérico no se traga el parámetro
    de timeout (que es relevante para operaciones bulk como
    ``execute_transactional_batch``).
    """
    gateway = TIAProcessGateway(persistent=False)
    gateway._dispatch_ephemeral_worker = AsyncMock(return_value={"ok": True})

    await gateway._dispatch_worker("any_command", args={"k": "v"}, timeout_override=12.5)

    gateway._dispatch_ephemeral_worker.assert_awaited_once_with(
        "any_command", {"k": "v"}, 12.5
    )


# ─────────────────────────────────────────────────────────────────────
# Tests de los helpers de wiring del worker persistente.
# ─────────────────────────────────────────────────────────────────────


def test_resolve_persistent_worker_exec_args_returns_flag() -> None:
    """``_resolve_persistent_worker_exec_args()`` retorna ``["--worker-persistent"]``.

    El gateway combina estos args con ``_resolve_worker_exec_args()``
    (que resuelve ``main.py`` en dev / el .exe en frozen) para
    lanzar el subproceso. El flag DEBE ser EXACTAMENTE
    ``--worker-persistent`` porque ``worker_tia.main()`` lo busca
    con ``"--worker-persistent" in sys.argv``. Cualquier variante
    (``--persistent``, ``-p``, etc.) NO sería detectada.
    """
    gateway = TIAProcessGateway(persistent=True)
    assert gateway._resolve_persistent_worker_exec_args() == ["--worker-persistent"]


@pytest.mark.asyncio
async def test_start_persistent_worker_is_placeholder() -> None:
    """``_start_persistent_worker()`` lanza el subproceso y espera al ready_idle (sept-2026).

    Cambio sept-2026 (state machine refactor): el worker ya NO hace
    attach al inicio, solo emite ``ready_idle``. El gateway
    transiciona a ``"idle"`` (no ``"connected"``).

    Verificaciones:
      - Tras el ready_idle, ``_connection_state == "idle"``.
      - ``_worker_proc`` no es None.
      - ``_reader_task`` no es None.
    """
    import json
    from unittest.mock import AsyncMock, MagicMock, patch

    gateway = TIAProcessGateway(persistent=True)

    fake_proc = MagicMock(name="FakeSubprocess")
    fake_proc.returncode = None  # vivo
    fake_proc.stdin = MagicMock()
    # stdout: emite el "ready_idle" (id=0) y luego EOF. El reader_task
    # leera el ready_idle, resolvera el future en
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
    ):
        await gateway._start_persistent_worker()

    # El ready_idle retorno ok -> el estado pasa a "idle"
    # (NO "connected"; el connect via attach_portal es lo que
    # transiciona a connected, sept-2026).
    assert gateway._connection_state == "idle"
    assert gateway._worker_proc is fake_proc
    assert gateway._reader_task is not None
