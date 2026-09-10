"""Tests del comando ``ping`` del worker OT y de su wrapper en el gateway.

Cubre PR 1 del refactor del worker OT persistente
(``_plan/13_persistent_worker_impl.md``):

- **Worker:** ``_cmd_ping`` delega en ``portal.get_process_id()`` y
  normaliza el resultado a ``{ok, pid?}`` o ``{ok, error}``.
  Tres caminos cubiertos:
    1. Portal attached, ``get_process_id()`` retorna entero → ``{ok: True, pid: int}``.
    2. ``portal is None`` → ``{ok: False, error: "No hay portal attached"}``.
    3. ``get_process_id()`` lanza excepción (TIA cerrado) → ``{ok: False, error: "..."}``.
- **Registry:** ``"ping"`` aparece en ``COMMAND_REGISTRY`` y mapea
  a ``_cmd_ping``.
- **Gateway:** ``gateway.ping()`` delega en ``_dispatch_worker``
  con ``("ping", args={})`` y retorna el resultado del worker tal cual.

Estrategia de testing:

- **Handler:** ``MagicMock()`` (sin ``spec``: el portal es un objeto
  Pythonnet arbitrario). El mock expone ``get_process_id()`` que
  retorna un entero o lanza una excepción según el test. NO
  necesitamos un TIA Portal real ni ``siemens_tia_scripting``.

- **Gateway wrapper:** ``AsyncMock`` sobre ``_dispatch_worker`` (mismo
  patrón que ``test_disp_gateway.py``). Verificamos que se invoca
  con los argumentos correctos y que retorna el resultado del worker.
"""
from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.infrastructure.gateway import TIAProcessGateway


# ────────────────────────────────────────────────────────────────────────
# Carga perezosa del módulo del worker (sin ejecutar main()).
# ────────────────────────────────────────────────────────────────────────

worker_tia = importlib.import_module("core.infrastructure.tia.worker_tia")
COMMAND_REGISTRY: dict = worker_tia.COMMAND_REGISTRY
_cmd_ping = worker_tia._cmd_ping


# ────────────────────────────────────────────────────────────────────────
# Tests del handler ``_cmd_ping``.
# ────────────────────────────────────────────────────────────────────────


class TestCmdPing:
    """Verifica los 3 caminos del handler del worker."""

    def test_portal_attached_con_pid_devuelve_ok_y_pid(self) -> None:
        """Portal mock con ``get_process_id()`` válido → ``{ok: True, pid: int}``."""
        portal = MagicMock()
        portal.get_process_id.return_value = 12345

        result = _cmd_ping(portal, ts=None, args={})

        assert result == {"ok": True, "pid": 12345}
        portal.get_process_id.assert_called_once_with()

    def test_portal_none_devuelve_error(self) -> None:
        """Sin portal attached (lazy start aún no ejecutado) → ``{ok: False, error: ...}``.

        NO debe intentar llamar a ``get_process_id()`` sobre ``None``
        (reventaría con ``AttributeError``). Por eso el handler hace
        el ``if portal is None`` ANTES del ``try``.
        """
        result = _cmd_ping(portal=None, ts=None, args={})

        assert result["ok"] is False
        assert "No hay portal attached" in result["error"]
        # Asegurar que NO se intentó llamar a ``get_process_id`` (portal es None).
        # Si el handler lo intentara, reventaría; este assert es defensivo
        # contra refactors que muevan el orden de las comprobaciones.

    def test_get_process_id_lanza_excepcion_devuelve_error(self) -> None:
        """Excepción COM/RPC (TIA cerrado) → ``{ok: False, error: "<Type>: <msg>"}``.

        El handler DEBE capturar la excepción y devolver un dict con
        ``ok=False`` y el mensaje de error, NO propagar la excepción
        (los callers esperan un dict siempre).
        """
        portal = MagicMock()
        portal.get_process_id.side_effect = RuntimeError(
            "RPC server unavailable"
        )

        result = _cmd_ping(portal, ts=None, args={})

        assert result["ok"] is False
        assert "RuntimeError" in result["error"]
        assert "RPC server unavailable" in result["error"]

    def test_get_process_id_devuelve_int_se_normaliza(self) -> None:
        """``get_process_id()`` puede devolver un tipo .NET (no exactamente int).

        El handler aplica ``int(pid)`` para garantizar que el payload
        es JSON-serializable como entero. Test con un mock que devuelve
        un valor que se parece a un entero de Pythonnet (cualquier
        objeto con ``__int__``).
        """
        portal = MagicMock()

        class FakePid:
            """Mock de un PID .NET: implementa ``__int__`` pero NO es ``int``."""

            def __int__(self) -> int:
                return 67890

        portal.get_process_id.return_value = FakePid()

        result = _cmd_ping(portal, ts=None, args={})

        assert result == {"ok": True, "pid": 67890}
        assert isinstance(result["pid"], int)


# ────────────────────────────────────────────────────────────────────────
# Tests del registro en ``COMMAND_REGISTRY``.
# ────────────────────────────────────────────────────────────────────────


def test_ping_registered_in_command_registry() -> None:
    """``"ping"`` está en ``COMMAND_REGISTRY`` y mapea a ``_cmd_ping``.

    Garantiza que el command loader del worker (que llama
    ``COMMAND_REGISTRY[command](portal, ts, args)`` en ``main()``)
    puede despachar el comando correctamente.
    """
    assert "ping" in COMMAND_REGISTRY
    assert COMMAND_REGISTRY["ping"] is _cmd_ping


# ────────────────────────────────────────────────────────────────────────
# Tests del wrapper ``gateway.ping()``.
# ────────────────────────────────────────────────────────────────────────


class TestGatewayPing:
    """Verifica que ``TIAProcessGateway.ping()`` delega correctamente."""

    @pytest.mark.asyncio
    async def test_ping_delega_en_dispatch_worker(self) -> None:
        """``gateway.ping()`` invoca ``_dispatch_worker("ping", args={})`` y retorna el resultado."""
        gateway = TIAProcessGateway()
        # Mockeamos ``_dispatch_worker`` para no lanzar subproceso real.
        gateway._dispatch_worker = AsyncMock(
            return_value={"ok": True, "pid": 12345}
        )

        result = await gateway.ping()

        # Verificar que se llamó con los argumentos correctos.
        gateway._dispatch_worker.assert_awaited_once_with("ping", args={})
        # Y que el resultado del worker se retorna tal cual.
        assert result == {"ok": True, "pid": 12345}

    @pytest.mark.asyncio
    async def test_ping_propag_error_del_worker(self) -> None:
        """Si el worker reporta ``{ok: False, error: ...}``, el gateway propaga ``RuntimeError``.

        El comportamiento de ``_dispatch_worker`` (lanzar ``RuntimeError``
        cuando el JSON de respuesta tiene ``ok: False``) NO cambia; el
        wrapper ``ping()`` lo hereda automáticamente. Test de regresión
        para que un futuro cambio en el wrapper no rompa este contrato.
        """
        gateway = TIAProcessGateway()
        # Simulamos que ``_dispatch_worker`` lanza RuntimeError (camino
        # normal de error del gateway actual).
        gateway._dispatch_worker = AsyncMock(
            side_effect=RuntimeError("El subproceso OT colapsó")
        )

        with pytest.raises(RuntimeError, match="subproceso OT colapsó"):
            await gateway.ping()
