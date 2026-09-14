"""Blueprints Flask del shell (comunes a todas las áreas).

Los routers específicos de cada Bounded Context viven en
``areas/<area>/interfaces/web/`` y los monta el shell vía
``AreaRegistry.for_each("contributes_routers", app=app)`` desde
``core/web_server/app_flask.py``.

Cada submódulo expone un ``Blueprint`` independiente que se ensambla
en ``core/web_server/app_flask.py::create_app``. Las dependencias
se reciben vía ``current_app.config["_LAZY_*"]`` (lazy resolvers).
"""
from __future__ import annotations

__all__: list[str] = []
