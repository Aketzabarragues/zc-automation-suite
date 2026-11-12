"""zc_suite.nucleo.funciones.bloques.preparar — lee los bloques de TIA.

Es un **FB**: recibe el ``job``, declara sus pasos y se ejecuta entero
dentro del hilo de TIA.
"""
from __future__ import annotations

import logging
from typing import Any

from zc_suite.errores import OperacionError
from zc_suite.nucleo.tia.job import Job
from zc_suite.nucleo.tia.workdir import workdir_editor_bloques
from zc_suite.simatic.sd.cabecera import soporta_simaticsd, titulo_y_comentario
from zc_suite.tia_ops.bloques import leer_bloques
from zc_suite.tia_ops.exportar import exportar_bloques

logger = logging.getLogger(__name__)


def preparar(job: Job, plc: str, nombres: list[str]) -> dict[str, Any]:
    """Lee de TIA las propiedades de los bloques seleccionados.

    El titulo, el autor y la version se leen de las propiedades del bloque.
    El **comentario** solo existe en el XML exportado en SimaticSD, que
    requiere TIA V21: en V18 se salta ese paso y se avisa.

    Returns:
        ``{"plc", "bloques"}``, con la misma forma que el escaneo. El
        ``extended`` de cada bloque lleva ademas ``comment``, vacio si no se
        pudo leer.
    """
    version = job.tia.version_tia
    con_comentario = soporta_simaticsd(version)
    pasos: list[tuple[str, str]] = [
        ("validar", "Validar la selección"),
        ("leer", "Leer los bloques de TIA"),
    ]
    if con_comentario:
        pasos.append(("exportar", "Exportar los bloques en SimaticSD"))
        pasos.append(("parsear", "Leer las cabeceras de los bloques"))
    pasos.append(("combinar", "Combinar los datos"))

    job.empezar(f"Preparar {len(nombres)} bloques", pasos)

    with job.paso("validar") as paso:
        if not nombres:
            raise OperacionError("No hay bloques seleccionados.")
        # El preview del editor se vacia al empezar: asi los ficheros que
        # quedan son los del ultimo prepare, y los de un prepare anterior
        # no contaminan este.
        editor = workdir_editor_bloques()
        editor.limpiar_preview()
        editor.preview.mkdir(parents=True, exist_ok=True)
        paso["detail"] = f"{len(nombres)} bloques"

    with job.paso("leer") as paso:
        leidos = leer_bloques(job.tia.portal, plc, nombres)
        paso["detail"] = f"{len(leidos)} bloques leidos"
        if not con_comentario:
            aviso = (
                "El comentario solo se puede leer del XML exportado en SimaticSD, "
                f"que necesita TIA V21. El TIA conectado es {version or 'V?'}: se salta."
            )
            paso["detail"] = f"{len(leidos)} bloques leidos. {aviso}"
            logger.warning("Preparar bloques en %s: %s", plc, aviso)

    cabeceras: dict[str, dict[str, str]] = {}
    if con_comentario:
        editor = workdir_editor_bloques()
        with job.paso("exportar") as paso:
            exportar_bloques(
                job.tia.portal,
                plc,
                editor.preview,
                nombres,
                version_tia=version,
            )
            paso["detail"] = f"{len(nombres)} bloques exportados"
        with job.paso("parsear") as paso:
            for bloque in leidos:
                cabeceras[str(bloque["nombre"])] = titulo_y_comentario(
                    editor.preview, str(bloque["nombre"])
                )
            paso["detail"] = f"{len(cabeceras)} cabeceras leidas"

    with job.paso("combinar") as paso:
        for bloque in leidos:
            extendidas = dict(bloque.get("extended") or {})
            cabecera = cabeceras.get(str(bloque["nombre"]), {})
            if cabecera.get("title"):
                extendidas["title"] = cabecera["title"]
            extendidas["comment"] = cabecera.get("comment", "")
            bloque["extended"] = extendidas
        paso["detail"] = f"{len(leidos)} bloques listos"
    return {"plc": plc, "bloques": leidos}
