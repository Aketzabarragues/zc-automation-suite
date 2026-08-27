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
"""
from __future__ import annotations

import re
from pathlib import Path


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

    def was_modified(self) -> bool:
        """Devuelve ``True`` si ``update_or_insert_assignment`` modificó
        el contenido en memoria."""
        return self._modified

    def save(self, output_path: str | Path) -> None:
        """Escribe el contenido modificado en ``output_path``."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self._content, encoding="utf-8")


__all__ = ["SDModifier"]
