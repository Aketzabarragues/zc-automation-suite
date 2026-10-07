"""Funciones puras de diff entre desired (Excel) y base (TIA) para ENTIDADES.

El feature ENTIDADES sincroniza 1 sola coleccion multi-PLC contra TIA. Aqui
hay 4 lados del diff, todos filtrados por el PLC activo:

  1. **N_MAX_ENTIDAD** (1 PlcUserConstant en ``0_Config_Generales``).
     Re-uso de ``compute_nmax_diff`` del helper de dispositivos
     (``areas/alimentacion/helpers/disp/disp_generate_preview.py``).

  2. **Constantes PlcUserConstant** en ``6_Entidades`` (tabla de tags).
     Diff por ``plc_tag`` (string canonico ``ENT_<X>``), value = ``numero``.

  3. **Comentarios ``DB6_ENT.ENT[i]``** (array UDT).
     Diff por ``slot`` (i). Re-uso de ``find_array_slots`` +
     ``read_current_comments`` del helper de SimaticSD.

  4. **Diff unificado** (C.18): cruza (2) + (3) en una sola lista
     indexada por ``numero`` (regla canonica del feature: el plc_tag es
     ``ENT_<X>`` con value=X, donde X coincide con el slot del array
     ``ENT[]``). Es lo que consume la SPA.

Convenciones del feature:
  - El ``plc_tag`` canonico es ``ENT_<X>`` en MAYUSCULAS, donde ``X`` es
    el ordinal del Excel (regla confirmada por el operario, oct-2026).
    Pre-C.10 se asumia prefijo ``ent_`` (minusculas); eso cambio tras
    ver el XML real de TIA que exporta ``ENT_000``, ``ENT_001``, etc.
  - El ``numero`` del Excel coincide con el value de la PlcUserConstant
    TIA y con el slot del array. Si en algun PLC no se cumple la regla,
    es error del operario.

Restricciones arquitectonicas:
  - Sin estado mutable, sin dataclasses mutables, sin I/O fuera de la
    lectura del XML/.s7dcl/.s7res ya en disco.
  - Sin ``siemens_tia_scripting``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from areas.alimentacion.helpers.disp.disp_generate_preview import (
    compute_nmax_diff,
)
from core.helpers.simatic_sd.simatic_sd_db_array_comment_updater import (
    find_array_slots,
    read_current_comments,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol (no ata al area; cualquier objeto con estos atributos sirve)
# ---------------------------------------------------------------------------


class EntidadLike(Protocol):
    """Contrato minimo de una entidad del Excel."""

    numero: int
    plc_tag: str
    plc_comentario: str


# ---------------------------------------------------------------------------
# Dataclass de salida: DiffEntities (constantes ent_<plc_tag>)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiffEntities:
    """Resultado del diff entre desired (Excel) y base (TIA) para 1 tabla.

    Atributos:
        table_name: nombre de la tabla TIA (``"6_Entidades"``).
        base: ``{plc_tag: numero}`` del TIA (constants ``ent_<X>``).
        desired: ``{plc_tag: numero}`` del Excel.
        added: plc_tags en desired pero no en base.
        removed: plc_tags en base pero no en desired.
        renamed: ``{plc_tag: (numero_TIA, numero_Excel)}``. NO es el
            mismo rename que dispositivos: la PlcUserConstant se
            identifica por ``name`` (plc_tag), no por value (numero).
            Aqui solo se reporta cuando el plc_tag existe en ambos
            pero el ``numero`` (value) es distinto. El sync debe decidir
            entre ``update_user_constant_value`` (cambia value) y
            ``update_user_constant_name`` + delete+create.
        missing_xml: True si el XML de TIA no existia.
    """

    table_name: str
    base: dict[str, int]
    desired: dict[str, int]
    added: list[str]
    removed: list[str]
    renamed: dict[str, tuple[int, int]]
    missing_xml: bool = False

    @property
    def is_empty(self) -> bool:
        """True si no hay ningun cambio."""
        return not (self.added or self.removed or self.renamed)

    @property
    def n_total_changes(self) -> int:
        """Total de entries a aplicar en TIA (added + renamed)."""
        return len(self.added) + len(self.renamed)


# ---------------------------------------------------------------------------
# Dataclass de salida: DiffComments (comentarios de DB6_ENT.ENT[])
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiffComments:
    """Resultado del diff de comentarios entre desired (Excel) y base (TIA).

    Atributos:
        db_name: nombre del DB (``"DB6_ENT"``).
        array_name: nombre del array (``"ENT"``).
        slots_tia: set de slots existentes en TIA.
        current: ``{slot: comment_actual}`` del TIA.
        desired: ``{slot: comment_deseado}`` del Excel.
        added: slots en desired pero no en TIA (habra que inyectar).
        removed: slots en TIA sin comment Excel (preservamos: NO
            eliminamos el comment online en preview).
        updated: slots con comment distinto.
        unchanged: slots sin cambios.
        missing_xml: True si el .s7dcl/.s7res no existia.
    """

    db_name: str
    array_name: str
    slots_tia: set[int]
    current: dict[int, str | None]
    desired: dict[int, str | None]
    added: list[int]
    removed: list[int]
    updated: list[int]
    unchanged: list[int]
    missing_xml: bool = False

    @property
    def n_total_changes(self) -> int:
        """Total de comments a aplicar (added + updated)."""
        return len(self.added) + len(self.updated)


# ---------------------------------------------------------------------------
# Helpers privados (lectura XML)
# ---------------------------------------------------------------------------


def _read_entities_from_xml(xml_path: Path) -> dict[str, int]:
    """Lee un XML FLAT de ``6_Entidades`` y devuelve ``{plc_tag: numero}``.

    El XML exporta ``{value: name}`` (``PlcUserConstantModifier
    .read_user_constants_with_uids``). En TIA la tabla ``6_Entidades``
    SOLO contiene PlcUserConstants de entidades (el operario las mete
    a mano con el nombre canonico ``ENT_000``, ``ENT_001``, etc., en
    MAYUSCULAS por convencion Siemens), asi que no hay que filtrar
    por prefijo: la tabla ya viene pre-filtrada.

    Invirtiendo: ``name`` (string) = ``plc_tag`` del Excel,
    ``value`` (int via ``uid_str``) = ``numero``.

    Si el XML no existe o falla el parse, devuelve ``{}``.
    """
    if not xml_path.is_file():
        return {}
    try:
        from core.helpers.simatic_ml import PlcUserConstantModifier
        modifier = PlcUserConstantModifier(xml_path)
        raw = dict(modifier.read_user_constants_with_uids())
    except Exception as exc:
        logger.warning(
            f"[diff] No se pudo cargar XML de entidades '{xml_path.name}': {exc}"
        )
        return {}
    out: dict[str, int] = {}
    for uid_str, name in raw.items():
        plc_tag = str(name).strip()
        if not plc_tag:
            continue
        try:
            numero = int(str(uid_str).strip())
        except (TypeError, ValueError):
            continue
        out[plc_tag] = numero
    return out


# ---------------------------------------------------------------------------
# API publica: compute_diff_entities
# ---------------------------------------------------------------------------


def compute_diff_entities(
    table_name: str,
    desired_entities: list[EntidadLike],
    xml_path: Path,
) -> DiffEntities:
    """Calcula el diff entre desired_entities (Excel) y xml_path (TIA).

    Args:
        table_name: nombre de la tabla TIA (``"6_Entidades"``).
        desired_entities: lista de ``EntidadLike``.
        xml_path: ruta al ``.xml`` FLAT exportado de TIA.

    Returns:
        ``DiffEntities`` con los 4 vectores del diff + ``base``/``desired``.
    """
    desired: dict[str, int] = {}
    for entidad in desired_entities:
        plc_tag = str(getattr(entidad, "plc_tag", "") or "")
        numero = int(getattr(entidad, "numero", 0) or 0)
        if plc_tag and numero >= 0:
            desired[plc_tag] = numero

    base = _read_entities_from_xml(xml_path)
    missing_xml = not xml_path.is_file()

    base_keys = set(base.keys())
    desired_keys = set(desired.keys())

    added = sorted(desired_keys - base_keys)
    removed = sorted(base_keys - desired_keys)
    renamed: dict[str, tuple[int, int]] = {
        plc_tag: (base[plc_tag], desired[plc_tag])
        for plc_tag in (base_keys & desired_keys)
        if base[plc_tag] != desired[plc_tag]
    }

    return DiffEntities(
        table_name=table_name,
        base=base,
        desired=desired,
        added=added,
        removed=removed,
        renamed=renamed,
        missing_xml=missing_xml,
    )


# ---------------------------------------------------------------------------
# API publica: compute_nmax_diff_entidades
# ---------------------------------------------------------------------------


def compute_nmax_diff_entidades(
    table_name: str,
    desired_nmax: dict[str, int],
    xml_path: Path,
) -> Any:
    """Wrapper del ``compute_nmax_diff`` de dispositivos para N_MAX_ENTIDAD.

    La PlcUserConstant ``N_MAX_ENTIDAD`` vive en ``0_Config_Generales``
    y tiene la misma semantica que el resto de N_MAX (value = int,
    diff vs desired del Excel via ``cache.n_max[<plc>].extras``).

    Args:
        table_name: nombre de la tabla (``"0_Config_Generales"``).
        desired_nmax: ``{"N_MAX_ENTIDAD": value}`` (1 entry).
        xml_path: ruta al XML FLAT de TIA con la tabla.

    Returns:
        ``NmaxDiff`` (dataclass del helper de disp).
    """
    return compute_nmax_diff(
        table_name=table_name,
        desired_nmax=desired_nmax,
        xml_path=xml_path,
    )


# ---------------------------------------------------------------------------
# API publica: compute_comments_diff
# ---------------------------------------------------------------------------


def compute_comments_diff(
    db_name: str,
    array_name: str,
    desired_entities: list[EntidadLike],
    dcl_text: str,
    res_text: str,
) -> DiffComments:
    """Calcula el diff de comentarios del array ``ENT[]`` de ``DB6_ENT``.

    Re-uso de ``find_array_slots`` y ``read_current_comments`` del helper
    de SimaticSD (mismo patron que procesos).

    Politica (no-goal explicito del plan, lo cumple esta funcion):
      - Slots en desired pero no en TIA -> ``added`` (se inyectaran
        en el sync).
      - Slots en TIA pero no en desired -> NO se eliminan en preview
        (``removed = []``). Se preservan defensivamente; el sync (D)
        decidira si eliminarlos o no.
      - Slots en ambos con comment distinto -> ``updated``.

    Args:
        db_name: nombre del DB (``"DB6_ENT"``).
        array_name: nombre del array (``"ENT"``).
        desired_entities: lista de ``EntidadLike`` del Excel.
        dcl_text: contenido del .s7dcl.
        res_text: contenido del .s7res.

    Returns:
        ``DiffComments`` con ``current``/``desired``/4 vectores.
    """
    slots_tia = find_array_slots(dcl_text, array_name, array_type="UDT")
    current = read_current_comments(
        res_text=res_text,
        array_name=array_name,
        slots=sorted(slots_tia),
        dcl_text=dcl_text,
        array_type="UDT",
    )

    desired: dict[int, str | None] = {}
    for entidad in desired_entities:
        numero = int(getattr(entidad, "numero", 0) or 0)
        plc_comentario = str(getattr(entidad, "plc_comentario", "") or "")
        desired[numero] = plc_comentario or None

    added: list[int] = sorted(set(desired.keys()) - slots_tia)
    removed: list[int] = []  # preservacion defensiva (ver docstring)
    updated: list[int] = []
    unchanged: list[int] = []

    for slot in sorted(slots_tia & set(desired.keys())):
        cur = current.get(slot)
        des = desired.get(slot)
        # Equivalencia: ambos vacios/None = sin cambios.
        cur_norm = (cur or "").strip() if cur else ""
        des_norm = (des or "").strip() if des else ""
        if cur_norm == des_norm:
            unchanged.append(slot)
        else:
            updated.append(slot)

    return DiffComments(
        db_name=db_name,
        array_name=array_name,
        slots_tia=set(slots_tia),
        current=current,
        desired=desired,
        added=added,
        removed=removed,
        updated=updated,
        unchanged=unchanged,
        missing_xml=not (dcl_text and res_text),
    )


# ---------------------------------------------------------------------------
# API publica: compute_summary
# ---------------------------------------------------------------------------


def compute_summary(
    diff_entities: DiffEntities,
    diff_comments: DiffComments,
) -> dict[str, int]:
    """Resumen agregado del preview de entidades.

    Devuelve:
        {
          "constants_agregados":   int,
          "constants_eliminados":  int,
          "constants_renombrados": int,
          "constants_sin_cambios": int,
          "comments_added":        int,
          "comments_updated":      int,
          "comments_unchanged":    int,
          "total":                 int,
        }
    """
    sin_cambios = sum(
        1 for plc_tag in (diff_entities.base.keys() & diff_entities.desired.keys())
        if plc_tag not in diff_entities.renamed
        and plc_tag not in diff_entities.added
        and plc_tag not in diff_entities.removed
    )
    constants_agregados = len(diff_entities.added)
    constants_eliminados = len(diff_entities.removed)
    constants_renombrados = len(diff_entities.renamed)
    comments_added = len(diff_comments.added)
    comments_updated = len(diff_comments.updated)
    comments_unchanged = len(diff_comments.unchanged)

    return {
        "constants_agregados":   constants_agregados,
        "constants_eliminados":  constants_eliminados,
        "constants_renombrados": constants_renombrados,
        "constants_sin_cambios": sin_cambios,
        "comments_added":        comments_added,
        "comments_updated":      comments_updated,
        "comments_unchanged":    comments_unchanged,
        "total":                 (
            constants_agregados + constants_eliminados + constants_renombrados
            + comments_added + comments_updated
        ),
    }


# ---------------------------------------------------------------------------
# API publica: compute_unified_diff_entities
# ---------------------------------------------------------------------------


def compute_unified_diff_entities(
    diff_entities: DiffEntities,
    diff_comments: DiffComments,
) -> list[dict[str, Any]]:
    """Combina diff de constantes + diff de comentarios en una lista unificada.

    Match key: **plc_tag literal** (C.21, antes era por numero).
    El cambio es por union con PostSmoke: si TIA tiene un plc_tag
    ``Constant_1`` con value=4 y el Excel tiene ``ENT_004`` con numero=4,
    el matching por numero los emparejaba falsamente. Ahora son 2 filas
    separadas (Constant_1 como ``eliminar``, ENT_004 como ``agregar``).

    Match comment: por ``numero`` (= slot del array ``ENT[]``). Es la
    unica coordenada estable entre PlcUserConstants (value=N) y el slot
    del array que tiene el comment. Si el plc_tag no es canonico
    (``ENT_<X>``), el helper lo detecta via ``detect_inconsistencias_plc_tags``.

    Status por row (4 vectores, mismo set que ``STATUS_META``):
      - ``agregar``: plc_tag en Excel, no en TIA (o TIA sin comment en slot).
      - ``renombrar``: plc_tag en ambos, comentarios distintos.
      - ``sin_cambios``: plc_tag en ambos, comentarios identicos.
      - ``eliminar``: plc_tag en TIA con comment, no en el Excel.
        Se muestra para visibilidad; el sync lo trata como
        preservar-no-borrar (misma politica que ``compute_comments_diff``).

    Output shape por row (mismo que consume la SPA desde C.20):

        numero         : int
        plc_tag_tia    : str | None
        comment_tia    : str | None
        plc_tag_excel  : str
        comment_excel  : str | None
        status         : "agregar" | "renombrar" | "sin_cambios" | "eliminar"

    Args:
        diff_entities: resultado de ``compute_diff_entities`` sobre
            ``6_Entidades.xml``. ``desired`` y ``base`` son
            ``{plc_tag: numero}``.
        diff_comments: resultado de ``compute_comments_diff`` sobre
            ``DB6_ENT.s7dcl`` + ``.s7res``. ``current`` y ``desired``
            son ``{slot: comment}`` (slot == numero del Excel).

    Returns:
        Lista de dicts ordenada por ``numero``. NO incluye filas en TIA
        sin comment en el slot (no hay nada que representar).
    """
    base_by_plc_tag: dict[str, int] = dict(diff_entities.base)

    rows: list[dict[str, Any]] = []

    for plc_tag, numero in sorted(
        diff_entities.desired.items(), key=lambda kv: kv[1]
    ):
        comment_tia = diff_comments.current.get(numero)
        comment_excel = diff_comments.desired.get(numero)
        plc_tag_tia: str | None = plc_tag if plc_tag in base_by_plc_tag else None

        if plc_tag_tia is None or comment_tia is None:
            status = "agregar"
        elif comment_tia == comment_excel:
            status = "sin_cambios"
        else:
            status = "renombrar"

        rows.append({
            "numero":        numero,
            "plc_tag_tia":   plc_tag_tia,
            "comment_tia":   comment_tia,
            "plc_tag_excel": plc_tag,
            "comment_excel": comment_excel,
            "status":        status,
        })

    excel_plc_tags = set(diff_entities.desired.keys())
    for plc_tag in sorted(
        set(diff_entities.base.keys()) - excel_plc_tags,
        key=lambda pt: diff_entities.base[pt],
    ):
        numero = diff_entities.base[plc_tag]
        comment_tia = diff_comments.current.get(numero)
        if comment_tia is None:
            continue
        rows.append({
            "numero":        numero,
            "plc_tag_tia":   plc_tag,
            "comment_tia":   comment_tia,
            "plc_tag_excel": None,
            "comment_excel": None,
            "status":        "eliminar",
        })

    rows.sort(key=lambda r: r["numero"])
    return rows


# ---------------------------------------------------------------------------
# API publica: detect_inconsistencias_plc_tags
# ---------------------------------------------------------------------------


def detect_inconsistencias_plc_tags(
    diff_entities: DiffEntities,
) -> list[str]:
    """Detecta PlcUserConstants de TIA con plc_tag NO canonico (``ENT_<X>``).

    Caso real (PostSmoke, oct-2026): el operador metio a mano una
    constante llamada ``Constant_1`` con value=4 en TIA, mientras que
    el Excel tiene ``ENT_004`` con numero=4. La regla canonica del
    feature es que el plc_tag sea ``ENT_<X>`` con X = numero. Cualquier
    PlcUserConstant de TIA que NO la cumpla es un error del operador.

    Output: lista de warnings legibles (1 por inconsistencia). El caller
    los anyade a ``result["warnings"]`` del FB. La SPA los rendera como
    banner.

    Args:
        diff_entities: resultado de ``compute_diff_entities``.

    Returns:
        Lista de strings con warnings. Vacia si no hay inconsistencias.
    """
    warnings: list[str] = []
    for plc_tag, numero in diff_entities.base.items():
        canonico = f"ENT_{numero:03d}"
        if plc_tag != canonico:
            # Busca si ese numero existe en el Excel con el plc_tag canonico.
            excel_plc_tag = None
            for t, n in diff_entities.desired.items():
                if n == numero:
                    excel_plc_tag = t
                    break
            if excel_plc_tag is not None:
                warnings.append(
                    f"TIA tiene PlcUserConstant '{plc_tag}' con value={numero}, "
                    f"pero el Excel tiene '{excel_plc_tag}' con el mismo numero. "
                    f"La regla canonica es plc_tag = ENT_<X> con X = numero. "
                    f"Quita una o renombra."
                )
    return warnings


__all__ = [
    "DiffEntities",
    "DiffComments",
    "compute_diff_entities",
    "compute_nmax_diff_entidades",
    "compute_comments_diff",
    "compute_unified_diff_entities",
    "detect_inconsistencias_plc_tags",
    "compute_summary",
]