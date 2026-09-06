"""Tests del fix A4 (audit de robustez, sept-2026).

Cubre la invalidacion de caches (``_cache`` y ``_bloques_cache``)
tras rename / delete de ``PlcUserConstant``. Antes (pre-A4) el
gateway solo invalidaba caches en ``update_user_constant_value``;
``update_user_constant_name`` y ``delete_user_constant`` dejaban
la cache stale, por lo que el siguiente ``get_user_constants``
podia devolver una lista fantasma (con el nombre viejo o sin
el borrado). Ver ``core/infrastructure/gateway.py:2473-2510``
para el codigo de produccion.

Estrategia:
  - Mockeamos ``_dispatch_worker`` con ``AsyncMock`` para que
    devuelva ``True`` sin tocar el subproceso real.
  - Pre-poblamos ``_cache`` y ``_bloques_cache`` con datos
    sentinela.
  - Invocamos el metodo (rename / delete) y verificamos que
    ``_cache == {}`` y ``_bloques_cache == {}`` tras el exito.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.infrastructure.gateway import TIAProcessGateway


@pytest.fixture
def gateway_with_cache() -> TIAProcessGateway:
    """Gateway fresco con ``_cache`` y ``_bloques_cache`` pre-poblados.

    Mismo patron que ``test_disp_gateway.py``: mockeamos
    ``_dispatch_worker`` para que devuelva ``True`` sin lanzar
    el subproceso real (requiere TIA + siemens_tia_scripting).
    """
    g = TIAProcessGateway()
    g._dispatch_worker = AsyncMock(return_value=True)
    # Pre-poblamos las caches con sentinelas.
    g._cache["plcs"] = ["PLC1", "PLC2"]
    g._cache["project_info"] = {"name": "TestProject"}
    # _bloques_cache espera un BloqueCache; usamos un dict como sentinel.
    g._bloques_cache["PLC1"] = {"fake_bloque_cache": True}
    g._bloques_cache["PLC2"] = {"fake_bloque_cache": True}
    return g


class TestUpdateUserConstantNameCacheInvalidation:
    """``update_user_constant_name`` invalida ``_cache`` y ``_bloques_cache`` (fix A4)."""

    def test_rename_invalida_cache_global(
        self, gateway_with_cache: TIAProcessGateway,
    ) -> None:
        """Tras un rename exitoso, ``_cache == {}`` y ``_bloques_cache == {}``.

        Caso real (audit A4, sept-2026): el operario renombra
        ``N_MAX_DISP_ED`` a ``N_MAX_DISP_ED_NEW``. Sin la
        invalidacion, el siguiente ``get_user_constants``
        devolveria la lista con el nombre viejo y el frontend
        mostraria referencias rotas (comentarios de slots,
        dimensiones de DBs que apuntan al nombre nuevo).
        """
        import asyncio

        asyncio.run(
            gateway_with_cache.update_user_constant_name(
                plc_name="PLC1",
                table_name="UserConstants",
                current_name="N_MAX_DISP_ED",
                new_name="N_MAX_DISP_ED_NEW",
            )
        )

        # _dispatch_worker se llamo con los args correctos.
        gateway_with_cache._dispatch_worker.assert_called_once()
        call = gateway_with_cache._dispatch_worker.call_args
        assert call.args[0] == "update_user_constant_name"
        assert call.kwargs.get("args", call.args[1] if len(call.args) > 1 else None) is not None

        # Las caches se invalidaron.
        assert gateway_with_cache._cache == {}
        assert gateway_with_cache._bloques_cache == {}

    def test_rename_no_toca_worker_si_dispatch_falla(
        self, gateway_with_cache: TIAProcessGateway,
    ) -> None:
        """Si el dispatch lanza, NO se invalidan las caches (no hay nada que invalidar).

        Cambio de comportamiento: ``update_user_constant_value``
        (linea 2470) invalida DESPUES del dispatch. Si el
        dispatch lanza, ``self.clear_cache()`` no se ejecuta y
        el caller ve la excepcion. Misma semantica aplicada a
        ``update_user_constant_name``.
        """
        import asyncio

        gateway_with_cache._dispatch_worker = AsyncMock(
            side_effect=RuntimeError("TIA no responde")
        )

        with pytest.raises(RuntimeError, match="TIA no responde"):
            asyncio.run(
                gateway_with_cache.update_user_constant_name(
                    plc_name="PLC1",
                    table_name="UserConstants",
                    current_name="OLD",
                    new_name="NEW",
                )
            )

        # Las caches NO se invalidaron (la operacion fallo).
        assert gateway_with_cache._cache != {}
        assert "plcs" in gateway_with_cache._cache


class TestDeleteUserConstantCacheInvalidation:
    """``delete_user_constant`` invalida ``_cache`` y ``_bloques_cache`` (fix A4)."""

    def test_delete_invalida_cache_global(
        self, gateway_with_cache: TIAProcessGateway,
    ) -> None:
        """Tras un delete exitoso, ``_cache == {}`` y ``_bloques_cache == {}``.

        Caso real (audit A4): el operario borra una constante
        obsoleta. Sin invalidacion, ``get_user_constants``
        devolveria la lista con la constante borrada todavia
        presente.
        """
        import asyncio

        asyncio.run(
            gateway_with_cache.delete_user_constant(
                plc_name="PLC1",
                table_name="UserConstants",
                constant_name="OBSOLETE_CONST",
            )
        )

        gateway_with_cache._dispatch_worker.assert_called_once()
        call = gateway_with_cache._dispatch_worker.call_args
        assert call.args[0] == "delete_user_constant"

        # Las caches se invalidaron.
        assert gateway_with_cache._cache == {}
        assert gateway_with_cache._bloques_cache == {}

    def test_delete_no_invalida_si_dispatch_falla(
        self, gateway_with_cache: TIAProcessGateway,
    ) -> None:
        """Si el dispatch lanza, NO se invalidan las caches (consistente con rename)."""
        import asyncio

        gateway_with_cache._dispatch_worker = AsyncMock(
            side_effect=RuntimeError("TIA error")
        )

        with pytest.raises(RuntimeError):
            asyncio.run(
                gateway_with_cache.delete_user_constant(
                    plc_name="PLC1",
                    table_name="UserConstants",
                    constant_name="X",
                )
            )

        # Las caches NO se invalidaron.
        assert gateway_with_cache._cache != {}


class TestUpdateUserConstantValueStillInvalidates:
    """Sanity check: ``update_user_constant_value`` sigue invalidando caches (no-op en A4).

    El fix A4 NO toco ``update_user_constant_value``: ese
    metodo ya invalidaba correctamente. Este test sirve de
    regression: si alguien rompe ese comportamiento en el
    futuro, el test lo detecta.
    """

    def test_value_update_invalida_cache(
        self, gateway_with_cache: TIAProcessGateway,
    ) -> None:
        """``update_user_constant_value`` sigue limpiando caches tras el OK."""
        import asyncio

        asyncio.run(
            gateway_with_cache.update_user_constant_value(
                plc_name="PLC1",
                table_name="UserConstants",
                constant_name="N_MAX_DISP_ED",
                new_value=42,
            )
        )

        assert gateway_with_cache._cache == {}
        assert gateway_with_cache._bloques_cache == {}
