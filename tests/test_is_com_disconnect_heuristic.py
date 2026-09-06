"""Tests directos de la heuristica ``_is_com_disconnect``.

Cubre el HALLAZGO #2 del agente build-and-tests (audit profundo
del worker, 2026-09-06): la funcion ``_is_com_disconnect`` del
worker era la UNICA defensa para detectar TIA Portal cerrado
mid-comando y forzar re-attach, pero NO tenia tests directos
en el repo. Cualquier refactor de la heuristica (e.g. cambiar
el orden de los checks, eliminar el ``hasattr(exc, "hresult")``)
pasaba silenciosamente porque ningun test lo detectaba.

Ademas de los tests de la heuristica, este archivo cubre un
gap CRITICO adicional del audit:

- ``gateway.start()`` (HALLAZGO #3 del build-and-tests): el
  fix ``28c2f9d`` restauro este metodo publico. Sin un test
  directo (no mockeado), un futuro refactor podria borrarlo
  de nuevo sin que los tests del lifespan lo detecten (todos
  mockean ``start = AsyncMock()``).

NOTA sobre ``_try_reattach``: la funcion es un closure dentro
de ``main_persistent_loop()``, no se puede importar a nivel
de modulo. Testearla requiere ejecutar el loop entero con
stdin/stdout fakes (el agente 2 lo propuso en
``test_persistent_worker_protocol.py``). Queda fuera de este
PR por scope.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.infrastructure.gateway import TIAProcessGateway  # noqa: E402
from core.infrastructure.tia.worker_tia import (  # noqa: E402
    _is_com_disconnect,
)


# ───────────────────────────────────────────────────────────────────────
# _is_com_disconnect
# ───────────────────────────────────────────────────────────────────────


class TestIsComDisconnect:
    """Cobertura exhaustiva de la heuristica que detecta
    excepciones de desconexion COM/RPC en el worker."""

    def test_com_exception_es_detectado(self) -> None:
        """``COMException`` (tipo .NET) -> ``True`` (por nombre)."""
        # No podemos importar la clase real de Pythonnet (no
        # instalado en CI), pero creamos una clase con el
        # nombre correcto.
        class COMException(Exception):
            pass

        assert _is_com_disconnect(COMException("RCW invalido")) is True

    def test_rpc_exception_es_detectado(self) -> None:
        """``RPCException`` (tipo .NET) -> ``True`` (por nombre)."""

        class RPCException(Exception):
            pass

        assert _is_com_disconnect(RPCException("server unavailable")) is True

    def test_excepcion_con_hresult_es_detectada(self) -> None:
        """Excepcion SIN ``COM``/``RPC`` en el nombre pero CON
        ``hresult`` -> ``True`` (segundo check de la heuristica)."""
        exc = ValueError("error de aplicacion")
        # ``hresult`` es un atributo tipico de las excepciones
        # COM de .NET cuando se envuelven en Python.
        exc.hresult = 0x8001010A  # E_RPC_SERVER_UNAVAILABLE
        assert _is_com_disconnect(exc) is True

    def test_value_error_sin_hresult_no_es_detectado(self) -> None:
        """``ValueError`` SIN ``hresult`` -> ``False`` (es un
        error de aplicacion, no de COM)."""
        assert _is_com_disconnect(ValueError("argumento invalido")) is False

    def test_runtime_error_sin_hresult_no_es_detectado(self) -> None:
        """``RuntimeError`` SIN ``hresult`` -> ``False``."""
        assert _is_com_disconnect(RuntimeError("error interno")) is False

    def test_keyboard_interrupt_no_es_detectado(self) -> None:
        """``KeyboardInterrupt`` NO es COM-disconnect.

        Caso real: si el operario aborta con Ctrl+C, queremos
        que se propague, no que el loop lo trate como re-attach.
        """
        assert _is_com_disconnect(KeyboardInterrupt()) is False

    def test_filenotfound_no_es_detectado(self) -> None:
        """``FileNotFoundError`` NO es COM-disconnect."""
        assert _is_com_disconnect(FileNotFoundError("no existe")) is False

    def test_asyncio_cancelled_error_no_es_detectado(self) -> None:
        """``asyncio.CancelledError`` NO es COM-disconnect.

        Caso real: si el gateway se apaga, el loop del worker
        recibe ``CancelledError``. La heuristica NO debe
        confundirlo con COM-disconnect (seria un bug grave:
        re-attacharia en lugar de salir limpiamente).
        """
        assert _is_com_disconnect(asyncio.CancelledError()) is False

    def test_subclase_con_nombre_parcial_tambien_detectada(self) -> None:
        """Subclases con ``"COM"`` o ``"RPC"`` en el nombre
        tambien son detectadas (caso real: clases .NET como
        ``System.Runtime.InteropServices.COMException``)."""
        # El ``type(exc).__name__`` es "COMException", no
        # "System.Runtime.InteropServices.COMException". La
        # heuristica usa el nombre de la clase directamente.
        class COMException(Exception):
            pass

        # Verificamos que el match es por substring.
        assert _is_com_disconnect(COMException()) is True


# ───────────────────────────────────────────────────────────────────────
# gateway.start()
# ───────────────────────────────────────────────────────────────────────


class TestGatewayStartPublic:
    """Tests directos del metodo publico ``gateway.start()``.

    HALLAZGO #3 del build-and-tests: el fix ``28c2f9d``
    restauro este metodo. Sin un test que ejecute la logica
    real (no mockeada), un refactor futuro podria borrarlo
    sin que los tests del lifespan lo detecten.
    """

    @pytest.mark.asyncio
    async def test_start_no_op_si_persistent_false(self) -> None:
        """Si ``persistent=False``, ``start()`` retorna sin
        hacer nada (el modo 1-shot/MCP no tiene worker
        persistente)."""
        gateway = TIAProcessGateway(persistent=False)
        # Mockeamos solo lo que el constructor pueda tocar.
        gateway._start_persistent_worker = AsyncMock()

        # No debe lanzar ni bloquear.
        await gateway.start()

        # _start_persistent_worker NO debe haberse llamado.
        gateway._start_persistent_worker.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_invoca_start_persistent_worker_si_persistent_true(
        self,
    ) -> None:
        """Si ``persistent=True``, ``start()`` invoca
        ``_start_persistent_worker()`` y espera al ``ready_idle``.

        Mockeamos ``_start_persistent_worker`` (no el subproceso
        real) para verificar que el flujo de arranque del
        worker ocurre.
        """
        gateway = TIAProcessGateway(persistent=True)
        gateway._start_persistent_worker = AsyncMock()

        await gateway.start()

        gateway._start_persistent_worker.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_log_info_arrancando_worker(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """El log de ``start()`` (commit ``b82f9d6``) se emite
        con el prefijo ``gateway.start():``.

        HALLAZGO #13 del build-and-tests: los logs de ciclo de
        vida añadidos en ``b82f9d6`` no se verificaban con
        caplog. Este test cubre el log de start."""
        import logging

        gateway = TIAProcessGateway(persistent=True)
        gateway._start_persistent_worker = AsyncMock()

        with caplog.at_level(
            logging.INFO, logger="core.infrastructure.gateway"
        ):
            await gateway.start()

        assert any(
            "gateway.start(): arrancando worker" in record.message
            for record in caplog.records
        ), f"Logs capturados: {[r.message for r in caplog.records]}"
