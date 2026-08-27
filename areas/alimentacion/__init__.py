"""Bounded Context: Alimentación.

Paquete autocontenido que aporta al core, en este PR 3:
  - Modelos de dominio (Dispositivo, DispED/EA/SA/V/M/M_VF,
    DimensionesDispositivos) en ``domain/models/dispositivos.py``.
  - Catálogo de presentación del área (``build_catalog``) en
    ``domain/catalog.py``, consumido por ``GET /api/v1/catalog``.
  - Casos de uso de sync de dispositivos y comentarios en
    ``application/use_cases/``.
  - Parser de Excel corporativo en
    ``infrastructure/parsers/alimentacion_excel_parser.py``.
  - Modificadores SimaticML offline de comentarios por instancia y
    registro de MLCs en ``infrastructure/sd/``.
  - 6 comandos transaccionales adicionales al ``COMMAND_REGISTRY``
    del worker OT (``update_disp_comments_db_*``) aportados vía
    ``infrastructure/tia/extra_commands.register``. Cableados a
    ``AREA_SPEC.contributes_tia_commands`` y descubiertos al
    arrancar el worker por ``core.infrastructure.tia.command_loader``.
  - Back-compat de las 6 properties legacy en ``AppState`` vía
    ``application/state_extensions.install``.
  - Defaults defensivos del ``ConfigManager`` vía
    ``infrastructure/config_defaults.install``.

En PR 5 y PR 6 este módulo añadirá a la ``AREA_SPEC``:
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
from areas.alimentacion.frontend.manifest import build as build_manifest
from areas.alimentacion.infrastructure.config_defaults import (
    install as install_defaults,
)
from areas.alimentacion.infrastructure.tia.extra_commands import (
    register as register_tia,
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
    # ── Implementado en PR 3 ──────────────────────────────────────
    contributes_tia_commands=register_tia,
    # ── Implementado en PR 4 ──────────────────────────────────────
    contributes_routers=register_routers,
    # ── Implementado en PR 5 (frontend-spa) ────────────────────────
    # Manifest del área para la SPA. Espejo Python de ``manifest.js``
    # (mismo shape, pero con URLs strings en ``loaders`` en vez de
    # ``() => import(...)``). El backend lo serializa a JSON desde el
    # endpoint ``GET /api/v1/areas/<id>/manifest``.
    contributes_frontend_manifest=build_manifest,
    # ── Pendiente (None hasta PR 6) ───────────────────────────────
    # PR 6: contributes_mcp_tools = register_mcp (interfaces/mcp/tools.py)
    contributes_mcp_tools=None,
)


__all__ = ["AREA_SPEC", "register_tia", "build_manifest"]
