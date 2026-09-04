"""Tests del manejo de errores de conexion TIA en el gateway.

Cubre la opcion B conservadora del fix de invalidacion de cache:
solo invalidar cuando el mensaje del worker matchea con un patron
conocido de "TIA no disponible" (portal cerrado, version no
encontrada, sin proyecto abierto, etc.). NO invalida en cualquier
error (e.g. un error de logica).

Mockeamos ``asyncio.create_subprocess_exec`` a nivel de modulo
gateway para inyectar un subprocess que devuelve la respuesta del
worker que queremos testear. Asi NO tocamos ``_dispatch_worker``
(que es el codigo bajo prueba) y el flujo real ejecuta la
deteccion de patrones + invalidacion de cache + raise de la
excepcion apropiada.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.infrastructure.gateway import (
    TIAConnectionError,
    TIAProcessGateway,
    _is_tia_connection_error,
)


# ── Tests del helper puro ──────────────────────────────────────────────


class TestIsTiaConnectionError:
    """Tests unitarios del matcher de patrones (sin gateway)."""

    @pytest.mark.parametrize(
        "msg",
        [
            "OpennessAccessException: No matching TIA Portal version could be found.",
            "TIA Portal is not running",
            "Cannot attach to portal",
            "no project is open",
            "TIA Portal ExclusiveAccess denied",
            "OpennessAccessException: some other text",
            "wrapped OpennessAccessException",  # substring match
        ],
    )
    def test_patrones_conocidos_matchean(self, msg: str) -> None:
        assert _is_tia_connection_error(msg) is True

    @pytest.mark.parametrize(
        "msg",
        [
            "ValueError: division by zero",
            "RuntimeError: unexpected EOF",
            "PermissionError: file in use",
            "KeyError: 'foo'",
            "Some other unrelated error",
        ],
    )
    def test_errores_de_logica_no_matchean(self, msg: str) -> None:
        assert _is_tia_connection_error(msg) is False

    def test_mensaje_vacio_no_matchea(self) -> None:
        assert _is_tia_connection_error("") is False


# ── Tests de integracion: subprocess mockeado ──────────────────────────


def _make_fake_subprocess(
    json_response: dict,
    stderr_text: str = "",
    returncode: int = 0,
) -> MagicMock:
    """Crea un mock de ``Process`` que devuelve ``json_response`` por stdout.

    Simula el output del worker subprocess sin necesidad de arrancar
    un proceso real. El stdout contiene SOLO la respuesta JSON en
    una linea (mismo shape que el worker real).
    """
    proc = MagicMock(name="FakeSubprocess")
    proc.returncode = returncode
    proc.communicate = AsyncMock(
        return_value=(
            (json.dumps(json_response) + "\n").encode("utf-8"),
            stderr_text.encode("utf-8"),
        )
    )
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


class TestGatewayConnectionErrorHandling:
    """Tests end-to-end: subprocess devuelve error, gateway decide
    si es TIAConnectionError y limpia cache."""

    def test_tia_connection_error_es_subclase_de_runtime_error(self) -> None:
        """Compatibilidad: call sites que capturan RuntimeError siguen
        capturando TIAConnectionError sin cambios."""
        assert issubclass(TIAConnectionError, RuntimeError)

    @pytest.mark.asyncio
    async def test_error_de_conexion_lanza_tia_connection_error_y_limpia_cache(self) -> None:
        """Patron de error de conexion matcheado:
          - Lanza TIAConnectionError.
          - Invalida ``_bloques_cache`` y ``_cache``."""
        from datetime import datetime, timezone
        from core.models import BloqueCache, BloquePLC

        gateway = TIAProcessGateway()
        # Sembrar ambas caches con datos stale.
        gateway._cache["plcs"] = ["PLC_X", "PLC_Y"]
        gateway._cache["project_info"] = {"name": "OldProject"}
        cache_stale = BloqueCache(
            blocks={"db1": BloquePLC(nombre="DB1", numero=1, tipo="DB", ruta="")},
            tag_tables={},
            udts={},
            plc_name="PLC_X",
            scanned_at=datetime.now(timezone.utc),
        )
        gateway._bloques_cache["PLC_X"] = cache_stale

        # Subprocess falso: devuelve un error que matchea el patron
        # tipico del log de operario.
        fake_proc = _make_fake_subprocess({
            "ok": False,
            "error": (
                "OpennessAccessException: No matching TIA Portal version "
                "could be found."
            ),
        })

        with patch(
            "core.infrastructure.gateway.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=fake_proc),
        ):
            with pytest.raises(TIAConnectionError):
                await gateway.get_plcs(force_refresh=True)

        # Tras el error, AMBAS caches deben estar vacias.
        assert gateway._cache == {}
        assert gateway._bloques_cache == {}

    @pytest.mark.asyncio
    async def test_error_de_logica_no_limpia_cache(self) -> None:
        """Error de logica (no de conexion) → RuntimeError plano,
        cache intacta (no invalidamos en cualquier error)."""
        gateway = TIAProcessGateway()
        gateway._cache["plcs"] = ["PLC_X", "PLC_Y"]
        # _bloques_cache se mantiene como dict normal (lo que el
        # gateway usa internamente); no necesitamos un BloqueCache real
        # porque el gateway solo hace ``.clear()`` / ``.pop()``.
        gateway._bloques_cache["PLC_X"] = object()  # type: ignore[assignment]

        fake_proc = _make_fake_subprocess({
            "ok": False,
            "error": "ValueError: division by zero",
        })

        with patch(
            "core.infrastructure.gateway.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=fake_proc),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                await gateway.get_plcs(force_refresh=True)

        # NO es TIAConnectionError (subclase de RuntimeError).
        assert not isinstance(exc_info.value, TIAConnectionError)
        # Cache intacta: el error es de logica, no de conexion.
        assert "plcs" in gateway._cache
        assert "PLC_X" in gateway._bloques_cache

    @pytest.mark.asyncio
    async def test_error_de_conexion_en_scan_blocks_tambien_limpia(self) -> None:
        """El mismo flujo aplica a ``scan_plc_blocks`` (la cache
        especializada de bloques, que es la que tiene los snapshots
        grandes que más le duelen al operario si quedan stale)."""
        from datetime import datetime, timezone
        from core.models import BloqueCache, BloquePLC

        gateway = TIAProcessGateway()
        cache_stale = BloqueCache(
            blocks={
                "db1": BloquePLC(nombre="DB1", numero=1, tipo="DB", ruta=""),
            },
            tag_tables={},
            udts={},
            plc_name="PLC_X",
            scanned_at=datetime.now(timezone.utc),
        )
        gateway._bloques_cache["PLC_X"] = cache_stale

        fake_proc = _make_fake_subprocess({
            "ok": False,
            "error": "Cannot attach to TIA Portal V18",
        })

        with patch(
            "core.infrastructure.gateway.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=fake_proc),
        ):
            with pytest.raises(TIAConnectionError):
                await gateway.scan_plc_blocks("PLC_X", force_refresh=True)

        assert gateway._bloques_cache == {}
        assert gateway._cache == {}


# ── Tests del helper _is_tia_connection_error (edge cases) ─────────────


def test_helper_matchea_substring_en_cualquier_posicion() -> None:
    """El matcher es por substring, no por equality."""
    assert _is_tia_connection_error("Error: Cannot attach to portal V18") is True
    assert _is_tia_connection_error("pre: Cannot attach, post") is True
    assert _is_tia_connection_error("Cannot attach") is True
