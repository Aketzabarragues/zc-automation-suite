"""zc_suite.tia_ops.exportar — exportar del PLC a disco.

Portado de ``core/infrastructure/tia/tia_cmd_export.py`` de la version
anterior. Peculiaridades conservadas:

- Las tablas de tags se exportan **sin** ``export_format``: el wrapper
  escribe el XML directamente. Pasar el formato ahi es lo que rompia el
  reimport.
- El layout de las tablas (``mantener_estructura``) tiene que ser
  **explicito**. Con el XML plano, TIA al reimportar **crea** la tabla en
  vez de actualizarla y la transaccion muere con ``CommitOnDispose``. Por
  eso el parametro no tiene valor por defecto: la decision es del que
  llama.
- El formato de export de un bloque depende del objeto y de la version de
  TIA, asi que se consulta ``get_supported_export_format()`` en vez de
  suponerlo.

No se porta ``export_udts``: no tiene ningun llamador.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from zc_suite.tia_ops import OperacionError
from zc_suite.tia_ops._resolver import buscar_plc, nombre_bloque, nombre_tabla

logger = logging.getLogger(__name__)

#: Formato de export de los bloques: SimaticSD (``.s7dcl`` + ``.s7res``).
FORMATO_SD = "SimaticSD"


def exportar_bloques(
    portal: Any,
    plc: str,
    destino: str | Path,
    nombres: list[str] | None = None,
    *,
    mantener_estructura: bool = False,
) -> dict[str, Any]:
    """Exporta bloques de programa del PLC como SimaticSD.

    Args:
        portal: el portal de TIA.
        plc: nombre del PLC.
        destino: carpeta destino. Se crea si no existe.
        nombres: whitelist de nombres de bloque. ``None`` = todos. Match
            exacto y sensible a mayusculas.
        mantener_estructura: ``True`` preserva la jerarquia de TIA; ``False``
            exporta plano.

    Returns:
        ``{"exportado_a", "cantidad", "nombres", "omitidos"}``. ``omitidos``
        son los del whitelist que no se han encontrado en el PLC.

    Raises:
        OperacionError: si el PLC no existe o el bloque no admite SimaticSD.
    """
    objetivo = buscar_plc(portal, plc)
    carpeta = _preparar_destino(destino)
    pedidos = _filtro(nombres)

    exportados: list[str] = []
    for bloque in objetivo.get_program_blocks():
        nombre = nombre_bloque(bloque)
        if not nombre:
            continue
        if pedidos is not None and nombre not in pedidos:
            continue
        bloque.export(
            target_directory_path=str(carpeta),
            export_format=_formato_bloque(bloque),
            keep_folder_structure=mantener_estructura,
        )
        exportados.append(nombre)

    return {
        "exportado_a": str(carpeta),
        "cantidad": len(exportados),
        "nombres": exportados,
        "omitidos": sorted(pedidos - set(exportados)) if pedidos is not None else [],
    }


def exportar_tablas(
    portal: Any,
    plc: str,
    destino: str | Path,
    nombres: list[str] | None = None,
    *,
    mantener_estructura: bool,
) -> dict[str, Any]:
    """Exporta las tablas de tags del PLC como XML SimaticML.

    Args:
        portal: el portal de TIA.
        plc: nombre del PLC.
        destino: carpeta destino. Se crea si no existe.
        nombres: whitelist de nombres de tabla. ``None`` = todas. Match
            exacto y sensible a mayusculas.
        mantener_estructura: **obligatorio**. ``True`` preserva la jerarquia
            de TIA; ``False`` exporta plano, y entonces TIA creara la tabla
            de nuevo al reimportar en vez de actualizarla.

    Returns:
        ``{"exportado_a", "cantidad", "nombres", "omitidos"}``.

    Raises:
        OperacionError: si el PLC no existe.
    """
    objetivo = buscar_plc(portal, plc)
    carpeta = _preparar_destino(destino)
    pedidos = _filtro(nombres)

    exportados: list[str] = []
    for tabla in objetivo.get_plc_tag_tables():
        nombre = nombre_tabla(tabla)
        if not nombre:
            continue
        if pedidos is not None and nombre not in pedidos:
            continue
        # Sin ``export_format``: las tablas de tags no lo aceptan. El wrapper
        # escribe el XML directamente.
        tabla.export(
            target_directory_path=str(carpeta),
            keep_folder_structure=mantener_estructura,
        )
        exportados.append(nombre)

    return {
        "exportado_a": str(carpeta),
        "cantidad": len(exportados),
        "nombres": exportados,
        "omitidos": sorted(pedidos - set(exportados)) if pedidos is not None else [],
    }


# ── helpers ────────────────────────────────────────────────────────────────


def _preparar_destino(destino: str | Path) -> Path:
    """Valida el destino y crea la carpeta.

    Raises:
        OperacionError: si el destino esta vacio o no se puede crear.
    """
    if not destino:
        raise OperacionError("Se requiere el directorio destino.")
    carpeta = Path(destino)
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OperacionError(f"No se pudo crear el destino '{carpeta}': {exc}") from exc
    return carpeta


def _filtro(nombres: list[str] | None) -> set[str] | None:
    """Whitelist de nombres. ``None`` significa todos."""
    if nombres is None:
        return None
    return {str(nombre).strip() for nombre in nombres if nombre}


def _formatos_soportados(objeto: Any) -> list[str]:
    """Los formatos de export que admite el objeto. Vacia si no lo dice."""
    getter = getattr(objeto, "get_supported_export_format", None)
    if getter is None:
        return []
    try:
        formatos = getter()
    except Exception:
        return []
    return [str(formato) for formato in (formatos or [])]


def _formato_bloque(bloque: Any) -> str:
    """El formato con el que se exporta un bloque.

    El formato depende del objeto y de la version de TIA, asi que se
    consulta ``get_supported_export_format()`` en vez de suponerlo. La
    edicion offline trabaja sobre ficheros SimaticSD (``.s7dcl``), asi que
    si TIA no lo ofrece, es un error y no un formato cualquiera.

    Raises:
        OperacionError: si el bloque no admite SimaticSD.
    """
    formatos = _formatos_soportados(bloque)
    if not formatos:
        # El SDK no dice que formatos admite: se usa el de siempre.
        return FORMATO_SD
    if FORMATO_SD in formatos:
        return FORMATO_SD
    raise OperacionError(
        f"El bloque no admite exportacion {FORMATO_SD} "
        f"(formatos admitidos: {', '.join(formatos)})."
    )
