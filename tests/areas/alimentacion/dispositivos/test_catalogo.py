"""Tests del catalogo de presentacion del area: las pestanas y los N_MAX.

El port de ``build_device_tabs`` y ``build_nmax_view`` de ``main``.
"""

from __future__ import annotations

from typing import Any

from zc_suite.areas.alimentacion.dispositivos import catalogo as dispositivos_catalogo


def test_las_pestanas_salen_en_el_orden_del_config(seccion: dict[str, Any]) -> None:
    """Las pestanas van en el orden de declaracion del ``config.json``."""
    pestanas = dispositivos_catalogo.construir_pestanas(seccion)

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


def test_las_etiquetas_de_las_pestanas(seccion: dict[str, Any]) -> None:
    """La etiqueta sale del tipo: ``"m_vf"`` -> ``"MVF"``."""
    pestanas = dispositivos_catalogo.construir_pestanas(seccion)

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


def test_el_canonico_de_cada_pestana(seccion: dict[str, Any]) -> None:
    """El canonico es el nombre del dominio: ``"DispED"``, ``"DispM_VF"``."""
    pestanas = dispositivos_catalogo.construir_pestanas(seccion)
    canonicos = {pestana["hw_type"]: pestana["canonical"] for pestana in pestanas}

    assert canonicos["ed"] == "DispED"
    assert canonicos["m_vf"] == "DispM_VF"
    assert canonicos["tq_ae"] == "DispTQ_AE"


def test_las_etiquetas_de_n_max(seccion: dict[str, Any]) -> None:
    """La etiqueta de un N_MAX sale de su nombre canonico."""
    tarjetas = dispositivos_catalogo.construir_n_max(seccion)
    etiquetas = {tarjeta["name"]: tarjeta["label"] for tarjeta in tarjetas}

    assert etiquetas["N_MAX_DISP_ED"] == "num_disp_ed"
    assert etiquetas["N_MAX_DISP_M_VF"] == "num_disp_m_vf"


def test_los_n_max_salen_en_el_orden_del_catalogo(seccion: dict[str, Any]) -> None:
    """Las tarjetas de N_MAX van en el orden del ``n_max_catalog``."""
    tarjetas = dispositivos_catalogo.construir_n_max(seccion)

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
