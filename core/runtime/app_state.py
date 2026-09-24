"""Estado global (AppState).

Single-tenant: asume un unico usuario departamental concurrente. Si
se requiere multi-tenancy, sustituir este Singleton por un contexto
por sesion / usuario.

Diseno extensible:
  - ``AppState`` es TRANSVERSAL: no sabe de areas concretas. Mantiene
    un ``_dispositivos: dict[str, list[Any]]`` indexado por ``hw_type``.
  - Las areas aportan propiedades adicionales (back-compat) via
    ``AreaSpec.contributes_state_extensions``. El area "alimentacion"
    instala ``dispositivos_ed/ea/sa/v/m/m_vf`` como sugar que delegan
    a ``get_devices`` / ``set_devices``.
  - API data-driven: ``get_devices``, ``set_devices``, ``list_hw_types``,
    ``all_devices``, ``reset``, ``__iter__``, ``__contains__``.

``get_app_state()`` itera el ``AreaRegistry`` y, para cada spec con
``contributes_state_extensions``, invoca el callable pasando la instancia
Singleton.
"""
from __future__ import annotations

from threading import Lock
from typing import Any, Iterator


class AppState:
    """Estado global generico (data-driven), no ligado a alimentacion.

    Mantiene las listas de dispositivos indexadas por ``hw_type`` y se
    expone via ``get_app_state()`` (Singleton thread-safe).

    Las listas son mutables para admitir actualizaciones del operario,
    pero los dispositivos individuales son ``frozen=True``: para
    "modificar" uno se crea uno nuevo y se sustituye en la lista.

    Attributes:
        dimensiones: dict[str, Any] con default ``{}``. N_MAX
            (dimensiones de los PlcUserConstant de la tabla de
            configuracion). Se rellena tras un upload de Excel.
            ``{}`` = "el operario aun no ha subido Excel" = preview sin
            cambios N_MAX (renderiza vacio, no explota).
        excel_cache: Any con default ``None``. Cache IT del Excel.
            Anotado ``Any`` para no importar el area desde ``core/``.
            Lo puebla ``POST /api/v1/excel/upload`` tras un load OK.
        excel_path: str | None. Ruta absoluta del Excel cacheado,
            o ``None`` si no hay ninguno. Sirve para invalidacion por
            mtime sin re-leer el cache.
    """

    def __init__(self) -> None:
        # Storage generico (data-driven): unica fuente de verdad.
        self._dispositivos: dict[str, list[Any]] = {}
        self.dimensiones: dict[str, Any] = {}
        self.excel_cache: Any = None
        self.excel_path: str | None = None

    # -- API data-driven (publico, no ligado a alimentacion) -------

    def reset(self) -> None:
        """Vacia todas las listas (util para tests)."""
        for hw in list(self._dispositivos.keys()):
            self.set_devices(hw, [])

    def get_devices(self, hw_type: str) -> list[Any]:
        """Devuelve la lista de dispositivos de ``hw_type``.

        Lista vacia si el tipo aun no tiene entradas.
        """
        return self._dispositivos.get(hw_type, [])

    def set_devices(
        self, hw_type: str, devices: list[Any]
    ) -> None:
        """Sustituye la lista de dispositivos de ``hw_type``.

        Las areas que aportan ``contributes_state_extensions``
        instalan ``state.dispositivos_<hw>`` como sugar que delegan
        a ``get_devices`` / ``set_devices``.
        """
        self._dispositivos[hw_type] = list(devices)

    def list_hw_types(self) -> list[str]:
        """Devuelve los hw_types que tienen al menos un dispositivo cargado."""
        return [hw for hw, lst in self._dispositivos.items() if lst]

    def all_devices(self) -> list[Any]:
        """Aplana todas las listas en una unica lista heterogenea."""
        out: list[Any] = []
        for lst in self._dispositivos.values():
            out.extend(lst)
        return out

    def __iter__(self) -> Iterator[tuple[str, list[Any]]]:
        """Permite iterar ``for hw, devices in state: ...``."""
        return iter(self._dispositivos.items())

    def __contains__(self, hw_type: str) -> bool:
        return hw_type in self._dispositivos

    # -- Magic para inspeccion / debugging --------------------------

    def __repr__(self) -> str:
        counts = {
            hw: len(lst) for hw, lst in self._dispositivos.items() if lst
        }
        return f"AppState(dispositivos={counts})"


# -- Singleton thread-safe (inicializacion perezosa) ---------------------


_state: AppState | None = None
_state_lock: Lock = Lock()


def get_app_state() -> AppState:
    """Devuelve la instancia Singleton de ``AppState`` (thread-safe).

    Tras crear el Singleton, invoca el ``contributes_state_extensions``
    de cada area registrada para que pueda aportar properties legacy
    sobre la CLASE ``AppState`` (con efecto en todas las instancias
    presentes y futuras). El hook se ejecuta una sola vez por proceso:
    instalarlo en cada llamada seria redundante y gastaria un ``setattr``
    por acceso.
    """
    global _state
    if _state is None:
        with _state_lock:
            if _state is None:
                _state = AppState()
                from core.composition.app_area_registry import AreaRegistry
                for spec in AreaRegistry.discover().all():
                    if spec.contributes_state_extensions is not None:
                        spec.contributes_state_extensions(_state)
    return _state


__all__ = ["AppState", "get_app_state"]
