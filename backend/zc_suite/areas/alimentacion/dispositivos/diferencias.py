"""zc_suite.areas.alimentacion.dispositivos.diferencias — el diff de dispositivos.

Lo que hay en TIA frente a lo que dice el Excel.

Funciones puras: comparan el XML exportado de TIA con los dispositivos del
Excel y devuelven el diff. No escriben nada.

El port de ``main`` (helpers/disp/disp_generate_preview.py) con los mismos
nombres de campo y los mismos estados.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from zc_suite.areas.alimentacion.diferencias import DiffTabla
from zc_suite.simatic.ml import ModificadorConstantesUsuario

logger = logging.getLogger(__name__)


def _leer_dispositivos_del_xml(ruta_xml: Path) -> dict[str, str]:
    """Lee un XML plano de tabla de tags y devuelve ``{numero: plc_tag}``."""
    if not ruta_xml.is_file():
        return {}
    try:
        modificador = ModificadorConstantesUsuario(ruta_xml)
    except Exception as exc:
        logger.warning(
            "[diff] No se pudo cargar el XML de dispositivos '%s': %s", ruta_xml.name, exc
        )
        return {}
    return dict(modificador.leer_constantes_con_valores())


def disp_calcular_diff_tabla(
    tabla: str,
    dispositivos: list[dict[str, Any]],
    ruta_xml: Path,
) -> DiffTabla:
    """Calcula el diff entre los dispositivos del Excel y el XML de TIA.

    Args:
        tabla: nombre de la tabla de TIA.
        dispositivos: los dispositivos del Excel, ya filtrados por PLC.
        ruta_xml: ruta al XML plano exportado de TIA.

    Returns:
        El ``DiffTabla`` de la tabla.
    """
    deseado: dict[str, str] = {}
    for dispositivo in dispositivos:
        numero = int(dispositivo.get("numero", 0) or 0)
        plc_tag = str(dispositivo.get("plc_tag", "") or "")
        if numero >= 0 and plc_tag:
            deseado[str(numero)] = plc_tag

    base = _leer_dispositivos_del_xml(ruta_xml)
    xml_ausente = not ruta_xml.is_file()

    numeros_base = set(base)
    numeros_deseados = set(deseado)

    agregados = sorted(numeros_deseados - numeros_base)
    eliminados = sorted(numeros_base - numeros_deseados)
    renombrados: dict[str, tuple[str, str]] = {
        numero: (base[numero], deseado[numero])
        for numero in numeros_base & numeros_deseados
        if base[numero] != deseado[numero]
    }

    return DiffTabla(
        tabla=tabla,
        base=base,
        deseado=deseado,
        agregados=agregados,
        eliminados=eliminados,
        renombrados=renombrados,
        xml_ausente=xml_ausente,
    )
