"""zc_suite.areas.alimentacion.entidades.diferencias — el diff de entidades.

Lo que hay en TIA frente a lo que dice el Excel: las constantes de usuario de
la tabla de entidades y los comentarios de los slots del array del DB.

Es logica pura: no habla con el portal de TIA y no abre transacciones. El FB
que la usa es ``../funciones/entidades/generar_prevision.py``.

El port de ``main`` (``helpers/entidades/entidades_generate_preview.py``) con
los mismos criterios:

- Una entidad se identifica por su ``plc_tag`` (el ``<Name>`` de la
  ``PlcUserConstant``). Su numero es el ``<Value>`` y el slot del array.
- El ``plc_tag`` canonico es ``ENT_<X>`` en mayusculas, con ``X`` el numero de
  la entidad. TIA exporta ``ENT_000``, ``ENT_001``...
- Los slots que hay en TIA y no en el Excel **no** se eliminan: se preservan.
- Los comentarios de los slots se aplican **siempre** desde el Excel ("manda
  el Excel"), sin diff.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zc_suite.areas.alimentacion.dispositivos.diferencias import (
    DiffNMax,
    disp_calcular_diff_n_max,
)
from zc_suite.simatic.ml import ModificadorConstantesUsuario
from zc_suite.simatic.sd import comentarios_actuales, indices_de_array

logger = logging.getLogger(__name__)

#: El tipo de array del DB de entidades: el array es de un UDT.
TIPO_ARRAY = "UDT"


@dataclass(frozen=True)
class DiffEntidades:
    """El diff de las constantes de usuario de la tabla de entidades.

    Attributes:
        tabla: nombre de la tabla de TIA (``"6_Entidades"``).
        base: ``{plc_tag: numero}`` de TIA.
        deseado: ``{plc_tag: numero}`` del Excel.
        agregados: ``plc_tag`` del Excel que no estan en TIA.
        eliminados: ``plc_tag`` de TIA que no estan en el Excel.
        renombrados: ``{plc_tag: (numero_de_TIA, numero_del_Excel)}``.
        comentarios_base: ``{plc_tag: comentario}`` leido del XML de TIA.
        xml_ausente: ``True`` si el XML de TIA no existia.
        operaciones: la lista de operaciones a aplicar, en orden.
    """

    tabla: str
    base: dict[str, int]
    deseado: dict[str, int]
    agregados: list[str]
    eliminados: list[str]
    renombrados: dict[str, tuple[int, int]]
    comentarios_base: dict[str, str | None] = field(default_factory=dict)
    xml_ausente: bool = False
    operaciones: list[dict[str, Any]] = field(default_factory=list)

    @property
    def vacio(self) -> bool:
        """``True`` si no hay ningun cambio."""
        return not (self.agregados or self.eliminados or self.renombrados)


@dataclass(frozen=True)
class DiffComentarios:
    """El diff de los comentarios de los slots del array de entidades.

    Attributes:
        db: nombre del DB (``"DB6_ENT"``).
        array: nombre del array (``"ENT"``).
        slots_tia: los slots que existen en TIA.
        actuales: ``{slot: comentario_de_TIA}``.
        deseados: ``{slot: comentario_del_Excel}``.
        agregados: slots del Excel que no estan en TIA.
        eliminados: siempre vacio: los slots de TIA se preservan.
        actualizados: slots con comentario distinto.
        sin_cambios: slots con el mismo comentario.
        xml_ausente: ``True`` si el par ``.s7dcl``/``.s7res`` no existia.
    """

    db: str
    array: str
    slots_tia: set[int]
    actuales: dict[int, str | None]
    deseados: dict[int, str | None]
    agregados: list[int]
    eliminados: list[int]
    actualizados: list[int]
    sin_cambios: list[int]
    xml_ausente: bool = False

    @property
    def total_cambios(self) -> int:
        """Los comentarios que hay que aplicar (agregados + actualizados)."""
        return len(self.agregados) + len(self.actualizados)


# ── la lectura del XML de TIA ───────────────────────────────────────────────


def _leer_constantes_del_xml(ruta_xml: Path) -> tuple[dict[str, int], dict[str, str | None]]:
    """Lee el XML de la tabla de entidades y devuelve ``(base, comentarios)``.

    La tabla solo contiene ``PlcUserConstant`` de entidades: el ``<Name>`` es
    el ``plc_tag`` del Excel y el ``<Value>`` es su numero.

    Si el XML no existe o no se puede parsear, devuelve ``({}, {})``.
    """
    if not ruta_xml.is_file():
        return {}, {}
    try:
        modificador = ModificadorConstantesUsuario(ruta_xml)
        crudo = dict(modificador.leer_constantes_con_comentarios())
    except Exception as exc:
        logger.warning(
            "[diff ent] No se pudo cargar el XML de entidades '%s': %s", ruta_xml.name, exc
        )
        return {}, {}

    base: dict[str, int] = {}
    comentarios: dict[str, str | None] = {}
    for valor, datos in crudo.items():
        plc_tag = str(datos.get("name", "")).strip()
        if not plc_tag:
            continue
        try:
            numero = int(str(valor).strip())
        except (TypeError, ValueError):
            continue
        base[plc_tag] = numero
        comentarios[plc_tag] = datos.get("comment")
    return base, comentarios


# ── el diff de las constantes ───────────────────────────────────────────────


def ent_calcular_diff_constantes(
    tabla: str,
    entidades: list[dict[str, Any]],
    ruta_xml: Path,
) -> DiffEntidades:
    """Calcula el diff entre las entidades del Excel y el XML de TIA.

    Deteccion en dos pasos:

    1. **Renombres por valor**: un ``plc_tag`` de TIA cuyo valor coincide con
       el de otro ``plc_tag`` del Excel es un rename: TIA conserva el valor y
       el sync cambia el ``<Name>``.
    2. **Delete / add / update_comment** sobre lo que queda: un ``plc_tag``
       solo en TIA se elimina; uno con el mismo nombre y distinto valor se
       elimina y se anade; uno con el mismo nombre y mismo valor pero otro
       comentario solo cambia el comentario.

    Args:
        tabla: nombre de la tabla de TIA (``"6_Entidades"``).
        entidades: las filas del Excel de las entidades, ya filtradas por PLC.
        ruta_xml: ruta al XML plano exportado de TIA.

    Returns:
        El ``DiffEntidades`` con la lista de ``operaciones``.
    """
    deseado: dict[str, int] = {}
    comentarios_deseados: dict[str, str | None] = {}
    for entidad in entidades:
        plc_tag = str(entidad.get("plc_tag", "") or "").strip()
        numero = int(entidad.get("numero", 0) or 0)
        comentario = str(entidad.get("plc_comentario", "") or "") or None
        if plc_tag and numero >= 0:
            deseado[plc_tag] = numero
            comentarios_deseados[plc_tag] = comentario

    base, comentarios_base = _leer_constantes_del_xml(ruta_xml)
    xml_ausente = not ruta_xml.is_file()

    claves_base = set(base)
    claves_deseadas = set(deseado)
    claves_comunes = claves_base & claves_deseadas

    # ── 1. los renombres por valor ──────────────────────────────────────
    deseados_por_valor: dict[int, list[str]] = {}
    for plc_tag, valor in deseado.items():
        deseados_por_valor.setdefault(valor, []).append(plc_tag)

    renombres: list[tuple[str, int, str]] = []
    usados: set[str] = set()
    for plc_tag_tia in sorted(base):
        valor = base[plc_tag_tia]
        candidatos = [
            etiqueta
            for etiqueta in deseados_por_valor.get(valor, [])
            if etiqueta != plc_tag_tia and etiqueta not in usados
        ]
        if not candidatos:
            continue
        if plc_tag_tia in claves_comunes and base[plc_tag_tia] == deseado.get(plc_tag_tia):
            continue
        plc_tag_nuevo = sorted(candidatos)[0]
        renombres.append((plc_tag_tia, valor, plc_tag_nuevo))
        usados.add(plc_tag_nuevo)

    renombrados_tia = {renombre[0] for renombre in renombres}
    renombrados_excel = {renombre[2] for renombre in renombres}

    agregados = sorted(claves_deseadas - claves_base - renombrados_excel)
    eliminados = sorted(claves_base - claves_deseadas - renombrados_tia)
    renombrados: dict[str, tuple[int, int]] = {
        plc_tag: (base[plc_tag], deseado[plc_tag])
        for plc_tag in claves_comunes
        if base[plc_tag] != deseado[plc_tag]
    }

    # ── 2. las operaciones, en el orden en que las aplica el sync ───────
    operaciones_eliminar = [
        {"kind": "delete", "plc_tag": plc_tag, "value_tia": base[plc_tag]}
        for plc_tag in eliminados
    ]

    operaciones_renombrar = [
        {
            "kind": "rename",
            "plc_tag_tia": plc_tag_tia,
            "value_tia": valor,
            "plc_tag_new": plc_tag_nuevo,
        }
        for plc_tag_tia, valor, plc_tag_nuevo in renombres
    ]

    operaciones_eliminar_y_anadir: list[dict[str, Any]] = []
    for plc_tag in sorted(claves_comunes):
        if base[plc_tag] == deseado[plc_tag]:
            continue
        if plc_tag in renombrados_tia:
            continue
        operaciones_eliminar_y_anadir.append(
            {"kind": "delete", "plc_tag": plc_tag, "value_tia": base[plc_tag]}
        )
        operaciones_eliminar_y_anadir.append(
            {
                "kind": "add",
                "plc_tag": plc_tag,
                "value_excel": deseado[plc_tag],
                "comment_excel": comentarios_deseados[plc_tag],
            }
        )

    operaciones_anadir = [
        {
            "kind": "add",
            "plc_tag": plc_tag,
            "value_excel": deseado[plc_tag],
            "comment_excel": comentarios_deseados[plc_tag],
        }
        for plc_tag in agregados
        if plc_tag not in renombrados_excel
    ]

    operaciones_comentario: list[dict[str, Any]] = []
    for plc_tag in sorted(claves_comunes):
        if base[plc_tag] != deseado[plc_tag]:
            continue
        if plc_tag in renombrados_tia:
            continue
        actual = (comentarios_base.get(plc_tag) or "").strip()
        nuevo = (comentarios_deseados.get(plc_tag) or "").strip()
        if actual == nuevo:
            continue
        operaciones_comentario.append(
            {
                "kind": "update_comment",
                "plc_tag": plc_tag,
                "value_tia": base[plc_tag],
                "comment_tia": comentarios_base.get(plc_tag),
                "comment_excel": comentarios_deseados[plc_tag],
            }
        )

    # Cada rename trae tambien el comentario del Excel: asi el primer sync
    # lo aplica sin esperar al segundo.
    for _plc_tag_tia, valor, plc_tag_nuevo in renombres:
        comentario_excel = comentarios_deseados.get(plc_tag_nuevo)
        if comentarios_base.get(plc_tag_nuevo) == comentario_excel:
            continue
        operaciones_comentario.append(
            {
                "kind": "update_comment",
                "plc_tag": plc_tag_nuevo,
                "value_tia": valor,
                "comment_tia": comentarios_base.get(plc_tag_nuevo),
                "comment_excel": comentario_excel,
            }
        )

    operaciones_sin_cambios: list[dict[str, Any]] = []
    for plc_tag in sorted(claves_comunes):
        if plc_tag in renombrados_tia:
            continue
        if base[plc_tag] != deseado[plc_tag]:
            continue
        actual = (comentarios_base.get(plc_tag) or "").strip()
        nuevo = (comentarios_deseados.get(plc_tag) or "").strip()
        if actual != nuevo:
            continue
        operaciones_sin_cambios.append(
            {"kind": "sin_cambios", "plc_tag": plc_tag, "value_tia": base[plc_tag]}
        )

    return DiffEntidades(
        tabla=tabla,
        base=base,
        deseado=deseado,
        agregados=agregados,
        eliminados=eliminados,
        renombrados=renombrados,
        comentarios_base=comentarios_base,
        xml_ausente=xml_ausente,
        operaciones=(
            operaciones_eliminar
            + operaciones_renombrar
            + operaciones_eliminar_y_anadir
            + operaciones_anadir
            + operaciones_comentario
            + operaciones_sin_cambios
        ),
    )


# ── el diff de los comentarios ──────────────────────────────────────────────


def ent_calcular_diff_comentarios(
    db: str,
    array: str,
    entidades: list[dict[str, Any]],
    texto_dcl: str,
    texto_res: str,
) -> DiffComentarios:
    """Calcula el diff de comentarios de los slots del array de entidades.

    Los slots del Excel que no estan en TIA se anaden; los que estan en TIA y
    no en el Excel **se preservan** (no se eliminan).

    Args:
        db: nombre del DB (``"DB6_ENT"``).
        array: nombre del array (``"ENT"``).
        entidades: las filas del Excel de las entidades, ya filtradas por PLC.
        texto_dcl: contenido del ``.s7dcl``.
        texto_res: contenido del ``.s7res``.

    Returns:
        El ``DiffComentarios`` con los cuatro vectores.
    """
    slots_tia = indices_de_array(texto_dcl, array, array_type=TIPO_ARRAY)
    actuales = comentarios_actuales(
        res_text=texto_res,
        array_name=array,
        indices=sorted(slots_tia),
        dcl_text=texto_dcl,
        array_type=TIPO_ARRAY,
    )

    deseados: dict[int, str | None] = {}
    for entidad in entidades:
        numero = int(entidad.get("numero", 0) or 0)
        comentario = str(entidad.get("plc_comentario", "") or "")
        deseados[numero] = comentario or None

    agregados = sorted(set(deseados) - slots_tia)
    eliminados: list[int] = []
    actualizados: list[int] = []
    sin_cambios: list[int] = []

    for slot in sorted(slots_tia & set(deseados)):
        actual = (actuales.get(slot) or "").strip()
        nuevo = (deseados.get(slot) or "").strip()
        if actual == nuevo:
            sin_cambios.append(slot)
        else:
            actualizados.append(slot)

    return DiffComentarios(
        db=db,
        array=array,
        slots_tia=set(slots_tia),
        actuales=actuales,
        deseados=deseados,
        agregados=agregados,
        eliminados=eliminados,
        actualizados=actualizados,
        sin_cambios=sin_cambios,
        xml_ausente=not (texto_dcl and texto_res),
    )


# ── el diff del N_MAX ───────────────────────────────────────────────────────


def ent_calcular_diff_n_max(
    tabla: str,
    n_max_deseado: dict[str, int],
    ruta_xml: Path,
) -> DiffNMax:
    """El diff del N_MAX de las entidades.

    La constante ``N_MAX_ENTIDAD`` vive en la tabla de configuracion y tiene
    la misma semantica que el resto de N_MAX.

    Args:
        tabla: nombre de la tabla (``"0_Config_Generales"``).
        n_max_deseado: ``{"N_MAX_ENTIDAD": valor}`` del Excel.
        ruta_xml: ruta al XML plano de TIA.

    Returns:
        El ``DiffNMax`` con ``actual``, ``deseado``, ``todos`` y ``resumen``.
    """
    return disp_calcular_diff_n_max(tabla, n_max_deseado, ruta_xml)


# ── los avisos y el resumen ─────────────────────────────────────────────────


def ent_detectar_inconsistencias(diff: DiffEntidades) -> list[str]:
    """Detecta constantes de TIA cuyo ``plc_tag`` no es el canonico.

    La regla canonica es ``plc_tag = ENT_<X>`` con ``X`` el numero. Una
    constante de TIA que no la cumpla y que se solape con una entidad del
    Excel es un error del operario: el sync no puede decidir por si solo.

    Args:
        diff: el diff de las constantes.

    Returns:
        Los avisos, uno por inconsistencia. Vacio si no hay ninguna.
    """
    avisos: list[str] = []
    for plc_tag, numero in diff.base.items():
        canonico = f"ENT_{numero:03d}"
        if plc_tag == canonico:
            continue
        etiqueta_excel = next(
            (etiqueta for etiqueta, valor in diff.deseado.items() if valor == numero),
            None,
        )
        if etiqueta_excel is None:
            continue
        avisos.append(
            f"TIA tiene PlcUserConstant '{plc_tag}' con value={numero}, "
            f"pero el Excel tiene '{etiqueta_excel}' con el mismo numero. "
            "La regla canonica es plc_tag = ENT_<X> con X = numero. "
            "Quita una o renombra."
        )
    return avisos


def ent_resumen(
    diff_constantes: DiffEntidades,
    diff_comentarios: DiffComentarios,
) -> dict[str, int]:
    """El resumen agregado de la prevision de entidades.

    Returns:
        ``{"constants_agregados", "constants_eliminados",
        "constants_renombrados", "constants_sin_cambios", "comments_added",
        "comments_updated", "comments_unchanged", "total"}``.
    """
    sin_cambios = sum(
        1
        for plc_tag in (diff_constantes.base.keys() & diff_constantes.deseado.keys())
        if plc_tag not in diff_constantes.renombrados
        and plc_tag not in diff_constantes.agregados
        and plc_tag not in diff_constantes.eliminados
    )
    agregados = len(diff_constantes.agregados)
    eliminados = len(diff_constantes.eliminados)
    renombrados = len(diff_constantes.renombrados)
    comentarios_agregados = len(diff_comentarios.agregados)
    comentarios_actualizados = len(diff_comentarios.actualizados)
    comentarios_sin_cambios = len(diff_comentarios.sin_cambios)

    return {
        "constants_agregados": agregados,
        "constants_eliminados": eliminados,
        "constants_renombrados": renombrados,
        "constants_sin_cambios": sin_cambios,
        "comments_added": comentarios_agregados,
        "comments_updated": comentarios_actualizados,
        "comments_unchanged": comentarios_sin_cambios,
        "total": (
            agregados
            + eliminados
            + renombrados
            + comentarios_agregados
            + comentarios_actualizados
        ),
    }
