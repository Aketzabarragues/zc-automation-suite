"""zc_suite.areas.alimentacion.funciones.procesos.sincronizar — el sync.

Es un **FB**: recibe el ``job``, declara sus pasos y se ejecuta entero dentro
del hilo de TIA.

Es el port de ``function_proc_db_sincronizar`` de ``main``. Dos
transacciones, en su orden, y cada una se comprueba:

1. **N_MAX** (en linea): los valores de los N_MAX de la tabla del proceso,
   que redimensionan los arrays de los DBs.
2. **Comentarios** (offline, solo desde TIA V21): la importacion de los dos
   DBs con los comentarios ya editados en disco.

El resultado dice **cual se confirmo, cual se revirtio y cual no se
ejecuto**, y lo mismo se ve en el faceplate: cada transaccion lleva su
estado en el detalle, y las que no se alcanzan se quedan pendientes.

El N_MAX no se exporta para editarlo (a diferencia de las entidades): se
cambia en linea con ``cambiar_valor`` sobre la tabla del proceso. El
criterio de las operaciones es el de ``main``: solo las constantes que ya
existen en TIA y cuyo valor no coincide.

Los DBs se exportan con la carpeta de TIA conservada (``mantener_estructura``)
y se copian a ``modified/`` con su ruta relativa: lo que se importa es la
copia, no el export, y solo los DBs que la edicion offline ha modificado.

El estado de las transacciones, el texto del aviso de compilacion y los
helpers de texto y rutas los aporta ``sincronizacion_comun``: lo comun de los
cuatro FB de sync, en un solo sitio.

Correcciones sobre ``main``:

- Cada transaccion **comprueba** su resultado y lo lleva en el resumen: si
  la de los comentarios falla, el mensaje dice que los N_MAX ya estaban
  confirmados.
- La transaccion de comentarios **solo se ejecuta con TIA V21 o superior**:
  la exportacion en SimaticSD no existe antes.
- Al terminar se **recalcula la prevision** con la misma funcion que la
  genera (``generar_prevision``), para que la vista vea el estado final.
- El proyecto **no** se guarda.
"""
from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Any

from zc_suite.areas.alimentacion.config import ConfigArea
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel
from zc_suite.areas.alimentacion.funciones._transaccion import _transaccion
from zc_suite.areas.alimentacion.funciones.procesos.generar_prevision import (
    escaneo_de,
    fila_de_proceso,
    filas_de,
    generar_prevision,
    leer_par_sd,
)
from zc_suite.areas.alimentacion.procesos.diferencias import (
    proc_arrays_vacios,
    proc_calcular_arrays,
    proc_calcular_diff_n_max,
    proc_resumen,
    proc_slots_actuales,
)
from zc_suite.areas.alimentacion.procesos.mapa import (
    MapaProceso,
    proc_construir_mapa,
    proc_falta_db,
    proc_precondiciones_ok,
)
from zc_suite.areas.alimentacion.procesos.sincronizacion import (
    ARRAYS_PROCESO,
    EXTENSION_DCL,
    EXTENSION_RES,
    SATELITES_POR_ARRAY,
    proc_arrays_para_apply,
    proc_confirmar_db,
    proc_localizar_db,
    proc_operaciones_n_max,
    proc_tipo_array,
)
from zc_suite.areas.alimentacion.sincronizacion_comun import (
    ESTADO_CONFIRMADA,
    ESTADO_NO_EJECUTADA,
    ESTADO_REVIRTIDA,
    compilar_con_aviso,
    estado_no_ejecutada,
    estados_iniciales,
    localizar_xml,
)
from zc_suite.errores import OperacionError
from zc_suite.nucleo.sesion import Sesion
from zc_suite.nucleo.tia.job import Job
from zc_suite.nucleo.tia.workdir import workdir
from zc_suite.simatic.sd.cabecera import soporta_simaticsd
from zc_suite.tia_ops.compilar import compilar_bloques
from zc_suite.tia_ops.constantes import cambiar_valor
from zc_suite.tia_ops.exportar import exportar_bloques, exportar_tablas
from zc_suite.tia_ops.importar import importar_bloques

logger = logging.getLogger(__name__)

#: El area y el contexto del workdir del sync de procesos.
AREA = "alimentacion"
CONTEXTO = "procesos"

#: Segundos que se espera a que TIA consolide tras la transaccion de N_MAX.
PAUSA_CONSOLIDACION_S = 2.0

#: La transaccion se confirmo: TIA guardo los cambios.
CONFIRMADA = ESTADO_CONFIRMADA

#: La transaccion fallo y se revirtio: TIA no guardo nada.
REVIRTIDA = ESTADO_REVIRTIDA

#: La transaccion no llego a ejecutarse.
NO_EJECUTADA = ESTADO_NO_EJECUTADA

#: La cola final del aviso de una compilacion con errores de los procesos.
#: Singular (``ese``): se compilan los dos DBs del proceso.
COLA_COMPILACION = (
    " Revisa ese bloque en TIA Portal: puede haber quedado con "
    "un tamano inconsistente tras el cambio de N_MAX."
)

#: Los pasos del sync, declarados al inicio del trabajo.
PASOS = (
    ("mapa", "Construir mapa de slots"),
    ("exportar", "Exportar tabla y DBs"),
    ("preparar", "Preparar operaciones"),
    ("tx_n_max", "Aplicar N_MAX"),
    ("consolidacion", "Esperar consolidación TIA"),
    ("compilar", "Compilar bloques"),
    ("reexportar", "Re-exportar tabla y DBs"),
    ("copiar", "Copiar bloques a modified"),
    ("editar", "Editar comentarios offline"),
    ("tx_comentarios", "Aplicar comentarios"),
    ("prevision", "Recalcular la prevision"),
)


def sincronizar(
    job: Job,
    proc_uid: int,
    plc: str,
    almacen: AlmacenExcel,
    config: ConfigArea,
    sesion: Sesion | None = None,
) -> dict[str, Any]:
    """Aplica en TIA los cambios de un proceso que dice el Excel.

    Args:
        job: el trabajo en curso.
        proc_uid: el ``uid`` del proceso a sincronizar.
        plc: el PLC cuyo proceso se sincroniza.
        almacen: la cache del Excel maestro.
        config: el modelo del area.
        sesion: la sesion del backend; al terminar se recalcula la prevision.

    Returns:
        El resumen del sync: que se aplico, como quedo cada transaccion y la
        prevision posterior.

    Raises:
        OperacionError: si no hay escaneo fresco, si falta la tabla o los
            dos DBs, o si falla alguna transaccion.
    """
    job.empezar("Sincronizar proceso", list(PASOS))
    datos, proceso, escaneo = _validar_previos(almacen, proc_uid, sesion, plc)
    transacciones = estados_iniciales({"n_max": "N_MAX", "comentarios": "Comentarios"})
    carpeta = workdir(AREA, CONTEXTO)
    # En TIA anterior a V21 no se exporta SimaticSD: el sync solo toca el
    # N_MAX y la tx de comentarios queda no ejecutada.
    sin_comentarios = not soporta_simaticsd(job.tia.version_tia)

    # 1. Preparar: el mapa de slots.
    with job.paso("mapa") as paso:
        mapa = _paso_mapa(job, datos, proceso, config, escaneo, paso)
    # 2. Exportar tabla y DBs.
    with job.paso("exportar") as paso:
        db_a_exportar, rutas_db = _paso_exportar(
            job, plc, mapa, carpeta, sin_comentarios, paso
        )
    # 3. Preparar las operaciones.
    with job.paso("preparar") as paso:
        ops_n_max, arrays, arrays_por_db = _paso_preparar(
            mapa, carpeta, sin_comentarios, paso
        )
    # 4. Tx A: los N_MAX (en linea).
    with job.paso("tx_n_max") as paso:
        paso["detail"] = _paso_n_max(job, plc, mapa, ops_n_max, transacciones)
    # 5. Esperar la consolidacion de TIA.
    with job.paso("consolidacion") as paso:
        time.sleep(PAUSA_CONSOLIDACION_S)
        paso["detail"] = f"TIA consolida ({PAUSA_CONSOLIDACION_S:g} s)"
    # 6. Compilar los bloques (siempre que hubo N_MAX). Como main: se compila
    # antes de re-exportar, porque TIA no exporta bloques inconsistentes.
    # No depende de si los comentarios cambian.
    with job.paso("compilar") as paso:
        detalle_compilacion = _compilar_proceso(
            job, plc, mapa, bool(ops_n_max), sin_comentarios
        )
        paso["detail"] = detalle_compilacion
    # 7. Re-exportar tabla y DBs (solo si hubo N_MAX). Los textos SD se leen
    # de la re-export cuando hay DBs que releer: el N_MAX pudo redimensionar
    # los arrays y los comentarios actuales son los que van a la edicion.
    with job.paso("reexportar") as paso:
        arrays, textos_sd = _paso_reexportar(
            job, plc, mapa, carpeta, db_a_exportar,
            bool(ops_n_max), sin_comentarios, arrays, paso,
        )
    # 8. Copiar los DBs a modified.
    with job.paso("copiar") as paso:
        _copiar_bloques_paso(sin_comentarios, carpeta, rutas_db, paso)
    # 9. Editar los comentarios offline.
    with job.paso("editar") as paso:
        con_cambios = _paso_editar(
            sin_comentarios, transacciones, mapa, textos_sd,
            carpeta, arrays_por_db, paso,
        )
    # 10. Tx B: los comentarios (offline, solo V21+).
    with job.paso("tx_comentarios") as paso:
        _paso_tx_comentarios(
            job, plc, carpeta, transacciones, con_cambios, paso
        )
    # 11. Recalcular la prevision.
    with job.paso("prevision") as paso:
        prevision = _paso_prevision(
            job, proc_uid, plc, almacen, config, sesion, paso
        )

    return _armar_resultado(
        plc, proc_uid, ops_n_max, arrays,
        transacciones, detalle_compilacion, prevision,
    )


# ── los pasos, en helpers privados ─────────────────────────────────────────


def _paso_mapa(
    job: Job,
    datos: dict[str, Any],
    proceso: dict[str, Any],
    config: ConfigArea,
    escaneo: Any,
    paso: dict[str, Any],
) -> MapaProceso:
    """El paso del mapa de slots, con su detalle de slots."""
    mapa = _preparar_mapa(job, datos, proceso, config, escaneo)
    paso["detail"] = (
        f"PReal={len(mapa.preal)}, PInt={len(mapa.pint)}, "
        f"ALM={len(mapa.alm)} slots"
    )
    return mapa


def _paso_exportar(
    job: Job,
    plc: str,
    mapa: MapaProceso,
    carpeta: Any,
    sin_comentarios: bool,
    paso: dict[str, Any],
) -> tuple[list[str], dict[str, Path | None]]:
    """El paso de exportacion de la tabla y los DBs."""
    db_a_exportar, rutas_db = _exportar_tabla_y_dbs(
        job, plc, mapa, carpeta, sin_comentarios
    )
    paso["detail"] = _detalle_exportar(mapa, db_a_exportar, sin_comentarios)
    return db_a_exportar, rutas_db


def _paso_preparar(
    mapa: MapaProceso,
    carpeta: Any,
    sin_comentarios: bool,
    paso: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, dict[int, str | None]]],
    dict[str, dict[str, dict[int, str]]],
]:
    """El paso de preparacion de las operaciones, con su detalle."""
    ops_n_max, arrays, arrays_por_db = _preparar_operaciones(
        mapa, carpeta, sin_comentarios
    )
    paso["detail"] = _detalle_operaciones(mapa, ops_n_max, arrays_por_db)
    return ops_n_max, arrays, arrays_por_db


def _paso_reexportar(
    job: Job,
    plc: str,
    mapa: MapaProceso,
    carpeta: Any,
    db_a_exportar: list[str],
    hubo_n_max: bool,
    sin_comentarios: bool,
    arrays: dict[str, dict[str, dict[int, str | None]]],
    paso: dict[str, Any],
) -> tuple[
    dict[str, dict[str, dict[int, str | None]]],
    tuple[str, str, str, str],
]:
    """El paso de re-exportacion de la tabla y los DBs."""
    arrays, textos_sd = _reexportar(
        job, plc, mapa, carpeta, db_a_exportar,
        hubo_n_max, sin_comentarios, arrays,
    )
    paso["detail"] = _detalle_reexportar(hubo_n_max, sin_comentarios)
    return arrays, textos_sd


def _paso_prevision(
    job: Job,
    proc_uid: int,
    plc: str,
    almacen: AlmacenExcel,
    config: ConfigArea,
    sesion: Sesion | None,
    paso: dict[str, Any],
) -> dict[str, Any] | None:
    """El paso de recalcular la prevision, con su detalle."""
    prevision = _recalcular_prevision(
        job, proc_uid, plc, almacen, config, sesion
    )
    if prevision is None:
        paso["detail"] = "no se pudo recalcular la prevision"
    else:
        paso["detail"] = f"{prevision['summary']['total']} cambios en la vista"
    return prevision


def _validar_previos(
    almacen: AlmacenExcel,
    proc_uid: int,
    sesion: Sesion | None,
    plc: str,
) -> tuple[dict[str, Any], dict[str, Any], Any]:
    """El proceso del Excel y el escaneo fresco del PLC.

    Sin el proceso ni el escaneo no hay sync: el error dice que falta.

    Returns:
        Los datos del dominio ``procesos`` del Excel, la fila del proceso y
        el escaneo fresco del PLC.
    """
    datos = almacen.estado()["procesos"]
    proceso = fila_de_proceso(filas_de(datos, "Procesos"), proc_uid)
    if proceso is None:
        raise OperacionError(
            f"No hay un proceso con uid={proc_uid} en el Excel: el dominio "
            "'Procesos' no lo tiene."
        )
    escaneo = escaneo_de(sesion, plc)
    if escaneo is None:
        raise OperacionError(
            "No hay un escaneo fresco del PLC: escanea el PLC antes de "
            "sincronizar el proceso."
        )
    return datos, proceso, escaneo


def _exportar_tabla_y_dbs(
    job: Job,
    plc: str,
    mapa: MapaProceso,
    carpeta: Any,
    sin_comentarios: bool,
) -> tuple[list[str], dict[str, Path | None]]:
    """Exporta la tabla del proceso y, con V21+, sus dos DBs.

    Los DBs se exportan con la carpeta de TIA conservada (``mantener_estructura``)
    y se anota la ruta relativa de cada uno dentro del export: la conserva la
    copia a ``modified/``. Sin la carpeta de TIA, TIA no haria UPDATE.

    Returns:
        Los DBs exportados y la ruta relativa de cada uno dentro del
        export (``None`` si no se pudo localizar).
    """
    carpeta.limpiar_sincronizar()
    exportar_tablas(
        job.tia.portal,
        plc,
        carpeta.variables_export,
        [mapa.table_name],
        mantener_estructura=True,
    )
    if sin_comentarios:
        # V18: no se exporta SimaticSD; el sync solo toca el N_MAX.
        return [], {}
    db_a_exportar = [
        db
        for db in (mapa.db_param_name, mapa.db_alm_name)
        if db not in mapa.db_missing
    ]
    exportar_bloques(
        job.tia.portal,
        plc,
        carpeta.bloques_export,
        db_a_exportar,
        mantener_estructura=True,
        version_tia=job.tia.version_tia,
    )
    rutas_db = {
        db: _ruta_relativa_db(carpeta.bloques_export, db)
        for db in db_a_exportar
    }
    return db_a_exportar, rutas_db


def _detalle_exportar(
    mapa: MapaProceso,
    db_a_exportar: list[str],
    sin_comentarios: bool,
) -> str:
    """El detalle del paso de exportacion, con y sin DBs (V18)."""
    if sin_comentarios:
        return f"tabla {mapa.table_name} exportada (sin DBs)"
    return f"tabla {mapa.table_name} y {len(db_a_exportar)} DBs exportados"


def _detalle_reexportar(
    ops_n_max: list[dict[str, Any]],
    sin_comentarios: bool,
) -> str:
    """El detalle del paso de re-exportacion, segun si hubo N_MAX y la version."""
    if not ops_n_max:
        return "no hacia falta releer"
    # V18: no se re-exportan bloques (no hay SimaticSD).
    if sin_comentarios:
        return "tabla releida (los DBs no se re-exportan)"
    return "tabla y DBs releidos"


def _copiar_bloques_paso(
    sin_comentarios: bool,
    carpeta: Any,
    rutas_db: dict[str, Path | None],
    paso: dict[str, Any],
) -> None:
    """El paso de copia de los DBs exportados a ``modified``."""
    if sin_comentarios:
        paso["detail"] = "no hay que copiar (sin comentarios en esta version)"
        return
    _copiar_bloques(
        carpeta.bloques_export, carpeta.bloques_modified, rutas_db
    )
    paso["detail"] = f"{len(rutas_db)} DBs copiados a modified"


def _detalle_operaciones(
    mapa: MapaProceso,
    ops_n_max: list[dict[str, Any]],
    arrays_por_db: dict[str, dict[str, dict[int, str]]],
) -> str:
    """El detalle del paso de preparacion: cuantas operaciones hay por DB."""
    return (
        f"{len(ops_n_max)} N_MAX, "
        f"{len(arrays_por_db.get(mapa.db_param_name, {}))} arrays en el "
        "DB de parametros, "
        f"{len(arrays_por_db.get(mapa.db_alm_name, {}))} arrays en el "
        "DB de alarmas"
    )


def _preparar_mapa(
    job: Job,
    datos: dict[str, Any],
    proceso: dict[str, Any],
    config: ConfigArea,
    escaneo: Any,
) -> MapaProceso:
    """Construye el mapa de slots del proceso y avisa de lo que falta."""
    mapa = proc_construir_mapa(
        proceso,
        filas_de(datos, "ParametrosReales"),
        filas_de(datos, "ParametrosEnteros"),
        filas_de(datos, "Alarmas"),
        config.procesos.sufijos_nmax,
        escaneo.bloques,
        escaneo.tablas,
    )
    for aviso in mapa.warnings:
        logger.warning(aviso)
        job.log(aviso, nivel="warning")
    for db in mapa.db_missing:
        aviso = proc_falta_db(mapa, db)
        logger.warning(aviso)
        job.log(aviso, nivel="warning")
    if not proc_precondiciones_ok(mapa):
        # Como main: sin la tabla, o sin los dos DBs, no hay nada que
        # aplicar.
        raise OperacionError(
            "No se puede sincronizar el proceso: "
            + "; ".join(mapa.missing_blocks)
        )
    return mapa


def _preparar_operaciones(
    mapa: MapaProceso,
    carpeta: Any,
    sin_comentarios: bool,
) -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, dict[int, str | None]]],
    dict[str, dict[str, dict[int, str]]],
]:
    """Las operaciones del sync: los N_MAX y los arrays por DB.

    Returns:
        Los N_MAX a cambiar, los arrays del proceso (para el resumen de
        comentarios) y los arrays por DB (para la edicion offline).
    """
    diff_n_max = proc_calcular_diff_n_max(
        mapa.table_name,
        mapa.nmax_names,
        mapa.nmax,
        localizar_xml(carpeta.variables_export, mapa.table_name),
    )
    if diff_n_max.xml_ausente:
        # Como main: sin el XML de la tabla no se puede comparar el
        # N_MAX ni aplicar nada.
        raise OperacionError(
            f"La tabla '{mapa.table_name}' no existe en TIA (o no se pudo "
            "exportarla): lanza la prevision antes de sincronizar."
        )
    ops_n_max = proc_operaciones_n_max(mapa.table_name, diff_n_max)

    if sin_comentarios:
        arrays = proc_arrays_vacios(mapa)
        arrays_por_db: dict[str, dict[str, dict[int, str]]] = {}
    else:
        dcl_param, res_param = leer_par_sd(
            carpeta.bloques_export, mapa.db_param_name
        )
        dcl_alm, res_alm = leer_par_sd(carpeta.bloques_export, mapa.db_alm_name)
        arrays = proc_calcular_arrays(
            mapa,
            dcl_param,
            res_param,
            dcl_alm,
            res_alm,
        )
        arrays_por_db = proc_arrays_para_apply(
            {
                "preal": mapa.preal,
                "pint": mapa.pint,
                "alm": mapa.alm,
            },
            mapa.db_param_name,
            mapa.db_alm_name,
            mapa.db_missing,
        )
    return ops_n_max, arrays, arrays_por_db


def _aplicar_n_max(
    job: Job,
    plc: str,
    tabla: str,
    ops_n_max: list[dict[str, Any]],
) -> None:
    """Aplica en linea el valor de los N_MAX del proceso."""
    for operacion in ops_n_max:
        cambiar_valor(
            job.tia.portal,
            plc,
            str(operacion["tabla"]),
            str(operacion["constante"]),
            int(operacion["valor"]),
        )


def _paso_n_max(
    job: Job,
    plc: str,
    mapa: MapaProceso,
    ops_n_max: list[dict[str, Any]],
    transacciones: dict[str, dict[str, Any]],
) -> str:
    """Ejecuta la transaccion de los N_MAX (en linea) y anota su estado.

    Returns:
        El detalle del paso.
    """
    if not ops_n_max:
        estado_no_ejecutada(
            transacciones, "n_max", "no habia nada que aplicar"
        )
        return "sin cambios de N_MAX"
    _transaccion(
        job,
        transacciones,
        "n_max",
        "Actualizando los N_MAX del proceso",
        lambda: _aplicar_n_max(job, plc, mapa.table_name, ops_n_max),
        f"{len(ops_n_max)} N_MAX",
    )
    return f"{transacciones['n_max']['estado']}: {len(ops_n_max)} N_MAX"


def _compilar_proceso(
    job: Job,
    plc: str,
    mapa: MapaProceso,
    hubo_n_max: bool,
    sin_comentarios: bool,
) -> str:
    """Compila los DBs del proceso, fuera de la transaccion.

    Solo si hubo N_MAX y la version soporta SimaticSD; en el resto de
    casos la compilacion no se ejecuta (``compile=no-op``), como en
    ``main``. El detalle que devuelve es el que lleva el paso y el
    resultado.
    """
    if not (hubo_n_max and not sin_comentarios):
        return "compile=no-op"
    return compilar_con_aviso(
        compilador=lambda: compilar_bloques(
            job.tia.portal,
            plc,
            [
                db
                for db in (mapa.db_param_name, mapa.db_alm_name)
                if db not in mapa.db_missing
            ],
        ),
        cola=COLA_COMPILACION,
        logger=logger,
    )


def _reexportar(
    job: Job,
    plc: str,
    mapa: MapaProceso,
    carpeta: Any,
    db_a_exportar: list[str],
    hubo_n_max: bool,
    sin_comentarios: bool,
    arrays: dict[str, dict[str, dict[int, str | None]]],
) -> tuple[
    dict[str, dict[str, dict[int, str | None]]],
    tuple[str, str, str, str],
]:
    """Re-exporta la tabla y los DBs tras el N_MAX.

    Sin cambios de N_MAX no se vuelve a exportar nada. En V18 (sin
    SimaticSD) solo se releen las tablas: no hay bloques que re-exportar.

    Returns:
        Los arrays (recalculados con la re-export cuando se releen los
        DBs, que es cuando el N_MAX pudo redimensionarlos) y los textos
        SimaticSD releidos (vacios si no se releo nada).
    """
    if not hubo_n_max:
        return arrays, ("", "", "", "")
    exportar_tablas(
        job.tia.portal,
        plc,
        carpeta.variables_export,
        [mapa.table_name],
        mantener_estructura=True,
    )
    if sin_comentarios:
        return arrays, ("", "", "", "")
    exportar_bloques(
        job.tia.portal,
        plc,
        carpeta.bloques_export,
        db_a_exportar,
        mantener_estructura=True,
        version_tia=job.tia.version_tia,
    )
    # Los comentarios actuales se re-leen de la re-export: el N_MAX
    # pudo redimensionar los arrays.
    dcl_param, res_param = leer_par_sd(
        carpeta.bloques_export, mapa.db_param_name
    )
    dcl_alm, res_alm = leer_par_sd(carpeta.bloques_export, mapa.db_alm_name)
    # Los arrays se recalculan con lo releido: el N_MAX pudo
    # redimensionar los DBs y el resumen de 'comentarios' debe
    # reflejar el estado post-N_MAX.
    arrays = proc_calcular_arrays(
        mapa,
        dcl_param,
        res_param,
        dcl_alm,
        res_alm,
    )
    return arrays, (dcl_param, res_param, dcl_alm, res_alm)


def _paso_editar(
    sin_comentarios: bool,
    transacciones: dict[str, dict[str, Any]],
    mapa: MapaProceso,
    textos_sd: tuple[str, str, str, str],
    carpeta: Any,
    arrays_por_db: dict[str, dict[str, dict[int, str]]],
    paso: dict[str, Any],
) -> bool:
    """El paso de edicion offline de los comentarios.

    En V18 no se edita nada: la tx de comentarios queda no ejecutada y el
    detalle del paso lo dice.
    """
    if sin_comentarios:
        estado_no_ejecutada(
            transacciones,
            "comentarios",
            "los comentarios por instancia necesitan TIA Portal V21 o superior",
        )
        paso["detail"] = "no ejecutada: TIA Portal anterior a V21"
        return False
    dbs_con_cambios, con_cambios = _editar_comentarios(
        mapa, textos_sd, carpeta, arrays_por_db, transacciones
    )
    paso["detail"] = (
        f"{len(dbs_con_cambios)} DBs con cambios" if con_cambios else "sin cambios"
    )
    return con_cambios


def _paso_tx_comentarios(
    job: Job,
    plc: str,
    carpeta: Any,
    transacciones: dict[str, dict[str, Any]],
    con_cambios: bool,
    paso: dict[str, Any],
) -> None:
    """La transaccion de los comentarios del proceso (offline, solo V21+)."""
    if not con_cambios:
        paso["detail"] = transacciones["comentarios"]["detalle"]
        return
    _transaccion(
        job,
        transacciones,
        "comentarios",
        "Sincronizando los comentarios del proceso",
        lambda: importar_bloques(
            job.tia.portal,
            plc,
            carpeta.bloques_modified,
            "",
        ),
        "DBs del proceso",
    )
    paso["detail"] = (
        f"{transacciones['comentarios']['estado']}: DBs del proceso"
    )


def _editar_comentarios(
    mapa: MapaProceso,
    textos_sd: tuple[str, str, str, str],
    carpeta: Any,
    arrays_por_db: dict[str, dict[str, dict[int, str]]],
    transacciones: dict[str, dict[str, Any]],
) -> tuple[list[str], bool]:
    """Edita los comentarios offline en ``modified/``.

    ``textos_sd`` son los pares SimaticSD releidos de la re-export (los
    comentarios actuales contra los que se confirman los cambios).

    Returns:
        Los DBs con cambios (con los DBs sin cambios recortados de
        ``modified/``) y si quedo alguno.
    """
    dcl_param, res_param, dcl_alm, res_alm = textos_sd
    actuales = _arrays_actuales(mapa, dcl_param, res_param, dcl_alm, res_alm)
    modificados: dict[str, int] = {}
    for db, arrays_db in arrays_por_db.items():
        modificados[db] = proc_confirmar_db(
            carpeta.bloques_modified,
            db,
            arrays_db,
            actuales.get(db, {}),
        )
    db_con_cambios = [db for db, n in modificados.items() if n > 0]
    _recortar_a(db_con_cambios, carpeta.bloques_modified)
    if not db_con_cambios:
        estado_no_ejecutada(
            transacciones, "comentarios", "los comentarios ya estaban al dia"
        )
    return db_con_cambios, bool(db_con_cambios)


def _recalcular_prevision(
    job: Job,
    proc_uid: int,
    plc: str,
    almacen: AlmacenExcel,
    config: ConfigArea,
    sesion: Sesion | None,
) -> dict[str, Any] | None:
    """Recalcula la prevision con la misma funcion que la genera.

    Lo anterior ya esta confirmado en TIA: si el recuento falla, se avisa
    pero no se tumba el trabajo (devuelve ``None``).
    """
    try:
        return generar_prevision(
            job,
            proc_uid,
            plc,
            almacen,
            config,
            sesion,
            con_pasos=False,
        )
    except Exception as exc:
        # Lo anterior ya esta confirmado: el fallo se avisa, pero no
        # tumba el trabajo.
        aviso = (
            f"No se pudo recalcular la prevision tras el sync: {exc}. "
            "Los cambios ya estan aplicados en TIA."
        )
        logger.warning(aviso)
        job.log(aviso, nivel="warning")
        return None


def _armar_resultado(
    plc: str,
    proc_uid: int,
    ops_n_max: list[dict[str, Any]],
    arrays: dict[str, dict[str, dict[int, str | None]]],
    transacciones: dict[str, dict[str, Any]],
    detalle_compilacion: str,
    prevision: dict[str, Any] | None,
) -> dict[str, Any]:
    """El resumen del sync: que se aplico, como quedo cada transaccion y la
    prevision posterior."""
    resumen = proc_resumen(arrays)
    return {
        "plc": plc,
        "proc_uid": proc_uid,
        "operaciones": (
            len(ops_n_max)
            + resumen["agregados"]
            + resumen["renombrados"]
            + resumen["eliminados"]
        ),
        "n_max": {"actualizados": len(ops_n_max)},
        "comentarios": resumen,
        "transacciones": list(transacciones.values()),
        "compilacion": detalle_compilacion,
        "prevision": prevision,
    }


# ── los helpers de ficheros de la copia modified ───────────────────────────


def _copiar_bloques(
    origen: Path,
    destino: Path,
    rutas_db: dict[str, Path | None],
) -> None:
    """Copia a ``modified`` los pares SimaticSD de los DBs exportados.

    Cada DB conserva su ruta relativa dentro del export (la carpeta de TIA):
    al importar desde la raiz de ``modified/`` TIA lo hace UPDATE en su sitio
    original. Lo que se importa en TIA es la copia, no el export.
    """
    for db, ruta in rutas_db.items():
        if ruta is None:
            continue
        par = origen / ruta / f"{db}{EXTENSION_DCL}"
        destino_par = destino / ruta / f"{db}{EXTENSION_DCL}"
        if par.is_file():
            _copiar_par(par, destino_par)
        else:
            logger.warning(
                "[proc sync] No se encontro '%s' en la exportacion: se omite "
                "del sync.",
                par,
            )


def _copiar_par(origen: Path, destino: Path) -> None:
    """Copia un par ``.s7dcl``/``.s7res`` conservando la carpeta destino."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    for extension in (EXTENSION_DCL, EXTENSION_RES):
        fichero = origen.with_suffix(extension)
        if fichero.is_file():
            shutil.copy2(fichero, destino.with_suffix(extension))


def _ruta_relativa_db(base: Path, db: str) -> Path | None:
    """La ruta relativa del par de un DB dentro del export, o ``None``.

    Con ``mantener_estructura=True`` el par puede estar en la raiz del
    export o dentro de la carpeta de TIA del DB.
    """
    par = proc_localizar_db(base, db)
    if par is None:
        return None
    return par[0].parent.relative_to(base)


def _recortar_a(dbs: list[str], carpeta: Path) -> None:
    """Deja en ``modified/`` solo los DBs indicados (el resto se borra).

    La transaccion de comentarios importa desde la raiz de ``modified/``:
    si alli queda un DB sin cambios, TIA lo vuelve a importar tal cual.
    """
    dbs = set(dbs)
    for dcl in sorted(carpeta.rglob(f"*{EXTENSION_DCL}")):
        if dcl.stem in dbs:
            continue
        dcl.unlink(missing_ok=True)
        dcl.with_suffix(EXTENSION_RES).unlink(missing_ok=True)


def _arrays_actuales(
    mapa: MapaProceso,
    dcl_param: str,
    res_param: str,
    dcl_alm: str,
    res_alm: str,
) -> dict[str, dict[str, dict[int, str | None]]]:
    """Los comentarios actuales por DB y por array, leidos del export.

    El DB_PARAM lleva los seis arrays (PReal y PInt con sus satelites) y el
    DB_ALM el ``ALM``. Un DB que no se pudo leer no aparece.
    """
    # Los principales y su DB: los seis arrays de ``ARRAYS_PROCESO`` (sin
    # los satelites, que se aplican con el mapa de su principal) mas el
    # ``ALM``, que no esta en ``ARRAYS_PROCESO``.
    principales = [
        (nombre, tipo, mapa.db_param_name)
        for nombre, tipo, principal in ARRAYS_PROCESO
        if nombre == principal
    ]
    principales.append(("ALM", proc_tipo_array("ALM"), mapa.db_alm_name))
    textos = {
        mapa.db_param_name: (dcl_param, res_param),
        mapa.db_alm_name: (dcl_alm, res_alm),
    }
    slot_maps = {
        "PReal": mapa.preal,
        "PInt": mapa.pint,
        "ALM": mapa.alm,
    }
    resultado: dict[str, dict[str, dict[int, str | None]]] = {}
    for nombre, tipo, db in principales:
        if db in mapa.db_missing:
            continue
        dcl, res = textos[db]
        actual = proc_slots_actuales(
            dcl, res, nombre, slot_maps[nombre], tipo
        )
        if actual is None:
            continue
        resultado.setdefault(db, {})[nombre] = actual
        for satelite in SATELITES_POR_ARRAY.get(nombre, ()):
            resultado.setdefault(db, {})[satelite] = actual
    return resultado
