"""Routers web del área de alimentación (FastAPI).

Mueve los 3 routers específicos de alimentación del shell web a este
paquete. El shell (``interfaces/web_server/app.py``) los descubre
vía ``AreaRegistry.for_each("contributes_routers", app=app)``, NO
los importa directamente.

Routers aportados:
  - ``alimentacion_router``: ``/api/v1/alimentacion/aplicar-comentarios-disp``
  - ``sync_router``:         ``/api/v1/sync/{preview,commit}``
  - ``excel_router``:        ``/api/v1/excel/upload``

El shell sigue montando los routers comunes (``portal``,
``areas``, ``catalog``, ``diagnostics``) desde
``interfaces/web_server/routers/``; aquí solo se aportan los
específicos del área.
"""
from __future__ import annotations

from fastapi import FastAPI

from areas.alimentacion.interfaces.web.alimentacion import (
    router as alimentacion_router,
)
from areas.alimentacion.interfaces.web.excel import (
    router as excel_router,
)
from areas.alimentacion.interfaces.web.sync import (
    router as sync_router,
)


__all__ = ["register_routers"]


def register_routers(app: FastAPI) -> None:
    """Monta los 3 routers específicos del área en ``app``.

    Llamado por el shell web vía
    ``AreaRegistry.discover().for_each("contributes_routers", app=app)``.
    El orden de ``include_router`` es estable (alfabético) y los
    prefijos son disjuntos, así que el orden respecto a los routers
    comunes del shell no afecta al routing.
    """
    app.include_router(alimentacion_router)
    app.include_router(excel_router)
    app.include_router(sync_router)
