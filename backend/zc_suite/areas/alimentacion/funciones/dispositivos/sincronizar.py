"""zc_suite.areas.alimentacion.funciones.dispositivos.sincronizar — el sync.

Es un **FB**: recibe el ``job``, declara sus pasos y se ejecuta entero dentro
del hilo de TIA.

Es el port de ``function_disp_sincronizar`` de ``main``. Las tres
transacciones van **en su orden** y **cada una se comprueba**:

1. **N_MAX y renombres** (en linea): los valores de las constantes de usuario
   y los nombres de los dispositivos que cambiaron.
2. **Dispositivos** (offline): la importacion de las tablas de tags ya
   editadas en disco.
3. **Comentarios** (offline, solo desde TIA V21): los comentarios por
   instancia de los DBs de dispositivos.

El resultado dice **cual se confirmo, cual se revirtio y cual no se ejecuto**,
y lo mismo se ve en el faceplate: cada paso de transaccion lleva su estado en
el detalle, y los pasos que no se alcanzan se quedan pendientes.

Correcciones sobre ``main``:

- Cada transaccion **comprueba** su resultado. En ``main`` la de los
  comentarios no lo hacia: un fallo a mitad dejaba el PLC a medias sin
  enterarse.
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
from zc_suite.areas.alimentacion.dispositivos.diferencias import (
    DiffNMax,
    DiffTabla,
    disp_calcular_diff_n_max,
    disp_calcular_diff_tabla,
)
from zc_suite.areas.alimentacion.dispositivos.sincronizacion import (
    disp_calcular_cambios_dispositivos,
    disp_calcular_operaciones_n_max,
    disp_calcular_renombres,
    disp_copiar_y_editar,
    disp_localizar_xml,
    disp_mapa_comentarios,
)
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel
from zc_suite.areas.alimentacion.funciones.dispositivos.generar_prevision import (
    generar_prevision,
)
from zc_suite.errores import OperacionError
from zc_suite.nucleo.sesion import Sesion
from zc_suite.nucleo.tia.errores import CanceladoError
from zc_suite.nucleo.tia.job import Job
from zc_suite.nucleo.tia.transaccion import transaccion
from zc_suite.nucleo.tia.workdir import Workdir, workdir
from zc_suite.simatic.sd import confirmar_comentarios_array
from zc_suite.simatic.sd.cabecera import soporta_simaticsd
from zc_suite.tia_ops.compilar import compilar_bloques
from zc_suite.tia_ops.constantes import cambiar_valor, renombrar
from zc_suite.tia_ops.exportar import exportar_bloques, exportar_tablas
from zc_suite.tia_ops.importar import importar_bloques, importar_tablas

logger = logging.getLogger(__name__)

#: El area y el contexto del workdir de los dispositivos.
AREA = "alimentacion"
CONTEXTO = "disp"

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
    plc: str,
    almacen: AlmacenExcel,
    config: ConfigArea,
    sesion: Sesion | None = None,
) -> dict[str, Any]:
    """Aplica en TIA los cambios de dispositivos que dice el Excel.

    Args:
        job: el trabajo en curso.
        plc: el PLC cuyos dispositivos se sincronizan.
        almacen: la cache del Excel maestro.
        config: el modelo del area.
        sesion: la sesion del backend. Al terminar se recalcula la prevision
            y se guarda en ella.

    Returns:
        El resumen del sync: que se aplico, como quedo cada transaccion y la
        prevision posterior.

    Raises:
        OperacionError: si falla alguna transaccion. El mensaje dice que se
            confirmo y que no.
    """
    job.empezar(
        "Sincronizar dispositivos",
        [
            ("exportar", "Exportar etiquetas"),
            ("diferencias", "Calcular diferencias de dispositivos"),
            ("preparar", "Preparar operaciones"),
            ("tx_n_max", "Aplicar N_MAX y renombres"),
            ("consolidacion", "Esperar consolidación TIA"),
            ("reexportar", "Re-exportar etiquetas"),
            ("editar", "Editar archivos XML"),
            ("tx_dispositivos", "Aplicar dispositivos"),
            ("compilar", "Compilar bloques"),
            ("tx_comentarios", "Aplicar comentarios"),
            ("prevision", "Recalcular la prevision"),
        ],
    )

    transacciones = _transacciones_iniciales()
    carpeta = workdir(AREA, CONTEXTO, preview=("config", "disp"))

    # ── 1. Exportar etiquetas ───────────────────────────────────────────
    with job.paso("exportar") as paso:
        carpeta.limpiar_sincronizar()
        tablas = _tablas_selectivas(config)
        exportar_tablas(
            job.tia.portal,
            plc,
            carpeta.variables_export,
            tablas,
            mantener_estructura=True,
        )
        paso["detail"] = f"{len(tablas)} tablas exportadas"

    # ── 2. Calcular diferencias de dispositivos ──────────────────────────
    with job.paso("diferencias") as paso:
        diffs = _calcular_diffs(almacen, config, plc, carpeta.variables_export)
        diff_n_max = _calcular_diff_n_max(almacen, config, plc, carpeta.variables_export)
        agregados = sum(len(d.agregados) for d in diffs.values())
        eliminados = sum(len(d.eliminados) for d in diffs.values())
        renombrados = sum(len(d.renombrados) for d in diffs.values())
        paso["detail"] = (
            f"{agregados} agregados, {eliminados} eliminados, {renombrados} renombrados"
        )

    # ── 3. Preparar operaciones ─────────────────────────────────────────
    with job.paso("preparar") as paso:
        ops_n_max = disp_calcular_operaciones_n_max(config.tabla_nmax, diff_n_max)
        renombres = disp_calcular_renombres(diffs)
        cambios = disp_calcular_cambios_dispositivos(diffs)
        paso["detail"] = (
            f"{len(ops_n_max)} N_MAX, {len(renombres)} renombres, "
            f"{len(cambios)} tablas con cambios"
        )

    # ── 4. Tx A: N_MAX y renombres (en linea) ───────────────────────────
    with job.paso("tx_n_max") as paso:
        if not ops_n_max and not renombres:
            transacciones["n_max"]["estado"] = NO_EJECUTADA
            transacciones["n_max"]["detalle"] = "no habia nada que aplicar"
            paso["detail"] = "sin cambios de N_MAX ni renombres"
        else:
            _transaccion(
                job,
                transacciones,
                "n_max",
                "Actualizando N_MAX y renombrando dispositivos",
                lambda: _aplicar_n_max_y_renombres(
                    job, plc, ops_n_max, renombres
                ),
                f"{len(ops_n_max)} N_MAX y {len(renombres)} renombres",
            )
            paso["detail"] = (
                f"{transacciones['n_max']['estado']}: "
                f"{len(ops_n_max)} N_MAX y {len(renombres)} renombres"
            )

    # ── 5. Esperar la consolidacion de TIA ──────────────────────────────
    with job.paso("consolidacion") as paso:
        time.sleep(PAUSA_CONSOLIDACION_S)
        paso["detail"] = f"TIA consolida ({PAUSA_CONSOLIDACION_S:g} s)"

    # ── 6. Re-exportar etiquetas ────────────────────────────────────────
    with job.paso("reexportar") as paso:
        tablas_con_cambios = [str(cambio["tabla"]) for cambio in cambios]
        if tablas_con_cambios:
            exportar_tablas(
                job.tia.portal,
                plc,
                carpeta.variables_export,
                tablas_con_cambios,
                mantener_estructura=True,
            )
        paso["detail"] = f"{len(tablas_con_cambios)} tablas releidas"

    # ── 7. Editar los XML en disco ──────────────────────────────────────
    with job.paso("editar") as paso:
        edicion = disp_copiar_y_editar(
            carpeta.variables_export,
            carpeta.variables_modified,
            cambios,
        )
        paso["detail"] = (
            f"{edicion['escritos']} tags anadidos y {edicion['eliminados']} "
            f"eliminados"
        )

    # ── 8. Tx B: los dispositivos (offline) ─────────────────────────────
    with job.paso("tx_dispositivos") as paso:
        if not cambios:
            transacciones["dispositivos"]["estado"] = NO_EJECUTADA
            transacciones["dispositivos"]["detalle"] = "no habia dispositivos que aplicar"
            paso["detail"] = "sin cambios de dispositivos"
        else:
            _transaccion(
                job,
                transacciones,
                "dispositivos",
                "Sincronizando dispositivos",
                lambda: _aplicar_dispositivos(job, plc, carpeta.variables_modified),
                f"{len(cambios)} tablas",
            )
            paso["detail"] = (
                f"{transacciones['dispositivos']['estado']}: {len(cambios)} tablas"
            )

    # ── 9. Compilar los bloques ─────────────────────────────────────────
    with job.paso("compilar") as paso:
        compilacion = _compilar(job, plc, config)
        paso["detail"] = compilacion["detalle"]

    # ── 10. Tx C: los comentarios (offline, solo V21+) ──────────────────
    with job.paso("tx_comentarios") as paso:
        comentarios = _aplicar_comentarios(job, plc, almacen, config, carpeta, transacciones)
        paso["detail"] = comentarios

    # ── 11. Recalcular la prevision ─────────────────────────────────────
    prevision: dict[str, Any] | None = None
    with job.paso("prevision") as paso:
        try:
            prevision = generar_prevision(
                job,
                plc,
                almacen,
                config,
                sesion,
                con_pasos=False,
            )
            paso["detail"] = f"{prevision['summary']['total']} entradas en la vista unificada"
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

    return {
        "plc": plc,
        "operaciones": _numero_de_operaciones(ops_n_max, renombres, cambios),
        "n_max": {"actualizados": len(ops_n_max), "renombres": len(renombres)},
        "dispositivos": {
            "tablas": len(cambios),
            "agregados": sum(len(cambio["agregados"]) for cambio in cambios),
            "eliminados": sum(len(cambio["eliminados"]) for cambio in cambios),
        },
        "transacciones": list(transacciones.values()),
        "compilacion": compilacion,
        "prevision": prevision,
    }


# ── las transacciones ───────────────────────────────────────────────────────


def _transacciones_iniciales() -> dict[str, dict[str, Any]]:
    """Las tres transacciones del sync,todas sin ejecutar."""
    return {
        "n_max": {
            "nombre": "N_MAX y renombres",
            "estado": NO_EJECUTADA,
            "detalle": "",
        },
        "dispositivos": {
            "nombre": "Dispositivos",
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


# ── los pasos, en helpers privados ─────────────────────────────────────────


def _tablas_selectivas(config: ConfigArea) -> list[str]:
    """Las tablas que toca el sync: las de dispositivos y la de N_MAX."""
    tablas = [dispositivo.tabla_tags for dispositivo in config.dispositivos.values()]
    tablas.append(config.tabla_nmax)
    return tablas


def _calcular_diffs(
    almacen: AlmacenExcel,
    config: ConfigArea,
    plc: str,
    export: Path,
) -> dict[str, DiffTabla]:
    """El diff de cada tabla de dispositivos, contra el XML exportado."""
    diffs: dict[str, DiffTabla] = {}
    for tipo, dispositivo in config.dispositivos.items():
        tabla = dispositivo.tabla_tags
        xml = disp_localizar_xml(export, tabla)
        if xml is None:
            aviso = (
                f"La tabla '{tabla}' no esta en la exportacion de TIA: "
                "sus dispositivos se omiten del sync."
            )
            logger.warning(aviso)
            continue
        diffs[tabla] = disp_calcular_diff_tabla(
            tabla,
            almacen.dispositivos_de(tipo, plc),
            xml,
        )
    return diffs


def _calcular_diff_n_max(
    almacen: AlmacenExcel,
    config: ConfigArea,
    plc: str,
    export: Path,
) -> DiffNMax:
    """El diff de los N_MAX, contra el XML exportado."""
    xml = disp_localizar_xml(export, config.tabla_nmax)
    return disp_calcular_diff_n_max(
        config.tabla_nmax,
        almacen.valores_n_max_de(plc),
        xml if xml is not None else export / f"{config.tabla_nmax}.xml",
    )


def _aplicar_n_max_y_renombres(
    job: Job,
    plc: str,
    ops_n_max: list[dict[str, Any]],
    renombres: list[dict[str, str]],
) -> None:
    """Aplica en linea los N_MAX y los renombres."""
    for operacion in ops_n_max:
        cambiar_valor(
            job.tia.portal,
            plc,
            str(operacion["tabla"]),
            str(operacion["constante"]),
            int(operacion["valor"]),
        )
    for operacion in renombres:
        renombrar(
            job.tia.portal,
            plc,
            str(operacion["tabla"]),
            str(operacion["actual"]),
            str(operacion["nuevo"]),
        )


def _aplicar_dispositivos(job: Job, plc: str, modified: Path) -> None:
    """Importa las tablas de tags ya editadas en disco.

    El import va **desde la raiz** de ``modified/`` y **sin carpeta destino**:
    con la carpeta vacia TIA no hace el match UPDATE de los objetos que ya
    existen, intenta crearlos y falla.
    """
    importar_tablas(job.tia.portal, plc, modified, "")


def _compilar(job: Job, plc: str, config: ConfigArea) -> dict[str, Any]:
    """Compila los DBs de dispositivos, fuera de la transaccion.

    Los errores de compilacion **no** tumban el sync: el commit ya esta
    aplicado y el operario tiene que ver el error, no perder el trabajo.
    """
    dbs = [dispositivo.db for dispositivo in config.dispositivos.values()]
    if not dbs:
        return {"ok": True, "error": None, "detalle": "sin DBs que compilar"}
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
                    detalles.append(f"{compilado['nombre']} ({_mensaje_corto(mensajes[0])})")
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
            + ". Revisa esos bloques en TIA Portal: pueden haber quedado con "
            "un tamano inconsistente tras el cambio de N_MAX."
        )
        logger.warning("Compilacion con errores (los cambios ya estan aplicados): %s", error)
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

    ``"ZC_PLC_STD > Program blocks > DB5 (DB5) > Interface > Data type Boo
    is unknown."`` queda en ``"Interface > Data type Boo is unknown."``.
    """
    partes = [parte.strip() for parte in mensaje.split(" > ")]
    for indice, parte in enumerate(partes):
        if parte.endswith(")") and "(" in parte:
            resto = partes[indice + 1:]
            return " > ".join(resto) if resto else mensaje
    return mensaje


def _aplicar_comentarios(
    job: Job,
    plc: str,
    almacen: AlmacenExcel,
    config: ConfigArea,
    carpeta: Workdir,
    transacciones: dict[str, dict[str, Any]],
) -> str:
    """Aplica los comentarios por instancia de los DBs de dispositivos.

    Solo con TIA V21 o superior: la exportacion en SimaticSD no existe antes.

    Returns:
        El detalle del paso.
    """
    if not soporta_simaticsd(job.tia.version_tia):
        transacciones["comentarios"]["estado"] = NO_EJECUTADA
        transacciones["comentarios"]["detalle"] = (
            "los comentarios por instancia necesitan TIA Portal V21 o superior"
        )
        return "no ejecutada: TIA Portal anterior a V21"

    mapas = _mapas_de_comentarios(almacen, config, plc)
    if not mapas:
        transacciones["comentarios"]["estado"] = NO_EJECUTADA
        transacciones["comentarios"]["detalle"] = "no hay comentarios que aplicar"
        return "no habia comentarios que aplicar"

    dbs = [dispositivo.db for dispositivo in config.dispositivos.values()]
    try:
        exportar_bloques(
            job.tia.portal,
            plc,
            carpeta.bloques_export,
            dbs,
            mantener_estructura=True,
            version_tia=job.tia.version_tia,
        )
    except Exception as exc:
        transacciones["comentarios"]["detalle"] = str(exc)
        raise OperacionError(
            f"{exc}. {_resumen_de_transacciones(transacciones)}"
        ) from exc
    if carpeta.bloques_export.is_dir():
        shutil.copytree(
            carpeta.bloques_export,
            carpeta.bloques_modified,
            dirs_exist_ok=True,
        )

    modificados = _confirmar_comentarios(mapas, config, carpeta.bloques_modified)
    if not modificados:
        transacciones["comentarios"]["estado"] = NO_EJECUTADA
        transacciones["comentarios"]["detalle"] = "los comentarios ya estaban al dia"
        return "no habia comentarios que aplicar"

    _transaccion(
        job,
        transacciones,
        "comentarios",
        "Sincronizando comentarios de dispositivos",
        lambda: importar_bloques(job.tia.portal, plc, carpeta.bloques_modified, ""),
        f"{modificados} DBs con comentarios",
    )
    return (
        f"{transacciones['comentarios']['estado']}: {modificados} DBs con comentarios"
    )


def _mapas_de_comentarios(
    almacen: AlmacenExcel,
    config: ConfigArea,
    plc: str,
) -> dict[str, dict[int, str]]:
    """El mapa de slots de cada tipo de dispositivo, para el PLC elegido."""
    mapas: dict[str, dict[int, str]] = {}
    for tipo, dispositivo in config.dispositivos.items():
        filas = almacen.dispositivos_de(tipo, plc)
        if not filas:
            continue
        mapas[dispositivo.db] = disp_mapa_comentarios(filas)
    return mapas


def _confirmar_comentarios(
    mapas: dict[str, dict[int, str]],
    config: ConfigArea,
    modified: Path,
) -> int:
    """Escribe los comentarios en los ``.s7dcl``/``.s7res`` de ``modified/``.

    Returns:
        Cuantos DBs han cambiado.
    """
    carpeta_tia = config.carpetas_tia.dispositivos
    arrays = {dispositivo.db: dispositivo.array for dispositivo in config.dispositivos.values()}
    modificados = 0
    for db, mapa in mapas.items():
        base = modified / carpeta_tia if carpeta_tia else modified
        dcl = base / f"{db}.s7dcl"
        res = base / f"{db}.s7res"
        if not dcl.is_file() or not res.is_file():
            logger.warning(
                "[disp sync] No se encontro el bloque '%s' en la exportacion: "
                "sus comentarios se omiten.",
                db,
            )
            continue
        resultado = confirmar_comentarios_array(
            dcl,
            res,
            arrays.get(db, ""),
            mapa,
            array_type="Simple",
            write_to_original=True,
        )
        if resultado.injected or resultado.updated or resultado.removed:
            modificados += 1
    return modificados


def _numero_de_operaciones(
    ops_n_max: list[dict[str, Any]],
    renombres: list[dict[str, str]],
    cambios: list[dict[str, Any]],
) -> int:
    """Cuantas operaciones se han aplicado en TIA."""
    agregados = sum(len(cambio["agregados"]) for cambio in cambios)
    eliminados = sum(len(cambio["eliminados"]) for cambio in cambios)
    return len(ops_n_max) + len(renombres) + agregados + eliminados
