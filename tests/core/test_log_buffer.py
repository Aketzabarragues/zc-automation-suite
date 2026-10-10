"""Tests unitarios de ``core.runtime.log_buffer.LogBuffer``.

Cubre el contrato base del buffer sin publishers externos:
  - ``info()`` y ``warning()`` registran entries con ``level`` y ``message``.
  - ``snapshot()`` devuelve los entries en orden de insercion.
"""
from __future__ import annotations

from core.runtime.log_buffer import LogBuffer


def test_sin_hook_el_buffer_sigue_funcionando() -> None:
    """Backward compat: LogBuffer sin hook funciona como antes."""
    log_buffer = LogBuffer()
    log_buffer.info("hola")
    log_buffer.warning("cuidado")
    snapshot = log_buffer.snapshot()
    assert [e["level"] for e in snapshot] == ["info", "warning"]
    assert [e["message"] for e in snapshot] == ["hola", "cuidado"]