"""Tests unitarios de ``core.runtime.progress_buffer.ProgressTracker``.

Cubre el contrato base del tracker sin publishers externos:
  - ``begin`` / ``start_stage`` / ``finish_stage`` actualizan ``snapshot()``.
  - ``snapshot.active``, ``current``, ``total`` y ``percent`` reflejan el estado.
"""
from __future__ import annotations

from core.runtime.progress_buffer import ProgressTracker


def test_sin_hook_el_tracker_sigue_funcionando() -> None:
    """Backward compat: tracker sin hook se comporta identico al de antes."""
    tracker = ProgressTracker()  # sin on_publish
    tracker.begin("op", "Op", ["s1"])
    tracker.start_stage("s1")
    tracker.finish_stage("s1")
    snapshot = tracker.snapshot()
    assert snapshot.active is True
    assert snapshot.current == 1
    assert snapshot.total == 1
    assert snapshot.percent == 100