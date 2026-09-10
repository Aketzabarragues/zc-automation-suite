"""core.data.data_app_state — Data Block del estado global de la app.

Fase 3, paso 3.1.4.  Migrado de ``core/application/state.py``.  A
diferencia del legacy ``AppState``, este DB representa el estado
como **data pura** (sin comportamiento): los campos son primitivos
o ``Any``, la mutacion es por asignacion directa o via el metodo
conveniente ``set_devices``, y la serializacion a SSE es trivial.

El legacy ``AppState`` mantiene su Singleton ``get_app_state()`` con
``Lock``, su API data-driven (``get_devices`` / ``set_devices`` /
``list_hw_types`` / ``all_devices`` / ``__iter__`` / ``__contains__``
/ ``__repr__``) y la integracion con ``AreaRegistry.contributes_state_extensions``
(las 6 properties ``dispositivos_ed/ea/...`` que el area de
alimentacion pega sobre la clase).  Todo eso es comportamiento de
**aplicacion**, no data, y se conserva intacto hasta Fase 4
(DA-006 del plan).  31 archivos lo siguen importando (use cases,
routers, FBs del area, tests); ninguno de ellos se toca en este
paso.

Campos:
  - ``dispositivos`` (dict[str, list[Any]]): dispositivos indexados
    por ``hw_type``.  Equivalente al ``_dispositivos`` (privado) del
    legacy.  Publico aqui: la SPA ve este dict, no la API.
  - ``dimensiones`` (dict[str, Any]): N_MAX de PlcUserConstants de
    la tabla ``000_Config_Dispositivos``.  Default ``{}`` (dict
    vacio, no ``None``) por el mismo trade-off que documenta el
    legacy: el operario puede pulsar "Generar Prevision" antes de
    subir un Excel, y ``_extract_nmax_diff`` hace ``d.get(name)``
    sobre este slot; si fuera ``None`` reventaria con
    ``'NoneType' object has no attribute 'get'``.
  - ``excel_cache`` (Any): cache IT del Excel.  Anotado ``Any``
    para no importar el area desde ``core/``.  Lo puebla
    ``POST /api/v1/excel/upload`` tras un load OK.  **No se
    serializa** en ``to_dict()``: contiene objetos no-JSON y la
    SPA solo necesita el flag ``excel_loaded``.
  - ``excel_path`` (str | None): ruta absoluta del Excel
    actualmente cacheado.  ``None`` si no hay Excel cargado.

Migracion:
  - Renombrado de ``AppState`` (legacy) a ``DataAppState``.  El
    legacy se mantiene hasta Fase 4 (DA-006).
  - El wiring final con todos los DBs activos (DA-005.5) decidira
    si el snapshot SSE se construye releyendo del ``AppState``
    legacy o manteniendo un ``DataAppState`` sincronizado.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=False)
class DataAppState:
    """Estado de la app como data pura, serializable a SSE.

    Instanciar con ``DataAppState()`` da el estado por defecto
    (sin dispositivos, sin dimensiones N_MAX, sin Excel).  Los
    campos son reasignables (``frozen=False``).
    """

    dispositivos: dict[str, list[Any]] = field(default_factory=dict)
    dimensiones: dict[str, Any] = field(default_factory=dict)
    excel_cache: Any = None
    excel_path: str | None = None

    def set_devices(self, hw_type: str, devices: list[Any]) -> None:
        """Sustituye la lista de dispositivos de ``hw_type``.

        Atajo para el patron habitual del legacy
        ``state.set_devices(hw, devs)``.  Copia la lista para
        evitar aliasing entre el caller y el estado interno.
        """
        self.dispositivos[hw_type] = list(devices)

    def to_dict(self) -> dict:
        """Serializa a dict primitivo (compatible JSON / IPC / SSE).

        ``excel_cache`` se excluye del snapshot (contiene objetos
        no-JSON); seemite el flag ``excel_loaded`` para que la
        SPA sepa si hay un Excel en memoria sin tener que recibir
        su contenido.
        """
        return {
            "dispositivos": {
                hw: list(devs) for hw, devs in self.dispositivos.items()
            },
            "dimensiones": dict(self.dimensiones),
            "excel_loaded": self.excel_cache is not None,
            "excel_path": self.excel_path,
        }
