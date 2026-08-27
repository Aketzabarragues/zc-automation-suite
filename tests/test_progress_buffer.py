"""Tests para ``application.progress_buffer.ProgressTracker``.

Cubre:
  1. Singleton (misma instancia entre llamadas).
  2. ``begin`` deja ``active=True`` con ``total = len(stages)``.
  3. ``start_stage`` cambia status a ``running`` y rellena ``started_at``.
  4. ``finish_stage`` cambia a ``done`` y rellena ``finished_at``.
  5. ``error_stage`` cambia a ``error`` con ``detail``.
  6. ``start_stage`` de id desconocido -> ``ValueError`` (fail-fast).
  7. ``snapshot()`` es inmutable (no se puede mutar ``stages`` desde fuera).
  8. ``clear()`` resetea a estado vacío.
  9. ``finish(success=False)`` marca stages huérfanos en ``running``
     como ``error``.
"""
from __future__ import annotations

from core.application.progress_buffer import (
    ProgressTracker,
    STAGE_DONE,
    STAGE_ERROR,
    STAGE_PENDING,
    STAGE_RUNNING,
    get_progress_tracker,
)


def test_singleton_returns_same_instance() -> None:
    """Dos llamadas a ``get_progress_tracker`` devuelven la misma instancia."""
    a = get_progress_tracker()
    b = get_progress_tracker()
    assert a is b


def test_begin_activates_with_total_stages() -> None:
    """``begin`` deja ``active=True`` con ``total = len(stages)``."""
    tracker = ProgressTracker()
    tracker.begin(
        operation="preview",
        label="Test preview",
        stages=["a", "b", "c", "d"],
    )
    snap = tracker.snapshot()
    assert snap.active is True
    assert snap.operation == "preview"
    assert snap.label == "Test preview"
    assert snap.total == 4
    assert snap.current == 0
    assert snap.percent == 0
    assert len(snap.stages) == 4
    assert all(s["status"] == STAGE_PENDING for s in snap.stages)
    assert all(s["started_at"] is None for s in snap.stages)
    assert all(s["finished_at"] is None for s in snap.stages)


def test_start_stage_marks_running_with_timestamp() -> None:
    """``start_stage`` cambia status a ``running`` y rellena ``started_at``."""
    tracker = ProgressTracker()
    tracker.begin("op", "label", ["s1", "s2"])
    tracker.start_stage("s1", "Doing s1...")
    snap = tracker.snapshot()
    s1 = next(s for s in snap.stages if s["id"] == "s1")
    s2 = next(s for s in snap.stages if s["id"] == "s2")
    assert s1["status"] == STAGE_RUNNING
    assert s1["started_at"] is not None
    assert s1["detail"] == "Doing s1..."
    assert s2["status"] == STAGE_PENDING
    assert s2["started_at"] is None


def test_finish_stage_marks_done_with_timestamp() -> None:
    """``finish_stage`` cambia a ``done`` y rellena ``finished_at``."""
    tracker = ProgressTracker()
    tracker.begin("op", "label", ["s1"])
    tracker.start_stage("s1")
    tracker.finish_stage("s1", "Hecho")
    snap = tracker.snapshot()
    s1 = snap.stages[0]
    assert s1["status"] == STAGE_DONE
    assert s1["started_at"] is not None
    assert s1["finished_at"] is not None
    assert s1["detail"] == "Hecho"
    # El current counter subió a 1.
    assert snap.current == 1
    assert snap.percent == 100


def test_finish_stage_idempotent_on_non_running() -> None:
    """``finish_stage`` sobre un stage que NO está en ``running``
    es no-op silencioso (idempotente para retries)."""
    tracker = ProgressTracker()
    tracker.begin("op", "label", ["s1"])
    # s1 está en pending. finish_stage no debe hacer nada.
    tracker.finish_stage("s1", "intento 1")
    snap = tracker.snapshot()
    s1 = snap.stages[0]
    assert s1["status"] == STAGE_PENDING
    assert s1["finished_at"] is None


def test_error_stage_marks_error() -> None:
    """``error_stage`` cambia a ``error`` con ``detail``."""
    tracker = ProgressTracker()
    tracker.begin("op", "label", ["s1"])
    tracker.start_stage("s1")
    tracker.error_stage("s1", "Falló por X")
    snap = tracker.snapshot()
    s1 = snap.stages[0]
    assert s1["status"] == STAGE_ERROR
    assert s1["finished_at"] is not None
    assert s1["detail"] == "Falló por X"
    # El current cuenta done y error por igual.
    assert snap.current == 1


def test_start_stage_unknown_id_raises() -> None:
    """``start_stage`` de id desconocido -> ``ValueError`` (fail-fast)."""
    tracker = ProgressTracker()
    tracker.begin("op", "label", ["a", "b"])
    try:
        tracker.start_stage("c")
    except ValueError as exc:
        assert "c" in str(exc)
        assert "a" in str(exc)  # IDs válidos listados
    else:
        raise AssertionError("Se esperaba ValueError")


def test_snapshot_is_immutable() -> None:
    """``snapshot().stages`` es tupla (no lista) y los dicts no
    pueden mutar el estado interno."""
    tracker = ProgressTracker()
    tracker.begin("op", "label", ["s1"])
    snap1 = tracker.snapshot()
    assert isinstance(snap1.stages, tuple)
    # Intentar mutar la tupla debe fallar (tuplas son inmutables).
    try:
        snap1.stages[0]["status"] = "FAKE"  # type: ignore[index]
    except (TypeError, AttributeError):
        pass  # OK
    # El estado interno NO debe haberse corrompido.
    snap2 = tracker.snapshot()
    assert snap2.stages[0]["status"] == STAGE_PENDING


def test_clear_resets_to_empty() -> None:
    """``clear()`` resetea al estado vacío inicial."""
    tracker = ProgressTracker()
    tracker.begin("op", "label", ["a", "b"])
    tracker.start_stage("a")
    tracker.clear()
    snap = tracker.snapshot()
    assert snap.active is False
    assert snap.operation is None
    assert snap.label is None
    assert snap.total == 0
    assert snap.stages == ()
    assert snap.error is None


def test_finish_failure_marks_orphan_running_as_error() -> None:
    """``finish(success=False)`` marca stages huérfanos en ``running``
    como ``error`` con el mensaje."""
    tracker = ProgressTracker()
    tracker.begin("op", "label", ["a", "b"])
    tracker.start_stage("a")
    # b queda en pending (no se llegó a iniciar).
    tracker.finish(success=False, error="Algo reventó")
    snap = tracker.snapshot()
    a = next(s for s in snap.stages if s["id"] == "a")
    b = next(s for s in snap.stages if s["id"] == "b")
    assert a["status"] == STAGE_ERROR
    assert "Algo reventó" in (a["detail"] or "")
    # ``b`` sigue en pending — solo los huérfanos en running se promueven.
    assert b["status"] == STAGE_PENDING
    assert snap.active is False
    assert snap.error == "Algo reventó"


def test_finish_success_keeps_active_false() -> None:
    """``finish(success=True)`` deja ``active=False`` pero conserva
    los stages finalizados (para que la SPA los muestre unos segundos)."""
    tracker = ProgressTracker()
    tracker.begin("op", "label", ["a", "b", "c"])
    tracker.start_stage("a")
    tracker.finish_stage("a")
    tracker.finish(success=True)
    snap = tracker.snapshot()
    assert snap.active is False
    assert len(snap.stages) == 3  # Stages NO se borran
    assert snap.error is None
    assert snap.finished_at is not None


def test_concurrent_begin_does_not_corrupt() -> None:
    """Llamadas concurrentes a ``begin`` desde varios threads no
    corrompen el estado (test rápido con ThreadPoolExecutor).

    NOTA: con concurrencia real, múltiples ``begin()`` se pisan
    entre sí (el último gana, por diseño single-tenant). Lo único
    que verificamos es que el estado resultante sea **coherente**:
    ``active=False`` (cada worker llama a ``finish(success=True)``),
    ``total`` igual al tamaño de la lista ``stages`` declarada y
    los ``stages`` con estructura válida.
    """
    import concurrent.futures

    tracker = ProgressTracker()

    def worker(i: int) -> None:
        tracker.begin(f"op-{i}", f"label-{i}", ["s1", "s2"])
        tracker.start_stage("s1")
        tracker.finish_stage("s1")
        tracker.finish_stage("s2")
        tracker.finish(success=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futures = [ex.submit(worker, i) for i in range(20)]
        for f in futures:
            f.result()  # no debe levantar excepciones

    snap = tracker.snapshot()
    # Coherencia: cada worker hizo ``finish(success=True)``, por lo
    # que el último en escribir deja ``active=False``.
    assert snap.active is False
    # El último ``begin()`` ganó con 2 stages declarados.
    assert snap.total == 2
    # Estructura coherente: 2 stages con shape válido.
    assert len(snap.stages) == 2
    for s in snap.stages:
        assert "id" in s
        assert "status" in s
        assert s["status"] in {"pending", "running", "done", "error"}
