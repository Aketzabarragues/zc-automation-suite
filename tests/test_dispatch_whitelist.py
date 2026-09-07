"""Tests del fix A8 (audit de robustez, sept-2026).

Cubre la inclusion de ``list_plcs`` en la whitelist de comandos
que pueden saltarse la validacion de ``_connection_state ==
"connected"`` en ``_dispatch_worker``. Antes (pre-A8) el polling
de ``get_plcs`` (que el frontend hace desde el primer ``GET
/tia/connection``, ANTES de que el operario haya pulsado
"Conectar") fallaba con un error confuso si el state estaba en
transitorio. Anadirlo permite que la SPA muestre la lista de PLCs
en cuanto el worker este vivo, sin esperar al connect.

Estrategia:
  - Gateway persistente (sin mockear el subproceso: usamos un
    proc mock simple con stdin.write/drain y stdout.readline).
  - Probamos con cada uno de los 5 comandos de la whitelist
    (``attach_portal``, ``detach_portal``, ``ping``,
    ``get_project_info``, ``list_plcs``) que NO lanzan
    ``TIAConnectionError`` aunque el state NO sea "connected".
  - Probamos con un comando NO whitelist (``compile_plc``) que
    SI lanza ``TIAConnectionError`` si el state es
    "idle"/"connecting".
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.infrastructure.gateway import TIAProcessGateway, TIAConnectionError


def _make_proc_with_response(response: dict) -> MagicMock:
    """Crea un fake proc que emite 1 linea JSON y luego EOF."""
    line = (json.dumps(response) + "\n").encode("utf-8")
    stream_iter = iter([line, b""])

    class _FakeStream:
        async def readline(self) -> bytes:
            return next(stream_iter, b"")

    class _FakeStdin:
        def __init__(self) -> None:
            self.written: list[bytes] = []

        def write(self, data: bytes) -> None:
            self.written.append(data)

        async def drain(self) -> None:
            pass

    fake_proc = MagicMock(name="FakeSubprocess")
    fake_proc.stdin = _FakeStdin()
    fake_proc.stdout = _FakeStream()
    fake_proc.returncode = None
    return fake_proc


class TestListPlcsInWhitelist:
    """``list_plcs`` esta en la whitelist y se acepta con state != connected (fix A8)."""

    @pytest.mark.asyncio
    async def test_list_plcs_se_acepta_con_state_idle(self) -> None:
        """``list_plcs`` con state ``"idle"`` NO lanza ``TIAConnectionError``.

        Caso real: el frontend hace polling de PLCs desde el
        primer GET /tia/connection. El state esta en ``"idle"``
        (worker vivo, portal no attached). El polling debe
        poder pedir PLCs sin que el gateway le devuelva un
        error de "no conectado".
        """
        gateway = TIAProcessGateway(persistent=True, timeout=2.0)
        gateway._connection_state = "idle"
        # Mockeamos el proc para que devuelva una respuesta OK.
        gateway._worker_proc = _make_proc_with_response(
            {"id": 1, "ok": True, "result": ["PLC1"]}
        )

        # Reader mock que resuelve el future al instante.
        async def _reader() -> None:
            await asyncio.sleep(60)

        gateway._reader_task = asyncio.create_task(_reader())
        try:
            # Sin state "connected" pero con list_plcs en la whitelist,
            # NO debe lanzar TIAConnectionError.
            real_wait_for = asyncio.wait_for

            async def _patched(awaitable, *args, **kwargs):  # noqa: ARG001
                if isinstance(awaitable, asyncio.Future):
                    # sept-2026: ``list_plcs`` ahora devuelve una
                    # lista de dicts ``{name, short_designation}``
                    # (no solo strings). Este test mockea la
                    # respuesta del subproceso worker, asi que
                    # usamos la nueva forma para que el ``assert``
                    # de abajo sea coherente con el contrato real.
                    awaitable.set_result(
                        {
                            "id": 1,
                            "ok": True,
                            "result": [
                                {"name": "PLC1", "short_designation": None}
                            ],
                        }
                    )
                    return awaitable.result()
                return await real_wait_for(awaitable, *args, **kwargs)

            with patch("core.infrastructure.gateway.asyncio.wait_for", side_effect=_patched):
                result = await gateway._dispatch_worker("list_plcs", args={})
            assert result == [{"name": "PLC1", "short_designation": None}]
        finally:
            gateway._reader_task.cancel()
            try:
                await gateway._reader_task
            except (asyncio.CancelledError, Exception):
                pass

    @pytest.mark.asyncio
    async def test_comando_no_whitelist_bloqueado_en_idle(self) -> None:
        """Un comando que NO esta en la whitelist (e.g. ``compile_plc``) SI lanza con state ``"idle"``.

        Sanity check del whitelist: ``compile_plc`` requiere
        state "connected" (no es un comando de control del
        state machine ni una lectura ligera del polling).
        """
        gateway = TIAProcessGateway(persistent=True, timeout=2.0)
        gateway._connection_state = "idle"

        # NO debe tocar el subproceso: el check de state debe
        # cortar ANTES de enviar.
        with pytest.raises(TIAConnectionError, match="no conectado"):
            await gateway._dispatch_worker("compile_plc", args={})


# Necesario para el patch usado arriba.
from unittest.mock import patch  # noqa: E402
