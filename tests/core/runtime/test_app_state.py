"""Tests de ``AppState`` (transversal en core/runtime).

Cobertura (sept-2026, multi-PLC):
  - ``selected_plc`` default vacio (modo legacy).
  - ``get_devices`` filtra por ``selected_plc`` (strict equality sobre ``plc_name``).
  - ``selected_plc = ''`` -> lista completa (back-compat).
  - ``reset()`` limpia ``selected_plc``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from core.runtime.app_state import AppState


# ---------------------------------------------------------------------------
# Test fixtures: dispositivos congelados con plc_name
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FakeDispo:
    """Dispo minimo para tests de filtrado (frozen=True)."""
    numero: int
    plc_name: str = ""
    descripcion: str = field(default="")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_selected_plc_default_vacio():
    """Sin setear selected_plc, devuelve '' (modo legacy sin filtro)."""
    state = AppState()
    assert state.selected_plc == ""


def test_get_devices_sin_filtro_devuelve_todos():
    """selected_plc='' devuelve la lista completa (back-compat)."""
    state = AppState()
    state.set_devices("ed", [
        _FakeDispo(numero=1, plc_name="PLC1"),
        _FakeDispo(numero=2, plc_name="PLC2"),
        _FakeDispo(numero=3, plc_name="PLC1"),
    ])
    assert len(state.get_devices("ed")) == 3


def test_get_devices_filtra_por_selected_plc():
    """selected_plc='PLC1' devuelve solo los de PLC1."""
    state = AppState()
    state.set_devices("ed", [
        _FakeDispo(numero=1, plc_name="PLC1"),
        _FakeDispo(numero=2, plc_name="PLC2"),
        _FakeDispo(numero=3, plc_name="PLC1"),
    ])
    state.selected_plc = "PLC1"
    devices = state.get_devices("ed")
    assert len(devices) == 2
    assert all(d.plc_name == "PLC1" for d in devices)


def test_get_devices_sin_match_devuelve_lista_vacia():
    """selected_plc que no existe -> lista vacia."""
    state = AppState()
    state.set_devices("ed", [
        _FakeDispo(numero=1, plc_name="PLC1"),
        _FakeDispo(numero=2, plc_name="PLC2"),
    ])
    state.selected_plc = "PLC3_INEXISTENTE"
    assert state.get_devices("ed") == []


def test_get_devices_strict_equality():
    """Strict equality: 'PLC1' != 'plc1' (case-sensitive)."""
    state = AppState()
    state.set_devices("ed", [
        _FakeDispo(numero=1, plc_name="PLC1"),
        _FakeDispo(numero=2, plc_name="plc1"),  # lowercase
    ])
    state.selected_plc = "PLC1"
    devices = state.get_devices("ed")
    # Solo el primero (plc_name="PLC1") matchea.
    assert len(devices) == 1
    assert devices[0].plc_name == "PLC1"


def test_get_devices_legacy_dto_sin_plc_name():
    """DTOs legacy sin plc_name (atributo no existe) -> matchea solo si
    selected_plc='' (modo legacy). Con selected_plc != '', se descartan."""
    @dataclass(frozen=True)
    class _LegacyDispo:
        numero: int
        # NO tiene plc_name (atributo legacy).

    state = AppState()
    state.set_devices("ed", [_LegacyDispo(numero=1)])
    # Modo legacy (selected_plc=''): todos visibles.
    assert len(state.get_devices("ed")) == 1
    # Modo multi-PLC (selected_plc='PLC1'): todos descartados.
    state.selected_plc = "PLC1"
    assert state.get_devices("ed") == []


def test_reset_limpia_selected_plc():
    """reset() pone selected_plc='' y vacia dispositivos."""
    state = AppState()
    state.set_devices("ed", [_FakeDispo(numero=1, plc_name="PLC1")])
    state.selected_plc = "PLC1"
    state.reset()
    assert state.selected_plc == ""
    assert state.get_devices("ed") == []


def test_cambio_selected_plc_en_runtime():
    """Cambiar selected_plc en runtime re-filtra automaticamente."""
    state = AppState()
    state.set_devices("ed", [
        _FakeDispo(numero=1, plc_name="PLC1"),
        _FakeDispo(numero=2, plc_name="PLC2"),
    ])
    state.selected_plc = "PLC1"
    assert len(state.get_devices("ed")) == 1
    state.selected_plc = "PLC2"
    assert len(state.get_devices("ed")) == 1
    assert state.get_devices("ed")[0].plc_name == "PLC2"
    state.selected_plc = ""
    assert len(state.get_devices("ed")) == 2


# ---------------------------------------------------------------------------
# Tests de excel_cache_full / excel_cache_active (multi-PLC, sept-2026)
# ---------------------------------------------------------------------------


def test_excel_cache_full_y_active_default_none():
    """Defaults: ambos caches None (no hay Excel cargado)."""
    state = AppState()
    assert state.excel_cache_full is None
    assert state.excel_cache_active is None


def test_excel_cache_full_se_puebla_directamente():
    """``excel_cache_full`` se setea por el codigo que carga el Excel."""
    state = AppState()
    fake = object()
    state.excel_cache_full = fake
    assert state.excel_cache_full is fake
    # excel_cache_active sigue None hasta que se filtre.
    assert state.excel_cache_active is None


def test_excel_cache_active_es_distinto_de_full_si_hay_filtro():
    """Si hay ``selected_plc`` set, ``excel_cache_active`` es la version
    filtrada de ``excel_cache_full`` (no la misma instancia)."""
    state = AppState()
    # Construimos un cache falso solo para verificar identidad.
    state.excel_cache_full = "FULL"
    state.selected_plc = "PLC1"
    state.excel_cache_active = "ACTIVE_FOR_PLC1"
    assert state.excel_cache_active == "ACTIVE_FOR_PLC1"
    assert state.excel_cache_full != state.excel_cache_active


def test_reset_limpia_solo_selected_plc_no_los_caches():
    """``reset()`` limpia ``selected_plc`` y ``_dispositivos`` pero NO
    toca ``excel_cache_full``/``excel_cache_active``: el cache del
    Excel sobrevive al reset (es data, no estado de operacion)."""
    state = AppState()
    state.excel_cache_full = "FULL"
    state.excel_cache_active = "ACTIVE"
    state.reset()
    assert state.selected_plc == ""
    # Los caches siguen (la SPA los ve aunque no haya operacion en curso).
    assert state.excel_cache_full == "FULL"
    assert state.excel_cache_active == "ACTIVE"