"""Tests del decorador ``@log_ot_command`` (post-giro 'DEBUG by default').

Tras el giro estrategico de sept-2026, el decorador SOLO emite a
``logging.DEBUG``. Ya no acepta ``msg_in``/``msg_ok`` (eliminado en
el commit 2 del giro). Cubre:

  - Por defecto los mensajes van a DEBUG (no a web).
  - La firma sigue siendo ``@log_ot_command(name='...')``.
  - Back-compat: un handler decorado sigue siendo callable.
  - ``_sanitize_args`` y ``_summarize_result`` siguen disponibles
    para debug tecnico (no se han tocado).
"""
from __future__ import annotations

import io
import logging

import pytest

from core.infrastructure.tia.tia_helpers import log_ot_command
from core.infrastructure.log_web_bridge import install_web_level, WEB_LEVEL


@pytest.fixture(autouse=True)
def _install_web_levels() -> None:
    install_web_level()


@pytest.fixture
def capture_zc_tia_loop() -> io.StringIO:
    logger = logging.getLogger("zc.tia_loop")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield stream
    finally:
        logger.removeHandler(handler)


def test_mensajes_van_a_debug_por_defecto(
    capture_zc_tia_loop: io.StringIO,
) -> None:
    """Sin parametros extra, los mensajes son DEBUG (no WEB_LEVEL)."""
    @log_ot_command(name="my_handler")
    def _h(args: dict, tia_client: object) -> dict:
        return {"ok": True}

    _h({"plc_name": "ZC"}, None)

    out = capture_zc_tia_loop.getvalue()
    assert "OT[my_handler] args=" in out
    assert "OT[my_handler] OK en" in out


def test_nivel_es_debug_no_web(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """El level del record es DEBUG (10), no WEB_LEVEL (25).

    Asi la web no captura estos mensajes aunque el handler se llame
    muchas veces por sync.
    """
    import logging

    @log_ot_command(name="nivel_debug")
    def _h(args: dict, tia_client: object) -> dict:
        return {}

    logger = logging.getLogger("zc.tia_loop")
    with caplog.at_level(logging.DEBUG, logger="zc.tia_loop"):
        _h({}, None)

    debug_records = [
        r for r in caplog.records
        if r.name == "zc.tia_loop" and r.levelno == logging.DEBUG
    ]
    web_records = [
        r for r in caplog.records
        if r.name == "zc.tia_loop" and r.levelno == WEB_LEVEL
    ]
    assert any("OT[nivel_debug]" in r.getMessage() for r in debug_records)
    assert not web_records


def test_back_compat_handler_sigue_siendo_callable() -> None:
    """Tras decorar, el handler sigue siendo una funcion usable."""
    @log_ot_command(name="callable_test")
    def _h(args: dict, tia_client: object) -> dict:
        return {"value": 42}

    assert callable(_h)
    assert _h({}, None) == {"value": 42}


def test_sin_parametros_extra() -> None:
    """El decorador acepta solo ``name`` (no hay ``msg_in``/``msg_ok``)."""
    import inspect

    sig = inspect.signature(log_ot_command)
    params = list(sig.parameters.keys())
    assert "name" in params
    # No debe haber msg_in ni msg_ok (giro sept-2026 los elimino).
    assert "msg_in" not in params
    assert "msg_ok" not in params


def test_decorador_idempotente() -> None:
    """Aplicar a varios handlers no rompe."""

    @log_ot_command(name="h1")
    def _h1(args: dict, tia_client: object) -> dict:
        return {}

    @log_ot_command(name="h2")
    def _h2(args: dict, tia_client: object) -> dict:
        return {}

    assert callable(_h1) and callable(_h2)
    assert _h1({}, None) == {}
    assert _h2({}, None) == {}