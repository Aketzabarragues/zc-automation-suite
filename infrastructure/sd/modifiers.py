"""Modificadores de Simatic Source Documents (.s7dcl) para bloques.

Inyecta/actualiza líneas SCL (``cfg_* := ...;``) en archivos .s7dcl
exportados por ``TIAProcessGateway.export_blocks_sd``.

Restricción arquitectónica: este módulo es OFFLINE; no importa
``siemens_tia_scripting``. Solo usa ``pathlib`` y ``re`` (stdlib).

Estrategia:
  - El método ``update_or_insert_assignment`` trabaja sobre el LHS
    (Left-Hand Side) de la asignación (``cfg_* := ...;``).
  - Si el LHS ya existe en el archivo, reemplaza la línea completa.
  - Si no existe, la inserta al final del bloque de configuración.
  - Idempotencia garantizada: aplicar dos veces con los mismos
    parámetros no produce duplicados.

Convención de campos cfg_*:
  - ``cfg_* := TRUE;``           → habilitación booleana
  - ``cfg_* := 5;``               → asignación entera
  - ``cfg_* := DB_xxx.YYY;``      → referencia a otro bloque
  - Cada dispositivo del dominio tiene hasta 16 campos ``cfg_*``
    (ver ``core.alimentacion.models.dispositivos``).
"""
from __future__ import annotations

import re
from pathlib import Path

from core.alimentacion.models.dispositivos import Dispositivo


_MARKER_START = "// AUTO_GEN_START"
_MARKER_END = "// AUTO_GEN_END"

# Regex que captura una asignación completa:
#   ^(\s*)(LHS\s*:=.*?;)\s*$
# Grupo 1: indentación (preservada).
# Grupo 2: la asignación completa (LHS := ...;).
_ASSIGNMENT_PATTERN = re.compile(
    r"^(\s*)(\S[^\n]*?:=[^\n]*?;)\s*$",
    re.MULTILINE,
)

# Regex específica para el marcador de inicio con el LHS exacto
# (usada por update_or_insert_assignment).
_LHS_LINE_PATTERN = re.compile(
    r"^(\s*)({lhs}\s*:=.*?;)\s*$",
    re.MULTILINE,
)

# Marker pair (similar a la versión anterior) — se usa para insertar
# nuevas líneas justo antes de ``// AUTO_GEN_END``.
_MARKERS_PATTERN = re.compile(
    rf"{re.escape(_MARKER_START)}\s*\n(?P<body>.*?){re.escape(_MARKER_END)}",
    re.DOTALL,
)


def _strip_assignment_left_side(line: str) -> str:
    """Devuelve la parte LHS de una asignación (lo que está antes del ``:=``).

    Helper para construir el patrón regex dinámicamente.
    """
    idx = line.find(":=")
    if idx < 0:
        return line
    return line[:idx].rstrip()


class SDModifier:
    """Abre un .s7dcl, inyecta/actualiza líneas SCL y guarda."""

    def __init__(self, sd_path: str | Path) -> None:
        self._path = Path(sd_path)
        if not self._path.is_file():
            raise FileNotFoundError(
                f"No se encontró el archivo SD: '{self._path}'"
            )
        self._content: str = self._path.read_text(encoding="utf-8")
        self._modified: bool = False

    # ── API principal ────────────────────────────────────────────────
    def update_or_insert_assignment(
        self,
        lhs_reference: str,
        full_assignment_line: str,
    ) -> bool:
        """Inserta o reemplaza una asignación SCL por LHS.

        Args:
            lhs_reference: LHS a buscar, ej. ``"DB2000_ED.ED[1].Config_Habilitar"``.
                La coincidencia es **exacta** (ignorando espacios alrededor
                del ``:=``). El LHS puede estar precedido de indentación.
            full_assignment_line: Línea completa de asignación,
                ej. ``"DB2000_ED.ED[1].Config_Habilitar := TRUE;"``.

        Returns:
            ``True`` si el archivo fue modificado (insert o update),
            ``False`` si el contenido ya coincidía exactamente
            (idempotencia).

        Comportamiento:
          1. Busca una línea cuyo LHS coincida con ``lhs_reference``.
          2. Si existe → reemplaza la línea completa por
             ``full_assignment_line``.
          3. Si no existe → inserta ``full_assignment_line`` justo antes
             del marcador ``// AUTO_GEN_END``.
          4. Si el archivo no contiene los marcadores ``AUTO_GEN_*``,
             no hace nada y retorna ``False``.
        """
        if (
            _MARKER_START not in self._content
            or _MARKER_END not in self._content
        ):
            return False

        # 1) Intentar reemplazo.
        pattern = re.compile(
            rf"^(\s*){re.escape(lhs_reference)}\s*:=.*?;\s*$",
            re.MULTILINE,
        )
        new_content, n_subs = pattern.subn(
            full_assignment_line, self._content, count=1
        )
        if n_subs > 0:
            if new_content != self._content:
                self._content = new_content
                self._modified = True
                return True
            return False  # idempotente: ya estaba así

        # 2) Insertar antes de ``// AUTO_GEN_END``.
        #    Preservamos la indentación del marcador (8 espacios por
        #    convención de bloques de configuración Siemens).
        insertion = (
            f"        {full_assignment_line}\n"
            f"{_MARKER_END}"
        )
        patched, n_sub2 = re.subn(
            re.escape(_MARKER_END), insertion, self._content, count=1
        )
        if n_sub2 > 0:
            self._content = patched
            self._modified = True
            return True

        return False

    # ── Backwards-compatible: insert_calls (legacy) ──────────────────
    def insert_calls(self, call_names: list[str]) -> bool:
        """(LEGACY) Inserta llamadas ``Name();`` entre marcadores.

        Conservado por compatibilidad con código previo que asume este
        patrón. El motor de dispositivos moderno usa
        ``update_or_insert_assignment`` (basado en LHS := ...;).
        """
        if (
            _MARKER_START not in self._content
            or _MARKER_END not in self._content
        ):
            return False

        existing_names: set[str] = set(re.findall(
            r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(\s*\)\s*;\s*$",
            self._content, re.MULTILINE
        ))
        new_calls = [
            name for name in call_names
            if isinstance(name, str) and name.strip() and name.strip() not in existing_names
        ]
        if not new_calls:
            return False

        rendered_calls = "\n".join(f"  {name}();" for name in new_calls)
        patched, _ = _MARKERS_PATTERN.subn(
            lambda m: f"{_MARKER_START}\n{rendered_calls}\n{_MARKER_END}",
            self._content, count=1
        )
        self._content = patched
        self._modified = True
        return True

    def was_modified(self) -> bool:
        """Devuelve ``True`` si ``update_or_insert_assignment`` o
        ``insert_calls`` modificaron el contenido en memoria."""
        return self._modified

    def save(self, output_path: str | Path) -> None:
        """Escribe el contenido modificado en ``output_path``."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self._content, encoding="utf-8")


def collect_cfg_assignments(
    dispositivos_por_tipo: dict[str, list[Dispositivo]],
) -> list[tuple[str, str]]:
    """Genera ``[(lhs, full_line)]`` para TODOS los ``cfg_*`` de TODOS
    los dispositivos del subdominio.

    Convención de generación del LHS:
      - Se construye como ``"<table>.<index>.<cfg_field>"``
        (ej. ``"DB2000_ED.ED[1].Config_Habilitar"``).
    Convención del valor:
      - Si el ``cfg_*`` del dispositivo está vacío → se omite.
      - Si tiene valor → ``"<LHS> := <valor>;"``.

    Returns:
        Lista ``[(lhs_reference, full_assignment_line), ...]``.
    """
    result: list[tuple[str, str]] = []
    for tipo, dispositivos in dispositivos_por_tipo.items():
        for idx, disp in enumerate(dispositivos, start=1):
            plc_tag = str(getattr(disp, "plc_tag", "")).strip()
            if not plc_tag:
                continue
            # Construir LHS base: ``"<table>.<idx>.Config_<field>"``
            table = _to_table_name(tipo)
            for cfg_field in _iter_cfg_fields(disp):
                value = getattr(disp, cfg_field, "")
                if not value:
                    continue
                lhs = (
                    f"{table}."
                    f"{_index_token(plc_tag, idx)}."
                    f"{_cfg_to_lhs_suffix(cfg_field)}"
                )
                line = f"{lhs} := {value};"
                result.append((lhs, line))
    return result


# ── Helpers privados ──────────────────────────────────────────────────────


_TYPE_TO_TABLE_PREFIX: dict[str, str] = {
    "DispED": "DB2000_ED",
    "DispEA": "DB2000_EA",
    "DispSA": "DB2000_SA",
    "DispV": "DB2000_V",
    "DispM": "DB2000_M",
    "DispM_VF": "DB2000_MVF",
}


def _to_table_name(tipo: str) -> str:
    """Convierte ``DispED`` → ``DB2000_ED``. Fallback: tipoそのまま."""
    return _TYPE_TO_TABLE_PREFIX.get(tipo, tipo)


def _index_token(plc_tag: str, idx: int) -> str:
    """Heurística de índice: usa el último segmento del plc_tag
    si es numérico; si no, devuelve ``ED[idx]``."""
    parts = plc_tag.split("_")
    if parts and parts[-1].isdigit():
        return parts[-1]
    return f"ED[{idx}]"


def _cfg_to_lhs_suffix(cfg_field: str) -> str:
    """``cfg_habilitar`` → ``Config_Habilitar`` (camel-case)."""
    parts = cfg_field.split("_")
    return "Config_" + "_".join(p.capitalize() for p in parts[1:])


def _iter_cfg_fields(disp: Dispositivo) -> list[str]:
    """Devuelve la lista de campos ``cfg_*`` del dispositivo.

    En runtime siempre recibimos dataclasses concretos (DispED, DispEA,
    etc.), nunca instancias del Protocol. El ``# type: ignore`` silencia
    el warning de varianza de ``dataclasses.fields()`` que requiere un
    ``DataclassInstance`` o ``type[DataclassInstance]`` estricto.
    """
    import dataclasses  # type: ignore[import-untyped]

    return [
        f.name
        for f in dataclasses.fields(disp)  # type: ignore[arg-type]
        if f.name.startswith("cfg_")
    ]


__all__ = [
    "SDModifier",
    "collect_cfg_assignments",
]
