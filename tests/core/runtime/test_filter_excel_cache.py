"""Tests del helper ``filter_cache_by_plc``.

Cobertura:
  - ``cache=None`` -> ``None`` (no rompe).
  - ``plc_name=""`` -> cache sin filtrar (modo "sin filtro": el
    cache activo coincide con el completo; el caller es responsable
    de pasar plc_name valido si quiere filtrar).
  - ``plc_name="PLC1"`` -> solo filas con ``plc_name == "PLC1"``.
  - Las listas informativas (``plcs``, lookups, ``excel_path``) NO se filtran.
  - El cache original NO se muta (es frozen, ``dataclasses.replace``
    crea una copia).
  - Dispositivos sin ``plc_name`` (DTO legacy) NO matchean ningun PLC:
    si bien es comportamiento intencional del strict equality D11.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping

import pytest

from core.runtime.filter_excel_cache import filter_cache_by_plc


# ── DTOs fake con plc_name ──────────────────────────────────────────


@dataclass(frozen=True)
class _FakeDispo:
    numero: int
    plc_name: str = ""


@dataclass(frozen=True)
class _FakeProc:
    uid: int
    plc_name: str = ""


@dataclass(frozen=True)
class _FakeAlarma:
    uid: str
    plc_name: str = ""


@dataclass(frozen=True)
class _FakeParam:
    uid: str
    plc_name: str = ""


@dataclass(frozen=True)
class _FakeDimPLC:
    plc_name: str
    extras: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class _FakeDims:
    por_plc: tuple = ()


@dataclass(frozen=True)
class _FakeDataPLC:
    uid: int
    plc: str


@dataclass(frozen=True)
class _FakeCache:
    """Replica minimalista de DataExcelCache para tests."""

    excel_path: str
    excel_mtime_ns: int
    parsed_at: datetime
    dispositivos: dict
    n_max: _FakeDims
    plcs: tuple
    procesos: tuple
    parametros_real: tuple
    parametros_int: tuple
    alarmas: tuple
    procesos_by_codigo: Mapping = field(default_factory=dict)
    parametros_real_by_codigo: Mapping = field(default_factory=dict)
    parametros_int_by_codigo: Mapping = field(default_factory=dict)
    software_parsers_implemented: bool = True


# ── Helpers ─────────────────────────────────────────────────────────


def _make_cache(plcs_in_excel=("PLC1", "PLC2")):
    """Cache con 2 PLCs y disp + procesos + alarmas + N_MAX distribuidos."""
    return _FakeCache(
        excel_path="C:/fake.xlsx",
        excel_mtime_ns=1700000000,
        parsed_at=datetime(2026, 9, 30),
        dispositivos={
            "ed": (
                _FakeDispo(numero=1, plc_name="PLC1"),
                _FakeDispo(numero=2, plc_name="PLC2"),
                _FakeDispo(numero=3, plc_name="PLC1"),
                _FakeDispo(numero=4, plc_name="PLC2"),
            ),
            "ea": (
                _FakeDispo(numero=1, plc_name="PLC1"),
                _FakeDispo(numero=2, plc_name="PLC2"),
            ),
        },
        n_max=_FakeDims(por_plc=(
            _FakeDimPLC(plc_name="PLC1", extras={"N_MAX_DISP_ED": 50}),
            _FakeDimPLC(plc_name="PLC2", extras={"N_MAX_DISP_ED": 200}),
        )),
        plcs=(
            _FakeDataPLC(uid=0, plc="PLC1"),
            _FakeDataPLC(uid=1, plc="PLC2"),
        ),
        procesos=(
            _FakeProc(uid=0, plc_name="PLC1"),
            _FakeProc(uid=100, plc_name="PLC2"),
            _FakeProc(uid=0, plc_name="PLC1"),
        ),
        parametros_real=(
            _FakeParam(uid="PLC1_PR_0", plc_name="PLC1"),
            _FakeParam(uid="PLC2_PR_0", plc_name="PLC2"),
        ),
        parametros_int=(
            _FakeParam(uid="PLC1_PI_0", plc_name="PLC1"),
            _FakeParam(uid="PLC2_PI_0", plc_name="PLC2"),
        ),
        alarmas=(
            _FakeAlarma(uid="PLC1_AL_0", plc_name="PLC1"),
            _FakeAlarma(uid="PLC2_AL_0", plc_name="PLC2"),
            _FakeAlarma(uid="PLC1_AL_1", plc_name="PLC1"),
        ),
    )


# ── Tests ───────────────────────────────────────────────────────────


def test_cache_none_devuelve_none():
    """``cache=None`` -> ``None`` (no rompe)."""
    assert filter_cache_by_plc(None, "PLC1") is None
    assert filter_cache_by_plc(None, "") is None


def test_plc_name_vacio_devuelve_cache_sin_filtrar():
    """``plc_name=""`` -> cache sin filtrar (modo sin filtro)."""
    cache = _make_cache()
    result = filter_cache_by_plc(cache, "")
    # Mismo cache (no se duplica si no hay filtro).
    assert result is cache
    # Dispositivos sin filtrar.
    assert len(result.dispositivos["ed"]) == 4
    assert len(result.dispositivos["ea"]) == 2


def test_filtra_dispositivos_por_plc():
    """``plc_name="PLC1"`` -> solo filas con ``plc_name == "PLC1"``."""
    cache = _make_cache()
    result = filter_cache_by_plc(cache, "PLC1")
    assert len(result.dispositivos["ed"]) == 2
    assert all(d.plc_name == "PLC1" for d in result.dispositivos["ed"])
    assert len(result.dispositivos["ea"]) == 1
    assert result.dispositivos["ea"][0].plc_name == "PLC1"


def test_filtra_procesos_por_plc():
    """``procesos`` filtrado por plc_name."""
    cache = _make_cache()
    result = filter_cache_by_plc(cache, "PLC1")
    assert len(result.procesos) == 2
    assert all(p.plc_name == "PLC1" for p in result.procesos)
    # PLC2 solo tiene 1 fila en el fake.
    result_p2 = filter_cache_by_plc(cache, "PLC2")
    assert len(result_p2.procesos) == 1


def test_filtra_parametros_y_alarmas_por_plc():
    """``parametros_real/int/alarmas`` filtrados por plc_name."""
    cache = _make_cache()
    result = filter_cache_by_plc(cache, "PLC1")
    assert len(result.parametros_real) == 1
    assert result.parametros_real[0].plc_name == "PLC1"
    assert len(result.parametros_int) == 1
    assert len(result.alarmas) == 2


def test_filtra_n_max_por_plc():
    """``n_max.por_plc`` se filtra al PLC seleccionado."""
    cache = _make_cache()
    result = filter_cache_by_plc(cache, "PLC1")
    assert len(result.n_max.por_plc) == 1
    assert result.n_max.por_plc[0].plc_name == "PLC1"
    assert result.n_max.por_plc[0].extras == {"N_MAX_DISP_ED": 50}

    result_p2 = filter_cache_by_plc(cache, "PLC2")
    assert result_p2.n_max.por_plc[0].extras == {"N_MAX_DISP_ED": 200}


def test_plcs_informativos_no_se_filtran():
    """``plcs`` (lista informativa del Excel) NO se filtra."""
    cache = _make_cache()
    result = filter_cache_by_plc(cache, "PLC1")
    assert len(result.plcs) == 2
    assert result.plcs[0].plc == "PLC1"
    assert result.plcs[1].plc == "PLC2"


def test_cache_original_no_se_muta():
    """El cache original NO se muta (frozen + dataclasses.replace)."""
    cache = _make_cache()
    original_ed_count = len(cache.dispositivos["ed"])
    original_n_max_count = len(cache.n_max.por_plc)
    filter_cache_by_plc(cache, "PLC1")
    # Cache intacto.
    assert len(cache.dispositivos["ed"]) == original_ed_count
    assert len(cache.n_max.por_plc) == original_n_max_count


def test_plc_inexistente_devuelve_contenedores_vacios():
    """plc_name que no existe -> todos los contenedores vacios, plcs intacto."""
    cache = _make_cache()
    result = filter_cache_by_plc(cache, "PLC_FANTASMA")
    assert result.dispositivos["ed"] == ()
    assert result.dispositivos["ea"] == ()
    assert result.procesos == ()
    assert result.n_max.por_plc == ()
    assert len(result.plcs) == 2  # informativa, no se filtra


def test_excel_path_y_mtime_se_preservan():
    """``excel_path``, ``excel_mtime_ns``, ``parsed_at`` se preservan."""
    cache = _make_cache()
    result = filter_cache_by_plc(cache, "PLC1")
    assert result.excel_path == "C:/fake.xlsx"
    assert result.excel_mtime_ns == 1700000000
    assert result.parsed_at == datetime(2026, 9, 30)


def test_filtra_disp_sin_plc_name_como_vacios():
    """DTOs sin ``plc_name`` no matchean ningun PLC (strict equality D11).

    Si el Excel tiene disp legacy sin plc_name, quedan fuera del
    filtro. La SPA exige que cada disp lleve su ``plc_name`` (regla
    multi-PLC); un Excel con DTOs legacy esta mal formado.
    """
    cache = _FakeCache(
        excel_path="x", excel_mtime_ns=0, parsed_at=datetime(2026, 1, 1),
        dispositivos={
            "ed": (
                _FakeDispo(numero=1, plc_name=""),
                _FakeDispo(numero=2, plc_name="PLC1"),
            ),
        },
        n_max=_FakeDims(),
        plcs=(),
        procesos=(),
        parametros_real=(),
        parametros_int=(),
        alarmas=(),
    )
    result = filter_cache_by_plc(cache, "PLC1")
    # Solo el de PLC1 entra; el legacy queda fuera.
    assert len(result.dispositivos["ed"]) == 1
    assert result.dispositivos["ed"][0].plc_name == "PLC1"
