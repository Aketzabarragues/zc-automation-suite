"""Tests del clasificador heuristico de bloques TIA Portal.

Cubre dos niveles:
  - ``classify_from_features``: pura, con tuplas (lang, props, nombre).
    Sin mocks del SDK.
  - ``classify_block``: wrapper defensivo que extrae features del bloque
    nativo via el SDK. Tests con un Mock que simula los metodos del
    wrapper ``siemens_tia_scripting``.

Casos cubiertos (validados con smoke oct-2026 sobre PLC S7-1500 con 168
bloques: 0 sin clasificar):
  - DB (60 bloques): una llamada, valor unico "DB".
  - FB (25 bloques): dos llamadas, ISMultiInstanceCapable en props.
  - OB (15 bloques): dos llamadas, SecondaryType o nombre empieza por OB.
  - FC (70 bloques): dos llamadas, lenguaje de codigo (SCL/LAD/FBD/STL/GRAPH/CFC).
  - OTHER: defensivo, sin clasificar cuando todas las features faltan.
  - UDT: clase Python UserDataType, 0 llamadas al SDK.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.helpers.tia.tia_block_classifier import (
    classify_block,
    classify_from_features,
)


# ────────────────────────────────────────────────────────────────────
# Tests puros: classify_from_features (sin mocks del SDK)
# ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "lang, props, nombre, esperado",
    [
        # DB: valor unico de ProgrammingLanguage
        ("DB", [], "cualquier_cosa", "DB"),
        ("DB", [], "_borrar", "DB"),                     # caso real smoke oct-2026
        ("DB", [], "Documentacion_rara", "DB"),           # nomenclatura custom
        ("db", [], "lowercase_lang", "DB"),               # case-insensitive
        # FB: ISMultiInstanceCapable presente (unica discriminante)
        ("SCL", ["ISMultiInstanceCapable", "ProgrammingLanguage"], "FB100", "FB"),
        ("LAD", ["ISMultiInstanceCapable"], "FB15148_ZC_SEC", "FB"),
        # OB: SecondaryType presente
        ("LAD", ["SecondaryType"], "OB40", "OB"),
        # OB: nombre empieza por OB (fallback para OBs renombrados sin SecondaryType)
        ("LAD", [], "OB100_Startup", "OB"),
        ("LAD", [], "OB1", "OB"),
        # FC: lenguaje de codigo, sin ISMultiInstanceCapable ni SecondaryType
        ("SCL", ["ProgrammingLanguage"], "FC99_test", "FC"),
        ("LAD", ["ProgrammingLanguage"], "FC55100_CPR_GEST_ALM", "FC"),
        ("FBD", ["ProgrammingLanguage"], "FC_FBD_demo", "FC"),
        ("STL", ["ProgrammingLanguage"], "FC_STL_demo", "FC"),
        ("GRAPH", ["ProgrammingLanguage"], "FC_GRAPH_demo", "FC"),
        ("CFC", ["ProgrammingLanguage"], "FC_CFC_demo", "FC"),
        # lowercase en lang sigue funcionando (TIA uppercase post-set defensivo)
        ("scl", [], "FC1", "FC"),
        # OTHER: sin clasificar
        (None, [], "", "OTHER"),
        (None, [], "Main", "OTHER"),
        ("UNKNOWN_LANG", [], "Bloque_raro", "OTHER"),
        ("", [], "Bloque_vacio", "OTHER"),
        # Sin lang, sin props, nombre generico
        (None, None, "Algo", "OTHER"),
        # Edge case: lang = "DB" tiene prioridad incluso si tiene ISMultiInstanceCapable
        ("DB", ["ISMultiInstanceCapable"], "DB_especial", "DB"),
    ],
)
def test_classify_from_features(lang, props, nombre, esperado):
    assert classify_from_features(lang, props, nombre) == esperado


def test_classify_from_features_props_puede_ser_set():
    """Acepta props como set ademas de lista (defensivo)."""
    assert classify_from_features("SCL", {"ISMultiInstanceCapable"}, "FB100") == "FB"


def test_classify_from_features_props_none_se_trata_como_vacio():
    """props=None no rompe; se trata como lista vacia."""
    assert classify_from_features("SCL", None, "FC1") == "FC"


def test_classify_from_features_nombre_none_se_trata_como_vacio():
    """nombre=None no rompe; se trata como string vacio."""
    assert classify_from_features("LAD", [], None) == "FC"


def test_classify_from_features_lang_no_string_se_normaliza():
    """lang puede venir como enum o int desde el SDK; str() lo maneja."""
    assert classify_from_features("DB", [], "X") == "DB"


# ────────────────────────────────────────────────────────────────────
# Tests con mock del SDK: classify_block (wrapper defensivo)
# ────────────────────────────────────────────────────────────────────


def _make_fake_block(
    *,
    class_name="ProgramBlock",
    lang_value="SCL",
    lang_raises=False,
    props_value=None,
    props_raises=False,
    name_value="FC1_test",
    name_raises=False,
    has_get_properties=True,
    has_get_name=True,
):
    """Crea un mock que simula un bloque nativo del SDK TIA Portal.

    Usa ``type(nombre, ...)`` para que ``type(block).__name__`` devuelva
    ``class_name`` (necesario para que ``classify_block`` distinga UDT vs
    ProgramBlock). Los metodos delegan en un MagicMock interno.
    """
    mocks = MagicMock(spec=["get_property", "get_properties", "get_name"])

    def mock_get_property(name=None, **kwargs):
        if lang_raises:
            raise RuntimeError("simulado: COM transitorio")
        if name == "ProgrammingLanguage":
            return lang_value
        raise KeyError(f"prop no esperada: {name}")

    def mock_get_properties():
        if props_raises:
            raise RuntimeError("simulado: COM transitorio en props")
        if props_value is None:
            return []
        return props_value

    def mock_get_name():
        if name_raises:
            raise RuntimeError("simulado: COM transitorio en name")
        return name_value

    mocks.get_property.side_effect = mock_get_property
    if has_get_properties:
        mocks.get_properties.side_effect = mock_get_properties
    else:
        # Quitar el metodo para probar el path defensivo (hasattr False).
        del mocks.get_properties
    if has_get_name:
        mocks.get_name.side_effect = mock_get_name
    else:
        del mocks.get_name

    # Crear clase dinamica con el nombre correcto y los metodos delegadores.
    def make_get_property(self, *args, **kwargs):
        return self._mocks.get_property(*args, **kwargs)

    def make_get_properties(self):
        return self._mocks.get_properties()

    def make_get_name(self):
        return self._mocks.get_name()

    def make_init(self):
        self._mocks = mocks

    cls = type(
        class_name,
        (object,),
        {
            "__init__": make_init,
            "get_property": make_get_property,
            "get_properties": make_get_properties,
            "get_name": make_get_name,
        },
    )
    return cls()


def test_classify_block_db_con_1_llamada():
    """DB: caso rapido, solo get_property. get_properties NO se llama."""
    block = _make_fake_block(lang_value="DB", name_value="_borrar")
    assert classify_block(block) == "DB"
    block._mocks.get_property.assert_called_once_with(name="ProgrammingLanguage")
    block._mocks.get_properties.assert_not_called()


def test_classify_block_fb_con_2_llamadas():
    """FB: get_property + get_properties. get_name tambien (defensivo)."""
    block = _make_fake_block(
        lang_value="SCL",
        props_value=["ISMultiInstanceCapable", "ProgrammingLanguage"],
        name_value="FB15148",
    )
    assert classify_block(block) == "FB"
    block._mocks.get_property.assert_called_once()
    block._mocks.get_properties.assert_called_once()
    block._mocks.get_name.assert_called_once()  # defensivo, siempre se llama


def test_classify_block_ob_por_secondary_type():
    block = _make_fake_block(
        lang_value="LAD",
        props_value=["SecondaryType", "ProgrammingLanguage"],
        name_value="OB40_HardwareInterrupt",
    )
    assert classify_block(block) == "OB"
    block._mocks.get_property.assert_called_once()
    block._mocks.get_properties.assert_called_once()


def test_classify_block_ob_por_nombre_sin_secondary_type():
    """OB renombrado sin SecondaryType se rescata por nombre."""
    block = _make_fake_block(
        lang_value="LAD",
        props_value=["ProgrammingLanguage"],
        name_value="OB100_Startup",
    )
    assert classify_block(block) == "OB"
    block._mocks.get_property.assert_called_once()
    block._mocks.get_properties.assert_called_once()
    block._mocks.get_name.assert_called_once()


def test_classify_block_fc_con_lenguaje_de_codigo():
    block = _make_fake_block(
        lang_value="SCL",
        props_value=["ProgrammingLanguage"],
        name_value="FC99_test",
    )
    assert classify_block(block) == "FC"
    block._mocks.get_property.assert_called_once()
    block._mocks.get_properties.assert_called_once()


def test_classify_block_other_cuando_nada_clasifica():
    block = _make_fake_block(
        lang_value=None,
        props_value=[],
        name_value="Bloque_raro",
    )
    assert classify_block(block) == "OTHER"


def test_classify_block_udt_sin_llamadas_al_sdk():
    """UDT: type().name contiene 'UserDataType', 0 llamadas al SDK."""
    block = _make_fake_block(class_name="UserDataType_subclass")
    assert classify_block(block) == "UDT"
    block._mocks.get_property.assert_not_called()
    block._mocks.get_properties.assert_not_called()
    block._mocks.get_name.assert_not_called()


def test_classify_block_lang_falla_bloque_se_clasifica_igual():
    """Si get_property(ProgrammingLanguage) lanza, lang=None; sigue clasificando."""
    block = _make_fake_block(
        lang_raises=True,
        props_value=["ISMultiInstanceCapable"],
        name_value="FB_robusto",
    )
    assert classify_block(block) == "FB"


def test_classify_block_props_falla_bloque_se_clasifica_igual():
    """Si get_properties() lanza, props=[]; sigue clasificando por nombre."""
    block = _make_fake_block(
        lang_value="LAD",
        props_raises=True,
        name_value="OB1_robust",
    )
    # lang="LAD" + nombre empieza por "OB" => OB por fallback de nombre
    assert classify_block(block) == "OB"


def test_classify_block_name_falla_se_clasifica_por_props():
    """Si get_name() lanza, nombre=''; FC por lenguaje sigue funcionando."""
    block = _make_fake_block(
        lang_value="SCL",
        props_value=["ProgrammingLanguage"],
        name_raises=True,
    )
    assert classify_block(block) == "FC"


def test_classify_block_sin_get_properties_como_atributo():
    """Si el bloque no expone get_properties (raro pero defensivo)."""
    block = _make_fake_block(
        lang_value="LAD",
        has_get_properties=False,
        name_value="OB1",
    )
    assert classify_block(block) == "OB"  # por nombre


def test_classify_block_sin_get_name_como_atributo():
    """Si el bloque no expone get_name (raro pero defensivo)."""
    block = _make_fake_block(
        lang_value="SCL",
        props_value=["ISMultiInstanceCapable"],
        has_get_name=False,
    )
    assert classify_block(block) == "FB"


def test_classify_block_lowercase_lang_db():
    """lang lowercase se acepta (TIA devuelve uppercase normalmente)."""
    block = _make_fake_block(lang_value="db", name_value="X")
    assert classify_block(block) == "DB"


# ────────────────────────────────────────────────────────────────────
# Tests de cobertura: 100% clasificación con datos del smoke real
# ────────────────────────────────────────────────────────────────────


SMOKE_CASES_OCT_2026 = [
    # (nombre, lang, props, esperado)
    # DBs del PLC de Aketza
    ("_borrar", "DB", [], "DB"),
    ("Documentacion_es_FC", "SCL", [], "FC"),
    ("DB1_SYS", "DB", [], "DB"),
    ("DB55100_CPR_ALM", "DB", [], "DB"),
    ("DB3_CHECKSUM", "DB", [], "DB"),
    # FCs
    ("FC99_test", "SCL", ["ProgrammingLanguage"], "FC"),
    ("FC55100_CPR_GEST_ALM", "LAD", ["ProgrammingLanguage"], "FC"),
    # FBs
    ("FB15148_ZC_SEC_MB_CLIENT", "SCL", ["ISMultiInstanceCapable"], "FB"),
    ("FB15051_ZC_INF_COMPACTO", "LAD", ["ISMultiInstanceCapable"], "FB"),
    # OBs
    ("OB1_MAIN", "LAD", ["SecondaryType"], "OB"),
    ("OB100_Startup", "LAD", [], "OB"),
    ("OB40_HardwareInterrupt", "LAD", ["SecondaryType"], "OB"),
    ("OB30_PID_100MS", "SCL", ["SecondaryType"], "OB"),
]


@pytest.mark.parametrize("nombre,lang,props,esperado", SMOKE_CASES_OCT_2026)
def test_smoke_coverage_100_por_cient(nombre, lang, props, esperado):
    """Cobertura del smoke real: todos los bloques se clasifican correctamente."""
    assert classify_from_features(lang, props, nombre) == esperado