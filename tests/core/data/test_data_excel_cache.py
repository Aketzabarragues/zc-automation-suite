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
from areas.alimentacion.data.data_dimensiones import (
    DataDimensionesPLC,
    DimensionesPLC,
)
from areas.alimentacion.data.data_entidades import Entidad
from core.data.data_excel_cache import DataExcelCache
from areas.alimentacion.data.data_parametros_int import DataParamIntPLC
from areas.alimentacion.data.data_parametros_real import DataParamRealPLC
from areas.alimentacion.data.data_procesos import DataProcesoPLC


def _cache_minimo() -> DataExcelCache:
    """Helper: un DataExcelCache valido con datos minimos."""
    return DataExcelCache(
        excel_path="/ruta/al/maestro.xlsx",
        excel_mtime_ns=1700000000_000_000_000,
        parsed_at=datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc),
        dispositivos={},
        n_max=DimensionesPLC(),
        plcs=(),
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
    assert cache.n_max.por_plc == ()
    assert cache.procesos == ()


def test_to_dict_shape_minimo():
    """``to_dict()`` emite las 10 keys del shape estable (multi-PLC)."""
    cache = _cache_minimo()
    snapshot = cache.to_dict()

    assert set(snapshot.keys()) == {
        "excel_path",
        "excel_mtime_ns",
        "parsed_at",
        "dispositivos",
        "n_max",
        "plcs",
        "procesos",
        "parametros_real",
        "parametros_int",
        "alarmas",
        "entidades",
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
    """``to_dict()`` serializa ``n_max`` con shape multi-PLC anidado."""
    cache = DataExcelCache(
        excel_path="x",
        excel_mtime_ns=0,
        parsed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        dispositivos={},
        n_max=DimensionesPLC(por_plc=(
            DataDimensionesPLC(plc_name="PLC1", extras={
                "N_MAX_DISP_ED": 15,
                "N_MAX_DISP_V": 20,
            }),
        )),
        plcs=(),
        procesos=(),
        parametros_real=(),
        parametros_int=(),
        alarmas=(),
        procesos_by_codigo=MappingProxyType({}),
        parametros_real_by_codigo=MappingProxyType({}),
        parametros_int_by_codigo=MappingProxyType({}),
    )

    snapshot = cache.to_dict()

    # Shape multi-PLC: {plc_name: {nmax_name: int}}.
    # ``N_MAX_ENTIDAD`` aparece con valor 0 si no se setea (back-compat).
    assert snapshot["n_max"] == {
        "PLC1": {
            "N_MAX_DISP_ED": 15,
            "N_MAX_DISP_V": 20,
            "N_MAX_ENTIDAD": 0,
        },
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
        n_max=DimensionesPLC(),
        plcs=(),
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


# ── Entidades ─────────────────────────────────────────────────


def test_entidades_default_es_tupla_vacia():
    """Si no se pasa ``entidades``, el cache lo deja como ``()``.

    Mantiene backward compat: tests existentes que construyen
    ``DataExcelCache(...)`` sin ``entidades=`` siguen funcionando.
    El loader lo rellenara con ``tuple(Entidad, ...)``.
    """
    cache = _cache_minimo()
    assert cache.entidades == ()


def test_entidades_se_puede_inyectar_explicitamente():
    """``entidades`` acepta cualquier ``tuple[Entidad, ...]``."""
    cache = DataExcelCache(
        excel_path="x",
        excel_mtime_ns=0,
        parsed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        dispositivos={},
        n_max=DimensionesPLC(),
        plcs=(),
        procesos=(),
        parametros_real=(),
        parametros_int=(),
        alarmas=(),
        entidades=(
            Entidad(numero=1, plc_name="PLC1", plc_tag="ent_001"),
            Entidad(numero=2, plc_name="PLC1", plc_tag="ent_002"),
        ),
        procesos_by_codigo=MappingProxyType({}),
        parametros_real_by_codigo=MappingProxyType({}),
        parametros_int_by_codigo=MappingProxyType({}),
    )
    assert len(cache.entidades) == 2
    assert cache.entidades[0].plc_tag == "ent_001"


def test_to_dict_entidades_via_asdict():
    """``to_dict()`` serializa ``entidades`` con la misma regla que las otras listas."""
    cache = DataExcelCache(
        excel_path="x",
        excel_mtime_ns=0,
        parsed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        dispositivos={},
        n_max=DimensionesPLC(),
        plcs=(),
        procesos=(),
        parametros_real=(),
        parametros_int=(),
        alarmas=(),
        entidades=(
            Entidad(
                numero=1,
                plc_name="PLC1",
                plc_tag="ent_001",
                descripcion="Valvula",
                plc_comentario="// slot 1",
            ),
        ),
        procesos_by_codigo=MappingProxyType({}),
        parametros_real_by_codigo=MappingProxyType({}),
        parametros_int_by_codigo=MappingProxyType({}),
    )
    snapshot = cache.to_dict()

    assert len(snapshot["entidades"]) == 1
    assert snapshot["entidades"][0]["numero"] == 1
    assert snapshot["entidades"][0]["plc_name"] == "PLC1"
    assert snapshot["entidades"][0]["plc_tag"] == "ent_001"
    assert snapshot["entidades"][0]["descripcion"] == "Valvula"
    assert snapshot["entidades"][0]["plc_comentario"] == "// slot 1"


def test_to_dict_entidades_vacia_sigue_siendo_lista():
    """``to_dict()`` con ``entidades=()`` emite ``[]`` (lista, no tupla)."""
    snapshot = _cache_minimo().to_dict()
    assert snapshot["entidades"] == []
    assert isinstance(snapshot["entidades"], list)


def test_entidades_multi_PLC_en_una_lista():
    """El cache guarda TODAS las entidades multi-PLC; el filtrado por
    PLC vive en el ``excel_active`` derivado, no aqui."""
    cache = DataExcelCache(
        excel_path="x",
        excel_mtime_ns=0,
        parsed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        dispositivos={},
        n_max=DimensionesPLC(),
        plcs=(),
        procesos=(),
        parametros_real=(),
        parametros_int=(),
        alarmas=(),
        entidades=(
            Entidad(numero=1, plc_name="PLC1", plc_tag="a"),
            Entidad(numero=2, plc_name="PLC2", plc_tag="b"),
            Entidad(numero=3, plc_name="PLC1", plc_tag="c"),
        ),
        procesos_by_codigo=MappingProxyType({}),
        parametros_real_by_codigo=MappingProxyType({}),
        parametros_int_by_codigo=MappingProxyType({}),
    )
    assert [e.plc_name for e in cache.entidades] == ["PLC1", "PLC2", "PLC1"]
