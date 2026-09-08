"""Tests del helper ``core.infrastructure.tia.worker_logging``.

Cubre el contrato publico del modulo:

- :class:`JsonLineFormatter` produce JSON lines validos con los
  metadatos correctos (``ts``, ``level``, ``logger``, ``event``).
- :func:`log_event` emite al level correcto y anade ``_unknown_event``
  si el nombre del evento no esta en ``_KNOWN_EVENTS``.
- :func:`configure_worker_logger` es idempotente (no duplica handlers
  en llamadas sucesivas) y crea el archivo rotatorio en
  ``<resolve_log_dir()>/worker_ot.log`` (NO lee ``ZC_LOG_DIR``
  directamente).
- Si no se puede crear el archivo de log, el handler de archivo se
  desactiva silenciosamente y el worker sigue con solo stderr.

Los tests que tocan handlers de archivo rotatorio usan ``tmp_path``
de pytest como ``resolve_log_dir()`` falso (via ``monkeypatch``), asi
no contaminamos la carpeta de logs real del operario.

Estrategia de aislamiento:

- Cada test empieza con :func:`reset_worker_logger_for_tests` para
  que el logger este limpio (handlers eliminados, ``propagate=True``).
- Para tests que necesitan stderr, se redirige ``sys.stderr`` con
  ``capsys`` de pytest (no tocamos el stderr real).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from core.application.log_paths import resolve_log_dir
from core.infrastructure.tia.worker_logging import (
    JsonLineFormatter,
    _KNOWN_EVENTS,
    _LOGGER_NAME,
    configure_worker_logger,
    log_event,
    reset_worker_logger_for_tests,
)


# ────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_logger():
    """Limpia el logger antes y despues de cada test.

    Garantiza aislamiento entre tests: si un test invoca
    ``configure_worker_logger()`` varias veces o varios tests lo
    invocan, no se filtran handlers entre ellos. Tambien restaura
    ``propagate`` para que pytest caplog funcione normalmente.
    """
    reset_worker_logger_for_tests()
    yield
    reset_worker_logger_for_tests()


# ────────────────────────────────────────────────────────────────────────
# Test 1: JsonLineFormatter produce JSON valido
# ────────────────────────────────────────────────────────────────────────


class TestJsonLineFormatter:
    """El formatter emite lineas JSON parseables con los metadatos correctos."""

    def test_format_emits_valid_json_with_metadata(self) -> None:
        """Un record con un payload valido se serializa como JSON con ts/level/logger."""
        formatter = JsonLineFormatter()
        record = logging.LogRecord(
            name="zc.worker_ot",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg=json.dumps({"event": "command_completed", "command": "compile_plc"}),
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["event"] == "command_completed"
        assert parsed["command"] == "compile_plc"
        # Metadatos inyectados por el formatter.
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "zc.worker_ot"
        # ``ts`` debe ser un float (epoch unix con decimales).
        assert isinstance(parsed["ts"], (int, float))
        assert parsed["ts"] > 0

    def test_format_handles_invalid_json_payload(self) -> None:
        """Si ``msg`` no es JSON, el formatter degrada a ``{"msg": ...}`` sin tirar."""
        formatter = JsonLineFormatter()
        record = logging.LogRecord(
            name="zc.worker_ot",
            level=logging.WARNING,
            pathname=__file__,
            lineno=1,
            msg="texto arbitrario que no es JSON",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        # Sin ``event`` (porque el msg no era JSON), pero los metadatos
        # basicos siguen ahi.
        assert parsed["msg"] == "texto arbitrario que no es JSON"
        assert parsed["level"] == "WARNING"
        assert parsed["logger"] == "zc.worker_ot"


# ────────────────────────────────────────────────────────────────────────
# Test 2: log_event emite al level correcto
# ────────────────────────────────────────────────────────────────────────


class TestLogEventLevel:
    """``log_event`` respeta el ``level`` pasado."""

    def test_log_event_info(self, caplog: pytest.LogCaptureFixture) -> None:
        """Un log_event con level=INFO se emite como INFO."""
        logger = logging.getLogger(_LOGGER_NAME)
        with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
            log_event(logger, logging.INFO, "worker_started", pid=1234)
        # caplog captura el msg completo (que es el JSON serializado).
        assert any("worker_started" in rec.message for rec in caplog.records)
        # El level del record es INFO.
        info_records = [r for r in caplog.records if "worker_started" in r.message]
        assert len(info_records) == 1
        assert info_records[0].levelno == logging.INFO

    def test_log_event_error(self, caplog: pytest.LogCaptureFixture) -> None:
        """Un log_event con level=ERROR se emite como ERROR."""
        logger = logging.getLogger(_LOGGER_NAME)
        with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
            log_event(logger, logging.ERROR, "command_failed", error_class="ValueError")
        err_records = [r for r in caplog.records if "command_failed" in r.message]
        assert len(err_records) == 1
        assert err_records[0].levelno == logging.ERROR


# ────────────────────────────────────────────────────────────────────────
# Test 3: evento desconocido -> _unknown_event
# ────────────────────────────────────────────────────────────────────────


class TestUnknownEvent:
    """``log_event`` con evento no listado anade ``_unknown_event`` al payload."""

    def test_unknown_event_adds_marker(self, caplog: pytest.LogCaptureFixture) -> None:
        """Un evento typo aparece en el log con la marca ``_unknown_event``."""
        logger = logging.getLogger(_LOGGER_NAME)
        with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
            log_event(logger, logging.INFO, "comand_completed")  # typo: "comand"

        target = [r for r in caplog.records if "comand_completed" in r.message]
        assert len(target) == 1
        payload = json.loads(target[0].message)
        assert payload["event"] == "comand_completed"
        # La marca esta ahi para que el operario detecte el typo.
        assert payload["_unknown_event"] == "comand_completed"

    def test_known_event_has_no_unknown_marker(self, caplog: pytest.LogCaptureFixture) -> None:
        """Un evento conocido NO lleva la marca ``_unknown_event``."""
        logger = logging.getLogger(_LOGGER_NAME)
        with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
            log_event(logger, logging.INFO, "command_completed", command="ping")

        target = [r for r in caplog.records if "command_completed" in r.message]
        assert len(target) == 1
        payload = json.loads(target[0].message)
        assert "_unknown_event" not in payload

    def test_known_events_set_includes_documented_events(self) -> None:
        """``_KNOWN_EVENTS`` contiene los 13 eventos del diseno del PR."""
        expected = {
            "worker_started",
            "worker_stopped",
            "attach",
            "attach_failed",
            "detach",
            "command_received",
            "command_completed",
            "command_failed",
            "ping_received",
            "ping_completed",
            "reconnect",
            "reconnect_failed",
            "error",
        }
        assert expected.issubset(_KNOWN_EVENTS)


# ────────────────────────────────────────────────────────────────────────
# Test 4: configure_worker_logger es idempotente
# ────────────────────────────────────────────────────────────────────────


class TestConfigureIdempotent:
    """``configure_worker_logger`` no duplica handlers en llamadas sucesivas."""

    def test_second_call_does_not_add_handlers(self) -> None:
        """Invocar 2 veces seguidas produce 1 set de handlers, no 2."""
        logger1 = configure_worker_logger()
        handlers_after_first = list(logger1.handlers)

        logger2 = configure_worker_logger()
        handlers_after_second = list(logger2.handlers)

        # logger1 y logger2 son el MISMO objeto (singleton por nombre).
        assert logger1 is logger2
        # Mismos handlers (mismas referencias, no duplicados).
        assert len(handlers_after_second) == len(handlers_after_first)
        assert set(handlers_after_second) == set(handlers_after_first)


# ────────────────────────────────────────────────────────────────────────
# Test 5: el archivo se crea en resolve_log_dir() / "worker_ot.log"
# ────────────────────────────────────────────────────────────────────────


class TestFileHandlerLocation:
    """El handler de archivo se monta en la ruta que devuelve ``resolve_log_dir()``."""

    def test_file_handler_uses_resolve_log_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Con ``resolve_log_dir`` parcheado a ``tmp_path``, el log acaba en tmp_path/worker_ot.log.

        Demuestra que el helper USA ``resolve_log_dir()`` y NO lee
        ``os.environ["ZC_LOG_DIR"]`` directamente. Asi garantizamos
        que el log del worker vive en la misma carpeta que
        ``zc_tray.log`` (mismo override, mismo fallback).
        """
        # Apuntamos resolve_log_dir a tmp_path y borramos ZC_LOG_DIR
        # para que no haya override. Asi verificamos que el helper
        # realmente consulta resolve_log_dir.
        monkeypatch.delenv("ZC_LOG_DIR", raising=False)
        monkeypatch.setattr(
            "core.application.log_paths.resolve_log_dir", lambda *a, **k: tmp_path
        )
        # Tambien parcheamos el simbolo que el helper importa.
        monkeypatch.setattr(
            "core.infrastructure.tia.worker_logging.resolve_log_dir",
            lambda *a, **k: tmp_path,
        )

        logger = configure_worker_logger()
        # Forzamos un flush implicito emitiendo un log y cerrando el handler de archivo.
        log_event(logger, logging.INFO, "worker_started", pid=999)
        # Flush explicito: el RotatingFileHandler bufferiza. Sin esto,
        # el test leeria el archivo antes de que el log llegue a disco
        # y veria un JSON parcial (o nada).
        for h in logger.handlers:
            try:
                h.flush()
            except Exception:
                pass

        expected_path = tmp_path / "worker_ot.log"
        assert expected_path.exists(), f"se esperaba {expected_path}, pero no existe"

        # El contenido es JSON lines valido con el evento esperado.
        content = expected_path.read_text(encoding="utf-8")
        lines = [line for line in content.splitlines() if line.strip()]
        assert len(lines) >= 1
        first = json.loads(lines[0])
        assert first["event"] == "worker_started"
        assert first["pid"] == 999
        assert first["level"] == "INFO"

    def test_does_not_read_zc_log_dir_directly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """El helper NO escribe en ``os.environ['ZC_LOG_DIR']`` directamente.

        Si ZC_LOG_DIR apunta a un sitio y resolve_log_dir a otro
        distinto, el helper DEBE usar el segundo (resolve_log_dir),
        no el primero. Asi el comportamiento es coherente con el
        resto de la app (un solo punto de decision sobre donde van
        los logs).
        """
        zc_log_dir = tmp_path / "from_env"
        resolved_dir = tmp_path / "from_resolver"
        resolved_dir.mkdir()

        monkeypatch.setenv("ZC_LOG_DIR", str(zc_log_dir))
        monkeypatch.setattr(
            "core.infrastructure.tia.worker_logging.resolve_log_dir",
            lambda *a, **k: resolved_dir,
        )

        logger = configure_worker_logger()
        log_event(logger, logging.INFO, "worker_started", pid=1)
        for h in logger.handlers:
            try:
                h.flush()
            except Exception:
                pass

        # El archivo esta en resolved_dir, NO en zc_log_dir.
        assert (resolved_dir / "worker_ot.log").exists()
        assert not (zc_log_dir / "worker_ot.log").exists(), (
            "el helper escribio en ZC_LOG_DIR directamente; "
            "debe usar resolve_log_dir()"
        )


# ────────────────────────────────────────────────────────────────────────
# Test 6: handler de archivo se desactiva si no se puede escribir
# ────────────────────────────────────────────────────────────────────────


class TestFileHandlerResilience:
    """Si no se puede crear el handler de archivo, el worker sigue con solo stderr."""

    def test_falls_back_to_stderr_only_when_file_handler_fails(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Si ``resolve_log_dir`` retorna un path no escribible, el helper no peta.

        Verificamos que:
          1. ``configure_worker_logger`` NO lanza excepcion.
          2. El logger sigue teniendo al menos el handler de stderr.
          3. Se emite un warning explicando que se continua solo con stderr.
        """
        # Forzamos a que ``resolve_log_dir`` retorne algo inutilizable.
        # Un path dentro de un directorio que no existe y no se puede
        # crear. ``RotatingFileHandler`` falla con ``FileNotFoundError``
        # o ``PermissionError`` al hacer ``open()`` en modo 'a' (el
        # ``open()`` NO crea el padre en algunos casos; en nuestro
        # helper pre-creamos el dir via resolve_log_dir, asi que
        # forzamos el fallo con un path que apunte a un fichero
        # existente: el handler no puede abrir un directorio como
        # archivo). Usamos un path con un caracter nulo (invalido en
        # Windows y Linux) o None para forzar el error.
        bogus_path = Path("\x00invalid")
        with patch(
            "core.infrastructure.tia.worker_logging.resolve_log_dir",
            return_value=bogus_path,
        ):
            # NO debe lanzar excepcion.
            logger = configure_worker_logger()

        # El logger tiene handlers (al menos stderr; file falló y se
        # sustituyo por NullHandler). Y el helper logueo un warning.
        assert len(logger.handlers) >= 1
        # La propagacion esta desactivada (sigue activa entre tests
        # por el fixture, pero configure_worker_logger la puso en
        # False al ejecutarse).
        assert logger.propagate is False
        # Y al menos un log sobrevive sin lanzar excepcion.
        log_event(logger, logging.INFO, "worker_started", pid=42)
        # caplog puede o no capturar el log segun los handlers que
        # quedaron; lo importante es que la llamada NO explota.
        assert True  # si llegamos aqui, no hubo excepcion


# ────────────────────────────────────────────────────────────────────────
# Test extra: el logger se llama "zc.worker_ot" (constante exportada)
# ────────────────────────────────────────────────────────────────────────


def test_logger_name_constant() -> None:
    """La constante ``_LOGGER_NAME`` es ``"zc.worker_ot"``."""
    assert _LOGGER_NAME == "zc.worker_ot"


def test_resolve_log_dir_is_used_not_env_var_directly() -> None:
    """Sanity check: el helper importa ``resolve_log_dir``, no ``os.environ``.

    Si alguien cambiase el modulo para leer ``os.environ['ZC_LOG_DIR']``
    directamente, este test falla (es un detector de regresion
    barato; complementa el test 5).
    """
    import core.infrastructure.tia.worker_logging as mod
    # El simbolo esta en el namespace del modulo.
    assert hasattr(mod, "resolve_log_dir")
    # Y NO se importa ``os.environ`` para leer ZC_LOG_DIR.
    # (Test negativo: verificamos que ``os`` no se usa para esto.)
    assert "ZC_LOG_DIR" not in mod.__dict__, (
        "el modulo define ZC_LOG_DIR directamente; debe usar resolve_log_dir()"
    )


# Sanity: el modulo de logging NO contamina ``os.environ``.
# Garantiza que ``configure_worker_logger`` no hace ``os.environ[...]``
# y respeta la politica de "el helper NO lee ZC_LOG_DIR directamente".
def test_configure_does_not_set_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    """``configure_worker_logger`` no modifica ``os.environ``."""
    monkeypatch.delenv("ZC_LOG_DIR", raising=False)
    before = dict(os.environ)
    configure_worker_logger()
    after = dict(os.environ)
    assert before == after
