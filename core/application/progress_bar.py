"""core.application.progress_bar

ProgressBar per-instance para visualizar el progreso de UNA operación
larga (subir Excel, sincronizar dispositivos, escanear bloques, etc.).

Versión nueva (DA-013) de ``ProgressTracker`` (Singleton, polling):

  +-------------------------+----------------------------+----------------------------+
  | Característica         | ProgressTracker (legacy)   | ProgressBar (nuevo)        |
  +-------------------------+----------------------------+----------------------------+
  | Lifecycle              | Singleton global           | Per-instance (cada FB crea |
  |                        |                            | el suyo)                    |
  | Transporte             | Polling (SPA cada 500 ms)   | SSE event-driven            |
  | Shape del dict         | {operation, label, stages, | Igual                       |
  |                        |  current, total, percent}  | (compatible con frontend)  |
  | Weights por stage      | No (todos cuentan igual)   | Sí (``weight`` opcional)    |
  | Integración con FB     | Manual (router llama       | Auto (FB lo crea en         |
  |                        | progress.begin())          | _start_locked)             |
  | Publica al EventBus    | Vía hook on_publish        | Directo                     |
  | UI en web              | ProgressIndicator.vue      | Igual (mismo shape)         |
  +-------------------------+----------------------------+----------------------------+

Uso típico (desde un FunctionBlock)::

    class FunctionSubirExcel(FunctionBase):
        async def _start_locked(self, xlsx_path):
            self._xlsx_path = xlsx_path
            self.progress_bar = ProgressBar(
                operation="subir_excel",
                label="Subir Excel",
                stages=[
                    ProgressBarStage("parse_xlsx", "Parseando archivo", weight=1.0),
                    ProgressBarStage("validate", "Validando dispositivos", weight=2.0),
                    ProgressBarStage("sync_tia", "Sincronizando con TIA", weight=3.0),
                ],
            )
            if self._engine and self._engine._event_bus:
                self.progress_bar.attach_to_bus(self._engine._event_bus)
            self.progress_bar.start()
            return True
        
        async def _tick_locked(self):
            ...
            self.progress_bar.advance("parse_xlsx", detail=f"{n} devices")
            ...
            self.progress_bar.complete()

Publica eventos ``type: "progress_bar"`` al EventBus. El frontend Vue
los consume del SSE stream y los renderiza igual que el legacy.

Coexiste con ``ProgressTracker`` durante la migración. En Fase 4 OB1
se reemplaza definitivamente.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


# ── Constantes (compatibles con ProgressTracker legacy) ────────────

STAGE_PENDING = "pending"
STAGE_RUNNING = "running"
STAGE_DONE = "done"
STAGE_ERROR = "error"

_VALID_STATUSES = frozenset({STAGE_PENDING, STAGE_RUNNING, STAGE_DONE, STAGE_ERROR})


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ── Modelos ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProgressBarStage:
    """Un stage individual del ProgressBar.

    Attributes:
        id: Identificador canónico ("parse_xlsx", "validate", "sync_tia").
            Único dentro del ProgressBar.
        label: Texto humano-legible para el operario.
        weight: Peso relativo para el cálculo del ``percent``.
            Default 1.0 (todos los stages pesan igual).
            Útil cuando un stage es "más caro" que otro
            (e.g. "sync_tia" tarda más que "parse").
    """
    id: str
    label: str
    weight: float = 1.0


# ── Clase principal ────────────────────────────────────────────────


@dataclass
class ProgressBar:
    """Progress bar per-instance para UNA operación larga.

    Shape estable (compatible con el frontend existente; el legacy
    ``ProgressTracker`` produce el mismo shape)::

        {
            "type": "progress_bar",
            "operation": "subir_excel_42",
            "label": "Subir Excel",
            "active": True,
            "current": 1,           # 1-based: 1 = primer stage done, etc.
            "total": 3,
            "percent": 33,
            "stages": [
                {"id": "parse_xlsx", "label": "Parseando...", "status": "done",
                 "detail": "25 dispositivos", "started_at": "...", "finished_at": "..."},
                {"id": "validate",   "label": "Validando...",  "status": "running",
                 "detail": null, "started_at": "...", "finished_at": null},
                {"id": "sync_tia",   "label": "Sincronizando...","status": "pending",
                 "detail": null, "started_at": null, "finished_at": null},
            ],
            "started_at": "2026-09-11T18:30:00",
            "finished_at": null,
            "error": null,
        }

    Attributes:
        operation: ID de la operación (e.g. "subir_excel_42").
        label: Texto humano-legible para el operario.
        stages: Lista ordenada de stages del ProgressBar.
        _event_bus: Referencia al EventBus para publicar eventos
            (se setea con ``attach_to_bus(bus)``).
        _stage_details: Dict opcional de detalles por stage (e.g.
            "25 dispositivos"). Se llena en ``advance(stage_id, detail=...)``.
    """
    operation: str
    label: str
    stages: list[ProgressBarStage]
    current_index: int = -1
    status: Literal["idle", "running", "complete", "error"] = "idle"
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    _event_bus: Any = field(default=None, repr=False)
    _stage_details: dict[str, str] = field(default_factory=dict, repr=False)

    # ── API ─────────────────────────────────────────────────────

    def attach_to_bus(self, bus: Any) -> None:
        """Adjunta el ProgressBar al EventBus para publicar vía SSE."""
        self._event_bus = bus

    def start(self) -> None:
        """Arranca el ProgressBar (status='running', primer stage)."""
        self.status = "running"
        self.current_index = 0
        self.started_at = _now_iso()
        self.finished_at = None
        self.error = None
        self._publish()

    def advance(
        self,
        stage_id: str | None = None,
        detail: str | None = None,
    ) -> None:
        """Avanza al siguiente stage (o salta a ``stage_id`` si se da).

        Args:
            stage_id: Salta directamente al stage con este id. Útil
                cuando los stages no son estrictamente lineales (e.g.
                se puede saltar "validate" si no hay nada que validar).
            detail: Texto adicional del stage actual (e.g.
                "Tabla ED: 25 entries").
        """
        if detail is not None:
            # Si nos pasan detail y estamos en un stage, lo guardamos
            # para ese stage (sobrescribe si ya había).
            current_id = self._current_stage_id()
            if current_id is not None:
                self._stage_details[current_id] = detail

        if stage_id is not None:
            for i, s in enumerate(self.stages):
                if s.id == stage_id:
                    self.current_index = i
                    break
        else:
            self.current_index += 1
            if self.current_index >= len(self.stages):
                # No-op silencioso si intentan avanzar más allá del último.
                self.current_index = len(self.stages) - 1
        self._publish()

    def complete(self) -> None:
        """Marca el ProgressBar como 'complete'."""
        self.status = "complete"
        self.current_index = len(self.stages) - 1
        self.finished_at = _now_iso()
        self._publish()

    def error(self, msg: str) -> None:
        """Marca el ProgressBar como 'error' con detalle."""
        self.status = "error"
        self.error = msg
        self.finished_at = _now_iso()
        self._publish()

    # ── Serialización ────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Snapshot serializable a dict (compatible con frontend)."""
        stages_data: list[dict[str, Any]] = []
        current_done = 0
        for i, s in enumerate(self.stages):
            if i < self.current_index:
                state = STAGE_DONE
                current_done += 1
            elif i == self.current_index and self.status == "running":
                state = STAGE_RUNNING
            elif i == self.current_index and self.status in (STAGE_DONE, "complete"):
                # Último stage en estado "complete": todos done
                state = STAGE_DONE
                current_done += 1
            else:
                state = STAGE_PENDING

            stages_data.append({
                "id": s.id,
                "label": s.label,
                "status": state,
                "detail": self._stage_details.get(s.id),
                "started_at": self.started_at if i <= self.current_index else None,
                "finished_at": (
                    self.finished_at if state == STAGE_DONE
                    else None
                ),
            })

        total = len(self.stages)
        percent = 100 if self.status == "complete" else self._percent(
            current_done
        )

        return {
            "type": "progress_bar",
            "operation": self.operation,
            "label": self.label,
            "active": self.status in ("running", "complete", "error"),
            "current": current_done,
            "total": total,
            "percent": percent,
            "stages": stages_data,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }

    # ── Internos ────────────────────────────────────────────────

    def _current_stage_id(self) -> str | None:
        if 0 <= self.current_index < len(self.stages):
            return self.stages[self.current_index].id
        return None

    def _percent(self, current_done: int) -> int:
        if not self.stages:
            return 0
        total_weight = sum(s.weight for s in self.stages)
        if total_weight <= 0:
            return 0
        done_weight = sum(
            s.weight for i, s in enumerate(self.stages)
            if i < self.current_index
        )
        # Bonus: media del current stage (asume "estamos a la mitad").
        cur_weight = (
            self.stages[self.current_index].weight / 2
            if 0 <= self.current_index < len(self.stages)
            else 0
        )
        return round(
            (done_weight + cur_weight) / total_weight * 100
        )

    def _publish(self) -> None:
        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(self.to_dict())
        except Exception:
            # Nunca rompemos el FB por un fallo de publicación.
            # El snapshot del Engine es el fallback.
            pass


__all__ = [
    "ProgressBar",
    "ProgressBarStage",
    "STAGE_PENDING",
    "STAGE_RUNNING",
    "STAGE_DONE",
    "STAGE_ERROR",
]
