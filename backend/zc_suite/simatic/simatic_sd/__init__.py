"""Helpers para trabajar con archivos SimaticSD.

Funciones puras (sin estado) para:

- generar IDs MLC unicos (``generador_mlc``)
- actualizar comentarios de arrays en DBs (``actualizador_comentarios_array``)

Este paquete es **offline**: no importa ``siemens_tia_scripting``.
"""
from __future__ import annotations

from zc_suite.simatic.simatic_sd.actualizador_comentarios_array import (
    ResultadoArray,
    comentarios_actuales,
    confirmar_comentarios_array,
    indices_de_array,
)
from zc_suite.simatic.simatic_sd.generador_mlc import (
    ids_mlc_existentes,
    mapa_mlc,
    siguiente_id_mlc,
)

__all__ = [
    "ResultadoArray",
    "comentarios_actuales",
    "confirmar_comentarios_array",
    "ids_mlc_existentes",
    "indices_de_array",
    "mapa_mlc",
    "siguiente_id_mlc",
]
