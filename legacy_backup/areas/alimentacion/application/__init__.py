"""Capa de aplicación del área Alimentación (Bounded Context).

Casos de uso específicos del departamento de alimentación
(sync de dispositivos, sync de comentarios, etc.) y helpers de
apoyo (``disp_slot_map_builder``).

Esta capa NO importa ``siemens_tia_scripting`` (offline-first).
Toda interacción con TIA Portal pasa por ``TIAProcessGateway`` vía
inyección de dependencias.

El área se autoregistra con un ``AREA_SPEC`` declarado en el
``__init__.py`` raíz (``areas/alimentacion/__init__.py``).
"""
