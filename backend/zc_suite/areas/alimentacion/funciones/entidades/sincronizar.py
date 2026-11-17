"""zc_suite.areas.alimentacion.funciones.entidades.sincronizar — el sync.

Es un **FB**: recibe el ``job``, declara sus pasos y se ejecuta entero dentro
del hilo de TIA.

Es el port de ``function_entidades_sincronizar`` de ``main``. Las tres
transacciones van **en su orden** y **cada una se comprueba**:

1. **N_MAX** (en linea): el valor de ``N_MAX_ENTIDAD``, que redimensiona el
   array ``ENT[]`` del DB.
2. **Constantes** (offline): la importacion de la tabla de tags ya editada en
   disco.
3. **Comentarios** (offline, solo desde TIA V21): los comentarios por
   instancia del DB de entidades.

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
import time
from pathlib import Path
from typing import Any

from zc_suite.areas.alimentacion.config import ConfigArea
from zc_suite.areas.alimentacion.entidades.diferencias import (
    ent_calcular_diff_comentarios,
    ent_calcular_diff_constantes,
    ent_calcular_diff_n_max,
    ent_leer_par_sd,
)
from zc_suite.areas.alimentacion.entidades.sincronizacion import (
    ent_calcular_operaciones_comentarios,
    ent_calcular_operaciones_constantes,
    ent_copiar_y_editar,
)
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel
from zc_suite.areas.alimentacion.funciones._transaccion import _transaccion
from zc_suite.areas.alimentacion.funciones.entidades.generar_prevision import (
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
    localizar_xml,
)
from zc_suite.nucleo.sesion import Sesion
from zc_suite.nucleo.tia.job import Job
from zc_suite.nucleo.tia.workdir import Workdir, workdir
from zc_suite.simatic.sd.cabecera import soporta_simaticsd
from zc_suite.tia_ops.compilar import compilar_bloques
from zc_suite.tia_ops.constantes import cambiar_valor
from zc_suite.tia_ops.exportar import exportar_bloques, exportar_tablas
from zc_suite.tia_ops.importar import importar_bloques, importar_tablas

logger = logging.getLogger(__name__)

#: El area y el contexto del workdir de las entidades.
AREA = "alimentacion"
CONTEXTO = "entidades"

#: Segundos que se espera a que TIA consolide tras la transaccion de N_MAX.
PAUSA_CONSOLIDACION_S = 2.0

#: La transaccion se confirmo: TIA guardo los cambios.
CONFIRMADA = ESTADO_CONFIRMADA

#: La transaccion fallo y se revirtio: TIA no guardo nada.
REVIRTIDA = ESTADO_REVIRTIDA

#: La transaccion no llego a ejecutarse.
NO_EJECUTADA = ESTADO_NO_EJECUTADA

#: La cola final del aviso de una compilacion con errores de las entidades.
COLA_COMPILACION = (
    " Revisa ese bloque en TIA Portal: puede haber quedado con "
    "un tamano inconsistente tras el cambio de N_MAX."
)

#: Los pasos del sync, declarados al inicio del trabajo.
PASOS = (
    ("exportar", "Exportar etiquetas y DB"),
    ("diferencias", "Calcular diferencias"),
    ("preparar", "Preparar operaciones"),
    ("tx_n_max", "Aplicar N_MAX"),
    ("consolidacion", "Esperar consolidación TIA"),
    ("reexportar", "Re-exportar etiquetas y DB"),
    ("editar", "Editar archivos offline"),
    ("tx_constantes", "Aplicar constantes"),
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
    """Aplica en TIA los cambios de entidades que dice el Excel.

    Args:
        job: el trabajo en curso.
        plc: el PLC cuyas entidades se sincronizan.
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
    job.empezar("Sincronizar entidades", list(PASOS))
    transacciones = estados_iniciales(
        {"n_max": "N_MAX", "constantes": "Constantes", "comentarios": "Comentarios"}
    )
    carpeta = workdir(AREA, CONTEXTO, preview=("disp", "bloques"))

    # ── 1. Exportar etiquetas y DB ──────────────────────────────────────
    with job.paso("exportar") as paso:
        _exportar(job, plc, config, carpeta, paso)

    # ── 2 y 3. Diferencias y operaciones ────────────────────────────────
    ops_n_max, ops_constantes, ops_comentarios = _calcular_y_preparar(
        job, almacen, config, carpeta, plc
    )

    # ── 4. Tx A: el N_MAX (en linea) ────────────────────────────────────
    with job.paso("tx_n_max") as paso:
        _paso_n_max(job, plc, config, transacciones, ops_n_max, paso)

    # ── 5. Esperar la consolidacion de TIA ──────────────────────────────
    with job.paso("consolidacion") as paso:
        time.sleep(PAUSA_CONSOLIDACION_S)
        paso["detail"] = f"TIA consolida ({PAUSA_CONSOLIDACION_S:g} s)"

    # ── 6. Re-exportar etiquetas y DB ───────────────────────────────────
    with job.paso("reexportar") as paso:
        _reexportar(job, plc, config, carpeta, ops_n_max, paso)

    # ── 7. Editar los ficheros offline ──────────────────────────────────
    with job.paso("editar") as paso:
        edicion = _editar_ficheros(config, carpeta, ops_constantes, ops_comentarios)
        for aviso in edicion["avisos"]:
            job.log(aviso, nivel="warning")
        paso["detail"] = (
            f"{edicion['anadidos']} constantes anadidas, "
            f"{edicion['eliminados']} eliminadas, "
            f"{edicion['comentarios']} DB con comentarios"
        )

    # ── 8. Tx B: las constantes (offline) ───────────────────────────────
    with job.paso("tx_constantes") as paso:
        _paso_constantes(job, plc, carpeta, transacciones, ops_constantes, paso)

    # ── 9. Compilar los bloques ─────────────────────────────────────────
    with job.paso("compilar") as paso:
        detalle_compilacion = _compilar(job, plc, config, paso)

    # ── 10. Tx C: los comentarios (offline, solo V21+) ──────────────────
    with job.paso("tx_comentarios") as paso:
        paso["detail"] = _aplicar_comentarios(
            job, plc, carpeta, transacciones, edicion
        )

    # ── 11. Recalcular la prevision ─────────────────────────────────────
    with job.paso("prevision") as paso:
        prevision = _recalcular_prevision(
            job, plc, almacen, config, sesion, paso
        )

    return _armar_resultado(
        plc,
        ops_n_max,
        ops_constantes,
        ops_comentarios,
        transacciones,
        detalle_compilacion,
        prevision,
    )


# ── los pasos, en helpers privados ─────────────────────────────────────────


def _exportar(
    job: Job,
    plc: str,
    config: ConfigArea,
    carpeta: Workdir,
    paso: dict[str, Any],
) -> None:
    """Exporta las tablas de las entidades y su DB, partiendo limpio."""
    entidades = config.entidades
    carpeta.limpiar_sincronizar()
    exportar_tablas(
        job.tia.portal,
        plc,
        carpeta.variables_export,
        [entidades.tabla_config, entidades.tabla_tags],
        mantener_estructura=True,
    )
    exportar_bloques(
        job.tia.portal,
        plc,
        carpeta.bloques_export,
        [entidades.db],
        mantener_estructura=True,
        version_tia=job.tia.version_tia,
    )
    paso["detail"] = f"2 tablas y {entidades.db} exportados"


def _calcular_y_preparar(
    job: Job,
    almacen: AlmacenExcel,
    config: ConfigArea,
    carpeta: Workdir,
    plc: str,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Los dos pasos previos a las transacciones, en su orden.

    Abre el paso ``diferencias`` (los diffs contra el export) y el paso
    ``preparar`` (las operaciones a aplicar), cada uno con su detalle.
    """
    with job.paso("diferencias") as paso:
        filas = almacen.entidades_de(plc)
        diff_constantes, diff_n_max, diff_comentarios = _calcular_diferencias(
            almacen, filas, config, carpeta, plc
        )
        paso["detail"] = (
            f"{len(diff_constantes.agregados)} agregadas, "
            f"{len(diff_constantes.eliminados)} eliminadas, "
            f"{len(diff_comentarios.actualizados)} comentarios"
        )
    with job.paso("preparar") as paso:
        ops_n_max, ops_constantes, ops_comentarios = _preparar_operaciones(
            config, filas, diff_n_max, diff_constantes
        )
        paso["detail"] = (
            f"{len(ops_n_max)} N_MAX, {len(ops_constantes)} operaciones de constantes, "
            f"{len(ops_comentarios)} comentarios"
        )
    return ops_n_max, ops_constantes, ops_comentarios


def _calcular_diferencias(
    almacen: AlmacenExcel,
    filas: list[dict[str, Any]],
    config: ConfigArea,
    carpeta: Workdir,
    plc: str,
) -> tuple[Any, Any, Any]:
    """Los diffs de constantes, N_MAX y comentarios, contra el export."""
    entidades = config.entidades
    diff_constantes = ent_calcular_diff_constantes(
        entidades.tabla_tags,
        filas,
        localizar_xml(carpeta.variables_export, entidades.tabla_tags),
    )
    diff_n_max = ent_calcular_diff_n_max(
        entidades.tabla_config,
        almacen.n_max_de_entidades(plc),
        localizar_xml(carpeta.variables_export, entidades.tabla_config),
    )
    diff_comentarios = ent_calcular_diff_comentarios(
        entidades.db,
        entidades.array,
        filas,
        *ent_leer_par_sd(carpeta.bloques_export, entidades.db),
    )
    return diff_constantes, diff_n_max, diff_comentarios


def _preparar_operaciones(
    config: ConfigArea,
    filas: list[dict[str, Any]],
    diff_n_max: Any,
    diff_constantes: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Las operaciones del sync: N_MAX, constantes y comentarios."""
    return (
        calcular_operaciones_n_max(config.entidades.tabla_config, diff_n_max),
        ent_calcular_operaciones_constantes(diff_constantes),
        ent_calcular_operaciones_comentarios(filas),
    )


def _paso_n_max(
    job: Job,
    plc: str,
    config: ConfigArea,
    transacciones: dict[str, dict[str, Any]],
    ops_n_max: list[dict[str, Any]],
    paso: dict[str, Any],
) -> None:
    """La transaccion del N_MAX (en linea), con su compilacion defensiva."""
    if not ops_n_max:
        estado_no_ejecutada(transacciones, "n_max", "no habia nada que aplicar")
        paso["detail"] = "sin cambios de N_MAX"
        return
    _transaccion(
        job,
        transacciones,
        "n_max",
        "Actualizando el N_MAX de las entidades",
        lambda: _aplicar_n_max(job, plc, ops_n_max),
        f"{len(ops_n_max)} N_MAX",
    )
    paso["detail"] = (
        f"{transacciones['n_max']['estado']}: {len(ops_n_max)} N_MAX"
    )
    _compilacion_defensiva(job, plc, config.entidades.db)


def _reexportar(
    job: Job,
    plc: str,
    config: ConfigArea,
    carpeta: Workdir,
    ops_n_max: list[dict[str, Any]],
    paso: dict[str, Any],
) -> None:
    """Re-exporta tablas y DB cuando hubo N_MAX (pudo redimensionar)."""
    if not ops_n_max:
        paso["detail"] = "no hacia falta releer"
        return
    entidades = config.entidades
    exportar_tablas(
        job.tia.portal,
        plc,
        carpeta.variables_export,
        [entidades.tabla_config, entidades.tabla_tags],
        mantener_estructura=True,
    )
    exportar_bloques(
        job.tia.portal,
        plc,
        carpeta.bloques_export,
        [entidades.db],
        mantener_estructura=True,
        version_tia=job.tia.version_tia,
    )
    paso["detail"] = "tablas y DB releidos"


def _editar_ficheros(
    config: ConfigArea,
    carpeta: Workdir,
    ops_constantes: list[dict[str, Any]],
    ops_comentarios: list[dict[str, Any]],
) -> dict[str, Any]:
    """Copia los ficheros a ``modified`` y aplica las ediciones offline."""
    entidades = config.entidades
    return ent_copiar_y_editar(
        carpeta.variables_export,
        carpeta.variables_modified,
        carpeta.bloques_export,
        carpeta.bloques_modified,
        entidades.tabla_config,
        entidades.tabla_tags,
        config.carpetas_tia.entidades,
        entidades.db,
        entidades.array,
        ops_constantes,
        ops_comentarios,
    )


def _paso_constantes(
    job: Job,
    plc: str,
    carpeta: Workdir,
    transacciones: dict[str, dict[str, Any]],
    ops_constantes: list[dict[str, Any]],
    paso: dict[str, Any],
) -> None:
    """La transaccion de las constantes (offline), con su estado."""
    if not ops_constantes:
        estado_no_ejecutada(
            transacciones, "constantes", "no habia constantes que aplicar"
        )
        paso["detail"] = "sin cambios de constantes"
        return
    _transaccion(
        job,
        transacciones,
        "constantes",
        "Sincronizando las constantes de las entidades",
        lambda: _aplicar_constantes(job, plc, carpeta.variables_modified),
        f"{len(ops_constantes)} operaciones",
    )
    paso["detail"] = (
        f"{transacciones['constantes']['estado']}: {len(ops_constantes)} operaciones"
    )


def _compilar(job: Job, plc: str, config: ConfigArea, paso: dict[str, Any]) -> str:
    """Compila el DB de entidades, fuera de la transaccion.

    Returns:
        El detalle de la compilacion para el paso y el resultado.
    """
    detalle_compilacion = compilar_con_aviso(
        compilador=lambda: compilar_bloques(job.tia.portal, plc, [config.entidades.db]),
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
        return None
    return prevision


def _armar_resultado(
    plc: str,
    ops_n_max: list[dict[str, Any]],
    ops_constantes: list[dict[str, Any]],
    ops_comentarios: list[dict[str, Any]],
    transacciones: dict[str, dict[str, Any]],
    detalle_compilacion: str,
    prevision: dict[str, Any] | None,
) -> dict[str, Any]:
    """El resumen del sync: que se aplico, como quedo cada transaccion y la
    prevision posterior."""
    return {
        "plc": plc,
        "operaciones": len(ops_n_max) + len(ops_constantes) + len(ops_comentarios),
        "n_max": {"actualizados": len(ops_n_max)},
        "constantes": {"operaciones": len(ops_constantes)},
        "comentarios": {"operaciones": len(ops_comentarios)},
        "transacciones": list(transacciones.values()),
        "compilacion": detalle_compilacion,
        "prevision": prevision,
    }


def _aplicar_n_max(job: Job, plc: str, ops_n_max: list[dict[str, Any]]) -> None:
    """Aplica en linea el valor del N_MAX de las entidades."""
    for operacion in ops_n_max:
        cambiar_valor(
            job.tia.portal,
            plc,
            str(operacion["tabla"]),
            str(operacion["constante"]),
            int(operacion["valor"]),
        )


def _aplicar_constantes(job: Job, plc: str, modified: Path) -> None:
    """Importa la tabla de tags ya editada en disco.

    El import va **desde la raiz** de ``modified/`` y **sin carpeta destino**:
    con la carpeta vacia TIA no hace el match UPDATE de los objetos que ya
    existen, intenta crearlos y falla.
    """
    importar_tablas(job.tia.portal, plc, modified, "")


def _aplicar_comentarios(
    job: Job,
    plc: str,
    carpeta: Workdir,
    transacciones: dict[str, dict[str, Any]],
    edicion: dict[str, Any],
) -> str:
    """Importa el DB de entidades con los comentarios ya editados.

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

    if not edicion["comentarios"]:
        estado_no_ejecutada(
            transacciones, "comentarios", "los comentarios ya estaban al dia"
        )
        return "no habia comentarios que aplicar"

    _transaccion(
        job,
        transacciones,
        "comentarios",
        "Sincronizando los comentarios de las entidades",
        lambda: importar_bloques(job.tia.portal, plc, carpeta.bloques_modified, ""),
        "DB de entidades",
    )
    return f"{transacciones['comentarios']['estado']}: DB de entidades"


def _compilacion_defensiva(job: Job, plc: str, db: str) -> None:
    """Compila el DB para que TIA regenere el array redimensionado.

    Si falla, solo se avisa: el sync sigue.
    """
    try:
        compilar_bloques(job.tia.portal, plc, [db])
    except Exception as exc:
        logger.warning(
            "[ent sync] La compilacion defensiva de '%s' fallo (el sync sigue): %s",
            db,
            exc,
        )



