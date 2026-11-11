"""zc_suite.trabajos — los trabajos que la SPA puede lanzar.

Un trabajo es una operacion larga que se ejecuta **entera** dentro del hilo de
TIA. La funcion recibe el ``job`` y sus parametros, declara sus pasos con
``job.empezar`` y devuelve un dict de primitivos.

Las operaciones de TIA de verdad viven en ``tia_ops``: aqui solo se orquestan,
en el orden que ve el operario en el faceplate.

Ningun trabajo toca el portal fuera del hilo de TIA: lo reciben por
``job.tia.portal``.
"""
from __future__ import annotations

from typing import Any

from zc_suite.tia import Job, transaccion
from zc_suite.tia_ops import OperacionError
from zc_suite.tia_ops.bloques import (
    aplicar_cambios,
    escanear_bloques,
    escanear_tipos_de_usuario,
    leer_bloques,
)
from zc_suite.tia_ops.proyecto import info_proyecto, listar_plcs
from zc_suite.tia_ops.tablas import escanear_tablas_tags


def buscar_plcs(job: Job) -> dict[str, Any]:
    """Los PLCs del proyecto abierto y los datos del proyecto.

    Returns:
        ``{"plcs": [{"nombre", "designacion"}], "proyecto": {"nombre", "ruta"}}``.
    """
    job.empezar("Buscar PLCs", [("listar", "Listar los PLCs del proyecto")])
    with job.paso("listar") as paso:
        plcs = listar_plcs(job.tia.portal)
        proyecto = info_proyecto(job.tia.portal)
        paso["detail"] = f"{len(plcs)} PLCs"
    return {"plcs": plcs, "proyecto": proyecto}


def escanear_plc(job: Job, plc: str) -> dict[str, Any]:
    """Escanea el PLC: bloques, tablas de tags y tipos de usuario.

    Returns:
        ``{"plc", "bloques", "tablas", "tipos"}``.
    """
    job.empezar(
        f"Escanear {plc}",
        [
            ("bloques", "Escanear bloques"),
            ("tablas", "Escanear tablas de tags"),
            ("tipos", "Escanear tipos de usuario"),
        ],
    )
    with job.paso("bloques") as paso:
        bloques = escanear_bloques(job.tia.portal, plc)
        paso["detail"] = f"{len(bloques)} bloques"
    with job.paso("tablas") as paso:
        tablas = escanear_tablas_tags(job.tia.portal, plc)
        paso["detail"] = f"{len(tablas)} tablas de tags"
    with job.paso("tipos") as paso:
        tipos = escanear_tipos_de_usuario(job.tia.portal, plc)
        paso["detail"] = f"{len(tipos)} tipos de usuario"
    return {"plc": plc, "bloques": bloques, "tablas": tablas, "tipos": tipos}


def preparar_bloques(job: Job, plc: str, nombres: list[str]) -> dict[str, Any]:
    """Lee de TIA las propiedades de los bloques seleccionados.

    Returns:
        ``{"plc", "bloques"}``, con la misma forma que el escaneo.
    """
    job.empezar(
        f"Preparar {len(nombres)} bloques",
        [
            ("validar", "Validar la selección"),
            ("leer", "Leer los bloques de TIA"),
            ("combinar", "Combinar los datos"),
        ],
    )
    with job.paso("validar") as paso:
        if not nombres:
            raise OperacionError("No hay bloques seleccionados.")
        paso["detail"] = f"{len(nombres)} bloques"
    with job.paso("leer") as paso:
        leidos = leer_bloques(job.tia.portal, plc, nombres)
        paso["detail"] = f"{len(leidos)} bloques leidos"
    with job.paso("combinar") as paso:
        paso["detail"] = f"{len(leidos)} bloques listos"
    return {"plc": plc, "bloques": leidos}


def editar_bloques(
    job: Job,
    plc: str,
    cambios: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Aplica los cambios de nombre y numero de los bloques indicados.

    Todos los cambios van en **una sola transaccion**: si uno falla, se
    deshace todo el lote.

    Returns:
        ``{"plc", "aplicados"}``, con la lista de cambios aplicados.
    """
    job.empezar(
        f"Aplicar cambios en {plc}",
        [
            ("validar", "Validar los cambios"),
            ("diferencias", "Calcular las diferencias"),
            ("aplicar", "Aplicar la transacción"),
            ("verificar", "Verificar el resultado"),
        ],
    )
    with job.paso("validar") as paso:
        if not cambios:
            raise OperacionError("No hay cambios que aplicar.")
        paso["detail"] = f"{len(cambios)} bloques"
    with job.paso("diferencias") as paso:
        paso["detail"] = ", ".join(sorted(cambios))
    aplicados: list[dict[str, Any]] = []
    with job.paso("aplicar") as paso:
        with transaccion(job, "Editar bloques"):
            for nombre, propiedades in cambios.items():
                aplicados.append(
                    aplicar_cambios(job.tia.portal, plc, nombre, dict(propiedades))
                )
        paso["detail"] = f"{len(aplicados)} bloques"
    with job.paso("verificar") as paso:
        paso["detail"] = f"{len(aplicados)} bloques confirmados"
    return {"plc": plc, "aplicados": aplicados}
