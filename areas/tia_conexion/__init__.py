"""Area ``tia_conexion`` — Conexion con TIA Portal (Fase 3).

Esta es la **primera area operativa** del greenfield. Su unico
proposito en Fase 3 es servir como "Hola Mundo" end-to-end:
  - Aparece en el catalogo ``GET /api/v1/areas``.
  - Aporta un manifest con un componente ``ConexionTIAView`` que
    la SPA importa dinamicamente.
  - La vista usa el FB transversal ``FB_ConexionTIA`` (registrado
    en ``core.plc.plc`` durante Fase 1) para conectar / desconectar
    contra TIA Portal.

Importante:
  - Esta area **NO** aporta FBs propios. ``FB_ConexionTIA`` vive
    en ``core/plc/plc.py`` por ser transversal (otras areas futuras
    tambien necesitan attach/detach). El ``register_plc()`` del area
    queda vacio por convencion (ver AGENTS.md §5).
  - El router ``/api/v1/areas`` se monta UNA sola vez en
    ``core/web/app.py::create_app()``, no por area. Esta funcion
    ``register()`` solo se ocupa de la entrada del Catalogo.

Ver AGENTS.md §5 para el contrato completo de las areas.
"""
from __future__ import annotations

from fastapi import FastAPI

from core.application.area_registry import AreaSpec, register as register_area
from core.plc.plc import Engine

# ─────────────────────────────────────────────────────────────────────
#  Especificacion del area
# ─────────────────────────────────────────────────────────────────────


AREA_SPEC = AreaSpec(
    key="tia_conexion",
    label="Conexion TIA",
    icon="🔌",
    available=True,
    description=(
        "Attach / detach con TIA Portal. Vista de diagnostico del "
        "worker y de los PLCs del proyecto activo."
    ),
)


# ─────────────────────────────────────────────────────────────────────
#  Hook de registro (llamado por core/web/app.py::create_app)
# ─────────────────────────────────────────────────────────────────────


def register(engine: Engine, app: FastAPI) -> None:
    """Registra el area en el sistema. **Llamado una sola vez al
    arrancar la app** desde ``core/web/app.py::create_app``.

    Args:
        engine: el Engine transversal (``core.plc.plc.ENGINE``). Se
            pasa para que areas futuras con FBs propios puedan
            registrarlos con ``engine.register_fb(name, fb)``. En
            esta area **no se usa** (``FB_ConexionTIA`` ya esta
            registrado en el ``lifespan`` de Fase 1).
        app: la instancia de FastAPI. Se pasa para que areas con
            routers especificos puedan hacer
            ``app.include_router(...)``. En esta area no se usa
            (el router ``/api/v1/areas`` se monta una sola vez
            en ``create_app``, no por area).

    Comportamiento:
        1. Llama a ``register_plc()`` del area (vacío en Fase 3).
        2. Anade el ``AreaSpec`` al Catalogo (registry).
        3. NO monta routers especificos: el endpoint
           ``/api/v1/areas`` es transversal.
    """
    # 1) Hook para FBs / DBs del area. Vacio en Fase 3 (los FBs
    #    trasversales como ``FB_ConexionTIA`` ya estan registrados
    #    en el ``lifespan`` de Fase 1).
    from .plc import register_plc
    register_plc(engine)

    # 2) Registrar el AreaSpec en el Catalogo.
    register_area(AREA_SPEC)

    # 3) ``app`` no se usa en esta fase. La firma lo incluye por
    #    contrato (AGENTS.md §5: "register(engine, app) -> None")
    #    para que areas futuras con routers especificos no
    #    necesiten tocar ``core/web/app.py``.
    _ = app  # silence unused-argument lint; el parametro es del contrato
