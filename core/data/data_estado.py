"""core.data.data_estado — Data Block del estado global de TIA Portal.

Fase 3, paso 3.1.1.  Reemplaza (progresivamente) los campos sueltos
de ``core/infrastructure/gateway.py:_connection_state`` y agrega
metadata del proyecto y del worker.  Es la fuente de verdad que
el router expone a la SPA via SSE (``tia_state`` channel).

Campos:
  - ``worker_alive`` (bool): ¿el subproceso persistente de TIA está
    corriendo?  ``False`` si el proceso se cayó o aún no arrancó.
  - ``tia_state`` (str): estado de la conexión TIA.  Mismo alfabeto
    que ``TIAProcessGateway._connection_state`` (``"idle"``,
    ``"connecting"``, ``"connected"``, ``"error"``).
  - ``project_name`` (str | None): nombre del proyecto TIA abierto.
    ``None`` si no hay proyecto cargado.
  - ``project_path`` (str | None): ruta absoluta al ``.ap``
    del proyecto.  ``None`` si no hay proyecto.
  - ``plcs`` (list[str]): nombres de los PLCs del proyecto abierto.
    Lista vacía si no hay proyecto o si el proyecto no tiene PLCs
    declarados.
  - ``last_error`` (str | None): último mensaje de error del worker
    o de la conexión.  ``None`` si no hay error reciente.
  - ``last_ping_ok_unix`` (float | None): timestamp (segundos desde
    epoch) del último ``ping`` al worker que respondió OK.  ``None``
    si nunca se ha hecho ping o el último falló.

Migracion:
  - La SPA hoy consume ``{"type": "tia_state", "state": "..."}``
    (1 campo).  En 3.3 (refactor in-place de ``store.js``) se
    actualiza a consumir el payload completo de ``DataEstado``.
  - Hasta entonces, el serializador de ``tia_state`` emite el campo
    ``state`` (back-compat) y, opcionalmente, el resto de los
    campos en un dict extendido.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DataEstado:
    """Estado global del worker TIA + proyecto + PLCs.

    Instanciar con ``DataEstado()`` da el estado por defecto
    (worker muerto, TIA idle, sin proyecto).  El Composition Root
    lo inyecta en ``app.state.data_estado`` y el router lo lee
    para servirlo al frontend.
    """

    worker_alive: bool = False
    tia_state: str = "idle"  # "idle" | "connecting" | "connected" | "error"
    project_name: str | None = None
    project_path: str | None = None
    plcs: list[str] = field(default_factory=list)
    last_error: str | None = None
    last_ping_ok_unix: float | None = None

    def to_dict(self) -> dict:
        """Serializa a dict para emitir por SSE / JSON.

        El campo ``state`` se mantiene por back-compat con la SPA
        actual (que solo lee ``state``).  El resto de los campos
        están disponibles para el refactor in-place de ``store.js``
        en 3.3.
        """
        return {
            "state": self.tia_state,  # back-compat
            "worker_alive": self.worker_alive,
            "project_name": self.project_name,
            "project_path": self.project_path,
            "plcs": list(self.plcs),
            "last_error": self.last_error,
            "last_ping_ok_unix": self.last_ping_ok_unix,
        }
