r"""Regression test: ``main_tray.main()`` no debe petar cuando
``sys.stdout`` / ``sys.stderr`` / ``sys.stdin`` son ``None``.

Este escenario se da cuando el binario se ejecuta en modo
**windowed** (``console=False`` en el ``.spec`` de PyInstaller):
el bootloader deja los streams estándar como ``None`` porque no
hay consola asignada. El bug original (visto en
``dist\zc_automation_suite.exe`` tras el primer build) era:

    AttributeError: 'NoneType' object has no attribute 'reconfigure'
  During handling of the above exception, another exception occurred:
    AttributeError: 'NoneType' object has no attribute 'buffer'

El ``except`` caía a un fallback que también tocaba ``.buffer`` sobre
``None``. El fix itera por los streams, salta los ``None`` y solo
intenta la reconfiguración / fallback cuando el stream existe.

Este test NO invoca la bandeja real (pystray requiere GUI). Solo
verifica que el bloque de setup de UTF-8 al inicio de ``main()``
es tolerante a streams ``None``.
"""
from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def fresh_main_tray(monkeypatch: pytest.MonkeyPatch):
    """Recarga ``main_tray`` con ``sys.argv`` controlado (sin ``--worker``)
    y streams ``None`` para forzar el path windowed."""
    monkeypatch.setattr(sys, "argv", ["zc_automation_suite.exe"])
    # Forzar streams None: simula el modo windowed de PyInstaller.
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(sys, "stdin", None)

    # El módulo tiene un setup module-level (logging) que ya consumió
    # los streams reales. Recargamos para que ``_setup_logging_redirect``
    # se evalúe de nuevo con el ``sys`` parchado.
    if "main_tray" in sys.modules:
        del sys.modules["main_tray"]
    return importlib.import_module("main_tray")


def test_main_does_not_crash_when_streams_are_none(
    fresh_main_tray, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``main()`` debe tolerar streams ``None`` (modo windowed).

    No podemos invocar ``main()`` completa porque arrancaría
    pystray / WebServiceSupervisor y eso requiere GUI. En su lugar,
    patcheamos el ``__main__`` block (no se ejecuta en import) y
    validamos que las primeras líneas de ``main()`` (UTF-8 reconfigure)
    no lanzan excepción.

    Truco: extraemos la rama previa a la inicialización de pystray
    ejecutando solo el setup de UTF-8 (mismas líneas que ``main()``)
    vía un import + exec acotado.
    """
    import io

    # El bloque problemático está en main(). Lo extraemos y ejecutamos
    # en un namespace aislado para verificar que NO lanza.
    src = Path(ROOT / "main_tray.py").read_text(encoding="utf-8")

    # Encontrar el bloque del UTF-8 reconfigure dentro de main().
    marker = "# Forzar UTF-8"
    start = src.index(marker)
    # Hasta el siguiente bloque de "──" (separador) o fin de la rama
    # try/except de UTF-8. El bloque termina antes de "_setup_logging_redirect".
    end_marker = "_setup_logging_redirect"
    end = src.index(end_marker, start)
    block = src[start:end]

    # Ejecutar el bloque con nuestros streams None. Debe NO lanzar.
    namespace: dict = {"sys": sys, "io": io}
    # El bloque es indentado dentro de un `if` y de `def main`, así
    # que le quitamos la indentación de 4 espacios del main.
    dedented = "\n".join(line[4:] if line.startswith("    ") else line
                         for line in block.splitlines())
    exec(dedented, namespace)  # noqa: S102 — extracto intencional


def test_main_handles_none_stdout_specifically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Variante: solo ``sys.stdout`` es None. El resto puede ser real.

    En este caso el bloque debe poder reconfigurar stderr y stdin
    sin lanzar, y simplemente saltarse stdout.
    """
    import io

    # Restaurar streams reales para stderr/stdin (en caso de que
    # fixtures previas los hayan parchado).
    import sys as _real_sys

    monkeypatch.setattr(sys, "stdout", None)
    # stderr y stdin los dejamos como están (pueden ser los reales
    # capturados por pytest).

    src = Path(ROOT / "main_tray.py").read_text(encoding="utf-8")
    marker = "# Forzar UTF-8"
    start = src.index(marker)
    end = src.index("_setup_logging_redirect", start)
    block = src[start:end]

    namespace: dict = {"sys": _real_sys, "io": io}
    dedented = "\n".join(line[4:] if line.startswith("    ") else line
                         for line in block.splitlines())
    exec(dedented, namespace)  # noqa: S102


def test_main_handles_streams_without_buffer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Streams que existen pero carecen de ``.buffer`` y ``.reconfigure``.

    Caso degenerado: stream cerrado o redirigido de forma rara.
    El bloque no debe lanzar.
    """
    import io

    class _WeirdStream:
        """Stream que no tiene ``.reconfigure`` ni ``.buffer``."""

        def write(self, *_a, **_kw) -> int:
            return 0

        def flush(self) -> None:
            pass

    monkeypatch.setattr(sys, "stdout", _WeirdStream())
    monkeypatch.setattr(sys, "stderr", _WeirdStream())
    monkeypatch.setattr(sys, "stdin", _WeirdStream())

    src = Path(ROOT / "main_tray.py").read_text(encoding="utf-8")
    marker = "# Forzar UTF-8"
    start = src.index(marker)
    end = src.index("_setup_logging_redirect", start)
    block = src[start:end]

    namespace: dict = {"sys": sys, "io": io}
    dedented = "\n".join(line[4:] if line.startswith("    ") else line
                         for line in block.splitlines())
    exec(dedented, namespace)  # noqa: S102


# ── Logging setup con sys.stdout None ──────────────────────────────


def test_logging_setup_skips_streamhandler_when_stdout_is_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression: el ``logging.basicConfig`` a nivel de módulo debe
    NO crear un ``StreamHandler(sys.stdout)`` cuando ``sys.stdout`` es
    ``None`` (modo windowed de PyInstaller).

    Si lo crea, cada ``log.info(...)`` revienta con
    ``AttributeError: 'NoneType' object has no attribute 'write'``
    y el handler recursa el error hasta agotar la cola.
    """
    # Forzar stdout=None ANTES de recargar el módulo (el basicConfig
    # se ejecuta al import).
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(sys, "stdin", None)
    # Apuntar el log file a tmp_path para no tocar %LocalAppData%.
    monkeypatch.setenv("ZC_LOG_DIR", str(tmp_path))

    if "main_tray" in sys.modules:
        del sys.modules["main_tray"]
    importlib.import_module("main_tray")

    log = logging.getLogger("zc_tray")

    # Verificación específica del bug: ningún handler debe tener
    # ``stream=None`` (eso era lo que reventaba emit() con
    # ``NoneType.write``). Filtramos por tipo ``StreamHandler``
    # (y subclases como ``FileHandler``), pero el discriminante
    # es el atributo ``.stream``.
    import logging as _lg
    root = logging.getLogger()
    broken_handlers = [
        h for h in root.handlers
        if isinstance(h, _lg.StreamHandler) and getattr(h, "stream", None) is None
    ]
    assert broken_handlers == [], (
        f"BUG REGRESIÓN: hay handler(s) con stream=None: {broken_handlers!r}. "
        f"main_tray.py debería omitir el StreamHandler cuando sys.stdout es None."
    )

    # El log debe poder emitir sin lanzar (el bug era aquí).
    log.info("smoke test con stdout=None; debería loguear sin error")
    # Drenar handlers manualmente.
    for h in root.handlers:
        h.flush()
