"""zc_suite.tia_ops.importar — importar del disco al PLC.

Portado de ``core/infrastructure/tia/tia_cmd_import_.py`` de la version
anterior. Peculiaridades conservadas:

- ``target_folder_path`` **no se pasa** si el que llama no da una carpeta no
  vacia. Pasarlo como ``""`` hace que TIA V21 NO haga match UPDATE de los
  bloques pre-existentes: intenta CREATE y falla con *"Import failed because
  an object with the name X already exists"*. Sin ese argumento, TIA escanea
  recursivamente y hace match UPDATE por nombre, conservando la ruta
  relativa.
- La misma regla para bloques y para tablas de tags.

En la version anterior habia tres handlers de bloques (``import_block``,
``import_blocks_sd``) que hacian lo mismo. Aqui hay uno: ``importar_bloques``.

No se porta ``import_tag_table``: no tiene ningun llamador.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from zc_suite.tia_ops import OperacionError
from zc_suite.tia_ops._resolver import buscar_plc


def importar_bloques(
    portal: Any,
    plc: str,
    origen: str | Path,
    carpeta_destino: str = "",
) -> dict[str, Any]:
    """Importa bloques SimaticSD (``.s7dcl``) del disco al PLC.

    Args:
        portal: el portal de TIA.
        plc: nombre del PLC.
        origen: carpeta con los ficheros a importar.
        carpeta_destino: carpeta del PLC destino. **Vacia** significa que no
            se manda el argumento a TIA y este hace match UPDATE por nombre
            conservando la ruta relativa. Es lo que hay que hacer: mandar
            ``""`` rompe el match UPDATE.

    Returns:
        ``{"importado_de": str(origen), "carpeta_destino": ...}``.

    Raises:
        OperacionError: si el PLC no existe, la carpeta no existe o TIA
            rechaza la importacion.
    """
    objetivo = buscar_plc(portal, plc)
    carpeta = _preparar_origen(origen)
    try:
        if carpeta_destino:
            objetivo.import_blocks(
                import_root_directory=str(carpeta),
                target_folder_path=carpeta_destino,
            )
        else:
            objetivo.import_blocks(import_root_directory=str(carpeta))
    except Exception as exc:
        raise OperacionError(
            f"No se pudo importar los bloques desde '{carpeta}': "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    return {"importado_de": str(carpeta), "carpeta_destino": carpeta_destino}


def importar_tablas(
    portal: Any,
    plc: str,
    origen: str | Path,
    carpeta_destino: str = "",
) -> dict[str, Any]:
    """Importa tablas de tags (XML SimaticML) del disco al PLC.

    Args:
        portal: el portal de TIA.
        plc: nombre del PLC.
        origen: carpeta con los XML a importar.
        carpeta_destino: carpeta del PLC destino. **Vacia** significa que no
            se manda el argumento a TIA (match UPDATE por nombre).

    Returns:
        ``{"importado_de": str(origen), "carpeta_destino": ...}``.

    Raises:
        OperacionError: si el PLC no existe, la carpeta no existe o TIA
            rechaza la importacion.
    """
    objetivo = buscar_plc(portal, plc)
    carpeta = _preparar_origen(origen)
    try:
        if carpeta_destino:
            objetivo.import_plc_tags(
                import_root_directory=str(carpeta),
                target_folder_path=carpeta_destino,
            )
        else:
            objetivo.import_plc_tags(import_root_directory=str(carpeta))
    except Exception as exc:
        raise OperacionError(
            f"No se pudo importar las tablas desde '{carpeta}': "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    return {"importado_de": str(carpeta), "carpeta_destino": carpeta_destino}


def _preparar_origen(origen: str | Path) -> Path:
    """Valida la carpeta de origen.

    Raises:
        OperacionError: si la carpeta no existe.
    """
    if not origen:
        raise OperacionError("Se requiere la carpeta de origen.")
    carpeta = Path(origen)
    if not carpeta.is_dir():
        raise OperacionError(
            f"El directorio de importacion no existe o no es accesible: '{carpeta}'."
        )
    return carpeta
