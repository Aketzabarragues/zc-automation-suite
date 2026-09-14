"""Estado global del worker TIA + proyecto + PLCs.

Data Block puro consumido por la SPA via SSE (``tia_state`` channel).

Campos:
  - worker_alive (bool): ¿el subproceso TIA esta corriendo?
  - tia_state (str): ``"idle" | "connecting" | "connected" | "error"``.
  - project_name (str | None): nombre del proyecto TIA.
  - project_path (str | None): ruta absoluta al ``.ap`` del proyecto.
  - plcs (list[str]): nombres de los PLCs del proyecto abierto.
  - last_error (str | None): ultimo mensaje de error.
  - last_ping_ok_unix (float | None): timestamp (segundos epoch) del
    ultimo ping OK al worker. ``None`` si nunca ha habido ping OK.

El campo ``state`` (alias de ``tia_state``) se serializa por
back-compat con la SPA actual.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DataTiaStatus:
    """Estado global del worker TIA + proyecto + PLCs."""

    worker_alive: bool = False
    tia_state: str = "idle"
    project_name: str | None = None
    project_path: str | None = None
    plcs: list[str] = field(default_factory=list)
    last_error: str | None = None
    last_ping_ok_unix: float | None = None

    def to_dict(self) -> dict:
        """Serializa para SSE / JSON."""
        return {
            "state": self.tia_state,  # back-compat
            "worker_alive": self.worker_alive,
            "project_name": self.project_name,
            "project_path": self.project_path,
            "plcs": list(self.plcs),
            "last_error": self.last_error,
            "last_ping_ok_unix": self.last_ping_ok_unix,
        }
