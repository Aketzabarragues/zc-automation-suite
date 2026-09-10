"""Capa de dominio del área Alimentación (Bounded Context).

Modelos puros del subdominio alimentación:
  - ``Dispositivo`` (Protocol base).
  - 6+1 dataclasses frozen (``DispED``/``DispEA``/``DispSA``/``DispV``/
    ``DispM``/``DispM_VF`` + ``DimensionesDispositivos``).
  - Catálogo de presentación del área (``build_catalog``) que el
    endpoint ``GET /api/v1/catalog`` consume.

Restricción arquitectónica: este paquete es ESTRICTAMENTE PURO.
- Prohibido importar ``siemens_tia_scripting``.
- Prohibido el uso de ``Any`` en los modelos de dominio declarados.
- Prohibido depender de librerías de infraestructura (openpyxl, etc.).
"""
from areas.alimentacion.domain.models.excel_cache import (
    DimensionesDispositivos,
    DispEA,
    DispED,
    DispM,
    DispM_VF,
    DispSA,
    DispV,
    Dispositivo,
)

__all__ = [
    # Protocol y dimensiones
    "Dispositivo",
    "DimensionesDispositivos",
    # Dataclasses de dispositivos
    "DispED",
    "DispEA",
    "DispSA",
    "DispV",
    "DispM",
    "DispM_VF",
]
