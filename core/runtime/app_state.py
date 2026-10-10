"""Estado global (AppState).

Single-tenant: asume un unico usuario departamental concurrente. Si
se requiere multi-tenancy, sustituir este Singleton por un contexto
por sesion / usuario.

``AppState`` es un contenedor minimo: solo expone ``app_cache`` (El
container del proceso en ``core.runtime.app_cache``). Los caches del
Excel (completo + filtrado por PLC) y el PLC activo viven dentro del
``AppCache``, accedidos por las funciones puras de
``core.runtime.excel_cache`` y via ``app_cache.selected_plc``.
"""
from __future__ import annotations

from threading import Lock

from core.runtime.app_cache import AppCache


class AppState:
    """Estado global minimo: solo expone ``app_cache``.

    Attributes:
        app_cache: AppCache. Contenedor del proceso (ver
            ``core.runtime.app_cache``).
    """

    # Class-attribute defaults. Sirven para que ``MagicMock(spec=AppState)``
    # los exponga (spec= solo ve atributos declarados en la clase, no los
    # asignados en __init__). ``__init__`` los reasigna para que cada
    # instancia tenga su propio slot (no se comparta el class-attribute).
    app_cache: AppCache = AppCache()

    def __init__(self) -> None:
        # Lazy import: evita ciclo app_state <-> app_cache y garantiza
        # que ``state.app_cache`` es la misma instancia Singleton que
        # ``get_app_cache()``. Asi los FBs (que reciben ``app_cache`` por
        # wiring) escriben en la misma instancia donde las areas se
        # registran en boot.
        from core.runtime.app_cache import get_app_cache
        self.app_cache: AppCache = get_app_cache()

    def __repr__(self) -> str:
        return (
            f"AppState(app_cache={self.app_cache!r})"
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