"""core.data.data_bloque_plc — Data Block del DTO ``BloquePLC``.

Fase 3, paso 3.1.3.  Migrado de ``core/models/bloque_plc.py``.  DTO
inmutable que representa un bloque (o grupo) del arbol de programas
de un PLC en TIA Portal.  Se construye en el worker OT durante el
escaneo recursivo y se serializa a JSON primitivo para cruzar la
frontera IPC.

Campos:
  - ``nombre`` (str): nombre visible en TIA (``"DB1_SYS"``,
    ``"FB_Main"``...).
  - ``numero`` (int): ordinal numerico (parte tras el prefijo
    ``DB/FB/FC/OB/UDT``).  ``0`` si el nombre no encaja en ninguno
    de esos prefijos.
  - ``tipo`` (str): familia normalizada.  Uno de
    ``"DB" | "FB" | "FC" | "OB" | "UDT" | "OTHER"``.
  - ``ruta`` (str): jerarquia TIA con separador ``"\\"`` (p.ej.
    ``"0_Sistema\\DB1_SYS"``).  Vacia si TIA no pudo resolver la
    ruta en ese instante (defensivo, ver legacy ``scanner.py``
    lineas 156-169).

Helpers estaticos:
  - ``normalize_name(nombre)``: clave estable para caches y lookups
    case/space-insensitive (tolera NBSP, espacios, mayusculas).
    NO se hace prefix-stripping (``DB/FB/FC``): la identidad del
    bloque incluye el tipo, y al normalizar debemos seguir
    distinguiendo un ``DB1`` de un ``FB1``.
  - ``detect_tipo(nombre)``: detecta la familia a partir del
    prefijo.  ``"OTHER"`` si no encaja.

Migracion:
  - Renombrado de ``BloquePLC`` (legacy) a ``DataBloquePLC``.  El
    legacy ``core/models/bloque_plc.py`` se mantiene hasta Fase 4
    (DA-006 del plan: los use cases legacy coexisten con los DBs
    hasta Fase 4).  En 4.0.6 se borra ``core/models/`` y la
    implementacion pasa a vivir solo aqui.
  - ``DataBloqueCache`` (paso 3.1.2) se actualiza en este mismo
    paso para importar ``DataBloquePLC`` desde el nuevo modulo
    en lugar de ``BloquePLC`` del legacy.

Restriccion arquitectonica (.clinerules §3): no se importan wrappers
nativos.  Solo ``dataclasses`` y ``re``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DataBloquePLC:
    """DTO inmutable de un bloque PLC escaneado."""

    nombre: str
    numero: int
    tipo: str  # "DB" | "FB" | "FC" | "OB" | "UDT" | "OTHER"
    ruta: str  # TIA hierarchy, "\\" separator, "" si fallo get_path().

    @staticmethod
    def normalize_name(nombre: str) -> str:
        """Clave estable para caches y lookups case/space-insensitive.

        - Sustituye NBSP (``\\xa0``) por vacio.
        - Elimina espacios.
        - ``strip()`` y ``lower()``.

        NO se hace prefix-stripping (``DB/FB/FC``): la identidad del
        bloque en TIA incluye el tipo, y al normalizar debemos
        seguir distinguiendo un ``DB1`` de un ``FB1``.
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

        Devuelve ``"DB" | "FB" | "FC" | "OB" | "UDT"`` si ``nombre``
        empieza por uno de esos prefijos (case-insensitive) seguido
        de digitos.  Devuelve ``"OTHER"`` en cualquier otro caso
        (p.ej. grupos de usuario, bloques sin prefijo estandar).
        """
        m = re.match(r"^(DB|FB|FC|OB|UDT)(\d+)", nombre, re.IGNORECASE)
        return m.group(1).upper() if m else "OTHER"

    def to_dict(self) -> dict:
        """Serializa a dict primitivo (compatible JSON / IPC / SSE)."""
        return {
            "nombre": self.nombre,
            "numero": self.numero,
            "tipo": self.tipo,
            "ruta": self.ruta,
        }
