"""El catalogo de presentacion del area: las pestañas y las etiquetas.

Es el port de ``build_device_tabs`` y ``build_nmax_view`` de ``main``: las
pestañas por tipo de dispositivo (en el orden del ``config.json``) y la
etiqueta de cada N_MAX.
"""
from __future__ import annotations

from typing import Any

from zc_suite.areas.alimentacion.excel import tablas


def etiqueta_de_tipo(tipo: str) -> str:
    """La etiqueta de un tipo de dispositivo.

    ``"ed"`` -> ``"ED"``, ``"m_vf"`` -> ``"MVF"``, ``"m_sina"`` -> ``"MSINA"``.
    """
    return tipo.replace("_", "").upper()


def etiqueta_de_n_max(nombre: str) -> str:
    """La etiqueta de un N_MAX.

    ``"N_MAX_DISP_ED"`` -> ``"num_disp_ed"``.
    """
    if nombre.startswith("N_MAX_DISP_"):
        return f"num_disp_{nombre[len('N_MAX_DISP_') :].lower()}"
    return nombre


def construir_pestanas(config: dict[str, Any]) -> list[dict[str, str]]:
    """Las pestañas por tipo de dispositivo.

    Returns:
        La lista de ``{"hw_type", "canonical", "label"}``, en el orden del
        ``config.json``.
    """
    pestanas: list[dict[str, str]] = []
    for tipo in config.get("Dispositivos", {}):
        _hoja, _tabla, canonico = tablas.destino_de_dispositivo(str(tipo), config)
        pestanas.append(
            {
                "hw_type": str(tipo),
                "canonical": canonico,
                "label": etiqueta_de_tipo(str(tipo)),
            }
        )
    return pestanas


def construir_n_max(config: dict[str, Any]) -> list[dict[str, str]]:
    """Las tarjetas de N_MAX.

    Returns:
        La lista de ``{"name", "label"}``, en el orden del catalogo de N_MAX.
    """
    tarjetas: list[dict[str, str]] = []
    for entrada in config.get("n_max_catalog", []):
        nombre = str(entrada.get("name", "")).strip()
        if not nombre:
            continue
        tarjetas.append({"name": nombre, "label": etiqueta_de_n_max(nombre)})
    return tarjetas
