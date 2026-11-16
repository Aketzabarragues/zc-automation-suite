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
from zc_suite.areas.alimentacion.sincronizacion_comun import (
    datos_compilacion,
    estado_confirmada,
    estado_revertida,
    estados_iniciales,
    resumen_transacciones,
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

#: El nombre de la unica transaccion del apply: el nombre que se ve en el
#: faceplate y en el mensaje de fallo.
NOMBRE_TX_IMPORTAR = "Importar proceso"

#: La cola final del aviso de una compilacion con errores del crear.
#: Plural (``bloques``): se compilan todos los bloques del proceso nuevo.
COLA_COMPILACION = " Revisa los bloques en TIA Portal."

#: Los pasos del apply, declarados al inicio del trabajo.
PASOS = (
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
)


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
        dir_plantilla_nombre: la subcarpeta de la plantilla en
            ``plantillas_dir`` (sin separadores).
        almacen: la cache del Excel maestro.
        config: el modelo del area.
        sesion: la sesion del backend; de su escaneo salen los bloques con
            los que se cruzan colisiones y dependencias.
        plantillas_dir: la carpeta de plantillas; ``None`` usa la del config.

    Returns:
        El resumen del apply: que se genero, como quedo la transaccion de
        import y la compilacion.

    Raises:
        OperacionError: si el proceso no esta en el Excel, si no hay escaneo
            fresco, si TIA no soporta SimaticSD, si hay colisiones, si faltan
            dependencias, o si falla la transaccion de import.
    """
    job.empezar("Crear proceso desde plantilla", list(PASOS))
    # 1. Validar el proceso, la plantilla, el escaneo y la version de TIA.
    proceso, carpeta, escaneo, codigo_nuevo, nombre_nuevo = _validar(
        job, proc_uid, plc, almacen, config, sesion, plantillas_dir,
    )
    # 2. Leer el manifiesto de la plantilla.
    (
        manifest_plantilla,
        base_vieja,
        codigo_viejo,
        nombre_viejo,
        dependencias,
        dir_plantilla,
    ) = _leer_manifest(job, carpeta, dir_plantilla_nombre)
    # 3. Validar los minimos del operario contra los de la plantilla.
    minimos_usuario = _validar_minimos(job, manifest_plantilla, proceso)
    # 4. Copiar la plantilla al workdir.
    dir_plantilla_copia = _copiar_plantilla(job, dir_plantilla)
    # 5. Construir los diccionarios de la clonacion.
    dicc_bloques, dicc_xml = _construir_diccionarios(
        job, dir_plantilla_copia, base_vieja, proc_uid,
        codigo_viejo, codigo_nuevo, nombre_viejo, nombre_nuevo,
    )
    # 6. Detectar colisiones con el escaneo del PLC.
    _validar_colisiones(job, dicc_bloques, escaneo)
    # 7. Validar las dependencias declaradas de la plantilla.
    _validar_dependencias(job, dependencias, escaneo)
    # 8. Generar el proceso nuevo en el workdir.
    archivos_generados = _generar_proceso(
        job, dir_plantilla_copia, dicc_bloques, dicc_xml, proc_uid,
        minimos_usuario,
    )
    # 9. Escribir el manifiesto del proceso nuevo.
    _escribir_manifest(
        job, manifest_plantilla, proc_uid, codigo_nuevo, nombre_nuevo,
        dependencias, minimos_usuario, archivos_generados,
    )
    # 10. Importar tablas y bloques en una transaccion unica.
    transacciones = estados_iniciales({"importar": NOMBRE_TX_IMPORTAR})
    _importar(job, transacciones, plc)
    # 11. Compilar los bloques, fuera de la transaccion.
    compilacion = _compilar(job, plc, archivos_generados)
    # 12. Actualizar el escaneo de la sesion.
    escaneo_actualizado = _actualizar_escaneo(job, sesion, plc)
    return _armar_resultado(
        plc, proc_uid, codigo_nuevo, archivos_generados,
        transacciones, compilacion, escaneo_actualizado,
    )


# ── los pasos del apply, en helpers privados ───────────────────────────────


def _armar_resultado(
    plc: str,
    proc_uid: int,
    codigo_nuevo: str,
    archivos_generados: list[str],
    transacciones: dict[str, dict[str, str]],
    compilacion: dict[str, Any],
    escaneo_actualizado: bool,
) -> dict[str, Any]:
    """El resumen observable del apply: generado, transacciones y compilacion."""
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


def _validar(
    job: Job,
    proc_uid: int,
    plc: str,
    almacen: AlmacenExcel,
    config: ConfigArea,
    sesion: Sesion | None,
    plantillas_dir: Path | None,
) -> tuple[dict[str, Any], Any, Any, str, str]:
    """El proceso del Excel, la carpeta de plantillas, el escaneo fresco y
    la version de TIA, con sus errores esperados.
    """
    datos = almacen.estado()["procesos"]
    filas = modulo_prevision.filas_de(datos, "Procesos")
    proceso = modulo_prevision.fila_de_proceso(filas, proc_uid)
    codigo_nuevo = str(proceso.get("codigo", "") or "") if proceso else ""
    nombre_nuevo = str(proceso.get("nombre", "") or "") if proceso else ""
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
    return proceso, carpeta, escaneo, codigo_nuevo, nombre_nuevo


def _leer_manifest(
    job: Job,
    carpeta: Path,
    dir_plantilla_nombre: str,
) -> tuple[dict[str, Any], int, str, str, list[str], Path]:
    """El manifiesto de la plantilla, su carpeta y los campos que la
    clonacion renombra."""
    with job.paso("manifest") as paso:
        dir_plantilla = proc_resolver_plantilla(carpeta, dir_plantilla_nombre)
        manifest = proc_leer_manifest(dir_plantilla)
        base_vieja = int(manifest["base"])
        codigo_viejo = str(manifest["codigo"]).strip()
        nombre_viejo = str(manifest.get("nombre", "") or "")
        dependencias = [str(d).strip() for d in manifest["dependencias"]]
        paso["detail"] = f"base={base_vieja} codigo={codigo_viejo}"
    return (
        manifest,
        base_vieja,
        codigo_viejo,
        nombre_viejo,
        dependencias,
        dir_plantilla,
    )


def _validar_minimos(
    job: Job,
    manifest_plantilla: dict[str, Any],
    proceso: dict[str, Any],
) -> dict[str, int]:
    """Los N_MAX del proceso cubren los de la plantilla."""
    minimos_usuario = proc_minimos_de_proceso(proceso)
    with job.paso("minimos") as paso:
        proc_validar_minimos(manifest_plantilla, minimos_usuario)
        paso["detail"] = "los N_MAX del proceso cubren los de la plantilla"
    return minimos_usuario


def _copiar_plantilla(job: Job, dir_plantilla: Path) -> Path:
    """Copia la plantilla al workdir, partiendo limpio de cada apply."""
    workdir = workdir_crear()
    dir_copia = workdir.carpeta(CARPETA_PLANTILLA)
    with job.paso("copiar") as paso:
        # Cada apply parte limpio: se borra la copia anterior de la plantilla.
        if dir_copia.exists():
            shutil.rmtree(dir_copia)
        shutil.copytree(dir_plantilla, dir_copia)
        paso["detail"] = f"plantilla copiada a {dir_copia}"
    return dir_copia


def _construir_diccionarios(
    job: Job,
    dir_plantilla_copia: Path,
    base_vieja: int,
    proc_uid: int,
    codigo_viejo: str,
    codigo_nuevo: str,
    nombre_viejo: str,
    nombre_nuevo: str,
) -> tuple[dict[str, str], dict[str, str]]:
    """Los diccionarios de bloques y de XML de la clonacion."""
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
    return dicc_bloques, dicc_xml


def _validar_colisiones(job: Job, dicc_bloques: dict[str, str], escaneo: Any) -> None:
    """Los nombres post-rename no pueden existir ya en el PLC."""
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


def _validar_dependencias(job: Job, dependencias: list[str], escaneo: Any) -> None:
    """Las dependencias declaradas de la plantilla existen en el PLC."""
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


def _generar_proceso(
    job: Job,
    dir_plantilla_copia: Path,
    dicc_bloques: dict[str, str],
    dicc_xml: dict[str, str],
    proc_uid: int,
    minimos_usuario: dict[str, int],
) -> list[str]:
    """Materializa el proceso nuevo en el workdir ``Nuevo`` y lo renombra."""
    workdir = workdir_crear()
    dir_nuevo = workdir.carpeta(CARPETA_NUEVO)
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
    return archivos_generados


def _escribir_manifest(
    job: Job,
    manifest_plantilla: dict[str, Any],
    proc_uid: int,
    codigo_nuevo: str,
    nombre_nuevo: str,
    dependencias: list[str],
    minimos_usuario: dict[str, int],
    archivos_generados: list[str],
) -> None:
    """El manifest.json del proceso nuevo, con los datos del proceso."""
    with job.paso("manifest_nuevo") as paso:
        # El manifest.json del proceso nuevo: la plantilla como base, con
        # override de base/codigo/nombre/minimos del proceso nuevo.
        workdir = workdir_crear()
        manifest_path = workdir.carpeta(CARPETA_NUEVO) / "manifest.json"
        payload = {
            "base": proc_uid,
            "codigo": codigo_nuevo,
            "nombre": nombre_nuevo,
            "descripcion": str(
                manifest_plantilla.get("descripcion", "") or ""
            ).strip(),
            "dependencias": list(dependencias),
            "minimos": dict(minimos_usuario),
        }
        manifest_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        archivos_generados.append("manifest.json")
        paso["detail"] = "manifest del proceso nuevo escrito"


def _importar(
    job: Job,
    transacciones: dict[str, dict[str, str]],
    plc: str,
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
    workdir = workdir_crear()
    dir_nuevo = workdir.carpeta(CARPETA_NUEVO)
    with job.paso("importar") as paso:
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
            # La cancelacion del operario no es un fallo: sale tal cual para
            # que el trabajo termine como cancelado y no como error.
            estado_revertida(transacciones, "importar", "el trabajo fue cancelado")
            raise
        except Exception as exc:
            estado_revertida(transacciones, "importar", str(exc))
            raise OperacionError(
                f"Importar proceso: revertida. {exc}. "
                f"{resumen_transacciones(transacciones)}"
            ) from exc
        estado_confirmada(
            transacciones,
            "importar",
            "tablas y bloques del proceso nuevo",
        )
        paso["detail"] = (
            f"{transacciones['importar']['estado']}: tablas y bloques "
            "del proceso nuevo"
        )


def _compilar(job: Job, plc: str, archivos_generados: list[str]) -> dict[str, Any]:
    """Compila los bloques del proceso nuevo, fuera de la transaccion.

    Los errores de compilacion **no** tumban el apply: el import ya esta
    confirmado y el operario tiene que ver el error, no perder el trabajo.
    Devuelve el shape observable ``{ok, error, detalle}`` que lee la SPA.
    """
    # Los nombres de los bloques a compilar: los stems de los ficheros
    # ``.s7dcl`` de la carpeta de bloques (cada bloque TIA vive en un par
    # ``.s7dcl``/``.s7res`` de mismo stem).
    nombres = [
        Path(archivo).stem
        for archivo in archivos_generados
        if Path(archivo).suffix == ".s7dcl"
    ]
    if not nombres:
        return {"ok": True, "error": None, "detalle": "compile=no-op"}
    with job.paso("compilar") as paso:
        # El callable invoca la ``compilar_bloques`` del modulo (los tests
        # la parchean ahi), como en los demas FB de sync.
        compilacion = datos_compilacion(
            compilador=lambda: compilar_bloques(job.tia.portal, plc, nombres),
            cola=COLA_COMPILACION,
            logger=logger,
        )
        paso["detail"] = compilacion["detalle"]
    return compilacion


def _actualizar_escaneo(
    job: Job,
    sesion: Sesion | None,
    plc: str,
) -> bool:
    """Refresca el escaneo de la sesion con los bloques importados.

    Un fallo aqui **no** tumba el apply: el import ya esta confirmado en
    TIA y solo deja el escaneo viejo.
    """
    if sesion is None:
        with job.paso("escaneo") as paso:
            paso["detail"] = "sin sesion: el escaneo no se actualiza"
        return False
    # La prevision de crear ya no vale: el proceso existe. Se borra aqui (y
    # no al final) para que un fallo del refresco del escaneo no la deje en
    # la sesion.
    sesion.borrar_dato_area(AREA, CLAVE_PREVISION_CREAR)
    with job.paso("escaneo") as paso:
        try:
            bloques = escanear_bloques(job.tia.portal, plc)
            tablas = escanear_tablas_tags(job.tia.portal, plc)
            sesion.actualizar_bloques(plc, bloques)
            sesion.actualizar_tablas(plc, tablas)
            paso["detail"] = (
                f"{len(bloques)} bloques y {len(tablas)} tablas en el "
                "escaneo"
            )
            return True
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
            return False
