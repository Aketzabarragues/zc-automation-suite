"""Tests del ``build_catalog`` de disp con override de ``display_order``.

Cobertura:
  - Sin override: ``model_columns`` == ``get_model_columns_map()``
    (TODOS los campos visibles del DTO, comportamiento historico).
  - Override por canonical: reemplaza la lista de campos.
  - Override parcial: solo los campos listados.
  - Override con canonical desconocido: se descarta con warning.
  - Override con columnas inexistentes: se descartan con warning.
  - Override con todas las columnas invalidas: el canonical cae
    al default.
  - Override preserva el orden indicado por el operario.
  - Sin ``config_manager`` (None): defaults (compat tests).
"""
from __future__ import annotations

from unittest.mock import MagicMock

from areas.alimentacion.data.data_disp_catalog import (
    _CANONICAL_TO_CLASS,
    build_catalog,
    get_model_columns_map,
)


def _cm_with_override(override):
    """Construye un mock de ConfigManager con override de disp."""
    cm = MagicMock()
    cm.get_disp_display_order_override.return_value = override
    cm.get_proc_display_order_override.return_value = {}
    # Stubs de las APIs que build_catalog usa para device_tabs y nmax.
    cm.list_hw_types_active.return_value = []
    cm.get_excel_target_for.return_value = None
    cm.list_nmax_active.return_value = []
    cm.get_nmax_entry.return_value = None
    return cm


def test_build_catalog_sin_override_devuelve_todos_los_campos() -> None:
    """Sin override, ``model_columns`` es la lista completa (TODOS los campos)."""
    cm = _cm_with_override({})
    payload = build_catalog(cm)
    expected = get_model_columns_map()
    assert payload["model_columns"] == expected
    # Sanity: TODOS los canonicals aparecen con sus campos reales.
    for canon in _CANONICAL_TO_CLASS:
        assert canon in payload["model_columns"]
        assert len(payload["model_columns"][canon]) > 0


def test_build_catalog_con_config_manager_vacio_devuelve_todos_los_campos() -> None:
    """``config_manager`` mockeado sin override -> defaults (compat tests sin cm)."""
    cm = _cm_with_override({})
    payload = build_catalog(cm)
    assert payload["model_columns"] == get_model_columns_map()


def test_build_catalog_override_reemplaza_un_canonical() -> None:
    """Override por canonical reemplaza la lista de campos de ese canonical."""
    override = {
        "DispED": ["uid", "numero", "tag"],   # solo 3 campos del DTO
    }
    cm = _cm_with_override(override)
    payload = build_catalog(cm)
    assert payload["model_columns"]["DispED"] == ["uid", "numero", "tag"]
    # Los demas canonicals quedan con su default.
    for canon in _CANONICAL_TO_CLASS:
        if canon == "DispED":
            continue
        assert payload["model_columns"][canon] == get_model_columns_map()[canon]


def test_build_catalog_override_ignora_canonical_desconocido() -> None:
    """Canonical que no existe en el catalog se descarta con warning."""
    override = {
        "DispED":   ["uid", "numero"],
        "Inventado": ["x", "y"],  # canonical desconocido
    }
    cm = _cm_with_override(override)
    payload = build_catalog(cm)
    assert "DispED" in payload["model_columns"]
    assert "Inventado" not in payload["model_columns"]


def test_build_catalog_override_ignora_columnas_inexistentes() -> None:
    """Columnas que no son campos del DTO se descartan con warning."""
    override = {
        "DispED": ["uid", "numero", "fantasma"],  # 'fantasma' no es campo
    }
    cm = _cm_with_override(override)
    payload = build_catalog(cm)
    assert payload["model_columns"]["DispED"] == ["uid", "numero"]


def test_build_catalog_override_canonical_sin_columnas_validas() -> None:
    """Si TODAS las columnas del override son invalidas, el canonical
    cae al default (no se queda vacio).
    """
    override = {
        "DispED": ["x", "y", "z"],  # ninguna es campo real
    }
    cm = _cm_with_override(override)
    payload = build_catalog(cm)
    assert payload["model_columns"]["DispED"] == get_model_columns_map()["DispED"]


def test_build_catalog_override_preserva_orden() -> None:
    """El override determina el orden visible (no se reordena a default)."""
    default = get_model_columns_map()["DispED"]
    override = {
        "DispED": list(reversed(default)),  # orden inverso al default
    }
    cm = _cm_with_override(override)
    payload = build_catalog(cm)
    assert payload["model_columns"]["DispED"] == list(reversed(default))


def test_build_catalog_override_incluye_multiples_canonicals() -> None:
    """Override afecta a TODOS los canonicals listados, los demas caen a default."""
    override = {
        "DispED": ["uid"],
        "DispEA": ["uid", "numero"],
    }
    cm = _cm_with_override(override)
    payload = build_catalog(cm)
    assert payload["model_columns"]["DispED"] == ["uid"]
    assert payload["model_columns"]["DispEA"] == ["uid", "numero"]
    # DispSA no esta en override -> default.
    assert payload["model_columns"]["DispSA"] == get_model_columns_map()["DispSA"]


def test_build_catalog_override_con_lista_vacia_es_warning() -> None:
    """Override con lista vacia para un canonical: el canonical cae al default."""
    override = {"DispED": []}
    cm = _cm_with_override(override)
    payload = build_catalog(cm)
    # Lista vacia = sin override efectivo, default.
    assert payload["model_columns"]["DispED"] == get_model_columns_map()["DispED"]


def test_build_catalog_no_toca_device_tabs_ni_nmax() -> None:
    """El override solo afecta ``model_columns``; ``device_tabs`` y ``nmax``
    siguen leyendo del config_manager como antes.
    """
    cm = MagicMock()
    cm.get_disp_display_order_override.return_value = {
        "DispED": ["uid"],
    }
    cm.get_proc_display_order_override.return_value = {}
    cm.list_hw_types_active.return_value = ["ed"]
    cm.get_excel_target_for.return_value = {"sheet": "DISP_ED", "table": "Disp_ED", "canonical": "DispED"}
    cm.list_nmax_active.return_value = ["max1"]
    cm.get_nmax_entry.return_value = {"name": "max1", "label": "MAX1"}

    payload = build_catalog(cm)
    # ``device_tabs`` y ``nmax`` vienen del config_manager; su
    # shape no depende del override de display_order (solo valido
    # que aparecen y tienen las claves esperadas).
    assert len(payload["device_tabs"]) == 1
    assert payload["device_tabs"][0]["hw_type"] == "ed"
    assert payload["device_tabs"][0]["canonical"] == "DispED"
    assert len(payload["nmax"]) == 1
    assert payload["nmax"][0]["name"] == "max1"
    # El override SÍ se aplica en model_columns.
    assert payload["model_columns"]["DispED"] == ["uid"]