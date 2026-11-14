"""El mapa de slots, los nombres y los N_MAX de un proceso.

Que se llama que en TIA y que slot toca cada fila del Excel. Es logica pura:
aqui no hay ni portal de TIA ni transacciones.
"""
from __future__ import annotations

import logging

import pytest

from zc_suite.areas.alimentacion.procesos.mapa import (
    COMENTARIO_SLOT_CERO,
    COMENTARIO_VACIO,
    MapaProceso,
    proc_construir_mapa,
    proc_falta_db,
    proc_mapa_de_slots,
    proc_nmax,
    proc_nombres,
    proc_precondiciones_ok,
)

#: Los sufijos de N_MAX del config.
SUFIJOS = {"preal": "PREAL", "pint": "PINT", "alm": "ALM", "alm_hmi": "ALM_HMI"}


def _proceso() -> dict:
    """La fila del proceso del Excel."""
    return {
        "uid": 100,
        "nombre": "CPR",
        "codigo": "CPR",
        "preal": 3,
        "pint": 2,
        "alarmas": 16,
        "alm_hmi": 2,
        "plc_name": "ZC_PLC_STD",
    }


def _preal() -> list[dict]:
    """Las filas de ParametrosReales del proceso."""
    return [
        {"codigo": "CPR", "numero": 1, "num_db": 53100, "comentario_db": "Un real"},
        {"codigo": "CPR", "numero": 2, "num_db": 53100, "comentario_db": "Otro real"},
        {"codigo": "CPR", "numero": 3, "num_db": 53100, "comentario_db": ""},
        {"codigo": "OTR", "numero": 9, "num_db": 53100, "comentario_db": "otro proceso"},
    ]


def _pint() -> list[dict]:
    """Las filas de ParametrosEnteros del proceso."""
    return [
        {"codigo": "CPR", "numero": 1, "num_db": 53100, "comentario_db": "Un entero"},
        {"codigo": "CPR", "numero": 2, "num_db": 53100, "comentario_db": "Otro entero"},
    ]


def _alm() -> list[dict]:
    """Las filas de Alarmas del proceso: se filtran por nombre, no codigo."""
    return [
        {"proceso": "CPR", "numero": 1, "num_db": 55100, "comentario_db": "Una alarma"},
        {"proceso": "CPR", "numero": 2, "num_db": 55100, "comentario_db": "Otra alarma"},
        {"proceso": "OTRO", "numero": 3, "num_db": 55100, "comentario_db": "otra"},
    ]


def _bloques() -> list[dict]:
    """El escaneo de bloques: los dos DBs del proceso."""
    return [
        {"nombre": "DB53100_CPR_PARAM", "numero": 53100, "tipo": "DB"},
        {"nombre": "DB55100_CPR_ALM", "numero": 55100, "tipo": "DB"},
        {"nombre": "DB1_OB", "numero": 1, "tipo": "OB"},
    ]


def _tablas() -> list[dict]:
    """El escaneo de tablas: la tabla del proceso."""
    return [
        {"nombre": "100_CPR", "ruta": "0_Procesos/CPR"},
        {"nombre": "0_Config_Generales", "ruta": "0_Sistema"},
    ]


# ── los nombres ─────────────────────────────────────────────────────────────


def test_el_num_db_sale_de_la_primera_fila_del_excel() -> None:
    """El ``num_db`` del DB_PARAM sale de la primera fila de PReal con ese
    codigo y el del DB_ALM, de la primera fila de Alarmas con ese nombre."""
    db_param, db_alm, tabla = proc_nombres(
        _proceso(), _preal(), _alm(), 100
    )

    assert db_param == "DB53100_CPR_PARAM"
    assert db_alm == "DB55100_CPR_ALM"
    assert tabla == "100_CPR"


def test_el_num_db_por_defecto_es_el_uid_con_warning() -> None:
    """Sin filas en el Excel, ``num_db = uid`` (convencion legacy) y un aviso."""
    warnings: list[str] = []
    db_param, db_alm, tabla = proc_nombres(
        _proceso(), [], [], 100, warnings
    )

    assert db_param == "DB100_CPR_PARAM"
    assert db_alm == "DB100_CPR_ALM"
    assert tabla == "100_CPR"
    assert len(warnings) == 2
    assert warnings[0] == (
        "Proceso uid=100 (PReal/PInt): no hay filas en el Excel; "
        "se usa num_db=100 como fallback (convencion legacy)."
    )
    assert warnings[1] == (
        "Proceso uid=100 (ALM): no hay filas en el Excel; "
        "se usa num_db=100 como fallback (convencion legacy)."
    )


def test_el_num_db_de_param_no_mira_a_pint() -> None:
    """El ``num_db`` del DB_PARAM **solo** mira a ``ParametrosReales`` (como
    ``main``): con PReal vacio sale el fallback, aunque PInt tenga filas."""
    warnings: list[str] = []
    db_param, _, _ = proc_nombres(
        _proceso(), [], _alm(), 100, warnings
    )

    assert db_param == "DB100_CPR_PARAM"
    assert warnings == [
        "Proceso uid=100 (PReal/PInt): no hay filas en el Excel; "
        "se usa num_db=100 como fallback (convencion legacy)."
    ]


def test_el_filtro_de_codigo_es_exacto_sin_strip() -> None:
    """El filtro de ``codigo`` es una comparacion exacta (sin ``strip``), como
    ``main``: una fila con espacios no pasa el filtro y sale el fallback."""
    warnings: list[str] = []
    preal = [{"codigo": "CPR ", "numero": 1, "num_db": 53100}]
    db_param, _, _ = proc_nombres(_proceso(), preal, _alm(), 100, warnings)

    assert db_param == "DB100_CPR_PARAM"
    assert warnings == [
        "Proceso uid=100 (PReal/PInt): no hay filas en el Excel; "
        "se usa num_db=100 como fallback (convencion legacy)."
    ]


def test_alm_filtra_por_nombre_y_no_por_codigo() -> None:
    """El DB_ALM se nombra por ``proceso == nombre`` del proceso."""
    proceso = {"uid": 100, "nombre": "CPR", "codigo": "CPR"}
    alarmas = [
        {"proceso": "CPR", "numero": 1, "num_db": 55100},
        {"proceso": "CPR", "numero": 2, "num_db": 55999},
    ]
    _, db_alm, _ = proc_nombres(proceso, [], alarmas, 100)

    assert db_alm == "DB55100_CPR_ALM"


# ── los mapas de slots ───────────────────────────────────────────────────────


def test_el_slot_cero_es_el_placeholder_no_usar() -> None:
    """Cada slot map empieza en ``0`` con el placeholder ``"NO USAR"``, como
    ``main``."""
    mapa = proc_mapa_de_slots([], [], [], "CPR", "CPR")

    assert mapa == {
        "preal": {0: COMENTARIO_SLOT_CERO},
        "pint": {0: COMENTARIO_SLOT_CERO},
        "alm": {0: COMENTARIO_SLOT_CERO},
    }


def test_los_slots_se_numeran_en_el_orden_del_excel() -> None:
    """Las filas se numeran 1..N por ORDEN en el Excel, no por ``numero``,
    detras del placeholder del slot 0."""
    preal = [
        {"codigo": "CPR", "numero": 7, "comentario_db": "siete"},
        {"codigo": "CPR", "numero": 3, "comentario_db": "tres"},
        {"codigo": "CPR", "numero": 1, "comentario_db": "uno"},
    ]
    mapa = proc_mapa_de_slots(preal, [], [], "CPR", "CPR")

    assert mapa["preal"] == {0: "NO USAR", 1: "siete", 2: "tres", 3: "uno"}


def test_se_descartan_los_filas_con_numero_menor_o_igual_a_cero() -> None:
    """Las filas con ``numero <= 0`` (la fila "NO USAR" de la macro) se
    descartan y no ocupan slot."""
    preal = [
        {"codigo": "CPR", "numero": 0, "comentario_db": "NO USAR"},
        {"codigo": "CPR", "numero": 5, "comentario_db": "cinco"},
        {"codigo": "CPR", "numero": -1, "comentario_db": "negativo"},
    ]
    mapa = proc_mapa_de_slots(preal, [], [], "CPR", "CPR")

    assert mapa["preal"] == {0: "NO USAR", 1: "cinco"}


def test_el_comentario_vacio_se_mapea_a_punto() -> None:
    """El ``comentario_db`` vacio sale como ``"."`` (convencion TIA)."""
    preal = [
        {"codigo": "CPR", "numero": 1, "comentario_db": ""},
        {"codigo": "CPR", "numero": 2, "comentario_db": "   "},
    ]
    mapa = proc_mapa_de_slots(preal, [], [], "CPR", "CPR")

    assert mapa["preal"] == {0: "NO USAR", 1: COMENTARIO_VACIO, 2: COMENTARIO_VACIO}


def test_el_comentario_vacio_avisa_al_logger(caplog: pytest.LogCaptureFixture) -> None:
    """El ``comentario_db`` vacio se mapea a ``"."`` y lo avisa el logger, con
    el texto de ``main``."""
    preal = [
        {"codigo": "CPR", "numero": 1, "comentario_db": ""},
        {"codigo": "CPR", "numero": 2, "comentario_db": "con comentario"},
    ]
    with caplog.at_level(logging.WARNING):
        proc_mapa_de_slots(preal, [], [], "CPR", "CPR")

    assert caplog.records
    assert [r.message for r in caplog.records] == [
        "Parametro sin comentario_db (Excel vacio); se mapea a '.' (indice 1)."
    ]


def test_alm_se_filtra_por_el_nombre_del_proceso() -> None:
    """Las filas de ALM se filtran por ``proceso == nombre``."""
    mapa = proc_mapa_de_slots([], [], _alm(), "CPR", "CPR")

    assert mapa["alm"] == {0: "NO USAR", 1: "Una alarma", 2: "Otra alarma"}


# ── los N_MAX ───────────────────────────────────────────────────────────────


def test_el_n_max_saca_el_valor_de_la_columna_del_proceso() -> None:
    """El valor de cada N_MAX es la columna del proceso del Excel (no el
    numero de filas) y el nombre es ``<uid>_N_MAX_<SUFIXO>``."""
    valores, nombres = proc_nmax(_proceso(), 100, SUFIJOS)

    assert valores == {"preal": 3, "pint": 2, "alm": 16, "alm_hmi": 2}
    assert nombres == {
        "preal": "100_N_MAX_PREAL",
        "pint": "100_N_MAX_PINT",
        "alm": "100_N_MAX_ALM",
        "alm_hmi": "100_N_MAX_ALM_HMI",
    }


def test_el_n_max_solo_con_los_sufijos_del_config() -> None:
    """Un config sin un sufijo no aporta ese N_MAX."""
    valores, nombres = proc_nmax(_proceso(), 100, {"preal": "PREAL"})

    assert valores == {"preal": 3}
    assert nombres == {"preal": "100_N_MAX_PREAL"}


def test_el_n_max_sin_sufijos_sale_vacio() -> None:
    """Sin sufijos en el config, no hay N_MAX."""
    valores, nombres = proc_nmax(_proceso(), 100, {})

    assert valores == {}
    assert nombres == {}


# ── el mapa completo ────────────────────────────────────────────────────────


def test_construir_mapa_con_todo_presente() -> None:
    """Con la tabla y los dos DBs en el PLC, el mapa sale completo."""
    mapa = proc_construir_mapa(
        _proceso(), _preal(), _pint(), _alm(), SUFIJOS, _bloques(), _tablas()
    )

    assert isinstance(mapa, MapaProceso)
    assert mapa.db_param_name == "DB53100_CPR_PARAM"
    assert mapa.db_alm_name == "DB55100_CPR_ALM"
    assert mapa.table_name == "100_CPR"
    assert mapa.table_present is True
    assert mapa.db_missing == []
    assert mapa.missing_blocks == []
    assert mapa.warnings == []
    assert mapa.preal == {0: "NO USAR", 1: "Un real", 2: "Otro real", 3: "."}
    assert mapa.pint == {0: "NO USAR", 1: "Un entero", 2: "Otro entero"}
    assert mapa.alm == {0: "NO USAR", 1: "Una alarma", 2: "Otra alarma"}
    assert mapa.nmax == {"preal": 3, "pint": 2, "alm": 16, "alm_hmi": 2}
    assert proc_precondiciones_ok(mapa) is True


def test_construir_mapa_sin_tabla() -> None:
    """Sin tabla en el PLC: ``table_present`` falso, slot maps, N_MAX y
    nombres de N_MAX vacios, y precondiciones no ok (como ``main``)."""
    mapa = proc_construir_mapa(
        _proceso(), _preal(), _pint(), _alm(), SUFIJOS, _bloques(), []
    )

    assert mapa.table_present is False
    assert mapa.preal == {}
    assert mapa.pint == {}
    assert mapa.alm == {}
    assert mapa.nmax == {}
    assert mapa.nmax_names == {}
    assert mapa.missing_blocks == ["Tabla de variables: 100_CPR"]
    assert proc_precondiciones_ok(mapa) is False


def test_construir_mapa_falta_un_db() -> None:
    """Falta un DB solo: se sigue, con el DB en ``db_missing`` y precondiciones
    ok."""
    bloques = [b for b in _bloques() if b["nombre"] != "DB55100_CPR_ALM"]
    mapa = proc_construir_mapa(
        _proceso(), _preal(), _pint(), _alm(), SUFIJOS, bloques, _tablas()
    )

    assert mapa.db_missing == ["DB55100_CPR_ALM"]
    assert mapa.missing_blocks == ["DB de alarmas: DB55100_CPR_ALM"]
    assert mapa.preal  # el slot map sigue poblado
    assert proc_precondiciones_ok(mapa) is True


def test_construir_mapa_faltan_los_dos_dbs() -> None:
    """Faltan los dos DBs: precondiciones no ok (no hay nada que aplicar)."""
    mapa = proc_construir_mapa(
        _proceso(), _preal(), _pint(), _alm(), SUFIJOS, [], _tablas()
    )

    assert mapa.db_missing == ["DB53100_CPR_PARAM", "DB55100_CPR_ALM"]
    assert mapa.missing_blocks == [
        "DB de parametros: DB53100_CPR_PARAM",
        "DB de alarmas: DB55100_CPR_ALM",
    ]
    assert proc_precondiciones_ok(mapa) is False


def test_el_mensaje_de_falta_db_distingue_param_de_alm() -> None:
    """El mensaje de un DB ausente usa el texto de ``main``."""
    mapa = proc_construir_mapa(
        _proceso(), _preal(), _pint(), _alm(), SUFIJOS, [], _tablas()
    )

    assert proc_falta_db(mapa, mapa.db_param_name) == (
        "DB de parametros no existe en el PLC; "
        "se omite esa sincronizacion: DB53100_CPR_PARAM"
    )
    assert proc_falta_db(mapa, mapa.db_alm_name) == (
        "DB de alarmas no existe en el PLC; "
        "se omite esa sincronizacion: DB55100_CPR_ALM"
    )


def test_el_nombre_del_proceso_no_confunde_codigo_y_nombre() -> None:
    """Un proceso cuyo ``codigo`` y ``nombre`` son distintos: el DB_ALM se
    nombra por el nombre y los slots de ALM se filtran por el nombre."""
    proceso = {
        "uid": 100,
        "nombre": "Compresor principal",
        "codigo": "CPR",
        "preal": 1,
        "pint": 1,
        "alarmas": 2,
        "alm_hmi": 1,
    }
    alarmas = [
        {"proceso": "Compresor principal", "numero": 1, "num_db": 55100,
         "comentario_db": "A1"},
    ]
    mapa = proc_construir_mapa(
        proceso, [], [], alarmas, SUFIJOS, _bloques(), _tablas()
    )

    assert mapa.db_alm_name == "DB55100_CPR_ALM"
    assert mapa.alm == {0: "NO USAR", 1: "A1"}
    assert mapa.table_name == "100_CPR"
