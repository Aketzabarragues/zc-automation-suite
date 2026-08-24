"""Application Layer - Estado Global (AppState).

WARNING: Arquitectura Single-Tenant. Este estado asume un único usuario
departamental concurrente. Si en el futuro se requiere multi-tenancy,
hay que sustituir este singleton por un contexto por-sesión/usuario.

Modelo **extensible** (Plan: Base extensible para tablas de
dispositivos y N_MAX):

  - Internamente, ``AppState`` mantiene un ``_dispositivos:
    dict[str, list[Dispositivo]]`` indexado por ``hw_type``.
  - Los 6 tipos legacy (``ed/ea/sa/v/m/m_vf``) se exponen como
    **propiedades de back-compat** con sus tipos concretos
    (``list[DispED]``, etc.) para que la SPA, los routers web y los
    tests existentes sigan funcionando sin cambios.
  - Los tipos nuevos (futuros: ``sd/m_sina/tq/tq_ae`` y los que
    vengan) se acceden vía ``state.get_devices(hw_type)`` /
    ``state.set_devices(hw_type, devices)``.
  - ``all_devices()`` aplana todos los tipos en una sola lista.
"""

from __future__ import annotations

from threading import Lock
from typing import Any, Iterator

from core.alimentacion.models.dispositivos import (
    DimensionesDispositivos,
    DispEA,
    DispED,
    DispM,
    DispM_VF,
    DispSA,
    DispV,
    Dispositivo,
)


# Lista canónica (hw_type, attr, lista_tipada) que se usa para:
#  1. Exponer las 6 propiedades de back-compat.
#  2. Sincronizar el dict interno con las propiedades concretas.
#  3. ``reset()`` para vaciar.
_LEGACY_ATTRS: tuple[tuple[str, str, type], ...] = (
    ("ed",   "dispositivos_ed",    DispED),
    ("ea",   "dispositivos_ea",    DispEA),
    ("sa",   "dispositivos_sa",    DispSA),
    ("v",    "dispositivos_v",     DispV),
    ("m",    "dispositivos_m",     DispM),
    ("m_vf", "dispositivos_m_vf",  DispM_VF),
)


def _legacy_attr_for(hw_type: str) -> str | None:
    """Devuelve el nombre del atributo legacy de ``AppState`` para ``hw_type``
    (p.ej. ``"ed"`` → ``"dispositivos_ed"``), o ``None`` si no es un
    tipo legacy.
    """
    for hw, attr, _t in _LEGACY_ATTRS:
        if hw == hw_type:
            return attr
    return None


def _hw_for_legacy_attr(attr_name: str) -> str | None:
    """Devuelve el hw_type legacy para un nombre de atributo, o ``None``."""
    for hw, attr, _t in _LEGACY_ATTRS:
        if attr == attr_name:
            return hw
    return None


class AppState:
    """Estado global del subdominio alimentación.

    Mantiene las listas de dispositivos del departamento y la
    instancia de ``DimensionesDispositivos``. Se expone vía
    ``get_app_state()`` (Singleton thread-safe).

    Las listas son mutables para admitir actualizaciones del operario,
    pero los dispositivos individuales son ``frozen=True`` (no se
    pueden mutar tras su creación; para "modificar" un dispositivo
    se crea uno nuevo y se sustituye en la lista).
    """

    def __init__(self) -> None:
        # ── Storage genérico (data-driven) ────────────────────────────
        # ``_dispositivos`` es la fuente de verdad extensible. Las 6
        # propiedades ``dispositivos_*`` se mantienen sincronizadas
        # con este dict vía ``__setattr__`` y ``__getattribute__``.
        self._dispositivos: dict[str, list[Dispositivo]] = {}
        # ── Dimensiones (cantidades) ────────────────────────────────────
        self.dimensiones: DimensionesDispositivos = DimensionesDispositivos()

    # ── Interceptación de los 6 atributos legacy ──────────────────────

    def __getattribute__(self, name: str) -> Any:
        """Sirve ``dispositivos_ed/ea/sa/v/m/m_vf`` desde ``_dispositivos``.

        Mantiene la API legacy: ``state.dispositivos_ed`` devuelve la
        lista de DispED (tipada en type-checkers pero la runtime ve
        ``list[Dispositivo]``). Si los tipos concretos importan para
        el caller, puede usar ``cast`` o check con ``isinstance``.
        """
        # Evita recursión infinita: ``_dispositivos`` se accede por el
        # camino normal de ``object.__getattribute__``.
        if name in _LEGACY_ATTR_NAMES:
            disp = object.__getattribute__(self, "_dispositivos")
            return disp.get(name_to_hw(name), [])
        return object.__getattribute__(self, name)

    def __setattr__(self, name: str, value: Any) -> None:
        """Sincroniza ``dispositivos_ed = ...`` con ``_dispositivos["ed"]``.

        Si ``name`` es uno de los 6 legacy attrs, actualiza también
        el dict. Si es ``_dispositivos`` o ``dimensiones``, se guarda
        tal cual.
        """
        if name in _LEGACY_ATTR_NAMES:
            disp = object.__getattribute__(self, "_dispositivos")
            disp[name_to_hw(name)] = value
            # No usamos ``object.__setattr__`` aquí: el resto de la
            # clase no expone esos nombres como atributos (viven solo
            # en el dict). Si lo hiciéramos, duplicaríamos la lista.
            return
        object.__setattr__(self, name, value)

    def reset(self) -> None:
        """Vacía todas las listas (útil para tests)."""
        for hw in list(self._dispositivos.keys()):
            self.set_devices(hw, [])

    # ── API data-driven (futuro) ──────────────────────────────────────

    def get_devices(self, hw_type: str) -> list[Dispositivo]:
        """Devuelve la lista de dispositivos de ``hw_type``.

        Retorna lista vacía si el tipo aún no tiene entradas.
        """
        return self._dispositivos.get(hw_type, [])

    def set_devices(
        self, hw_type: str, devices: list[Dispositivo]
    ) -> None:
        """Sustituye la lista de dispositivos de ``hw_type``.

        Para los 6 tipos legacy, las propiedades
        ``state.dispositivos_<hw>`` se actualizan automáticamente
        (vía ``__getattribute__``) para devolver esta misma lista.
        """
        self._dispositivos[hw_type] = list(devices)

    def list_hw_types(self) -> list[str]:
        """Devuelve los hw_types que tienen al menos un dispositivo cargado."""
        return [hw for hw, lst in self._dispositivos.items() if lst]

    def all_devices(self) -> list[Dispositivo]:
        """Aplana todas las listas en una única lista heterogénea."""
        out: list[Dispositivo] = []
        for lst in self._dispositivos.values():
            out.extend(lst)
        return out

    def __iter__(self) -> Iterator[tuple[str, list[Dispositivo]]]:
        """Permite iterar ``for hw, devices in state: ...``."""
        return iter(self._dispositivos.items())

    def __contains__(self, hw_type: str) -> bool:
        return hw_type in self._dispositivos

    # ── Magic para inspección / debugging ─────────────────────────────

    def __repr__(self) -> str:
        counts = {
            hw: len(lst) for hw, lst in self._dispositivos.items() if lst
        }
        return f"AppState(dispositivos={counts})"


# ── Helpers de mapeo attr ↔ hw_type ────────────────────────────────────


_LEGACY_ATTR_NAMES: frozenset[str] = frozenset(attr for _hw, attr, _t in _LEGACY_ATTRS)


def name_to_hw(attr_name: str) -> str:
    """``"dispositivos_ed"`` → ``"ed"``. Helper para ``__getattribute__``."""
    for hw, attr, _t in _LEGACY_ATTRS:
        if attr == attr_name:
            return hw
    raise KeyError(attr_name)


# ── Singleton thread-safe (inicialización perezosa) ──────────────────────


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
