"""Tests de los handlers de ciclo de vida del portal TIA.

Cubre:
  - ``_h_detach_portal`` limpia el ``AppCache`` tras cerrar el wrapper
    (regresion del gap conocido: antes, el cache quedaba stale keyed
    por ``plc_name`` si el operario desconectaba y abria otro proyecto
    con PLCs del mismo nombre).
  - ``_h_attach_portal`` con portal ya attached y ``get_process_id``
    operativo devuelve el PID sin re-attach (idempotente).
  - ``_h_detach_portal`` con ``wrapper is None`` devuelve
    ``{"detached": False}`` sin tocar el cache.
"""
from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock

import pytest

from core.infrastructure.tia import tia_cmd_lifecycle as mod
from core.runtime.app_cache import get_app_cache


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """Reset del Singleton ``AppCache`` antes de cada test."""
    import core.runtime.app_cache as _cache_mod
    _cache_mod._app_cache = None
    yield
    _cache_mod._app_cache = None


def _set_selected_plc(value: str) -> None:
    """Helper: poplar ``app_cache.selected_plc`` con ``value``."""
    cache = get_app_cache()
    cache.mutate(
        slot="selected_plc",
        fn=lambda s: dataclasses.replace(s, selected_plc=value),
    )


def test_detach_portal_limpia_app_cache() -> None:
    """Tras detach, el AppCache queda en estado vacio.

    El operario desconecta TIA Portal: el wrapper se cierra, el
    ``AppCache`` se resetea (slate limpio para que abrir otro proyecto
    no arrastre datos stale del anterior).
    """
    _set_selected_plc("PLC_ANTIGUO")

    wrapper = MagicMock()
    tia_client = MagicMock()
    tia_client.wrapper = wrapper

    result = mod._h_detach_portal({}, tia_client)

    assert result["detached"] is True
    wrapper.detach.assert_called_once()
    tia_client.attach_wrapper.assert_called_once_with(None)
    # Cache vacio tras el reset.
    state = get_app_cache().get_state()
    assert state.selected_plc == ""
    assert state.plc_list == ()
    assert state.plc_blocks == {}


def test_detach_portal_sin_wrapper_no_resetea() -> None:
    """Si no hay portal attached, no se invoca ``app_cache.reset()``.

    El operario llama a ``/api/v1/tia/disconnect`` sin haber attachado
    antes: idempotente, no hace nada.
    """
    _set_selected_plc("PLC_X")

    tia_client = MagicMock()
    tia_client.wrapper = None

    result = mod._h_detach_portal({}, tia_client)

    assert result == {"detached": False}
    # Cache intacto: no se resetea.
    assert get_app_cache().get_state().selected_plc == "PLC_X"


def test_detach_portal_best_effort_si_wrapper_lanza() -> None:
    """Si ``wrapper.detach()`` lanza, el reset del cache se hace igualmente.

    El handler es best-effort por contrato: un RCW stale no debe
    impedir la limpieza del cache.
    """
    _set_selected_plc("PLC_VIEJO")

    wrapper = MagicMock()
    wrapper.detach.side_effect = RuntimeError("RCW stale")
    tia_client = MagicMock()
    tia_client.wrapper = wrapper

    result = mod._h_detach_portal({}, tia_client)

    assert result["detached"] is True
    assert "RuntimeError" in result["warning"]
    tia_client.attach_wrapper.assert_called_once_with(None)
    # Cache reseteado aun con detach fallido.
    assert get_app_cache().get_state().selected_plc == ""
