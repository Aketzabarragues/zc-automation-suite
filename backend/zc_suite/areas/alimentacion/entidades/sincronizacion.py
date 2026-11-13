"""zc_suite.areas.alimentacion.entidades.sincronizacion — el calculo del sync.

Que cambios hay que meter en TIA y como se editan los ficheros en disco.

Es logica pura: no habla con el portal de TIA y no abre transacciones. El FB
que la usa es ``../funciones/entidades/sincronizar.py``.

El port de los helpers de ``main`` (``entidades_generate_preview``) con los
mismos criterios:

- La tabla de N_MAX **no** se importa en la transaccion de constantes: su
  valor se aplica en linea, en la transaccion anterior. Si se copiara a
  ``modified/``, la importacion le devolveria el valor previo y anularia el
  ya aplicado.
- Un rename de una ``PlcUserConstant`` se materializa como remove + add con
  el mismo valor: en TIA la constante se identifica por ``<Name>``.
- Los comentarios de los slots del array se aplican **siempre** desde el
  Excel ("manda el Excel"): no hay diff, una operacion por entidad con
  comentario.
"""
from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from zc_suite.areas.alimentacion.entidades.diferencias import (
    DiffEntidades,
    DiffNMax,
)
from zc_suite.simatic.ml import ModificadorConstantesUsuario
from zc_suite.simatic.sd import confirmar_comentarios_array

logger = logging.getLogger(__name__)

#: La extension de los XML de tablas de tags.
EXTENSION_XML = ".xml"

#: El tipo de array del DB de entidades: el array es de un UDT.
TIPO_ARRAY = "UDT"


# ── las operaciones que hay que aplicar ─────────────────────────────────────


def ent_calcular_operaciones_n_max(tabla: str, diff: DiffNMax) -> list[dict[str, Any]]:
    """Las operaciones de N_MAX que hay que aplicar en linea.

    Solo se proponen las constantes que **ya existen** en TIA y cuyo valor
    no coincide. Una constante que no esta en TIA no se puede cambiar: el
    cambio de valor fallaria. Es lo que hace ``main``.

    Args:
        tabla: la tabla de TIA donde viven los N_MAX.
        diff: el diff de los N_MAX.

    Returns:
        La lista de ``{"tabla", "constante", "valor"}``.
    """
    return [
        {
            "tabla": tabla,
            "constante": str(fila["name"]),
            "valor": int(fila["nuevo"]),
        }
        for fila in diff.todos
        if fila["status"] == "actualizar" and str(fila["name"]) in diff.actual
    ]


def ent_calcular_operaciones_constantes(diff: DiffEntidades) -> list[dict[str, Any]]:
    """Las operaciones sobre las constantes de usuario.

    Son las que se aplican offline sobre el XML de la tabla:

    - ``remove``  borrar la constante.
    - ``add``  anadirla con su valor y su comentario.
    - ``rename_comment``  cambiarle solo el comentario.

    El rename de una constante se traduce en un ``remove`` + un ``add`` con el
    mismo valor: en TIA la constante se identifica por su ``<Name>``, asi que
    no hay otra forma de renombrarla.

    Args:
        diff: el diff de las constantes.

    Returns:
        La lista de operaciones, en el orden en que se aplican.
    """
    operaciones: list[dict[str, Any]] = []
    for operacion in diff.operaciones:
        kind = operacion.get("kind")
        if kind == "delete":
            operaciones.append({"kind": "remove", "plc_tag": operacion["plc_tag"]})
        elif kind == "add":
            operaciones.append(
                {
                    "kind": "add",
                    "plc_tag": operacion["plc_tag"],
                    "valor": operacion["value_excel"],
                    "comment": operacion.get("comment_excel") or "",
                }
            )
        elif kind == "rename":
            operaciones.append({"kind": "remove", "plc_tag": operacion["plc_tag_tia"]})
            operaciones.append(
                {
                    "kind": "add",
                    "plc_tag": operacion["plc_tag_new"],
                    "valor": operacion["value_tia"],
                    "comment": "",
                }
            )
        elif kind == "update_comment":
            operaciones.append(
                {
                    "kind": "rename_comment",
                    "plc_tag": operacion["plc_tag"],
                    "new_comment": operacion.get("comment_excel") or "",
                }
            )
    return operaciones


def ent_calcular_operaciones_comentarios(
    entidades: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Las operaciones sobre los comentarios de los slots del array.

    Se aplican **siempre** desde el Excel ("manda el Excel"): una operacion
    por entidad con comentario no vacio, sin diff.

    Args:
        entidades: las filas del Excel de las entidades, ya filtradas por PLC.

    Returns:
        La lista de ``{"kind", "slot", "new_comment"}``.
    """
    operaciones: list[dict[str, Any]] = []
    for entidad in entidades:
        comentario = str(entidad.get("plc_comentario", "") or "")
        if not comentario:
            continue
        operaciones.append(
            {
                "kind": "update_comment",
                "slot": int(entidad.get("numero", 0) or 0),
                "new_comment": comentario,
            }
        )
    return operaciones


def ent_mapa_de_comentarios(operaciones: list[dict[str, Any]]) -> dict[int, str]:
    """El mapa ``{slot: comentario}`` que se pasa a la escritura del SD.

    Args:
        operaciones: las operaciones de comentarios.

    Returns:
        El mapa de los slots que tienen comentario.
    """
    return {
        int(operacion["slot"]): str(operacion["new_comment"])
        for operacion in operaciones
        if operacion.get("kind") == "update_comment"
    }


# ── la edicion offline ──────────────────────────────────────────────────────


def ent_copiar_y_editar(
    variables_export: Path,
    variables_modified: Path,
    bloques_export: Path,
    bloques_modified: Path,
    tabla_config: str,
    tabla_tags: str,
    carpeta_tia: str,
    db: str,
    array: str,
    operaciones_constantes: list[dict[str, Any]],
    operaciones_comentarios: list[dict[str, Any]],
) -> dict[str, Any]:
    """Copia lo exportado a ``modified/`` y edita los ficheros.

    Cuatro sub-pasos:

    1. Copia **filtrada** de ``variables/export/`` a ``variables/modified/``: se
       excluye el XML de la tabla de N_MAX, porque su valor ya se aplico en
       linea y reimportarla dejaria el PLC con el valor previo.
    2. Edicion offline del XML de la tabla de tags: altas, bajas y cambios de
       comentario.
    3. Copia simple de ``bloques/export/`` a ``bloques/modified/``.
    4. Edicion offline del par ``.s7dcl``/``.s7res`` del DB.

    Args:
        variables_export: la carpeta ``variables/export/``.
        variables_modified: la carpeta ``variables/modified/``.
        bloques_export: la carpeta ``bloques/export/``.
        bloques_modified: la carpeta ``bloques/modified/``.
        tabla_config: la tabla donde vive el N_MAX (se excluye de la copia).
        tabla_tags: la tabla de las constantes de las entidades.
        carpeta_tia: la carpeta de TIA donde viven la tabla y el DB.
        db: el nombre del DB de las entidades.
        array: el nombre del array dentro del DB.
        operaciones_constantes: las operaciones de las constantes.
        operaciones_comentarios: las operaciones de los comentarios.

    Returns:
        ``{"anadidos", "eliminados", "comentarios", "avisos"}``.
    """
    avisos: list[str] = []
    anadidos = 0
    eliminados = 0
    comentarios = 0

    # ── 1. la copia filtrada de las variables ───────────────────────────
    if variables_export.is_dir():
        shutil.copytree(
            variables_export,
            variables_modified,
            ignore=_ignorar_tabla_de_n_max(tabla_config),
            dirs_exist_ok=True,
        )
    else:
        aviso = f"No existe la exportacion de variables: {variables_export}."
        logger.warning("[ent sync] %s", aviso)
        avisos.append(aviso)

    # ── 2. la edicion offline del XML de las constantes ─────────────────
    if operaciones_constantes:
        ruta_xml = _localizar_xml(variables_modified, tabla_tags, carpeta_tia)
        if ruta_xml is None:
            aviso = (
                f"El XML de '{tabla_tags}' no esta en {variables_modified}: "
                "las constantes se omiten del sync."
            )
            logger.warning("[ent sync] %s", aviso)
            avisos.append(aviso)
        else:
            anadidos, eliminados = _editar_constantes(
                ruta_xml, tabla_tags, operaciones_constantes
            )

    # ── 3. la copia simple de los bloques ───────────────────────────────
    if bloques_export.is_dir():
        shutil.copytree(bloques_export, bloques_modified, dirs_exist_ok=True)
    else:
        aviso = f"No existe la exportacion de bloques: {bloques_export}."
        logger.warning("[ent sync] %s", aviso)
        avisos.append(aviso)

    # ── 4. la edicion offline de los comentarios del DB ─────────────────
    mapa = ent_mapa_de_comentarios(operaciones_comentarios)
    if mapa:
        base = bloques_modified / carpeta_tia if carpeta_tia else bloques_modified
        dcl = base / f"{db}.s7dcl"
        res = base / f"{db}.s7res"
        if not dcl.is_file() or not res.is_file():
            aviso = (
                f"No se encontro el bloque '{db}' en la exportacion: "
                "sus comentarios se omiten."
            )
            logger.warning("[ent sync] %s", aviso)
            avisos.append(aviso)
        else:
            resultado = confirmar_comentarios_array(
                dcl,
                res,
                array,
                mapa,
                array_type=TIPO_ARRAY,
                write_to_original=True,
            )
            if resultado.injected or resultado.updated or resultado.removed:
                comentarios = 1

    return {
        "anadidos": anadidos,
        "eliminados": eliminados,
        "comentarios": comentarios,
        "avisos": avisos,
    }


def _editar_constantes(
    ruta_xml: Path,
    tabla: str,
    operaciones: list[dict[str, Any]],
) -> tuple[int, int]:
    """Edita el XML de la tabla de constantes.

    El orden es **borrar, anadir y luego comentar**. La baja de una constante
    cuyo nombre vuelve a anadirse va primero: si no, el alta se pierde, porque
    el modificador no anade un nombre que ya existe.

    Returns:
        La tupla ``(anadidos, eliminados)``.
    """
    modificador = ModificadorConstantesUsuario(ruta_xml)
    altas = [
        {
            "plc_tag": operacion["plc_tag"],
            "valor": str(operacion["valor"]),
            "comment": str(operacion.get("comment", "")),
        }
        for operacion in operaciones
        if operacion["kind"] == "add"
    ]
    bajas = {
        str(operacion["plc_tag"])
        for operacion in operaciones
        if operacion["kind"] == "remove"
    }
    comentarios = [
        (str(operacion["plc_tag"]), str(operacion.get("new_comment", "")))
        for operacion in operaciones
        if operacion["kind"] == "rename_comment"
    ]

    nombres_altas = {alta["plc_tag"] for alta in altas}
    anadidos = 0
    eliminados = 0
    if bajas & nombres_altas:
        eliminados += modificador.eliminar_constantes_por_nombre(bajas & nombres_altas)
    if altas:
        anadidos = modificador.anadir_constantes_de_tabla(tabla, altas)
    if bajas - nombres_altas:
        eliminados += modificador.eliminar_constantes_por_nombre(bajas - nombres_altas)
    for plc_tag, comentario in comentarios:
        modificador.actualizar_comentario(plc_tag, comentario)

    if modificador.modificado():
        modificador.guardar(ruta_xml)
    return anadidos, eliminados


def _localizar_xml(base: Path, tabla: str, carpeta_tia: str) -> Path | None:
    """Localiza el XML de una tabla dentro de la copia de ``modified/``.

    Tolera los dos layouts: con la carpeta de TIA o en la raiz.
    """
    if carpeta_tia:
        directo = base / carpeta_tia / f"{tabla}{EXTENSION_XML}"
        if directo.is_file():
            return directo
    directo = base / f"{tabla}{EXTENSION_XML}"
    if directo.is_file():
        return directo
    for encontrado in sorted(base.rglob(f"{tabla}{EXTENSION_XML}")):
        return encontrado
    return None


def _ignorar_tabla_de_n_max(tabla_config: str) -> Callable[[str, list[str]], set[str]]:
    """El ``ignore`` de ``shutil.copytree`` que deja fuera la tabla de N_MAX."""

    def _ignore(_directorio: str, nombres: list[str]) -> set[str]:
        return {nombre for nombre in nombres if nombre == f"{tabla_config}{EXTENSION_XML}"}

    return _ignore
