"""zc_suite.simatic.sd.cabecera — las propiedades de un bloque exportado en SimaticSD.

El ``.s7dcl`` de SimaticSD lleva, en su primer bloque ``{ ... }``, las
propiedades del bloque: ``S7_BlockTitle``, ``S7_BlockComment``... Son las
que ``get_property`` **no** expone.

El titulo y el comentario van como identificadores MLC (``MLC_a1b2``), que
se resuelven en el ``.s7res`` hermano. Si el MLC no esta ahi, se devuelve el
identificador tal cual.

Este modulo es offline: no habla con el portal y no importa
``siemens_tia_scripting``. Recibe rutas de fichero y devuelve datos.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

#: La exportacion en SimaticSD solo existe desde TIA Portal V21.
VERSION_MINIMA_SIMATICSD = 21

#: Sufijo del fichero exportado con el bloque.
SUFIJO_SD = ".s7dcl"

#: Sufijo del fichero de textos multilinguales.
SUFIJO_RES = ".s7res"

APERTURA = "{"
CIERRE = "}"
ASIGNACION = re.compile(r'(\w+)\s*:=\s*"((?:[^"\\]|\\.)*)"')


def version_principal(version_tia: str) -> int:
    """El numero mayor de la version de TIA. ``0`` si no se entiende."""
    coincidencia = re.search(r"v?(\d+)", version_tia or "", re.IGNORECASE)
    return int(coincidencia.group(1)) if coincidencia else 0


def soporta_simaticsd(version_tia: str) -> bool:
    """``True`` si la version de TIA conectada exporta en SimaticSD.

    La exportacion en SimaticSD solo existe desde TIA Portal V21. En V18 el
    SDK responde "The method is not supported in this API version".
    """
    return version_principal(version_tia) >= VERSION_MINIMA_SIMATICSD


def leer_cabecera(ruta: str | Path) -> dict[str, str]:
    """Las asignaciones ``CLAVE := "VALOR"`` de la cabecera del ``.s7dcl``.

    Lee el primer bloque ``{ ... }`` del fichero. Si no hay cabecera, el
    fichero esta vacio o no se puede leer, devuelve ``{}``.
    """
    fichero = Path(ruta)
    if not fichero.is_file():
        return {}
    try:
        datos = fichero.read_text(encoding="utf-8").lstrip("\ufeff")
    except OSError as exc:
        logger.debug("No se pudo leer la cabecera de %s: %s", fichero, exc)
        return {}
    ventana = "\n".join(datos.splitlines()[:50])
    inicio = ventana.find(APERTURA)
    if inicio < 0:
        return {}
    fin = datos.find(CIERRE, inicio)
    if fin < 0:
        return {}
    cuerpo = datos[inicio + 1 : fin]
    return dict(ASIGNACION.findall(cuerpo))


def textos_mlc(ruta: str | Path) -> dict[str, str]:
    """El mapping ``MLC_id -> texto`` del ``.s7res``.

    El ``.s7res`` es un YAML con un bloque ``MultiLingualTexts`` de entradas
    ``- id: MLC_xxx`` con un campo por idioma. Se toma el texto en espanol y,
    si no esta, el primero que haya.
    """
    import yaml

    fichero = Path(ruta)
    if not fichero.is_file():
        return {}
    try:
        datos = yaml.safe_load(fichero.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.debug("No se pudo leer el %s: %s", fichero, exc)
        return {}
    entradas = datos.get("MultiLingualTexts", []) or []
    salida: dict[str, str] = {}
    for entrada in entradas:
        if not isinstance(entrada, dict):
            continue
        identificador = entrada.get("id", "")
        if not identificador or not str(identificador).startswith("MLC_"):
            continue
        texto = entrada.get("es-ES") or entrada.get("en-US") or entrada.get("de-DE") or ""
        salida[str(identificador)] = str(texto)
    return salida


def titulo_y_comentario(carpeta: str | Path, nombre: str) -> dict[str, str]:
    """El titulo y el comentario del bloque exportado.

    Args:
        carpeta: carpeta donde TIA dejo el ``.s7dcl`` y su ``.s7res``.
        nombre: nombre del bloque.

    Returns:
        ``{"title": str, "comment": str}``. Vacio si no hay cabecera o si
        el MLC no se puede resolver.
    """
    base = Path(carpeta) / nombre
    cabecera = leer_cabecera(f"{base}{SUFIJO_SD}")
    mlc = textos_mlc(f"{base}{SUFIJO_RES}")
    return {
        "title": _texto(cabecera.get("S7_BlockTitle", ""), mlc),
        "comment": _texto(cabecera.get("S7_BlockComment", ""), mlc),
    }


def _texto(valor: str, mlc: dict[str, str]) -> str:
    """Resuelve un identificador MLC a su texto. Vacio si no hay."""
    if not valor:
        return ""
    if valor.startswith("MLC_"):
        return mlc.get(valor, valor)
    return valor
