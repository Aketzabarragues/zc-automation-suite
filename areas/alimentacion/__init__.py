"""Bounded Context: Alimentación.

Paquete autocontenido que aporta al core:
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
  - 3 routers web en ``interfaces/web/`` (alimentacion, sync, excel)
    cableados a ``contributes_routers``.
  - 4 tools MCP en ``interfaces/mcp/tools.py`` (sync preview/commit,
    aplicar comentarios, upload excel) cableadas a
    ``contributes_mcp_tools``. Dan paridad con los endpoints web:
    LLM y SPA ejecutan los mismos flujos contra los mismos use cases.
  - Manifest del área para la SPA en ``frontend/manifest.js`` y
    su espejo Python ``frontend/manifest.py`` (URLs strings) en
    ``contributes_frontend_manifest``.
  - Back-compat de las 6 properties legacy en ``AppState`` vía
    ``application/state_extensions.install``.
  - Defaults defensivos del ``ConfigManager`` vía
    ``infrastructure/config_defaults.install``.

Los 7 ``contributes_*`` quedan cableados en la ``AREA_SPEC`` definida
abajo: el área aporta TODOS los extension points disponibles hoy.
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
from areas.alimentacion.interfaces.mcp.tools import register as register_mcp
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
    # ── Implementado en PR 6 (backend-api) ────────────────────────
    # 4 tools MCP que dan paridad con los endpoints web del área.
    # Las tools delegan en los mismos use cases que los routers:
    # si cambia un flujo, cambia en un único sitio.
    contributes_mcp_tools=register_mcp,
)


__all__ = ["AREA_SPEC", "register_tia", "register_mcp", "build_manifest"]
