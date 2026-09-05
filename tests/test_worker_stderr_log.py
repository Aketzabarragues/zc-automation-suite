"""Tests del log de stderr del worker persistente (sept-2026).

Regresion: el subproceso del worker escribe errores a
``sys.stderr.write(...)`` directamente (no usa ``logging`` ni el
logger nativo de Siemens para todo). Si nadie lee stderr, los
mensajes se pierden. El gateway ahora lee stderr y los loguea a
``worker_openness.log`` (misma carpeta que ``zc_tray.log``).

Estos tests verifican:
  - El helper ``_get_worker_stderr_logger`` configura el logger
    correctamente (FileHandler al path correcto, propagate=False,
    singleton).
  - ``_read_worker_stderr_forever`` lee stderr y loguea al logger.
  - El cleanup cancela la task en ``_kill_persistent_worker``.
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── Helper: _get_worker_stderr_logger ──────────────────────────────


def test_helper_returns_singleton_logger() -> None:
    """El helper retorna el mismo logger en llamadas repetidas
    (singleton) para no duplicar FileHandlers."""
    from core.infrastructure.gateway import _get_worker_stderr_logger

    log1 = _get_worker_stderr_logger()
    log2 = _get_worker_stderr_logger()
    assert log1 is log2, (
        "_get_worker_stderr_logger debe retornar el mismo logger "
        "cada vez (singleton) para no duplicar FileHandlers."
    )
    assert log1.name == "zc.worker_stderr"
    assert log1.propagate is False, (
        "El logger no debe propagar al root (evita duplicacion en "
        "zc_tray.log)."
    )
    assert log1.level <= logging.INFO, (
        "El logger debe aceptar mensajes INFO (los stderr.write "
        "del worker se loguean como INFO)."
    )


def test_helper_attaches_file_handler_to_worker_openness_log() -> None:
    """El helper crea un FileHandler que apunta a
    ``worker_openness.log`` dentro de la carpeta de logs del
    repo (mismo path que ``zc_tray.log``)."""
    from core.infrastructure.gateway import _get_worker_stderr_logger
    from core.application.log_paths import resolve_log_dir

    log = _get_worker_stderr_logger()
    file_handlers = [h for h in log.handlers if isinstance(h, logging.FileHandler)]
    assert file_handlers, (
        "El logger debe tener al menos un FileHandler apuntando a "
        "worker_openness.log."
    )

    expected_dir = resolve_log_dir()
    expected_path = expected_dir / "worker_openness.log"
    actual_paths = [h.baseFilename for h in file_handlers]
    assert any(str(expected_path) in p for p in actual_paths), (
        f"FileHandler debe apuntar a {expected_path}, pero apunta a "
        f"{actual_paths}."
    )


# ── Reader: _read_worker_stderr_forever ────────────────────────────


def test_reader_method_exists() -> None:
    """El gateway expone el reader de stderr como metodo."""
    from core.infrastructure.gateway import TIAProcessGateway
    g = TIAProcessGateway(persistent=False)
    assert hasattr(g, "_read_worker_stderr_forever"), (
        "TIAProcessGateway debe tener un metodo "
        "_read_worker_stderr_forever() (sept-2026)."
    )
    assert asyncio.iscoroutinefunction(g._read_worker_stderr_forever), (
        "_read_worker_stderr_forever debe ser una coroutine."
    )


def test_reader_writes_stderr_lines_to_logger(tmp_path) -> None:
    """Test funcional: dado un subproceso mock con un stderr que
    emite 2 lineas, el reader las loguea al archivo de log."""
    from core.infrastructure.gateway import (
        TIAProcessGateway,
        _get_worker_stderr_logger,
    )

    # Mock del proc con un stderr que emite 2 lineas y luego EOF.
    fake_proc = MagicMock()
    lines = [
        b"[WORKER LOOP ERROR] attach failed: COMException\n",
        b"[WORKER LOOP ERROR] retrying...\n",
        b"",  # EOF
    ]
    fake_proc.stderr = MagicMock()
    fake_proc.stderr.readline = AsyncMock(side_effect=lines)

    g = TIAProcessGateway(persistent=False)
    g._worker_proc = fake_proc

    # Usar un logger de prueba para evitar contaminar el log real.
    test_log = logging.getLogger("test.worker_stderr")
    test_log.handlers.clear()
    test_log.setLevel(logging.INFO)
    test_log.propagate = False
    log_file = tmp_path / "test_worker_openness.log"
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    test_log.addHandler(handler)

    # Patch el helper para retornar nuestro logger de prueba.
    with pytest.MonkeyPatch.context() as mp:
        from core.infrastructure import gateway as gw_mod
        mp.setattr(gw_mod, "_get_worker_stderr_logger", lambda: test_log)
        asyncio.run(g._read_worker_stderr_forever())

    handler.close()
    content = log_file.read_text(encoding="utf-8")
    assert "[WORKER LOOP ERROR] attach failed: COMException" in content
    assert "[WORKER LOOP ERROR] retrying..." in content
    assert content.count("\n") >= 2, (
        "El reader debe haber logueado al menos 2 lineas."
    )


def test_reader_handles_eof_gracefully(tmp_path) -> None:
    """Si el stderr devuelve EOF (b'') inmediatamente, el reader
    sale sin crashear (no loguea nada)."""
    from core.infrastructure.gateway import TIAProcessGateway

    fake_proc = MagicMock()
    fake_proc.stderr = MagicMock()
    fake_proc.stderr.readline = AsyncMock(return_value=b"")  # EOF

    g = TIAProcessGateway(persistent=False)
    g._worker_proc = fake_proc

    # Patch el logger para evitar contaminar el log real.
    test_log = logging.getLogger("test.eof_graceful")
    test_log.handlers.clear()
    test_log.setLevel(logging.INFO)
    test_log.propagate = False
    log_file = tmp_path / "eof.log"
    handler = logging.FileHandler(log_file, encoding="utf-8")
    test_log.addHandler(handler)

    with pytest.MonkeyPatch.context() as mp:
        from core.infrastructure import gateway as gw_mod
        mp.setattr(gw_mod, "_get_worker_stderr_logger", lambda: test_log)
        # No debe lanzar.
        asyncio.run(g._read_worker_stderr_forever())

    handler.close()
    assert log_file.read_text(encoding="utf-8") == ""


def test_reader_handles_invalid_utf8_gracefully(tmp_path) -> None:
    """Si el stderr emite bytes que no son UTF-8 validos, el reader
    los decodifica con errors='replace' (no crashea)."""
    from core.infrastructure.gateway import TIAProcessGateway

    # 0x8d no es UTF-8 valido (cp1252 es valido pero UTF-8 no).
    fake_proc = MagicMock()
    fake_proc.stderr = MagicMock()
    fake_proc.stderr.readline = AsyncMock(
        side_effect=[b"[WORKER] \x8d bad byte\n", b""]
    )

    g = TIAProcessGateway(persistent=False)
    g._worker_proc = fake_proc

    test_log = logging.getLogger("test.invalid_utf8")
    test_log.handlers.clear()
    test_log.setLevel(logging.INFO)
    test_log.propagate = False
    log_file = tmp_path / "invalid.log"
    handler = logging.FileHandler(log_file, encoding="utf-8")
    test_log.addHandler(handler)

    with pytest.MonkeyPatch.context() as mp:
        from core.infrastructure import gateway as gw_mod
        mp.setattr(gw_mod, "_get_worker_stderr_logger", lambda: test_log)
        # No debe lanzar.
        asyncio.run(g._read_worker_stderr_forever())

    handler.close()
    # El byte invalido se reemplaza con el caracter Unicode replacement.
    content = log_file.read_text(encoding="utf-8")
    assert "[WORKER]" in content
    # Verifica que NO lanzo excepcion (es decir, el test llego hasta aqui).


# ── Cleanup: _kill_persistent_worker cancela la task ────────────────


def test_init_persistent_initializes_stderr_task_field() -> None:
    """El ``__init__`` con ``persistent=True`` inicializa
    ``_stderr_task`` a ``None``. Necesario para que el cleanup
    de ``_kill_persistent_worker`` y el state-tracking funcionen."""
    from core.infrastructure.gateway import TIAProcessGateway

    g = TIAProcessGateway(persistent=True)
    assert hasattr(g, "_stderr_task"), (
        "TIAProcessGateway(persistent=True) debe tener _stderr_task."
    )
    assert g._stderr_task is None, (
        "Recién construido, _stderr_task debe ser None (se setea "
        "cuando se llama a _start_persistent_worker)."
    )


def test_kill_persistent_worker_cancels_stderr_task() -> None:
    """``_kill_persistent_worker`` cancela el ``_stderr_task`` (lo
    mismo que hace con ``_reader_task``). Si no se cancela, la
    task queda zombie consumiendo stderr de un proc muerto."""
    from core.infrastructure.gateway import TIAProcessGateway
    from unittest.mock import AsyncMock

    g = TIAProcessGateway(persistent=True)
    fake_task = MagicMock()
    fake_task.done.return_value = False
    g._stderr_task = fake_task
    g._worker_proc = MagicMock()
    g._worker_proc.returncode = None
    # El proc mock: terminate() es no-op, wait() retorna OK, kill() no-op.
    g._worker_proc.terminate = MagicMock()
    g._worker_proc.kill = MagicMock()
    g._worker_proc.wait = AsyncMock(return_value=0)

    asyncio.run(g._kill_persistent_worker())

    # El _stderr_task debe haber sido cancelado y puesto a None.
    assert fake_task.cancel.call_count >= 1, (
        "_kill_persistent_worker debe cancelar el _stderr_task."
    )
    assert g._stderr_task is None, (
        "_stderr_task debe quedar a None tras _kill_persistent_worker."
    )


def test_init_persistent_initializes_stderr_task_field() -> None:
    """El ``__init__`` con ``persistent=True`` inicializa
    ``_stderr_task`` a ``None``. Necesario para que el cleanup
    de ``_kill_persistent_worker`` y el state-tracking funcionen."""
    from core.infrastructure.gateway import TIAProcessGateway

    g = TIAProcessGateway(persistent=True)
    assert hasattr(g, "_stderr_task"), (
        "TIAProcessGateway(persistent=True) debe tener _stderr_task."
    )
    assert g._stderr_task is None, (
        "Recién construido, _stderr_task debe ser None (se setea "
        "cuando se llama a _start_persistent_worker)."
    )
