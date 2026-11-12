"""El trabajo de la prevision de dispositivos: exportar y diffear, sin escribir.

Es el port de ``function_disp_generar_preview`` de ``main`` con los mismos
pasos y el mismo shape de resultado. No abre transacciones, no compila y no
importa nada en TIA: solo exporta las tablas de tags y las compara con el
Excel.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from zc_suite.areas.alimentacion.dispositivos.prevision import (
    DiffNMax,
    DiffTabla,
    disp_calcular_diff_n_max,
    disp_calcular_diff_tabla,
)
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel
from zc_suite.nucleo.tia.job import Job
from zc_suite.nucleo.tia.workdir import workdir
from zc_suite.tia_ops.exportar import exportar_tablas

logger = logging.getLogger(__name__)

#: El area y el contexto del workdir de los dispositivos.
AREA = "alimentacion"
CONTEXTO = "disp"


def workdir_dispositivos() -> Any:
    """El workdir de los dispositivos: ``preview/config`` y ``preview/disp``."""
    return workdir(AREA, CONTEXTO, preview=("config", "disp"))


def tablas_de_dispositivos(config: dict[str, Any]) -> list[tuple[str, str]]:
    """Las tablas de tags de los dispositivos.

    Returns:
        La lista de ``(tipo, tabla_de_tags)``, en el orden del ``config.json``.
    """
    tablas: list[tuple[str, str]] = []
    for tipo, entrada in config.get("Dispositivos", {}).items():
        tabla = str(entrada.get("tag_table", ""))
        if not tabla:
            continue
        tablas.append((str(tipo), tabla))
    return tablas


def _dispositivos_del_excel(
    almacen: AlmacenExcel,
    tipo: str,
    plc: str,
) -> list[dict[str, Any]]:
    """Los dispositivos de un tipo del Excel, filtrados por PLC."""
    for tabla in almacen.estado()["dispositivos"]:
        if tabla["tipo"] != tipo:
            continue
        return [fila for fila in tabla["filas"] if str(fila.get("plc_name", "")) == plc]
    return []


def _n_max_del_excel(
    almacen: AlmacenExcel,
    plc: str,
    config: dict[str, Any],
) -> dict[str, int]:
    """Los N_MAX de dispositivos del Excel del PLC elegido.

    Los N_MAX de las entidades son otra cosa (van en su propia tabla): aqui no
    entran, igual que en ``main``.

    El orden es el del catalogo de N_MAX del ``config.json``, no el de las
    columnas del Excel: las tarjetas de N_MAX se pintan en ese orden.
    """
    for fila in almacen.estado()["configuracion"]["filas"]:
        if str(fila.get("PLC", "")) != plc:
            continue
        valores: dict[str, int] = {}
        for entrada in config.get("n_max_catalog", []):
            nombre = str(entrada.get("name", "")).strip()
            if not nombre.startswith("N_MAX_DISP_"):
                continue
            valor = fila.get(nombre)
            if isinstance(valor, (int, float)):
                valores[nombre] = int(valor)
        return valores
    return {}


def disp_generar_preview(
    job: Job,
    plc: str,
    almacen: AlmacenExcel,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Exporta del PLC y calcula el diff de los dispositivos contra el Excel.

    Args:
        job: el trabajo en curso.
        plc: el PLC cuyos dispositivos se comparan.
        almacen: la cache del Excel maestro.
        config: la seccion del area en el ``config.json``.

    Returns:
        El shape que consume la SPA: ``agregados``, ``eliminados``,
        ``renombrados``, ``todos``, ``nmax`` y ``summary``.
    """
    job.empezar(
        "Prevision de dispositivos",
        [
            ("exportar", "Exportar etiquetas"),
            ("dispositivos", "Calcular diferencias de dispositivos"),
            ("n_max", "Calcular diferencias de N_MAX"),
            ("componer", "Componer respuesta"),
        ],
    )

    carpeta = workdir_dispositivos()
    carpeta.limpiar_preview()
    destino_config = carpeta.preview_de("config")
    destino_disp = carpeta.preview_de("disp")

    tablas = tablas_de_dispositivos(config)
    tabla_n_max = str(config.get("global_config_table_name", ""))

    with job.paso("exportar") as paso:
        if not tablas:
            aviso = (
                "No hay tablas de dispositivos que exportar: el catalogo del area "
                "esta vacio. Revisa el config.json en uso."
            )
            logger.warning(aviso)
            job.log(aviso, nivel="warning")
        if tabla_n_max:
            exportar_tablas(
                job.tia.portal,
                plc,
                destino_config,
                [tabla_n_max],
                mantener_estructura=False,
            )
        exportar_tablas(
            job.tia.portal,
            plc,
            destino_disp,
            [tabla for _tipo, tabla in tablas],
            mantener_estructura=False,
        )
        paso["detail"] = f"{len(tablas)} tablas exportadas"

    diffs: dict[str, DiffTabla] = {}
    with job.paso("dispositivos") as paso:
        for tipo, tabla in tablas:
            diff = disp_calcular_diff_tabla(
                tabla,
                _dispositivos_del_excel(almacen, tipo, plc),
                destino_disp / f"{tabla}.xml",
            )
            if diff.xml_ausente:
                aviso = (
                    f"La tabla '{tabla}' no existe en TIA (o no se pudo exportar): "
                    "sus dispositivos salen como altas."
                )
                logger.warning(aviso)
                job.log(aviso, nivel="warning")
            diffs[tabla] = diff
        agregados = sum(len(d.agregados) for d in diffs.values())
        eliminados = sum(len(d.eliminados) for d in diffs.values())
        renombrados = sum(len(d.renombrados) for d in diffs.values())
        paso["detail"] = (
            f"{agregados} agregados, {eliminados} eliminados, {renombrados} renombrados"
        )

    diff_n_max: DiffNMax | None = None
    with job.paso("n_max") as paso:
        diff_n_max = disp_calcular_diff_n_max(
            tabla_n_max,
            _n_max_del_excel(almacen, plc, config),
            destino_config / f"{tabla_n_max}.xml",
        )
        if diff_n_max.xml_ausente:
            aviso = (
                f"La tabla de N_MAX '{tabla_n_max}' no existe en TIA (o no se pudo "
                "exportar): todos los N_MAX salen como actualizar."
            )
            logger.warning(aviso)
            job.log(aviso, nivel="warning")
        paso["detail"] = (
            f"{diff_n_max.resumen['actualizar']} a actualizar de {diff_n_max.resumen['total']}"
        )

    with job.paso("componer") as paso:
        resultado = componer_respuesta(diffs, diff_n_max, tabla_n_max, destino_config)
        paso["detail"] = f"{resultado['summary']['total']} entradas en la vista unificada"

    return resultado


def componer_respuesta(
    diffs: dict[str, DiffTabla],
    diff_n_max: DiffNMax | None,
    tabla_n_max: str,
    destino_config: Path,
) -> dict[str, Any]:
    """Compone el shape final que consume la SPA."""
    agregados: list[dict[str, Any]] = []
    eliminados: list[dict[str, Any]] = []
    renombrados: list[dict[str, Any]] = []
    todos: list[dict[str, Any]] = []

    for tabla, diff in diffs.items():
        tipo = _tipo_de_tabla(tabla)
        for numero in diff.agregados:
            agregados.append(
                {"uid": numero, "table": tabla, "plc_tag": diff.deseado.get(numero, "")}
            )
        for numero in diff.eliminados:
            eliminados.append(
                {"uid": numero, "table": tabla, "plc_tag": diff.base.get(numero, "")}
            )
        for numero, (actual, nuevo) in diff.renombrados.items():
            renombrados.append(
                {"uid": numero, "table": tabla, "actual": actual, "nuevo": nuevo}
            )

        for numero, plc_tag in diff.base.items():
            if numero in diff.renombrados:
                estado = "renombrar"
                nuevo: str | None = diff.renombrados[numero][1]
            elif numero in diff.eliminados:
                estado = "eliminar"
                nuevo = None
            else:
                estado = "sin_cambios"
                nuevo = plc_tag
            todos.append(_fila_de_diff(tabla, tipo, numero, plc_tag, nuevo, estado))

        for numero in diff.agregados:
            todos.append(
                _fila_de_diff(
                    tabla,
                    tipo,
                    numero,
                    None,
                    diff.deseado.get(numero, ""),
                    "agregar",
                )
            )

    todos.sort(key=lambda fila: (fila["type"], fila["numero"]))

    return {
        "agregados": agregados,
        "eliminados": eliminados,
        "renombrados": renombrados,
        "todos": todos,
        "nmax": _shape_de_n_max(diff_n_max, tabla_n_max, destino_config),
        "summary": {
            "agregados": len(agregados),
            "eliminados": len(eliminados),
            "renombrados": len(renombrados),
            "sin_cambios": sum(1 for fila in todos if fila["status"] == "sin_cambios"),
            "total": len(todos),
        },
    }


def _tipo_de_tabla(tabla: str) -> str:
    """``2000_Disp_ED`` -> ``"ed"``, ``2000_Disp_M_VF`` -> ``"m_vf"``."""
    return tabla.split("_Disp_", 1)[-1].lower()


def _fila_de_diff(
    tabla: str,
    tipo: str,
    numero: str,
    actual: str | None,
    nuevo: str | None,
    estado: str,
) -> dict[str, Any]:
    """Una fila de la vista unificada del diff."""
    try:
        numero_int = int(numero)
    except (TypeError, ValueError):
        numero_int = 0
    return {
        "table": tabla,
        "type": tipo,
        "uid": numero,
        "numero": numero_int,
        "actual": actual,
        "nuevo": nuevo,
        "status": estado,
    }


def _shape_de_n_max(
    diff_n_max: DiffNMax | None,
    tabla_n_max: str,
    destino_config: Path,
) -> dict[str, Any]:
    """El bloque de los N_MAX con el shape que espera la SPA."""
    if diff_n_max is None:
        return {
            "current": {},
            "desired": {},
            "todos": [],
            "summary": {"actualizar": 0, "sin_cambios": 0, "total": 0},
            "nmax_error": None,
        }
    error = (
        f"XML de N_MAX no encontrado en TIA export: {destino_config / f'{tabla_n_max}.xml'}"
        if diff_n_max.xml_ausente
        else None
    )
    return {
        "current": diff_n_max.actual,
        "desired": diff_n_max.deseado,
        "todos": diff_n_max.todos,
        "summary": diff_n_max.resumen,
        "nmax_error": error,
    }
