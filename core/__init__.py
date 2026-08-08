"""Capa de Dominio (Core).

Modelos de dominio puros: entidades, value objects, dataclasses y reglas
de negocio. Esta capa es ESTRICTAMENTE PURA y no puede depender de:

- ``siemens_tia_scripting`` (motor OT de TIA Portal).
- ``infrastructure.*`` (capa de infraestructura).
- ``interfaces.*`` (capa de presentación).

Únicamente puede importar de la stdlib y de tipos primitivos.
"""
