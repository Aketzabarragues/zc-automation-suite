"""Tests de ``DataExcelCache``.

Cobertura:
  - Construccion basica con los campos requeridos.
  - ``to_dict()`` shape estable, ``parsed_at`` en ISO-8601.
  - ``to_dict()`` omite los lookups precomputados.
  - ``to_dict()`` serializa ``n_max`` con nombres canonicos de TIA.
  - ``to_dict()`` serializa los 4 listas via ``dataclasses.asdict``.
  - ``frozen=True``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from areas.alimentacion.data.data_alarmas import DataAlarmaPLC
from areas.alimentacion.data.data_dispositivos import DispED
from areas.alimentacion.data.data_dimensiones import DimensionesDispositivos
from areas.alimentacion.data.data_ExcelCache import DataExcelCache
from areas.alimentacion.data.data_ParametrosInt import DataParamIntPLC
from areas.alimentacion.data.data_ParametrosReal import DataParamRealPLC
from areas.alimentacion.data.data_Procesos import DataProcesoPLC


def _cache_minimo() -> DataExcelCache:
    """Helper: un DataExcelCache valido con datos minimos."""
    return DataExcelCache(
        excel_path="/ruta/al/maestro.xlsx",
        excel_mtime_ns=1700000000_000_000_000,
        parsed_at=datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc),
        dispositivos={},
        n_max=DimensionesDispositivos(),
        procesos=(),
        parametros_real=(),
        parametros_int=(),
        alarmas=(),
        procesos_by_codigo=MappingProxyType({}),
        parametros_real_by_codigo=MappingProxyType({}),
        parametros_int_by_codigo=MappingProxyType({}),
    )


def test_construccion_minima():
    """DataExcelCache acepta los 14 campos minimos."""
    cache = _cache_minimo()

    assert cache.excel_path == "/ruta/al/maestro.xlsx"
    assert cache.excel_mtime_ns == 1700000000_000_000_000
    assert cache.software_parsers_implemented is True
    assert dict(cache.n_max.extras) == {}
    assert cache.procesos == ()


def test_to_dict_shape_minimo():
    """``to_dict()`` emite las 7 keys del shape estable."""
    cache = _cache_minimo()
    snapshot = cache.to_dict()

    assert set(snapshot.keys()) == {
        "excel_path",
        "excel_mtime_ns",
        "parsed_at",
        "n_max",
        "procesos",
        "parametros_real",
        "parametros_int",
        "alarmas",
        "software_parsers_implemented",
    }


def test_to_dict_parsed_at_iso_8601():
    """``parsed_at`` se serializa en formato ISO-8601."""
    cache = _cache_minimo()
    snapshot = cache.to_dict()

    assert isinstance(snapshot["parsed_at"], str)
    assert "T" in snapshot["parsed_at"]
    # El datetime original debe poder reconstruirse.
    assert snapshot["parsed_at"].startswith("2026-09-10T12:00:00")


def test_to_dict_omite_lookups():
    """``to_dict()`` NO serializa los 3 lookups precomputados (son derivables)."""
    cache = _cache_minimo()
    snapshot = cache.to_dict()

    assert "procesos_by_codigo" not in snapshot
    assert "parametros_real_by_codigo" not in snapshot
    assert "parametros_int_by_codigo" not in snapshot


def test_to_dict_n_max_via_to_api_dict():
    """``to_dict()`` serializa ``n_max`` con nombres canonicos de TIA."""
    cache = DataExcelCache(
        excel_path="x",
        excel_mtime_ns=0,
        parsed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        dispositivos={},
        n_max=DimensionesDispositivos(extras={
            "N_MAX_DISP_ED": 15,
            "N_MAX_DISP_V": 20,
        }),
        procesos=(),
        parametros_real=(),
        parametros_int=(),
        alarmas=(),
        procesos_by_codigo=MappingProxyType({}),
        parametros_real_by_codigo=MappingProxyType({}),
        parametros_int_by_codigo=MappingProxyType({}),
    )

    snapshot = cache.to_dict()

    assert snapshot["n_max"] == {
        "N_MAX_DISP_ED": 15,
        "N_MAX_DISP_V": 20,
    }


def test_to_dict_listas_via_asdict():
    """``to_dict()`` serializa cada elemento de las 4 listas via asdict."""
    proc = DataProcesoPLC(uid=1, nombre="P1", codigo="P1")
    preal = DataParamRealPLC(
        uid="PR_1_001", numero="001", proceso="P1", codigo="P1",
        num_db=3000, producto="L", tipo="T", descripcion="D",
        comentario_db="C", visibilidad="Si", num_lista=0, txt_lista="X",
    )
    pint = DataParamIntPLC(
        uid="PI_1_001", numero="001", proceso="P1", codigo="P1",
        num_db=3000, producto="L", tipo="T", descripcion="D",
        comentario_db="C", visibilidad="Si", num_lista=0, txt_lista="X",
    )
    alarma = DataAlarmaPLC(
        uid="AL_1_001", numero="001", proceso="P1", num_db=3001,
        descripcion="D", comentario_db="C",
    )

    cache = DataExcelCache(
        excel_path="x",
        excel_mtime_ns=0,
        parsed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        dispositivos={"ed": (DispED(1, "t", "c", "d", "u"),)},
        n_max=DimensionesDispositivos(),
        procesos=(proc,),
        parametros_real=(preal,),
        parametros_int=(pint,),
        alarmas=(alarma,),
        procesos_by_codigo=MappingProxyType({"P1": proc}),
        parametros_real_by_codigo=MappingProxyType({"P1": preal}),
        parametros_int_by_codigo=MappingProxyType({"P1": pint}),
    )

    snapshot = cache.to_dict()

    # Cada lista se serializa como un array de dicts (asdict).
    assert len(snapshot["procesos"]) == 1
    assert snapshot["procesos"][0]["uid"] == 1
    assert snapshot["procesos"][0]["codigo"] == "P1"

    assert len(snapshot["parametros_real"]) == 1
    assert snapshot["parametros_real"][0]["uid"] == "PR_1_001"
    assert snapshot["parametros_real"][0]["num_lista"] == 0

    assert len(snapshot["parametros_int"]) == 1
    assert snapshot["parametros_int"][0]["uid"] == "PI_1_001"

    assert len(snapshot["alarmas"]) == 1
    assert snapshot["alarmas"][0]["uid"] == "AL_1_001"


def test_frozen_no_muta():
    """``frozen=True``: asignar un campo levanta ``FrozenInstanceError``."""
    from dataclasses import FrozenInstanceError

    cache = _cache_minimo()
    with pytest.raises(FrozenInstanceError):
        cache.excel_path = "/otro.xlsx"  # type: ignore[misc]
