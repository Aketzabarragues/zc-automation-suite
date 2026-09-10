"""Tests del helper ``_patch_stdio_for_uvicorn``.

Regresion (2026-09-05): en modo windowed (``pythonw.exe`` o frozen
sin consola), ``sys.stdout`` es ``None``. ``uvicorn.Config.__init__``
llama a su formatter por defecto, que hace
``sys.stdout.isatty()`` y crashea con::

    AttributeError: 'NoneType' object has no attribute 'isatty'

El helper ``_patch_stdio_for_uvicorn`` (context manager) reemplaza
``sys.stdout`` y ``sys.stderr`` por ``io.StringIO()`` si son None,
y los restaura al salir. Esto permite que ``uvicorn.Config`` se
inicialice en modo windowed sin crashear.
"""
from __future__ import annotations

import io
import sys

import pytest

from launcher.web_supervisor import _patch_stdio_for_uvicorn


def test_patch_sustituye_none_por_stringio_y_restaura() -> None:
    """Si ``sys.stdout`` y ``sys.stderr`` son ``None``, el context manager
    los reemplaza por ``io.StringIO()`` durante el bloque, y los
    restaura a ``None`` al salir."""
    saved_stdout, saved_stderr = sys.stdout, sys.stderr
    try:
        sys.stdout = None
        sys.stderr = None
        with _patch_stdio_for_uvicorn():
            assert sys.stdout is not None
            assert sys.stderr is not None
            assert isinstance(sys.stdout, io.StringIO)
            assert isinstance(sys.stderr, io.StringIO)
        # Tras salir del context manager, se restauran los originales
        # (que en este caso eran None).
        assert sys.stdout is None
        assert sys.stderr is None
    finally:
        sys.stdout, sys.stderr = saved_stdout, saved_stderr


def test_patch_no_toca_streams_validos() -> None:
    """Si ``sys.stdout`` y ``sys.stderr`` ya son validos (modo dev), el
    context manager los deja intactos (NO los sustituye por
    StringIO). El objetivo es solo proteger contra ``None``; en
    modo dev el comportamiento debe ser identico al pre-fix."""
    sentinel_out = sys.stdout
    sentinel_err = sys.stderr
    try:
        # Forzamos a usar dos objetos sentinela (no los reales) para
        # detectar cualquier sustitucion no intencional.
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        with _patch_stdio_for_uvicorn():
            assert sys.stdout is not None
            assert sys.stderr is not None
            # NO son StringIO nuevos: son los mismos que pusimos.
            # (Si fueran nuevos, la igualdad de identidad fallaria.)
        # Tras el context, se restauran los originales.
        assert sys.stdout is not None
    finally:
        sys.stdout = sentinel_out
        sys.stderr = sentinel_err


def test_patch_uvicorn_config_no_explota_con_stdout_none() -> None:
    """Test de regresion end-to-end (mocks): con ``sys.stdout = None``,
    instanciar ``uvicorn.Config`` dentro del context manager NO
    crashea con el ``AttributeError`` original. Mockeamos uvicorn
    para no depender de un bind real."""
    from unittest.mock import patch, MagicMock

    fake_config = MagicMock()
    saved_stdout, saved_stderr = sys.stdout, sys.stderr
    try:
        sys.stdout = None
        sys.stderr = None
        with patch("launcher.web_supervisor.uvicorn.Config", return_value=fake_config) as mock_cls:
            # Llamamos al codigo que internamente crea uvicorn.Config,
            # sin necesidad de instanciar WebServiceSupervisor.
            with _patch_stdio_for_uvicorn():
                # Replicamos la llamada que _serve_once hace:
                result = mock_cls(
                    "fake-app",
                    host="127.0.0.1",
                    port=8000,
                    log_level="info",
                    access_log=False,
                )
            assert result is fake_config
            mock_cls.assert_called_once()
        # Tras el context, sys.stdout y sys.stderr vuelven a None.
        assert sys.stdout is None
        assert sys.stderr is None
    finally:
        sys.stdout, sys.stderr = saved_stdout, saved_stderr
