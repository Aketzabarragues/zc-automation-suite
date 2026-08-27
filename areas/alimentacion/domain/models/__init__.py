"""Modelos de dominio del subdominio alimentación.

Expone las dataclasses inmutables (frozen) que modelan los dispositivos
de hardware del departamento de alimentación. Todos los modelos respetan
el Protocol ``Dispositivo`` cuando representan dispositivos instanciables
en el PLC.

Restricción arquitectónica: estos modelos son ESTRICTAMENTE PUROS.
- Sin imports de ``siemens_tia_scripting``.
- Sin imports de openpyxl u otras librerías de infraestructura.
- Sin uso de ``Any`` en los atributos declarados.
"""

from areas.alimentacion.domain.models.dispositivos import (
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
    # Dataclasses de dispositivos (purgado de "hardware")
    "DispED",
    "DispEA",
    "DispSA",
    "DispV",
    "DispM",
    "DispM_VF",
]
