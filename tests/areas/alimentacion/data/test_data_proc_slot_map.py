"""Tests para ``areas.alimentacion.data.data_proc_slot_map.DataProcSlotMap``.

Fase 3, paso 3.2.9.  Cobertura:
  - defaults razonables (3 dicts, 3 strs, 2 strs, 2 dicts, 2 lists).
  - ``frozen=True``: no se puede mutar.
  - ``to_dict()`` shape estable: 12 keys.
  - ``to_dict()`` convierte los ``int`` slots a ``str`` (JSON-friendly).
  - copia defensiva en ``to_dict()``.
"""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from areas.alimentacion.data.data_proc_slot_map import (
    DataProcSlotMap,
    proc_build_slot_maps,
)
from core.runtime.app_state import AppState
from core.infrastructure.config.config_manager import ConfigManager
from core.data.data_block_cache import DataBloqueCache
from core.data.data_block_plc import DataBloquePLC


def test_defaults_vacios():
    """DataProcSlotMap() da todos los campos a su valor por defecto."""
    m = DataProcSlotMap()

    assert m.preal == {}
    assert m.pint == {}
    assert m.alm == {}
    assert m.db_param_name == ""
    assert m.db_alm_name == ""
    assert m.table_name == ""
    assert m.param_subpath == ""
    assert m.alm_subpath == ""
    assert m.nmax == {}
    assert m.nmax_names == {}
    assert m.missing_blocks == []
    assert m.warnings == []


def test_frozen_no_muta():
    """``frozen=True``: asignar un campo levanta ``FrozenInstanceError``."""
    from dataclasses import FrozenInstanceError

    m = DataProcSlotMap()
    with pytest.raises(FrozenInstanceError):
        m.db_param_name = "DB9999_X_PARAM"  # type: ignore[misc]


def test_to_dict_shape():
    """``to_dict()`` emite las 13 keys del shape estable (incluye satellites_by_array)."""
    m = DataProcSlotMap(
        preal={1: "real_1"},
        pint={1: "int_1"},
        alm={1: "alm_1"},
        db_param_name="DB3000_P1_PARAM",
        db_alm_name="DB3001_P1_ALM",
        table_name="1_P1",
    )
    snapshot = m.to_dict()

    assert set(snapshot.keys()) == {
        "preal", "pint", "alm",
        "db_param_name", "db_alm_name", "table_name",
        "table_present", "db_missing",
        "param_subpath", "alm_subpath",
        "nmax", "nmax_names",
        "missing_blocks", "warnings",
        "satellites_by_array",
    }

    # satellites_by_array expone el dict constante (tuplas -> listas).
    assert snapshot["satellites_by_array"] == {
        "preal": ["PReal_Vis", "Aux.PReal_ValorAnterior"],
        "pint": ["PInt_Vis", "Aux.PInt_ValorAnterior"],
        "alm": [],
    }


def test_proc_satellites_by_array_constant():
    """``PROC_SATELLITES_BY_ARRAY`` es la fuente unica de verdad."""
    from areas.alimentacion.data.data_proc_slot_map import (
        PROC_SATELLITES_BY_ARRAY,
    )

    assert PROC_SATELLITES_BY_ARRAY == {
        "preal": ("PReal_Vis", "Aux.PReal_ValorAnterior"),
        "pint": ("PInt_Vis", "Aux.PInt_ValorAnterior"),
        "alm": (),
    }


def test_default_satellites_by_array_reflects_constant():
    """``DataProcSlotMap()`` por defecto tiene los satellites de la constante."""
    from areas.alimentacion.data.data_proc_slot_map import (
        PROC_SATELLITES_BY_ARRAY,
    )
    m = DataProcSlotMap()
    assert m.satellites_by_array == PROC_SATELLITES_BY_ARRAY


def test_to_dict_convierte_slots_int_a_str():
    """``to_dict()`` convierte los ``int`` slots a ``str`` (JSON-friendly)."""
    m = DataProcSlotMap(
        preal={1: "real_1", 2: "real_2"},
        pint={1: "int_1"},
        alm={1: "alm_1", 5: "alm_5"},
    )
    snapshot = m.to_dict()

    assert snapshot["preal"] == {"1": "real_1", "2": "real_2"}
    assert snapshot["pint"] == {"1": "int_1"}
    assert snapshot["alm"] == {"1": "alm_1", "5": "alm_5"}


def test_to_dict_copia_defensiva():
    """``to_dict()`` hace copia defensiva: mutar el snapshot NO afecta al original."""
    m = DataProcSlotMap(
        preal={1: "real_1"},
        pint={1: "int_1"},
        nmax={"preal": 5},
        warnings=["w1"],
    )

    snapshot = m.to_dict()

    # Mutar el snapshot NO afecta al estado del DB.
    snapshot["preal"]["2"] = "MUTATED"
    snapshot["nmax"]["MUTATED"] = 0
    snapshot["warnings"].append("MUTATED")

    assert m.preal == {1: "real_1"}
    assert m.nmax == {"preal": 5}
    assert m.warnings == ["w1"]


def test_listas_entre_instancias_son_independientes():
    """``default_factory``: dos instancias no comparten listas ni dicts."""
    m1 = DataProcSlotMap()
    m2 = DataProcSlotMap()

    assert m1.preal is not m2.preal
    assert m1.missing_blocks is not m2.missing_blocks
    assert m1.warnings is not m2.warnings

    m1.missing_blocks.append("solo en m1")
    m1.warnings.append("solo en m1")
    assert m2.missing_blocks == []
    assert m2.warnings == []


# ─────────────────────────────────────────────────────────────────────
# Tests de ``proc_build_slot_maps``: cobertura de ``table_present``
# y ``db_missing`` segun el estado de la cache de bloques.
# ─────────────────────────────────────────────────────────────────────


@dataclass
class _FakeProc:
    uid: int = 100
    codigo: str = "CPR"
    nombre: str = "Compresor"
    preal: int = 3
    pint: int = 2
    alarmas: int = 1
    alm_hmi: int = 1


@dataclass
class _FakeParamRow:
    codigo: str = "CPR"
    numero: int = 1
    num_db: int = 100
    comentario_db: str = ""


@dataclass
class _FakeAlarmaRow:
    proceso: str = "Compresor"
    numero: int = 1
    num_db: int = 100
    comentario_db: str = ""


def _make_excel_cache(proc=None, params=None, ints=None, alarms=None) -> MagicMock:
    cache = MagicMock()
    cache.procesos = [proc or _FakeProc()]
    cache.parametros_real = list(params or [_FakeParamRow(comentario_db="real 1")])
    cache.parametros_int = list(ints or [_FakeParamRow(comentario_db="int 1")])
    cache.alarmas = list(alarms or [_FakeAlarmaRow(comentario_db="alm 1")])
    return cache


def _make_bloques_cache(blocks_present: set[str], tag_tables_present: set[str]) -> MagicMock:
    """``blocks_present`` y ``tag_tables_present`` son sets con nombres ya normalizados."""
    cache = MagicMock(spec=DataBloqueCache)
    cache.blocks = {n: MagicMock(spec=DataBloquePLC) for n in blocks_present}
    cache.tag_tables = {n: MagicMock(spec=DataBloquePLC) for n in tag_tables_present}
    return cache


def _make_config_manager() -> MagicMock:
    cfg = MagicMock(spec=ConfigManager)
    cfg.get_proc_nmax_suffixes.return_value = {
        "preal": "PREAL",
        "pint": "PINT",
        "alm": "ALM",
        "alm_hmi": "ALM_HMI",
    }
    return cfg


def _make_state_with_active(active_cache) -> AppState:
    """Construye un ``AppState`` con el cache activo del area seteado."""
    from core.runtime.excel_cache import excel_set_active
    from areas.alimentacion.state.area_cache import AlimentacionAreaCache
    state = AppState()
    state.app_cache.register_area("alimentacion", AlimentacionAreaCache())
    if active_cache is not None:
        excel_set_active(state.app_cache, "alimentacion", active_cache)
    return state


def test_proc_build_slot_maps_happy_path():
    """Tabla + DB_PARAM + DB_ALM presentes: slot maps y nmax poblados."""
    from core.data.data_block_plc import DataBloquePLC

    state = _make_state_with_active(_make_excel_cache())
    bloques = _make_bloques_cache(
        blocks_present={
            DataBloquePLC.normalize_name("DB100_CPR_PARAM"),
            DataBloquePLC.normalize_name("DB100_CPR_ALM"),
        },
        tag_tables_present={
            DataBloquePLC.normalize_name("100_CPR"),
        },
    )

    sm = proc_build_slot_maps(state, _make_config_manager(), 100, bloques)

    assert sm.table_present is True
    assert sm.db_missing == []
    assert sm.db_param_name == "DB100_CPR_PARAM"
    assert sm.db_alm_name == "DB100_CPR_ALM"
    assert sm.table_name == "100_CPR"
    assert sm.preal == {0: "NO USAR", 1: "real 1"}
    assert sm.pint == {0: "NO USAR", 1: "int 1"}
    assert sm.alm == {0: "NO USAR", 1: "alm 1"}
    assert sm.nmax == {"preal": 3, "pint": 2, "alm": 1, "alm_hmi": 1}
    assert sm.nmax_names == {
        "preal": "100_N_MAX_PREAL",
        "pint": "100_N_MAX_PINT",
        "alm": "100_N_MAX_ALM",
        "alm_hmi": "100_N_MAX_ALM_HMI",
    }
    assert sm.missing_blocks == []


def test_proc_build_slot_maps_tabla_ausente():
    """Tabla del proceso no esta: slot maps y nmax vacios, table_present=False."""
    from core.data.data_block_plc import DataBloquePLC

    state = _make_state_with_active(_make_excel_cache())
    bloques = _make_bloques_cache(
        blocks_present={
            DataBloquePLC.normalize_name("DB100_CPR_PARAM"),
            DataBloquePLC.normalize_name("DB100_CPR_ALM"),
        },
        tag_tables_present=set(),  # tabla ausente
    )

    sm = proc_build_slot_maps(state, _make_config_manager(), 100, bloques)

    assert sm.table_present is False
    assert sm.db_missing == []
    assert sm.preal == {}
    assert sm.pint == {}
    assert sm.alm == {}
    assert sm.nmax == {}
    assert sm.nmax_names == {}
    # missing_blocks reporta la tabla (forma que consume el preview FB).
    assert sm.missing_blocks == ["Tabla de variables: 100_CPR"]


def test_proc_build_slot_maps_solo_db_alm_ausente():
    """Tabla + DB_PARAM presentes, DB_ALM ausente: slot maps poblados, db_missing=[db_alm]."""
    from core.data.data_block_plc import DataBloquePLC

    state = _make_state_with_active(_make_excel_cache())
    bloques = _make_bloques_cache(
        blocks_present={
            DataBloquePLC.normalize_name("DB100_CPR_PARAM"),  # solo DB_PARAM
        },
        tag_tables_present={
            DataBloquePLC.normalize_name("100_CPR"),
        },
    )

    sm = proc_build_slot_maps(state, _make_config_manager(), 100, bloques)

    assert sm.table_present is True
    assert sm.db_missing == ["DB100_CPR_ALM"]
    assert sm.db_alm_name == "DB100_CPR_ALM"
    # slot maps siguen poblados (los comentarios del Excel existen).
    assert sm.preal == {0: "NO USAR", 1: "real 1"}
    assert sm.pint == {0: "NO USAR", 1: "int 1"}
    assert sm.alm == {0: "NO USAR", 1: "alm 1"}
    # nmax se calcula siempre que la tabla este presente.
    assert sm.nmax == {"preal": 3, "pint": 2, "alm": 1, "alm_hmi": 1}
    # missing_blocks reporta solo DB_ALM.
    assert sm.missing_blocks == ["DB de alarmas: DB100_CPR_ALM"]


def test_proc_build_slot_maps_solo_db_param_ausente():
    """Tabla + DB_ALM presentes, DB_PARAM ausente: simetrico al anterior."""
    from core.data.data_block_plc import DataBloquePLC

    state = _make_state_with_active(_make_excel_cache())
    bloques = _make_bloques_cache(
        blocks_present={
            DataBloquePLC.normalize_name("DB100_CPR_ALM"),  # solo DB_ALM
        },
        tag_tables_present={
            DataBloquePLC.normalize_name("100_CPR"),
        },
    )

    sm = proc_build_slot_maps(state, _make_config_manager(), 100, bloques)

    assert sm.table_present is True
    assert sm.db_missing == ["DB100_CPR_PARAM"]
    assert sm.db_param_name == "DB100_CPR_PARAM"
    assert sm.preal == {0: "NO USAR", 1: "real 1"}
    assert sm.missing_blocks == ["DB de parametros: DB100_CPR_PARAM"]


def test_proc_build_slot_maps_ambos_dbs_ausentes_tabla_presente():
    """Tabla presente + 0 DBs: slot maps y nmax poblados, db_missing=[ambos]."""
    from core.data.data_block_plc import DataBloquePLC

    state = _make_state_with_active(_make_excel_cache())
    bloques = _make_bloques_cache(
        blocks_present=set(),  # ni DB_PARAM ni DB_ALM
        tag_tables_present={
            DataBloquePLC.normalize_name("100_CPR"),
        },
    )

    sm = proc_build_slot_maps(state, _make_config_manager(), 100, bloques)

    assert sm.table_present is True
    assert set(sm.db_missing) == {"DB100_CPR_PARAM", "DB100_CPR_ALM"}
    # slot maps poblados: el stage 3 del FB aborta con "no hay nada
    # que aplicar" ANTES de usarlos.
    assert sm.preal == {0: "NO USAR", 1: "real 1"}
    assert sm.nmax == {"preal": 3, "pint": 2, "alm": 1, "alm_hmi": 1}
    # missing_blocks reporta los 2 DBs.
    assert set(sm.missing_blocks) == {
        "DB de parametros: DB100_CPR_PARAM",
        "DB de alarmas: DB100_CPR_ALM",
    }


def test_proc_build_slot_maps_excel_no_cargado():
    """Sin cache activo: RuntimeError claro."""
    state = _make_state_with_active(None)
    bloques = _make_bloques_cache(set(), set())

    with pytest.raises(RuntimeError, match="alimentacion"):
        proc_build_slot_maps(state, _make_config_manager(), 100, bloques)


def test_proc_build_slot_maps_proc_uid_no_existe():
    """proc_uid no esta en cache.procesos: RuntimeError claro."""
    state = _make_state_with_active(_make_excel_cache())
    bloques = _make_bloques_cache(set(), set())

    with pytest.raises(RuntimeError, match="uid=999"):
        proc_build_slot_maps(state, _make_config_manager(), 999, bloques)
