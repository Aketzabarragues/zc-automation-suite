"""Estado global (AppState).

Single-tenant: asume un unico usuario departamental concurrente. Si
se requiere multi-tenancy, sustituir este Singleton por un contexto
por sesion / usuario.

Conserva los caches del Excel (completo + filtrado por PLC) y el PLC
activo. ``app_cache`` (``core.runtime.app_cache``) es el nuevo
contenedor del proceso; los caches del Excel migraran al a el.
"""
from __future__ import annotations

from threading import Lock
from typing import Any

from core.runtime.app_cache import AppCache


class AppState:
    """Estado global minimo: caches del Excel + PLC activo.

    Attributes:
        excel_path: str | None. Ruta absoluta del Excel cacheado, o
            ``None`` si no hay ninguno. Sirve para invalidacion por
            mtime sin re-leer el cache.
        excel_cache_full: DataExcelCache o ``None``. Cache COMPLETO
            del Excel (datos UI / "definicion programacion"). Nunca
            filtrado; nunca mutado. Lo puebla ``dump_cache_to_state``.
        excel_cache_active: DataExcelCache o ``None``. Cache FILTRADO
            por ``selected_plc`` (datos que consumen los FB). Se
            regenera en cada ``with_plc`` cuando cambia la seleccion.
            Si ``selected_plc == ""`` es identico a ``excel_cache_full``.
        selected_plc: str. Nombre del PLC activo (multi-PLC). Lo
            setea ``with_plc`` cuando el endpoint recibe el plc_name
            del body. ``""`` = "sin filtro" = el cache activo es
            igual al completo.
        app_cache: AppCache. Contenedor del proceso (ver
            ``core.runtime.app_cache``).
    """

    # Class-attribute defaults. Sirven para que ``MagicMock(spec=AppState)``
    # los exponga (spec= solo ve atributos declarados en la clase, no los
    # asignados en __init__). ``__init__`` los reasigna para que cada
    # instancia tenga su propio slot (no se comparta el class-attribute).
    excel_path: str | None = None
    excel_cache_full: Any = None
    excel_cache_active: Any = None
    selected_plc: str = ""
    app_cache: AppCache = AppCache()

    def __init__(self) -> None:
        # Reasignar para tener slots de instancia independientes.
        self.excel_path = None
        self.excel_cache_full = None
        self.excel_cache_active = None
        self.selected_plc = ""
        self.app_cache = AppCache()

    def __repr__(self) -> str:
        return (
            f"AppState(selected_plc={self.selected_plc!r}, "
            f"excel_loaded={self.excel_cache_full is not None})"
        )


# -- Singleton thread-safe (inicializacion perezosa) --------------------


_state: AppState | None = None
_state_lock: Lock = Lock()


def get_app_state() -> AppState:
    """Devuelve la instancia Singleton de ``AppState`` (thread-safe)."""
    global _state
    if _state is None:
        with _state_lock:
            if _state is None:
                _state = AppState()
    return _state


__all__ = ["AppState", "get_app_state"]