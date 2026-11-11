"""Tests del parseo del Excel maestro y de la cache del area.

Ningun test toca TIA: el Excel se construye aqui mismo y el portal no hace
falta para nada.

El test de paridad usa el Excel completo (una fila de cada dominio) y
comprueba que el modelo sale con los mismos campos y los mismos valores que
daba el ``ExcelLoader`` de ``main``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from openpyxl import Workbook, load_workbook

from zc_suite.areas.alimentacion.excel import almacen as modulo_almacen
from zc_suite.areas.alimentacion.excel import parser
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel
from zc_suite.tia_ops import OperacionError

# ── el modelo completo, campo a campo ───────────────────────────────────────

#: Los campos de cada tipo de dispositivo, como en los DTO de ``main``.
CAMPOS_DISPOSITIVOS: dict[str, set[str]] = {
    "DispED": {
        "numero", "plc_tag", "plc_comentario", "descripcion", "uid", "tag", "fat",
        "e_byte", "e_bit", "gr_alarma", "cuadro", "observaciones", "plc_tipo",
        "plc_index", "hmi_index", "hmi_texto", "cfg_habilitar", "cfg_byte_entrada",
        "cfg_bit_entrada", "cfg_grupo_alarma", "comentario_db", "plc_name",
    },
    "DispEA": {
        "numero", "plc_tag", "plc_comentario", "descripcion", "uid", "tag", "fat",
        "e_byte", "unidades", "rii", "rsi", "gr_alarma", "cuadro", "observaciones",
        "plc_tipo", "plc_index", "hmi_index", "hmi_texto", "cfg_habilitar",
        "cfg_byte_entrada", "cfg_escaladomin", "cfg_escaladomax", "cfg_grupo_alarma",
        "comentario_db", "plc_name",
    },
    "DispSD": {
        "numero", "plc_tag", "plc_comentario", "descripcion", "uid", "tag", "fat",
        "s_byte", "s_bit", "gr_alarma", "cuadro", "observaciones", "plc_tipo",
        "plc_index", "hmi_index", "hmi_texto", "cfg_habilitar", "cfg_byte_entrada",
        "cfg_bit_entrada", "cfg_grupo_alarma", "comentario_db", "plc_name",
    },
    "DispV": {
        "numero", "plc_tag", "plc_comentario", "descripcion", "uid", "tag", "fat",
        "s_byte", "s_bit", "rr_byte", "rr_bit", "rt_byte", "rt_bit", "gr_alarma",
        "cuadro", "observaciones", "plc_tipo", "plc_index", "hmi_index", "hmi_texto",
        "cfg_habilitar", "cfg_byteretornoreposo", "cfg_bitretornoreposo",
        "cfg_byteretornotrabajo", "cfg_bitretornotrabajo", "cfg_byteactivacion",
        "cfg_bitactivacion", "cfg_habitreposo", "cfg_habitrtrabajo", "cfg_grupoalarma",
        "comentario_db", "plc_name",
    },
    "DispM": {
        "numero", "plc_tag", "plc_comentario", "descripcion", "uid", "tag", "fat",
        "s_byte", "s_bit", "rt_byte", "rt_bit", "rm_byte", "rm_bit", "gr_alarma",
        "cuadro", "observaciones", "plc_tipo", "plc_index", "hmi_index", "hmi_texto",
        "cfg_habilitar", "cfg_byteretornotermico", "cfg_bitretornotermico",
        "cfg_byteconfmarcha", "cfg_bitconfmarcha", "cfg_byteactivacion",
        "cfg_bitactivacion", "cfg_habrettermico", "cfg_habretconfmarcha",
        "cfg_grupo_alarma", "comentario_db", "plc_name",
    },
    "DispM_VF": {
        "numero", "plc_tag", "plc_comentario", "descripcion", "uid", "tag", "fat",
        "s_byte", "s_bit", "rt_byte", "rt_bit", "rm_byte", "rm_bit", "gr_alarma",
        "cuadro", "observaciones", "plc_tipo", "plc_index", "hmi_index", "hmi_texto",
        "cfg_habilitar", "cfg_byteretornotermico", "cfg_bitretornotermico",
        "cfg_byteconfmarcha", "cfg_bitconfmarcha", "cfg_byteactivacion",
        "cfg_bitactivacion", "cfg_habrettermico", "cfg_habretconfmarcha",
        "cfg_grupo_alarma", "comentario_db", "plc_name", "sa_byte",
        "cfg_byteanalogica",
    },
    "DispM_SINA": {
        "numero", "plc_tag", "plc_comentario", "descripcion", "uid", "tag", "fat",
        "rt_byte", "rt_bit", "vel_min", "vel_max", "cons_k", "gr_alarma", "cuadro",
        "observaciones", "plc_tipo", "plc_index", "hmi_index", "hmi_texto",
        "cfg_habilitar", "cfg_byteretornotermico", "cfg_bitretornotermico",
        "cfg_vel_min", "cfg_vel_max", "cfg_cons_k", "cfg_grupo_alarma",
        "comentario_db", "plc_name",
    },
    "DispTQ": {
        "numero", "plc_tag", "plc_comentario", "descripcion", "uid", "tag", "fat",
        "observaciones", "plc_tipo", "plc_index", "hmi_index", "hmi_texto",
        "cfg_habilitar", "comentario_db", "plc_name",
    },
    "DispTOT": {
        "numero", "plc_tag", "plc_comentario", "descripcion", "uid", "tag", "fat",
        "tipo", "e_byte", "e_bit", "incxpulso", "gr_alarma", "proceso",
        "observaciones", "plc_tipo", "plc_index", "hmi_index", "hmi_texto",
        "cfg_habilitar", "cfg_byteentrada", "cfg_bitentrada", "cfg_tipo",
        "comentario_db", "plc_name",
    },
    "DispPID": {
        "numero", "plc_tag", "plc_comentario", "descripcion", "uid", "tag", "fat",
        "proceso", "pv", "disp_tipo", "disp_tag", "observaciones", "plc_tipo",
        "plc_index", "hmi_index", "hmi_texto", "cfg_habilitar", "comentario_db",
        "plc_name",
    },
}


def _tabla(datos: dict[str, Any], tipo: str) -> dict[str, Any]:
    """La tabla de un tipo de dispositivo del volcado."""
    for tabla in datos["dispositivos"]:
        if tabla["tipo"] == tipo:
            return tabla
    raise AssertionError(f"El volcado no tiene la tabla {tipo}.")


# ── la paridad con main ─────────────────────────────────────────────────────


def test_el_modelo_de_los_dispositivos_tiene_los_campos_de_main(
    excel_completo: Path,
    seccion: dict[str, Any],
) -> None:
    datos = parser.leer_excel(excel_completo, seccion)

    for tipo, campos in CAMPOS_DISPOSITIVOS.items():
        fila = _tabla(datos, tipo)["filas"][0]
        assert set(fila) == campos, f"faltan campos en {tipo}"


def test_los_valores_de_los_dispositivos_son_los_de_main(
    excel_completo: Path,
    seccion: dict[str, Any],
) -> None:
    datos = parser.leer_excel(excel_completo, seccion)

    assert _tabla(datos, "DispED")["filas"] == [
        {
            "numero": 1,
            "plc_tag": "V_ED_001",
            "plc_comentario": "",
            "descripcion": "Entrada digital 1",
            "uid": "ED_001",
            "tag": "",
            "fat": "",
            "plc_tipo": "",
            "plc_index": 0,
            "hmi_index": 0,
            "hmi_texto": "",
            "cfg_habilitar": "",
            "comentario_db": "",
            "plc_name": "PLC1",
            "e_byte": 0,
            "e_bit": 0,
            "gr_alarma": 0,
            "cuadro": "",
            "observaciones": "",
            "cfg_byte_entrada": "",
            "cfg_bit_entrada": "",
            "cfg_grupo_alarma": "",
        }
    ]
    assert _tabla(datos, "DispEA")["filas"][0]["rii"] == 0.0
    assert _tabla(datos, "DispEA")["filas"][0]["rsi"] == 100.0
    assert _tabla(datos, "DispEA")["filas"][0]["uid"] == "EA_001"
    assert _tabla(datos, "DispTOT")["filas"][0]["uid"] == "TOT_001"

def test_los_valores_del_software_son_los_de_main(
    excel_completo: Path,
    seccion: dict[str, Any],
) -> None:
    datos = parser.leer_excel(excel_completo, seccion)

    assert datos["procesos"]["Procesos"]["filas"] == [
        {
            "uid": 1,
            "nombre": "Proceso 1",
            "codigo": "PR1",
            "preal": 1,
            "index_preal": 0,
            "pint": 1,
            "index_pint": 0,
            "alarmas": 16,
            "alm_hmi": 0,
            "plc_name": "PLC1",
        }
    ]
    assert datos["procesos"]["ParametrosReales"]["filas"] == [
        {
            "uid": "PR_1_001",
            "numero": "001",
            "proceso": "Proceso 1",
            "codigo": "PR1",
            "num_db": 3001,
            "producto": "Producto",
            "tipo": "Setpoint",
            "descripcion": "PR1",
            "comentario_db": "c",
            "visibilidad": "Si",
            "num_lista": 1,
            "txt_lista": "Txt",
            "plc_name": "PLC1",
        }
    ]
    assert datos["procesos"]["ParametrosEnteros"]["filas"][0]["num_db"] == 3002
    assert datos["procesos"]["ParametrosEnteros"]["filas"][0]["num_lista"] == 0
    assert datos["procesos"]["Alarmas"]["filas"] == [
        {
            "uid": "AL_1_001",
            "numero": "001",
            "proceso": "Proceso 1",
            "num_db": 5001,
            "descripcion": "Alarma 1",
            "comentario_db": "c",
            "plc_name": "PLC1",
        }
    ]


def test_los_plcs_las_entidades_y_las_dimensiones_son_los_de_main(
    excel_completo: Path,
    seccion: dict[str, Any],
) -> None:
    datos = parser.leer_excel(excel_completo, seccion)

    assert datos["plcs"] == [{"uid": 1, "plc": "PLC1"}]
    assert datos["entidades"]["filas"] == [
        {
            "numero": 1,
            "plc_name": "PLC1",
            "plc_tag": "ent_001",
            "descripcion": "Entidad 1",
            "plc_comentario": "",
            "plc_tipo": 0,
            "plc_index": 0,
        }
    ]
    fila = datos["configuracion"]["filas"][0]
    assert fila["PLC"] == "PLC1"
    assert fila["N_MAX_DISP_ED"] == 10
    assert fila["N_MAX_DISP_EA"] == 20
    assert fila["N_MAX_DISP_PID"] == 90
    assert fila["N_MAX_ENTIDAD"] == 6


# ── las filas ───────────────────────────────────────────────────────────────


def test_una_fila_mala_dice_la_hoja_la_tabla_y_la_fila(
    tmp_path: Path,
    crear_excel: Callable[..., Path],
    seccion: dict[str, Any],
) -> None:
    ruta = crear_excel(
        tmp_path / "malo.xlsx",
        [["PLC1", "ED_001", "no es un numero", "V_ED_001", "Entrada digital", 3, 2]],
    )

    with pytest.raises(OperacionError) as fallo:
        parser.leer_excel(ruta, seccion)

    mensaje = str(fallo.value)
    assert "Fila 2 invalida" in mensaje
    assert "Tabla_Disp_ED" in mensaje
    assert "DISP_ED" in mensaje
    assert "Numero" in mensaje


def test_una_celda_vacia_sale_como_cero_o_vacia(
    tmp_path: Path,
    crear_excel: Callable[..., Path],
    seccion: dict[str, Any],
) -> None:
    ruta = crear_excel(
        tmp_path / "vacias.xlsx",
        [["PLC1", "ED_001", None, "", "Entrada digital", 3, 2]],
    )

    datos = parser.leer_excel(ruta, seccion)

    fila = _tabla(datos, "DispED")["filas"][0]
    assert fila["numero"] == 0
    assert fila["tag"] == ""


def test_una_fila_sin_uid_ni_numero_se_descarta(
    tmp_path: Path,
    crear_excel: Callable[..., Path],
    seccion: dict[str, Any],
) -> None:
    ruta = crear_excel(
        tmp_path / "sin_uid.xlsx",
        [
            ["PLC1", "", None, "", "Entrada digital", 3, 2],
            ["PLC1", "ED_002", 2, "V_ED_002", "Otra", 3, 2],
        ],
    )

    datos = parser.leer_excel(ruta, seccion)

    assert len(_tabla(datos, "DispED")["filas"]) == 1


# ── los avisos ──────────────────────────────────────────────────────────────


def test_una_hoja_que_no_existe_avisa_y_no_rompe(
    tmp_path: Path,
    seccion: dict[str, Any],
) -> None:
    ruta = tmp_path / "vacio.xlsx"
    libro = Workbook()
    libro.save(ruta)

    datos = parser.leer_excel(ruta, seccion)

    assert _tabla(datos, "DispED")["filas"] == []
    assert "No se encuentra la hoja DISP_ED en el Excel" in datos["avisos"]
    assert "No se encuentra la hoja ENTIDADES en el Excel" in datos["avisos"]


def test_una_tabla_que_no_existe_avisa(
    excel_completo: Path,
    seccion: dict[str, Any],
) -> None:
    libro = load_workbook(excel_completo)
    del libro["DISP_ED"].tables["Tabla_Disp_ED"]
    libro.save(excel_completo)

    datos = parser.leer_excel(excel_completo, seccion)

    assert "No se encuentra la tabla Tabla_Disp_ED en la hoja DISP_ED" in datos["avisos"]
    assert _tabla(datos, "DispED")["filas"] == []


def test_un_excel_completo_no_avisa_de_nada(
    excel_completo: Path,
    seccion: dict[str, Any],
) -> None:
    datos = parser.leer_excel(excel_completo, seccion)

    assert datos["avisos"] == []


# ── las columnas que se ensenan ─────────────────────────────────────────────


def test_las_columnas_son_las_del_display_order(
    excel_completo: Path,
    seccion: dict[str, Any],
) -> None:
    datos = parser.leer_excel(excel_completo, seccion)

    assert _tabla(datos, "DispED")["columnas"] == seccion["disp_catalog"]["display_order"][
        "DispED"
    ]
    assert datos["entidades"]["columnas"] == seccion["entidades_catalog"]["display_order"][
        "entidades"
    ]


def test_las_etiquetas_salen_del_col_labels(
    excel_completo: Path,
    seccion: dict[str, Any],
) -> None:
    datos = parser.leer_excel(excel_completo, seccion)

    etiquetas = _tabla(datos, "DispED")["etiquetas"]
    assert etiquetas["numero"] == seccion["disp_catalog"]["col_labels"]["numero"]
    assert "plc_name" not in etiquetas or etiquetas["plc_name"] == "PLC"
    assert datos["procesos"]["Procesos"]["etiquetas"]["alm_hmi"] == "Alarmas HMI"
    assert datos["entidades"]["etiquetas"]["plc_tag"] == "PLC.Tag"


# ── la cache ────────────────────────────────────────────────────────────────


def test_el_almacen_guarda_el_volcado(
    excel_completo: Path,
    seccion: dict[str, Any],
) -> None:
    almacen = AlmacenExcel()
    almacen.config = seccion

    almacen.volcar(excel_completo)

    assert almacen.cargado is True
    assert almacen.archivo == "completo.xlsx"
    assert almacen.cargado_en
    estado = almacen.estado()
    assert estado["cargado"] is True
    assert estado["plcs"] == [{"uid": 1, "plc": "PLC1"}]
    assert _tabla(estado, "DispED")["filas"][0]["plc_tag"] == "V_ED_001"


def test_el_almacen_vacio_sale_vacio() -> None:
    almacen = AlmacenExcel()

    estado = almacen.estado()

    assert estado["cargado"] is False
    assert estado["archivo"] is None
    assert estado["plcs"] == []
    assert estado["dispositivos"] == []
    assert estado["avisos"] == []
    assert estado["entidades"] == {"columnas": [], "filas": []}


def test_el_almacen_persiste_y_recarga(
    excel_completo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seccion: dict[str, Any],
) -> None:
    carpeta = tmp_path / "excel"
    monkeypatch.setattr(modulo_almacen, "carpeta_persistida", lambda: carpeta)
    almacen = AlmacenExcel()
    almacen.config = seccion

    almacen.volcar(excel_completo)
    copia = almacen.persistir(excel_completo)

    assert copia == carpeta / "completo.xlsx"
    assert copia.is_file()

    otro = AlmacenExcel()
    otro.config = seccion
    assert otro.recargar() is True
    assert otro.archivo == "completo.xlsx"
    assert _tabla(otro.estado(), "DispED")["filas"][0]["plc_tag"] == "V_ED_001"


def test_al_guardar_una_copia_nueva_se_borran_las_anteriores(
    excel_completo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seccion: dict[str, Any],
) -> None:
    carpeta = tmp_path / "excel"
    monkeypatch.setattr(modulo_almacen, "carpeta_persistida", lambda: carpeta)
    almacen = AlmacenExcel()
    almacen.config = seccion

    almacen.persistir(excel_completo)
    otro = excel_completo.with_name("otro.xlsx")
    otro.write_bytes(excel_completo.read_bytes())
    almacen.persistir(otro)

    assert sorted(p.name for p in carpeta.glob("*.xlsx")) == ["otro.xlsx"]


def test_recargar_sin_copia_devuelve_false(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        modulo_almacen,
        "carpeta_persistida",
        lambda: tmp_path / "excel",
    )
    almacen = AlmacenExcel()

    assert almacen.recargar() is False
    assert almacen.cargado is False


def test_la_carpeta_persistida_en_empaquetado_va_junto_al_ejecutable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    congelado = SimpleNamespace(frozen=True, executable=str(tmp_path / "zc.exe"))
    monkeypatch.setattr(modulo_almacen, "sys", congelado)

    ruta = modulo_almacen.carpeta_persistida()

    assert ruta == tmp_path / "excel"


def test_la_carpeta_persistida_en_desarrollo_va_en_el_repo() -> None:
    carpeta = modulo_almacen.carpeta_persistida()

    assert carpeta.name == "excel"
    assert (carpeta.parent / "backend" / "zc_suite").is_dir()
