"""DTO inmutable de un bloque (o grupo) del arbol de programas TIA.

Se construye en el worker OT durante el escaneo recursivo y se
serializa a JSON primitivo para cruzar la frontera IPC.

Campos basicos (siempre presentes):
  - nombre (str): nombre visible en TIA (``"DB1_SYS"``, ``"FB_Main"``).
  - numero (int): ordinal numerico (parte tras el prefijo DB/FB/FC/OB/UDT).
    0 si el nombre no encaja en ninguno de esos prefijos.
  - tipo (str): familia normalizada. Uno de ``"DB" | "FB" | "FC" | "OB" | "UDT" | "OTHER"``.
  - ruta (str): jerarquia TIA con separador ``"\\"``. Vacia si TIA no
    pudo resolver la ruta (defensivo).

Campos extendidos (opcionales, default ``None``). Se populan desde
TIA via ``PlcBlock.get_properties()`` durante el scan:
  - title (str | None): titulo del bloque en TIA.
  - comment (str | None): comentario del bloque en TIA.
  - author (str | None): autor del bloque en TIA.
  - version (str | None): version del bloque en TIA.
  - programming_language (str | None): SCL/LAD/FBD/STL/GRAPH/CFC.
  - memory_layout (str | None): Standard/Optimized.

Solo ``nombre`` y ``numero`` son editables via ``PlcBlock.set_property``.
Los campos extendidos no son editables por ``set_property``
(rc=20 OpennessAccessException); requieren export-XML-reimport.

Helpers estaticos:
  - normalize_name(nombre): clave estable case/space-insensitive
    (tolera NBSP, espacios, mayusculas). NO hace prefix-stripping:
    la identidad del bloque incluye el tipo (DB1 != FB1).
  - detect_tipo(nombre): detecta la familia a partir del prefijo.
    ``"OTHER"`` si no encaja.

Restriccion arquitectonica (.clinerules): no se importan wrappers nativos.
Solo ``dataclasses``, ``re`` y ``typing``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DataBloquePLC:
    """DTO inmutable de un bloque PLC escaneado."""

    nombre: str
    numero: int
    tipo: str
    ruta: str
    title: Optional[str] = None
    comment: Optional[str] = None
    author: Optional[str] = None
    version: Optional[str] = None
    programming_language: Optional[str] = None
    memory_layout: Optional[str] = None

    @staticmethod
    def normalize_name(nombre: str) -> str:
        """Clave case/space-insensitive para caches y lookups.

        Tolera NBSP, espacios y mayusculas. NO hace prefix-stripping:
        DB1 y FB1 son distintos aunque coincidan al quitar prefijo.
        """
        return (
            nombre.replace("\xa0", "")
            .replace(" ", "")
            .strip()
            .lower()
        )

    @staticmethod
    def detect_tipo(nombre: str) -> str:
        """Familia del bloque segun prefijo (DB/FB/FC/OB/UDT) + digitos.

        Devuelve ``"OTHER"`` si no encaja (grupos de usuario, etc.).
        """
        m = re.match(r"^(DB|FB|FC|OB|UDT)(\d+)", nombre, re.IGNORECASE)
        return m.group(1).upper() if m else "OTHER"

    def to_dict(self) -> dict:
        """Serializa a dict primitivo (JSON / IPC / SSE)."""
        return {
            "nombre": self.nombre,
            "numero": self.numero,
            "tipo": self.tipo,
            "ruta": self.ruta,
            "title": self.title,
            "comment": self.comment,
            "author": self.author,
            "version": self.version,
            "programming_language": self.programming_language,
            "memory_layout": self.memory_layout,
        }