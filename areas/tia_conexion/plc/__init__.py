"""PLC layer del area ``tia_conexion``.

Por convencion del proyecto (AGENTS.md §5), cada area expone
``register_plc(engine, worker_bridge) -> None`` que crea instancias
de sus FBs/DBs y las registra en el Engine. Esta funcion la llama
``areas.<area>.__init__.register()`` durante el ``create_app``.

Estado en Fase 3 (2026-09):
  - Esta area **NO** aporta FBs propios en Fase 3. El unico FB
    relevante (``FB_ConexionTIA``) es **trasversal** y vive en
    ``core/plc/plc.py`` porque cualquier otra area futura tambien
    necesitara attach/detach con TIA Portal.
  - Esta area **NO** aporta DBs propias. La ``DB_EstadoConexion``
    trasversal (``core.plc.plc.DB_ESTADO``) ya esta registrada en
    el singleton del Engine.
  - Por lo tanto ``register_plc()`` es un **no-op** que solo
    queda como hook para que Fase 4+ puedan anyadir FBs/DBs
    del area sin tocar ``core/web/app.py``.

Ver AGENTS.md §5 para la justificacion arquitectonica.
"""
from __future__ import annotations

from core.plc.plc import Engine


def register_plc(engine: Engine) -> None:
    """Registra los FBs/DBs del area en el Engine. **No-op en Fase 3.**

    Args:
        engine: el Engine transversal. Se acepta por contrato aunque
            en esta fase no se use (Fase 1 ya registro
            ``FB_ConexionTIA`` y ``DB_EstadoConexion`` en el
            ``lifespan`` de ``core/web/app.py``).

    Comportamiento (Fase 3):
        - No hace nada. El unico FB relevante (``FB_ConexionTIA``)
          es trasversal y se registro en Fase 1.

    Comportamiento esperado (Fase 4+):
        - Crear instancias de los FBs/DBs del area y llamar a
          ``engine.register_fb(name, fb)`` /
          ``engine.register_db(name, db)`` para cada uno.
        - Ejemplo (Fase 4, area de inspeccion):
          ````python
          db = MiDB()
          engine.register_db("mi_area_db", db)
          fb = FB_MiArea(bridge=..., db=db)
          engine.register_fb("MiArea", fb)
          ````
    """
    _ = engine  # silence unused-argument; el parametro es del contrato
