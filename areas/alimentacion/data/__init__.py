"""areas.alimentacion.data — Data Blocks (DBs) del area de alimentacion.

Fase 3, seccion 3.2.  Reemplaza progresivamente los modelos y
constructores de ``areas/alimentacion/domain/``.  Los DBs del area
son data pura: dataclasses con campos primitivos (o ``Any`` cuando
la SPA no necesita introspeccion), aptas para serializarse a dict
y emitirse por SSE al frontend.

Convencion (acordada con el operario, sept-2026):
  - ``data_<Nombre>.py``: el nombre del archivo usa PascalCase
    despues del guion bajo para reflejar la clase que contiene
    (p.ej. ``data_Dispositivos.py`` contiene ``DataDispositivos``).
  - ``@dataclass(frozen=False)``: los campos son reasignables, con
    ``default_factory`` para colecciones.
  - Sin I/O, sin dependencias de TIA.  Logica pura.
  - Si el DB debe ser reactivo en el frontend, se serializa a
    dict en el snapshot SSE via ``to_dict()``.
  - ``frozen=False`` por defecto (mutacion in-place via
    asignacion directa o metodos ``update_*`` cuando convenga).

Tests en ``tests/areas/alimentacion/data/test_data_<Nombre>.py``.

Los DBs transversales (3.1) viven en ``core/data/``; los del area
(3.2) viven aqui.
"""
