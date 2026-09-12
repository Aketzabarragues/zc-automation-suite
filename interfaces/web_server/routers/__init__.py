"""Routers Flask de la capa web (Fase 4 / DA-014, sept-2026).

Solo blueprints del shell (comunes a todas las áreas). Los routers
específicos de cada Bounded Context viven en
``areas/<area>/interfaces/web/`` y los monta el shell vía
``AreaRegistry.for_each("contributes_routers", app=app)`` desde
``interfaces/web_server/app_flask.py``.

Cada submódulo expone un ``Blueprint`` independiente que se ensambla
en ``interfaces/web_server/app_flask.py::create_app``. Los blueprints
NO importan estado global: las dependencias se reciben vía
``current_app.config["_LAZY_*"]`` (lazy resolvers parametrizados en
create_app).

Histórico:
  - Hasta sept-2026 existían 7 routers FastAPI equivalentes
    (``areas.py``, ``area_manifests.py``, ``catalog.py``,
    ``diagnostics.py``, ``plc.py``, ``portal.py``, ``tia_connection.py``).
    Se borraron en Fase A (4.N10) tras migrar a Flask + OB1.

Convenio de naming:
  - El sufijo ``_ob1`` se eliminara en una fase posterior del cleanup
    cuando el equipo valide que los blueprints no tienen duplicados.
"""
from __future__ import annotations

__all__: list[str] = []
