"""Tests del formato del config del area.

El ``config.json`` del operario manda siempre: si no cumple el formato, la
app lo dice con un mensaje claro y sigue. Estos tests fijan ese mensaje.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from zc_suite.areas.alimentacion import config as config_area
from zc_suite.areas.alimentacion.config import ConfigArea, ConfigInvalidoError


def _sin_clave(seccion: dict[str, Any], camino: list[str]) -> dict[str, Any]:
    """La seccion sin la clave del camino."""
    copia = copy.deepcopy(seccion)
    destino = copia
    for parte in camino[:-1]:
        destino = destino[parte]
    del destino[camino[-1]]
    return copia


def test_el_config_del_repo_cumple_el_formato(seccion: dict[str, Any]) -> None:
    """La plantilla del repo vale."""
    modelo = config_area.cargar(seccion)

    assert isinstance(modelo, ConfigArea)
    assert len(modelo.dispositivos) == 12


@pytest.mark.parametrize(
    "camino",
    [
        ["dispositivos", "ed", "db"],
        ["dispositivos", "ed", "tabla_tags"],
        ["dispositivos", "ed", "excel"],
        ["dispositivos", "ed", "nmax"],
    ],
)
def test_un_tipo_incompleto_no_cumple_el_formato(
    seccion: dict[str, Any],
    camino: list[str],
) -> None:
    """Un tipo al que le falta una clave no vale: el error dice cual."""
    with pytest.raises(ConfigInvalidoError) as error:
        config_area.cargar(_sin_clave(seccion, camino))

    mensaje = str(error.value)
    assert "no cumple el formato" in mensaje
    assert ".".join(camino) in mensaje


def test_el_formato_anterior_se_dice_que_es_el_anterior(seccion: dict[str, Any]) -> None:
    """Un config de la version anterior no se ignora: se explica."""
    viejo = copy.deepcopy(seccion)
    viejo["Dispositivos"] = {"ed": {}}
    viejo["n_max_catalog"] = []

    with pytest.raises(ConfigInvalidoError) as error:
        config_area.cargar(viejo)

    mensaje = str(error.value)
    assert "formato anterior" in mensaje
    assert "Dispositivos" in mensaje
    assert "n_max_catalog" in mensaje


def test_una_clave_desconocida_no_se_ignora(seccion: dict[str, Any]) -> None:
    """Las claves que no son del formato se rechazan."""
    seccion = copy.deepcopy(seccion)
    seccion["inventada"] = 1

    with pytest.raises(ConfigInvalidoError) as error:
        config_area.cargar(seccion)

    assert "'inventada' no es una clave admitida" in str(error.value)


def test_problema_devuelve_el_motivo_o_none(seccion: dict[str, Any]) -> None:
    """``problema()`` no lanza: dice si vale o por que no."""
    assert config_area.problema(seccion) is None

    assert config_area.problema({"dispositivos": {}}) is not None


def test_el_n_max_de_las_entidades_es_el_ultimo(modelo: ConfigArea) -> None:
    """Los N_MAX de los dispositivos van por constante; el de las entidades, al final."""
    constantes = [entrada.constante for entrada in config_area.n_max_de(modelo)]

    assert constantes[-1] == "N_MAX_ENTIDAD"
    assert constantes[:-1] == sorted(constantes[:-1])
    assert len(constantes) == 13


def test_los_n_max_de_las_entidades_viven_en_su_tabla(modelo: ConfigArea) -> None:
    """Cada N_MAX dice en que tabla de TIA vive su constante."""
    entradas = {entrada.constante: entrada for entrada in config_area.n_max_de(modelo)}

    assert entradas["N_MAX_DISP_ED"].tabla == "0_Config_Dispositivos"
    assert entradas["N_MAX_ENTIDAD"].tabla == "0_Config_Generales"
