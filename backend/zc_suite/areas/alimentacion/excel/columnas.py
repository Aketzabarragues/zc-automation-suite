"""Las columnas que se ensenan y como se titulan.

Las columnas de cada tipo de dispositivo salen de su entrada del
``config.json`` del area; las de las entidades y las del software, de las
secciones ``entidades`` y ``procesos``. Los titulos salen de las etiquetas
de su seccion: donde no hay etiqueta, el titulo es el nombre del campo.

Las etiquetas van separadas por seccion a proposito: el mismo campo se
titula distinto en cada una (``numero`` es "Número" en los dispositivos,
"No" en el software y "Numero" en las entidades).

El modelo completo de cada fila lo decide el parser: el almacen lo guarda
todo, y la vista solo enseña estas columnas.
"""
from __future__ import annotations

from zc_suite.areas.alimentacion.config import ConfigArea, n_max_de

#: La clave de cada subdominio del software en ``procesos.columnas``.
SUBDOMINIOS: dict[str, str] = {
    "Procesos": "procesos",
    "ParametrosEnteros": "pint",
    "ParametrosReales": "preal",
    "Alarmas": "alarmas",
}


def _etiquetas(etiquetas: dict[str, str], columnas: list[str]) -> dict[str, str]:
    """Las etiquetas de las columnas que se ven."""
    return {columna: etiquetas[columna] for columna in columnas if columna in etiquetas}


def columnas_de_dispositivo(clave: str, config: ConfigArea) -> list[str]:
    """Las columnas que se ensenan de un tipo de dispositivo.

    Args:
        clave: la clave del tipo en el ``config.json``.
        config: el modelo del area.
    """
    dispositivo = config.dispositivos.get(clave)
    if dispositivo is None:
        return []
    return list(dispositivo.columnas)


def columnas_de_configuracion(config: ConfigArea) -> list[str]:
    """Las columnas de la vista de configuracion: el PLC y los N_MAX.

    Args:
        config: el modelo del area.
    """
    return ["PLC", *[entrada.constante for entrada in n_max_de(config)]]


def columnas_de_procesos(subdominio: str, config: ConfigArea) -> list[str]:
    """Las columnas de un subdominio de los procesos.

    Args:
        subdominio: ``"Procesos"``, ``"ParametrosEnteros"``,
            ``"ParametrosReales"`` o ``"Alarmas"``.
        config: el modelo del area.
    """
    clave = SUBDOMINIOS.get(subdominio, "")
    return list(config.procesos.columnas.get(clave, []))


def columnas_de_entidades(config: ConfigArea) -> list[str]:
    """Las columnas de la vista de entidades.

    Args:
        config: el modelo del area.
    """
    return list(config.entidades.columnas)


def etiquetas_de_dispositivo(config: ConfigArea, columnas: list[str]) -> dict[str, str]:
    """Los titulos de las columnas de los dispositivos.

    Args:
        config: el modelo del area.
        columnas: las columnas que se ven.
    """
    return _etiquetas(config.etiquetas_dispositivos, columnas)


def etiquetas_de_procesos(config: ConfigArea, columnas: list[str]) -> dict[str, str]:
    """Los titulos de las columnas del software.

    Args:
        config: el modelo del area.
        columnas: las columnas que se ven.
    """
    return _etiquetas(config.procesos.etiquetas, columnas)


def etiquetas_de_entidades(config: ConfigArea, columnas: list[str]) -> dict[str, str]:
    """Los titulos de las columnas de las entidades.

    Args:
        config: el modelo del area.
        columnas: las columnas que se ven.
    """
    return _etiquetas(config.entidades.etiquetas, columnas)
