"""Tests del bridge logging <-> LogBuffer.

Cubre:
  - Registro de custom levels WEB (25) y OK (26).
  - Monkey-patch idempotente de ``Logger.web`` y ``Logger.ok``.
  - Mapeo de cada level Python a ``LogBuffer.level``.
  - Filtrado: INFO/DEBUG NO llegan al LogBuffer (solo archivo).
  - Idempotencia de ``install_log_buffer_handler()``.
  - Formato del mensaje con ``[<logger_name>]``.

Helper privado ``_make_isolated_handler()`` crea un ``LogBufferHandler``
con un ``LogBuffer(maxlen=10)`` propio y lo anade solo al logger del
test, sin tocar el root logger ni contaminar otros tests.
"""
from __future__ import annotations

import logging

import pytest

from core.infrastructure.log_web_bridge import (
    LogBufferHandler,
    OK_LEVEL,
    OK_LEVEL_NAME,
    WEB_LEVEL,
    WEB_LEVEL_NAME,
    install_log_buffer_handler,
    install_web_level,
)
from core.runtime.log_buffer import LogBuffer


def _make_isolated_handler() -> tuple[LogBufferHandler, LogBuffer]:
    """Crea un handler con buffer propio para tests aislados.

    No toca el root logger: el caller debe anadir el handler al logger
    especifico que use (``root.addHandler``) o configurar
    ``propagate=True`` para que el record suba hasta el root del test.
    """
    buf = LogBuffer(maxlen=10)
    handler = LogBufferHandler(level=WEB_LEVEL)
    # Sustituir el buffer global del handler por el nuestro.
    handler._buffer = buf
    return handler, buf


@pytest.fixture(autouse=True)
def _reset_bridge_state() -> None:
    """Quita cualquier ``LogBufferHandler`` del root tras cada test.

    Evita contaminacion entre tests si alguno olvido limpiar.
    """
    yield
    for h in list(logging.root.handlers):
        if isinstance(h, LogBufferHandler):
            logging.root.removeHandler(h)


# ── Tests de registro de levels ─────────────────────────────────────


def test_levels_registrados() -> None:
    """``WEB`` (25) y ``OK`` (26) aparecen en la tabla de ``logging``."""
    install_web_level()
    assert logging.getLevelName(WEB_LEVEL) == WEB_LEVEL_NAME
    assert logging.getLevelName(OK_LEVEL) == OK_LEVEL_NAME
    # No se pisan levels existentes.
    assert logging.getLevelName(logging.WARNING) == "WARNING"
    assert logging.getLevelName(logging.INFO) == "INFO"


def test_install_web_level_es_idempotente() -> None:
    """Llamar 2 veces no rompe ni duplica el monkey-patch."""
    install_web_level()
    install_web_level()
    # ``Logger.web`` y ``Logger.ok`` siguen siendo los mismos (o equivalentes).
    assert callable(getattr(logging.Logger, "web", None))
    assert callable(getattr(logging.Logger, "ok", None))


# ── Tests de enrutamiento por level ─────────────────────────────────


def test_logger_web_llega_a_log_buffer_con_level_info() -> None:
    """``logger.web(...)`` -> LogBuffer con ``level="info"`` (neutro)."""
    handler, buf = _make_isolated_handler()
    root = logging.getLogger("test_bridge.web")
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    root.web("hola web")
    snap = buf.snapshot()
    assert len(snap) == 1
    assert "test_bridge.web" in snap[0]["message"]
    assert "hola web" in snap[0]["message"]
    assert snap[0]["level"] == "info"


def test_logger_ok_llega_a_log_buffer_con_level_success() -> None:
    """``logger.ok(...)`` -> LogBuffer con ``level="success"`` (verde en SPA)."""
    handler, buf = _make_isolated_handler()
    root = logging.getLogger("test_bridge.ok")
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    root.ok("sync completo: 8 dispositivos")
    snap = buf.snapshot()
    assert len(snap) == 1
    assert "sync completo" in snap[0]["message"]
    assert snap[0]["level"] == "success"


def test_logger_info_NO_llega_a_log_buffer() -> None:
    """``logger.info(...)`` se queda en archivo; la web NO lo ve."""
    handler, buf = _make_isolated_handler()
    root = logging.getLogger("test_bridge.info")
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    root.info("ruido interno")
    assert buf.snapshot() == []


def test_logger_debug_NO_llega_a_log_buffer() -> None:
    """``logger.debug(...)`` idem."""
    handler, buf = _make_isolated_handler()
    root = logging.getLogger("test_bridge.debug")
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    root.debug("trace")
    assert buf.snapshot() == []


def test_logger_warning_llega_a_log_buffer_con_level_warning() -> None:
    """``logger.warning(...)`` -> LogBuffer ``level="warning"`` (amber)."""
    handler, buf = _make_isolated_handler()
    root = logging.getLogger("test_bridge.warn")
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    root.warning("compilacion parcial")
    snap = buf.snapshot()
    assert snap[0]["level"] == "warning"


def test_logger_error_llega_a_log_buffer_con_level_error() -> None:
    """``logger.error(...)`` -> LogBuffer ``level="error"`` (rojo)."""
    handler, buf = _make_isolated_handler()
    root = logging.getLogger("test_bridge.err")
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    root.error("commit fallo")
    snap = buf.snapshot()
    assert snap[0]["level"] == "error"


def test_ok_no_se_interpreta_como_warning() -> None:
    """``OK`` (26) cae en ``"success"``, NO en ``"warning"``.

    Cobertura explicita del riesgo del plan: como 26 esta adyacente a
    WARNING (30), el ``_map_level`` debe discriminar por rango
    ``OK_LEVEL <= pynum < WARNING``.
    """
    handler, buf = _make_isolated_handler()
    root = logging.getLogger("test_bridge.okwarn")
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    root.ok("cierre OK")
    snap = buf.snapshot()
    assert snap[0]["level"] == "success"


# ── Tests de instalacion en root ─────────────────────────────────────


def test_handler_idempotente_en_root() -> None:
    """Llamar ``install_log_buffer_handler()`` 2 veces no duplica handlers."""
    install_log_buffer_handler()
    install_log_buffer_handler()
    handlers = [
        h for h in logging.root.handlers if isinstance(h, LogBufferHandler)
    ]
    assert len(handlers) == 1


# ── Tests de formato del mensaje ────────────────────────────────────


def test_formato_mensaje_con_logger_name() -> None:
    """Mensaje final: ``[<logger.name>] <texto>``. Sin timestamp propio.

    El timestamp lo genera ``LogBuffer._push``; el handler solo
    aporta el ``[<name>]`` para que el operario vea el origen.
    """
    handler, buf = _make_isolated_handler()
    root = logging.getLogger("test_bridge.fmt")
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    root.warning("hola")
    msg = buf.snapshot()[0]["message"]
    assert msg.startswith("[test_bridge.fmt] ")
    assert "hola" in msg
    # El timestamp lo lleva el dict (no el ``message``); ``_push`` lo genera.
    assert "timestamp" in buf.snapshot()[0]
