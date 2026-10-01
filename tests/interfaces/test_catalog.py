"""Tests del blueprint catalog."""
from __future__ import annotations

from unittest.mock import MagicMock

from core.web_server.app_flask import create_app


def _app_with_registry(registry_mock, config_manager=None):
    app = create_app(config_manager=config_manager or MagicMock())
    app.config["TESTING"] = True
    import core.composition.app_area_registry as ar_mod
    original_discover = ar_mod.AreaRegistry.discover
    ar_mod.AreaRegistry.discover = lambda: registry_mock
    return app.test_client(), ar_mod, original_discover


def _restore(ar_mod, original):
    ar_mod.AreaRegistry.discover = original


def test_get_catalog_merges_all_areas():
    registry = MagicMock()
    spec_a = MagicMock()
    spec_a.contributes_catalog = lambda cm: {
        "device_tabs": [{"hw_type": "ed", "label": "Entradas Digitales"}],
    }
    spec_b = MagicMock()
    spec_b.contributes_catalog = lambda cm: {
        "nmax": [{"name": "N_MAX_ED", "label": "Max EDs"}],
    }
    registry.all.return_value = [spec_a, spec_b]

    client, ar_mod, original = _app_with_registry(registry)
    try:
        resp = client.get("/api/v1/catalog")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert "device_tabs" in data["catalog"]
        assert "nmax" in data["catalog"]
    finally:
        _restore(ar_mod, original)


def test_get_catalog_skips_areas_without_catalog():
    registry = MagicMock()
    spec_with = MagicMock()
    spec_with.contributes_catalog = lambda cm: {"nmax": []}
    spec_without = MagicMock()
    spec_without.contributes_catalog = None
    registry.all.return_value = [spec_with, spec_without]

    client, ar_mod, original = _app_with_registry(registry)
    try:
        resp = client.get("/api/v1/catalog")
        data = resp.get_json()
        assert "nmax" in data["catalog"]
    finally:
        _restore(ar_mod, original)


def test_get_catalog_with_no_areas_returns_empty():
    registry = MagicMock()
    registry.all.return_value = []

    client, ar_mod, original = _app_with_registry(registry)
    try:
        resp = client.get("/api/v1/catalog")
        data = resp.get_json()
        assert data == {"ok": True, "catalog": {}}
    finally:
        _restore(ar_mod, original)


def test_get_catalog_skips_non_dict_returns():
    """Si contributes_catalog retorna no-dict (raro), se omite sin tumbar."""
    registry = MagicMock()
    spec_bad = MagicMock()
    spec_bad.contributes_catalog = lambda cm: "not a dict"  # mal programado
    spec_good = MagicMock()
    spec_good.contributes_catalog = lambda cm: {"nmax": [{"name": "OK"}]}
    registry.all.return_value = [spec_bad, spec_good]

    client, ar_mod, original = _app_with_registry(registry)
    try:
        resp = client.get("/api/v1/catalog")
        data = resp.get_json()
        assert data["catalog"] == {"nmax": [{"name": "OK"}]}
    finally:
        _restore(ar_mod, original)


def test_get_catalog_later_area_overrides_earlier_key():
    """Si dos areas aportan la misma clave, gana la ultima en orden."""
    registry = MagicMock()
    spec_first = MagicMock()
    spec_first.contributes_catalog = lambda cm: {"nmax": [{"name": "FIRST"}]}
    spec_second = MagicMock()
    spec_second.contributes_catalog = lambda cm: {"nmax": [{"name": "SECOND"}]}
    registry.all.return_value = [spec_first, spec_second]

    client, ar_mod, original = _app_with_registry(registry)
    try:
        resp = client.get("/api/v1/catalog")
        data = resp.get_json()
        assert data["catalog"]["nmax"] == [{"name": "SECOND"}]
    finally:
        _restore(ar_mod, original)


def test_get_catalog_expone_claves_proc_para_software():
    """El area ``alimentacion`` aporta ademas las 4 claves ``proc_*``
    (catalog de software: procesos / parametros_int / parametros_real /
    alarmas). El endpoint las fusiona en el top-level del payload.
    """
    from areas.alimentacion import _build_alim_catalog_combined

    registry = MagicMock()
    spec_alim = MagicMock()
    spec_alim.contributes_catalog = _build_alim_catalog_combined
    registry.all.return_value = [spec_alim]

    cm = MagicMock()
    client, ar_mod, original = _app_with_registry(registry, config_manager=cm)
    try:
        resp = client.get("/api/v1/catalog")
        data = resp.get_json()
        assert resp.status_code == 200
        catalog = data["catalog"]
        # 4 claves nuevas del catalog de software.
        for key in (
            "proc_model_columns",
            "proc_col_labels",
            "proc_mono_cols",
            "proc_display_order",
        ):
            assert key in catalog, f"falta {key}"
        # Las 4 cubren los 4 dominios canonicos.
        assert set(catalog["proc_model_columns"].keys()) == {
            "procesos", "parametros_int", "parametros_real", "alarmas",
        }
        assert set(catalog["proc_display_order"].keys()) == {
            "procesos", "parametros_int", "parametros_real", "alarmas",
        }
    finally:
        _restore(ar_mod, original)
