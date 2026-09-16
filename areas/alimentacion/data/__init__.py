"""Data Blocks (DBs) del área de alimentación.

Los DBs del área son data pura: dataclasses con campos primitivos (o
``Any`` cuando la SPA no necesita introspección), aptas para
serializarse a dict y emitirse por SSE al frontend.

Convención (acordada con el operario):
  - ``data_<Nombre>.py``: el nombre del archivo usa PascalCase
    después del guion bajo para reflejar la clase que contiene
    (p.ej. ``data_Dispositivos.py`` contiene ``DataDispositivos``).
  - ``@dataclass(frozen=False)``: los campos son reasignables, con
    ``default_factory`` para colecciones.
  - Sin I/O, sin dependencias de TIA. Lógica pura.
  - Si el DB debe ser reactivo en el frontend, se serializa a
    dict en el snapshot SSE via ``to_dict()``.
  - ``frozen=False`` por defecto (mutación in-place vía
    asignación directa o métodos ``update_*`` cuando convenga).

Tests en ``tests/areas/alimentacion/data/test_data_<Nombre>.py``.
"""
