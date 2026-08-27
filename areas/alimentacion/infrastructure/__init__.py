"""Capa de infraestructura del área Alimentación (Bounded Context).

Adaptadores específicos del área a formatos externos, modificadores
SimaticML offline y utilidades SD (Source Documents) que operan
sobre los modelos de dominio del área.

Tras PR 2, esta capa contiene:
  - ``parsers/`` — adaptadores de Excel corporativo.
  - ``config_defaults.py`` — defaults defensivos del ConfigManager
    que el área aporta para configs legacy (N_MAX, carpetas TIA,
    tabla global).

Los modificadores SD (``disp_comment_updater``, ``disp_mlc_registry``)
siguen en ``infrastructure/alimentacion/sd/`` y se migrarán a esta
carpeta en PR 3 junto con el refactor del ``worker_tia.py``.

Restricción arquitectónica: este paquete es OFFLINE; no importa
``siemens_tia_scripting``.
"""
