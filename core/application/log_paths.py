"""core.application.log_paths

Resolución centralizada de carpeta de logs + setup unificado.

Toda la app (``--web``, ``--mcp``, default bandeja, worker) escribe al
**MISMO archivo** ``<log_dir>/zc.log``. Esto unifica los 4 setups
distintos que existían antes:

  - ``main.py`` (default bandeja): ``zc_tray.log`` (FileHandler + StreamHandler)
  - ``main.py --web``: solo console (ZC_DEBUG, sin FileHandler)
  - ``main.py --mcp``: ???
  - ``worker_tia.py``: ``worker_openness.log`` (separado, con su setup)

Con este módulo, los 4 entrypoints llaman ``setup_logging(mode)`` y
todos escriben al mismo log. El modo ("web", "tray", etc.) aparece
como prefijo del logger name (``zc.web``, ``zc.tray``) para facilitar
``grep`` por fuente.

Uso::

    # main.py --web
    from core.application.log_paths import setup_logging
    setup_logging("web")

    # main.py (default bandeja)
    from core.application.log_paths import setup_logging
    setup_logging("tray")

    # worker_tia.py (subprocess)
    from core.application.log_paths import setup_logging
    setup_logging("worker")
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


_logger = logging.getLogger(f"{__name__}.resolve_log_dir")

# Formato consistente para TODOS los modos. ``[%(name)s]`` permite
# filtrar por fuente (``grep '\[zc.web\]'`` vs ``grep '\[zc.tray\]'``).
LOG_FORMAT = (
    "%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s] %(message)s"
)
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

# Nombre del archivo único. Todos los modos escriben aquí.
LOG_FILENAME = "zc.log"

# Flag de idempotencia (a nivel módulo). Una vez configurado, las
# llamadas siguientes son no-op (importante para tests que importan
# el módulo muchas veces o para setups múltiples accidentales).
_setup_done: bool = False


def resolve_log_dir(
    env_var: str = "ZC_LOG_DIR",
    default_subdir: str = "logs",
) -> Path:
    """Devuelve la carpeta donde escribir los logs del programa.

    Prioridad de localizacion:

      1. ``env_var`` (default ``ZC_LOG_DIR``) si esta definida y no vacia.
      2. Modo frozen (PyInstaller ``--onefile``): ``<exe_dir>/<default_subdir>``.
      3. Modo dev (``python main.py``): ``<cwd>/<default_subdir>``.
      4. Fallback legacy a ``%LocalAppData%\\zc-automation-suite\\<default_subdir>``
         si la ruta prioritaria no se puede crear (permisos, etc.).

    La ruta devuelta SIEMPRE existe en disco (``mkdir(parents=True,
    exist_ok=True)``). Esto es importante para los consumidores que
    escriben directamente (e.g. ``ts.set_logging(path=...)`` de Siemens
    no crea el directorio padre, solo escribe).

    Args:
        env_var: Nombre de la variable de entorno a respetar.
        default_subdir: Subcarpeta por defecto bajo el ejecutable o el CWD.

    Returns:
        ``Path`` a una carpeta existente. Nunca ``None``.
    """
    # 1. Override explicito por env var.
    override = os.environ.get(env_var, "").strip()
    if override:
        candidate = Path(override)
        if _try_mkdir(candidate, source=f"{env_var}={override}"):
            return candidate
        # Si el override fallo, cae al calculo por defecto (no silenciamos).

    # 2. Calcular ruta por defecto segun el modo de ejecucion.
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path.cwd()
    candidate = base / default_subdir
    if _try_mkdir(candidate, source=str(candidate)):
        return candidate

    # 3. Fallback al AppData legacy (clasico en Windows para apps internas).
    fallback = (
        Path.home() / "AppData" / "Local" / "zc-automation-suite" / default_subdir
    )
    fallback.mkdir(parents=True, exist_ok=True)
    _logger.warning(
        "No se pudo usar la ruta de logs por defecto; usando fallback AppData: %s",
        fallback,
    )
    return fallback


def _try_mkdir(path: Path, source: str) -> bool:
    """Intenta crear ``path``. Retorna True si existe tras la llamada."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except OSError as exc:
        _logger.warning(
            "No se pudo crear la carpeta de logs en %s (origen: %s): %s",
            path, source, exc,
        )
        return False


def setup_logging(mode: str = "default") -> Path:
    r"""Setup unificado de logging. Llamar UNA vez al inicio de cada entrypoint.

    Args:
        mode: Identificador del componente. Se usa como prefijo del
            logger root (``logging.root.name = f"zc.{mode}"``) para
            distinguir fuentes en el log unificado. Valores
            habituales: ``"web"``, ``"mcp"``, ``"tray"``, ``"worker"``.
            ``"default"`` no añade prefijo (``zc`` a secas).

    Returns:
        ``Path`` al archivo de log (``<log_dir>/zc.log``). Util para que
        el caller loggee "logs in <path>" al inicio.

    Comportamiento:
        - **Idempotente**: si ya se llamó en este proceso, no-op (los
          handlers no se duplican). Útil para tests que importan el
          módulo muchas veces.
        - **FileHandler append** a ``<log_dir>/zc.log`` (UTF-8, sin
          rotación por ahora; rotación queda como TODO Fase 4).
        - **StreamHandler** a ``sys.stdout`` si está disponible (no
          se añade en modo windowed de PyInstaller).
        - **Root level**: ``INFO`` por defecto, ``DEBUG`` si
          ``ZC_DEBUG=1`` (toggle para diagnostico, ver DA-012).
        - **Formato**: ``%(asctime)s.%(msecs)03d [%(levelname)s]
          [%(name)s] %(message)s``. El ``[%(name)s]`` permite grep:
          ``grep '\[zc\.web\]' zc.log`` vs ``grep '\[zc\.worker\]'``.
        - **uvicorn reconfig**: limpia los ``StreamHandler`` que
          uvicorn añade a sus loggers por defecto y deja que
          propagen al root (asi no aparece un ``[ERROR] zc.tray:
          INFO: ...`` con level equivocado). Solo aplica si uvicorn
          está instalado.

    Side effects:
        - Resetea ``logging.root.handlers`` (limpia basicConfig previo).
        - Cambia ``logging.root.name``.
        - Reconfigura uvicorn loggers.

    Example::

        # main.py --web
        setup_logging("web")
        # root logger name ahora es "zc.web"
        # logs van a <log_dir>/zc.log + stdout
    """
    global _setup_done

    if _setup_done:
        return resolve_log_dir() / LOG_FILENAME

    log_dir = resolve_log_dir()
    log_file = log_dir / LOG_FILENAME

    # Nombre del root logger (visible en cada línea como ``[zc.web]``).
    root_name = f"zc.{mode}" if mode and mode != "default" else "zc"
    logging.root.name = root_name

    # Level: INFO por defecto, DEBUG si ZC_DEBUG=1.
    level = logging.DEBUG if os.environ.get("ZC_DEBUG") == "1" else logging.INFO
    logging.root.setLevel(level)

    # Limpiar handlers previos (basicConfig previo, uvicorn por
    # defecto, etc.) para evitar duplicación cuando se llama 2 veces.
    for h in list(logging.root.handlers):
        logging.root.removeHandler(h)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT)

    # FileHandler: append mode (multiples procesos al mismo archivo
    # OK con lock). UTF-8 para tildes y emojis de logs.
    file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    logging.root.addHandler(file_handler)

    # StreamHandler: solo si stdout existe (no windowed de PyInstaller).
    if sys.stdout is not None:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(level)
        logging.root.addHandler(stream_handler)

    # uvicorn: limpiar StreamHandler propios y propagar al root.
    # Asi un INFO de uvicorn se loguea como ``[INFO] [uvicorn.access]:``
    # en vez de ``[ERROR] [zc.web]: INFO: ...`` con level equivocado.
    for uv_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(uv_name)
        uv_logger.handlers = [
            h for h in uv_logger.handlers
            if not (
                isinstance(h, logging.StreamHandler)
                and getattr(h, "stream", None) in (None, sys.__stderr__)
            )
        ]
        uv_logger.propagate = True

    _setup_done = True
    _logger.info(
        "setup_logging: mode=%s root_name=%s log_file=%s level=%s (ZC_DEBUG=%s)",
        mode, root_name, log_file, logging.getLevelName(level),
        os.environ.get("ZC_DEBUG", "0"),
    )

    return log_file


__all__ = ["resolve_log_dir", "setup_logging", "LOG_FORMAT", "LOG_FILENAME"]
