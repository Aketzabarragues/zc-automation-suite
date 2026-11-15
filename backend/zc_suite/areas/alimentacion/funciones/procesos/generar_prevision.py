"""zc_suite.areas.alimentacion.funciones.procesos.generar_prevision — la prevision.

Es un **FB**: recibe el ``job``, declara sus pasos y se ejecuta entero dentro
del hilo de TIA.

Es el port de ``function_proc_db_generar_preview`` de ``main`` con los mismos
pasos y el mismo shape de resultado. No abre transacciones, no compila y no
importa nada en TIA: solo exporta la tabla de variables del proceso y sus dos
DBs, y los compara con el Excel.

Las ayudas de este modulo que usan mas de un FB del area son publicas
(``filas_de``, ``fila_de_proceso``, ``escaneo_de``, ``leer_par_sd`` y
``localizar_fichero``): el sync las importa de aqui, no se las copia.
"""
from __future__ import annotations

import logging
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from zc_suite.areas.alimentacion.config import ConfigArea
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel
from zc_suite.areas.alimentacion.procesos import CLAVE_PREVISION
from zc_suite.areas.alimentacion.procesos.diferencias import (
    proc_calcular_arrays,
    proc_calcular_diff_n_max,
    proc_resumen,
)
from zc_suite.areas.alimentacion.procesos.mapa import (
    MapaProceso,
    proc_construir_mapa,
    proc_falta_db,
    proc_precondiciones_ok,
)
from zc_suite.errores import OperacionError
from zc_suite.nucleo.sesion import Escaneo, Sesion
from zc_suite.nucleo.tia.job import Job
from zc_suite.nucleo.tia.workdir import workdir
from zc_suite.tia_ops.exportar import exportar_bloques, exportar_tablas

logger = logging.getLogger(__name__)

#: El area y el contexto del workdir de los procesos.
AREA = "alimentacion"
CONTEXTO = "procesos"


def workdir_procesos() -> Any:
    """El workdir de los procesos: ``preview/disp`` y ``preview/bloques``."""
    return workdir(AREA, CONTEXTO, preview=("disp", "bloques"))


def _paso(job: Job, nombre: str, con_pasos: bool) -> Any:
    """El paso del trabajo, o un contexto vacio si el trabajo no declara pasos.

    Cuando la prevision se recalcula dentro de otro trabajo (el sync), los
    pasos los declara ese trabajo: aqui solo se escribe el detalle.
    """
    return job.paso(nombre) if con_pasos else nullcontext({})


def filas_de(
    datos: dict[str, Any],
    clave: str,
) -> list[dict[str, Any]]:
    """Las filas de un subdominio del Excel de software. Vacio si falta."""
    return list((datos.get(clave) or {}).get("filas", []))


def fila_de_proceso(filas: list[dict[str, Any]], proc_uid: int) -> dict[str, Any] | None:
    """La fila del proceso por su ``uid``. ``None`` si no esta."""
    for fila in filas:
        if int(fila.get("uid", 0) or 0) == proc_uid:
            return fila
    return None


def escaneo_de(
    sesion: Sesion | None,
    plc: str,
) -> Escaneo | None:
    """El escaneo fresco del PLC, o ``None`` si no hay o ha caducado.

    Los datos del escaneo dejan de ser de fiar pasados ``TTL_ESCANEO``
    segundos: un escaneo caducado es como no tener ninguno.
    """
    if sesion is None:
        return None
    return sesion.escaneo_fresco(plc)


def leer_par_sd(carpeta: Path, db: str) -> tuple[str, str]:
    """Lee el par SimaticSD de un bloque exportado.

    La exportacion puede dejar el bloque en la raiz o en una subcarpeta: se
    buscan las dos.

    Returns:
        La tupla ``(texto_del_s7dcl, texto_del_s7res)``. Vacia si no estan.
    """
    dcl = localizar_fichero(carpeta, f"{db}.s7dcl")
    res = localizar_fichero(carpeta, f"{db}.s7res")
    if dcl is None or res is None:
        return "", ""
    try:
        return (
            dcl.read_text(encoding="utf-8-sig"),
            res.read_text(encoding="utf-8-sig"),
        )
    except OSError as exc:
        logger.warning("[proc] No se pudo leer el par SimaticSD de '%s': %s", db, exc)
        return "", ""


def localizar_fichero(carpeta: Path, nombre: str) -> Path | None:
    """Localiza un fichero del export, en la raiz o en una subcarpeta."""
    if not carpeta.is_dir():
        return None
    directo = carpeta / nombre
    if directo.is_file():
        return directo
    for encontrado in sorted(carpeta.rglob(nombre)):
        return encontrado
    return None


def generar_prevision(
    job: Job,
    proc_uid: int,
    plc: str,
    almacen: AlmacenExcel,
    config: ConfigArea,
    sesion: Sesion | None = None,
    *,
    con_pasos: bool = True,
) -> dict[str, Any]:
    """Exporta del PLC y calcula el diff del proceso contra el Excel.

    Args:
        job: el trabajo en curso.
        proc_uid: el ``uid`` del proceso a previsualizar.
        plc: el PLC cuyo proceso se compara.
        almacen: la cache del Excel maestro.
        config: el modelo del area.
        sesion: la sesion del backend. La prevision se guarda en ella para
            que sobreviva a un F5 (como ``preview_disp`` en main), y del
            escaneo de su PLC sale la presencia de los bloques en TIA.
        con_pasos: si el trabajo declara sus propios pasos. ``False`` cuando
            la prevision se recalcula **dentro** de otro trabajo (el sync):
            entonces el paso lo declara el otro trabajo y esta funcion solo
            calcula.

    Returns:
        El shape que consume la SPA: ``proc_uid``, ``proc_codigo``,
        ``precondiciones_ok``, ``missing_blocks``, ``db_param_name``,
        ``db_alm_name``, ``table_name``, ``db_present``, ``table_present``,
        ``arrays``, ``summary``, ``nmax`` y ``warnings``.
    """
    if con_pasos:
        job.empezar(
            "Prevision de procesos",
            [
                ("mapa", "Construir mapa de slots"),
                ("exportar", "Exportar tabla y DBs"),
                ("comentarios", "Calcular diferencias de comentarios"),
                ("n_max", "Calcular diferencias de N_MAX"),
                ("componer", "Componer respuesta"),
            ],
        )

    datos = almacen.estado()["procesos"]
    procesos = filas_de(datos, "Procesos")
    preal_filas = filas_de(datos, "ParametrosReales")
    pint_filas = filas_de(datos, "ParametrosEnteros")
    alarmas = filas_de(datos, "Alarmas")
    proceso = fila_de_proceso(procesos, proc_uid)
    if proceso is None:
        raise OperacionError(
            f"No hay un proceso con uid={proc_uid} en el Excel: el dominio "
            "'Procesos' no lo tiene."
        )

    escaneo = escaneo_de(sesion, plc)
    if escaneo is None:
        # Como main: sin cache de bloques del PLC no se construye mapa ni se
        # exporta; la SPA muestra el hint y el operario re-escanea.
        resultado = componer_respuesta_sin_escaneo(proc_uid, proceso)
        if sesion is not None:
            sesion.guardar_dato_area(
                AREA,
                CLAVE_PREVISION,
                {"plc": plc, "proc_uid": proc_uid, "resultado": resultado},
            )
        return resultado

    avisos: list[str] = []
    carpeta = workdir_procesos()
    carpeta.limpiar_preview()
    destino_disp = carpeta.preview_de("disp")
    destino_bloques = carpeta.preview_de("bloques")

    with _paso(job, "mapa", con_pasos) as paso:
        mapa = proc_construir_mapa(
            proceso,
            preal_filas,
            pint_filas,
            alarmas,
            config.procesos.sufijos_nmax,
            escaneo.bloques,
            escaneo.tablas,
        )
        for aviso in mapa.warnings:
            logger.warning(aviso)
            avisos.append(aviso)
        paso["detail"] = (
            f"PReal={len(mapa.preal)}, PInt={len(mapa.pint)}, "
            f"ALM={len(mapa.alm)} slots"
        )

    with _paso(job, "exportar", con_pasos) as paso:
        exportar_tablas(
            job.tia.portal,
            plc,
            destino_disp,
            [mapa.table_name],
            mantener_estructura=False,
        )
        exportar_bloques(
            job.tia.portal,
            plc,
            destino_bloques,
            [mapa.db_param_name, mapa.db_alm_name],
            mantener_estructura=False,
            version_tia=job.tia.version_tia,
        )
        paso["detail"] = f"tabla {mapa.table_name} y 2 DBs exportados"

    arrays: dict[str, Any] = {}
    with _paso(job, "comentarios", con_pasos) as paso:
        texto_dcl_param, texto_res_param = leer_par_sd(
            destino_bloques, mapa.db_param_name
        )
        texto_dcl_alm, texto_res_alm = leer_par_sd(destino_bloques, mapa.db_alm_name)
        arrays = proc_calcular_arrays(
            mapa,
            texto_dcl_param,
            texto_res_param,
            texto_dcl_alm,
            texto_res_alm,
        )
        resumen = proc_resumen(arrays)
        paso["detail"] = (
            f"{resumen['agregados']} agregados, {resumen['renombrados']} renombrados, "
            f"{resumen['eliminados']} eliminados"
        )

    with _paso(job, "n_max", con_pasos) as paso:
        if not mapa.nmax_names:
            nmax_block = _bloque_n_max_vacio()
        else:
            diff_n_max = proc_calcular_diff_n_max(
                mapa.table_name,
                mapa.nmax_names,
                mapa.nmax,
                destino_disp / f"{mapa.table_name}.xml",
            )
            if diff_n_max.xml_ausente:
                aviso = (
                    f"La tabla '{mapa.table_name}' no existe en TIA (o no se pudo "
                    "exportar): los N_MAX del proceso salen como actualizar."
                )
                logger.warning(aviso)
                avisos.append(aviso)
                job.log(aviso, nivel="warning")
            nmax_block = {
                "current": diff_n_max.actual,
                "desired": diff_n_max.deseado,
                "todos": diff_n_max.todos,
                "summary": diff_n_max.resumen,
                "nmax_error": (
                    f"XML de N_MAX no encontrado en TIA export: "
                    f"{destino_disp / f'{mapa.table_name}.xml'}"
                    if diff_n_max.xml_ausente
                    else None
                ),
            }
        paso["detail"] = (
            f"{nmax_block['summary']['actualizar']} a actualizar de "
            f"{nmax_block['summary']['total']}"
        )

    with _paso(job, "componer", con_pasos) as paso:
        resultado = componer_respuesta(proc_uid, proceso, mapa, arrays, nmax_block, avisos)
        paso["detail"] = f"{resultado['summary']['total']} slots en la vista"

    if sesion is not None:
        sesion.guardar_dato_area(
            AREA, CLAVE_PREVISION, {"plc": plc, "proc_uid": proc_uid, "resultado": resultado}
        )
    return resultado


def _bloque_n_max_vacio() -> dict[str, Any]:
    """El bloque de N_MAX cuando no hay que comparar nada."""
    return {
        "current": {},
        "desired": {},
        "todos": [],
        "summary": {"actualizar": 0, "sin_cambios": 0, "total": 0},
        "nmax_error": None,
    }


def componer_respuesta(
    proc_uid: int,
    proceso: dict[str, Any],
    mapa: MapaProceso,
    arrays: dict[str, Any],
    nmax_block: dict[str, Any],
    avisos: list[str],
) -> dict[str, Any]:
    """Compone el shape final que consume la SPA."""
    precondiciones_ok = proc_precondiciones_ok(mapa)
    warnings = list(avisos)
    for db in mapa.db_missing:
        warnings.append(proc_falta_db(mapa, db))
    return {
        "proc_uid": proc_uid,
        "proc_codigo": str(proceso.get("codigo", "") or ""),
        "precondiciones_ok": precondiciones_ok,
        "missing_blocks": [] if precondiciones_ok else list(mapa.missing_blocks),
        "db_param_name": mapa.db_param_name,
        "db_alm_name": mapa.db_alm_name,
        "table_name": mapa.table_name,
        "db_present": {
            "param": mapa.db_param_name not in mapa.db_missing,
            "alm": mapa.db_alm_name not in mapa.db_missing,
        },
        "table_present": mapa.table_present,
        "arrays": {} if not precondiciones_ok else arrays,
        "summary": proc_resumen(arrays) if precondiciones_ok else _resumen_vacio(),
        "nmax": nmax_block if precondiciones_ok else _bloque_n_max_vacio(),
        "warnings": warnings,
    }


def componer_respuesta_sin_escaneo(
    proc_uid: int,
    proceso: dict[str, Any],
) -> dict[str, Any]:
    """La respuesta cuando no hay escaneo fresco del PLC.

    Como ``main``: sin la cache de bloques del PLC no se puede comprobar la
    presencia de nada, asi que no se construye mapa ni se exporta; la SPA
    muestra el hint para que el operario re-escanee.
    """
    return {
        "proc_uid": proc_uid,
        "proc_codigo": str(proceso.get("codigo", "") or ""),
        "precondiciones_ok": False,
        "missing_blocks": [
            "Cache de bloques del PLC no disponible. "
            "Selecciona el PLC en el sidebar y espera al "
            "escaneo de bloques (1-3 min en PLCs grandes)."
        ],
        "arrays": {},
        "summary": _resumen_vacio(),
        "nmax": _bloque_n_max_vacio(),
        "warnings": [],
    }


def _resumen_vacio() -> dict[str, int]:
    """El resumen sin slots."""
    return {
        "total": 0,
        "agregados": 0,
        "renombrados": 0,
        "eliminados": 0,
        "sin_cambios": 0,
    }
