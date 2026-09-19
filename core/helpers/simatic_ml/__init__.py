"""Helpers transversales para SimaticML (Siemens TIA Scripting).

Modelos XML soportados:
  - ``PlcUserConstant``: dispositivos (Name=plc_tag, Value=uid) y
    constantes N_MAX (Name=suffix, Value=dimension).

Las areas (disp, proc, ...) usan estos helpers para el ciclo
``export -> modificar offline -> import`` sin acoplarse al SDK
``siemens_tia_scripting``.

Restriccion arquitectonica: este paquete es OFFLINE. No importa
``siemens_tia_scripting`` ni ``core.infrastructure.tia``. Solo
``xml.etree.ElementTree`` (stdlib).
"""
from __future__ import annotations

from core.helpers.simatic_ml.simatic_ml_user_constant_modifier import (
    PlcUserConstantModifier,
)
from core.helpers.simatic_ml.simatic_ml_user_constant_parser import (
    PlcUserConstantParser,
)


__all__ = [
    "PlcUserConstantParser",
    "PlcUserConstantModifier",
]
