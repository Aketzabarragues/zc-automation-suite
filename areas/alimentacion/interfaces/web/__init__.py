"""Routers web del área de alimentación (FastAPI).

Mueve los routers específicos de alimentación del shell web a este
paquete. El shell (``interfaces/web_server/app.py``) los descubre
vía ``AreaRegistry.for_each("contributes_routers", app=app)``, NO
los importa directamente.

Routers aportados:
  - ``alimentacion_router``: ``/api/v1/alimentacion/aplicar-comentarios-disp``
  - ``excel_router``:        ``/api/v1/excel/upload``
  - ``plc_blocks_router``:   ``/api/v1/plcs/<plc>/blocks`` y ``/refresh``
  - ``procesos_router``:     ``/api/v1/procesos/sync/{preview,commit}``
  - ``sync_router``:         ``/api/v1/sync/{preview,commit}``

El shell sigue montando los routers comunes (``portal``,
``areas``, ``catalog``, ``diagnostics``) desde
``interfaces/web_server/routers/``; aquí solo se aportan los
específicos del área.
"""
from __future__ import annotations

from fastapi import FastAPI

from areas.alimentacion.interfaces.web.disp_comentarios import (
    router as alimentacion_router,
)
from areas.alimentacion.interfaces.web.excel import (
    router as excel_router,
)
from areas.alimentacion.interfaces.web.plc_blocks import (
    router as plc_blocks_router,
)
from areas.alimentacion.interfaces.web.proc_sync import (
    router as procesos_router,
)
from areas.alimentacion.interfaces.web.disp_sync import (
    router as sync_router,
)


__all__ = ["register_routers"]


def register_routers(app: FastAPI) -> None:
    """Monta los 5 routers específicos del área en ``app``.

    Llamado por el shell web vía
    ``AreaRegistry.discover().for_each("contributes_routers", app=app)``.
    El orden de ``include_router`` es estable (alfabético) y los
    prefijos son disjuntos, así que el orden respecto a los routers
    comunes del shell no afecta al routing.
    """
    app.include_router(alimentacion_router)
    app.include_router(excel_router)
    app.include_router(plc_blocks_router)
    app.include_router(procesos_router)
    app.include_router(sync_router)
