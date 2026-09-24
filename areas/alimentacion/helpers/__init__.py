"""Capa de infraestructura del área Alimentación (Bounded Context).

Adaptadores específicos del área a formatos externos, modificadores
SimaticML offline y utilidades SD (Source Documents) que operan
sobre los modelos de dominio del área.

Esta capa contiene:
  - ``build_cache.py`` — entrada única del workdir layout (DispLayout +
    ProcDbLayout).
  - ``config_defaults.py`` — defaults defensivos del ConfigManager
    que el área aporta para configs legacy (N_MAX, carpetas TIA,
    tabla global).
  - ``excel/`` — adaptadores de Excel corporativo (parsers + loaders).
  - ``disp/`` — modificadores SimaticML y modificadores SD de
    dispositivos.
  - ``proc/`` — modificadores SimaticML y modificadores SD de
    procesos.

Restricción arquitectónica: este paquete es OFFLINE; no importa
``siemens_tia_scripting``.
"""
