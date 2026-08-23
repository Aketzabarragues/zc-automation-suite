"""Subdominios del área (agrupación por departamento).

Los casos de uso de cada área viven en ``application/areas/<area>/use_cases/``.
Por ejemplo:

  - application/areas/alimentacion/use_cases/sync_disp_alimentacion.py
  - application/areas/alimentacion/use_cases/diff_constants.py

Catálogo de áreas (genérico, departamento-agnóstico)
-----------------------------------------------------------
Las clases ``AreaInfo`` y ``ListAreasUseCase`` se re-exportan desde
``application.areas.catalog`` para mantener la compatibilidad con el
contrato público (tests, otros módulos) que importaban
``from application.areas import AreaInfo, ListAreasUseCase`` cuando
``application.areas`` era un módulo y no un paquete.
"""
from application.areas.catalog import AreaInfo, ListAreasUseCase

__all__ = ["AreaInfo", "ListAreasUseCase"]
