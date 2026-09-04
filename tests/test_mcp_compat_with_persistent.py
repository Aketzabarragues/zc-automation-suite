"""Tests de compatibilidad del modo MCP con el refactor del worker persistente (PR 8).

Cubre ``_plan/13_persistent_worker_impl.md`` PR 8 y el design doc
`_plan/12_worker_persistent_design.md` §2.3 ("Modo MCP: sin cambios").

El refactor del worker persistente (PR 1-7) añadió el flag
``gateway.persistent: bool`` (default ``False``) y toda la
infraestructura asociada (campos de estado, ``_reader_task``,
``_heartbeat_task``, ``_send_to_persistent_worker``, ``reconnect()``,
``disconnect()``, ``_detect_project_change``, etc.). El modo MCP
(``gateway.persistent=False``) DEBE seguir comportándose exactamente
igual que antes del refactor:

  1. **Overhead cero**: los atributos del estado persistente NO se
     inicializan (no existen en la instancia). Esto evita que el
     modo 1-shot pague el costo de un ``asyncio.Lock`` que nunca va
     a usar, ni diccionarios de futures vacíos, ni un contador de
     IDs, ni nada.
  2. **Dispatcher 1-shot intacto**: cada llamada a
     ``_dispatch_worker`` cae en ``_dispatch_ephemeral_worker``
     (proceso efímero por comando, comportamiento histórico). NO
     debe llamar a ``_send_to_persistent_worker`` ni a
     ``_detect_project_change``.
  3. **API nueva del modo persistente no aplica**: ``reconnect()`` y
     ``disconnect()`` (introducidos en PR 6 para el topbar web)
     deben lanzar ``TIAConnectionError`` cuando se invocan en modo
     MCP. Si se permitieran, intentarían matar un worker que no
     existe o tocar atributos no inicializados.

Estrategia de testing:

- Para los puntos 1, 2, 3: tests síncronos que construyen un
  gateway con ``persistent=False`` y/o ``persistent=True`` e
  inspeccionan atributos. Sin mocks para los asserts de init
  condicional. Para el dispatcher, ``AsyncMock`` sobre
  ``_dispatch_ephemeral_worker`` y ``_send_to_persistent_worker``.
- Para los métodos nuevos ``reconnect()`` y ``disconnect()`` en modo
  1-shot: ``pytest.raises`` con ``match="solo aplica a
  gateway.persistent=True"`` (verifica que el mensaje apunta al
  modo correcto, no a un fallo genérico).

Por qué este test es importante:

Este test es la "valla de seguridad" del refactor: si alguien
rompe el init condicional en el futuro y empieza a asignar
``_worker_proc=None`` u ``_worker_lock=Lock()`` en modo MCP,
estos tests fallan inmediatamente. Lo mismo si el dispatcher
empieza a caer al path persistente por error (rompería el
modo 1-shot en producción).

Los tests del MCP existentes (``tests/test_mcp_shell.py``,
``tests/test_mcp_alimentacion_tools.py``) YA cubren el
comportamiento de las tools; este archivo es una capa extra
sobre el gateway en sí.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from core.infrastructure.gateway import TIAConnectionError, TIAProcessGateway


# ─────────────────────────────────────────────────────────────────────
# 1. Init condicional: ``persistent=False`` NO crea el estado del
#    worker persistente. Overhead cero para el modo MCP.
# ─────────────────────────────────────────────────────────────────────


def test_persistent_false_no_worker_proc() -> None:
    """Modo MCP no crea ``_worker_proc``: el subproceso es efímero por comando.

    ``_worker_proc`` es el handle del subproceso persistente. En
    modo 1-shot NO debe existir en absoluto: si un caller
    intentara accederlo, recibiría ``AttributeError`` (a propósito:
    el modo 1-shot no debe tocar esa estructura).
    """
    gateway = TIAProcessGateway(persistent=False)
    assert not hasattr(gateway, "_worker_proc"), (
        "Modo MCP (persistent=False) no debe inicializar _worker_proc. "
        "Si este assert falla, alguien toco el init condicional y "
        "rompio el overhead cero del modo 1-shot."
    )


def test_persistent_false_no_worker_lock() -> None:
    """Modo MCP no crea ``_worker_lock``: no hay stream que serializar.

    El lock se usa para serializar requests contra el stdin/stdout
    del worker persistente. En modo 1-shot cada subproceso es
    independiente (no hay stream compartido), por lo que el lock
    es innecesario y no debe existir.
    """
    gateway = TIAProcessGateway(persistent=False)
    assert not hasattr(gateway, "_worker_lock"), (
        "Modo MCP (persistent=False) no debe inicializar _worker_lock. "
        "Crea un asyncio.Lock innecesario."
    )


def test_persistent_false_no_task_or_state_fields() -> None:
    """Modo MCP no crea ``_reader_task``, ``_heartbeat_task`` ni ``_connection_state``.

    Estos 3 campos forman el "runtime" del worker persistente:
      - ``_reader_task``: task asyncio única que consume stdout
        del worker y resuelve futures por ID.
      - ``_heartbeat_task``: task asyncio que lanza un ``ping``
        cada 5s para detectar TIA cerrada.
      - ``_connection_state``: estado de la conexión persistente
        (``"disconnected"`` / ``"connecting"`` / ``"connected"`` /
        ``"error"``).

    En modo 1-shot ninguno tiene sentido. Si se crearan, el
    proceso MCP lanzaría un heartbeat que pegaría contra TIA cada
    5s aunque el operario no haya invocado ninguna tool, lo que es
    un cambio observable del comportamiento histórico.
    """
    gateway = TIAProcessGateway(persistent=False)
    assert not hasattr(gateway, "_reader_task")
    assert not hasattr(gateway, "_heartbeat_task")
    assert not hasattr(gateway, "_connection_state")


def test_persistent_false_no_project_change_or_ping_fields() -> None:
    """Modo MCP no crea ``_project_path``, ``_last_ping_ok``, ``_last_error`` ni ``_project_changed``.

    Estos 4 campos son bookkeeping de la sesión persistente:
      - ``_project_path``: para detectar cambios de proyecto (PR 7).
      - ``_project_changed``: flag one-shot que el frontend consume
        via ``/tia/connection``.
      - ``_last_ping_ok`` / ``_last_error``: estado del último
        ping del heartbeat.

    En modo 1-shot la SPA no existe, el heartbeat tampoco, y no
    hay frontend que consuma ``/tia/connection``. Estos campos
    son dead weight y no deben existir.
    """
    gateway = TIAProcessGateway(persistent=False)
    assert not hasattr(gateway, "_project_path")
    assert not hasattr(gateway, "_project_changed")
    assert not hasattr(gateway, "_last_ping_ok")
    assert not hasattr(gateway, "_last_error")


def test_persistent_false_no_request_bookkeeping() -> None:
    """Modo MCP no crea ``_next_request_id`` ni ``_pending_responses``.

    El protocolo request-response con IDs (PR 3) asigna un ID
    incremental a cada comando y registra un ``asyncio.Future``
    en ``_pending_responses`` que el reader_task resuelve al
    recibir la respuesta. En modo 1-shot no hay reader, no hay
    IDs y no hay futures pendientes: el subproceso efímero ya
    devuelve su resultado directamente por ``proc.communicate()``.
    """
    gateway = TIAProcessGateway(persistent=False)
    assert not hasattr(gateway, "_next_request_id")
    assert not hasattr(gateway, "_pending_responses")


# ─────────────────────────────────────────────────────────────────────
# 2. Dispatcher: ``persistent=False`` cae al path 1-shot intacto.
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_worker_ephemeral_does_not_touch_persistent_path() -> None:
    """``_dispatch_worker`` en modo MCP NO usa el path persistente.

    Verifica que el switch del dispatcher (``if self._persistent:
    ... else: _dispatch_ephemeral_worker(...)``) no se rompe ni
    cae al path persistente por error:

      - ``_send_to_persistent_worker`` NO se invoca.
      - ``_dispatch_ephemeral_worker`` SÍ se invoca.
      - El resultado del efímero se propaga tal cual.
      - ``_detect_project_change`` NO se invoca (es específico del
        modo persistente; introducirlo en modo MCP sería un
        cambio de comportamiento: cada tool MCP dispararía un
        ``get_project_info`` extra antes del comando, duplicando
        el attach contra TIA).

    Mocks: ``AsyncMock`` sobre los 3 métodos internos. NO
    lanzamos un subproceso real (sería lento y frágil, y este
    test no quiere probar el comportamiento 1-shot real — eso
    está cubierto por ``tests/test_timing_metrics.py``).
    """
    gateway = TIAProcessGateway(persistent=False)
    expected = {"ok": True, "result": "ephemeral_1shot"}
    gateway._dispatch_ephemeral_worker = AsyncMock(return_value=expected)
    # Si el dispatcher cayera al path persistente por error,
    # estos mocks detectarian la llamada.
    gateway._send_to_persistent_worker = AsyncMock(
        return_value={"ok": True, "result": "should_not_run"}
    )
    gateway._detect_project_change = AsyncMock(return_value=False)

    result = await gateway._dispatch_worker("ping", args={})

    assert result is expected
    gateway._dispatch_ephemeral_worker.assert_awaited_once_with("ping", {}, None)
    gateway._send_to_persistent_worker.assert_not_awaited()
    gateway._detect_project_change.assert_not_awaited()


# ─────────────────────────────────────────────────────────────────────
# 3. API nueva del modo persistente: en modo MCP lanza error claro.
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconnect_raises_in_ephemeral_mode() -> None:
    """``reconnect()`` en modo MCP lanza ``TIAConnectionError`` con mensaje claro.

    El botón "Reconectar" del topbar (introducido en PR 6) solo
    tiene sentido en el modo web (``persistent=True``). Si un
    caller del modo MCP invocara ``reconnect()`` (p.ej. por un
    bug del frontend o un caller que asume ``persistent=True``),
    el gateway debe fallar de forma explícita en lugar de:

      - Intentar matar un ``_worker_proc`` que no existe.
      - Tocar ``_reader_task`` o ``_heartbeat_task`` no inicializados.
      - Silenciosamente no hacer nada (lo que ocultaría el bug).

    El mensaje del error DEBE mencionar ``gateway.persistent=True``
    para que el caller sepa que el método no aplica a su modo.
    """
    gateway = TIAProcessGateway(persistent=False)
    with pytest.raises(TIAConnectionError, match="solo aplica a gateway.persistent=True"):
        await gateway.reconnect()


@pytest.mark.asyncio
async def test_disconnect_raises_in_ephemeral_mode() -> None:
    """``disconnect()`` en modo MCP lanza ``TIAConnectionError`` con mensaje claro.

    Mismo contrato que ``reconnect()`` (ver test anterior): el
    botón "Desconectar" del topbar es del modo web y no debe
    invocarse en modo MCP. Si pasara, queremos un error legible,
    no un ``AttributeError`` por acceder a ``_worker_proc`` no
    inicializado.
    """
    gateway = TIAProcessGateway(persistent=False)
    with pytest.raises(TIAConnectionError, match="solo aplica a gateway.persistent=True"):
        await gateway.disconnect()


# ─────────────────────────────────────────────────────────────────────
# 4. Defensivo: ``persistent=True`` SÍ inicializa el estado (regresión
#    del camino opuesto). No es redundante con test_gateway_persistent_flag.py:
#    este test valida que el init del estado persistente sigue
#    funcionando DESPUÉS de que se hicieron los tests del modo MCP,
#    como smoke test del switch.
# ─────────────────────────────────────────────────────────────────────


def test_persistent_true_init_does_not_break_ephemeral_init() -> None:
    """``persistent=True`` no contamina el init del modo 1-shot.

    En particular, el lock del worker persistente debe ser un
    ``asyncio.Lock`` real (no ``None``) porque ``_dispatch_worker``
    lo adquiere via ``async with self._worker_lock`` antes de
    delegar. Si fuera ``None``, el modo persistente crashearia
    con ``AttributeError`` en el primer comando. Este test es
    un smoke test del init del estado persistente y sirve de
    contrapunto al resto del archivo (que verifica que el modo
    1-shot NO se inicializa).
    """
    gateway = TIAProcessGateway(persistent=True)
    assert gateway.persistent is True
    assert gateway._worker_proc is None  # aún no hay subproceso arrancado
    assert isinstance(gateway._worker_lock, asyncio.Lock)
    assert gateway._next_request_id == 0
    assert gateway._pending_responses == {}
    assert gateway._reader_task is None
    assert gateway._heartbeat_task is None
    assert gateway._connection_state == "disconnected"
