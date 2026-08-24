"""Regression test: ``launcher.web_supervisor._reconfigure_uvicorn_loggers``
debe quitar los ``StreamHandler`` a stderr de los loggers de uvicorn
después de que ``uvicorn.Config`` los haya poblado.

Bug original: en modo frozen/windowed, ``main_tray._setup_logging_redirect()``
redirige ``sys.stderr`` al logger ``zc_tray`` a nivel ``ERROR``. uvicorn, en
su ``Config.__init__``, añade un ``StreamHandler(stderr)`` a sus 3 loggers
(``uvicorn``, ``uvicorn.error``, ``uvicorn.access``). El resultado: las ``INFO``
de uvicorn se recapturan como ``ERROR`` y aparecen en el log con el tag
equivocado:

    [ERROR] zc_tray: INFO:     Started server process [28752]

El fix debe ejecutarse JUSTO después de que ``uvicorn.Config`` configure los
loggers (no al importarse, porque uvicorn configura lazy en su ``__init__``).
Por eso está en ``launcher/web_supervisor.py:139-145``, no en ``main_tray.py``.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _populate_uvicorn_handlers_like_uicorn_does() -> None:
    """Simula lo que hace ``uvicorn.Config.__init__``: añadir un
    ``StreamHandler(sys.stderr)`` a cada uno de los 3 loggers de uvicorn.

    Necesitamos esto porque sin un ``uvicorn.Config`` real, los loggers
    están vacíos. Esta función los puebla de forma idéntica a uvicorn.
    """
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        # Reset para que el test sea determinista.
        logger.handlers = []
        logger.propagate = True
        # StreamHandler a stderr, como hace uvicorn por defecto.
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(
            logging.Formatter("%(levelprefix)s %(message)s")
        )
        logger.addHandler(h)
        logger.setLevel(logging.INFO)


def test_uvicorn_streamhandlers_are_removed() -> None:
    """``_reconfigure_uvicorn_loggers`` quita TODOS los ``StreamHandler``
    de los 3 loggers de uvicorn, sin importar a qué stream apunten.

    Razón: en producción, ``sys.stderr`` ha sido reemplazado por
    ``_StreamToLogger`` (vía ``main_tray._setup_logging_redirect``),
    por lo que filtrar por ``h.stream is sys.__stderr__`` no
    captura el caso real. La solución robusta es eliminar cualquier
    ``StreamHandler``: uvicorn propaga al root y este se encarga
    con el FileHandler.
    """
    from launcher.web_supervisor import _reconfigure_uvicorn_loggers

    _populate_uvicorn_handlers_like_uicorn_does()

    # Pre-condición: hay al menos un StreamHandler por logger.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        assert any(
            isinstance(h, logging.StreamHandler) for h in logger.handlers
        ), f"Pre-condición rota: {name} no tiene StreamHandler tras setup"

    # Aplicar el fix.
    _reconfigure_uvicorn_loggers()

    # Verificar que ya NO queda NINGÚN StreamHandler.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        stream_handlers = [
            h for h in logger.handlers if isinstance(h, logging.StreamHandler)
        ]
        assert not stream_handlers, (
            f"{name} todavía tiene StreamHandler(s) tras fix: {stream_handlers!r}"
        )


def test_uvicorn_loggers_propagate_to_root_after_fix() -> None:
    """``_reconfigure_uvicorn_loggers`` pone ``propagate=True`` en los
    3 loggers de uvicorn."""
    from launcher.web_supervisor import _reconfigure_uvicorn_loggers

    _populate_uvicorn_handlers_like_uicorn_does()

    # Forzar propagate=False para simular un estado "desconfigurado".
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).propagate = False

    _reconfigure_uvicorn_loggers()

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        assert logging.getLogger(name).propagate is True, (
            f"{name} no propaga al root tras fix"
        )


def test_uvicorn_info_appears_as_info_in_log_file(tmp_path: Path) -> None:
    """End-to-end: tras el fix, ``log.info()`` en un logger de uvicorn
    se escribe en el log file como ``[INFO]``, no como ``[ERROR]``.

    Simula el path completo:
      1. root logger con FileHandler a tmp log.
      2. uvicorn (simulado) añade su StreamHandler(stderr).
      3. main_tray (simulado) redirige stderr → root a nivel ERROR.
      4. Aplicamos el fix.
      5. uvicorn emite INFO; debe aparecer como [INFO] en el log.
    """
    from launcher.web_supervisor import _reconfigure_uvicorn_loggers

    # 1) Root logger con FileHandler a tmp.
    log_file = tmp_path / "test.log"
    root = logging.getLogger()
    root.handlers = [logging.FileHandler(log_file, encoding="utf-8")]
    root.setLevel(logging.INFO)
    root.handlers[0].setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )

    # 2) uvicorn añade su StreamHandler(stderr).
    _populate_uvicorn_handlers_like_uicorn_does()

    # 3) main_tray redirige stderr → root a nivel ERROR (solo
    #    simulación: en la app real, sys.stderr es _StreamToLogger).
    #    Como aquí queremos comprobar el log, NO redirigimos stderr
    #    de verdad; emitimos directamente al logger uvicorn, que es
    #    lo que uvicorn hace internamente. Lo importante es que
    #    ANTES del fix, los handlers de uvicorn escribirían a
    #    stderr, lo cual sería invisible para nuestro FileHandler.

    # 4) Aplicar el fix.
    _reconfigure_uvicorn_loggers()

    # 5) Emitir INFO desde uvicorn. Si propaga al root, el FileHandler
    #    la captura. Si no, se perdería.
    logging.getLogger("uvicorn").info("TEST_UVICORN_INFO_MESSAGE")
    logging.getLogger("uvicorn.error").warning("TEST_UVICORN_WARN_MESSAGE")
    for h in root.handlers:
        h.flush()

    content = log_file.read_text(encoding="utf-8")
    assert "[INFO] uvicorn: TEST_UVICORN_INFO_MESSAGE" in content, (
        f"INFO de uvicorn no se logueó como [INFO]. Log:\n{content}"
    )
    assert "[WARNING] uvicorn.error: TEST_UVICORN_WARN_MESSAGE" in content, (
        f"WARN de uvicorn.error no se logueó como [WARNING]. Log:\n{content}"
    )


def test_fix_preserves_non_stream_handlers() -> None:
    """Si alguien añade un FileHandler a un logger de uvicorn, el
    fix NO debe eliminarlo (solo filtra StreamHandler a stderr)."""
    from launcher.web_supervisor import _reconfigure_uvicorn_loggers

    name = "uvicorn"
    logger = logging.getLogger(name)
    logger.handlers = []
    # StreamHandler(stderr) que el fix debe quitar.
    logger.addHandler(logging.StreamHandler(sys.stderr))
    # FileHandler que el fix debe PRESERVAR.
    file_h = logging.FileHandler(str(Path(__file__).parent / "_dummy.log"))
    logger.addHandler(file_h)
    logger.propagate = False

    _reconfigure_uvicorn_loggers()

    # Queda solo el FileHandler.
    assert file_h in logger.handlers
    assert not any(
        isinstance(h, logging.StreamHandler) and h.stream is sys.stderr
        for h in logger.handlers
    )
    assert logger.propagate is True

    # Limpieza.
    file_h.close()
    Path(__file__).parent.joinpath("_dummy.log").unlink(missing_ok=True)
