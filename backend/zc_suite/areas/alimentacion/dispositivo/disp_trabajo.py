"""El trabajo de la prevision de dispositivos: exportar y diffear, sin escribir.

Es el port de ``function_disp_generar_preview`` de ``main`` con los mismos
pasos y el mismo shape de resultado. No abre transacciones, no compila y no
importa nada en TIA: solo exporta y compara.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from zc_suite.areas.alimentacion.dispositivo.disp_preview import (
    DiffNMax,
    DiffTabla,
    disp_calcular_diff_n_max,
    disp_calcular_diff_tabla,
)
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel
from zc_suite.simatic.cabecera import soporta_simaticsd
from zc_suite.simatic.simatic_sd import comentarios_actuales
from zc_suite.tia import Job
from zc_suite.tia_ops import OperacionError
from zc_suite.tia_ops.exportar import exportar_bloques, exportar_tablas
from zc_suite.workdir import workdir

logger = logging.getLogger(__name__)

#: El area y el contexto del workdir de los dispositivos.
AREA = "alimentacion"
CONTEXTO = "disp"


def workdir_dispositivos() -> Any:
    """El workdir de los dispositivos: ``preview/config`` y ``preview/disp``."""
    return workdir(AREA, CONTEXTO, preview=("config", "disp"))


def tablas_de_dispositivos(config: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Las tablas de tags de los dispositivos.

    Returns:
        La lista de ``(tipo, tabla_de_tags, nombre_del_db)``.
    """
    tablas: list[tuple[str, str, str]] = []
    for tipo, entrada in config.get("Dispositivos", {}).items():
        tabla = str(entrada.get("tag_table", ""))
        if not tabla:
            continue
        tablas.append((str(tipo), tabla, str(entrada.get("db_name", ""))))
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
        return [
            fila
            for fila in tabla["filas"]
            if str(fila.get("plc_name", "")) == plc
        ]
    return []


def _n_max_del_excel(almacen: AlmacenExcel, plc: str) -> dict[str, int]:
    """Los N_MAX del Excel del PLC elegido."""
    for fila in almacen.estado()["configuracion"]["filas"]:
        if str(fila.get("PLC", "")) != plc:
            continue
        return {
            nombre: int(valor)
            for nombre, valor in fila.items()
            if nombre.startswith("N_MAX_") and isinstance(valor, (int, float))
        }
    return {}


def _comentarios_de_tia(
    job: Job,
    plc: str,
    destino: Path,
    config: dict[str, Any],
    tipos: list[tuple[str, str, str]],
    almacen: AlmacenExcel,
) -> dict[str, dict[str, str]]:
    """Los comentarios que hay en TIA, por tipo y numero.

    Los comentarios viven en el bloque del DB y solo se pueden leer con la
    exportacion en SimaticSD, que solo existe en TIA V21. En V18 se salta con
    un aviso: la prevision sigue, pero sin el comentario de TIA.
    """
    if not soporta_simaticsd(job.tia.version_tia):
        aviso = (
            "Los comentarios de TIA no se pueden leer en esta version de TIA "
            "(hacen falta SimaticSD, que es de V21). Se sigue sin ellos."
        )
        logger.warning(aviso)
        job.log(aviso, nivel="aviso")
        return {}

    nombres = [db for _tipo, _tabla, db in tipos if db]
    if not nombres:
        return {}
    try:
        exportar_bloques(
            job.tia.portal,
            plc,
            destino,
            nombres,
            mantener_estructura=False,
            version_tia=job.tia.version_tia,
        )
    except OperacionError as exc:
        logger.warning("No se pudieron exportar los bloques para los comentarios: %s", exc)
        return {}

    comentarios: dict[str, dict[str, str]] = {}
    for tipo, _tabla, db in tipos:
        if not db:
            continue
        base = destino / db
        dcl = Path(f"{base}.s7dcl")
        res = Path(f"{base}.s7res")
        if not dcl.is_file() or not res.is_file():
            continue
        array = str(config.get("Dispositivos", {}).get(tipo, {}).get("db_array_name", ""))
        if not array:
            continue
        indices = [
            int(fila.get("numero", 0) or 0)
            for fila in _dispositivos_del_excel(almacen, tipo, plc)
        ]
        if not indices:
            continue
        try:
            leidos = comentarios_actuales(
                res.read_text(encoding="utf-8-sig"),
                array,
                indices,
                dcl_text=dcl.read_text(encoding="utf-8-sig"),
                array_type="UDT",
            )
        except Exception as exc:
            logger.warning("No se pudieron leer los comentarios de '%s': %s", db, exc)
            continue
        comentarios[tipo] = {
            str(indice): texto for indice, texto in leidos.items() if texto
        }
    return comentarios


def disp_generar_preview(
    job: Job,
    plc: str,
    almacen: AlmacenExcel,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Exporta del PLC y calcula el diff de los dispositivos contra el Excel.

    Args:
        job: el trabajo en curso.
        plc: el PLC whose dispositivos se comparan.
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
    destino_comentarios = destino_disp / "comentarios"

    tipos = tablas_de_dispositivos(config)
    tabla_n_max = str(config.get("global_config_table_name", ""))

    with job.paso("exportar") as paso:
        if tabla_n_max:
            exportar_tablas(
                job.tia.portal,
                plc,
                destino_config,
                [tabla_n_max],
                mantener_estructura=False,
            )
        nombres_tablas = [tabla for _tipo, tabla, _db in tipos]
        if nombres_tablas:
            exportar_tablas(
                job.tia.portal,
                plc,
                destino_disp,
                nombres_tablas,
                mantener_estructura=False,
            )
        comentarios = _comentarios_de_tia(
            job, plc, destino_comentarios, config, tipos, almacen
        )
        paso["detail"] = f"{len(nombres_tablas)} tablas exportadas"

    diffs: dict[str, DiffTabla] = {}
    with job.paso("dispositivos") as paso:
        for tipo, tabla, _db in tipos:
            diffs[tabla] = disp_calcular_diff_tabla(
                tabla,
                _dispositivos_del_excel(almacen, tipo, plc),
                destino_disp / f"{tabla}.xml",
            )
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
            _n_max_del_excel(almacen, plc),
            destino_config / f"{tabla_n_max}.xml",
        )
        paso["detail"] = (
            f"{diff_n_max.resumen['actualizar']} a actualizar de {diff_n_max.resumen['total']}"
        )

    with job.paso("componer") as paso:
        resultado = componer_respuesta(diffs, diff_n_max, comentarios)
        paso["detail"] = f"{resultado['summary']['total']} entradas en la vista unificada"

    return resultado


def _tipo_de_tabla(tabla: str) -> str:
    """``2000_Disp_ED`` -> ``"ed"``, ``2000_Disp_M_VF`` -> ``"m_vf"``."""
    return tabla.split("_Disp_", 1)[-1].lower()


def componer_respuesta(
    diffs: dict[str, DiffTabla],
    diff_n_max: DiffNMax | None,
    comentarios: dict[str, dict[str, str]],
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
            todos.append(
                _fila_de_diff(tabla, tipo, numero, plc_tag, nuevo, estado, comentarios)
            )

        for numero in diff.agregados:
            todos.append(
                _fila_de_diff(
                    tabla,
                    tipo,
                    numero,
                    None,
                    diff.deseado.get(numero, ""),
                    "agregar",
                    comentarios,
                )
            )

    todos.sort(key=lambda fila: (fila["type"], fila["numero"]))

    return {
        "agregados": agregados,
        "eliminados": eliminados,
        "renombrados": renombrados,
        "todos": todos,
        "nmax": _shape_de_n_max(diff_n_max),
        "summary": {
            "agregar": len(agregados),
            "eliminar": len(eliminados),
            "renombrados": len(renombrados),
            "sin_cambios": sum(1 for fila in todos if fila["status"] == "sin_cambios"),
            "total": len(todos),
        },
    }


def _fila_de_diff(
    tabla: str,
    tipo: str,
    numero: str,
    actual: str | None,
    nuevo: str | None,
    estado: str,
    comentarios: dict[str, dict[str, str]],
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
        "comentario_actual": comentarios.get(tipo, {}).get(numero, ""),
    }


def _shape_de_n_max(diff_n_max: DiffNMax | None) -> dict[str, Any]:
    """El bloque de los N_MAX con el shape que espera la SPA."""
    if diff_n_max is None:
        return {
            "current": {},
            "desired": {},
            "todos": [],
            "summary": {"actualizar": 0, "sin_cambios": 0, "total": 0},
        }
    return {
        "current": diff_n_max.actual,
        "desired": diff_n_max.deseado,
        "todos": diff_n_max.todos,
        "summary": diff_n_max.resumen,
    }
