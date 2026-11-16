"""zc_suite.areas.alimentacion.funciones.procesos.crear — aplicar la clonacion.

Es un **FB**: recibe el ``job``, declara sus pasos y se ejecuta entero dentro
del hilo de TIA.

Es el port de ``FunctionProcCrearSincronizar`` de ``main`` (10 stages)
adaptado a la forma de la rama: una funcion con ``job``, sin ``FunctionBase``.
A diferencia de la prevision (``generar_prevision_crear``), **escribe en
TIA**: clona la plantilla al workdir, la renombra, importa tablas y bloques
en una unica transaccion y compila fuera de ella.

La transaccion de import (stage 7 de ``main``) agrupa en un solo lote
atomico, en su orden:

1. ``importar_tablas`` sobre ``Nuevo/Variables PLC``.
2. una pausa de consolidacion de TIA (``TIA_CONSOLIDATION_SLEEP_S``).
3. ``importar_bloques`` sobre ``Nuevo/Bloques de programa``.

Si cualquiera de las tres falla, TIA hace rollback atomico de las tres
juntas, dejando el PLC en el mismo estado previo al apply.

ORDEN CRITICO (validado en vivo): **tablas ANTES que bloques**. Si se
invierte, los bloques que referencian una ``PlcUserConstant`` de la tabla de
tags fallan al compilar.

REGLA: ``importar_tablas`` / ``importar_bloques`` se invocan **sin
``carpeta_destino``** (omitiendo el argumento); **nunca** se pasa ``""``.
Con ``""`` TIA V21 NO hace match UPDATE de los bloques pre-existentes:
intenta CREATE y falla con *"Import failed because an object with the name
X already exists"*. Sin ese argumento, TIA escanea recursivamente y hace
match UPDATE por nombre, conservando la ruta relativa. Ver
``tia_ops.importar``.

Compilar (stage 8 de ``main``) va **fuera** de la transaccion: TIA no lo
admite dentro. Un fallo de compilacion **no** tumba el trabajo: el import ya
esta confirmado y el operario tiene que ver el error, no perder el trabajo.

El proyecto **no** se guarda.
"""
from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

from zc_suite.areas.alimentacion.config import ConfigArea
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel
from zc_suite.areas.alimentacion.funciones.procesos import (
    generar_prevision as modulo_prevision,
)
from zc_suite.areas.alimentacion.funciones.procesos.generar_prevision_crear import (
    AREA,
    CARPETA_NUEVO,
    CARPETA_PLANTILLA,
    carpeta_plantillas,
    workdir_crear,
)
from zc_suite.areas.alimentacion.procesos import CLAVE_PREVISION_CREAR
from zc_suite.areas.alimentacion.procesos.clonacion import (
    CARPETA_BLOQUES,
    proc_aplicar_clonacion,
    proc_construir_diccionarios,
)
from zc_suite.areas.alimentacion.procesos.plantillas import (
    proc_detectar_colisiones,
    proc_leer_manifest,
    proc_minimos_de_proceso,
    proc_resolver_plantilla,
    proc_validar_dependencias,
    proc_validar_minimos,
)
from zc_suite.errores import OperacionError
from zc_suite.nucleo.sesion import Sesion
from zc_suite.nucleo.tia.errores import CanceladoError
from zc_suite.nucleo.tia.job import Job
from zc_suite.nucleo.tia.transaccion import transaccion
from zc_suite.simatic.sd.cabecera import soporta_simaticsd
from zc_suite.tia_ops.bloques import escanear_bloques
from zc_suite.tia_ops.compilar import compilar_bloques
from zc_suite.tia_ops.importar import importar_bloques, importar_tablas
from zc_suite.tia_ops.tablas import escanear_tablas_tags

logger = logging.getLogger(__name__)

#: La carpeta de los bloques dentro de la exportacion de TIA.
CARPETA_VARIABLES = "Variables PLC"

#: Segundos que se espera a que TIA consolide entre el import de las tablas
#: y el de los bloques. TIA necesita consolidar internamente antes de
#: aceptar un segundo import.
TIA_CONSOLIDATION_SLEEP_S = 2.0

#: La transaccion se confirmo: TIA guardo los cambios.
CONFIRMADA = "confirmada"

#: La transaccion fallo y se revirtio: TIA no guardo nada.
REVIRTIDA = "revertida"

#: La transaccion no llego a ejecutarse.
NO_EJECUTADA = "no ejecutada"


def crear(
    job: Job,
    proc_uid: int,
    plc: str,
    dir_plantilla_nombre: str,
    almacen: AlmacenExcel,
    config: ConfigArea,
    sesion: Sesion | None = None,
    plantillas_dir: Path | None = None,
) -> dict[str, Any]:
    """Clona un proceso desde una plantilla TIA y lo importa al PLC.

    Args:
        job: el trabajo en curso.
        proc_uid: el ``uid`` del proceso nuevo (su base numerica).
        plc: el PLC destino.
        dir_plantilla_nombre: el nombre de la subcarpeta de la plantilla
            dentro de ``plantillas_dir`` (sin separadores).
        almacen: la cache del Excel maestro.
        config: el modelo del area.
        sesion: la sesion del backend. De su escaneo del PLC salen los
            bloques con los que se cruzan colisiones y dependencias, y al
            terminar se actualiza con los bloques nuevos.
        plantillas_dir: la carpeta con las plantillas. ``None`` para usar la
            ruta relativa del config.

    Returns:
        El resumen del apply: que se genero, como quedo la transaccion de
        import y la compilacion.

    Raises:
        OperacionError: si el proceso no esta en el Excel, si no hay escaneo
            fresco, si TIA no soporta SimaticSD, si hay colisiones, si faltan
            dependencias, o si falla la transaccion de import.
    """
    job.empezar(
        "Crear proceso desde plantilla",
        [
            ("validar", "Validar proceso, plantilla y TIA"),
            ("manifest", "Leer el manifiesto"),
            ("minimos", "Validar los minimos"),
            ("copiar", "Copiar la plantilla"),
            ("diccionarios", "Construir los diccionarios"),
            ("colisiones", "Detectar colisiones"),
            ("dependencias", "Validar dependencias"),
            ("generar", "Generar el proceso nuevo"),
            ("manifest_nuevo", "Escribir el manifiesto del nuevo"),
            ("importar", "Importar el proceso"),
            ("compilar", "Compilar los bloques"),
            ("escaneo", "Actualizar el escaneo"),
        ],
    )

    datos = almacen.estado()["procesos"]
    filas = modulo_prevision.filas_de(datos, "Procesos")
    proceso = modulo_prevision.fila_de_proceso(filas, proc_uid)
    codigo_nuevo = str(proceso.get("codigo", "") or "") if proceso else ""
    nombre_nuevo = str(proceso.get("nombre", "") or "") if proceso else ""

    manifest_plantilla: dict[str, Any] | None = None

    with job.paso("validar") as paso:
        if proceso is None:
            raise OperacionError(
                f"No hay un proceso con uid={proc_uid} en el Excel: el dominio "
                "'Procesos' no lo tiene."
            )
        carpeta = carpeta_plantillas(plantillas_dir, config)
        if carpeta is None:
            raise OperacionError(
                "La carpeta de plantillas no esta configurada: indica la "
                "ruta de las plantillas en la vista de crear procesos "
                "antes de aplicar."
            )
        dir_plantilla = proc_resolver_plantilla(carpeta, dir_plantilla_nombre)
        escaneo = modulo_prevision.escaneo_de(sesion, plc)
        if escaneo is None:
            raise OperacionError(
                "No hay un escaneo fresco del PLC: escanea el PLC antes de "
                "crear el proceso."
            )
        if not soporta_simaticsd(job.tia.version_tia):
            raise OperacionError(
                "Crear un proceso necesita TIA Portal V21 o superior."
            )
        paso["detail"] = f"proceso {proc_uid}, plantilla y escaneo de {plc}"

    with job.paso("manifest") as paso:
        manifest_plantilla = proc_leer_manifest(dir_plantilla)
        base_vieja = int(manifest_plantilla["base"])
        codigo_viejo = str(manifest_plantilla["codigo"]).strip()
        nombre_viejo = str(manifest_plantilla.get("nombre", "") or "")
        dependencias = [str(d).strip() for d in manifest_plantilla["dependencias"]]
        paso["detail"] = f"base={base_vieja} codigo={codigo_viejo}"

    with job.paso("minimos") as paso:
        minimos_usuario = proc_minimos_de_proceso(proceso)
        proc_validar_minimos(manifest_plantilla, minimos_usuario)
        paso["detail"] = "los N_MAX del proceso cubren los de la plantilla"

    carpeta = workdir_crear()
    dir_plantilla_copia = carpeta.carpeta(CARPETA_PLANTILLA)
    dir_nuevo = carpeta.carpeta(CARPETA_NUEVO)

    with job.paso("copiar") as paso:
        # Cada apply parte limpio: se borra la copia anterior de la plantilla.
        if dir_plantilla_copia.exists():
            shutil.rmtree(dir_plantilla_copia)
        shutil.copytree(dir_plantilla, dir_plantilla_copia)
        paso["detail"] = f"plantilla copiada a {dir_plantilla_copia}"

    with job.paso("diccionarios") as paso:
        dicc_bloques, dicc_xml = proc_construir_diccionarios(
            dir_plantilla_copia,
            base_vieja,
            proc_uid,
            codigo_viejo,
            codigo_nuevo,
            nombre_viejo,
            nombre_nuevo,
        )
        paso["detail"] = (
            f"{len(dicc_bloques)} reglas bloques + {len(dicc_xml)} reglas XML"
        )

    with job.paso("colisiones") as paso:
        colisiones, colisiones_con = proc_detectar_colisiones(
            dicc_bloques, escaneo.bloques
        )
        if colisiones:
            bloques_plc = ", ".join(sorted(colisiones_con.values()))
            raise OperacionError(
                "No se puede crear el proceso: hay colisiones con bloques "
                f"que ya existen en el PLC: {', '.join(colisiones)}. "
                f"Los bloques del PLC implicados: {bloques_plc}. "
                "Resuelve las colisiones antes de aplicar."
            )
        paso["detail"] = f"{len(colisiones)} colision(es)"

    with job.paso("dependencias") as paso:
        dependencias_faltantes = list(
            proc_validar_dependencias(dependencias, escaneo.bloques)
        )
        if dependencias_faltantes:
            raise OperacionError(
                "No se puede crear el proceso: faltan dependencias que la "
                "plantilla declara y que no existen en el PLC: "
                f"{', '.join(dependencias_faltantes)}. "
                "Importa esos bloques en el PLC antes de crear el proceso."
            )
        paso["detail"] = f"{len(dependencias)} dependencias OK"

    with job.paso("generar") as paso:
        # El proceso nuevo se materializa copiando la plantilla al workdir
        # ``Nuevo`` (sin el ``manifest.json``) y renombrando con los
        # diccionarios. Si ya hay un ``Nuevo`` de un apply anterior, se
        # borra para partir limpio.
        if dir_nuevo.exists():
            shutil.rmtree(dir_nuevo)
        shutil.copytree(dir_plantilla_copia, dir_nuevo)
        # El manifest.json de la plantilla no viaja al proceso nuevo: el del
        # nuevo se escribe en el paso siguiente con los datos del proceso
        # nuevo.
        (dir_nuevo / "manifest.json").unlink(missing_ok=True)
        archivos_generados = proc_aplicar_clonacion(
            dir_nuevo,
            dicc_bloques,
            dicc_xml,
            base_nueva=proc_uid,
            minimos_usuario=minimos_usuario,
        )
        paso["detail"] = f"{len(archivos_generados)} archivos generados"

    with job.paso("manifest_nuevo") as paso:
        # El manifest.json del proceso nuevo: la plantilla como base, con
        # override de base/codigo/nombre/minimos del proceso nuevo.
        manifest_path = dir_nuevo / "manifest.json"
        payload = {
            "base": proc_uid,
            "codigo": codigo_nuevo,
            "nombre": nombre_nuevo,
            "descripcion": str(manifest_plantilla.get("descripcion", "") or "").strip(),
            "dependencias": list(dependencias),
            "minimos": dict(minimos_usuario),
        }
        manifest_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        archivos_generados.append("manifest.json")
        paso["detail"] = "manifest del proceso nuevo escrito"

    transacciones = _transacciones_iniciales()

    with job.paso("importar") as paso:
        _transaccion_importar(
            job,
            transacciones,
            plc,
            dir_nuevo,
        )
        paso["detail"] = (
            f"{transacciones['importar']['estado']}: tablas y bloques "
            "del proceso nuevo"
        )

    with job.paso("compilar") as paso:
        compilacion = _compilar(job, plc, archivos_generados)
        paso["detail"] = compilacion["detalle"]

    escaneo_actualizado = False
    with job.paso("escaneo") as paso:
        if sesion is None:
            paso["detail"] = "sin sesion: el escaneo no se actualiza"
        else:
            # La prevision de crear ya no vale: el proceso existe. Se borra
            # aqui (y no al final) para que un fallo del refresco del
            # escaneo no la deje en la sesion.
            sesion.borrar_dato_area(AREA, CLAVE_PREVISION_CREAR)
            # El import ya esta confirmado en TIA: un fallo aqui solo deja el
            # escaneo viejo, no tumba el trabajo.
            try:
                bloques = escanear_bloques(job.tia.portal, plc)
                tablas = escanear_tablas_tags(job.tia.portal, plc)
                sesion.actualizar_bloques(plc, bloques)
                sesion.actualizar_tablas(plc, tablas)
                escaneo_actualizado = True
                paso["detail"] = (
                    f"{len(bloques)} bloques y {len(tablas)} tablas en el "
                    "escaneo"
                )
            except Exception as exc:  # no tumba el apply: ver el comentario
                logger.warning(
                    "El proceso se creo pero no se pudo refrescar el "
                    "escaneo: %s. Vuelve a escanear el PLC.",
                    exc,
                )
                job.log(
                    f"El proceso se creo pero no se pudo refrescar el "
                    f"escaneo: {exc}. Vuelve a escanear el PLC.",
                    nivel="warning",
                )
                paso["detail"] = "no se pudo refrescar"

    process_label = f"{proc_uid}_{codigo_nuevo}"
    logger.info(
        "Proceso %s creado en '%s': %d archivos generados.",
        process_label,
        plc,
        len(archivos_generados),
    )
    return {
        "plc": plc,
        "proc_uid": proc_uid,
        "process_label": process_label,
        "archivos_generados": archivos_generados,
        "colisiones": [],
        "transacciones": list(transacciones.values()),
        "compilacion": compilacion,
        "escaneo_actualizado": escaneo_actualizado,
        "success": True,
    }


# ── los helpers privados del FB ─────────────────────────────────────────────


def _transacciones_iniciales() -> dict[str, dict[str, Any]]:
    """Las transacciones del apply, todas sin ejecutar."""
    return {
        "importar": {
            "nombre": "Importar proceso",
            "estado": NO_EJECUTADA,
            "detalle": "",
        },
    }


def _transaccion_importar(
    job: Job,
    transacciones: dict[str, dict[str, Any]],
    plc: str,
    dir_nuevo: Path,
) -> None:
    """Importa tablas y bloques del proceso nuevo en una transaccion unica.

    ORDEN CRITICO (validado en vivo): **tablas ANTES que bloques**. Si se
    invierte, los bloques que referencian una ``PlcUserConstant`` de la
    tabla de tags fallan al compilar.

    REGLA: ni ``importar_tablas`` ni ``importar_bloques`` reciben
    ``carpeta_destino`` (se omite el argumento); **nunca** se pasa ``""``.
    Ver el docstring del modulo.

    Raises:
        CanceladoError: si el trabajo fue cancelado (no es un fallo).
        OperacionError: si el import falla, con el estado de las
            transacciones anadido al mensaje.
    """
    try:
        with transaccion(job, f"Importar proceso {plc}"):
            # 1. Las tablas de tags, primero.
            importar_tablas(
                job.tia.portal,
                plc,
                dir_nuevo / CARPETA_VARIABLES,
            )
            # 2. Pausa de consolidacion de TIA.
            time.sleep(TIA_CONSOLIDATION_SLEEP_S)
            # 3. Los bloques de programa, despues.
            importar_bloques(
                job.tia.portal,
                plc,
                dir_nuevo / CARPETA_BLOQUES,
            )
    except CanceladoError:
        # La cancelacion del operario no es un fallo: sale tal cual para que
        # el trabajo termine como cancelado y no como error.
        transacciones["importar"]["estado"] = REVIRTIDA
        transacciones["importar"]["detalle"] = "el trabajo fue cancelado"
        raise
    except Exception as exc:
        transacciones["importar"]["estado"] = REVIRTIDA
        transacciones["importar"]["detalle"] = str(exc)
        raise OperacionError(
            f"Importar proceso: revertida. {exc}. "
            f"{_resumen_de_transacciones(transacciones)}"
        ) from exc
    transacciones["importar"]["estado"] = CONFIRMADA
    transacciones["importar"]["detalle"] = "tablas y bloques del proceso nuevo"


def _resumen_de_transacciones(transacciones: dict[str, dict[str, Any]]) -> str:
    """El estado de las transacciones, en una frase."""
    partes = [
        f"{datos['nombre']}: {datos['estado']}" for datos in transacciones.values()
    ]
    return "Transacciones: " + "; ".join(partes) + "."


def _compilar(job: Job, plc: str, archivos_generados: list[str]) -> dict[str, Any]:
    """Compila los bloques del proceso nuevo, fuera de la transaccion.

    Los errores de compilacion **no** tumban el apply: el import ya esta
    confirmado y el operario tiene que ver el error, no perder el trabajo.
    """
    # Los nombres de los bloques a compilar: los stems de los ficheros
    # ``.s7dcl`` de la carpeta de bloques (cada bloque TIA vive en un par
    # ``.s7dcl``/``.s7res`` de mismo stem).
    nombres: list[str] = []
    for archivo in archivos_generados:
        ruta = Path(archivo)
        if ruta.suffix == ".s7dcl":
            nombres.append(ruta.stem)
    if not nombres:
        return {"ok": True, "error": None, "detalle": "compile=no-op"}
    try:
        resultado = compilar_bloques(job.tia.portal, plc, nombres)
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
            + ". Revisa los bloques en TIA Portal."
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
