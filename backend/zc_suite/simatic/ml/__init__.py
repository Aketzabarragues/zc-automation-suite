"""Helpers transversales para SimaticML (Siemens TIA Scripting).

Modelos XML soportados:

- ``PlcUserConstant``: el nombre es el tag del PLC y el valor es el dato
  (un indice de dispositivo o el valor de una constante de dimension).

Las areas usan estos helpers para el ciclo
``export -> modificar offline -> import`` sin acoplarse al SDK
``siemens_tia_scripting``.

Este paquete es **offline**: no importa ``siemens_tia_scripting`` ni el
nucleo de TIA. Solo ``xml.etree.ElementTree`` (stdlib).
"""
from __future__ import annotations

from zc_suite.simatic.ml.constantes_modificador import (
    ModificadorConstantesUsuario,
)
from zc_suite.simatic.ml.constantes_parser import (
    ParserConstantesUsuario,
)

__all__ = [
    "ModificadorConstantesUsuario",
    "ParserConstantesUsuario",
]
