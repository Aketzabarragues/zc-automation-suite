"""Router Catalog: ``/api/v1/catalog``.

Endpoint de sólo lectura que expone el **catálogo de presentación**
que consume la SPA para renderizar las pestañas de dispositivo y
las cards de N_MAX, evitando hardcoding en JS.

El catálogo se compone dinámicamente vía el hook
``AreaSpec.contributes_catalog`` (ver ``core/application/area_registry.py``):
cada área aporta su fragmento y el shell los fusiona. Esto da
paridad con el resto de extension points (``contributes_routers``,
``contributes_mcp_tools``, ``contributes_frontend_manifest``,
``contributes_tia_commands``) y permite que una nueva área aporte
catálogo sin tocar este shell.

Hoy el área de alimentación (ver
``areas.alimentacion.domain.catalog.build_catalog``) aporta estas
claves:

  - ``device_tabs``     ``[{hw_type, canonical, label}, ...]``
  - ``nmax``            ``[{name, label}, ...]``
  - ``model_columns``   ``{canonical: [field_name, ...], ...}``
  - ``col_labels``      ``{col_name: "Label humano", ...}``
  - ``mono_cols``       ``[col_name, ...]``

Este endpoint es la **fuente única de verdad** para los datos de
presentación del frontend: añadir un nuevo ``hw_type`` al
``config.json`` o un nuevo ``N_MAX`` al ``n_max_catalog`` se
refleja automáticamente en la SPA sin tocar JS.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from core.application.area_registry import AreaRegistry
from core.infrastructure.config_manager import ConfigManager
from interfaces.web_server.dependencies import get_config_manager


router = APIRouter(prefix="/api/v1", tags=["Catalog"])


@router.get("/catalog")
async def get_catalog(
    config_manager: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    """Devuelve el catálogo de presentación (device_tabs, nmax, ...).

    Itera las áreas vía ``AreaRegistry`` y fusiona los diccionarios
    que cada una aporta en su hook ``contributes_catalog``. El
    shell NO conoce áreas concretas: si una futura área declara
    ``contributes_catalog`` en su ``AreaSpec``, su salida aparece
    automáticamente en este endpoint sin tocar este router.

    Si dos áreas aportan claves con el mismo nombre, gana la
    última en orden de discovery de ``AreaRegistry``. El contrato
    actual del hook (``(cm: ConfigManager) -> dict[str, Any]``)
    se respeta intacto: este router no impone mutación de
    estado, solo hace merge de los payloads.

    La SPA lo llama una vez al arrancar (en ``main.js``) y lo
    cachea en ``store.catalog``. Si en el futuro la SPA
    quisiera refrescarlo sin recargar, se añade un botón
    "Refrescar catálogo" que llame a este mismo endpoint.

    Respuesta (shape estable, la SPA hace fallback por clave
    ausente si el backend aún no la expone):

        {
          "ok": true,
          "catalog": {
            "device_tabs":   [...],
            "nmax":          [...],
            "model_columns": {...},
            "col_labels":    {...},
            "mono_cols":     [...]
          }
        }
    """
    merged: dict[str, Any] = {}
    for spec in AreaRegistry.discover().all():
        if spec.contributes_catalog is None:
            continue
        partial = spec.contributes_catalog(config_manager)
        if isinstance(partial, dict):
            merged.update(partial)
    return {"ok": True, "catalog": merged}


__all__ = ["router"]
