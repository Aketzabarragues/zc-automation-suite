"""Las columnas que se ensenan y como se titulan.

El ``display_order`` del ``config.json`` decide **que columnas se ven**; el
``col_labels`` del mismo catalogo decide **como se titulan**. Donde no haya
etiqueta, el titulo es el nombre del campo tal cual.

El modelo completo de cada fila lo decide el parser: el almacen lo guarda
todo, y la vista solo enseña estas columnas.
"""
from __future__ import annotations

from typing import Any

#: La clave de cada catalogo de columnas.
CATALOGOS = ("disp", "proc", "entidades")


def _display_order(catalogo: str, config: dict[str, Any]) -> dict[str, list[str]]:
    """El ``display_order`` de un catalogo."""
    clave = f"{catalogo}_catalog"
    orden = config.get(clave, {}).get("display_order", {})
    return {str(k): [str(c) for c in v] for k, v in orden.items()}


def col_labels(catalogo: str, config: dict[str, Any]) -> dict[str, str]:
    """Las etiquetas de las columnas de un catalogo.

    Args:
        catalogo: ``"disp"``, ``"proc"`` o ``"entidades"``.
        config: la seccion del area en el ``config.json``.

    Returns:
        El dict ``{campo: etiqueta}`` del catalogo. Vacio si no lo tiene.
    """
    clave = f"{catalogo}_catalog"
    etiquetas = config.get(clave, {}).get("col_labels", {})
    return {str(k): str(v) for k, v in etiquetas.items() if k != "_comment"}


def etiquetas_de(catalogo: str, config: dict[str, Any], columnas: list[str]) -> dict[str, str]:
    """Las etiquetas de las columnas que se ensenan.

    Args:
        catalogo: el catalogo del que salen las etiquetas.
        config: la seccion del area en el ``config.json``.
        columnas: las columnas que se ven.

    Returns:
        El dict ``{campo: etiqueta}`` solo con las columnas indicadas.
    """
    etiquetas = col_labels(catalogo, config)
    return {columna: etiquetas[columna] for columna in columnas if columna in etiquetas}


def columnas_de_dispositivo(canonico: str, config: dict[str, Any]) -> list[str]:
    """Las columnas que se ensenan de un tipo de dispositivo.

    Args:
        canonico: el nombre canonico del tipo (``"DispED"``).
        config: la seccion del area en el ``config.json``.
    """
    return _display_order("disp", config).get(canonico, [])


def columnas_de_configuracion(config: dict[str, Any]) -> list[str]:
    """Las columnas de la vista de configuracion: el PLC y los N_MAX.

    Args:
        config: la seccion del area en el ``config.json``.
    """
    columnas = ["PLC"]
    for entrada in config.get("n_max_catalog", []):
        nombre = entrada.get("name")
        if nombre:
            columnas.append(str(nombre))
    return columnas


def columnas_de_procesos(subdominio: str, config: dict[str, Any]) -> list[str]:
    """Las columnas de un subdominio de los procesos.

    Args:
        subdominio: ``"Procesos"``, ``"ParametrosEnteros"``,
            ``"ParametrosReales"`` o ``"Alarmas"``.
        config: la seccion del area en el ``config.json``.
    """
    claves = {
        "Procesos": "procesos",
        "ParametrosEnteros": "parametros_int",
        "ParametrosReales": "parametros_real",
        "Alarmas": "alarmas",
    }
    return _display_order("proc", config).get(claves.get(subdominio, ""), [])


def columnas_de_entidades(config: dict[str, Any]) -> list[str]:
    """Las columnas de la vista de entidades.

    Args:
        config: la seccion del area en el ``config.json``.
    """
    return _display_order("entidades", config).get("entidades", [])
