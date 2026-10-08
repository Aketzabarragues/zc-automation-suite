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
from dataclasses import dataclass, field
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
        base_comments: ``{plc_tag: comment_o_None}`` leido del XML
            TIA de la user constants table (per-constant comment).
            ``None`` si la constant existe sin comment o con comment
            vacio. Usado por el diff unificado para preferir el
            comment per-constant sobre el comment del slot del DB
            (C.25: el operario normalmente configura el comment en
            la tabla, no en el slot del DB).
        missing_xml: True si el XML de TIA no existia.
        ops: lista plana de operaciones a aplicar por el sync, en
            orden de ejecucion (post-5-pasadas de Aketza). Cada op
            tiene un ``kind`` y los campos que necesita:

              - ``{"kind": "delete",         "plc_tag": str, "value_tia": int}``
              - ``{"kind": "add",            "plc_tag": str, "value_excel": int,
                                             "comment_excel": str|None}``
              - ``{"kind": "rename",         "plc_tag_tia": str, "value_tia": int,
                                             "plc_tag_new": str}``
              - ``{"kind": "update_comment", "plc_tag": str, "value_tia": int,
                                             "comment_tia": str|None,
                                             "comment_excel": str|None}``

            El sync FB itera esta lista en orden; el preview FB la
            muestra al operario en una sola vista.
    """

    table_name: str
    base: dict[str, int]
    desired: dict[str, int]
    added: list[str]
    removed: list[str]
    renamed: dict[str, tuple[int, int]]
    base_comments: dict[str, str | None] = field(default_factory=dict)
    missing_xml: bool = False
    ops: list[dict[str, Any]] = field(default_factory=list)

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


def _read_entities_from_xml(xml_path: Path) -> tuple[dict[str, int], dict[str, str | None]]:
    """Lee un XML FLAT de ``6_Entidades`` y devuelve ``(base, base_comments)``.

    El XML exporta ``{value: {"name": str, "comment": str|None}}``
    (``PlcUserConstantModifier.read_user_constants_with_comments``).
    En TIA la tabla ``6_Entidades`` SOLO contiene PlcUserConstants de
    entidades (el operario las mete a mano con el nombre canonico
    ``ENT_000``, ``ENT_001``, etc., en MAYUSCULAS por convencion Siemens),
    asi que no hay que filtrar por prefijo: la tabla ya viene
    pre-filtrada.

    Invirtiendo: ``name`` (string) = ``plc_tag`` del Excel,
    ``value`` (int via ``uid_str``) = ``numero``,
    ``comment`` (str o ``None``) = comment per-constant del TIA
    (C.25; se prefiere este al comment del slot del DB).

    Si el XML no existe o falla el parse, devuelve ``({}, {})``.
    """
    if not xml_path.is_file():
        return {}, {}
    try:
        from core.helpers.simatic_ml import PlcUserConstantModifier
        modifier = PlcUserConstantModifier(xml_path)
        raw = dict(modifier.read_user_constants_with_comments())
    except Exception as exc:
        logger.warning(
            f"[diff] No se pudo cargar XML de entidades '{xml_path.name}': {exc}"
        )
        return {}, {}
    base: dict[str, int] = {}
    base_comments: dict[str, str | None] = {}
    for uid_str, payload in raw.items():
        plc_tag = str(payload.get("name", "")).strip()
        if not plc_tag:
            continue
        try:
            numero = int(str(uid_str).strip())
        except (TypeError, ValueError):
            continue
        base[plc_tag] = numero
        base_comments[plc_tag] = payload.get("comment")
    return base, base_comments


# ---------------------------------------------------------------------------
# API publica: compute_diff_entities
# ---------------------------------------------------------------------------


def compute_diff_entities(
    table_name: str,
    desired_entities: list[EntidadLike],
    xml_path: Path,
) -> DiffEntities:
    """Calcula el diff entre desired_entities (Excel) y xml_path (TIA).

    Deteccion en 2 fases (orden no afecta al resultado, solo al sync):

      Fase A — detectar renames por value:
        Para cada TIA plc_tag, si su value matchea con un Excel
        plc_tag DISTINTO, hay un rename. TIA conserva el value, el
        sync cambia el ``Name`` al plc_tag del Excel.

      Fase B — sobre lo que queda, calcular delete / add / update_comment:
        - TIA plc_tag sin match en Excel        -> delete.
        - TIA plc_tag matchea Excel plc_tag distinto value -> delete + add.
        - TIA plc_tag matchea Excel plc_tag mismo value, comment distinto -> update_comment.
        - Excel plc_tag sin match en TIA         -> add.
        - Excel plc_tag matcheado por rename (Fase A) -> no aparece como add
          (la constant TIA sigue existiendo, solo cambia de name).

    Args:
        table_name: nombre de la tabla TIA (``"6_Entidades"``).
        desired_entities: lista de ``EntidadLike``.
        xml_path: ruta al ``.xml`` FLAT exportado de TIA.

    Returns:
        ``DiffEntities`` con la lista ``ops`` (orden de aplicacion
        para el sync) y los vectores legacy ``added``/``removed``/
        ``renamed``/``base``/``desired``/``base_comments`` para
        mantener compat con el preview FB.
    """
    desired: dict[str, int] = {}
    desired_comments: dict[str, str | None] = {}
    for entidad in desired_entities:
        plc_tag = str(getattr(entidad, "plc_tag", "") or "")
        numero = int(getattr(entidad, "numero", 0) or 0)
        comment = str(getattr(entidad, "plc_comentario", "") or "") or None
        if plc_tag and numero >= 0:
            desired[plc_tag] = numero
            desired_comments[plc_tag] = comment

    base, base_comments = _read_entities_from_xml(xml_path)
    missing_xml = not xml_path.is_file()

    base_keys = set(base.keys())
    desired_keys = set(desired.keys())
    common_keys = base_keys & desired_keys

    # Fase A: renames por value (calcular antes de los vectores
    # legacy para que removed/added no incluyan los renames).
    base_por_value: dict[int, list[str]] = {}
    for plc_tag, value in base.items():
        base_por_value.setdefault(value, []).append(plc_tag)

    desired_por_value: dict[int, list[str]] = {}
    for plc_tag, value in desired.items():
        desired_por_value.setdefault(value, []).append(plc_tag)

    renames: list[tuple[str, int, str]] = []  # (plc_tag_tia, value, plc_tag_new)
    used_excel_tags: set[str] = set()
    for plc_tag_tia in sorted(base.keys()):
        value = base[plc_tag_tia]
        candidates = [
            t for t in desired_por_value.get(value, [])
            if t != plc_tag_tia and t not in used_excel_tags
        ]
        if not candidates:
            continue
        if plc_tag_tia in common_keys and base[plc_tag_tia] == desired.get(plc_tag_tia):
            continue
        plc_tag_new = sorted(candidates)[0]
        renames.append((plc_tag_tia, value, plc_tag_new))
        used_excel_tags.add(plc_tag_new)

    renamed_tia_tags: set[str] = {r[0] for r in renames}
    renamed_excel_tags: set[str] = {r[2] for r in renames}

    # Vectores legacy corregidos: los renames NO cuentan como
    # removed/added (la constant existe, solo cambia de name).
    added = sorted(desired_keys - base_keys - renamed_excel_tags)
    removed = sorted(base_keys - desired_keys - renamed_tia_tags)
    renamed_legacy: dict[str, tuple[int, int]] = {
        plc_tag: (base[plc_tag], desired[plc_tag])
        for plc_tag in common_keys
        if base[plc_tag] != desired[plc_tag]
    }

    # ----------------------------------------------------------------
    # Fase A: renames por value.
    #   TIA plc_tag que matchea con Excel plc_tag DISTINTO por value.
    #   TIA conserva el value, el sync cambia el ``Name`` al plc_tag
    #   del Excel. Limitamos a 1-a-1 (no 2 TIA al mismo Excel plc_tag).
    # ----------------------------------------------------------------
    base_por_value: dict[int, list[str]] = {}
    for plc_tag, value in base.items():
        base_por_value.setdefault(value, []).append(plc_tag)

    desired_por_value: dict[int, list[str]] = {}
    for plc_tag, value in desired.items():
        desired_por_value.setdefault(value, []).append(plc_tag)

    renames: list[tuple[str, int, str]] = []  # (plc_tag_tia, value, plc_tag_new)
    used_excel_tags: set[str] = set()
    # Orden estable: iteramos TIA por plc_tag.
    for plc_tag_tia in sorted(base.keys()):
        value = base[plc_tag_tia]
        candidates = [
            t for t in desired_por_value.get(value, [])
            if t != plc_tag_tia and t not in used_excel_tags
        ]
        if not candidates:
            continue
        # Si el Excel tiene el mismo plc_tag (comun, mismo value), no
        # es un rename (es sin_cambios o update_comment). Saltamos.
        if plc_tag_tia in common_keys and base[plc_tag_tia] == desired.get(plc_tag_tia):
            continue
        # Tomamos el primer candidato disponible.
        plc_tag_new = sorted(candidates)[0]
        renames.append((plc_tag_tia, value, plc_tag_new))
        used_excel_tags.add(plc_tag_new)

    # ----------------------------------------------------------------
    # Fase B: delete / add / update_comment sobre lo que queda.
    # ----------------------------------------------------------------
    # Tags de TIA que se renombran (siguen existiendo, solo cambia name).
    renamed_tia_tags: set[str] = {r[0] for r in renames}
    # Tags de Excel que matchearon por rename (NO se agregan: la
    # constant TIA se renombra, no se duplica).
    renamed_excel_tags: set[str] = {r[2] for r in renames}

    # Construimos las ops por fase, luego las encadenamos en el
    # orden de aplicacion del sync:
    #   1. delete olds (plc_tag solo en TIA).
    #   2. renames (TIA conserva el value, cambia name).
    #   3. delete + add por value distinto (plc_tag comun, mismo
    #      plc_tag, value distinto).
    #   4. adds nuevos (Excel sin match en TIA, excluyendo los
    #      matcheados por rename).
    #   5. update_comment.

    ops_delete_olds: list[dict[str, Any]] = []
    for plc_tag in sorted(removed):
        ops_delete_olds.append({
            "kind":      "delete",
            "plc_tag":   plc_tag,
            "value_tia": base[plc_tag],
        })

    ops_renames: list[dict[str, Any]] = [
        {
            "kind":        "rename",
            "plc_tag_tia": plc_tag_tia,
            "value_tia":   value,
            "plc_tag_new": plc_tag_new,
        }
        for plc_tag_tia, value, plc_tag_new in renames
    ]

    ops_delete_add: list[dict[str, Any]] = []
    for plc_tag in common_keys:
        if base[plc_tag] == desired[plc_tag]:
            continue
        if plc_tag in renamed_tia_tags:
            continue  # cubierto por rename
        ops_delete_add.append({
            "kind":      "delete",
            "plc_tag":   plc_tag,
            "value_tia": base[plc_tag],
        })
        ops_delete_add.append({
            "kind":         "add",
            "plc_tag":      plc_tag,
            "value_excel":  desired[plc_tag],
            "comment_excel": desired_comments[plc_tag],
        })

    ops_adds: list[dict[str, Any]] = []
    for plc_tag in sorted(added):
        if plc_tag in renamed_excel_tags:
            continue  # cubierto por rename
        ops_adds.append({
            "kind":         "add",
            "plc_tag":      plc_tag,
            "value_excel":  desired[plc_tag],
            "comment_excel": desired_comments[plc_tag],
        })

    ops_update_comment: list[dict[str, Any]] = []
    for plc_tag in common_keys:
        if base[plc_tag] != desired[plc_tag]:
            continue  # ya manejado (delete+add) o rename
        cur = (base_comments.get(plc_tag) or "").strip()
        des = (desired_comments.get(plc_tag) or "").strip()
        if cur == des:
            continue
        ops_update_comment.append({
            "kind":         "update_comment",
            "plc_tag":      plc_tag,
            "value_tia":    base[plc_tag],
            "comment_tia":  base_comments.get(plc_tag),
            "comment_excel": desired_comments[plc_tag],
        })

    ops = (
        ops_delete_olds
        + ops_renames
        + ops_delete_add
        + ops_adds
        + ops_update_comment
    )

    return DiffEntities(
        table_name=table_name,
        base=base,
        desired=desired,
        added=added,
        removed=removed,
        renamed=renamed_legacy,
        base_comments=base_comments,
        missing_xml=missing_xml,
        ops=ops,
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
    los anyade a ``result["warnings"]`` del FB. Sin banner visual en
    la SPA (solo en el JSON).

    Args:
        diff_entities: resultado de ``compute_diff_entities``.

    Returns:
        Lista de strings con warnings. Vacia si no hay inconsistencias.
    """
    warnings: list[str] = []
    for plc_tag, numero in diff_entities.base.items():
        canonico = f"ENT_{numero:03d}"
        if plc_tag != canonico:
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
    "detect_inconsistencias_plc_tags",
    "compute_summary",
]
