"""Bounded Context: Alimentación.

Paquete autocontenido que aporta al core, en este PR 2 + 4:
  - Modelos de dominio (Dispositivo, DispED/EA/SA/V/M/M_VF,
    DimensionesDispositivos) en ``domain/models/dispositivos.py``.
  - Catálogo de presentación del área (``build_catalog``) en
    ``domain/catalog.py``, consumido por ``GET /api/v1/catalog``.
  - Casos de uso de sync de dispositivos y comentarios en
    ``application/use_cases/``.
  - Parser de Excel corporativo en
    ``infrastructure/parsers/alimentacion_excel_parser.py``.
  - Back-compat de las 6 properties legacy en ``AppState`` vía
    ``application/state_extensions.install`` (reemplaza al parche
    de transición de PR 1).
  - Defaults defensivos del ``ConfigManager`` vía
    ``infrastructure/config_defaults.install`` (N_MAX legacy,
    tabla global, carpetas TIA), aplicados solo al bloque
    ``departments["alimentacion"]`` y solo si faltan en el JSON.
  - **PR 4** — 3 routers FastAPI (``alimentacion``, ``sync``,
    ``excel``) en ``interfaces/web/``, montados por el shell web
    vía ``AreaRegistry.for_each("contributes_routers", app=app)``.

En PR 3, 5, 6 este módulo añadirá a la ``AREA_SPEC``:
  - ``contributes_tia_commands``     (PR 3, ``infrastructure/tia/extra_commands.py``)
  - ``contributes_frontend_manifest``(PR 5, ``frontend/manifest.js``)
  - ``contributes_mcp_tools``       (PR 6, ``interfaces/mcp/tools.py``)

Hasta entonces, esos ``contributes_*`` quedan como ``None``: el
área no aporta esos puntos y el core no intenta invocarlos.
"""
from __future__ import annotations

from areas.alimentacion.application.state_extensions import (
    install as install_state,
)
from areas.alimentacion.domain.catalog import build_catalog as build_alim_catalog
from areas.alimentacion.infrastructure.config_defaults import (
    install as install_defaults,
)
from areas.alimentacion.interfaces.web import register_routers
from core.application.area_registry import AreaSpec


AREA_SPEC = AreaSpec(
    id="alimentacion",
    label="Alimentación",
    icon="🍞",
    config_block="alimentacion",
    # ── Implementados en PR 2 ──────────────────────────────────────
    contributes_state_extensions=install_state,
    contributes_config_defaults=install_defaults,
    contributes_catalog=build_alim_catalog,
    # ── Implementado en PR 4 ──────────────────────────────────────
    contributes_routers=register_routers,
    # ── Pendientes (None hasta PR 3/5/6) ──────────────────────────
    # PR 3: contributes_tia_commands = register_tia (extra_commands.py)
    # PR 5: contributes_frontend_manifest = build_manifest (frontend/manifest.js)
    # PR 6: contributes_mcp_tools = register_mcp (interfaces/mcp/tools.py)
    contributes_tia_commands=None,
    contributes_mcp_tools=None,
    contributes_frontend_manifest=None,
)


__all__ = ["AREA_SPEC"]
