"""Tests del ``build_entidades_catalog`` con override de ``display_order``.

Replica el patron de ``test_data_disp_catalog_build.py`` y
``test_data_proc_catalog.py`` para el catalog de entidades.

Cobertura:
  - Sin override: ``model_columns`` == ``get_model_columns_map()``
    y ``col_labels`` == ``COLUMN_LABELS`` (defaults).
  - Override de ``display_order`` por dominio: reemplaza la lista.
  - Override de ``display_order`` con dominio desconocido: warning.
  - Override de ``display_order`` con columnas inexistentes: warning.
  - Override de ``col_labels`` por columna: reemplaza la etiqueta.
  - Override de ``col_labels`` con columna desconocida: warning.
  - Override preserva el orden indicado por el operario.
  - Sin ``config_manager`` (None): defaults.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from areas.alimentacion.data.data_entidades_catalog import (
    COLUMN_LABELS,
    DISPLAY_ORDER,
    _DOMAIN_TO_CLASS,
    build_entidades_catalog,
    get_model_columns_map,
)


def _cm_with_overrides(display_order=None, col_labels=None):
    """Construye un mock de ConfigManager con overrides de entidades."""
    cm = MagicMock()
    cm.get_entidades_display_order_override.return_value = display_order or {}
    cm.get_entidades_col_labels_override.return_value = col_labels or {}
    return cm


def test_build_catalog_sin_override_devuelve_todos_los_campos() -> None:
    """Sin override, ``model_columns`` es la lista completa del DTO."""
    cm = _cm_with_overrides()
    payload = build_entidades_catalog(cm)
    assert payload["model_columns"] == get_model_columns_map()
    # Sanity: el unico dominio es ``entidades`` y tiene los 7 campos.
    assert set(payload["model_columns"].keys()) == {"entidades"}
    assert len(payload["model_columns"]["entidades"]) == 7


def test_build_catalog_sin_config_manager_devuelve_defaults() -> None:
    """``config_manager`` ausente -> defaults (compat tests sin cm)."""
    payload = build_entidades_catalog()
    assert payload["model_columns"] == get_model_columns_map()
    assert payload["col_labels"] == dict(COLUMN_LABELS)
    assert payload["display_order"] == {
        dom: list(cols) for dom, cols in DISPLAY_ORDER.items()
    }


def test_build_catalog_override_display_order_reemplaza_dominio() -> None:
    """Override por dominio reemplaza la lista de campos de ese dominio."""
    override = {
        "entidades": ["plc_name", "numero", "plc_tag", "descripcion"],
    }
    cm = _cm_with_overrides(display_order=override)
    payload = build_entidades_catalog(cm)
    assert payload["display_order"]["entidades"] == override["entidades"]
    # ``model_columns`` sigue siendo el universo total.
    assert len(payload["model_columns"]["entidades"]) == 7


def test_build_catalog_override_preserva_orden_indicado() -> None:
    """El operario puede reordenar las columnas via config.json."""
    override = {
        "entidades": ["plc_comentario", "plc_tag", "numero", "plc_name"],
    }
    cm = _cm_with_overrides(display_order=override)
    payload = build_entidades_catalog(cm)
    assert payload["display_order"]["entidades"] == [
        "plc_comentario", "plc_tag", "numero", "plc_name",
    ]


def test_build_catalog_override_con_dominio_desconocido_se_descarta() -> None:
    """Override con dominio invalido se ignora con warning."""
    override = {
        "entidades": ["numero", "plc_tag"],
        "fantasma":  ["x", "y"],
    }
    cm = _cm_with_overrides(display_order=override)
    payload = build_entidades_catalog(cm)
    assert "entidades" in payload["display_order"]
    assert "fantasma" not in payload["display_order"]


def test_build_catalog_override_con_columnas_inexistentes_se_descartan() -> None:
    """Override con campos que no son del DTO se descartan con warning."""
    override = {
        "entidades": ["numero", "plc_tag", "no_existe", "tampoco_existe"],
    }
    cm = _cm_with_overrides(display_order=override)
    payload = build_entidades_catalog(cm)
    assert payload["display_order"]["entidades"] == ["numero", "plc_tag"]


def test_build_catalog_override_con_todas_columnas_invalidas_cae_al_default() -> None:
    """Override sin campos validos: el dominio cae al default."""
    override = {
        "entidades": ["no_existe_1", "no_existe_2"],
    }
    cm = _cm_with_overrides(display_order=override)
    payload = build_entidades_catalog(cm)
    assert payload["display_order"]["entidades"] == DISPLAY_ORDER["entidades"]


def test_build_catalog_override_col_labels_reemplaza_etiqueta() -> None:
    """Override de ``col_labels`` por columna reemplaza la etiqueta humana."""
    override = {
        "numero":  "Slot",
        "plc_tag": "Tag Name",
    }
    cm = _cm_with_overrides(col_labels=override)
    payload = build_entidades_catalog(cm)
    assert payload["col_labels"]["numero"] == "Slot"
    assert payload["col_labels"]["plc_tag"] == "Tag Name"
    # Las etiquetas no overriden se mantienen.
    assert payload["col_labels"]["descripcion"] == COLUMN_LABELS["descripcion"]


def test_build_catalog_override_col_labels_con_columna_desconocida_se_descarta() -> None:
    """Override de ``col_labels`` con columna que no es del DTO se ignora."""
    override = {
        "numero":      "Slot",
        "no_existe":   "Label Inventado",
    }
    cm = _cm_with_overrides(col_labels=override)
    payload = build_entidades_catalog(cm)
    assert payload["col_labels"]["numero"] == "Slot"
    assert "no_existe" not in payload["col_labels"]


def test_build_catalog_override_col_labels_con_label_vacio_se_descarta() -> None:
    """Override de ``col_labels`` con label vacio o no-string se ignora."""
    override = {
        "numero": "Slot",
        "plc_tag": "",
        "plc_tipo": "   ",
        "plc_index": None,
    }
    cm = _cm_with_overrides(col_labels=override)
    payload = build_entidades_catalog(cm)
    assert payload["col_labels"]["numero"] == "Slot"
    assert payload["col_labels"]["plc_tag"] == COLUMN_LABELS["plc_tag"]
    assert payload["col_labels"]["plc_tipo"] == COLUMN_LABELS["plc_tipo"]
    assert payload["col_labels"]["plc_index"] == COLUMN_LABELS["plc_index"]


def test_build_catalog_payload_keys_son_las_cuatro_ent() -> None:
    """El payload expone las 4 claves con prefijo ``ent_*``."""
    payload = build_entidades_catalog()
    assert set(payload.keys()) == {
        "model_columns", "col_labels", "mono_cols", "display_order",
    }


def test_dominio_unico_es_entidades() -> None:
    """El DTO Entidad es el unico dominio de este catalog."""
    assert set(_DOMAIN_TO_CLASS.keys()) == {"entidades"}