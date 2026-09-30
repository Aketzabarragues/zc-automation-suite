"""Tests del helper ``with_plc`` (PR5, multi-PLC)."""
from __future__ import annotations

import logging

from core.helpers.tia.with_plc import with_plc
from core.runtime.app_state import AppState


def test_with_plc_setea_selected_plc():
    """with_plc setea selected_plc en el AppState."""
    state = AppState()
    with_plc(state, "PLC1")
    assert state.selected_plc == "PLC1"


def test_with_plc_idempotente():
    """Llamar con el mismo plc_name varias veces es no-op."""
    state = AppState()
    with_plc(state, "PLC1")
    with_plc(state, "PLC1")
    with_plc(state, "PLC1")
    assert state.selected_plc == "PLC1"


def test_with_plc_cambia_seleccion():
    """Llamar con otro plc_name cambia selected_plc."""
    state = AppState()
    with_plc(state, "PLC1")
    with_plc(state, "PLC2")
    assert state.selected_plc == "PLC2"


def test_with_plc_plc_vacio_no_modifica(caplog):
    """plc_name='' no modifica selected_plc (warning)."""
    state = AppState()
    state.selected_plc = "PLC1"
    with caplog.at_level(logging.WARNING):
        with_plc(state, "")
    assert state.selected_plc == "PLC1"
    assert "vacio" in caplog.text.lower()


def test_with_plc_filtra_get_devices():
    """with_plc activa el filtro de get_devices."""
    state = AppState()
    # Crear devices simulados con plc_name
    from dataclasses import dataclass
    @dataclass(frozen=True)
    class FakeDispo:
        numero: int
        plc_name: str = ""
    state.set_devices("ed", [
        FakeDispo(numero=1, plc_name="PLC1"),
        FakeDispo(numero=2, plc_name="PLC2"),
    ])
    # Sin filtro: ambos
    assert len(state.get_devices("ed")) == 2
    # Con filtro PLC1: solo 1
    with_plc(state, "PLC1")
    devices = state.get_devices("ed")
    assert len(devices) == 1
    assert devices[0].plc_name == "PLC1"