"""Application Layer - Estado Global (AppState).

WARNING: Arquitectura Single-Tenant. Este estado asume un único usuario
departamental concurrente. Si en el futuro se requiere multi-tenancy,
hay que sustituir este singleton por un contexto por-sesión/usuario.

Diseño extensible:
  - ``AppState`` es TRANSVERSAL: no sabe de áreas concretas. Su
    única responsabilidad es mantener un ``_dispositivos:
    dict[str, list[Any]]`` indexado por ``hw_type``.
  - Las áreas pueden aportar PROPIEDADES ADICIONALES (back-compat
    legacy) vía ``AreaSpec.contributes_state_extensions``. El área
    "alimentación" instala ``dispositivos_ed/ea/sa/v/m/m_vf`` como
    properties de sugar que delegan a ``get_devices`` /
    ``set_devices``.
  - La API pública es **data-driven**: ``get_devices``,
    ``set_devices``, ``list_hw_types``, ``all_devices``, ``reset``,
    ``__iter__``, ``__contains__``.

Tras PR 2, ``get_app_state()`` itera el ``AreaRegistry`` y, para cada
spec con ``contributes_state_extensions``, invoca el callable pasando
la instancia Singleton. Esto reemplaza al parche de transición de PR 1.
"""
from __future__ import annotations

from threading import Lock
from typing import Any, Iterator


class AppState:
    """Estado global genérico (data-driven) — no ligado a alimentación.

    Mantiene las listas de dispositivos indexadas por ``hw_type`` y se
    expone vía ``get_app_state()`` (Singleton thread-safe).

    Las listas son mutables para admitir actualizaciones del operario,
    pero los dispositivos individuales son ``frozen=True`` (no se
    pueden mutar tras su creación; para "modificar" un dispositivo
    se crea uno nuevo y se sustituye en la lista).

    Attributes:
        dimensiones: Placeholder (Any) con default ``None``. Mantenido
            por back-compat con la SPA, los routers (``excel.py`` y
            ``diagnostics.py``) y los tests que aún leen/escriben
            ``state.dimensiones``. La tipificación correcta de
            ``DimensionesDispositivos`` (que ahora vive en el área
            de alimentación) se resolverá en un refactor futuro.
            TODO(PR2.5): tipar correctamente dimensiones una vez se
            decida dónde vive definitivamente.
        excel_cache: Placeholder (Any) con default ``None``. Cache IT
            del Excel (``ExcelCache``) que vive en
            ``areas/alimentacion/domain/models/excel_cache.py``. Se
            mantiene como ``Any`` para no importar el área desde
            ``core/``. Lo puebla el endpoint
            ``POST /api/v1/excel/upload`` tras un load exitoso.
        excel_path: Ruta absoluta del Excel actualmente cacheado,
            o ``None`` si todavía no se ha cargado ninguno. Sirve
            para la invalidación por mtime sin re-leer el cache.
    """

    def __init__(self) -> None:
        # Storage genérico (data-driven): única fuente de verdad.
        self._dispositivos: dict[str, list[Any]] = {}
        # Placeholder de back-compat (ver docstring de clase).
        # TODO(PR2.5): tipar correctamente dimensiones una vez se decida
        # dónde vive definitivamente.
        self.dimensiones: Any = None
        # Cache IT del Excel (Fase 5 del plan). Anotado ``Any`` para
        # no importar el área desde ``core/``.
        self.excel_cache: Any = None
        # Path absoluto del Excel actualmente cacheado. ``None`` si
        # todavía no se ha cargado ninguno.
        self.excel_path: str | None = None

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

        Para los 6 tipos del área de alimentación, las properties
        ``state.dispositivos_<hw>`` (aportadas vía
        ``contributes_state_extensions``) se actualizan
        automáticamente para devolver esta misma lista.
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

    Tras crear el Singleton, invoca el ``contributes_state_extensions``
    de cada área registrada (p. ej. ``areas.alimentacion.application.
    disp_state_extensions.install``) para que el área pueda aportar
    properties legacy sobre la CLASE ``AppState`` (no la instancia),
    con efecto en todas las instancias presentes y futuras.

    Las properties se instalan en la **clase** (con
    ``setattr(AppState, attr, property(...))``) para que se propaguen
    al Singleton global y a cualquier instancia futura. Por tanto, este
    hook se ejecuta **una sola vez** por proceso: instalarlo en cada
    llamada a ``get_app_state()`` sería redundante y gastaría un
    ``setattr`` por acceso.
    """
    global _state
    if _state is None:
        with _state_lock:
            if _state is None:
                _state = AppState()
                # Aportar las properties legacy de las áreas registradas.
                # El área de alimentación pega las 6 properties
                # ``dispositivos_ed/ea/...`` sobre la CLASE ``AppState``
                # (no sobre ``_state``) usando ``setattr(AppState, ...)``.
                from core.application.area_registry import AreaRegistry
                for spec in AreaRegistry.discover().all():
                    if spec.contributes_state_extensions is not None:
                        spec.contributes_state_extensions(_state)
    return _state


__all__ = ["AppState", "get_app_state"]
