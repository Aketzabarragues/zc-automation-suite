"""Tests del silenciamiento de loggers externos ruidosos.

El operario reporto que, con root en DEBUG, ``logs/zc.log`` se llenaba
de:

  - ``asyncio``: "Using proactor: IocpProactor" cada ~100ms exactos.
  - ``PIL.Image`` / ``PIL.PngImagePlugin``: ~49 lineas al importar Pillow.
  - ``werkzeug``: 1 INFO por cada HTTP request.
  - ``urllib3`` / ``httpcore`` / ``httpx``: DEBUG de pool/http.

Estos NO son errores nuestros: son ruido operacional de librerias de
terceros. La funcion ``silence_noisy_loggers()`` los sube a ``WARNING``
para que solo aparezcan cuando ocurra algo realmente anomalo.

Los tests verifican:

  - La funcion setea ``WARNING`` en los 8 loggers de ``_NOISY_LOGGERS``.
  - NO toca loggers nuestros (``zc.*``, ``core.*``, ``areas.*``).
  - Es idempotente (llamar 2 veces da el mismo resultado).
  - ``setup_logging()`` la invoca (smoke de integracion).
"""
from __future__ import annotations

import logging

import pytest

from core.infrastructure.config.config_paths import (
    _NOISY_LOGGERS,
    setup_logging,
    silence_noisy_loggers,
)


@pytest.fixture(autouse=True)
def _restore_logger_levels():
    """Restaura los levels originales de los loggers ruidosos tras cada test.

    Sin esto, contaminariamos el resto de la sesion pytest (los demas
    tests verian ``asyncio`` en WARNING cuando esperan NOTSET/DEBUG).
    """
    originals: dict[str, int] = {}
    for name in _NOISY_LOGGERS:
        originals[name] = logging.getLogger(name).level
    yield
    for name, level in originals.items():
        logging.getLogger(name).setLevel(level)


def test_silence_noisy_loggers_setea_warning_en_lista_completa() -> None:
    """Los 8 loggers de la lista quedan en WARNING tras la llamada."""
    silence_noisy_loggers()

    for name in _NOISY_LOGGERS:
        logger = logging.getLogger(name)
        assert logger.level == logging.WARNING, (
            f"{name!r} deberia estar en WARNING tras silence_noisy_loggers(); "
            f"tiene level={logger.level} ({logging.getLevelName(logger.level)})."
        )


def test_silence_noisy_loggers_no_toca_loggers_nuestros() -> None:
    """Loggers ``zc.*``, ``core.*`` y ``areas.*`` NO se modifican."""
    # Forzamos un level conocido en un logger nuestro para detectar cambios.
    zc_test = logging.getLogger("zc.test_no_silence")
    zc_test.setLevel(logging.DEBUG)
    core_test = logging.getLogger("core.test_no_silence")
    core_test.setLevel(logging.INFO)
    areas_test = logging.getLogger("areas.test_no_silence")
    areas_test.setLevel(logging.WARNING)

    silence_noisy_loggers()

    assert zc_test.level == logging.DEBUG
    assert core_test.level == logging.INFO
    assert areas_test.level == logging.WARNING


def test_silence_noisy_loggers_es_idempotente() -> None:
    """Llamar 2 veces seguidas no rompe ni cambia el resultado."""
    silence_noisy_loggers()
    first_levels = {n: logging.getLogger(n).level for n in _NOISY_LOGGERS}

    silence_noisy_loggers()
    second_levels = {n: logging.getLogger(n).level for n in _NOISY_LOGGERS}

    assert first_levels == second_levels
    for name in _NOISY_LOGGERS:
        assert second_levels[name] == logging.WARNING


def test_setup_logging_invoca_silence_noisy_loggers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``setup_logging()`` llama a ``silence_noisy_loggers()`` internamente.

    Usa ``monkeypatch.setattr`` con un ``MagicMock`` para detectar la
    llamada sin tener que re-parsear todo el archivo.
    """
    from unittest.mock import MagicMock

    import core.infrastructure.config.config_paths as cfg

    mock_silence = MagicMock(wraps=cfg.silence_noisy_loggers)
    monkeypatch.setattr(cfg, "silence_noisy_loggers", mock_silence)

    setup_logging(mode="default")

    mock_silence.assert_called_once_with()


def test_logger_externo_en_warning_no_emite_a_handler(
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Smoke: tras silenciar, ``logger.debug`` externo NO llega al handler.

    Capturamos con ``caplog`` (que escucha a nivel de pytest) para
    verificar que el silencio es efectivo. Usamos ``asyncio`` como
    ejemplo representativo.
    """
    silence_noisy_loggers()

    with caplog.at_level(logging.DEBUG):
        logging.getLogger("asyncio").debug("ESTO NO DEBE SALIR")
        logging.getLogger("werkzeug").info("ESTO TAMPOCO")

    # ``caplog.records`` solo incluye lo que paso el filtro; si los
    # loggers externos estan en WARNING, sus DEBUG/INFO quedan filtrados
    # antes de llegar al handler de caplog.
    captured_texts = [r.getMessage() for r in caplog.records]
    assert not any("ESTO NO DEBE SALIR" in t for t in captured_texts)
    assert not any("ESTO TAMPOCO" in t for t in captured_texts)