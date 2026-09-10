"""core.data — Data Blocks (DBs) transversales del refactor.

Fase 3, seccion 3.1.  Reemplaza progresivamente ``core/models/``
(los modelos "puros" se migran a este paquete con prefijo
``data_``).  El cambio es de ubicacion: la API se mantiene
back-compat con los consumidores existentes (router, SPA via
SSE) durante la migracion in-place.

Convencion:
  - ``data_<nombre>.py`` con ``@dataclass`` inmutable o casi.
  - Sin I/O, sin dependencias de TIA.  Logica pura.
  - Tests en ``tests/core/test_data_<nombre>.py``.

Los Data Blocks del area (3.2) van en
``areas/alimentacion/data/data_*.py``.
"""
