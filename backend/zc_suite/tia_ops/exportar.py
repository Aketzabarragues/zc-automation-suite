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
- Los bloques se exportan **siempre** en SimaticSD: es el formato que
  necesita la edicion offline. ``get_supported_export_format()`` no se
  consulta antes de exportar, sino solo si la exportacion falla, para
  anadir al mensaje de error los formatos que el bloque si admite.

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
        try:
            bloque.export(
                target_directory_path=str(carpeta),
                export_format=FORMATO_SD,
                keep_folder_structure=mantener_estructura,
            )
        except Exception as exc:
            raise OperacionError(
                f"No se pudo exportar el bloque '{nombre}': {exc}. "
                f"{_formatos_admitidos(bloque)}"
            ) from exc
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
        try:
            # Sin ``export_format``: las tablas de tags no lo aceptan. El
            # wrapper escribe el XML directamente.
            tabla.export(
                target_directory_path=str(carpeta),
                keep_folder_structure=mantener_estructura,
            )
        except Exception as exc:
            raise OperacionError(
                f"No se pudo exportar la tabla '{nombre}': {exc}. "
                f"{_formatos_admitidos(tabla)}"
            ) from exc
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


def _formatos_admitidos(objeto: Any) -> str:
    """Los formatos de export que admite el objeto, para el mensaje de error.

    Solo se consulta cuando la exportacion **ha fallado**: el formato que
    se pasa es siempre SimaticSD, que es el que necesita la edicion offline.
    La consulta tolera cualquier fallo: es informacion para el operario,
    no una condicion para exportar.
    """
    getter = getattr(objeto, "get_supported_export_format", None)
    if getter is None:
        return "El objeto no expone get_supported_export_format()."
    try:
        formatos = getter()
    except Exception as exc:
        return f"No se pudo consultar get_supported_export_format(): {exc}"
    if not formatos:
        return "El objeto no admite ningun formato de export."
    return f"Formatos admitidos: {', '.join(repr(formato) for formato in formatos)}."
