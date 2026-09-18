"""Tests de ``proc_build_slot_maps`` (Track B capa app).

Cubre el cruce Excel Ã¢â€ â€ DataBloqueCache para los 3 arrays por proceso
(PReal, PInt, ALM). Verifica precondiciones, fallback de ``num_db``,
comentarios vacÃƒÂ­os y filtrado por codigo/proceso.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from areas.alimentacion.data.data_ProcSlotMap import (
    DataProcSlotMap,
    proc_build_slot_maps,
)
from core.infrastructure.config.config_manager import ConfigManager
from core.data.data_block_cache import DataBloqueCache
from core.data.data_block_plc import DataBloquePLC


def _make_bloque_cache(names: list[str], tag_tables: list[str] | None = None) -> DataBloqueCache:
    """Crea un DataBloqueCache con los nombres de bloques y tag tables indicados."""
    blocks = {
        DataBloquePLC.normalize_name(n): DataBloquePLC(
            nombre=n, numero=0, tipo="DB", ruta=""
        )
        for n in names
    }
    tables_dict = {
        DataBloquePLC.normalize_name(n): DataBloquePLC(
            nombre=n, numero=0, tipo="TAG_TABLE", ruta=""
        )
        for n in (tag_tables or [])
    }
    return DataBloqueCache(blocks=blocks, tag_tables=tables_dict)


def _make_excel_cache(
    procesos: list | None = None,
    parametros_real: list | None = None,
    parametros_int: list | None = None,
    alarmas: list | None = None,
) -> MagicMock:
    """Crea un MagicMock que simula DataExcelCache con los datos dados."""
    ec = MagicMock()
    ec.procesos = procesos or []
    ec.parametros_real = parametros_real or []
    ec.parametros_int = parametros_int or []
    ec.alarmas = alarmas or []
    return ec


# Ã¢â€â‚¬Ã¢â€â‚¬ Tests Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬


def test_caso_normal_30_preal_60_pint_32_alm() -> None:
    """Caso normal: 30 PReal + 60 PInt + 32 ALM con comentarios."""
    proc = MagicMock(uid=1, nombre="Compacto", codigo="CPR")

    # 30 PReal con comentarios no vacÃƒÂ­os.
    parametros_real = [
        MagicMock(uid=f"PR_{i}", codigo="CPR", num_db=53100, comentario_db=f"PR {i}")
        for i in range(1, 31)
    ]
    # 60 PInt.
    parametros_int = [
        MagicMock(uid=f"PI_{i}", codigo="CPR", num_db=53100, comentario_db=f"PI {i}")
        for i in range(1, 61)
    ]
    # 32 ALM.
    alarmas = [
        MagicMock(uid=f"AL_{i}", proceso="Compacto", num_db=55100,
                  comentario_db=f"AL {i}")
        for i in range(1, 33)
    ]
    excel_cache = _make_excel_cache(
        procesos=[proc],
        parametros_real=parametros_real,
        parametros_int=parametros_int,
        alarmas=alarmas,
    )
    state = MagicMock(excel_cache=excel_cache)
    config = MagicMock()
    bloques = _make_bloque_cache(
        ["DB53100_CPR_PARAM", "DB55100_CPR_ALM"],
        tag_tables=["1_CPR"],
    )

    result = proc_build_slot_maps(state, config, 1, bloques)
    assert isinstance(result, DataProcSlotMap)
    assert result.missing_blocks == []
    assert result.db_param_name == "DB53100_CPR_PARAM"
    assert result.db_alm_name == "DB55100_CPR_ALM"
    assert result.table_name == "1_CPR"
    # Slot maps 1-based.
    assert len(result.preal) == 30
    assert result.preal[1] == "PR 1"
    assert result.preal[30] == "PR 30"
    assert len(result.pint) == 60
    assert result.pint[1] == "PI 1"
    assert result.pint[60] == "PI 60"
    assert len(result.alm) == 32
    assert result.alm[1] == "AL 1"
    assert result.alm[32] == "AL 32"


def test_comentario_vacio_se_mapea_a_punto() -> None:
    """``comentario_db`` vacÃƒÂ­o Ã¢â€ â€™ "." con warning."""
    proc = MagicMock(uid=1, nombre="Compacto", codigo="CPR")
    parametros_real = [
        MagicMock(uid="PR_1", codigo="CPR", num_db=53100, comentario_db=""),
        MagicMock(uid="PR_2", codigo="CPR", num_db=53100, comentario_db="OK"),
    ]
    # Incluimos alarmas para que el DB_ALM se resuelva bien.
    alarmas = [
        MagicMock(uid="AL_1", proceso="Compacto", num_db=55100,
                  comentario_db="AL 1")
    ]
    excel_cache = _make_excel_cache(
        procesos=[proc], parametros_real=parametros_real, alarmas=alarmas
    )
    state = MagicMock(excel_cache=excel_cache)
    bloques = _make_bloque_cache(
        ["DB53100_CPR_PARAM", "DB55100_CPR_ALM"],
        tag_tables=["1_CPR"],
    )

    result = proc_build_slot_maps(state, MagicMock(), 1, bloques)
    assert result.preal[1] == "."
    assert result.preal[2] == "OK"


def test_comentario_con_comillas_envolventes_se_limpian() -> None:
    """Si el operario pega el comentario del Excel con comillas
    envolventes por error (p. ej. ``'COMPACTO - FIJOS - '``), el
    builder las quita. Si no, el diff dirÃƒÂ­a "renombrar" siempre
    que el desired (Excel) tenga comillas y el current (TIA) no
    Ã¢â‚¬â€ un falso positivo. Caso real visto en producciÃƒÂ³n.
    """
    proc = MagicMock(uid=1, nombre="Compacto", codigo="CPR")
    parametros_real = [
        # Slot 1: el operario pegÃƒÂ³ el comentario con comillas simples.
        MagicMock(uid="PR_1", codigo="CPR", num_db=53100,
                  comentario_db="'COMPACTO - FIJOS - '"),
        # Slot 2: el operario lo pegÃƒÂ³ con comillas dobles.
        MagicMock(uid="PR_2", codigo="CPR", num_db=53100,
                  comentario_db='"COMPACTO - FIJOS - X"'),
    ]
    alarmas = [
        MagicMock(uid="AL_1", proceso="Compacto", num_db=55100,
                  comentario_db="AL 1")
    ]
    excel_cache = _make_excel_cache(
        procesos=[proc], parametros_real=parametros_real, alarmas=alarmas
    )
    state = MagicMock(excel_cache=excel_cache)
    bloques = _make_bloque_cache(
        ["DB53100_CPR_PARAM", "DB55100_CPR_ALM"],
        tag_tables=["1_CPR"],
    )

    result = proc_build_slot_maps(state, MagicMock(), 1, bloques)
    # Ambos comentarios vienen SIN comillas envolventes.
    assert result.preal[1] == "COMPACTO - FIJOS -"
    assert result.preal[2] == "COMPACTO - FIJOS - X"


def test_proceso_no_en_excel_lanza_runtime_error() -> None:
    """``proc_uid`` no estÃƒÂ¡ en ``excel_cache.procesos`` Ã¢â€ â€™ RuntimeError."""
    excel_cache = _make_excel_cache(procesos=[])
    state = MagicMock(excel_cache=excel_cache)
    bloques = DataBloqueCache()

    with pytest.raises(RuntimeError, match="no estÃƒÂ¡ en el Excel"):
        proc_build_slot_maps(state, MagicMock(), 999, bloques)


def test_bloque_ausente_en_bloque_cache_devuelve_missing() -> None:
    """Si falta DB_PARAM Ã¢â€ â€™ missing_blocks no vacÃƒÂ­o, preal/pint/alm vacÃƒÂ­os."""
    proc = MagicMock(uid=1, nombre="Compacto", codigo="CPR")
    parametros_real = [
        MagicMock(uid="PR_1", codigo="CPR", num_db=53100, comentario_db="X")
    ]
    alarmas = [
        MagicMock(uid="AL_1", proceso="Compacto", num_db=55100,
                  comentario_db="AL 1")
    ]
    excel_cache = _make_excel_cache(
        procesos=[proc], parametros_real=parametros_real, alarmas=alarmas
    )
    state = MagicMock(excel_cache=excel_cache)
    bloques = DataBloqueCache()  # vacÃƒÂ­o Ã¢â€ â€™ faltan los 3 bloques

    result = proc_build_slot_maps(state, MagicMock(), 1, bloques)
    assert len(result.missing_blocks) == 3
    # Los 3 dicts de slot_map estÃƒÂ¡n vacÃƒÂ­os.
    assert result.preal == {}
    assert result.pint == {}
    assert result.alm == {}
    # Pero los nombres TIA estÃƒÂ¡n resueltos igualmente.
    assert result.db_param_name == "DB53100_CPR_PARAM"
    assert result.db_alm_name == "DB55100_CPR_ALM"
    assert result.table_name == "1_CPR"


def test_tres_bloques_ausentes_missing_tiene_3_entradas() -> None:
    """Variante: 3 bloques ausentes Ã¢â€ â€™ missing_blocks con 3 entradas."""
    proc = MagicMock(uid=1, nombre="Compacto", codigo="CPR")
    # Proveemos filas para que _resolve_num_db NO caiga en el
    # fallback (necesitamos verificar que se generan los 3 nombres
    # correctos, no los del fallback).
    excel_cache = _make_excel_cache(
        procesos=[proc],
        parametros_real=[MagicMock(uid="PR_1", codigo="CPR", num_db=53100, comentario_db="X")],
        alarmas=[MagicMock(uid="AL_1", proceso="Compacto", num_db=55100, comentario_db="Y")],
    )
    state = MagicMock(excel_cache=excel_cache)
    bloques = DataBloqueCache()

    result = proc_build_slot_maps(state, MagicMock(), 1, bloques)
    assert len(result.missing_blocks) == 3
    # Los 3 mensajes mencionan los nombres esperados.
    joined = " ".join(result.missing_blocks)
    assert "DB53100_CPR_PARAM" in joined
    assert "DB55100_CPR_ALM" in joined
    assert "1_CPR" in joined


def test_excel_vacio_lanza_runtime_error() -> None:
    """``state.excel_cache is None`` Ã¢â€ â€™ RuntimeError."""
    state = MagicMock(excel_cache=None)
    bloques = DataBloqueCache()
    with pytest.raises(RuntimeError, match="excel_cache estÃƒÂ¡ vacÃƒÂ­o"):
        proc_build_slot_maps(state, MagicMock(), 1, bloques)


def test_fallback_num_db_cuando_lista_vacia() -> None:
    """Si no hay filas de PReal/PInt en el Excel, num_db_param = proc.uid
    con warning (convenciÃƒÂ³n legacy)."""
    proc = MagicMock(uid=123, nombre="Compacto", codigo="CPR")
    # Sin PReal en el Excel.
    excel_cache = _make_excel_cache(
        procesos=[proc], parametros_real=[],
        parametros_int=[], alarmas=[],
    )
    state = MagicMock(excel_cache=excel_cache)
    # Solo el DB_ALM estÃƒÂ¡ presente (con num_db=99).
    alarmas = [
        MagicMock(uid="AL_1", proceso="Compacto", num_db=99,
                  comentario_db="alarma 1")
    ]
    excel_cache.alarmas = alarmas
    bloques = _make_bloque_cache(
        ["DB123_CPR_PARAM", "DB99_CPR_ALM"],  # DB_PARAM con num_db=123 (fallback)
        tag_tables=["123_CPR"],
    )
    result = proc_build_slot_maps(state, MagicMock(), 123, bloques)
    # num_db_param cayÃƒÂ³ al fallback proc.uid=123.
    assert result.db_param_name == "DB123_CPR_PARAM"
    # Hubo al menos un warning por el fallback.
    assert any("fallback" in w.lower() or "no hay filas" in w.lower()
               for w in result.warnings)


# Ã¢â€â‚¬Ã¢â€â‚¬ N_MAX deseados (solo visual, no se aplican en el commit) Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬


def _config_with_nmax(suffixes: dict[str, str] | None) -> ConfigManager:
    """Mock de ConfigManager con ``get_proc_nmax_suffixes`` parametrizable."""
    config = MagicMock(spec=ConfigManager)
    config.get_proc_nmax_suffixes = MagicMock(return_value=suffixes or {})
    return config


def test_nmax_deseados_se_computan_desde_listas_del_excel() -> None:
    """``DataProcSlotMap.nmax`` = ``len()`` de las listas filtradas
    por proceso del Excel. ``nmax_names`` = nombres completos con
    el sufijo del config (``f"{proc.uid}_N_MAX_{suffix}"``).
    """
    proc = MagicMock(uid=100, nombre="Compacto", codigo="CPR",
                     alm_hmi=0)  # Sept-2026: legacy Excel sin columna.
    # 8 PReal, 3 PInt, 1 ALM.
    parametros_real = [
        MagicMock(uid=f"PR_{i}", codigo="CPR", num_db=53100,
                  comentario_db=f"PR {i}") for i in range(1, 9)
    ]
    parametros_int = [
        MagicMock(uid=f"PI_{i}", codigo="CPR", num_db=53100,
                  comentario_db=f"PI {i}") for i in range(1, 4)
    ]
    alarmas = [
        MagicMock(uid="AL_1", proceso="Compacto", num_db=55100,
                  comentario_db="AL 1")
    ]
    excel_cache = _make_excel_cache(
        procesos=[proc], parametros_real=parametros_real,
        parametros_int=parametros_int, alarmas=alarmas,
    )
    state = MagicMock(excel_cache=excel_cache)
    config = _config_with_nmax(
        {"preal": "PREAL", "pint": "PINT", "alm": "ALM",
         "alm_hmi": "ALM_HMI"}  # Sept-2026: nuevo sufijo.
    )
    bloques = _make_bloque_cache(
        ["DB53100_CPR_PARAM", "DB55100_CPR_ALM"],
        tag_tables=["100_CPR"],
    )

    result = proc_build_slot_maps(state, config, 100, bloques)
    # Sept-2026: 4 N_MAX (alm_hmi=0 en filas legacy).
    assert result.nmax == {
        "preal": 8, "pint": 3, "alm": 1, "alm_hmi": 0,
    }
    assert result.nmax_names == {
        "preal":   "100_N_MAX_PREAL",
        "pint":    "100_N_MAX_PINT",
        "alm":     "100_N_MAX_ALM",
        "alm_hmi": "100_N_MAX_ALM_HMI",
    }


def test_nmax_sin_sufijos_en_config_no_se_computa() -> None:
    """Si el config retorna ``{}`` para ``get_proc_nmax_suffixes``,
    el builder no computa ``nmax`` ni ``nmax_names``.
    """
    proc = MagicMock(uid=100, nombre="Compacto", codigo="CPR")
    parametros_real = [
        MagicMock(uid="PR_1", codigo="CPR", num_db=53100,
                  comentario_db="PR 1")
    ]
    alarmas = [
        MagicMock(uid="AL_1", proceso="Compacto", num_db=55100,
                  comentario_db="AL 1")
    ]
    excel_cache = _make_excel_cache(
        procesos=[proc], parametros_real=parametros_real, alarmas=alarmas,
    )
    state = MagicMock(excel_cache=excel_cache)
    config = _config_with_nmax({})  # sin sufijos
    bloques = _make_bloque_cache(
        ["DB53100_CPR_PARAM", "DB55100_CPR_ALM"],
        tag_tables=["100_CPR"],
    )

    result = proc_build_slot_maps(state, config, 100, bloques)
    assert result.nmax == {}
    assert result.nmax_names == {}


def test_nmax_alm_hmi_se_computa_desde_campo_del_excel() -> None:
    """Sept-2026: nuevo N_MAX ``alm_hmi``.

    A diferencia de preal/pint/alm (que se derivan del len() de cada
    slot_map), ``alm_hmi`` se deriva del campo ``proc.alm_hmi`` del
    Excel (la HMI no genera arrays reales en el DB).

    El builder debe anyadirlo al ``nmax`` con valor del campo, y al
    ``nmax_names`` con el sufijo del config (``ALM_HMI``).
    """
    proc = MagicMock(uid=100, nombre="Compacto", codigo="CPR", alm_hmi=8)
    # 3 PReal, 2 PInt, 1 ALM.
    parametros_real = [
        MagicMock(uid=f"PR_{i}", codigo="CPR", num_db=53100,
                  comentario_db=f"PR {i}") for i in range(1, 4)
    ]
    parametros_int = [
        MagicMock(uid=f"PI_{i}", codigo="CPR", num_db=53100,
                  comentario_db=f"PI {i}") for i in range(1, 3)
    ]
    alarmas = [
        MagicMock(uid="AL_1", proceso="Compacto", num_db=55100,
                  comentario_db="AL 1")
    ]
    excel_cache = _make_excel_cache(
        procesos=[proc], parametros_real=parametros_real,
        parametros_int=parametros_int, alarmas=alarmas,
    )
    state = MagicMock(excel_cache=excel_cache)
    config = _config_with_nmax({
        "preal":   "PREAL",
        "pint":    "PINT",
        "alm":     "ALM",
        "alm_hmi": "ALM_HMI",
    })
    bloques = _make_bloque_cache(
        ["DB53100_CPR_PARAM", "DB55100_CPR_ALM"],
        tag_tables=["100_CPR"],
    )

    result = proc_build_slot_maps(state, config, 100, bloques)

    # 4 N_MAX ahora (3 originales + alm_hmi).
    assert result.nmax == {
        "preal":   3,
        "pint":    2,
        "alm":     1,
        "alm_hmi": 8,  # viene del campo, no de un slot_map
    }
    assert result.nmax_names == {
        "preal":   "100_N_MAX_PREAL",
        "pint":    "100_N_MAX_PINT",
        "alm":     "100_N_MAX_ALM",
        "alm_hmi": "100_N_MAX_ALM_HMI",  # 4to sufijo del config
    }


def test_nmax_alm_hmi_cero_no_aparece_en_diff() -> None:
    """Si ``proc.alm_hmi=0`` (fila legacy del Excel sin la columna)
    pero el resto de filas preal/pint/alm SI existen, el builder
    sigue añadiendo ``alm_hmi`` al nmax (desired=0).

    Opcion A confirmada por el operario 2026-09-18: 'el Excel es la
    verdad'. Si el PLC tiene un valor distinto, generara un diff
    para bajarlo a 0. La logica de 'skip when current=desired=0'
    la maneja ``proc_compute_nmax_diff`` (no el builder).
    """
    # Fila legacy: alm_hmi=0 (sin columna) PERO tiene preal/pint/alm.
    proc = MagicMock(uid=100, nombre="Mixto", codigo="MIX", alm_hmi=0)
    parametros_real = [
        MagicMock(uid="PR_1", codigo="MIX", num_db=53100,
                  comentario_db="PR 1")
    ]
    parametros_int = [
        MagicMock(uid="PI_1", codigo="MIX", num_db=53100,
                  comentario_db="PI 1")
    ]
    alarmas = [
        MagicMock(uid="AL_1", proceso="Mixto", num_db=55100,
                  comentario_db="AL 1")
    ]
    excel_cache = _make_excel_cache(
        procesos=[proc], parametros_real=parametros_real,
        parametros_int=parametros_int, alarmas=alarmas,
    )
    state = MagicMock(excel_cache=excel_cache)
    config = _config_with_nmax({
        "preal":   "PREAL",
        "pint":    "PINT",
        "alm":     "ALM",
        "alm_hmi": "ALM_HMI",
    })
    bloques = _make_bloque_cache(
        ["DB53100_MIX_PARAM", "DB55100_MIX_ALM"],
        tag_tables=["100_MIX"],
    )

    result = proc_build_slot_maps(state, config, 100, bloques)

    # 1 fila de cada (preal/pint/alm) + alm_hmi=0 legacy.
    # La key siempre esta; el valor es 0 (fiel a Excel legacy).
    assert result.nmax["alm_hmi"] == 0
    assert result.nmax_names["alm_hmi"] == "100_N_MAX_ALM_HMI"
    # Las otras 3 deben seguir computandose normal.
    assert result.nmax["preal"] == 1
    assert result.nmax["pint"] == 1
    assert result.nmax["alm"] == 1


def test_nmax_sufijos_se_pasan_a_traves_del_config_manager() -> None:
    """El builder NO hardcodea sufijos: los lee del config."""
    proc = MagicMock(uid=42, nombre="Largo", codigo="LAR")
    parametros_real = [
        MagicMock(uid="PR_1", codigo="LAR", num_db=54000,
                  comentario_db="X")
    ]
    alarmas = [
        MagicMock(uid="AL_1", proceso="Largo", num_db=56000,
                  comentario_db="AL 1")
    ]
    excel_cache = _make_excel_cache(
        procesos=[proc], parametros_real=parametros_real,
        alarmas=alarmas,
    )
    state = MagicMock(excel_cache=excel_cache)
    config = _config_with_nmax(
        {"preal": "REAL", "pint": "INT", "alm": "ALARMS"}
    )
    bloques = _make_bloque_cache(
        ["DB54000_LAR_PARAM", "DB56000_LAR_ALM"],
        tag_tables=["42_LAR"],
    )

    result = proc_build_slot_maps(state, config, 42, bloques)
    assert result.nmax_names == {
        "preal": "42_N_MAX_REAL",
        "pint":  "42_N_MAX_INT",
        "alm":   "42_N_MAX_ALARMS",
    }
