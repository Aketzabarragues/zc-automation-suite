"""El calculo del sync de un proceso: los mapas de apply y los N_MAX.

Que se escribe en los SimaticSD exportados y que se aplica en linea. Es
logica pura: aqui no hay ni portal de TIA ni transacciones.
"""
from __future__ import annotations

from pathlib import Path

from zc_suite.areas.alimentacion.dispositivos.diferencias import DiffNMax
from zc_suite.areas.alimentacion.procesos.sincronizacion import (
    ARRAYS_PROCESO,
    proc_arrays_para_apply,
    proc_confirmar_db,
    proc_localizar_db,
    proc_mapa_apply,
    proc_operaciones_n_max,
)

# ── localizar los SimaticSD ─────────────────────────────────────────────────


def test_localizar_db_plano(tmp_path: Path) -> None:
    dcl = tmp_path / "DB53100_CPR_PARAM.s7dcl"
    dcl.write_text("END_DATA_BLOCK\n", encoding="utf-8")
    (tmp_path / "DB53100_CPR_PARAM.s7res").write_text("MultiLingualTexts: []\n", encoding="utf-8")
    par = proc_localizar_db(tmp_path, "DB53100_CPR_PARAM")
    assert par is not None
    assert par[0].name == "DB53100_CPR_PARAM.s7dcl"
    assert par[1].name == "DB53100_CPR_PARAM.s7res"


def test_localizar_db_con_jerarquia(tmp_path: Path) -> None:
    carpeta = tmp_path / "Program" / "DBs"
    carpeta.mkdir(parents=True)
    (carpeta / "DB53100_CPR_PARAM.s7dcl").write_text("END_DATA_BLOCK\n", encoding="utf-8")
    (carpeta / "DB53100_CPR_PARAM.s7res").write_text("MultiLingualTexts: []\n", encoding="utf-8")
    par = proc_localizar_db(tmp_path, "DB53100_CPR_PARAM")
    assert par is not None
    assert par[0] == carpeta / "DB53100_CPR_PARAM.s7dcl"
    assert par[1] == carpeta / "DB53100_CPR_PARAM.s7res"


def test_localizar_db_ausente(tmp_path: Path) -> None:
    assert proc_localizar_db(tmp_path, "DB53100_CPR_PARAM") is None


def test_localizar_db_sin_carpeta(tmp_path: Path) -> None:
    assert proc_localizar_db(tmp_path / "no_existe", "DB53100_CPR_PARAM") is None


# ── el mapa de apply ────────────────────────────────────────────────────────


def test_mapa_apply_es_el_excel_mas_los_slots_que_sobran() -> None:
    slot_map = {0: "NO USAR", 1: "P1", 2: "P2"}
    actuales = {1: "P1", 2: "P2 viejo", 3: "sobra"}
    assert proc_mapa_apply(slot_map, actuales) == {
        0: "NO USAR",
        1: "P1",
        2: "P2",
        3: "",
    }


def test_mapa_apply_no_toca_el_slot_con_comentario_vacio() -> None:
    slot_map = {0: "NO USAR", 1: "P1"}
    actuales = {1: "P1", 3: ""}
    assert proc_mapa_apply(slot_map, actuales) == {0: "NO USAR", 1: "P1"}


def test_mapa_apply_sin_actuales_lleva_todos_los_slots_del_excel() -> None:
    slot_map = {0: "NO USAR", 1: "P1"}
    assert proc_mapa_apply(slot_map, {}) == {0: "NO USAR", 1: "P1"}


def test_mapa_apply_degradado_sin_db_leido_aplica_el_excel_completo() -> None:
    # Modo degradado: el DB no se pudo leer (actuales vacio) pero el Excel
    # dice que hay slots: se aplican todos.
    slot_map = {0: "NO USAR", 1: "P1", 2: "."}
    assert proc_mapa_apply(slot_map, {}) == {0: "NO USAR", 1: "P1", 2: "."}


def test_mapa_apply_vacio_si_solo_hay_slot_cero() -> None:
    assert proc_mapa_apply({0: "NO USAR"}, {1: "sobra"}) == {}


def test_mapa_apply_vacio_si_no_hay_slots_del_excel() -> None:
    # Sin filas del Excel no se aplica nada, aunque TIA tenga slots.
    assert proc_mapa_apply({0: "NO USAR"}, {1: "sobra", 2: ""}) == {}


# ── los arrays por DB ───────────────────────────────────────────────────────


def _mapa_de_prueba() -> dict[str, dict[int, str]]:
    return {
        "preal": {0: "NO USAR", 1: "P1"},
        "pint": {0: "NO USAR"},
        "alm": {0: "NO USAR", 1: "A1"},
    }


def test_arrays_para_apply_con_todos_los_db() -> None:
    resultados = proc_arrays_para_apply(
        _mapa_de_prueba(), "DB53100_CPR_PARAM", "DB53100_CPR_ALM", []
    )
    assert set(resultados) == {"DB53100_CPR_PARAM", "DB53100_CPR_ALM"}
    param = resultados["DB53100_CPR_PARAM"]
    assert set(param) == {
        "PReal", "PReal_Vis", "Aux.PReal_ValorAnterior",
        "PInt", "PInt_Vis", "Aux.PInt_ValorAnterior",
    }
    # Los satelites reciben el mismo mapa que su principal.
    assert param["PReal_Vis"] == param["PReal"]
    assert param["Aux.PReal_ValorAnterior"] == param["PReal"]
    assert param["PInt_Vis"] == param["PInt"]
    assert param["Aux.PInt_ValorAnterior"] == param["PInt"]
    assert resultados["DB53100_CPR_ALM"] == {"ALM": {0: "NO USAR", 1: "A1"}}


def test_arrays_para_apply_falta_db_param() -> None:
    resultados = proc_arrays_para_apply(
        _mapa_de_prueba(), "DB53100_CPR_PARAM", "DB53100_CPR_ALM", ["DB53100_CPR_PARAM"]
    )
    assert set(resultados) == {"DB53100_CPR_ALM"}
    assert resultados["DB53100_CPR_ALM"] == {"ALM": {0: "NO USAR", 1: "A1"}}


def test_arrays_para_apply_falta_db_alm() -> None:
    resultados = proc_arrays_para_apply(
        _mapa_de_prueba(), "DB53100_CPR_PARAM", "DB53100_CPR_ALM", ["DB53100_CPR_ALM"]
    )
    assert set(resultados) == {"DB53100_CPR_PARAM"}
    assert "PReal" in resultados["DB53100_CPR_PARAM"]


# ── el apply sobre los ficheros ─────────────────────────────────────────────


def test_confirmar_db_escribe_el_excel_y_borra_los_sobrantes(tmp_path: Path) -> None:
    db = "DB53100_CPR_ALM"
    dcl = tmp_path / f"{db}.s7dcl"
    res = tmp_path / f"{db}.s7res"
    dcl.write_text(
        "END_DATA_BLOCK_MARKER\n"
        "DATA_BLOCK DB53100_CPR_ALM\n"
        '    { S7_MLC := "MLC_alm0" }\n'
        "        ALM[0] := ();\n"
        '    { S7_MLC := "MLC_alm1" }\n'
        "        ALM[1] := ();\n"
        '    { S7_MLC := "MLC_alm2" }\n'
        "        ALM[2] := ();\n"
        "END_DATA_BLOCK\n",
        encoding="utf-8",
    )
    res.write_text(
        "MultiLingualTexts:\n"
        "  - id: MLC_alm0\n"
        "    es-ES: NO USAR\n"
        "  - id: MLC_alm1\n"
        "    es-ES: Alarme 1\n"
        "  - id: MLC_alm2\n"
        "    es-ES: Sobra\n"
        "\n",
        encoding="utf-8",
    )
    modificados = proc_confirmar_db(
        tmp_path,
        db,
        {"ALM": {0: "NO USAR", 1: "Alarme 1 nueva"}},
        {"ALM": {0: "NO USAR", 1: "Alarme 1", 2: "Sobra"}},
    )
    assert modificados == 1
    dcl_text = dcl.read_text(encoding="utf-8")
    res_text = res.read_text(encoding="utf-8")
    # El slot 1 se renombra, el slot 2 se borra, el slot 0 queda como el Excel.
    assert "Alarme 1 nueva" in res_text
    assert "Sobra" not in res_text
    assert "MLC_alm2" not in dcl_text


def test_confirmar_db_solo_slot_cero_no_escribe(tmp_path: Path) -> None:
    db = "DB53100_CPR_ALM"
    dcl = tmp_path / f"{db}.s7dcl"
    res = tmp_path / f"{db}.s7res"
    dcl.write_text(
        "END_DATA_BLOCK_MARKER\n"
        "DATA_BLOCK DB53100_CPR_ALM\n"
        '    { S7_MLC := "MLC_alm0" }\n'
        "        ALM[0] := ();\n"
        "END_DATA_BLOCK\n",
        encoding="utf-8",
    )
    res.write_text(
        "MultiLingualTexts:\n"
        "  - id: MLC_alm0\n"
        "    es-ES: NO USAR\n"
        "\n",
        encoding="utf-8",
    )
    dcl_original = dcl.read_text(encoding="utf-8")
    res_original = res.read_text(encoding="utf-8")
    modificados = proc_confirmar_db(
        tmp_path, db, {"ALM": {0: "NO USAR"}}, {"ALM": {0: "NO USAR"}}
    )
    assert modificados == 0
    assert dcl.read_text(encoding="utf-8") == dcl_original
    assert res.read_text(encoding="utf-8") == res_original


def test_confirmar_db_ausente_en_la_exportacion(tmp_path: Path) -> None:
    assert proc_confirmar_db(
        tmp_path,
        "DB53100_CPR_ALM",
        {"ALM": {0: "NO USAR", 1: "A1"}},
        {"ALM": {0: "NO USAR", 1: "A1"}},
    ) == 0


# ── los N_MAX ───────────────────────────────────────────────────────────────


def _fila(kind: str, name: str, actual: int | None, nuevo: int, status: str) -> dict:
    return {"kind": kind, "name": name, "actual": actual, "nuevo": nuevo, "status": status}


def _diff_n_max() -> DiffNMax:
    return DiffNMax(
        tabla="100_CPR",
        actual={"100_N_MAX_PREAL": 3, "100_N_MAX_PINT": 2},
        deseado={"100_N_MAX_PREAL": 4, "100_N_MAX_PINT": 2},
        todos=[
            _fila("preal", "100_N_MAX_PREAL", 3, 4, "actualizar"),
            _fila("pint", "100_N_MAX_PINT", 2, 2, "igual"),
        ],
        resumen={"igual": 1, "actualizar": 1, "falta": 0},
        xml_ausente=False,
    )


def test_operaciones_n_max_solo_los_que_cambian_y_estan_en_tia() -> None:
    ops = proc_operaciones_n_max("100_CPR", _diff_n_max())
    assert ops == [{"tabla": "100_CPR", "constante": "100_N_MAX_PREAL", "valor": 4}]


def test_operaciones_n_max_vacias_si_no_hay_cambios() -> None:
    diff = DiffNMax(
        tabla="100_CPR",
        actual={"100_N_MAX_PREAL": 3},
        deseado={"100_N_MAX_PREAL": 3},
        todos=[
            _fila("preal", "100_N_MAX_PREAL", 3, 3, "igual"),
        ],
        resumen={"igual": 1, "actualizar": 0, "falta": 0},
        xml_ausente=False,
    )
    assert proc_operaciones_n_max("100_CPR", diff) == []


def test_operaciones_n_max_no_toca_los_que_no_estan_en_tia() -> None:
    diff = DiffNMax(
        tabla="100_CPR",
        actual={},
        deseado={"100_N_MAX_PREAL": 4},
        todos=[
            _fila("preal", "100_N_MAX_PREAL", None, 4, "falta"),
        ],
        resumen={"igual": 0, "actualizar": 0, "falta": 1},
        xml_ausente=False,
    )
    assert proc_operaciones_n_max("100_CPR", diff) == []


# ── el orden de los arrays ──────────────────────────────────────────────────


def test_el_orden_de_los_arrays_es_el_de_main() -> None:
    assert [nombre for nombre, _tipo, _principal in ARRAYS_PROCESO] == [
        "PReal",
        "PReal_Vis",
        "Aux.PReal_ValorAnterior",
        "PInt",
        "PInt_Vis",
        "Aux.PInt_ValorAnterior",
    ]
