"""Tests del parseo del Excel maestro y de la cache del area.

Ningun test toca TIA: el Excel se construye aqui mismo y el portal no hace
falta para nada.
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


def _tabla_dispositivo(datos: dict[str, Any], tipo: str) -> dict[str, Any]:
    """La tabla de un tipo de dispositivo del volcado."""
    for tabla in datos["dispositivos"]:
        if tabla["tipo"] == tipo:
            return tabla
    raise AssertionError(f"El volcado no tiene la tabla {tipo}.")


# ── el parseo ───────────────────────────────────────────────────────────────


def test_leer_excel_devuelve_todos_los_dominios(
    excel_maestro: Path,
    seccion: dict[str, Any],
) -> None:
    datos = parser.leer_excel(excel_maestro, seccion)

    assert datos["archivo"] == "maestro.xlsx"
    assert datos["plcs"] == ["PLC1"]
    assert datos["configuracion"]["filas"] == [
        {"PLC": "PLC1", "N_MAX_DISP_EA": 10, "N_MAX_DISP_ED": 20}
    ]
    assert datos["dispositivos"] == [
        {
            "tipo": "DispED",
            "columnas": seccion["disp_catalog"]["display_order"]["DispED"],
            "filas": [
                {
                    "plc_name": "PLC1",
                    "numero": 1,
                    "tag": "V_ED_001",
                    "descripcion": "Entrada digital",
                    "e_byte": 3,
                    "e_bit": 2,
                }
            ],
        }
    ]
    assert datos["procesos"]["Procesos"]["filas"] == [
        {"plc_name": "PLC1", "codigo": "PR1", "nombre": "Proceso uno"}
    ]
    assert datos["procesos"]["ParametrosEnteros"]["filas"][0]["num_db"] == 500
    assert datos["procesos"]["ParametrosReales"]["filas"][0]["num_db"] == 501
    assert datos["procesos"]["Alarmas"]["filas"][0]["comentario_db"] == "Comentario"
    assert datos["entidades"]["filas"] == [
        {
            "plc_name": "PLC1",
            "numero": 7,
            "descripcion": "Entidad de prueba",
            "plc_tag": "DB7",
        }
    ]


def test_las_columnas_son_las_del_catalogo(
    excel_maestro: Path,
    seccion: dict[str, Any],
) -> None:
    datos = parser.leer_excel(excel_maestro, seccion)

    assert datos["configuracion"]["columnas"] == ["PLC", "N_MAX_DISP_EA", "N_MAX_DISP_ED"]
    assert _tabla_dispositivo(datos, "DispED")["columnas"] == seccion["disp_catalog"][
        "display_order"
    ]["DispED"]
    assert datos["entidades"]["columnas"] == seccion["entidades_catalog"]["display_order"][
        "entidades"
    ]


def test_una_fila_mala_dice_la_hoja_la_tabla_y_la_fila(
    tmp_path: Path,
    crear_excel: Callable[..., Path],
    seccion: dict[str, Any],
) -> None:
    ruta = crear_excel(
        tmp_path / "malo.xlsx",
        [["PLC1", "no es un numero", "V_ED_001", "Entrada", 3, 2]],
    )

    with pytest.raises(OperacionError) as fallo:
        parser.leer_excel(ruta, seccion)

    mensaje = str(fallo.value)
    assert "Fila 2 invalida" in mensaje
    assert "Tabla_Disp_ED" in mensaje
    assert "DISP_ED" in mensaje
    assert "numero" in mensaje


def test_una_celda_vacia_sale_como_cero_o_vacia(
    tmp_path: Path,
    crear_excel: Callable[..., Path],
    seccion: dict[str, Any],
) -> None:
    ruta = crear_excel(
        tmp_path / "vacias.xlsx",
        [["PLC1", None, "", "Entrada digital", 3, 2]],
    )

    datos = parser.leer_excel(ruta, seccion)

    fila = _tabla_dispositivo(datos, "DispED")["filas"][0]
    assert fila["numero"] == 0
    assert fila["tag"] == ""


def test_un_excel_sin_tablas_no_es_un_error(
    tmp_path: Path,
    seccion: dict[str, Any],
) -> None:
    ruta = tmp_path / "vacio.xlsx"
    libro = Workbook()
    libro.save(ruta)

    datos = parser.leer_excel(ruta, seccion)

    assert datos["plcs"] == []
    assert _tabla_dispositivo(datos, "DispED")["filas"] == []
    assert datos["entidades"]["filas"] == []


def test_una_hoja_que_no_existe_no_es_un_error(
    excel_maestro: Path,
    seccion: dict[str, Any],
) -> None:
    libro = load_workbook(excel_maestro)
    del libro["ENTIDADES"]
    libro.save(excel_maestro)

    datos = parser.leer_excel(excel_maestro, seccion)

    assert datos["entidades"]["filas"] == []
    assert _tabla_dispositivo(datos, "DispED")["filas"]


def test_un_fichero_que_no_existe_falla(tmp_path: Path, seccion: dict[str, Any]) -> None:
    with pytest.raises(OperacionError):
        parser.leer_excel(tmp_path / "no_existe.xlsx", seccion)


# ── la cache ────────────────────────────────────────────────────────────────


def test_el_almacen_guarda_el_volcado(
    excel_maestro: Path,
    seccion: dict[str, Any],
) -> None:
    almacen = AlmacenExcel()
    almacen.config = seccion

    almacen.volcar(excel_maestro)

    assert almacen.cargado is True
    assert almacen.archivo == "maestro.xlsx"
    assert almacen.cargado_en
    estado = almacen.estado()
    assert estado["cargado"] is True
    assert estado["plcs"] == ["PLC1"]
    assert _tabla_dispositivo(estado, "DispED")["filas"][0]["tag"] == "V_ED_001"


def test_el_almacen_vacio_sale_vacio() -> None:
    almacen = AlmacenExcel()

    estado = almacen.estado()

    assert estado["cargado"] is False
    assert estado["archivo"] is None
    assert estado["plcs"] == []
    assert estado["dispositivos"] == []
    assert estado["entidades"] == {"columnas": [], "filas": []}


def test_el_almacen_persiste_y_recarga(
    excel_maestro: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seccion: dict[str, Any],
) -> None:
    carpeta = tmp_path / "excel"
    monkeypatch.setattr(modulo_almacen, "carpeta_persistida", lambda: carpeta)
    almacen = AlmacenExcel()
    almacen.config = seccion

    almacen.volcar(excel_maestro)
    copia = almacen.persistir(excel_maestro)

    assert copia == carpeta / "maestro.xlsx"
    assert copia.is_file()

    otro = AlmacenExcel()
    otro.config = seccion
    assert otro.recargar() is True
    assert otro.archivo == "maestro.xlsx"
    assert _tabla_dispositivo(otro.estado(), "DispED")["filas"][0]["tag"] == "V_ED_001"


def test_al_guardar_una_copia_nueva_se_borran_las_anteriores(
    excel_maestro: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seccion: dict[str, Any],
) -> None:
    carpeta = tmp_path / "excel"
    monkeypatch.setattr(modulo_almacen, "carpeta_persistida", lambda: carpeta)
    almacen = AlmacenExcel()
    almacen.config = seccion

    almacen.persistir(excel_maestro)
    otro = excel_maestro.with_name("otro.xlsx")
    otro.write_bytes(excel_maestro.read_bytes())
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
