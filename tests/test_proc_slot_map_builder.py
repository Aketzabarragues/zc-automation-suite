"""Tests de ``build_proceso_slot_maps`` (Track B capa app).

Cubre el cruce Excel ↔ BloqueCache para los 3 arrays por proceso
(PReal, PInt, ALM). Verifica precondiciones, fallback de ``num_db``,
comentarios vacíos y filtrado por codigo/proceso.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from areas.alimentacion.application.proc_slot_map_builder import (
    ProcesoSlotMap,
    build_proceso_slot_maps,
)
from core.models.bloque_cache import BloqueCache
from core.models.bloque_plc import BloquePLC


def _make_bloque_cache(names: list[str], tag_tables: list[str] | None = None) -> BloqueCache:
    """Crea un BloqueCache con los nombres de bloques y tag tables indicados."""
    blocks = {
        BloquePLC.normalize_name(n): BloquePLC(
            nombre=n, numero=0, tipo="DB", ruta=""
        )
        for n in names
    }
    tables_dict = {
        BloquePLC.normalize_name(n): BloquePLC(
            nombre=n, numero=0, tipo="TAG_TABLE", ruta=""
        )
        for n in (tag_tables or [])
    }
    return BloqueCache(blocks=blocks, tag_tables=tables_dict)


def _make_excel_cache(
    procesos: list | None = None,
    parametros_real: list | None = None,
    parametros_int: list | None = None,
    alarmas: list | None = None,
) -> MagicMock:
    """Crea un MagicMock que simula ExcelCache con los datos dados."""
    ec = MagicMock()
    ec.procesos = procesos or []
    ec.parametros_real = parametros_real or []
    ec.parametros_int = parametros_int or []
    ec.alarmas = alarmas or []
    return ec


# ── Tests ───────────────────────────────────────────────────────────────


def test_caso_normal_30_preal_60_pint_32_alm() -> None:
    """Caso normal: 30 PReal + 60 PInt + 32 ALM con comentarios."""
    proc = MagicMock(uid=1, nombre="Compacto", codigo="CPR")

    # 30 PReal con comentarios no vacíos.
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

    result = build_proceso_slot_maps(state, config, 1, bloques)
    assert isinstance(result, ProcesoSlotMap)
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
    """``comentario_db`` vacío → "." con warning."""
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

    result = build_proceso_slot_maps(state, MagicMock(), 1, bloques)
    assert result.preal[1] == "."
    assert result.preal[2] == "OK"


def test_proceso_no_en_excel_lanza_runtime_error() -> None:
    """``proc_uid`` no está en ``excel_cache.procesos`` → RuntimeError."""
    excel_cache = _make_excel_cache(procesos=[])
    state = MagicMock(excel_cache=excel_cache)
    bloques = BloqueCache()

    with pytest.raises(RuntimeError, match="no está en el Excel"):
        build_proceso_slot_maps(state, MagicMock(), 999, bloques)


def test_bloque_ausente_en_bloque_cache_devuelve_missing() -> None:
    """Si falta DB_PARAM → missing_blocks no vacío, preal/pint/alm vacíos."""
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
    bloques = BloqueCache()  # vacío → faltan los 3 bloques

    result = build_proceso_slot_maps(state, MagicMock(), 1, bloques)
    assert len(result.missing_blocks) == 3
    # Los 3 dicts de slot_map están vacíos.
    assert result.preal == {}
    assert result.pint == {}
    assert result.alm == {}
    # Pero los nombres TIA están resueltos igualmente.
    assert result.db_param_name == "DB53100_CPR_PARAM"
    assert result.db_alm_name == "DB55100_CPR_ALM"
    assert result.table_name == "1_CPR"


def test_tres_bloques_ausentes_missing_tiene_3_entradas() -> None:
    """Variante: 3 bloques ausentes → missing_blocks con 3 entradas."""
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
    bloques = BloqueCache()

    result = build_proceso_slot_maps(state, MagicMock(), 1, bloques)
    assert len(result.missing_blocks) == 3
    # Los 3 mensajes mencionan los nombres esperados.
    joined = " ".join(result.missing_blocks)
    assert "DB53100_CPR_PARAM" in joined
    assert "DB55100_CPR_ALM" in joined
    assert "1_CPR" in joined


def test_excel_vacio_lanza_runtime_error() -> None:
    """``state.excel_cache is None`` → RuntimeError."""
    state = MagicMock(excel_cache=None)
    bloques = BloqueCache()
    with pytest.raises(RuntimeError, match="excel_cache está vacío"):
        build_proceso_slot_maps(state, MagicMock(), 1, bloques)


def test_fallback_num_db_cuando_lista_vacia() -> None:
    """Si no hay filas de PReal/PInt en el Excel, num_db_param = proc.uid
    con warning (convención legacy)."""
    proc = MagicMock(uid=123, nombre="Compacto", codigo="CPR")
    # Sin PReal en el Excel.
    excel_cache = _make_excel_cache(
        procesos=[proc], parametros_real=[],
        parametros_int=[], alarmas=[],
    )
    state = MagicMock(excel_cache=excel_cache)
    # Solo el DB_ALM está presente (con num_db=99).
    alarmas = [
        MagicMock(uid="AL_1", proceso="Compacto", num_db=99,
                  comentario_db="alarma 1")
    ]
    excel_cache.alarmas = alarmas
    bloques = _make_bloque_cache(
        ["DB123_CPR_PARAM", "DB99_CPR_ALM"],  # DB_PARAM con num_db=123 (fallback)
        tag_tables=["123_CPR"],
    )
    result = build_proceso_slot_maps(state, MagicMock(), 123, bloques)
    # num_db_param cayó al fallback proc.uid=123.
    assert result.db_param_name == "DB123_CPR_PARAM"
    # Hubo al menos un warning por el fallback.
    assert any("fallback" in w.lower() or "no hay filas" in w.lower()
               for w in result.warnings)
