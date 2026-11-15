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
from zc_suite.areas.alimentacion.funciones.procesos.generar_prevision import (
    escaneo_de,
    fila_de_proceso,
    filas_de,
    generar_prevision,
    leer_par_sd,
)
from zc_suite.areas.alimentacion.procesos.diferencias import (
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
from zc_suite.errores import OperacionError
from zc_suite.nucleo.sesion import Sesion
from zc_suite.nucleo.tia.errores import CanceladoError
from zc_suite.nucleo.tia.job import Job
from zc_suite.nucleo.tia.transaccion import transaccion
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
CONFIRMADA = "confirmada"

#: La transaccion fallo y se revirtio: TIA no guardo nada.
REVIRTIDA = "revertida"

#: La transaccion no llego a ejecutarse.
NO_EJECUTADA = "no ejecutada"


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
        sesion: la sesion del backend. Del escaneo fresco de su PLC salen
            los nombres de los bloques en TIA, y al terminar se recalcula
            la prevision y se guarda en ella.

    Returns:
        El resumen del sync: que se aplico, como quedo cada transaccion y la
        prevision posterior.

    Raises:
        OperacionError: si no hay escaneo fresco, si falta la tabla o los
            dos DBs, o si falla alguna transaccion. El mensaje dice que se
            confirmo y que no.
    """
    job.empezar(
        "Sincronizar proceso",
        [
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
        ],
    )

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

    transacciones = _transacciones_iniciales()
    carpeta = workdir(AREA, CONTEXTO)

    # ── 1. Construir el mapa de slots ────────────────────────────────────
    with job.paso("mapa") as paso:
        preal_filas = filas_de(datos, "ParametrosReales")
        pint_filas = filas_de(datos, "ParametrosEnteros")
        alarmas = filas_de(datos, "Alarmas")
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
        paso["detail"] = (
            f"PReal={len(mapa.preal)}, PInt={len(mapa.pint)}, "
            f"ALM={len(mapa.alm)} slots"
        )

    # ── 2. Exportar tabla y DBs ──────────────────────────────────────────
    with job.paso("exportar") as paso:
        carpeta.limpiar_sincronizar()
        destino_variables = carpeta.variables_export
        destino_bloques = carpeta.bloques_export
        exportar_tablas(
            job.tia.portal,
            plc,
            destino_variables,
            [mapa.table_name],
            mantener_estructura=True,
        )
        # En TIA anterior a V21 no se exporta SimaticSD: el sync solo toca
        # el N_MAX y la tx de comentarios queda no ejecutada.
        sin_comentarios = not soporta_simaticsd(job.tia.version_tia)
        if sin_comentarios:
            db_a_exportar: list[str] = []
            rutas_db: dict[str, Path | None] = {}
            paso["detail"] = f"tabla {mapa.table_name} exportada (sin DBs)"
        else:
            db_a_exportar = [
                db
                for db in (mapa.db_param_name, mapa.db_alm_name)
                if db not in mapa.db_missing
            ]
            exportar_bloques(
                job.tia.portal,
                plc,
                destino_bloques,
                db_a_exportar,
                mantener_estructura=True,
                version_tia=job.tia.version_tia,
            )
            # La ruta relativa de cada DB dentro del export: la conserva la
            # copia a ``modified/``. Sin la carpeta de TIA, TIA no haria UPDATE.
            rutas_db = {
                db: _ruta_relativa_db(destino_bloques, db) for db in db_a_exportar
            }
            paso["detail"] = (
                f"tabla {mapa.table_name} y {len(db_a_exportar)} DBs exportados"
            )

    # ── 3. Preparar las operaciones ──────────────────────────────────────
    with job.paso("preparar") as paso:
        diff_n_max = proc_calcular_diff_n_max(
            mapa.table_name,
            mapa.nmax_names,
            mapa.nmax,
            _localizar_xml(destino_variables, mapa.table_name),
        )
        if diff_n_max.xml_ausente:
            # Como main: sin el XML de la tabla no se puede comparar el
            # N_MAX ni aplicar nada.
            raise OperacionError(
                f"La tabla '{mapa.table_name}' no existe en TIA (o no se pudo "
                "exportarla): lanza la prevision antes de sincronizar."
            )
        ops_n_max = proc_operaciones_n_max(mapa.table_name, diff_n_max)

        # En TIA anterior a V21 no se exporta SimaticSD: el sync solo toca
        # el N_MAX y la tx de comentarios queda no ejecutada.
        sin_comentarios = not soporta_simaticsd(job.tia.version_tia)
        if sin_comentarios:
            arrays = _arrays_vacios(mapa)
            arrays_por_db: dict[str, dict[str, dict[int, str]]] = {}
        else:
            dcl_param, res_param = leer_par_sd(
                destino_bloques, mapa.db_param_name
            )
            dcl_alm, res_alm = leer_par_sd(destino_bloques, mapa.db_alm_name)
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
        paso["detail"] = (
            f"{len(ops_n_max)} N_MAX, "
            f"{len(arrays_por_db.get(mapa.db_param_name, {}))} arrays en el "
            "DB de parametros, "
            f"{len(arrays_por_db.get(mapa.db_alm_name, {}))} arrays en el "
            "DB de alarmas"
        )

    # ── 4. Tx A: los N_MAX (en linea) ────────────────────────────────────
    with job.paso("tx_n_max") as paso:
        if not ops_n_max:
            transacciones["n_max"]["estado"] = NO_EJECUTADA
            transacciones["n_max"]["detalle"] = "no habia nada que aplicar"
            paso["detail"] = "sin cambios de N_MAX"
        else:
            _transaccion(
                job,
                transacciones,
                "n_max",
                "Actualizando los N_MAX del proceso",
                lambda: _aplicar_n_max(job, plc, mapa.table_name, ops_n_max),
                f"{len(ops_n_max)} N_MAX",
            )
            paso["detail"] = (
                f"{transacciones['n_max']['estado']}: {len(ops_n_max)} N_MAX"
            )

    # ── 5. Esperar la consolidacion de TIA ───────────────────────────────
    with job.paso("consolidacion") as paso:
        time.sleep(PAUSA_CONSOLIDACION_S)
        paso["detail"] = f"TIA consolida ({PAUSA_CONSOLIDACION_S:g} s)"

    # ── 6. Compilar los bloques (siempre que hubo N_MAX) ────────────────
    # Como main: se compila antes de re-exportar, porque TIA no exporta
    # bloques inconsistentes. No depende de si los comentarios cambian.
    compilacion = {"ok": True, "error": None, "detalle": "compile=no-op"}
    with job.paso("compilar") as paso:
        if ops_n_max and not sin_comentarios:
            compilacion = _compilar(
                job,
                plc,
                [
                    db
                    for db in (mapa.db_param_name, mapa.db_alm_name)
                    if db not in mapa.db_missing
                ],
            )
        paso["detail"] = compilacion["detalle"]

    # ── 7. Re-exportar tabla y DBs (solo si hubo N_MAX) ─────────────────
    with job.paso("reexportar") as paso:
        if ops_n_max:
            exportar_tablas(
                job.tia.portal,
                plc,
                destino_variables,
                [mapa.table_name],
                mantener_estructura=True,
            )
            if sin_comentarios:
                # V18: no se re-exportan bloques (no hay SimaticSD).
                paso["detail"] = "tabla releida (los DBs no se re-exportan)"
            else:
                exportar_bloques(
                    job.tia.portal,
                    plc,
                    destino_bloques,
                    db_a_exportar,
                    mantener_estructura=True,
                    version_tia=job.tia.version_tia,
                )
                # Los comentarios actuales se re-leen de la re-export: el N_MAX
                # pudo redimensionar los arrays.
                dcl_param, res_param = leer_par_sd(
                    destino_bloques, mapa.db_param_name
                )
                dcl_alm, res_alm = leer_par_sd(destino_bloques, mapa.db_alm_name)
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
                paso["detail"] = "tabla y DBs releidos"
        else:
            paso["detail"] = "no hacia falta releer"

    # ── 8. Copiar los DBs a modified ──────────────────────────────────────
    with job.paso("copiar") as paso:
        if sin_comentarios:
            paso["detail"] = "no hay que copiar (sin comentarios en esta version)"
        else:
            _copiar_bloques(destino_bloques, carpeta.bloques_modified, rutas_db)
            paso["detail"] = f"{len(rutas_db)} DBs copiados a modified"

    # ── 9. Editar los comentarios offline ────────────────────────────────
    con_cambios = False
    with job.paso("editar") as paso:
        if not soporta_simaticsd(job.tia.version_tia):
            transacciones["comentarios"]["estado"] = NO_EJECUTADA
            transacciones["comentarios"]["detalle"] = (
                "los comentarios por instancia necesitan TIA Portal V21 o superior"
            )
            paso["detail"] = "no ejecutada: TIA Portal anterior a V21"
        else:
            actuales = _arrays_actuales(
                mapa, dcl_param, res_param, dcl_alm, res_alm
            )
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
            con_cambios = bool(db_con_cambios)
            if not con_cambios:
                transacciones["comentarios"]["estado"] = NO_EJECUTADA
                transacciones["comentarios"]["detalle"] = (
                    "los comentarios ya estaban al dia"
                )
            paso["detail"] = (
                f"{len(db_con_cambios)} DBs con cambios"
                if con_cambios
                else "sin cambios"
            )

    # ── 10. Tx B: los comentarios (offline, solo V21+) ──────────────────
    with job.paso("tx_comentarios") as paso:
        if con_cambios:
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
        else:
            paso["detail"] = transacciones["comentarios"]["detalle"]

    # ── 11. Recalcular la prevision ──────────────────────────────────────
    prevision: dict[str, Any] | None = None
    with job.paso("prevision") as paso:
        try:
            prevision = generar_prevision(
                job,
                proc_uid,
                plc,
                almacen,
                config,
                sesion,
                con_pasos=False,
            )
            paso["detail"] = f"{prevision['summary']['total']} cambios en la vista"
        except Exception as exc:
            # Lo anterior ya esta confirmado: el fallo se avisa, pero no
            # tumba el trabajo.
            aviso = (
                f"No se pudo recalcular la prevision tras el sync: {exc}. "
                "Los cambios ya estan aplicados en TIA."
            )
            logger.warning(aviso)
            job.log(aviso, nivel="warning")
            paso["detail"] = "no se pudo recalcular la prevision"

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
        "compilacion": compilacion,
        "prevision": prevision,
    }


# ── los helpers privados del FB ─────────────────────────────────────────────


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


def _localizar_xml(base: Path, tabla: str) -> Path:
    """Localiza el XML de una tabla dentro de un export de TIA.

    Tolera los dos layouts: plano o con la jerarquia de carpetas del PLC.
    """
    directo = base / f"{tabla}.xml"
    if directo.is_file():
        return directo
    for encontrado in sorted(base.rglob(f"{tabla}.xml")):
        return encontrado
    return base / f"{tabla}.xml"


def _arrays_vacios(mapa: MapaProceso) -> dict[str, Any]:
    """Los tres arrays del proceso sin datos: TIA anterior a V21.

    Misma forma que ``proc_calcular_arrays``, pero con el slot_map vacio:
    sin SimaticSD no hay comentarios que comparar.
    """
    configuracion = (
        ("PReal", mapa.preal, mapa.db_param_name),
        ("PInt", mapa.pint, mapa.db_param_name),
        ("ALM", mapa.alm, mapa.db_alm_name),
    )
    return {
        nombre: {
            "db_name": db,
            "array_name": nombre,
            "satellite_arrays": list(SATELITES_POR_ARRAY.get(nombre, ())),
            "current_count": 0,
            "desired_count": len(slot_map),
            "slot_map": {},
            "summary": {
                "total": 0,
                "agregados": 0,
                "renombrados": 0,
                "eliminados": 0,
                "sin_cambios": 0,
            },
        }
        for nombre, slot_map, db in configuracion
    }


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


def _transacciones_iniciales() -> dict[str, dict[str, Any]]:
    """Las transacciones del sync, todas sin ejecutar."""
    return {
        "n_max": {
            "nombre": "N_MAX",
            "estado": NO_EJECUTADA,
            "detalle": "",
        },
        "comentarios": {
            "nombre": "Comentarios",
            "estado": NO_EJECUTADA,
            "detalle": "",
        },
    }


def _transaccion(
    job: Job,
    transacciones: dict[str, dict[str, Any]],
    clave: str,
    texto: str,
    operacion: Any,
    resumen: str,
) -> None:
    """Ejecuta una transaccion y anota si se confirmo o se revirtio.

    Args:
        job: el trabajo en curso.
        transacciones: el estado de las transacciones del sync.
        clave: la clave de la transaccion dentro de ``transacciones``.
        texto: el texto de la transaccion en TIA.
        operacion: lo que se hace dentro de la transaccion.
        resumen: lo que se cuenta en el detalle del paso.

    Raises:
        Exception: lo que falle dentro de la transaccion, con el estado de
            las transacciones anadido al mensaje.
    """
    try:
        with transaccion(job, texto):
            operacion()
    except CanceladoError:
        # La cancelacion del operario no es un fallo: sale tal cual para que
        # el trabajo termine como cancelado y no como error.
        transacciones[clave]["estado"] = REVIRTIDA
        transacciones[clave]["detalle"] = "el trabajo fue cancelado"
        raise
    except Exception as exc:
        transacciones[clave]["estado"] = REVIRTIDA
        transacciones[clave]["detalle"] = str(exc)
        raise OperacionError(
            f"{exc}. {_resumen_de_transacciones(transacciones)}"
        ) from exc
    transacciones[clave]["estado"] = CONFIRMADA
    transacciones[clave]["detalle"] = resumen


def _resumen_de_transacciones(transacciones: dict[str, dict[str, Any]]) -> str:
    """El estado de las transacciones, en una frase."""
    partes = [
        f"{datos['nombre']}: {datos['estado']}" for datos in transacciones.values()
    ]
    return "Transacciones: " + "; ".join(partes) + "."


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


def _compilar(job: Job, plc: str, dbs: list[str]) -> dict[str, Any]:
    """Compila los DBs del proceso, fuera de la transaccion.

    Los errores de compilacion **no** tumban el sync: el commit ya esta
    aplicado y el operario tiene que ver el error, no perder el trabajo.
    """
    try:
        resultado = compilar_bloques(job.tia.portal, plc, dbs)
    except Exception as exc:
        aviso = f"La compilacion fallo (los cambios ya estan aplicados): {exc}"
        logger.warning(aviso)
        return {"ok": False, "error": str(exc), "detalle": "compile=WARN"}
    if resultado["n_compilados_error"] or resultado["n_errores"]:
        partes = []
        if resultado["con_errores"]:
            detalles = []
            for compilado in resultado["compilados"]:
                if not compilado["tiene_errores"]:
                    continue
                mensajes = compilado.get("mensajes") or []
                if mensajes:
                    detalles.append(
                        f"{compilado['nombre']} ({_mensaje_corto(mensajes[0])})"
                    )
                else:
                    detalles.append(compilado["nombre"])
            partes.append(
                f"{len(resultado['con_errores'])} bloque(s) con errores: "
                + ", ".join(detalles)
            )
        if resultado["errores"]:
            partes.append(
                f"{len(resultado['errores'])} no se pudieron compilar: "
                + ", ".join(e["nombre"] for e in resultado["errores"])
            )
        if resultado["no_encontrados"]:
            partes.append(
                f"{len(resultado['no_encontrados'])} no encontrado(s): "
                + ", ".join(resultado["no_encontrados"])
            )
        error = (
            "TIA reporta errores de compilacion: "
            + "; ".join(partes)
            + ". Revisa ese bloque en TIA Portal: puede haber quedado con "
            "un tamano inconsistente tras el cambio de N_MAX."
        )
        logger.warning(
            "Compilacion con errores (los cambios ya estan aplicados): %s", error
        )
        return {"ok": False, "error": error, "detalle": "compile=WARN"}
    return {
        "ok": True,
        "error": None,
        "detalle": (
            f"compile=OK ({resultado['n_compilados_ok']} compilados, "
            f"{resultado['n_sin_cambios']} sin cambios)"
        ),
    }


def _mensaje_corto(mensaje: str) -> str:
    """El mensaje de TIA sin la ruta del bloque.

    ``"ZC_PLC_STD > Program blocks > DB6_ENT (DB6) > Interface > Data type
    Boo is unknown."`` queda en ``"Interface > Data type Boo is unknown."``.
    """
    partes = [parte.strip() for parte in mensaje.split(" > ")]
    for indice, parte in enumerate(partes):
        if parte.endswith(")") and "(" in parte:
            resto = partes[indice + 1 :]
            return " > ".join(resto) if resto else mensaje
    return mensaje
