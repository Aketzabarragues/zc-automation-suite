"""Application Layer - Progress Tracker (Singleton).

Buffer thread-safe que la SPA consulta via polling para mostrar el
avance granular de las operaciones largas (carga de Excel, generación
de previsión, commit contra TIA, etc.).

Estrategia: los use cases llaman ``progress_tracker.begin(...)`` y
van emitiendo ``start_stage``/``finish_stage``/``error_stage`` según
avanzan. La SPA hace ``GET /api/v1/progress/current`` cada 500 ms y
pinta un overlay con la lista de stages y su estado.

Inspirado en ``application/log_buffer.py`` (mismo patrón Singleton
thread-safe con snapshot inmutable).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from threading import Lock
from typing import Any


# Status values para ``ProgressStage.status``. Constantes exportadas
# para que la SPA y los tests no dependan de strings sueltos.
STAGE_PENDING = "pending"
STAGE_RUNNING = "running"
STAGE_DONE = "done"
STAGE_ERROR = "error"

_VALID_STATUSES = frozenset({STAGE_PENDING, STAGE_RUNNING, STAGE_DONE, STAGE_ERROR})


@dataclass(frozen=True)
class ProgressStage:
    """Un step individual dentro de una operación.

    Attributes:
        id: Identificador canónico (``"export_tags"``, ``"open_transaction"``...).
            Único dentro de la operación.
        label: Texto humano-legible para el operario.
        status: Uno de ``pending`` / ``running`` / ``done`` / ``error``.
        detail: Texto opcional adicional (ej. "Tabla ED: 25 entries").
        started_at: ISO timestamp del momento en que pasó a ``running``.
            ``None`` si aún está en ``pending``.
        finished_at: ISO timestamp del momento en que pasó a ``done``
            o ``error``. ``None`` si sigue activo.
    """
    id: str
    label: str
    status: str
    detail: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


@dataclass(frozen=True)
class ProgressSnapshot:
    """Snapshot inmutable del estado del tracker.

    La SPA recibe este dict vía ``GET /api/v1/progress/current``.
    El campo ``stages`` es una tupla (no lista) para reforzar la
    inmutabilidad de la respuesta.
    """
    active: bool
    operation: str | None
    label: str | None
    current: int
    total: int
    percent: int
    stages: tuple[dict[str, Any], ...]
    started_at: str | None
    finished_at: str | None
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        """Serializa a dict (con stages como lista) para JSON."""
        return {
            "active": self.active,
            "operation": self.operation,
            "label": self.label,
            "current": self.current,
            "total": self.total,
            "percent": self.percent,
            "stages": list(self.stages),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }


def _now_iso() -> str:
    """ISO timestamp con segundos (mismo formato que ``LogBuffer``)."""
    return datetime.now().isoformat(timespec="seconds")


class ProgressTracker:
    """Tracker thread-safe de progreso para la SPA.

    Modelo single-slot: asume un único operario a la vez
    (``application/state.py`` documenta que la app es single-tenant).
    Si llega un nuevo ``begin()`` mientras hay uno activo, se reemplaza
    el estado y se loggea un warning vía ``LogBuffer`` para trazabilidad.

    Stages modelados como ``dict[str, dict]`` internamente (mutables
    bajo lock) y re-empaquetados como ``ProgressStage`` inmutables en
    cada ``snapshot()``. Esto evita romper las tuplas ``frozen=True``
    cuando actualizamos un stage.
    """

    def __init__(self) -> None:
        self._lock: Lock = Lock()
        self._active: bool = False
        self._operation: str | None = None
        self._label: str | None = None
        self._started_at: str | None = None
        self._finished_at: str | None = None
        self._error: str | None = None
        # ``_stages`` es dict ``{id: _StageRecord}`` donde ``_StageRecord``
        # es un dict mutable (label, status, detail, started_at, finished_at).
        # Lo re-empaquetamos en dataclasses frozen al hacer ``snapshot()``.
        self._stages: dict[str, dict[str, Any]] = {}
        self._stage_order: list[str] = []

    @property
    def active(self) -> bool:
        """``True`` si hay una operación en curso. Solo lectura.

        Útil para que los use cases internos (ej. ``generar_prevision``
        llamado desde ``ejecutar_transaccion`` para post-sync) puedan
        detectar si ya hay un tracker activo y no pisarlo.
        """
        return self._active

    # ── API pública ─────────────────────────────────────────────────

    def begin(
        self,
        operation: str,
        label: str,
        stages: list[str],
    ) -> None:
        """Inicia una nueva operación.

        Si ya hay una activa, emite un warning al ``LogBuffer``
        (best-effort: si el logger no está disponible aún,
        simplemente no loggea — el tracker no debe fallar por eso).
        Excepción: si la nueva operación es **idéntica** a la actual
        (mismo ``operation`` + mismos ``stages``), NO se emite el
        warning — es claramente un reintento del mismo caller
        (p. ej. el operario pinchó el botón dos veces, o el SPA
        disparó el endpoint por auto-refresh mientras el primero
        estaba en vuelo). El warning se mantiene cuando:

          * la operación es **distinta** (conflicto real, p. ej.
            un escaneo y un preview compitiendo por el mismo
            tracker), o
          * la operación es la misma pero los ``stages`` son
            diferentes (alguien cambió la spec sin querer — un
            ``generar_prevision`` con 4 stages reemplazando a uno
            con 5).

        Args:
            operation: Tag canónico (``"preview"``, ``"commit"``,
                ``"upload_excel"``, ``"refresh_plcs"``...).
            label: Texto humano-legible para el overlay.
            stages: Lista de IDs de stage en orden de ejecución.
        """
        with self._lock:
            if self._active:
                # ¿Es un reintento idéntico? (mismo operation + mismos
                # stages). En ese caso NO warning — es el mismo
                # caller re-ejecutando, no un conflicto.
                same_operation = self._operation == operation
                same_stages = self._stage_order == list(stages)
                if not (same_operation and same_stages):
                    try:
                        from core.application.log_buffer import get_log_buffer
                        if not same_operation:
                            get_log_buffer().warning(
                                f"ProgressTracker: '{self._operation}' en curso fue "
                                f"reemplazado por '{operation}'."
                            )
                        else:
                            # Mismo operation pero stages distintos:
                            # escenario anómalo (alguien cambió la
                            # spec). Warning más específico.
                            get_log_buffer().warning(
                                f"ProgressTracker: '{self._operation}' en curso fue "
                                f"reiniciado con stages distintos "
                                f"(antes={self._stage_order}, ahora={list(stages)})."
                            )
                    except Exception:
                        # Nunca rompemos el tracker por un fallo de
                        # logging.
                        pass
            self._active = True
            self._operation = operation
            self._label = label
            self._started_at = _now_iso()
            self._finished_at = None
            self._error = None
            self._stages = {
                sid: {
                    "id": sid,
                    "label": sid.replace("_", " ").capitalize(),
                    "status": STAGE_PENDING,
                    "detail": None,
                    "started_at": None,
                    "finished_at": None,
                }
                for sid in stages
            }
            self._stage_order = list(stages)

    def start_stage(self, stage_id: str, detail: str | None = None) -> None:
        """Marca un stage como ``running``.

        Args:
            stage_id: ID declarado en ``begin()``.
            detail: Texto opcional (ej. "Aplicando 12 ops en TIA Portal...").

        Raises:
            ValueError: Si ``stage_id`` no fue declarado en ``begin()``.
                Fail-fast, mismo estilo que el resto del proyecto.
        """
        with self._lock:
            if stage_id not in self._stages:
                raise ValueError(
                    f"ProgressTracker: stage_id '{stage_id}' no fue declarado "
                    f"en begin() (operation='{self._operation}'). "
                    f"Stages válidos: {list(self._stages.keys())}"
                )
            rec = self._stages[stage_id]
            rec["status"] = STAGE_RUNNING
            rec["started_at"] = _now_iso()
            if detail is not None:
                rec["detail"] = detail

    def finish_stage(self, stage_id: str, detail: str | None = None) -> None:
        """Marca un stage como ``done``.

        Solo actúa si el stage está en ``running``; si no, no-op
        silencioso (idempotente para retries / re-entry).
        """
        with self._lock:
            rec = self._stages.get(stage_id)
            if rec is None or rec["status"] != STAGE_RUNNING:
                return
            rec["status"] = STAGE_DONE
            rec["finished_at"] = _now_iso()
            if detail is not None:
                rec["detail"] = detail

    def error_stage(self, stage_id: str, detail: str) -> None:
        """Marca un stage como ``error`` con detalle del fallo.

        No-op si el stage no existe o ya está terminal (``done``/``error``).
        """
        with self._lock:
            rec = self._stages.get(stage_id)
            if rec is None or rec["status"] in (STAGE_DONE, STAGE_ERROR):
                return
            rec["status"] = STAGE_ERROR
            rec["finished_at"] = _now_iso()
            rec["detail"] = detail

    def finish(
        self, success: bool = True, error: str | None = None
    ) -> None:
        """Cierra la operación.

        ``active`` pasa a ``False`` pero los stages NO se borran: el
        frontend debe poder ver el último resultado unos segundos
        hasta el auto-close o un ``clear()`` explícito.

        Si ``success=False``, todos los stages que aún estén en
        ``running`` se marcan como ``error`` con el motivo.

        Args:
            success: Si la operación terminó OK.
            error: Mensaje de error global (opcional). Si se pasa,
                sobreescribe ``self._error``.
        """
        with self._lock:
            self._active = False
            self._finished_at = _now_iso()
            if error is not None:
                self._error = error
            if not success:
                # Stages huérfanos en running → error.
                err_msg = error or "Operación fallida"
                for rec in self._stages.values():
                    if rec["status"] == STAGE_RUNNING:
                        rec["status"] = STAGE_ERROR
                        rec["finished_at"] = _now_iso()
                        if not rec.get("detail"):
                            rec["detail"] = err_msg

    def snapshot(self) -> ProgressSnapshot:
        """Devuelve un snapshot inmutable del estado actual.

        El snapshot es seguro de exponer a la SPA: ``stages`` es una
        tupla de dicts (no la estructura interna mutable).
        """
        with self._lock:
            stages: list[dict[str, Any]] = []
            current = 0
            for sid in self._stage_order:
                rec = self._stages.get(sid)
                if rec is None:
                    continue
                # Validamos el status (defensivo: nunca debería
                # haber un valor fuera del set, pero si lo hay
                # caemos a ``pending`` para no romper la SPA).
                status = rec["status"] if rec["status"] in _VALID_STATUSES else STAGE_PENDING
                stages.append({
                    "id": rec["id"],
                    "label": rec["label"],
                    "status": status,
                    "detail": rec["detail"],
                    "started_at": rec["started_at"],
                    "finished_at": rec["finished_at"],
                })
                if status in (STAGE_DONE, STAGE_ERROR):
                    current += 1

            total = len(self._stage_order)
            percent = (
                int(round(100.0 * current / total)) if total > 0 else 0
            )

            return ProgressSnapshot(
                active=self._active,
                operation=self._operation,
                label=self._label,
                current=current,
                total=total,
                percent=percent,
                stages=tuple(stages),
                started_at=self._started_at,
                finished_at=self._finished_at,
                error=self._error,
            )

    def clear(self) -> None:
        """Resetea el tracker al estado vacío inicial.

        Llamado por ``POST /api/v1/progress/clear`` o por el auto-close
        del frontend.
        """
        with self._lock:
            self._active = False
            self._operation = None
            self._label = None
            self._started_at = None
            self._finished_at = None
            self._error = None
            self._stages = {}
            self._stage_order = []


# ── Singleton thread-safe (inicialización perezosa) ─────────────────


_tracker: ProgressTracker | None = None
_tracker_lock: Lock = Lock()


def get_progress_tracker() -> ProgressTracker:
    """Devuelve la instancia Singleton de ``ProgressTracker`` (thread-safe).

    Mismo patrón que ``get_log_buffer()`` y ``get_app_state()``.
    """
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = ProgressTracker()
    return _tracker


__all__ = [
    "ProgressStage",
    "ProgressSnapshot",
    "ProgressTracker",
    "get_progress_tracker",
    "STAGE_PENDING",
    "STAGE_RUNNING",
    "STAGE_DONE",
    "STAGE_ERROR",
]
