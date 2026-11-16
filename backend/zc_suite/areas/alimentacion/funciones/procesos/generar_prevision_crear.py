"""zc_suite.areas.alimentacion.funciones.procesos.generar_prevision_crear —
la prevision de crear un proceso desde una plantilla.

Es un **FB**: recibe el ``job``, declara sus pasos y se ejecuta entero dentro
del hilo de TIA.

Es el port de ``FunctionProcCrearGenerarPreview`` de ``main`` (8 steps)
adaptado a la forma de la rama: una funcion con ``job``, sin ``FunctionBase``.
No abre transacciones, no compila y **no importa nada en TIA**: solo lee el
``manifest.json`` de la plantilla, la copia al workdir de preview, construye
los diccionarios de la clonacion y los cruza con el escaneo del PLC. El
resultado dice que bloques se crearian (``archivos_previstos``), que
colisionan con el PLC (``colisiones``) y que dependencias externas faltan
(``dependencias_faltantes``).

Los fallos **esperados** del pipeline suben como excepciones del trabajo, como
en ``main``: un manifest invalido o unos N_MAX del operario por debajo de los
minimos de la plantilla abortan la prevision (el paso queda en error). La unica
excepcion es la falta de escaneo fresco: no es un fallo (el trabajo termina en
``ok`` con ``precondiciones_ok`` ``False`` y el hint en ``missing_blocks``),
como la prevision de la 4.5.

El workdir del flujo es ``.build_cache/alimentacion/procesos_crear`` con dos
carpetas propias: ``Plantilla`` (la copia de la plantilla que se renombra) y
``Nuevo`` (el proceso generado por el apply; la prevision solo lo declara).
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from zc_suite.areas.alimentacion.config import ConfigArea
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel
from zc_suite.areas.alimentacion.funciones.procesos import (
    generar_prevision as modulo_prevision,
)
from zc_suite.areas.alimentacion.procesos import CLAVE_PREVISION_CREAR
from zc_suite.areas.alimentacion.procesos.clonacion import (
    proc_construir_diccionarios,
)
from zc_suite.areas.alimentacion.procesos.plantillas import (
    proc_detectar_colisiones,
    proc_generar_previstos,
    proc_leer_manifest,
    proc_minimos_de_proceso,
    proc_resolver_plantilla,
    proc_validar_dependencias,
    proc_validar_minimos,
)
from zc_suite.errores import OperacionError
from zc_suite.nucleo.sesion import Sesion
from zc_suite.nucleo.tia.job import Job
from zc_suite.nucleo.tia.workdir import raiz_datos, workdir

logger = logging.getLogger(__name__)

#: El area y el contexto del workdir del flujo de crear procesos.
AREA = "alimentacion"
CONTEXTO = "procesos_crear"

#: La carpeta de la plantilla dentro del workdir (la que se renombra).
CARPETA_PLANTILLA = "Plantilla"

#: La carpeta del proceso generado, dentro del workdir (la usa el apply).
CARPETA_NUEVO = "Nuevo"

#: El hint de la SPA cuando no hay escaneo fresco del PLC.
HINT_SIN_ESCANEO = (
    "Cache de bloques del PLC no disponible. "
    "Selecciona el PLC en el sidebar y espera al "
    "escaneo de bloques (1-3 min en PLCs grandes)."
)


def workdir_crear() -> Any:
    """El workdir del flujo de crear procesos: ``Plantilla`` y ``Nuevo``."""
    return workdir(AREA, CONTEXTO, carpetas=(CARPETA_PLANTILLA, CARPETA_NUEVO))


def carpeta_plantillas(
    plantillas_dir: Path | None,
    config: ConfigArea,
) -> Path | None:
    """La carpeta con las plantillas, o ``None`` si no esta configurada.

    Si el llamador pasa ``plantillas_dir`` (los tests y el router), se usa
    tal cual. Si no, ``config.plantillas_procesos``: la cadena vacia es
    "sin configurar" y **no** se resuelve contra la carpeta de datos (no
    puede dar ``raiz_datos()``); una ruta relativa se resuelve contra
    ``raiz_datos`` (empaquetado: la carpeta del ``.exe``; desarrollo: el
    repo) y una absoluta se respeta como esta.

    Returns:
        La carpeta de plantillas, o ``None`` si ``config.plantillas_procesos``
        esta vacia.
    """
    if plantillas_dir is not None:
        return plantillas_dir
    valor = config.plantillas_procesos
    if not valor:
        return None
    return raiz_datos() / valor


def _respuesta(
    manifest_plantilla: dict[str, Any] | None,
    archivos_previstos: list[dict[str, str]],
    colisiones: list[str],
    colisiones_con: dict[str, str],
    dependencias_ok: list[str],
    dependencias_faltantes: list[str],
    plantilla_copia_dir: str,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """El shape que consume la SPA (las claves de ``proc_process_done_summary``
    de ``main``), con ``precondiciones_ok`` y ``missing_blocks`` añadidos.

    ``success`` replica a ``main``: ``True`` solo si no hay colisiones. Las
    dependencias faltantes no lo rompen (se muestran como aviso);
    ``precondiciones_ok`` las cuenta, para que el apply no se lance sin ellas.
    Una colision no es un bloque ausente: ``missing_blocks`` siempre sale
    vacio por aqui.
    """
    warnings = list(warnings or [])
    success = len(colisiones) == 0
    precondiciones_ok = success and len(dependencias_faltantes) == 0
    if not success:
        warnings.append("Hay colisiones: revisa antes de aplicar.")
    for bloque in dependencias_faltantes:
        warnings.append(f"Dependencia ausente en el PLC: {bloque}.")
    return {
        "manifest_plantilla": manifest_plantilla,
        "descripcion": (
            str(manifest_plantilla.get("descripcion", "")).strip()
            if manifest_plantilla
            else ""
        ),
        "dependencias_ok": list(dependencias_ok),
        "dependencias_faltantes": list(dependencias_faltantes),
        "archivos_previstos": archivos_previstos,
        "colisiones": list(colisiones),
        "colisiones_con": dict(colisiones_con),
        "plantilla_copia_dir": str(plantilla_copia_dir),
        "success": success,
        "precondiciones_ok": precondiciones_ok,
        "missing_blocks": [],
        "warnings": warnings,
    }


def _respuesta_sin_escaneo() -> dict[str, Any]:
    """La respuesta cuando no hay escaneo fresco del PLC.

    Como ``main`` y como la 4.5: sin la cache de bloques del PLC no se puede
    comprobar la presencia de nada, asi que no se copia ni se lee nada de la
    plantilla; ``precondiciones_ok`` sale False y el hint va en
    ``missing_blocks`` (``colisiones`` queda vacia).
    """
    return {
        "manifest_plantilla": None,
        "descripcion": "",
        "dependencias_ok": [],
        "dependencias_faltantes": [],
        "archivos_previstos": [],
        "colisiones": [],
        "colisiones_con": {},
        "plantilla_copia_dir": "",
        "success": False,
        "precondiciones_ok": False,
        "missing_blocks": [HINT_SIN_ESCANEO],
        "warnings": [],
    }


def generar_prevision_crear(
    job: Job,
    proc_uid: int,
    plc: str,
    dir_plantilla_nombre: str,
    almacen: AlmacenExcel,
    config: ConfigArea,
    sesion: Sesion | None = None,
    plantillas_dir: Path | None = None,
) -> dict[str, Any]:
    """Genera el preview de crear un proceso desde una plantilla TIA.

    No escribe en TIA: el preview solo copia la plantilla al workdir, la
    renombra en memoria y la cruza con el escaneo del PLC.

    Args:
        job: el trabajo en curso.
        proc_uid: el ``uid`` del proceso nuevo (su base numerica).
        plc: el PLC destino, cuyo escaneo se cruza.
        dir_plantilla_nombre: el nombre de la subcarpeta de la plantilla
            dentro de ``plantillas_dir`` (sin separadores).
        almacen: la cache del Excel maestro.
        config: el modelo del area.
        sesion: la sesion del backend. La prevision se guarda en ella para
            que sobreviva a un F5, y de su escaneo del PLC salen los bloques
            con los que se cruzan colisiones y dependencias.
        plantillas_dir: la carpeta con las plantillas. ``None`` para usar la
            ruta relativa del config.

    Returns:
        El shape que consume la SPA: ``manifest_plantilla``, ``descripcion``,
        ``dependencias_ok``, ``dependencias_faltantes``,
        ``archivos_previstos``, ``colisiones``, ``colisiones_con``,
        ``plantilla_copia_dir``, ``success``, ``precondiciones_ok``,
        ``missing_blocks`` y ``warnings``.

    Raises:
        OperacionError: si el proceso no esta en el Excel, si el nombre de la
            plantilla no vale (path traversal) o si falta la carpeta de
            plantillas.
    """
    job.empezar(
        "Crear proceso desde plantilla",
        [
            ("validar", "Validar proceso y escaneo"),
            ("manifest", "Leer el manifiesto"),
            ("minimos", "Validar los minimos"),
            ("copiar", "Copiar la plantilla"),
            ("diccionarios", "Construir los diccionarios"),
            ("colisiones", "Detectar colisiones"),
            ("dependencias", "Validar dependencias"),
            ("previstos", "Generar los previstos"),
            ("respuesta", "Componer la respuesta"),
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
                "antes de lanzar la prevision."
            )
        dir_plantilla = proc_resolver_plantilla(carpeta, dir_plantilla_nombre)
        escaneo = modulo_prevision.escaneo_de(sesion, plc)
        if escaneo is None:
            # Como main y como la 4.5: sin escaneo fresco no se copia ni se
            # lee nada de la plantilla. No es un fallo del trabajo: el hint va
            # en ``missing_blocks`` y la SPA lo muestra.
            resultado = _respuesta_sin_escaneo()
            if sesion is not None:
                sesion.guardar_dato_area(
                    AREA,
                    CLAVE_PREVISION_CREAR,
                    {
                        "plc": plc,
                        "proc_uid": proc_uid,
                        "dir_plantilla_nombre": dir_plantilla_nombre,
                        "resultado": resultado,
                    },
                )
            paso["detail"] = "sin escaneo fresco"
            return resultado
        paso["detail"] = f"proceso {proc_uid} y escaneo de {plc}"

    # Manifest invalido o minimos insuficientes: como en ``main``, son fallos
    # del trabajo. ``proc_leer_manifest`` y ``proc_validar_minimos`` lanzan
    # (``ManifestInvalidoError`` / ``PlantillaMinimosNoCumplidosError``, que
    # cuelgan de ``ZCError``) y el paso queda en error.
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

    with job.paso("copiar") as paso:
        # Regla de retencion de main: cada preview parte limpio.
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
        paso["detail"] = f"{len(colisiones)} colision(es)"

    with job.paso("dependencias") as paso:
        dependencias_faltantes = list(
            proc_validar_dependencias(dependencias, escaneo.bloques)
        )
        dependencias_ok = [
            d for d in dependencias if d not in dependencias_faltantes
        ]
        paso["detail"] = (
            f"{len(dependencias_ok)} OK, {len(dependencias_faltantes)} faltantes"
        )

    with job.paso("previstos") as paso:
        archivos_previstos = proc_generar_previstos(
            dir_plantilla_copia,
            dicc_bloques,
            colisiones,
            colisiones_con,
        )
        paso["detail"] = f"{len(archivos_previstos)} bloques"

    with job.paso("respuesta") as paso:
        resultado = _respuesta(
            manifest_plantilla,
            archivos_previstos,
            colisiones,
            colisiones_con,
            dependencias_ok,
            dependencias_faltantes,
            dir_plantilla_copia,
        )
        paso["detail"] = (
            f"{len(archivos_previstos)} archivos previstos, "
            f"{len(colisiones)} colision(es)"
        )

    if sesion is not None:
        sesion.guardar_dato_area(
            AREA,
            CLAVE_PREVISION_CREAR,
            {
                "plc": plc,
                "proc_uid": proc_uid,
                "dir_plantilla_nombre": dir_plantilla_nombre,
                "resultado": resultado,
            },
        )
    return resultado
