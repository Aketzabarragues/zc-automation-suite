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


# ---------------------------------------------------------------------------
# Regeneracion de excel_cache_active (sept-2026)
# ---------------------------------------------------------------------------


def test_with_plc_regenera_excel_cache_active():
    """``with_plc`` regenera ``excel_cache_active`` desde ``excel_cache_full``
    filtrado por el nuevo plc_name.
    """
    from dataclasses import dataclass, field
    from datetime import datetime

    @dataclass(frozen=True)
    class _Dispo:
        numero: int
        plc_name: str = ""

    @dataclass(frozen=True)
    class _DimPLC:
        plc_name: str
        extras: dict = field(default_factory=dict)

    @dataclass(frozen=True)
    class _Dims:
        por_plc: tuple = ()

    @dataclass(frozen=True)
    class _FakeCache:
        excel_path: str
        excel_mtime_ns: int
        parsed_at: datetime
        dispositivos: dict
        n_max: _Dims
        plcs: tuple
        procesos: tuple
        parametros_real: tuple
        parametros_int: tuple
        alarmas: tuple

    cache = _FakeCache(
        excel_path="x", excel_mtime_ns=0, parsed_at=datetime(2026, 1, 1),
        dispositivos={
            "ed": (
                _Dispo(numero=1, plc_name="PLC1"),
                _Dispo(numero=2, plc_name="PLC2"),
            ),
        },
        n_max=_Dims(por_plc=(
            _DimPLC(plc_name="PLC1", extras={"N_MAX_DISP_ED": 50}),
            _DimPLC(plc_name="PLC2", extras={"N_MAX_DISP_ED": 200}),
        )),
        plcs=(),
        procesos=(),
        parametros_real=(),
        parametros_int=(),
        alarmas=(),
    )

    state = AppState()
    state.excel_cache_full = cache
    # Sin filtro: active == full (filter_cache_by_plc devuelve el mismo cache
    # si plc_name="").
    state.excel_cache_active = cache
    # Cambiamos al PLC1.
    with_plc(state, "PLC1")
    assert state.selected_plc == "PLC1"
    assert state.excel_cache_active is not cache  # copia filtrada
    assert len(state.excel_cache_active.dispositivos["ed"]) == 1
    assert state.excel_cache_active.dispositivos["ed"][0].plc_name == "PLC1"
    # N_MAX del PLC1 solamente.
    assert len(state.excel_cache_active.n_max.por_plc) == 1
    assert state.excel_cache_active.n_max.por_plc[0].extras == {"N_MAX_DISP_ED": 50}


def test_with_plc_idempotente_no_regenera_cache():
    """Llamar con el mismo plc_name NO regenera el cache (objeto identico)."""
    from dataclasses import dataclass, field
    from datetime import datetime

    @dataclass(frozen=True)
    class _Dispo:
        numero: int
        plc_name: str = ""

    @dataclass(frozen=True)
    class _Dims:
        por_plc: tuple = ()

    @dataclass(frozen=True)
    class _FakeCache:
        excel_path: str
        excel_mtime_ns: int
        parsed_at: datetime
        dispositivos: dict
        n_max: _Dims
        plcs: tuple
        procesos: tuple
        parametros_real: tuple
        parametros_int: tuple
        alarmas: tuple

    cache = _FakeCache(
        excel_path="x", excel_mtime_ns=0, parsed_at=datetime(2026, 1, 1),
        dispositivos={"ed": (_Dispo(numero=1, plc_name="PLC1"),)},
        n_max=_Dims(), plcs=(), procesos=(),
        parametros_real=(), parametros_int=(), alarmas=(),
    )
    state = AppState()
    state.excel_cache_full = cache
    state.excel_cache_active = cache
    with_plc(state, "PLC1")
    first = state.excel_cache_active
    # Segunda llamada con el mismo plc_name: no regenera.
    with_plc(state, "PLC1")
    assert state.excel_cache_active is first


def test_with_plc_cambio_plc_regenera_cache():
    """Cambiar de PLC1 a PLC2 regenera el cache."""
    state = AppState()
    from dataclasses import dataclass, field
    from datetime import datetime

    @dataclass(frozen=True)
    class _Dispo:
        numero: int
        plc_name: str = ""

    @dataclass(frozen=True)
    class _Dims:
        por_plc: tuple = ()

    @dataclass(frozen=True)
    class _FakeCache:
        excel_path: str
        excel_mtime_ns: int
        parsed_at: datetime
        dispositivos: dict
        n_max: _Dims
        plcs: tuple
        procesos: tuple
        parametros_real: tuple
        parametros_int: tuple
        alarmas: tuple

    cache = _FakeCache(
        excel_path="x", excel_mtime_ns=0, parsed_at=datetime(2026, 1, 1),
        dispositivos={
            "ed": (
                _Dispo(numero=1, plc_name="PLC1"),
                _Dispo(numero=2, plc_name="PLC2"),
            ),
        },
        n_max=_Dims(),
        plcs=(),
        procesos=(),
        parametros_real=(),
        parametros_int=(),
        alarmas=(),
    )
    state.excel_cache_full = cache
    with_plc(state, "PLC1")
    active_plc1 = state.excel_cache_active
    assert active_plc1.dispositivos["ed"][0].plc_name == "PLC1"
    with_plc(state, "PLC2")
    active_plc2 = state.excel_cache_active
    assert active_plc2 is not active_plc1
    assert active_plc2.dispositivos["ed"][0].plc_name == "PLC2"


def test_with_plc_sin_excel_cache_full_no_falla():
    """Si excel_cache_full es None (no se ha cargado Excel), with_plc no falla."""
    state = AppState()
    state.excel_cache_full = None
    state.excel_cache_active = None
    # No debe lanzar excepcion.
    with_plc(state, "PLC1")
    assert state.selected_plc == "PLC1"
    # excel_cache_active sigue None (nada que filtrar).
    assert state.excel_cache_active is None