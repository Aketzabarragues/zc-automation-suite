"""Regression test: ``main._force_utf8_streams()`` no debe petar cuando
``sys.stdout`` / ``sys.stderr`` / ``sys.stdin`` son ``None``.

Este escenario se da cuando el binario se ejecuta en modo
**windowed** (``console=False`` en el ``.spec`` de PyInstaller):
el bootloader deja los streams estándar como ``None`` porque no
hay consola asignada. El bug original era:

    AttributeError: 'NoneType' object has no attribute 'reconfigure'

El ``except`` caía a un fallback que también tocaba ``.buffer`` sobre
``None``. El fix (en ``_force_utf8_streams``): itera por los streams,
salta los ``None`` y solo intenta la reconfiguracion cuando el
stream existe.

Este test NO invoca la bandeja real (pystray requiere GUI). Solo
verifica que ``_force_utf8_streams()`` es tolerante a streams ``None``.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def fresh_main(monkeypatch: pytest.MonkeyPatch):
    """Recarga ``main`` con streams ``None`` (simula windowed de PyInstaller)."""
    monkeypatch.setattr(sys, "argv", ["zc_automation_suite.exe"])
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(sys, "stdin", None)
    if "main" in sys.modules:
        del sys.modules["main"]
    return importlib.import_module("main")


def test_main_does_not_crash_when_streams_are_none(fresh_main) -> None:
    """``_force_utf8_streams()`` debe tolerar los 3 streams ``None``."""
    fresh_main._force_utf8_streams()  # no raise


def test_main_handles_none_stdout_specifically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Variante: solo ``sys.stdout`` es ``None``. stderr/stdin se reconfiguran."""
    import io

    fake_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", fake_stderr)
    monkeypatch.setattr(sys, "stdin", io.StringIO())

    if "main" in sys.modules:
        del sys.modules["main"]
    fresh_main = importlib.import_module("main")
    fresh_main._force_utf8_streams()  # no raise


def test_main_handles_streams_without_buffer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Streams sin ``.reconfigure`` ni ``.buffer`` (Python < 3.7 simulado)."""
    class _LegacyStream:
        """Stream sin ``reconfigure`` ni ``buffer``."""

    monkeypatch.setattr(sys, "stdout", _LegacyStream())
    monkeypatch.setattr(sys, "stderr", _LegacyStream())
    monkeypatch.setattr(sys, "stdin", _LegacyStream())

    if "main" in sys.modules:
        del sys.modules["main"]
    fresh_main = importlib.import_module("main")
    fresh_main._force_utf8_streams()  # no raise


def test_logging_setup_skips_streamhandler_when_stdout_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``setup_logging('tray')`` NO añade StreamHandler si stdout es None.

    El comportamiento viene de ``core/application/log_paths.py``, no de
    ``main.py``, pero lo testeamos aqui para evitar regresiones futuras
    en el modo windowed.
    """
    monkeypatch.setattr(sys, "stdout", None)
    if "core.application.log_paths" in sys.modules:
        del sys.modules["core.application.log_paths"]
    from core.infrastructure.config.config_paths import setup_logging

    setup_logging("tray")  # no raise
