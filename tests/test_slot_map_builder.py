"""Tests de ``slot_map_builder``.

Cubre la logica de mapeo de AppState (comentario_db) a slot_maps
que se envia a TIA, con la config de DBs del ConfigManager.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from areas.alimentacion.application.slot_map_builder import (
    build_slot_map_for_hw,
    build_slot_maps,
)


# Mutable a nivel de módulo: cada test lo sobrescribe según su escenario.
devices_by_hw: dict[str, list] = {}


class _FakeDevice:
    def __init__(self, numero: int, comentario_db: str = "") -> None:
        self.numero = numero
        self.comentario_db = comentario_db


@pytest.fixture
def app_state() -> MagicMock:
    state = MagicMock()
    state.all_devices.return_value = [_FakeDevice(1, "X")]
    state.get_devices.side_effect = lambda hw: devices_by_hw.get(hw, [])
    return state


@pytest.fixture
def config_manager() -> MagicMock:
    cm = MagicMock()
    cm.list_hw_types_active.return_value = ["ed", "ea", "sa", "v", "m", "m_vf"]
    cm.get_tia_folder_dispositivos.return_value = "2000_Dispositivos"
    cm.get_dispositivo_config.side_effect = lambda hw: MagicMock(
        db_name=f"DB20{ord(hw[0]):02d}_{hw.upper()}",
        db_array_name=hw.upper(),
    )
    return cm


# ── build_slot_map_for_hw ─────────────────────────────────────────────


def test_build_slot_map_for_hw_slot_0_siempre_no_usar(app_state: MagicMock) -> None:
    """El slot 0 siempre esta con texto 'NO USAR'."""
    slot_map = build_slot_map_for_hw(app_state, "ed")
    assert slot_map[0] == "NO USAR"


def test_build_slot_map_for_hw_ignora_numero_cero_o_duplicado(
    app_state: MagicMock,
) -> None:
    """Devices con numero==0 o duplicados se ignoran (warning en logs)."""
    global devices_by_hw
    devices_by_hw = {
        "ed": [
            _FakeDevice(0, "ignorar"),  # numero=0 -> ignorar
            _FakeDevice(1, "OK"),
            _FakeDevice(1, "duplicado"),  # numero=1 repetido -> ignorar
            _FakeDevice(2, "OK2"),
        ]
    }
    slot_map = build_slot_map_for_hw(app_state, "ed")
    assert slot_map[0] == "NO USAR"
    assert slot_map[1] == "OK"
    assert slot_map[2] == "OK2"
    assert "ignorar" not in slot_map.values()
    assert "duplicado" not in slot_map.values()


def test_build_slot_map_for_hw_vacio_retorna_solo_slot_0(
    app_state: MagicMock,
) -> None:
    """Si no hay devices, el slot map solo tiene el slot 0."""
    global devices_by_hw
    devices_by_hw = {"ed": []}
    slot_map = build_slot_map_for_hw(app_state, "ed")
    assert slot_map == {0: "NO USAR"}


# ── build_slot_maps ────────────────────────────────────────────────────


def test_build_slot_maps_retorna_los_4_dicts(app_state: MagicMock, config_manager: MagicMock) -> None:
    """Retorna tupla (slot_maps, db_names, db_array_names, warnings)."""
    global devices_by_hw
    devices_by_hw = {"ed": [_FakeDevice(1, "Bomba 1")]}
    slot_maps, db_names, db_array_names, warnings = build_slot_maps(
        app_state, config_manager
    )
    assert len(slot_maps) == 6
    assert len(db_names) == 6
    assert len(db_array_names) == 6
    assert warnings == []


def test_build_slot_maps_warning_si_tipo_sin_config(
    app_state: MagicMock, config_manager: MagicMock
) -> None:
    """Un hw_type sin config TIA se omite y se reporta como warning."""
    config_manager.list_hw_types_active.return_value = ["ed", "fantasma"]
    config_manager.get_dispositivo_config.side_effect = lambda hw: (
        MagicMock(db_name=f"DB_{hw}", db_array_name=hw.upper())
        if hw == "ed"
        else None
    )
    global devices_by_hw
    devices_by_hw = {"ed": [_FakeDevice(1, "X")]}

    slot_maps, db_names, db_array_names, warnings = build_slot_maps(
        app_state, config_manager
    )
    # 'ed' presente, 'fantasma' omitido.
    assert "ed" in slot_maps
    assert "fantasma" not in slot_maps
    assert "ed" in db_names
    assert "fantasma" not in db_names
    # Warning reportado.
    assert any("fantasma" in w for w in warnings)


def test_build_slot_maps_no_hay_gap_entre_slot_y_numero(
    app_state: MagicMock, config_manager: MagicMock
) -> None:
    """El slot map es denso en slot_map[i] == comentario_db del device
    con numero==i. No rellena gaps (los slots sin device no aparecen).
    """
    global devices_by_hw
    devices_by_hw = {"ed": [_FakeDevice(5, "Bomba 5")]}
    slot_maps, _, _, _ = build_slot_maps(app_state, config_manager)
    # Solo hay slot 0 y slot 5. No hay slot 1, 2, 3, 4.
    assert 0 in slot_maps["ed"]
    assert 5 in slot_maps["ed"]
    for missing in (1, 2, 3, 4):
        assert missing not in slot_maps["ed"]
