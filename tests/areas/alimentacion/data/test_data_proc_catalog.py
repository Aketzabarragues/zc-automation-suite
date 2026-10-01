"""Tests de ``data_proc_catalog``.

Cobertura:
  - ``DataProcCatalog.to_dict`` con / sin contenido.
  - ``build_proc_catalog`` devuelve shape estable y claves
    canonicas (``procesos``, ``parametros_int``, ``parametros_real``,
    ``alarmas``).
  - ``get_columns_for`` enumera TODOS los campos del DTO (sin
    filtrar).
  - ``DISPLAY_ORDER`` contiene exactamente las columnas visibles
    del componente ``ProcesosPanel`` actual (regresion visual
    cero).
  - ``MONO_COLUMNS`` es un ``frozenset`` con los identificadores.
  - Toda columna de ``DISPLAY_ORDER`` esta declarada como campo
    en el DTO correspondiente (no hay typos en el catalog).
  - Toda columna de ``COLUMN_LABELS`` aparece como campo en
    AL MENOS un DTO.
"""
from __future__ import annotations

import dataclasses

from areas.alimentacion.data.data_alarmas import DataAlarmaPLC
from areas.alimentacion.data.data_parametros_int import DataParamIntPLC
from areas.alimentacion.data.data_parametros_real import DataParamRealPLC
from areas.alimentacion.data.data_procesos import DataProcesoPLC
from areas.alimentacion.data.data_proc_catalog import (
    COLUMN_LABELS,
    DISPLAY_ORDER,
    MONO_COLUMNS,
    DataProcCatalog,
    build_proc_catalog,
    get_columns_for,
    get_model_columns_map,
)


_DTO_BY_DOMAIN: dict[str, type] = {
    "procesos":        DataProcesoPLC,
    "parametros_int":  DataParamIntPLC,
    "parametros_real": DataParamRealPLC,
    "alarmas":         DataAlarmaPLC,
}


def test_data_proc_catalog_vacio_es_valido() -> None:
    """Instanciar ``DataProcCatalog()`` con defaults produce shape JSON-serializable."""
    cat = DataProcCatalog()
    d = cat.to_dict()
    assert d == {
        "model_columns": {},
        "col_labels": {},
        "mono_cols": [],
        "display_order": {},
    }


def test_build_proc_catalog_shape_completo() -> None:
    """El payload expone las 4 claves del contrato."""
    payload = build_proc_catalog()
    assert set(payload.keys()) == {
        "model_columns", "col_labels", "mono_cols", "display_order",
    }


def test_build_proc_catalog_tiene_los_4_dominios() -> None:
    """``model_columns`` y ``display_order`` cubren los 4 dominios."""
    payload = build_proc_catalog()
    expected = {"procesos", "parametros_int", "parametros_real", "alarmas"}
    assert set(payload["model_columns"].keys()) == expected
    assert set(payload["display_order"].keys()) == expected


def test_get_columns_for_devuelve_todos_los_campos_del_dto() -> None:
    """``get_columns_for`` enumera TODOS los campos (sin filtrar)."""
    for domain, dto in _DTO_BY_DOMAIN.items():
        cols = get_columns_for(domain)
        expected = {f.name for f in dataclasses.fields(dto)}
        assert set(cols) == expected, f"{domain}: {set(cols)} != {expected}"


def test_get_columns_for_dominio_inexistente_devuelve_vacio() -> None:
    """Dominio no registrado -> ``[]``."""
    assert get_columns_for("no_existe") == []


def test_get_model_columns_map_tiene_los_4_dominios() -> None:
    """``get_model_columns_map`` devuelve el universo completo."""
    m = get_model_columns_map()
    assert set(m.keys()) == set(_DTO_BY_DOMAIN.keys())
    for domain, cols in m.items():
        assert cols == get_columns_for(domain)


def test_mono_columns_es_frozenset_de_identificadores() -> None:
    """``MONO_COLUMNS`` es frozenset y solo contiene identificadores canonicos."""
    assert isinstance(MONO_COLUMNS, frozenset)
    for col in MONO_COLUMNS:
        presente_en_alguno = any(
            col in {f.name for f in dataclasses.fields(dto)}
            for dto in _DTO_BY_DOMAIN.values()
        )
        assert presente_en_alguno, f"MONO_COLUMNS contiene '{col}' que no es campo"


def test_display_order_solo_contiene_campos_del_dto() -> None:
    """Cada entrada de ``DISPLAY_ORDER`` referencia campos reales del DTO."""
    for domain, cols in DISPLAY_ORDER.items():
        dto_fields = {f.name for f in dataclasses.fields(_DTO_BY_DOMAIN[domain])}
        desconocidos = set(cols) - dto_fields
        assert not desconocidos, f"{domain}: campos desconocidos {desconocidos}"


def test_display_order_no_tiene_duplicados() -> None:
    """Ningun dominio repite una columna en ``DISPLAY_ORDER``."""
    for domain, cols in DISPLAY_ORDER.items():
        assert len(cols) == len(set(cols)), f"{domain} tiene duplicados en DISPLAY_ORDER"


def test_column_labels_cubre_los_campos_de_los_4_dtos() -> None:
    """Toda clave de ``COLUMN_LABELS`` es nombre de campo en al menos un DTO."""
    campos_totales: set[str] = set()
    for dto in _DTO_BY_DOMAIN.values():
        campos_totales.update(f.name for f in dataclasses.fields(dto))
    for col in COLUMN_LABELS:
        assert col in campos_totales, f"COLUMN_LABELS tiene '{col}' que no es campo de ningun DTO"


def test_build_proc_catalog_serializable_a_json() -> None:
    """``json.dumps(build_proc_catalog())`` funciona (no hay tipos no primitivos)."""
    import json
    json.dumps(build_proc_catalog())


def test_display_order_procesos_replica_la_tabla_actual() -> None:
    """El orden de ``procesos`` en ``DISPLAY_ORDER`` coincide con la
    tabla actual del componente ``ProcesosPanel``.
    """
    assert DISPLAY_ORDER["procesos"] == [
        "uid", "codigo", "nombre", "preal", "pint", "alarmas", "alm_hmi",
    ]


def test_display_order_parametros_replica_la_tabla_actual() -> None:
    """El orden de ``parametros_int`` y ``parametros_real`` coincide con la tabla actual."""
    expected = [
        "uid", "numero", "codigo", "num_db", "num_lista", "txt_lista", "descripcion",
    ]
    assert DISPLAY_ORDER["parametros_int"] == expected
    assert DISPLAY_ORDER["parametros_real"] == expected


def test_display_order_alarmas_replica_la_tabla_actual() -> None:
    """El orden de ``alarmas`` coincide con la tabla actual."""
    assert DISPLAY_ORDER["alarmas"] == [
        "uid", "numero", "proceso", "num_db", "descripcion", "comentario_db",
    ]