"""Router de areas: catalogo (``GET /areas``) y manifest (``GET /areas/{id}/manifest``).

Este router es **trasversal** y NO conoce areas especificas. Lee del
``AreaSpec`` registry (``core.application.area_registry``) para el
catalogo y del modulo ``areas.{area_id}.manifest`` para el manifest.

Endpoints:
  - ``GET /api/v1/areas`` -> ``list[dict]`` con las areas
    operativas (``{ key, label, icon, available, description? }``).
  - ``GET /api/v1/areas/{area_id}/manifest`` -> manifest JSON del
    area. **404** si el area no esta registrada.

Decision de diseno (importante):
  El **manifest NO es JS ejecutado en el servidor**. Es un
  ``dict`` Python serializado a JSON. Esto evita meter ``js2py`` /
  ``PyExecJS`` / etc. en el .exe (prohibido: solo ``core.worker``
  carga el SDK de Siemens). La SPA recibe el dict y luego resuelve
  los loaders (``import(url)``) en el navegador, igual que hacia el
  ``area-loader.js`` del legacy.

Convenciones (.clinerules §5, §6, §9; AGENTS.md):
  - Type hints en todas las firmas.
  - ``from __future__ import annotations``.
  - Los handlers devuelven ``dict`` o ``list[dict]`` (FastAPI
    serializa a JSON).
  - El router NO inyecta dependencias: el registry es global
    (single-tenant, .clinerules §11). Si en el futuro hay multi-tenant,
    se migra a ``Depends(get_area_registry)``.
"""
from __future__ import annotations

import importlib
from typing import Any

from fastapi import APIRouter, HTTPException

from core.application.area_registry import get_areas

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────
#  GET /areas
# ─────────────────────────────────────────────────────────────────────


@router.get("/areas")
async def list_areas() -> list[dict[str, Any]]:
    """Catalogo de areas operativas.

    Returns:
        Lista de ``{ key, label, icon, available, description? }``.
        ``description`` solo aparece si el ``AreaSpec.description``
        no esta vacio (omitido del JSON para mantener el payload
        limpio cuando el area no aporta copy).

    Note:
        El orden de la lista refleja el orden de registro en
        ``core/web/app.py::create_app()``. La SPA pinta las cards
        en ese orden.
    """
    out: list[dict[str, Any]] = []
    for a in get_areas():
        item: dict[str, Any] = {
            "key": a.key,
            "label": a.label,
            "icon": a.icon,
            "available": a.available,
        }
        # description es opcional: solo aparece si no esta vacio.
        if a.description:
            item["description"] = a.description
        out.append(item)
    return out


# ─────────────────────────────────────────────────────────────────────
#  GET /areas/{area_id}/manifest
# ─────────────────────────────────────────────────────────────────────


@router.get("/areas/{area_id}/manifest")
async def get_manifest(area_id: str) -> dict[str, Any]:
    """Manifest del area: shape de los componentes frontend + loaders.

    El manifest es un ``dict`` Python que vive en
    ``areas.{area_id}.manifest`` (modulo Python, NO ``.js``). Lo
    cargamos con ``importlib.import_module`` y llamamos a su
    funcion ``build()``.

    Returns:
        ``{ id, label, icon, components, loaders }`` donde:
          - ``components``: ``{ sidebar, landing, views }``
            (shape del frontend, no se ejecuta en el servidor).
          - ``loaders``: ``{ nombre_componente: url_absoluta.js }``.
            Las URLs son **relativas al root** (``/areas/...``) para
            que el ``area-loader.js`` (Agente A) pueda hacer
            ``import(url)`` directamente.

    Raises:
        HTTPException 404: si el area no esta registrada O si el
            modulo ``areas.{area_id}.manifest`` no existe o no
            expone ``build()``. Mapeamos todos los errores de carga
            a 404 para no filtrar detalles internos al cliente.
    """
    # 1) Verificar que el area esta registrada. Si no, 404 antes
    #    de intentar importar el modulo (mensaje claro).
    if not any(a.key == area_id for a in get_areas()):
        raise HTTPException(
            status_code=404, detail=f"Area '{area_id}' no encontrada"
        )

    # 2) Importar el modulo del manifest. Si falla (cualquier
    #    excepcion), 404: no queremos exponer el stack al cliente
    #    ni diferenciar "no existe" de "fallo al cargar".
    try:
        mod = importlib.import_module(f"areas.{area_id}.manifest")
    except Exception as exc:  # noqa: BLE001 - cualquier error -> 404
        raise HTTPException(
            status_code=404,
            detail=f"Area '{area_id}' no encontrada: {exc}",
        ) from exc

    # 3) Llamar a ``build()``. Si la funcion no existe o lanza,
    #    500 generico (esto SI es un bug del desarrollador del area).
    build = getattr(mod, "build", None)
    if build is None or not callable(build):
        raise HTTPException(
            status_code=500,
            detail=(
                f"areas.{area_id}.manifest no expone build() "
                "callable"
            ),
        )
    try:
        manifest = build()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail=f"build() del manifest de '{area_id}' fallo: {exc}",
        ) from exc

    # 4) Validacion minima del shape. El manifest TIENE que ser un
    #    ``dict`` con al menos ``id``, ``label`` e ``icon`` para que
    #    la SPA pueda hacer routing. Si no, 500.
    if not isinstance(manifest, dict):
        raise HTTPException(
            status_code=500,
            detail=(
                f"build() del manifest de '{area_id}' retorno "
                f"{type(manifest).__name__}, esperaba dict"
            ),
        )
    for required_key in ("id", "label", "icon", "components", "loaders"):
        if required_key not in manifest:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"build() del manifest de '{area_id}' no incluye "
                    f"clave requerida '{required_key}'"
                ),
            )

    return manifest
