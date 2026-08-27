"""Back-compat de las 6 properties legacy en ``AppState``.

Tras la migración a ``AppState`` genérico (PR 1), ``state.dispositivos_ed``,
``state.dispositivos_ea``, etc. ya no existen como properties
nativas. El área de alimentación las aporta aquí, monkey-patching
la CLASE ``AppState`` con properties de sugar que delegan a
``get_devices`` / ``set_devices``. Idéntico al comportamiento legacy
que el parche de transición de PR 1 garantizaba.

Compatible 100% con los tests existentes que hacen
``state.dispositivos_ed = [...]`` o leen ``state.dispositivos_ed``.

Importante: usamos ``setattr(AppState, attr, property(...))`` sobre
la CLASE (no sobre la instancia) para que la instalación se propague
a todas las instancias de ``AppState`` y al Singleton global que
``get_app_state()`` retorna. Si se hiciese sobre ``self``, el
comportamiento sería local a la instancia que recibió ``install()``
y la SPA (que usa el Singleton) NO vería las properties.

Invocación:
    ``get_app_state()`` invoca este callable tras crear el Singleton
    si la ``AreaSpec`` del área tiene ``contributes_state_extensions``.
"""
from __future__ import annotations

from core.application.state import AppState
from areas.alimentacion.domain.models.dispositivos import (
    DispED,
    DispEA,
    DispM,
    DispM_VF,
    DispSA,
    DispV,
)


# Mapeo canónico ``hw_type → nombre de la property legacy``.
# Mantener sincronizado con la convención que el área de alimentación
# documenta en AGENTS.md y que el parser de Excel usa para poblar
# ``AppState`` desde el corporativo.
_LEGACY = (
    # (hw_type, attr_legacy, dataclass_esperada)
    ("ed",   "dispositivos_ed",    DispED),
    ("ea",   "dispositivos_ea",    DispEA),
    ("sa",   "dispositivos_sa",    DispSA),
    ("v",    "dispositivos_v",     DispV),
    ("m",    "dispositivos_m",     DispM),
    ("m_vf", "dispositivos_m_vf",  DispM_VF),
)


def install(app_state: AppState) -> None:
    """Pega las 6 properties legacy a la CLASE ``AppState``.

    Args:
        app_state: Instancia de ``AppState`` (el Singleton global).
                   Solo se usa para tipar el callable de la ``AreaSpec``;
                   las properties se instalan sobre la **clase** para
                   que tengan efecto en todas las instancias presentes
                   y futuras.
    """
    for hw, attr, _cls in _LEGACY:
        _make_property(attr, hw)


def _make_property(attr: str, hw: str) -> None:
    """Construye una property ``getter``/``setter`` y la pega a ``AppState``.

    La property:
      - ``getter`` → ``self.get_devices(hw)`` (devuelve la lista del
        dict interno, o ``[]`` si el ``hw_type`` aún no existe).
      - ``setter`` → ``self.set_devices(hw, value)`` (sustituye la
        lista del ``hw_type``).
    """
    def _getter(self: AppState) -> list:  # noqa: ANN001
        return self.get_devices(hw)

    def _setter(self: AppState, value: list) -> None:  # noqa: ANN001
        self.set_devices(hw, value)

    setattr(AppState, attr, property(_getter, _setter))


__all__ = ["install"]
