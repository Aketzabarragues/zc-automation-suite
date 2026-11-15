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

Los fallos **esperados** del pipeline (sin escaneo, manifest invalido, N_MAX
del operario por debajo de los minimos de la plantilla) no son fallos del
trabajo: se capturan y devuelven con ``precondiciones_ok`` ``False`` y el
mensaje accionable en ``colisiones``/``missing_blocks`` (el hint de la SPA).
Solo lo inesperado sube con traceback.

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
    proc_validar_dependencias,
    proc_validar_minimos,
)
from zc_suite.errores import OperacionError, ZCError
from zc_suite.nucleo.sesion import Sesion
from zc_suite.nucleo.tia.job import Job
from zc_suite.nucleo.tia.workdir import workdir

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


def _carpeta_plantillas(
    plantillas_dir: Path | None,
    config: ConfigArea,
) -> Path:
    """La carpeta con las plantillas.

    Si el llamador pasa ``plantillas_dir`` (los tests y el router), se usa.
    Si no, se usa la ruta relativa ``config.plantillas_procesos`` del config
    (la app no tiene hoy un resolver publico de la carpeta de datos; el paso
    del router la resuelve contra los datos de la app).
    """
    if plantillas_dir is not None:
        return plantillas_dir
    return Path(config.plantillas_procesos)


def _minimos_de_proceso(proceso: dict[str, Any]) -> dict[str, int]:
    """Los 4 N_MAX del proceso del Excel, con el nombre de la constante.

    El Excel lleva las columnas ``preal``, ``pint``, ``alarmas`` y
    ``alm_hmi``; el manifest los declara como ``N_MAX_PREAL``,
    ``N_MAX_PINT``, ``N_MAX_ALM`` y ``N_MAX_ALM_HMI``.
    """
    return {
        "N_MAX_PREAL": int(proceso.get("preal", 0) or 0),
        "N_MAX_PINT": int(proceso.get("pint", 0) or 0),
        "N_MAX_ALM": int(proceso.get("alarmas", 0) or 0),
        "N_MAX_ALM_HMI": int(proceso.get("alm_hmi", 0) or 0),
    }


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
        "missing_blocks": list(colisiones),
        "warnings": warnings,
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
    warnings: list[str] = []

    with job.paso("validar") as paso:
        if proceso is None:
            raise OperacionError(
                f"No hay un proceso con uid={proc_uid} en el Excel: el dominio "
                "'Procesos' no lo tiene."
            )
        if not dir_plantilla_nombre:
            raise OperacionError(
                "El nombre de la carpeta de la plantilla es obligatorio."
            )
        if (
            "/" in dir_plantilla_nombre
            or "\\" in dir_plantilla_nombre
            or ".." in dir_plantilla_nombre
        ):
            raise OperacionError(
                "El nombre de la carpeta de la plantilla no puede contener "
                f"separadores ni '..': {dir_plantilla_nombre!r}."
            )
        plantillas_dir = _carpeta_plantillas(plantillas_dir, config)
        if not plantillas_dir.is_dir():
            raise OperacionError(
                f"No se encontro la carpeta de plantillas: {plantillas_dir}."
            )
        dir_plantilla = plantillas_dir / dir_plantilla_nombre
        if not dir_plantilla.is_dir():
            raise OperacionError(
                f"No se encontro la plantilla: {dir_plantilla}. "
                "Verifica la carpeta de plantillas y el nombre de la subcarpeta."
            )
        escaneo = modulo_prevision.escaneo_de(sesion, plc)
        if escaneo is None:
            # Como main y como la 4.5: sin escaneo fresco no se copia ni se
            # lee nada de la plantilla; el hint va en ``colisiones`` (como el
            # de main, de forma que ``success`` sale False) y la SPA lo muestra.
            resultado = _respuesta(
                None, [], [HINT_SIN_ESCANEO], {}, [], [], ""
            )
            if sesion is not None:
                sesion.guardar_dato_area(
                    AREA,
                    CLAVE_PREVISION_CREAR,
                    {"plc": plc, "proc_uid": proc_uid, "resultado": resultado},
                )
            paso["detail"] = "sin escaneo fresco"
            return resultado
        paso["detail"] = f"proceso {proc_uid} y escaneo de {plc}"

    with job.paso("manifest") as paso:
        try:
            manifest_plantilla = proc_leer_manifest(dir_plantilla)
        except ZCError as exc:
            # Fallo esperado: el preview no aborta, devuelve el mensaje.
            logger.warning("manifest: %s", exc)
            resultado = _respuesta(
                None, [], [str(exc)], {}, [], [], "", warnings
            )
            return _guardar_y_devolver(
                sesion, plc, proc_uid, resultado, str(exc)
            )
        base_vieja = int(manifest_plantilla["base"])
        codigo_viejo = str(manifest_plantilla["codigo"]).strip()
        nombre_viejo = str(manifest_plantilla.get("nombre", "") or "")
        dependencias = [str(d).strip() for d in manifest_plantilla["dependencias"]]
        paso["detail"] = f"base={base_vieja} codigo={codigo_viejo}"

    with job.paso("minimos") as paso:
        minimos_usuario = _minimos_de_proceso(proceso)
        try:
            proc_validar_minimos(manifest_plantilla, minimos_usuario)
        except ZCError as exc:
            # Fallo esperado: el preview no aborta, devuelve el mensaje.
            logger.warning("minimos: %s", exc)
            resultado = _respuesta(
                manifest_plantilla, [], [str(exc)], {}, [], [], "", warnings
            )
            return _guardar_y_devolver(
                sesion, plc, proc_uid, resultado, str(exc)
            )
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

    dependencias_faltantes = list(
        proc_validar_dependencias(dependencias, escaneo.bloques)
    )
    with job.paso("dependencias") as paso:
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
            warnings,
        )
        paso["detail"] = (
            f"{len(archivos_previstos)} archivos previstos, "
            f"{len(colisiones)} colision(es)"
        )

    if sesion is not None:
        sesion.guardar_dato_area(
            AREA,
            CLAVE_PREVISION_CREAR,
            {"plc": plc, "proc_uid": proc_uid, "resultado": resultado},
        )
    return resultado


def _guardar_y_devolver(
    sesion: Sesion | None,
    plc: str,
    proc_uid: int,
    resultado: dict[str, Any],
    error: str,
) -> dict[str, Any]:
    """Guarda en la sesion y devuelve la respuesta con el fallo esperado.

    El fallo no es del trabajo (``estado`` ``ok``): va como
    ``precondiciones_ok`` ``False`` con el mensaje en ``missing_blocks``.
    """
    resultado["missing_blocks"] = [error]
    if sesion is not None:
        sesion.guardar_dato_area(
            AREA,
            CLAVE_PREVISION_CREAR,
            {"plc": plc, "proc_uid": proc_uid, "resultado": resultado},
        )
    return resultado
