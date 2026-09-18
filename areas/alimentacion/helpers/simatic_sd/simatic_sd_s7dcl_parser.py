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
    INMEDIATAMENTE antes O inmediatamente despues de la asignacion,
    segun el formato. Esto es importante porque el formato TIA V21
    exporta DBs con DOS secciones mezcladas:

      - **Seccion A (inline / inicializacion)**: ``<ARRAY>[slot] := VALOR;``
        seguido del bloque MLC. Ejemplo real (sept-2026, proceso 50010):
        ``PInt_Vis[1] := false; \\n { \\n S7_MLC := "MLC_GXnT"; \\n }``.
        El MLC esta DESPUES de la asignacion.

      - **Seccion B (standalone / MLCs)**: ``{ \\n S7_MLC := "MLC_xxx"; \\n }``
        seguido de ``<ARRAY>[slot] := ();``. El MLC esta ANTES.

    Sept-2026 fix (tras bug smoke en vivo proceso 50010):

      - El algoritmo anterior buscaba el ULTIMO MLC en un rango que iba
        desde la ultima asignacion del mismo array hasta la actual.
        Esto daba resultados incorrectos en tres casos:

        1. Slots en Seccion A sin MLC propio (PReal_Vis[1] :=
           FALSE;) → devolvia un MLC compartido de UDT u otro array
           (p.ej. MLC_4dY del UDT PInt), contaminando ambos slots.
        2. Slots en Seccion A con MLC adyacente anterior (PInt_Vis[2]
           := false; con MLC_GXnT del PInt_Vis[1] entre medias) →
           off-by-one: devolvia el MLC del slot anterior.
        3. Slots en Seccion B tras Seccion A (PReal_Vis[2] := (); con
           docenas de MLCs de Seccion A entre medias) → devolvia un
           MLC aleatorio de Seccion A en lugar del MLC adyacente real
           (que esta en las 1-3 lineas anteriores).

      - El algoritmo nuevo detecta el formato (A vs B) y busca el MLC
        en la direccion correcta, dentro de un rango pequeno (~10
        lineas). Esto es determinista: si el MLC esta a >10 lineas
        de la asignacion, NO es de ese slot.

    Sept-2026 fix previo: normaliza ``array_name`` antes de comparar
    (soporta tanto ``'"DispED"'`` (disp) como ``'PReal'`` (proc)).

    Devuelve ``None`` si la asignacion no existe o si existe pero
    sin MLC adyacente.
    """
    target = _normalize_array_name(array_name)
    match = find_assignment(s7dcl, target, slot)
    if match is None:
        return None
    assign_start = match.start()
    assign_end = match.end()

    # Detectar formato: standalone (:= ();) o inline (:= VALOR;).
    # El regex _ASSIGNMENT_RE captura `(?:\([^)]*\)|[^;]+)` despues de
    # `:=`, o sea acepta ambos formatos. Aqui los distinguimos.
    full_match = match.group(0)
    is_standalone = bool(re.search(r":=\s*\(\s*\)\s*;", full_match))

    if is_standalone:
        # Seccion B: MLC esta ANTES de la asignacion. Tomamos el MLC
        # INMEDIATAMENTE anterior (sin asignaciones de cualquier
        # array entre medias). El rango es ~200 chars, suficiente
        # para un bloque MLC multi-linea con indentacion.
        #
        # Por que NO el algoritmo antiguo (`prev_assign_end` +
        # `last_mlc` en todo el rango): si hay MUCHAS asignaciones
        # del mismo array antes (caso real: PReal[1..3] del proceso
        # 50010), el ultimo MLC en ese rango enorme era de OTRO slot
        # (p.ej. MLC de Aux.PInt_ValorAnterior[10]), no el adyacente
        # al slot actual.
        #
        # El rango es ~200 chars: un bloque MLC multi-linea + ~5
        # lineas de asignacion. Suficiente para archivos reales y
        # sintéticos compactos. Para archivos sinteticos MUY grandes
        # (donde el MLC esta a >200 chars), el updater deberia usar
        # un cache pre-construido (no incluido en este fix; sept-2026
        # follow-up).
        before_start = max(0, assign_start - 200)
        before_range = s7dcl[before_start:assign_start]
        last_mlc: str | None = None
        last_mlc_end_in_range = -1
        for blk in _MLC_BLOCK_RE.finditer(before_range):
            inner = _MLC_INNER_RE.search(blk.group("body"))
            if inner:
                last_mlc = inner.group("mlc")
                last_mlc_end_in_range = blk.end()
        if last_mlc is None:
            return None
        # Verificar que no hay asignacion (de cualquier array) entre
        # el MLC encontrado y la asignacion actual.
        between = before_range[last_mlc_end_in_range:]
        if _ASSIGNMENT_RE.search(between):
            # Hay una asignacion entre el MLC y esta: el MLC no es
            # adyacente a esta asignacion (es de OTRO slot).
            return None
        return last_mlc

    # Seccion A (inline / inicializacion): MLC esta DESPUES de la
    # asignacion. Buscamos el PRIMER MLC que este INMEDIATAMENTE
    # despues, sin ninguna asignacion (de cualquier array) entre
    # medias. Si la hay, ese MLC es de OTRO slot/array (no del
    # actual) y debemos devolver None.
    #
    # El rango es de ~200 chars: suficiente para un bloque MLC
    # multi-linea con indentacion + 1 linea en blanco antes de la
    # siguiente asignacion del mismo array. Si el siguiente MLC esta
    # mas lejos, NO es del slot actual.
    after_range = s7dcl[assign_end:assign_end + 200]
    for blk in _MLC_BLOCK_RE.finditer(after_range):
        between = s7dcl[assign_end:assign_end + blk.start()]
        if _ASSIGNMENT_RE.search(between):
            # Hay otra asignacion entre medias: el MLC es de OTRO
            # slot/array. Esta asignacion tampoco tiene MLC propio.
            return None
        inner = _MLC_INNER_RE.search(blk.group("body"))
        if inner:
            return inner.group("mlc")
    return None


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
