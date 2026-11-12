"""Tests del parser de cabeceras SimaticSD."""

from __future__ import annotations

from pathlib import Path

from zc_suite.simatic.sd import cabecera

CABECERA_SD = """DATA_BLOCK "DB10"
{ S7_BlockTitle := "MLC_t1"
  S7_BlockComment := "MLC_c1"
  S7_BlockVersion := "1.0" }
"""

RES_S7 = """MultiLingualTexts:
  - id: MLC_t1
    es-ES: "El titulo"
    en-US: "The title"
  - id: MLC_c1
    es-ES: "El comentario"
"""


def test_la_version_principal_se_saca_del_texto() -> None:
    assert cabecera.version_principal("V21.0") == 21
    assert cabecera.version_principal("V18.0") == 18
    assert cabecera.version_principal("") == 0


def test_simaticsd_solo_desde_v21() -> None:
    assert cabecera.soporta_simaticsd("V21.0") is True
    assert cabecera.soporta_simaticsd("V18.0") is False
    assert cabecera.soporta_simaticsd("") is False


def test_la_cabecera_se_lee_del_s7dcl(tmp_path: Path) -> None:
    ruta = tmp_path / "DB10.s7dcl"
    ruta.write_text(CABECERA_SD, encoding="utf-8")

    resultado = cabecera.leer_cabecera(ruta)

    assert resultado["S7_BlockTitle"] == "MLC_t1"
    assert resultado["S7_BlockComment"] == "MLC_c1"


def test_la_cabecera_de_un_fichero_que_no_existe_vacia() -> None:
    assert cabecera.leer_cabecera(Path("no-existe.s7dcl")) == {}


def test_los_textos_mlc_se_leen_del_s7res(tmp_path: Path) -> None:
    ruta = tmp_path / "DB10.s7res"
    ruta.write_text(RES_S7, encoding="utf-8")

    resultado = cabecera.textos_mlc(ruta)

    assert resultado["MLC_t1"] == "El titulo"
    assert resultado["MLC_c1"] == "El comentario"


def test_el_titulo_y_el_comentario_resuelven_el_mlc(tmp_path: Path) -> None:
    (tmp_path / "DB10.s7dcl").write_text(CABECERA_SD, encoding="utf-8")
    (tmp_path / "DB10.s7res").write_text(RES_S7, encoding="utf-8")

    resultado = cabecera.titulo_y_comentario(tmp_path, "DB10")

    assert resultado == {"title": "El titulo", "comment": "El comentario"}


def test_un_mlc_sin_texto_se_devuelve_tal_cual(tmp_path: Path) -> None:
    (tmp_path / "DB10.s7dcl").write_text(CABECERA_SD, encoding="utf-8")

    resultado = cabecera.titulo_y_comentario(tmp_path, "DB10")

    assert resultado["title"] == "MLC_t1"
    assert resultado["comment"] == "MLC_c1"


def test_un_bloque_sin_cabecera_no_tiene_titulo_ni_comentario(tmp_path: Path) -> None:
    (tmp_path / "DB10.s7dcl").write_text("DATA_BLOCK \"DB10\"\n", encoding="utf-8")

    resultado = cabecera.titulo_y_comentario(tmp_path, "DB10")

    assert resultado == {"title": "", "comment": ""}
