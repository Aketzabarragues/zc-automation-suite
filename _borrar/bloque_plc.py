"""Value Object: ``BloquePLC``.

DTO inmutable que representa un bloque (o grupo) del árbol de programas de
un PLC en TIA Portal. Se construye en el worker OT durante el escaneo
recursivo y se serializa a JSON primitivo para cruzar la frontera IPC.

Convenciones:
  - ``nombre`` es el nombre visible en TIA (``"DB1_SYS"``, ``"FB_Main"``…).
  - ``numero`` es el ordinal numérico (parte tras el prefijo ``DB/FB/FC/OB/UDT``).
    ``0`` si el nombre no encaja en ninguno de esos prefijos.
  - ``tipo`` es la familia normalizada: ``"DB" | "FB" | "FC" | "OB" | "UDT" | "OTHER"``.
  - ``ruta`` es la jerarquía TIA con separador ``"\\"`` (p.ej. ``"0_Sistema\\DB1_SYS"``).
    Vacía si TIA no pudo resolver la ruta en ese instante (defensivo, ver
    legacy ``scanner.py`` líneas 156-169).
  - ``normalize_name`` se usa como clave estable en caches/dicts (tolera
    NBSP, espacios, mayúsculas/minúsculas). NO se hace prefix-stripping
    (``DB/FB/FC``) porque la identidad del bloque incluye el tipo.

Restricción arquitectónica (.clinerules §3): no se importan wrappers
nativos. Solo ``dataclasses`` y ``re``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class BloquePLC:
    """DTO inmutable de un bloque PLC escaneado."""

    nombre: str
    numero: int
    tipo: str  # "DB" | "FB" | "FC" | "OB" | "UDT" | "OTHER"
    ruta: str  # TIA hierarchy, "\\" separator, "" si falló get_path().

    @staticmethod
    def normalize_name(nombre: str) -> str:
        """Clave estable para caches y lookups case/space-insensitive.

        - Sustituye NBSP (``\\xa0``) por vacío.
        - Elimina espacios.
        - ``strip()`` y ``lower()``.

        NO se hace prefix-stripping (``DB/FB/FC``): la identidad del bloque
        en TIA incluye el tipo, y al normalizar debemos seguir
        distinguiendo un ``DB1`` de un ``FB1``.
        """
        return (
            nombre.replace("\xa0", "")
            .replace(" ", "")
            .strip()
            .lower()
        )

    @staticmethod
    def detect_tipo(nombre: str) -> str:
        """Detecta la familia del bloque a partir de su prefijo.

        Devuelve ``"DB" | "FB" | "FC" | "OB" | "UDT"`` si ``nombre`` empieza
        por uno de esos prefijos (case-insensitive) seguido de dígitos.
        Devuelve ``"OTHER"`` en cualquier otro caso (p.ej. grupos de
        usuario, bloques sin prefijo estándar).
        """
        m = re.match(r"^(DB|FB|FC|OB|UDT)(\d+)", nombre, re.IGNORECASE)
        return m.group(1).upper() if m else "OTHER"

    def to_dict(self) -> dict:
        """Serializa a dict primitivo (compatible JSON / IPC)."""
        return {
            "nombre": self.nombre,
            "numero": self.numero,
            "tipo": self.tipo,
            "ruta": self.ruta,
        }
