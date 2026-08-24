"""DEPRECATED: este test fue reemplazado por
``tests/test_uvicorn_loggers_reconfig.py``.

Razón: el fix de uvicorn NO debe estar en ``main_tray._setup_logging_redirect``
(que se ejecuta al principio de ``main()``, antes de que uvicorn haya
importado y configurado sus loggers). Debe estar en
``launcher/web_supervisor._reconfigure_uvicorn_loggers``, llamado JUSTO
después de instanciar ``uvicorn.Config`` (que es cuando uvicorn añade
sus handlers). Ver tests/test_uvicorn_loggers_reconfig.py.

Este archivo se mantiene como stub para evitar reintroducir tests
sobre el fix incorrecto. Se puede eliminar en cualquier momento.
"""
import pytest


def test_deprecated_file_is_just_a_stub() -> None:
    """Test trivial para que pytest no marque el archivo como vacío."""
    assert True
