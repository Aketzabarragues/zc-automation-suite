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
    ent_calcular_operaciones_n_max,
    ent_copiar_y_editar,
)
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel
from zc_suite.areas.alimentacion.funciones.entidades.generar_prevision import (
    generar_prevision,
)
from zc_suite.errores import OperacionError
from zc_suite.nucleo.sesion import Sesion
from zc_suite.nucleo.tia.errores import CanceladoError
from zc_suite.nucleo.tia.job import Job
from zc_suite.nucleo.tia.transaccion import transaccion
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
    """Aplica en TIA los cambios de entidades que dice el Excel.

    Args:
        job: el trabajo en curso.
        plc: el PLC cuyas entidades se sincronizan.
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
        "Sincronizar entidades",
        [
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
        ],
    )

    entidades = config.entidades
    db = entidades.db
    array = entidades.array
    tabla_tags = entidades.tabla_tags
    tabla_config = entidades.tabla_config
    carpeta_tia = config.carpetas_tia.entidades

    transacciones = _transacciones_iniciales()
    carpeta = workdir(AREA, CONTEXTO, preview=("disp", "bloques"))

    # ── 1. Exportar etiquetas y DB ──────────────────────────────────────
    with job.paso("exportar") as paso:
        carpeta.limpiar_sincronizar()
        exportar_tablas(
            job.tia.portal,
            plc,
            carpeta.variables_export,
            [tabla_config, tabla_tags],
            mantener_estructura=True,
        )
        exportar_bloques(
            job.tia.portal,
            plc,
            carpeta.bloques_export,
            [db],
            mantener_estructura=True,
            version_tia=job.tia.version_tia,
        )
        paso["detail"] = f"2 tablas y {db} exportados"

    # ── 2. Calcular diferencias ─────────────────────────────────────────
    with job.paso("diferencias") as paso:
        filas = almacen.entidades_de(plc)
        diff_constantes = ent_calcular_diff_constantes(
            tabla_tags,
            filas,
            _localizar_xml(carpeta.variables_export, tabla_tags),
        )
        diff_n_max = ent_calcular_diff_n_max(
            tabla_config,
            almacen.n_max_de_entidades(plc),
            _localizar_xml(carpeta.variables_export, tabla_config),
        )
        diff_comentarios = ent_calcular_diff_comentarios(
            db,
            array,
            filas,
            *ent_leer_par_sd(carpeta.bloques_export, db),
        )
        paso["detail"] = (
            f"{len(diff_constantes.agregados)} agregadas, "
            f"{len(diff_constantes.eliminados)} eliminadas, "
            f"{len(diff_comentarios.actualizados)} comentarios"
        )

    # ── 3. Preparar operaciones ─────────────────────────────────────────
    with job.paso("preparar") as paso:
        ops_n_max = ent_calcular_operaciones_n_max(tabla_config, diff_n_max)
        ops_constantes = ent_calcular_operaciones_constantes(diff_constantes)
        ops_comentarios = ent_calcular_operaciones_comentarios(filas)
        paso["detail"] = (
            f"{len(ops_n_max)} N_MAX, {len(ops_constantes)} operaciones de constantes, "
            f"{len(ops_comentarios)} comentarios"
        )

    # ── 4. Tx A: el N_MAX (en linea) ────────────────────────────────────
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
                "Actualizando el N_MAX de las entidades",
                lambda: _aplicar_n_max(job, plc, ops_n_max),
                f"{len(ops_n_max)} N_MAX",
            )
            paso["detail"] = (
                f"{transacciones['n_max']['estado']}: {len(ops_n_max)} N_MAX"
            )
            _compilacion_defensiva(job, plc, db)

    # ── 5. Esperar la consolidacion de TIA ──────────────────────────────
    with job.paso("consolidacion") as paso:
        time.sleep(PAUSA_CONSOLIDACION_S)
        paso["detail"] = f"TIA consolida ({PAUSA_CONSOLIDACION_S:g} s)"

    # ── 6. Re-exportar etiquetas y DB ───────────────────────────────────
    with job.paso("reexportar") as paso:
        if ops_n_max:
            exportar_tablas(
                job.tia.portal,
                plc,
                carpeta.variables_export,
                [tabla_config, tabla_tags],
                mantener_estructura=True,
            )
            exportar_bloques(
                job.tia.portal,
                plc,
                carpeta.bloques_export,
                [db],
                mantener_estructura=True,
                version_tia=job.tia.version_tia,
            )
        paso["detail"] = "tablas y DB releidos" if ops_n_max else "no hacia falta releer"

    # ── 7. Editar los ficheros offline ──────────────────────────────────
    with job.paso("editar") as paso:
        edicion = ent_copiar_y_editar(
            carpeta.variables_export,
            carpeta.variables_modified,
            carpeta.bloques_export,
            carpeta.bloques_modified,
            tabla_config,
            tabla_tags,
            carpeta_tia,
            db,
            array,
            ops_constantes,
            ops_comentarios,
        )
        for aviso in edicion["avisos"]:
            job.log(aviso, nivel="warning")
        paso["detail"] = (
            f"{edicion['anadidos']} constantes anadidas, "
            f"{edicion['eliminados']} eliminadas, "
            f"{edicion['comentarios']} DB con comentarios"
        )

    # ── 8. Tx B: las constantes (offline) ───────────────────────────────
    with job.paso("tx_constantes") as paso:
        if not ops_constantes:
            transacciones["constantes"]["estado"] = NO_EJECUTADA
            transacciones["constantes"]["detalle"] = "no habia constantes que aplicar"
            paso["detail"] = "sin cambios de constantes"
        else:
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

    # ── 9. Compilar los bloques ─────────────────────────────────────────
    with job.paso("compilar") as paso:
        compilacion = _compilar(job, plc, db)
        paso["detail"] = compilacion["detalle"]

    # ── 10. Tx C: los comentarios (offline, solo V21+) ──────────────────
    with job.paso("tx_comentarios") as paso:
        comentarios = _aplicar_comentarios(job, plc, carpeta, transacciones, edicion)
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

    return {
        "plc": plc,
        "operaciones": len(ops_n_max) + len(ops_constantes) + len(ops_comentarios),
        "n_max": {"actualizados": len(ops_n_max)},
        "constantes": {"operaciones": len(ops_constantes)},
        "comentarios": {"operaciones": len(ops_comentarios)},
        "transacciones": list(transacciones.values()),
        "compilacion": compilacion,
        "prevision": prevision,
    }


# ── las transacciones ───────────────────────────────────────────────────────


def _transacciones_iniciales() -> dict[str, dict[str, Any]]:
    """Las tres transacciones del sync, todas sin ejecutar."""
    return {
        "n_max": {
            "nombre": "N_MAX",
            "estado": NO_EJECUTADA,
            "detalle": "",
        },
        "constantes": {
            "nombre": "Constantes",
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
        transacciones["comentarios"]["estado"] = NO_EJECUTADA
        transacciones["comentarios"]["detalle"] = (
            "los comentarios por instancia necesitan TIA Portal V21 o superior"
        )
        return "no ejecutada: TIA Portal anterior a V21"

    if not edicion["comentarios"]:
        transacciones["comentarios"]["estado"] = NO_EJECUTADA
        transacciones["comentarios"]["detalle"] = "los comentarios ya estaban al dia"
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
            "[ent sync] La compilacion defensiva de '%s' fallo (el sync sigue): %s", db, exc
        )


def _compilar(job: Job, plc: str, db: str) -> dict[str, Any]:
    """Compila el DB de entidades, fuera de la transaccion.

    Los errores de compilacion **no** tumban el sync: el commit ya esta
    aplicado y el operario tiene que ver el error, no perder el trabajo.
    """
    try:
        resultado = compilar_bloques(job.tia.portal, plc, [db])
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
            + ". Revisa ese bloque en TIA Portal: puede haber quedado con "
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

    ``"ZC_PLC_STD > Program blocks > DB6_ENT (DB6) > Interface > Data type
    Boo is unknown."`` queda en ``"Interface > Data type Boo is unknown."``.
    """
    partes = [parte.strip() for parte in mensaje.split(" > ")]
    for indice, parte in enumerate(partes):
        if parte.endswith(")") and "(" in parte:
            resto = partes[indice + 1 :]
            return " > ".join(resto) if resto else mensaje
    return mensaje


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


