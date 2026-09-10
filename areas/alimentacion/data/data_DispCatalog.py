"""areas.alimentacion.data.data_DispCatalog — Data Block del catalogo de dispositivos.

Fase 3, paso 3.2.1.  Migrado de ``areas/alimentacion/domain/disp_catalog.py``.
Representa el payload completo del endpoint ``GET /api/v1/catalog`` como
**data pura** (sin comportamiento).  El legacy mantiene las constantes
globales (``_CANONICAL_TO_CLASS``, ``COLUMN_LABELS``, ``MONO_COLUMNS``)
y las funciones (``build_catalog``, ``build_device_tabs``,
``build_nmax_view``, ``get_columns_for``, ``get_disp_class``,
``get_model_columns_map``) hasta Fase 4 (DA-006 del plan).

El wiring final (DA-005.5) decidira si este DB se rellena
directamente desde ``ConfigManager`` en el router, o si se mantiene
un ``DataDispCatalog`` sincronizado releyendo del legacy.

Campos (shape estable del endpoint ``/api/v1/catalog``):
  - ``device_tabs`` (list[dict[str, str]]): ``[{hw_type, canonical,
    label}, ...]``.  Orden: el de declaracion en ``Dispositivos`` del
    config (preserva el orden historico: ``ed/ea/sa/v/m/m_vf``).
  - ``nmax`` (list[dict[str, str]]): ``[{name, label}, ...]`` para
    las cards de N_MAX.
  - ``model_columns`` (dict[str, list[str]]): ``{canonical:
    [field_name, ...], ...}`` con las columnas visibles de cada
    dataclass de dispositivo (filtra ``cfg_*``).
  - ``col_labels`` (dict[str, str]): ``{col_name: "Label humano"}``
    para los encabezados de la SPA.
  - ``mono_cols`` (list[str]): nombres de campo que se renderizan
    en ``font-mono`` (identificadores unicos).

Migracion:
  - Renombrado de las funciones del legacy a un dataclass con los
    5 campos del payload.  El legacy se mantiene hasta Fase 4.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=False)
class DataDispCatalog:
    """Snapshot del catalogo de dispositivos para la SPA.

    Instanciar con ``DataDispCatalog()`` da un catalogo vacio
    valido.  Los campos se rellenan en el wiring final de Fase 3
    (DA-005.5) leyendo del ``ConfigManager`` y/o del legacy
    ``disp_catalog.build_catalog``.
    """

    device_tabs: list[dict[str, str]] = field(default_factory=list)
    nmax: list[dict[str, str]] = field(default_factory=list)
    model_columns: dict[str, list[str]] = field(default_factory=dict)
    col_labels: dict[str, str] = field(default_factory=dict)
    mono_cols: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serializa a dict primitivo (compatible JSON / IPC / SSE).

        Hace copia defensiva de las colecciones para evitar que
        mutaciones del caller contaminen el estado del DB.
        """
        return {
            "device_tabs": [dict(tab) for tab in self.device_tabs],
            "nmax": [dict(n) for n in self.nmax],
            "model_columns": {
                canon: list(cols) for canon, cols in self.model_columns.items()
            },
            "col_labels": dict(self.col_labels),
            "mono_cols": list(self.mono_cols),
        }
