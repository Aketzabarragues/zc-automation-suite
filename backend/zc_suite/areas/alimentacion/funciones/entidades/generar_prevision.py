"""zc_suite.areas.alimentacion.funciones.entidades.generar_prevision — la prevision.

Es un **FB**: recibe el ``job``, declara sus pasos y se ejecuta entero dentro
del hilo de TIA.

Es el port de ``function_entidades_generar_preview`` de ``main`` con los mismos
pasos y el mismo shape de resultado. No abre transacciones, no compila y no
importa nada en TIA: solo exporta las tablas de tags y el DB, y los compara
con el Excel.

Los ayudantes de este modulo (``workdir_entidades``, ``componer_respuesta``)
son privados del FB: solo los usa el.
"""
from __future__ import annotations

import logging
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from zc_suite.areas.alimentacion.config import ConfigArea
from zc_suite.areas.alimentacion.entidades import CLAVE_PREVISION
from zc_suite.areas.alimentacion.entidades.diferencias import (
    DiffComentarios,
    DiffEntidades,
    ent_calcular_diff_comentarios,
    ent_calcular_diff_constantes,
    ent_calcular_diff_n_max,
    ent_detectar_inconsistencias,
    ent_leer_par_sd,
    ent_resumen,
)
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel
from zc_suite.nucleo.sesion import Sesion
from zc_suite.nucleo.tia.job import Job
from zc_suite.nucleo.tia.workdir import workdir
from zc_suite.tia_ops.exportar import exportar_bloques, exportar_tablas

logger = logging.getLogger(__name__)

#: El area y el contexto del workdir de las entidades.
AREA = "alimentacion"
CONTEXTO = "entidades"



def workdir_entidades() -> Any:
    """El workdir de las entidades: ``preview/disp`` y ``preview/bloques``."""
    return workdir(AREA, CONTEXTO, preview=("disp", "bloques"))


def _paso(job: Job, nombre: str, con_pasos: bool) -> Any:
    """El paso del trabajo, o un contexto vacio si el trabajo no declara pasos.

    Cuando la prevision se recalcula dentro de otro trabajo (el sync), los
    pasos los declara ese trabajo: aqui solo se escribe el detalle.
    """
    return job.paso(nombre) if con_pasos else nullcontext({})


def generar_prevision(
    job: Job,
    plc: str,
    almacen: AlmacenExcel,
    config: ConfigArea,
    sesion: Sesion | None = None,
    *,
    con_pasos: bool = True,
) -> dict[str, Any]:
    """Exporta del PLC y calcula el diff de las entidades contra el Excel.

    Args:
        job: el trabajo en curso.
        plc: el PLC cuyas entidades se comparan.
        almacen: la cache del Excel maestro.
        config: el modelo del area.
        sesion: la sesion del backend. La prevision se guarda en ella para
            que sobreviva a un F5 (como ``preview_disp`` en main).
        con_pasos: si el trabajo declara sus propios pasos. ``False`` cuando
            la prevision se recalcula **dentro** de otro trabajo (el sync):
            entonces el paso lo declara el otro trabajo y esta funcion solo
            calcula.

    Returns:
        El shape que consume la SPA: ``precondiciones_ok``, ``ops``,
        ``constants``, ``entities_block``, ``arrays``, ``nmax``, ``summary``
        y ``warnings``.
    """
    if con_pasos:
        job.empezar(
            "Prevision de entidades",
            [
                ("exportar", "Exportar etiquetas y DB"),
                ("n_max", "Calcular diferencias de N_MAX"),
                ("constantes", "Calcular diferencias de constantes"),
                ("comentarios", "Calcular diferencias de comentarios"),
                ("componer", "Componer respuesta"),
            ],
        )

    entidades = config.entidades
    db = entidades.db
    array = entidades.array
    tabla_tags = entidades.tabla_tags
    tabla_config = entidades.tabla_config

    carpeta = workdir_entidades()
    carpeta.limpiar_preview()
    destino_disp = carpeta.preview_de("disp")
    destino_bloques = carpeta.preview_de("bloques")

    avisos: list[str] = []

    with _paso(job, "exportar", con_pasos) as paso:
        exportar_tablas(
            job.tia.portal,
            plc,
            destino_disp,
            [tabla_config, tabla_tags],
            mantener_estructura=False,
        )
        exportar_bloques(
            job.tia.portal,
            plc,
            destino_bloques,
            [db],
            mantener_estructura=False,
            version_tia=job.tia.version_tia,
        )
        paso["detail"] = f"2 tablas y {db} exportados"

    with _paso(job, "n_max", con_pasos) as paso:
        diff_n_max = ent_calcular_diff_n_max(
            tabla_config,
            almacen.n_max_de_entidades(plc),
            destino_disp / f"{tabla_config}.xml",
        )
        if diff_n_max.xml_ausente:
            aviso = (
                f"La tabla '{tabla_config}' no existe en TIA (o no se pudo exportar): "
                "el N_MAX de las entidades sale como actualizar."
            )
            logger.warning(aviso)
            avisos.append(aviso)
            job.log(aviso, nivel="warning")
        paso["detail"] = (
            f"{diff_n_max.resumen['actualizar']} a actualizar de {diff_n_max.resumen['total']}"
        )

    filas = almacen.entidades_de(plc)

    with _paso(job, "constantes", con_pasos) as paso:
        diff_constantes = ent_calcular_diff_constantes(
            tabla_tags,
            filas,
            destino_disp / f"{tabla_tags}.xml",
        )
        if diff_constantes.xml_ausente:
            aviso = (
                f"La tabla '{tabla_tags}' no existe en TIA (o no se pudo exportar): "
                "sus entidades salen como altas."
            )
            logger.warning(aviso)
            avisos.append(aviso)
            job.log(aviso, nivel="warning")
        paso["detail"] = (
            f"{len(diff_constantes.agregados)} agregadas, "
            f"{len(diff_constantes.eliminados)} eliminadas"
        )

    with _paso(job, "comentarios", con_pasos) as paso:
        texto_dcl, texto_res = ent_leer_par_sd(destino_bloques, db)
        diff_comentarios = ent_calcular_diff_comentarios(
            db,
            array,
            filas,
            texto_dcl,
            texto_res,
        )
        if diff_comentarios.xml_ausente:
            aviso = (
                f"El bloque '{db}' no existe en TIA (o no se pudo exportar): "
                "sus comentarios no se pueden comparar."
            )
            logger.warning(aviso)
            avisos.append(aviso)
            job.log(aviso, nivel="warning")
        paso["detail"] = (
            f"{len(diff_comentarios.actualizados)} actualizados, "
            f"{len(diff_comentarios.sin_cambios)} sin cambios"
        )

    with _paso(job, "componer", con_pasos) as paso:
        resultado = componer_respuesta(
            diff_constantes,
            diff_comentarios,
            diff_n_max,
            tabla_config,
            destino_disp,
            avisos,
        )
        paso["detail"] = f"{resultado['summary']['total']} cambios en la vista"

    if sesion is not None:
        sesion.guardar_dato_area(AREA, CLAVE_PREVISION, {"plc": plc, "resultado": resultado})
    return resultado


def componer_respuesta(
    diff_constantes: DiffEntidades,
    diff_comentarios: DiffComentarios,
    diff_n_max: Any,
    tabla_config: str,
    destino_disp: Path,
    avisos: list[str],
) -> dict[str, Any]:
    """Compone el shape final que consume la SPA."""
    return {
        "precondiciones_ok": True,
        "missing_blocks": [],
        "db_name": diff_comentarios.db,
        "db_array_name": diff_comentarios.array,
        "tag_table": diff_constantes.tabla,
        "config_table": tabla_config,
        "db_present": not diff_comentarios.xml_ausente,
        "table_present": not diff_constantes.xml_ausente,
        "arrays": {diff_comentarios.array: _filas_de_slots(diff_comentarios)},
        "ops": list(diff_constantes.operaciones),
        "entities_block": {"desired": dict(diff_constantes.deseado)},
        "constants": {
            "agregados": [
                {
                    "plc_tag": plc_tag,
                    "numero": diff_constantes.deseado[plc_tag],
                    "actual": None,
                    "status": "agregar",
                }
                for plc_tag in diff_constantes.agregados
            ],
            "eliminados": [
                {
                    "plc_tag": plc_tag,
                    "numero": diff_constantes.base[plc_tag],
                    "actual": diff_constantes.base[plc_tag],
                    "nuevo": None,
                    "status": "eliminar",
                }
                for plc_tag in diff_constantes.eliminados
            ],
            "renombrados": [
                {
                    "plc_tag": plc_tag,
                    "actual": diff_constantes.renombrados[plc_tag][0],
                    "nuevo": diff_constantes.renombrados[plc_tag][1],
                    "status": "renombrar",
                }
                for plc_tag in sorted(diff_constantes.renombrados)
            ],
            "todos": _filas_de_constantes(diff_constantes),
        },
        "nmax": _bloque_de_n_max(diff_n_max, tabla_config, destino_disp),
        "summary": ent_resumen(diff_constantes, diff_comentarios),
        "warnings": [*avisos, *ent_detectar_inconsistencias(diff_constantes)],
    }


def _filas_de_constantes(diff: DiffEntidades) -> list[dict[str, Any]]:
    """La lista unificada de constantes, con el estado de cada una."""
    filas: list[dict[str, Any]] = []
    for plc_tag, numero in diff.base.items():
        if plc_tag in diff.renombrados:
            filas.append(
                {
                    "plc_tag": plc_tag,
                    "plc_tag_tia": plc_tag,
                    "plc_tag_excel": plc_tag,
                    "actual": diff.renombrados[plc_tag][0],
                    "nuevo": diff.renombrados[plc_tag][1],
                    "status": "renombrar",
                }
            )
        elif plc_tag in diff.eliminados:
            filas.append(
                {
                    "plc_tag": plc_tag,
                    "plc_tag_tia": plc_tag,
                    "plc_tag_excel": None,
                    "actual": numero,
                    "nuevo": None,
                    "status": "eliminar",
                }
            )
        elif plc_tag in diff.deseado:
            filas.append(
                {
                    "plc_tag": plc_tag,
                    "plc_tag_tia": plc_tag,
                    "plc_tag_excel": plc_tag,
                    "actual": numero,
                    "nuevo": diff.deseado[plc_tag],
                    "status": "sin_cambios",
                }
            )
    for plc_tag in diff.agregados:
        filas.append(
            {
                "plc_tag": plc_tag,
                "plc_tag_tia": None,
                "plc_tag_excel": plc_tag,
                "actual": None,
                "nuevo": diff.deseado[plc_tag],
                "status": "agregar",
            }
        )
    return filas


def _filas_de_slots(diff: DiffComentarios) -> list[dict[str, Any]]:
    """La lista unificada de slots del array, con el estado de cada uno."""
    filas: list[dict[str, Any]] = []
    for slot in sorted(diff.slots_tia):
        if slot in diff.agregados:
            estado = "agregar"
        elif slot in diff.actualizados:
            estado = "renombrar"
        else:
            estado = "sin_cambios"
        filas.append(
            {
                "slot": slot,
                "actual": diff.actuales.get(slot),
                "nuevo": diff.deseados.get(slot),
                "status": estado,
            }
        )
    return filas


def _bloque_de_n_max(diff_n_max: Any, tabla_config: str, destino_disp: Path) -> dict[str, Any]:
    """El bloque de los N_MAX con el shape que espera la SPA."""
    error = (
        f"XML de N_MAX no encontrado en TIA export: {destino_disp / f'{tabla_config}.xml'}"
        if diff_n_max.xml_ausente
        else None
    )
    return {
        "current": diff_n_max.actual,
        "desired": diff_n_max.deseado,
        "todos": diff_n_max.todos,
        "summary": diff_n_max.resumen,
        "nmax_error": error,
    }


