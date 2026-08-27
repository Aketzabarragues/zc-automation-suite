"""Router Catalog: ``/api/v1/catalog``.

Endpoint de sólo lectura que expone el **catálogo de presentación**
que consume la SPA para renderizar las pestañas de dispositivo y
las cards de N_MAX, evitando hardcoding en JS.

Lo que se expone (ver ``areas.alimentacion.domain.catalog.build_catalog``):

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

from areas.alimentacion.domain.catalog import build_catalog
from core.infrastructure.config_manager import ConfigManager
from interfaces.web_server.dependencies import get_config_manager


router = APIRouter(prefix="/api/v1", tags=["Catalog"])


@router.get("/catalog")
async def get_catalog(
    config_manager: ConfigManager = Depends(get_config_manager),
) -> dict[str, Any]:
    """Devuelve el catálogo de presentación (device_tabs, nmax, ...).

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
    return {
        "ok": True,
        "catalog": build_catalog(config_manager),
    }


__all__ = ["router"]
