"""Subdominios del área (agrupación por departamento).

Tras PR 2, este paquete queda como **shim de back-compat** para los
símbolos ``AreaInfo`` y ``ListAreasUseCase`` que originalmente vivían
en ``application.areas.catalog``. La implementación se ha movido a
``core.application.area_registry`` (donde reside el ``AreaSpec`` y
el ``AreaRegistry`` que la origina).

Las áreas concretas ahora viven en ``areas/<area>/`` siguiendo el
layout de Bounded Contexts:

  - areas/alimentacion/      (dominio, application, infrastructure)
  - areas/<futura>/          (idem)

Los tests y código existente pueden seguir importando
``from application.areas import AreaInfo, ListAreasUseCase`` sin
modificación; el shim re-exporta desde el core.
"""
from core.application.area_registry import AreaInfo, ListAreasUseCase

__all__ = ["AreaInfo", "ListAreasUseCase"]
