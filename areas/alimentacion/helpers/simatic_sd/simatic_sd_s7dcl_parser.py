"""Parser de .s7dcl para modificadores SimaticSD.

Funciones puras de extraccion (sin estado). Trabajan sobre el texto
del archivo .s7dcl/.s7res y devuelven estructuras (set, match, etc.).
"""
from __future__ import annotations

import re


# ── Regex ──────────────────────────────────────────────────────────────────

# Detecta una asignacion ``<ARRAY>[idx] := ();`` en el .s7dcl.
# - Acepta arrays cualificados con prefijo (e.g. ``"ED"``) y escalares
#   simples entre comillas.
# - Acepta tanto ``();`` como cualquier expresion que termine en ``;``.
_ASSIGNMENT_RE = re.compile(
    r"""(?xm)
    ^(?P<indent>\s*)
    (?P<lhs>"?(?P<array>(?:[A-Za-z_][A-Za-z0-9_]*\.)*[A-Za-z_][A-Za-z0-9_]*)"?\s*\[(?P<idx>\d+)\])
    \s*:=\s*(?:\([^)]*\)|[^;]+)\s*;
    \s*$
    """
)

# Detecta un bloque ``{ ... S7_MLC := "MLC_xxx" ... }`` (single-line o multi-linea).
_MLC_BLOCK_RE = re.compile(
    r"""(?xm)
    ^(?P<indent>\s*)\{(?P<body>[^}]*)\}\s*$
    """
)

# Captura el ``S7_MLC := "MLC_xxx"`` dentro del cuerpo de un bloque.
_MLC_INNER_RE = re.compile(
    r"""S7_MLC\s*:=\s*"(?P<mlc>[A-Za-z_][A-Za-z0-9_]*)"\s*;?"""
)


# ── Extraccion de MLCs ─────────────────────────────────────────────────────

def extract_existing_mlcs_from_s7res(s7res: str) -> set[str]:
    """Lee el ``.s7res`` y devuelve el set de IDs ``MLC_*`` presentes."""
    return set(re.findall(r"^\s*-\s*id:\s*(MLC_\S+)\s*$", s7res, re.MULTILINE))


def extract_all_mlcs_from_s7dcl(s7dcl: str) -> set[str]:
    """Extrae TODOS los MLCs referenciados en el ``.s7dcl``.

    Tres formatos soportados (todos producen una referencia MLC que
    TIA cuenta y que DEBE tener su entrada en el .s7res):

    1. **Cabecera del bloque**:
       ``S7_BlockComment := "MLC_32c"``,
       ``S7_BlockTitle := "MLC_wT"``.

    2. **Bloque de declaracion de variable/array**:
       ``{ S7_MLC := "MLC_3Vz" }`` antes de
       ``"ED" : Array[...] of _.UDT_...``.

    3. **Bloque adyacente a asignacion de instancia**:
       ``{ S7_MLC := "MLC_3vw" }`` antes de ``ED[i] := ();``.
    """
    return set(
        re.findall(
            r'S7_(?:BlockComment|BlockTitle|MLC)\s*:=\s*"(MLC_[A-Za-z0-9_]+)"',
            s7dcl,
        )
    )


# ── Busqueda de asignaciones ───────────────────────────────────────────────

def _normalize_array_name(name: str) -> str:
    """Quita comillas envolventes de un ``array_name``.

    El regex ``_ASSIGNMENT_RE`` captura el grupo ``array`` SIN comillas
    (las comillas estan fuera del grupo, marcadas con ``"?`` opcionales).
    Para que ``array_name`` del caller coincida tanto si lo paso con
    comillas (disp, ej. ``'"DispED"'``) como sin ellas (proc, ej.
    ``'PReal'``), normalizamos aqui.
    """
    return name.strip('"') if name else name


def find_assignment_mlc(
    s7dcl: str, array_name: str, slot: int
) -> str | None:
    """Busca ``<ARRAY>[slot] := ...;`` y devuelve su MLC adyacente.

    El MLC asociado es el bloque ``{ S7_MLC := "..." }`` que aparece
    INMEDIATAMENTE antes de la asignacion, sin otra asignacion
    ``<ARRAY>[<otro>]:=...;`` del mismo array en medio. Esto es
    importante porque el formato TIA puede tener varios bloques
    ``S7_MLC`` consecutivos (uno por slot) y cada uno va con su slot.

    Sept-2026 fix: normaliza ``array_name`` antes de comparar (soporta
    tanto ``'"DispED"'`` (disp) como ``'PReal'`` (proc)).

    Devuelve ``None`` si la asignacion no existe o si existe pero
    sin MLC adyacente.
    """
    target = _normalize_array_name(array_name)
    match = find_assignment(s7dcl, target, slot)
    if match is None:
        return None
    assign_start = match.start()
    prev_assign_end = 0
    for prev in _ASSIGNMENT_RE.finditer(s7dcl[:assign_start]):
        if prev.group("array") == target:
            prev_assign_end = prev.end()
    search_range = s7dcl[prev_assign_end:assign_start]
    last_mlc: str | None = None
    for blk in _MLC_BLOCK_RE.finditer(search_range):
        inner = _MLC_INNER_RE.search(blk.group("body"))
        if inner:
            last_mlc = inner.group("mlc")
    return last_mlc


def find_assignment(
    s7dcl: str, array_name: str, slot: int
) -> re.Match[str] | None:
    """Localiza la asignacion ``<ARRAY>[slot] := ...;`` en el .s7dcl.

    Sept-2026 fix: normaliza ``array_name`` antes de comparar (soporta
    tanto ``'"DispED"'`` (disp) como ``'PReal'`` (proc)).
    """
    target = _normalize_array_name(array_name)
    for m in _ASSIGNMENT_RE.finditer(s7dcl):
        array = m.group("array")
        idx = int(m.group("idx"))
        if array == target and idx == slot:
            return m
    return None


def find_array_slots(s7dcl: str, array_name: str) -> set[int]:
    """Devuelve el set de slots que tienen asignacion en el .s7dcl
    para el array dado.

    Filtra por ``slot >= 1`` (disp incluye slot 0 valido; proc no).
    Para disp, el caller debe pasar ``array_name`` con comillas
    ('"DispED"'); para proc, sin comillas ('PReal'). El parser
    ahora normaliza internamente para soportar ambos formatos
    indistintamente.

    Util para detectar slots "huerfanos" del Excel: el operario
    tiene en su Excel un subconjunto de los slots que existen
    en TIA.
    """
    target = _normalize_array_name(array_name)
    result: set[int] = set()
    for match in _ASSIGNMENT_RE.finditer(s7dcl):
        arr = match.group("array")
        if arr == target:
            try:
                slot = int(match.group("idx"))
            except (TypeError, ValueError):
                continue
            result.add(slot)
    return result


__all__ = [
    "extract_existing_mlcs_from_s7res",
    "extract_all_mlcs_from_s7dcl",
    "find_assignment_mlc",
    "find_assignment",
    "find_array_slots",
]
