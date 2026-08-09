"""Application Layer - Estado Global (AppState).

WARNING: Arquitectura Single-Tenant. Este estado asume un único usuario
departamental concurrente. Si en el futuro se requiere multi-tenancy,
hay que sustituir este singleton por un contexto por-sesión/usuario.
"""

from __future__ import annotations

from threading import Lock

from core.alimentacion.models.dispositivos import (
    DimensionesDispositivos,
    DispEA,
    DispED,
    DispM,
    DispM_VF,
    DispSA,
    DispV,
)


class AppState:
    """Estado global del subdominio alimentación.

    Mantiene las 6 listas de dispositivos del departamento y la
    instancia de ``DimensionesDispositivos``. Se expone vía
    ``get_app_state()`` (Singleton thread-safe).

    Las listas son mutables para admitir actualizaciones del operario,
    pero los dispositivos individuales son ``frozen=True`` (no se
    pueden mutar tras su creación; para "modificar" un dispositivo
    se crea uno nuevo y se sustituye en la lista).
    """

    def __init__(self) -> None:
        # ── Listas de dispositivos por tipo ────────────────────────────
        self.dispositivos_ed: list[DispED] = []
        self.dispositivos_ea: list[DispEA] = []
        self.dispositivos_sa: list[DispSA] = []
        self.dispositivos_v: list[DispV] = []
        self.dispositivos_m: list[DispM] = []
        self.dispositivos_m_vf: list[DispM_VF] = []
        # ── Dimensiones (cantidades) ────────────────────────────────────
        self.dimensiones: DimensionesDispositivos = DimensionesDispositivos()

    def reset(self) -> None:
        """Vacía todas las listas (útil para tests)."""
        self.dispositivos_ed.clear()
        self.dispositivos_ea.clear()
        self.dispositivos_sa.clear()
        self.dispositivos_v.clear()
        self.dispositivos_m.clear()
        self.dispositivos_m_vf.clear()
        self.dimensiones = DimensionesDispositivos()

    def all_devices(self) -> list:
        """Aplana las 6 listas en una única lista heterogénea."""
        return (
            self.dispositivos_ed
            + self.dispositivos_ea
            + self.dispositivos_sa
            + self.dispositivos_v
            + self.dispositivos_m
            + self.dispositivos_m_vf
        )


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


def reset_app_state() -> None:
    """Reinicia el Singleton (útil para tests)."""
    global _state
    with _state_lock:
        _state = None


__all__ = ["AppState", "get_app_state", "reset_app_state"]
