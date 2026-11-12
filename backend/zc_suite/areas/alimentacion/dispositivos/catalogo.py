"""El catalogo de presentacion del area: las pestañas y las etiquetas.

Es el port de ``build_device_tabs`` y ``build_nmax_view`` de ``main``: las
pestañas por tipo de dispositivo (en el orden del ``config.json``) y la
etiqueta de cada N_MAX.
"""
from __future__ import annotations

from zc_suite.areas.alimentacion.config import ConfigArea, n_max_de


def etiqueta_de_n_max(nombre: str) -> str:
    """La etiqueta de un N_MAX.

    ``"N_MAX_DISP_ED"`` -> ``"num_disp_ed"``.
    """
    if nombre.startswith("N_MAX_DISP_"):
        return f"num_disp_{nombre[len('N_MAX_DISP_') :].lower()}"
    return nombre


def construir_pestanas(config: ConfigArea) -> list[dict[str, str]]:
    """Las pestañas por tipo de dispositivo.

    Returns:
        La lista de ``{"hw_type", "label"}``, en el orden del
        ``config.json``.
    """
    return [
        {"hw_type": tipo, "label": dispositivo.etiqueta}
        for tipo, dispositivo in config.dispositivos.items()
    ]


def construir_n_max(config: ConfigArea) -> list[dict[str, str]]:
    """Las tarjetas de N_MAX.

    Returns:
        La lista de ``{"name", "label"}``, en el orden del catalogo de N_MAX.
    """
    return [
        {"name": entrada.constante, "label": etiqueta_de_n_max(entrada.constante)}
        for entrada in n_max_de(config)
    ]
