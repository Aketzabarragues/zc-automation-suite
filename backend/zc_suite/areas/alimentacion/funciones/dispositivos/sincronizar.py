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

El estado de las transacciones, el texto del aviso de compilacion y los
helpers de texto y rutas los aporta ``sincronizacion_comun``: lo comun de los
cuatro FB de sync, en un solo sitio.

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
    disp_calcular_renombres,
    disp_copiar_y_editar,
    disp_localizar_xml,
    disp_mapa_comentarios,
)
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel
from zc_suite.areas.alimentacion.funciones._transaccion import _transaccion
from zc_suite.areas.alimentacion.funciones.dispositivos.generar_prevision import (
    generar_prevision,
)
from zc_suite.areas.alimentacion.sincronizacion_comun import (
    ESTADO_CONFIRMADA,
    ESTADO_NO_EJECUTADA,
    ESTADO_REVIRTIDA,
    calcular_operaciones_n_max,
    compilar_con_aviso,
    estado_no_ejecutada,
    estados_iniciales,
    resumen_transacciones,
)
from zc_suite.errores import OperacionError
from zc_suite.nucleo.sesion import Sesion
from zc_suite.nucleo.tia.job import Job
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
CONFIRMADA = ESTADO_CONFIRMADA

#: La transaccion fallo y se revirtio: TIA no guardo nada.
REVIRTIDA = ESTADO_REVIRTIDA

#: La transaccion no llego a ejecutarse.
NO_EJECUTADA = ESTADO_NO_EJECUTADA

#: La cola final del aviso de una compilacion con errores de los dispositivos.
#: Plural (``esos``): se compilan todos los DBs de dispositivos.
COLA_COMPILACION = (
    " Revisa esos bloques en TIA Portal: pueden haber quedado con "
    "un tamano inconsistente tras el cambio de N_MAX."
)

#: Los pasos del sync, declarados al inicio del trabajo.
PASOS = (
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
)


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
        sesion: la sesion del backend; al terminar se recalcula la prevision.

    Returns:
        El resumen del sync: que se aplico, como quedo cada transaccion y la
        prevision posterior.

    Raises:
        OperacionError: si falla alguna transaccion; el mensaje dice que se
            confirmo y que no.
    """
    job.empezar("Sincronizar dispositivos", list(PASOS))

    transacciones = estados_iniciales(
        {
            "n_max": "N_MAX y renombres",
            "dispositivos": "Dispositivos",
            "comentarios": "Comentarios",
        }
    )
    carpeta = workdir(AREA, CONTEXTO, preview=("config", "disp"))

    # ── 1. Exportar etiquetas ───────────────────────────────────────────
    with job.paso("exportar") as paso:
        _exportar_etiquetas(job, plc, config, carpeta, paso)

    # ── 2. Calcular diferencias de dispositivos ──────────────────────────
    with job.paso("diferencias") as paso:
        diffs, diff_n_max = _calcular_diferencias(almacen, config, plc, carpeta)
        paso["detail"] = _resumen_diferencias(diffs)

    # ── 3. Preparar operaciones ─────────────────────────────────────────
    with job.paso("preparar") as paso:
        ops_n_max, renombres, cambios = _preparar_operaciones(config, diffs, diff_n_max)
        paso["detail"] = (
            f"{len(ops_n_max)} N_MAX, {len(renombres)} renombres, "
            f"{len(cambios)} tablas con cambios"
        )

    # ── 4. Tx A: N_MAX y renombres (en linea) ───────────────────────────
    with job.paso("tx_n_max") as paso:
        _paso_n_max_y_renombres(job, plc, transacciones, ops_n_max, renombres, paso)

    # ── 5. Esperar la consolidacion de TIA ──────────────────────────────
    with job.paso("consolidacion") as paso:
        time.sleep(PAUSA_CONSOLIDACION_S)
        paso["detail"] = f"TIA consolida ({PAUSA_CONSOLIDACION_S:g} s)"

    # ── 6. Re-exportar etiquetas ────────────────────────────────────────
    with job.paso("reexportar") as paso:
        _reexportar_etiquetas(job, plc, carpeta, cambios, paso)

    # ── 7. Editar los XML en disco ──────────────────────────────────────
    with job.paso("editar") as paso:
        _editar_xml(carpeta, cambios, paso)

    # ── 8. Tx B: los dispositivos (offline) ─────────────────────────────
    with job.paso("tx_dispositivos") as paso:
        _paso_dispositivos(job, plc, carpeta, transacciones, cambios, paso)

    # ── 9. Compilar los bloques ─────────────────────────────────────────
    with job.paso("compilar") as paso:
        detalle_compilacion = _compilar_dispositivos(job, plc, config, paso)

    # ── 10. Tx C: los comentarios (offline, solo V21+) ──────────────────
    with job.paso("tx_comentarios") as paso:
        paso["detail"] = _aplicar_comentarios(
            job, plc, almacen, config, carpeta, transacciones
        )

    # ── 11. Recalcular la prevision ─────────────────────────────────────
    with job.paso("prevision") as paso:
        prevision = _recalcular_prevision(job, plc, almacen, config, sesion, paso)

    return _armar_resultado(
        plc, ops_n_max, renombres, cambios, transacciones, detalle_compilacion, prevision
    )


# ── los pasos, en helpers privados ─────────────────────────────────────────


def _exportar_etiquetas(
    job: Job,
    plc: str,
    config: ConfigArea,
    carpeta: Workdir,
    paso: dict[str, Any],
) -> None:
    """Exporta las tablas que toca el sync, partiendo de la carpeta limpia."""
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


def _calcular_diferencias(
    almacen: AlmacenExcel,
    config: ConfigArea,
    plc: str,
    carpeta: Workdir,
) -> tuple[dict[str, DiffTabla], DiffNMax]:
    """El diff de cada tabla de dispositivos y el de los N_MAX."""
    return (
        _calcular_diffs(almacen, config, plc, carpeta.variables_export),
        _calcular_diff_n_max(almacen, config, plc, carpeta.variables_export),
    )


def _resumen_diferencias(diffs: dict[str, DiffTabla]) -> str:
    """El detalle del paso de diferencias: agregados, eliminados, renombrados."""
    agregados = sum(len(d.agregados) for d in diffs.values())
    eliminados = sum(len(d.eliminados) for d in diffs.values())
    renombrados = sum(len(d.renombrados) for d in diffs.values())
    return (
        f"{agregados} agregados, {eliminados} eliminados, {renombrados} renombrados"
    )


def _preparar_operaciones(
    config: ConfigArea,
    diffs: dict[str, DiffTabla],
    diff_n_max: DiffNMax,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, Any]]]:
    """Las operaciones del sync: N_MAX, renombres y cambios de tablas."""
    return (
        calcular_operaciones_n_max(config.tabla_nmax, diff_n_max),
        disp_calcular_renombres(diffs),
        disp_calcular_cambios_dispositivos(diffs),
    )


def _paso_n_max_y_renombres(
    job: Job,
    plc: str,
    transacciones: dict[str, dict[str, Any]],
    ops_n_max: list[dict[str, Any]],
    renombres: list[dict[str, str]],
    paso: dict[str, Any],
) -> None:
    """La transaccion de N_MAX y renombres (en linea), con su estado."""
    if not ops_n_max and not renombres:
        estado_no_ejecutada(
            transacciones, "n_max", "no habia nada que aplicar"
        )
        paso["detail"] = "sin cambios de N_MAX ni renombres"
        return
    _transaccion(
        job,
        transacciones,
        "n_max",
        "Actualizando N_MAX y renombrando dispositivos",
        lambda: _aplicar_n_max_y_renombres(job, plc, ops_n_max, renombres),
        f"{len(ops_n_max)} N_MAX y {len(renombres)} renombres",
    )
    paso["detail"] = (
        f"{transacciones['n_max']['estado']}: "
        f"{len(ops_n_max)} N_MAX y {len(renombres)} renombres"
    )


def _reexportar_etiquetas(
    job: Job,
    plc: str,
    carpeta: Workdir,
    cambios: list[dict[str, Any]],
    paso: dict[str, Any],
) -> None:
    """Re-exporta las tablas con cambios, para editarlas sobre lo actual."""
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


def _editar_xml(
    carpeta: Workdir,
    cambios: list[dict[str, Any]],
    paso: dict[str, Any],
) -> None:
    """Copia los XML exportados a ``modified`` y aplica los cambios."""
    edicion = disp_copiar_y_editar(
        carpeta.variables_export,
        carpeta.variables_modified,
        cambios,
    )
    paso["detail"] = (
        f"{edicion['escritos']} tags anadidos y {edicion['eliminados']} eliminados"
    )


def _paso_dispositivos(
    job: Job,
    plc: str,
    carpeta: Workdir,
    transacciones: dict[str, dict[str, Any]],
    cambios: list[dict[str, Any]],
    paso: dict[str, Any],
) -> None:
    """La transaccion de los dispositivos (offline), con su estado."""
    if not cambios:
        estado_no_ejecutada(
            transacciones, "dispositivos", "no habia dispositivos que aplicar"
        )
        paso["detail"] = "sin cambios de dispositivos"
        return
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


def _compilar_dispositivos(
    job: Job,
    plc: str,
    config: ConfigArea,
    paso: dict[str, Any],
) -> str:
    """Compila los DBs de dispositivos, fuera de la transaccion.

    Returns:
        El detalle de la compilacion para el paso y el resultado.
    """
    dbs = [dispositivo.db for dispositivo in config.dispositivos.values()]
    if not dbs:
        detalle_compilacion = "sin DBs que compilar"
    else:
        detalle_compilacion = compilar_con_aviso(
            compilador=lambda: compilar_bloques(job.tia.portal, plc, dbs),
            cola=COLA_COMPILACION,
            logger=logger,
        )
    paso["detail"] = detalle_compilacion
    return detalle_compilacion


def _recalcular_prevision(
    job: Job,
    plc: str,
    almacen: AlmacenExcel,
    config: ConfigArea,
    sesion: Sesion | None,
    paso: dict[str, Any],
) -> dict[str, Any] | None:
    """Recalcula la prevision con la misma funcion que la genera.

    Lo anterior ya esta confirmado: si el recuento falla, se avisa pero no
    se tumba el trabajo (devuelve ``None``).
    """
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
        return None
    return prevision


def _armar_resultado(
    plc: str,
    ops_n_max: list[dict[str, Any]],
    renombres: list[dict[str, str]],
    cambios: list[dict[str, Any]],
    transacciones: dict[str, dict[str, Any]],
    detalle_compilacion: str,
    prevision: dict[str, Any] | None,
) -> dict[str, Any]:
    """El resumen del sync: que se aplico, como quedo cada transaccion y la
    prevision posterior."""
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
        "compilacion": detalle_compilacion,
        "prevision": prevision,
    }


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
        estado_no_ejecutada(
            transacciones,
            "comentarios",
            "los comentarios por instancia necesitan TIA Portal V21 o superior",
        )
        return "no ejecutada: TIA Portal anterior a V21"

    mapas = _mapas_de_comentarios(almacen, config, plc)
    if not mapas:
        estado_no_ejecutada(
            transacciones, "comentarios", "no hay comentarios que aplicar"
        )
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
            f"{exc}. {resumen_transacciones(transacciones)}"
        ) from exc
    if carpeta.bloques_export.is_dir():
        shutil.copytree(
            carpeta.bloques_export,
            carpeta.bloques_modified,
            dirs_exist_ok=True,
        )

    modificados = _confirmar_comentarios(mapas, config, carpeta.bloques_modified)
    if not modificados:
        estado_no_ejecutada(
            transacciones, "comentarios", "los comentarios ya estaban al dia"
        )
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
            tipo_array="Simple",
            escribir_en_original=True,
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
