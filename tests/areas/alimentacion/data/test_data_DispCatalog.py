"""Tests para ``areas.alimentacion.data.data_DispCatalog.DataDispCatalog``.

Fase 3, paso 3.2.1.  Cobertura:
  - defaults razonables al instanciar sin argumentos (5 campos
    del payload de ``GET /api/v1/catalog``).
  - mutabilidad (``frozen=False``).
  - ``default_factory`` produce listas/dicts independientes
    entre instancias.
  - ``to_dict()`` emite el shape estable de 5 keys.
  - ``to_dict()`` hace copia defensiva (mutar el snapshot NO
    afecta al original).
"""
from __future__ import annotations

from areas.alimentacion.data.data_DispCatalog import DataDispCatalog


def test_defaults_vacios():
    """DataDispCatalog() sin argumentos da un catalogo inicial valido."""
    cat = DataDispCatalog()

    assert cat.device_tabs == []
    assert cat.nmax == []
    assert cat.model_columns == {}
    assert cat.col_labels == {}
    assert cat.mono_cols == []


def test_mutabilidad_campos_asignacion_directa():
    """``frozen=False``: puedo reasignar cada campo directamente."""
    cat = DataDispCatalog()

    cat.device_tabs = [{"hw_type": "ed", "canonical": "DispED", "label": "ED"}]
    cat.nmax = [{"name": "N_MAX_DISP_ED", "label": "num_disp_ed"}]
    cat.model_columns = {"DispED": ["uid", "numero", "plc_tag"]}
    cat.col_labels = {"uid": "UID"}
    cat.mono_cols = ["uid", "plc_tag"]

    assert cat.device_tabs == [
        {"hw_type": "ed", "canonical": "DispED", "label": "ED"}
    ]
    assert cat.nmax == [{"name": "N_MAX_DISP_ED", "label": "num_disp_ed"}]
    assert cat.model_columns == {"DispED": ["uid", "numero", "plc_tag"]}
    assert cat.col_labels == {"uid": "UID"}
    assert cat.mono_cols == ["uid", "plc_tag"]


def test_colecciones_independientes_entre_instancias():
    """``default_factory`` evita que dos instancias compartan colecciones."""
    c1 = DataDispCatalog()
    c2 = DataDispCatalog()

    assert c1.device_tabs is not c2.device_tabs
    assert c1.nmax is not c2.nmax
    assert c1.model_columns is not c2.model_columns
    assert c1.col_labels is not c2.col_labels
    assert c1.mono_cols is not c2.mono_cols

    # Mutar uno no afecta al otro.
    c1.device_tabs.append({"hw_type": "ed"})
    c1.model_columns["DispED"] = ["uid"]
    c1.col_labels["uid"] = "UID"
    c1.mono_cols.append("uid")

    assert c2.device_tabs == []
    assert c2.model_columns == {}
    assert c2.col_labels == {}
    assert c2.mono_cols == []


def test_to_dict_shape_vacio():
    """``to_dict()`` de un catalogo vacio emite las 5 keys esperadas."""
    cat = DataDispCatalog()
    snapshot = cat.to_dict()

    assert set(snapshot.keys()) == {
        "device_tabs",
        "nmax",
        "model_columns",
        "col_labels",
        "mono_cols",
    }
    assert snapshot["device_tabs"] == []
    assert snapshot["nmax"] == []
    assert snapshot["model_columns"] == {}
    assert snapshot["col_labels"] == {}
    assert snapshot["mono_cols"] == []


def test_to_dict_con_datos():
    """``to_dict()`` preserva el contenido de los 5 campos."""
    cat = DataDispCatalog(
        device_tabs=[{"hw_type": "ed", "canonical": "DispED", "label": "ED"}],
        nmax=[{"name": "N_MAX_DISP_ED", "label": "num_disp_ed"}],
        model_columns={"DispED": ["uid", "numero"]},
        col_labels={"uid": "UID", "numero": "Número"},
        mono_cols=["uid"],
    )

    snapshot = cat.to_dict()

    assert snapshot["device_tabs"] == [
        {"hw_type": "ed", "canonical": "DispED", "label": "ED"}
    ]
    assert snapshot["nmax"] == [
        {"name": "N_MAX_DISP_ED", "label": "num_disp_ed"}
    ]
    assert snapshot["model_columns"] == {"DispED": ["uid", "numero"]}
    assert snapshot["col_labels"] == {"uid": "UID", "numero": "Número"}
    assert snapshot["mono_cols"] == ["uid"]


def test_to_dict_copia_defensiva():
    """``to_dict()`` hace copia defensiva: mutar el snapshot NO afecta al original."""
    cat = DataDispCatalog(
        device_tabs=[{"hw_type": "ed", "canonical": "DispED", "label": "ED"}],
        model_columns={"DispED": ["uid"]},
        col_labels={"uid": "UID"},
        mono_cols=["uid"],
    )

    snapshot = cat.to_dict()

    # Mutar el snapshot NO afecta al estado del DB.
    snapshot["device_tabs"].append({"hw_type": "ea"})
    snapshot["device_tabs"][0]["label"] = "MUTATED"
    snapshot["model_columns"]["DispED"].append("MUTATED")
    snapshot["model_columns"]["NEW_KEY"] = ["x"]
    snapshot["col_labels"]["NEW"] = "MUTATED"
    snapshot["mono_cols"].append("MUTATED")

    # El original esta intacto.
    assert cat.device_tabs == [
        {"hw_type": "ed", "canonical": "DispED", "label": "ED"}
    ]
    assert cat.model_columns == {"DispED": ["uid"]}
    assert cat.col_labels == {"uid": "UID"}
    assert cat.mono_cols == ["uid"]


def test_to_dict_device_tabs_items_son_copias():
    """``to_dict()`` copia cada dict de device_tabs (no aliasing)."""
    tab = {"hw_type": "ed", "canonical": "DispED", "label": "ED"}
    cat = DataDispCatalog(device_tabs=[tab])

    snapshot = cat.to_dict()

    # El dict del item NO es el mismo objeto que el del caller.
    assert snapshot["device_tabs"][0] is not tab
    assert snapshot["device_tabs"][0] == tab

    # Mutar el dict del caller NO afecta al snapshot.
    tab["label"] = "MUTATED"
    assert snapshot["device_tabs"][0]["label"] == "ED"
