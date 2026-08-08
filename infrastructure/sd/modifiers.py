"""Modificadores de Simatic Source Documents (.s7dcl) para bloques.

Inyecta llamadas de instancia de hardware entre los marcadores
``// AUTO_GEN_START`` y ``// AUTO_GEN_END`` de un archivo .s7dcl
exportado previamente por ``TIAProcessGateway.export_blocks_sd``.

Restricción arquitectónica: este módulo es OFFLINE; no importa
``siemens_tia_scripting``. Solo usa ``pathlib`` y ``re`` (stdlib).

Idempotencia: si alguna de las llamadas a insertar ya existe en el
archivo (detectada como ``<nombre>();``), no se duplica.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


_MARKER_START = "// AUTO_GEN_START"
_MARKER_END = "// AUTO_GEN_END"

# Detecta llamadas tipo ``Algo();`` o ``Algo(  );`` (con/sin espacios).
_CALL_PATTERN = re.compile(
    r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(\s*\)\s*;\s*$",
    re.MULTILINE,
)

_MARKERS_PATTERN = re.compile(
    rf"{re.escape(_MARKER_START)}\s*\n(?P<body>.*?){re.escape(_MARKER_END)}",
    re.DOTALL,
)


class SDModifier:
    """Abre un .s7dcl, inyecta llamadas entre marcadores y guarda."""

    def __init__(self, sd_path: str | Path) -> None:
        self._path = Path(sd_path)
        if not self._path.is_file():
            raise FileNotFoundError(
                f"No se encontró el archivo SD: '{self._path}'"
            )
        self._content: str = self._path.read_text(encoding="utf-8")

    def insert_calls(self, call_names: list[str]) -> bool:
        """Inserta llamadas entre los marcadores AUTO_GEN.

        Args:
            call_names: Lista de nombres de instancia (``"DispED_1"``, ...).

        Returns:
            ``True`` si el archivo fue modificado, ``False`` si ya estaba
            sincronizado (idempotente) o no contenía los marcadores.
        """
        if (
            _MARKER_START not in self._content
            or _MARKER_END not in self._content
        ):
            return False

        existing_names: set[str] = set(_CALL_PATTERN.findall(self._content))
        new_calls = [
            name for name in call_names
            if isinstance(name, str)
            and name.strip()
            and name.strip() not in existing_names
        ]
        if not new_calls:
            return False

        rendered_calls = "\n".join(
            f"  {name}();" for name in new_calls
        )

        def _replace(match: re.Match[str]) -> str:
            body: str = match.group("body")
            # Preservar cuerpo previo (si lo hay) y añadir las nuevas.
            addition = (
                f"\n{rendered_calls}\n"
                if body.strip() == ""
                else f"\n{body.rstrip()}\n{rendered_calls}\n"
            )
            return f"{_MARKER_START}\n{addition}{_MARKER_END}"

        new_content, n_subs = _MARKERS_PATTERN.subn(
            _replace, self._content, count=1
        )
        if n_subs == 0:
            return False
        self._content = new_content
        return True

    def save(self, output_path: str | Path) -> None:
        """Escribe el contenido modificado en ``output_path``."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self._content, encoding="utf-8")


def collect_call_names(dtos_by_type: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Aplana el mapeo ``{tipo: [dto, ...]}`` a una lista de nombres.

    Útil para el Caso de Uso: recolecta todos los ``nombre`` de todas
    las instancias de hardware en una sola lista para inyectar en
    los archivos .s7dcl.

    Args:
        dtos_by_type: Salida de ``ExcelParser.extraer_dtos()``.

    Returns:
        Lista de nombres de instancia, sin duplicados, en orden estable.
    """
    seen: set[str] = set()
    result: list[str] = []
    for dtos in dtos_by_type.values():
        if not isinstance(dtos, list):
            continue
        for dto in dtos:
            if not isinstance(dto, dict):
                continue
            name = str(dto.get("nombre", "")).strip()
            if name and name not in seen:
                seen.add(name)
                result.append(name)
    return result
