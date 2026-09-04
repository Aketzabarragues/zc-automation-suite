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
    - ``_connection_state``: ``"disconnected"`` (estado inicial).
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
    assert gateway._connection_state == "disconnected"
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
    """``_dispatch_worker`` con ``persistent=True`` lanza ``NotImplementedError`` (PR 2).

    El mensaje DEBE mencionar "PR 3" para que un caller que active el
    flag por error reciba una referencia accionable al plan, no un
    fallo silencioso o un comportamiento 1-shot disfrazado de
    persistente.
    """
    gateway = TIAProcessGateway(persistent=True)
    with pytest.raises(NotImplementedError, match="PR 3"):
        await gateway._dispatch_worker("any_command", args={})


@pytest.mark.asyncio
async def test_dispatch_worker_persistent_does_not_call_ephemeral() -> None:
    """``_dispatch_worker`` con ``persistent=True`` NO cae al path 1-shot.

    Si el dispatcher se cayera al ``else`` cuando ``persistent=True``
    (p. ej. por un bug en el switch), la llamada a
    ``_dispatch_ephemeral_worker`` intentaría lanzar un subproceso
    real. Verificamos que el placeholder cortocircuita ANTES y que
    ``_dispatch_ephemeral_worker`` no se invoca.
    """
    gateway = TIAProcessGateway(persistent=True)
    gateway._dispatch_ephemeral_worker = AsyncMock(
        return_value={"ok": True, "result": "should_not_run"}
    )
    with pytest.raises(NotImplementedError, match="PR 3"):
        await gateway._dispatch_worker("any_command", args={})
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
    """``_start_persistent_worker()`` lanza ``NotImplementedError`` con mención a PR 3.

    La implementación real (lanzar el subproceso con
    ``--worker-persistent``, iniciar el reader task, enviar el ping
    inicial) viene en PR 3. Mientras tanto, este placeholder
    garantiza que un caller que intente arrancar el worker en este
    PR reciba un error explícito.
    """
    gateway = TIAProcessGateway(persistent=True)
    with pytest.raises(NotImplementedError, match="PR 3"):
        await gateway._start_persistent_worker()
