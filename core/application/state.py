"""Application Layer - Estado Global (AppState).

WARNING: Arquitectura Single-Tenant. Este estado asume un único usuario
departamental concurrente. Si en el futuro se requiere multi-tenancy,
hay que sustituir este singleton por un contexto por-sesión/usuario.

Modelo **genérico** (Plan: Bounded Contexts — PR 1):

  - ``AppState`` es TRANSVERSAL: no sabe de áreas concretas. Su
    única responsabilidad es mantener un ``_dispositivos:
    dict[str, list[Any]]`` indexado por ``hw_type``.
  - El área "alimentación" aporta las propiedades tipadas
    (``dispositivos_ed/ea/...``) y los modelos (``DispED``, etc.,
    ``DimensionesDispositivos``) vía ``AreaSpec.contributes_state_extensions``
    en PR 2.
  - La API pública es **data-driven**: ``get_devices``,
    ``set_devices``, ``list_hw_types``, ``all_devices``, ``reset``,
    ``__iter__``, ``__contains__``.

> **Parche de transición (PR 1, marcado con TODO(PR2))**
> Para no romper ni la SPA ni los tests que aún hacen
> ``state.dispositivos_ed = [...]`` o ``state.dispositivos_ed``,
> este módulo expone las 6 properties legacy como un parche
> temporal. PR 2 moverá estas properties a
> ``areas/alimentacion/application/state_extensions.py`` y las
> instalará vía ``contributes_state_extensions``.
> Una vez PR 2 esté mergeado, este bloque de ``__getattribute__`` /
> ``__setattr__`` se borrará.
"""

from __future__ import annotations

from threading import Lock
from typing import Any, Iterator

# ``DimensionesDispositivos`` se mantiene importado por ahora para no
# romper la SPA, los routers ni los tests que usan
# ``state.dimensiones`` o lo instancian directamente. PR 2 moverá el
# modelo a ``areas/alimentacion/domain/models/dispositivos.py`` y este
# import apuntará allí (o desaparecerá si ``AppState`` deja de tener
# una ``dimensiones`` propia y se aporta vía state_extensions).
# TODO(PR2): mover a ``areas/alimentacion/domain/models/``.
from core.alimentacion.models.dispositivos import (  # noqa: F401  (PR2 will relocate)
    DimensionesDispositivos,
)


# ── Lista canónica de los 6 atributos legacy de alimentación ──────────
# (PARCHE DE TRANSICIÓN: ver TODO(PR2) arriba)
_LEGACY_ATTRS: tuple[tuple[str, str], ...] = (
    ("ed",   "dispositivos_ed"),
    ("ea",   "dispositivos_ea"),
    ("sa",   "dispositivos_sa"),
    ("v",    "dispositivos_v"),
    ("m",    "dispositivos_m"),
    ("m_vf", "dispositivos_m_vf"),
)

_LEGACY_ATTR_NAMES: frozenset[str] = frozenset(
    attr for _hw, attr in _LEGACY_ATTRS
)


def _hw_for_legacy_attr(attr_name: str) -> str | None:
    """Devuelve el hw_type legacy para un nombre de atributo, o ``None``."""
    for hw, attr in _LEGACY_ATTRS:
        if attr == attr_name:
            return hw
    return None


def name_to_hw(attr_name: str) -> str:
    """``"dispositivos_ed"`` → ``"ed"``. Helper para ``__getattribute__``."""
    for hw, attr in _LEGACY_ATTRS:
        if attr == attr_name:
            return hw
    raise KeyError(attr_name)


class AppState:
    """Estado global genérico (data-driven) — no ligado a alimentación.

    Mantiene las listas de dispositivos indexadas por ``hw_type`` y
    (en este PR, vía parche de transición) expone las 6 properties
    legacy ``dispositivos_ed/ea/sa/v/m/m_vf`` para back-compat. Se
    expone vía ``get_app_state()`` (Singleton thread-safe).

    Las listas son mutables para admitir actualizaciones del operario,
    pero los dispositivos individuales son ``frozen=True`` (no se
    pueden mutar tras su creación; para "modificar" un dispositivo
    se crea uno nuevo y se sustituye en la lista).
    """

    def __init__(self) -> None:
        # ── Storage genérico (data-driven) ────────────────────────────
        # ``_dispositivos`` es la fuente de verdad extensible. Las 6
        # properties ``dispositivos_*`` (parche de transición) se
        # mantienen sincronizadas con este dict vía ``__setattr__`` y
        # ``__getattribute__``.
        self._dispositivos: dict[str, list[Any]] = {}
        # ── Dimensiones (cantidades) ────────────────────────────────────
        # Mantenido en este PR por back-compat con la SPA, routers y
        # tests que leen ``state.dimensiones``. PR 2 lo moverá al área.
        # TODO(PR2): sustituir por un mecanismo del área.
        self.dimensiones: DimensionesDispositivos = DimensionesDispositivos()

    # ── Parche de transición: 6 atributos legacy de alimentación ──────
    # TODO(PR2): eliminar este bloque. Las properties pasarán a
    # aportarse vía ``AreaSpec.contributes_state_extensions``.

    def __getattribute__(self, name: str) -> Any:
        """Sirve ``dispositivos_ed/ea/sa/v/m/m_vf`` desde ``_dispositivos``.

        Mantiene la API legacy: ``state.dispositivos_ed`` devuelve la
        lista de dispositivos de tipo ``"ed"`` (tipada en type-checkers
        pero la runtime ve ``list[Any]``). El área tipará las listas en
        PR 2 vía ``state_extensions.install``.
        """
        # Evita recursión infinita: ``_dispositivos`` se accede por el
        # camino normal de ``object.__getattribute__``.
        if name in _LEGACY_ATTR_NAMES:
            disp = object.__getattribute__(self, "_dispositivos")
            hw = _hw_for_legacy_attr(name)
            return disp.get(hw, []) if hw is not None else []
        return object.__getattribute__(self, name)

    def __setattr__(self, name: str, value: Any) -> None:
        """Sincroniza ``dispositivos_ed = ...`` con ``_dispositivos["ed"]``.

        Si ``name`` es uno de los 6 legacy attrs, actualiza también
        el dict. Si es ``_dispositivos`` o ``dimensiones``, se guarda
        tal cual.
        """
        if name in _LEGACY_ATTR_NAMES:
            disp = object.__getattribute__(self, "_dispositivos")
            hw = _hw_for_legacy_attr(name)
            if hw is not None:
                disp[hw] = value
            # No usamos ``object.__setattr__`` aquí: el resto de la
            # clase no expone esos nombres como atributos (viven solo
            # en el dict). Si lo hiciéramos, duplicaríamos la lista.
            return
        object.__setattr__(self, name, value)

    # ── API data-driven (público, no ligado a alimentación) ────────────

    def reset(self) -> None:
        """Vacía todas las listas (útil para tests)."""
        for hw in list(self._dispositivos.keys()):
            self.set_devices(hw, [])

    def get_devices(self, hw_type: str) -> list[Any]:
        """Devuelve la lista de dispositivos de ``hw_type``.

        Retorna lista vacía si el tipo aún no tiene entradas.
        """
        return self._dispositivos.get(hw_type, [])

    def set_devices(
        self, hw_type: str, devices: list[Any]
    ) -> None:
        """Sustituye la lista de dispositivos de ``hw_type``.

        Para los 6 tipos legacy, las properties
        ``state.dispositivos_<hw>`` se actualizan automáticamente
        (vía ``__getattribute__``) para devolver esta misma lista.
        """
        self._dispositivos[hw_type] = list(devices)

    def list_hw_types(self) -> list[str]:
        """Devuelve los hw_types que tienen al menos un dispositivo cargado."""
        return [hw for hw, lst in self._dispositivos.items() if lst]

    def all_devices(self) -> list[Any]:
        """Aplana todas las listas en una única lista heterogénea."""
        out: list[Any] = []
        for lst in self._dispositivos.values():
            out.extend(lst)
        return out

    def __iter__(self) -> Iterator[tuple[str, list[Any]]]:
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


# ── Singleton thread-safe (inicialización perezosa) ──────────────────────


_state: AppState | None = None
_state_lock: Lock = Lock()


def get_app_state() -> AppState:
    """Devuelve la instancia Singleton de ``AppState`` (thread-safe).

    En PR 2, tras crear el Singleton, se invocará
    ``AreaRegistry.discover().for_each("contributes_state_extensions", app_state=_state)``
    para instalar el parche de transición desde el área de alimentación
    (reemplazando las 6 properties legacy de este módulo).
    """
    global _state
    if _state is None:
        with _state_lock:
            if _state is None:
                _state = AppState()
    return _state


__all__ = ["AppState", "get_app_state"]
