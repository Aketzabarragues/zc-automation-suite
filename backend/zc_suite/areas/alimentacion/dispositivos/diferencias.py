"""zc_suite.areas.alimentacion.dispositivos.diferencias — el diff de dispositivos.

Lo que hay en TIA frente a lo que dice el Excel.

Funciones puras: comparan el XML exportado de TIA con los dispositivos del
Excel y devuelven el diff. No escriben nada.

El port de ``main`` (helpers/disp/disp_generate_preview.py) con los mismos
nombres de campo y los mismos estados.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zc_suite.simatic.ml import ModificadorConstantesUsuario, ParserConstantesUsuario

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiffTabla:
    """El diff entre lo deseado (Excel) y lo que hay (TIA) en una tabla.

    Attributes:
        tabla: nombre de la tabla de TIA (``"2000_Disp_ED"``).
        base: ``{numero: plc_tag}`` de TIA.
        deseado: ``{numero: plc_tag}`` del Excel.
        agregados: numeros que estan en el Excel y no en TIA.
        eliminados: numeros que estan en TIA y no en el Excel.
        renombrados: ``{numero: (plc_tag_de_TIA, plc_tag_del_Excel)}``.
        xml_ausente: ``True`` si el XML de TIA no existia.
    """

    tabla: str
    base: dict[str, str]
    deseado: dict[str, str]
    agregados: list[str]
    eliminados: list[str]
    renombrados: dict[str, tuple[str, str]]
    xml_ausente: bool = False

    @property
    def vacio(self) -> bool:
        """``True`` si no hay ningun cambio."""
        return not (self.agregados or self.eliminados or self.renombrados)

    @property
    def total_cambios(self) -> int:
        """Las entradas que se aplicarian en TIA (agregados + renombrados)."""
        return len(self.agregados) + len(self.renombrados)


@dataclass(frozen=True)
class DiffNMax:
    """El diff de los N_MAX entre lo deseado (Excel) y lo que hay (TIA).

    Attributes:
        tabla: nombre de la tabla (``"0_Config_Dispositivos"``).
        actual: los valores de TIA (``{}`` si falta el XML).
        deseado: los valores del Excel (nombres canonicos).
        todos: la lista de ``{name, actual, nuevo, status}``.
        resumen: ``{actualizar, sin_cambios, total}``.
        xml_ausente: ``True`` si el XML no existia.
    """

    tabla: str
    actual: dict[str, int]
    deseado: dict[str, int]
    todos: list[dict[str, Any]]
    resumen: dict[str, int]
    xml_ausente: bool = False


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


def _leer_n_max_del_xml(ruta_xml: Path) -> tuple[dict[str, int], str | None]:
    """Lee un XML plano con los N_MAX y devuelve ``(valores, error)``."""
    if not ruta_xml.is_file():
        return {}, f"El XML de los N_MAX no esta en la exportacion de TIA: {ruta_xml}"
    try:
        valores = ParserConstantesUsuario.leer_constantes(ruta_xml)
        return dict(valores), None
    except Exception as exc:
        logger.error("[N_MAX] No se pudo parsear %s: %s", ruta_xml, exc)
        return {}, f"no se pudo parsear: {exc}"


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


def disp_calcular_diff_n_max(
    tabla: str,
    n_max_deseado: dict[str, int],
    ruta_xml: Path,
) -> DiffNMax:
    """Calcula el diff de los N_MAX entre el Excel y el XML de TIA.

    Args:
        tabla: nombre de la tabla de los N_MAX.
        n_max_deseado: ``{nombre: valor}`` del Excel (nombres canonicos).
        ruta_xml: ruta al XML plano exportado de TIA.

    Returns:
        El ``DiffNMax`` con ``actual``, ``deseado``, ``todos`` y ``resumen``.
    """
    actual, error = _leer_n_max_del_xml(ruta_xml)
    if error is not None:
        return DiffNMax(
            tabla=tabla,
            actual={},
            deseado=dict(n_max_deseado),
            todos=[],
            resumen={
                "actualizar": 0,
                "sin_cambios": len(n_max_deseado),
                "total": len(n_max_deseado),
            },
            xml_ausente=True,
        )

    todos: list[dict[str, Any]] = []
    for nombre in n_max_deseado:
        valor_actual = actual.get(nombre)
        valor_deseado = int(n_max_deseado[nombre])
        if valor_actual is not None and int(valor_actual) == valor_deseado:
            estado = "sin_cambios"
        else:
            estado = "actualizar"
        todos.append(
            {
                "name": nombre,
                "actual": valor_actual,
                "nuevo": valor_deseado,
                "status": estado,
            }
        )

    return DiffNMax(
        tabla=tabla,
        actual=actual,
        deseado=dict(n_max_deseado),
        todos=todos,
        resumen={
            "actualizar": sum(1 for fila in todos if fila["status"] == "actualizar"),
            "sin_cambios": sum(1 for fila in todos if fila["status"] == "sin_cambios"),
            "total": len(todos),
        },
        xml_ausente=False,
    )
