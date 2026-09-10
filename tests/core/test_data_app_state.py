"""Tests para ``core.data.data_app_state.DataAppState``.

Fase 3, paso 3.1.4.  Cobertura:
  - defaults razonables al instanciar sin argumentos.
  - mutabilidad (``frozen=False``): puedo reasignar campos
    primitivos y el dict.
  - ``default_factory`` produce dicts independientes entre
    instancias (no se comparte estado por accidente).
  - ``set_devices(hw, devs)`` copia la lista (defensivo contra
    aliasing con el caller).
  - ``to_dict()`` shape estable: 4 keys, ``excel_loaded`` flag
    en lugar de ``excel_cache``.
  - ``to_dict()`` hace copia defensiva de ``dispositivos`` y
    ``dimensiones`` (mutar el dict devuelto no afecta al
    original).
"""
from __future__ import annotations

from core.data.data_app_state import DataAppState


def test_defaults_vacios():
    """DataAppState() sin argumentos da un estado inicial valido."""
    state = DataAppState()

    assert state.dispositivos == {}
    assert state.dimensiones == {}
    assert state.excel_cache is None
    assert state.excel_path is None


def test_mutabilidad_campos_primitivos():
    """``frozen=False``: puedo reasignar campos primitivos."""
    state = DataAppState()

    state.excel_path = "C:/datos/maestro.xlsx"
    assert state.excel_path == "C:/datos/maestro.xlsx"

    sentinel = object()
    state.excel_cache = sentinel
    assert state.excel_cache is sentinel


def test_mutabilidad_dicts_asignacion_directa():
    """``frozen=False``: puedo reasignar el dict completo."""
    state = DataAppState()

    state.dispositivos = {"ED": ["a", "b"], "EA": ["x"]}
    state.dimensiones = {"MAX_DISP": 100}

    assert state.dispositivos == {"ED": ["a", "b"], "EA": ["x"]}
    assert state.dimensiones == {"MAX_DISP": 100}


def test_dictionaries_independientes_entre_instancias():
    """``default_factory`` evita que dos instancias compartan dicts."""
    s1 = DataAppState()
    s2 = DataAppState()

    assert s1.dispositivos is not s2.dispositivos
    assert s1.dimensiones is not s2.dimensiones

    s1.dispositivos["ED"] = ["d1"]
    s1.dimensiones["MAX"] = 50
    assert s2.dispositivos == {}
    assert s2.dimensiones == {}


def test_set_devices_copia_lista():
    """``set_devices`` copia la lista (defensivo contra aliasing)."""
    state = DataAppState()
    lista_original = ["disp_1", "disp_2"]

    state.set_devices("ED", lista_original)

    # La lista guardada NO es la misma instancia que la del caller.
    assert state.dispositivos["ED"] is not lista_original
    assert state.dispositivos["ED"] == lista_original

    # Mutar la lista del caller NO afecta al estado.
    lista_original.append("disp_3")
    assert state.dispositivos["ED"] == ["disp_1", "disp_2"]


def test_to_dict_shape_vacio():
    """``to_dict()`` de un estado vacio emite las 4 keys esperadas."""
    state = DataAppState()
    snapshot = state.to_dict()

    assert set(snapshot.keys()) == {
        "dispositivos",
        "dimensiones",
        "excel_loaded",
        "excel_path",
    }
    assert snapshot["dispositivos"] == {}
    assert snapshot["dimensiones"] == {}
    assert snapshot["excel_loaded"] is False
    assert snapshot["excel_path"] is None


def test_to_dict_excel_loaded_es_flag_no_cache():
    """``to_dict()`` emite ``excel_loaded`` (bool) y NO el cache."""
    state = DataAppState()
    state.excel_cache = object()  # cualquier cosa no-JSON
    state.excel_path = "C:/datos/maestro.xlsx"

    snapshot = state.to_dict()

    # El flag refleja si hay cache; el cache en si NO se serializa.
    assert snapshot["excel_loaded"] is True
    assert "excel_cache" not in snapshot
    assert snapshot["excel_path"] == "C:/datos/maestro.xlsx"


def test_to_dict_copia_defensiva():
    """``to_dict()`` hace copia defensiva de dispositivos y dimensiones."""
    state = DataAppState()
    state.dispositivos["ED"] = ["a", "b"]
    state.dimensiones["MAX"] = 10

    snapshot = state.to_dict()

    # Mutar el snapshot NO afecta al estado original.
    snapshot["dispositivos"]["ED"].append("c")
    snapshot["dimensiones"]["NUEVO"] = 99

    assert state.dispositivos == {"ED": ["a", "b"]}
    assert state.dimensiones == {"MAX": 10}
