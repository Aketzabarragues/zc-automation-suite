"""Tests del catalogo de presentacion del area: las pestanas y los N_MAX.

El port de ``build_device_tabs`` y ``build_nmax_view`` de ``main``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from zc_suite.areas.alimentacion.config import ConfigArea
from zc_suite.areas.alimentacion.dispositivos import catalogo as dispositivos_catalogo


def test_las_pestanas_salen_en_el_orden_del_config(modelo: ConfigArea) -> None:
    """Las pestanas van en el orden de declaracion del ``config.json``."""
    pestanas = dispositivos_catalogo.construir_pestanas(modelo)

    assert [pestana["hw_type"] for pestana in pestanas] == [
        "ed",
        "ea",
        "sa",
        "sd",
        "v",
        "m",
        "m_vf",
        "m_sina",
        "tq",
        "tq_ae",
        "tot",
        "pid",
    ]


def test_las_etiquetas_de_las_pestanas(modelo: ConfigArea) -> None:
    """La etiqueta de la pestaña sale del config: ``"m_vf"`` -> ``"MVF"``."""
    pestanas = dispositivos_catalogo.construir_pestanas(modelo)

    assert [pestana["label"] for pestana in pestanas] == [
        "ED",
        "EA",
        "SA",
        "SD",
        "V",
        "M",
        "MVF",
        "MSINA",
        "TQ",
        "TQAE",
        "TOT",
        "PID",
    ]


def test_las_etiquetas_de_n_max(modelo: ConfigArea) -> None:
    """La etiqueta de un N_MAX sale de su nombre canonico."""
    tarjetas = dispositivos_catalogo.construir_n_max(modelo)
    etiquetas = {tarjeta["name"]: tarjeta["label"] for tarjeta in tarjetas}

    assert etiquetas["N_MAX_DISP_ED"] == "num_disp_ed"
    assert etiquetas["N_MAX_DISP_M_VF"] == "num_disp_m_vf"


def test_los_n_max_salen_en_el_orden_del_catalogo(modelo: ConfigArea) -> None:
    """Las tarjetas de N_MAX van en el orden del catalogo de N_MAX."""
    tarjetas = dispositivos_catalogo.construir_n_max(modelo)

    assert [tarjeta["name"] for tarjeta in tarjetas][:2] == [
        "N_MAX_DISP_EA",
        "N_MAX_DISP_ED",
    ]


def test_el_catalogo_del_area_lleva_pestanas_y_n_max(seccion: dict[str, Any]) -> None:
    """El catalogo del area lleva lo que la SPA necesita para pintar."""
    from zc_suite.areas import alimentacion

    catalogo = alimentacion.catalogo(seccion)

    assert catalogo["device_tabs"]
    assert catalogo["nmax"]
    assert catalogo["device_tabs"][0]["hw_type"] == "ed"


def test_el_catalogo_emite_su_log_y_los_avisos(
    caplog: pytest.LogCaptureFixture,
    seccion: dict[str, Any],
) -> None:
    """El area emite su log y sus avisos, con su vocabulario.

    El log del area (tipos de dispositivo y N_MAX) y los dos avisos se
    emiten aqui, no en el nucleo: los textos son los que antes salian en
    ``log_de_arranque``.
    """
    from zc_suite.areas import alimentacion

    # Con el catalogo completo: solo el log, sin avisos.
    with caplog.at_level(logging.INFO):
        catalogo = alimentacion.catalogo(seccion, Path("C:/app/config/config.json"))
    tipos = len(catalogo["device_tabs"])
    n_max = len(catalogo["nmax"])
    assert f"Area 'alimentacion': {tipos} tipos de dispositivo, {n_max} N_MAX" in [
        registro.getMessage() for registro in caplog.records
    ]
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    # Con el catalogo vacio: el log mas los dos avisos, con la ruta del
    # config en uso.
    caplog.clear()
    with caplog.at_level(logging.INFO):
        alimentacion.catalogo({}, Path("C:/app/config/config.json"))
    mensajes = [registro.getMessage() for registro in caplog.records]
    assert "Area 'alimentacion': 0 tipos de dispositivo, 0 N_MAX" in mensajes
    assert "El area 'alimentacion' no tiene tipos de dispositivo en el " \
        "catalogo: la vista de dispositivos saldra vacia. Revisa el " \
        "config.json en uso (C:/app/config/config.json): puede que este " \
        "vacio o incompleto." in mensajes
    assert "El area 'alimentacion' no tiene N_MAX en el catalogo: las " \
        "tarjetas de N_MAX saldran vacias. Revisa el config.json en uso " \
        "(C:/app/config/config.json)." in mensajes


def test_las_pestanas_no_cambian_con_el_formato_del_config(
    modelo: ConfigArea,
    dorado: dict[str, Any],
) -> None:
    """Las pestanas son las de antes: mismas y en el mismo orden."""
    pestanas = dispositivos_catalogo.construir_pestanas(modelo)

    assert [{"hw_type": p["hw_type"], "label": p["label"]} for p in pestanas] == dorado["catalogo"][
        "device_tabs"
    ]


def test_las_tarjetas_de_n_max_no_cambian_con_el_formato_del_config(
    modelo: ConfigArea,
    dorado: dict[str, Any],
) -> None:
    """Las tarjetas de N_MAX son las de antes: mismas y en el mismo orden."""
    tarjetas = dispositivos_catalogo.construir_n_max(modelo)

    assert tarjetas == dorado["catalogo"]["nmax"]
