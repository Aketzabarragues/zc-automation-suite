"""Tests del helper ``with_plc`` (multi-PLC, sept-2026).

``with_plc(state, plc_name)``:
  - setea ``state.selected_plc = plc_name``.
  - regenera ``state.excel_cache_active`` filtrado por ese PLC.
  - es idempotente: si el PLC ya esta activo, no hace nada.

Si ``plc_name`` es vacio, emite un warning y NO modifica nada
(el caller deberia pasar un plc_name valido). Si no hay
``excel_cache_full`` cargado, NO falla: simplemente deja el cache
activo tal como estaba (el caller es responsable de la precondicion).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.helpers.tia.with_plc import with_plc


def _make_state(
    full: object | None = object(),
    active: object | None = None,
    selected: str = "",
) -> MagicMock:
    """Mock ``AppState`` con caches y PLC activo inyectados."""
    state = MagicMock()
    state.excel_cache_full = full
    state.excel_cache_active = active
    state.selected_plc = selected
    return state


def test_with_plc_setea_selected_plc_y_regenera_cache():
    """Caso feliz: setea selected_plc y regenera el cache activo."""
    full = MagicMock(name="full_cache")
    state = _make_state(full=full, selected="")

    with patch("core.runtime.filter_excel_cache.filter_cache_by_plc") as filt:
        filt.return_value = "FILTERED"
        with_plc(state, "PLC1")

    assert state.selected_plc == "PLC1"
    assert state.excel_cache_active == "FILTERED"
    filt.assert_called_once_with(full, "PLC1")


def test_with_plc_idempotente_si_mismo_plc():
    """Llamar dos veces con el mismo PLC no regenera el cache."""
    state = _make_state(full=object(), active="ALREADY", selected="PLC1")
    with patch("core.runtime.filter_excel_cache.filter_cache_by_plc") as filt:
        with_plc(state, "PLC1")
        # selected_plc ya era "PLC1": no se regenera.
        filt.assert_not_called()
    # El cache activo queda intacto (no se sobreescribe).
    assert state.excel_cache_active == "ALREADY"


def test_with_plc_cambia_de_plc_regenera_cache():
    """Cambiar de PLC regenera el cache activo."""
    full = MagicMock(name="full_cache")
    state = _make_state(full=full, active="ACTIVE_OLD", selected="PLC1")
    with patch("core.runtime.filter_excel_cache.filter_cache_by_plc") as filt:
        filt.return_value = "ACTIVE_NEW"
        with_plc(state, "PLC2")

    assert state.selected_plc == "PLC2"
    assert state.excel_cache_active == "ACTIVE_NEW"
    filt.assert_called_once_with(full, "PLC2")


def test_with_plc_sin_full_no_regenera():
    """Si no hay cache completo, no regenera (no falla)."""
    state = _make_state(full=None, active=None, selected="")
    with patch("core.runtime.filter_excel_cache.filter_cache_by_plc") as filt:
        with_plc(state, "PLC1")
        filt.assert_not_called()
    # selected_plc SI se setea (eso SI es responsabilidad del helper).
    assert state.selected_plc == "PLC1"


def test_with_plc_plc_vacio_no_modifica():
    """plc_name vacio: warning y return, sin tocar el estado."""
    state = _make_state(full=object(), active="ACTIVE", selected="PLC_PREV")
    with patch("core.runtime.filter_excel_cache.filter_cache_by_plc") as filt:
        with_plc(state, "")
        filt.assert_not_called()
    # selected_plc NO cambia (helper lo deja como estaba).
    assert state.selected_plc == "PLC_PREV"
    assert state.excel_cache_active == "ACTIVE"