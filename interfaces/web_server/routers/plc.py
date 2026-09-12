"""Router PLC FBs: ``/api/v1/plc/fb/...``.

Fase 2, paso 2.2.1.  Expone los Function Blocks (FBs) registrados en el
``Engine`` (vía ``core/plc/engine.py``) como endpoints HTTP.  La SPA
puede arrancar y consultar el estado de un FB sin acoplar a la
implementación interna del state machine.

Endpoints:
  - ``POST /api/v1/plc/fb/{name}/start``     arranca el FB con los
    params del body.
  - ``POST /api/v1/plc/fb/{name}/disconnect``  desregistra el FB del
    engine (el engine deja de tickearlo).
  - ``GET  /api/v1/plc/fb/{name}/status``    devuelve el estado
    actual (nStep, is_terminal, error_msg, result).

Reglas arquitectónicas:
  - Cero estado global: el ``Engine`` se obtiene vía
    ``Depends(get_engine)`` (ver ``dependencies.py``).
  - El ``name`` del path mapea a la key usada en
    ``engine.register_fb(name, fb)``.  El Composition Root
    (``app.py``) es quien registra los FBs concretos (SubirExcel,
    ScanPlcBlocks, etc.).
  - El router NO toca ``app.state.engine`` directamente; usa el
    dependency injector.

Wiring pendiente: este router está creado pero ``app.py`` aún NO
lo incluye (regla "Nada de main cambia sin pedir").  El Composition
Root debe añadir las 2 líneas::

    app.state.engine = Engine(tick_period_s=0.1, event_bus=app.state.event_bus)
    # (registrar los 7 FBs concretos aquí)
    app.include_router(plc_router)
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.plc.engine import Engine
from interfaces.web_server.dependencies import get_engine


router = APIRouter(prefix="/api/v1/plc/fb", tags=["PLC FBs"])


class FBStartRequest(BaseModel):
    """Body de ``POST /start``.  ``params`` se splatting al ``start()``
    del FB.  Cada FB acepta sus propios params (ej.
    ``{"plc_name": "S7-1500", "xlsx_path": "..."}``).
    """
    params: dict[str, Any] = {}


class FBStartResponse(BaseModel):
    started: bool
    nStep: int


class FBStatusResponse(BaseModel):
    name: str
    nStep: int
    is_terminal: bool
    error_msg: str | None = None
    result: Any | None = None


@router.post("/{name}/start", response_model=FBStartResponse)
async def start_fb(
    name: str,
    body: FBStartRequest,
    engine: Engine = Depends(get_engine),
) -> FBStartResponse:
    """Arranca el FB registrado bajo ``name``.

    Devuelve 404 si el FB no está registrado.  Devuelve 200 con
    ``started=True`` si el FB pasó de ``n_idle`` a ``nStep=10``.
    Devuelve ``started=False`` si ya estaba activo (idempotente).
    """
    fb = engine.get_fb(name)
    if fb is None:
        raise HTTPException(
            status_code=404,
            detail=f"FB '{name}' no registrado en el engine",
        )
    started = await fb.start(**body.params)
    return FBStartResponse(started=started, nStep=fb.nStep)


@router.post("/{name}/disconnect", status_code=204)
async def disconnect_fb(
    name: str,
    engine: Engine = Depends(get_engine),
) -> None:
    """Desregistra el FB del engine.  Tras esto, el engine deja de
    tickearlo (ya no aparece en ``registered_fb_names()``).

    204 No Content si se desregistró, 404 si no estaba registrado.
    """
    # El engine no expone ``unregister_fb`` aún (Fase 2.0.5 lo dejó
    # fuera).  Implementación minimalista: usamos un método privado
    # del engine vía ``pop()`` sobre el dict, que es la fuente de
    # verdad.
    removed = engine._fbs.pop(name, None) is not None  # noqa: SLF001
    if not removed:
        raise HTTPException(
            status_code=404,
            detail=f"FB '{name}' no registrado en el engine",
        )


@router.get("/{name}/status", response_model=FBStatusResponse)
async def get_fb_status(
    name: str,
    engine: Engine = Depends(get_engine),
) -> FBStatusResponse:
    """Devuelve el estado actual del FB.  Útil para la SPA tras
    arrancar (polling del state machine) o para el operario en
    debugging."""
    fb = engine.get_fb(name)
    if fb is None:
        raise HTTPException(
            status_code=404,
            detail=f"FB '{name}' no registrado en el engine",
        )
    return FBStatusResponse(
        name=name,
        nStep=fb.nStep,
        is_terminal=fb.is_terminal(),
        error_msg=fb.error_msg,
        result=fb.result,
    )
