"""Resolucion centralizada del ``config.json`` del usuario.

Patron: "template bundleado + copia writable al lado del .exe".
En modo frozen (PyInstaller ``--onefile``) el ``config.json``
bundleado en ``sys._MEIPASS`` es la plantilla. En la primera
ejecucion se copia a ``<exe_dir>/config/config.json``; en
siguientes ejecuciones **siempre gana el del usuario** (no se
sobreescribe). Si la carpeta no es escribible, fallback readonly
al bundleado con warning.

El resolver se llama desde ``ConfigManager.__init__`` cuando el
caller no pasa un ``config_path`` explicito. Inspirado en
``core/application/log_paths.py:resolve_log_dir``.
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

from core.infrastructure.log_web_bridge import (
    install_log_buffer_handler,
    install_web_level,
)


_logger = logging.getLogger(f"{__name__}.resolve_config_path")


# Nombre del archivo de configuracion (siempre este nombre, en
# cualquier carpeta donde vivamos).
_CONFIG_FILENAME: str = "config.json"


def resolve_config_path(
    env_var: str = "ZC_CONFIG_DIR",
    default_subdir: str = "config",
    bundled_relpath: str = "config/config.json",
) -> Path:
    """Devuelve la ruta al ``config.json`` que debe usar la app.

    Prioridad de localizacion:
      1. ``$ZC_CONFIG_DIR/config.json`` si la env var esta
         definida y no vacia.
      2. Modo frozen: ``<exe_dir>/<default_subdir>/config.json``,
         copiando el bundleado si no existe.
      3. Modo dev: ``<cwd>/<bundled_relpath>`` (el del repo).

    Politica: **el usuario gana siempre**. Si el archivo destino
    ya existe, NO se sobreescribe. Si no se puede escribir
    (permisos, red readonly, CD-ROM), fallback readonly al
    bundleado con warning.

    Args:
        env_var: Variable de entorno a respetar como override.
        default_subdir: Subcarpeta por defecto bajo el ejecutable
            (modo frozen).
        bundled_relpath: Ruta relativa al bundle (``_MEIPASS`` en
            frozen, ``cwd`` en dev) donde vive el ``config.json``
            plantilla.

    Returns:
        ``Path`` al ``config.json`` recien copiado o preexistente,
        o a la ruta bundleada si la copia fallo (lectura OK pero
        escritura no).

    Raises:
        FileNotFoundError: Si ni la ruta prioritaria ni la
            bundleada se pueden resolver.
    """
    # 1. Override explicito por env var (aplica en cualquier modo).
    override = os.environ.get(env_var, "").strip()
    if override:
        candidate = Path(override) / _CONFIG_FILENAME
        bundled = _bundled_path(bundled_relpath)
        if _ensure_user_config(bundled, candidate, source=f"{env_var}={override}"):
            return candidate
        if candidate.is_file():
            return candidate
        # Si tampoco existe, cae al calculo por defecto (no silenciamos).

    # 2. Modo frozen: copiar el bundleado a <exe_dir>/<subdir>/.
    if getattr(sys, "frozen", False):
        candidate = (
            Path(sys.executable).parent / default_subdir / _CONFIG_FILENAME
        )
        bundled = _bundled_path(bundled_relpath)
        if _ensure_user_config(bundled, candidate, source=str(candidate)):
            return candidate
        if candidate.is_file():
            return candidate
        # Fallback readonly: ruta bundleada (lectura OK, escritura no).
        if bundled.is_file():
            _logger.warning(
                "No se pudo escribir config en %s. Usando bundleado "
                "readonly: %s. Los edits del operario no persistiran "
                "hasta que se resuelva el problema de permisos.",
                candidate, bundled,
            )
            return bundled
        raise FileNotFoundError(
            f"No se encontro config.json bundleado en {bundled}. "
            f"Revisa que el .exe este correctamente empaquetado."
        )

    # 3. Modo dev: usar el archivo del repo directamente (sin copia).
    #    El developer edita ``config/config.json`` en su repo y los
    #    cambios se ven en el siguiente reinicio. No copiamos a un
    #    sitio "del usuario" porque no hay .exe del que hablar.
    return _bundled_path(bundled_relpath)


def _bundled_path(relpath: str) -> Path:
    """Resuelve la ruta al ``config.json`` bundleado (template).

    En frozen: ``<sys._MEIPASS>/<relpath>``.
    En dev: ``<cwd>/<relpath>``.
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / relpath
    return Path.cwd() / relpath


def _ensure_user_config(
    bundled: Path, dst: Path, source: str,
) -> bool:
    """Asegura que ``dst`` existe; si no, copia ``bundled`` a ``dst``.

    Politica: **el usuario gana siempre**. Si ``dst`` ya existe
    (aunque sea un archivo vacio o un JSON malformado), NO se
    sobreescribe. El operario borra el archivo a mano si quiere
    resetear al bundleado.

    Returns:
        True si ``dst`` existe tras la llamada (preexistente o
        recien copiado). False si la copia fallo (permisos, etc.).
    """
    if dst.is_file():
        return True  # el del usuario ya esta; no tocamos
    if not bundled.is_file():
        return False  # no hay template para copiar
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _logger.warning(
            "No se pudo crear la carpeta de config en %s (origen: "
            "%s): %s.", dst.parent, source, exc,
        )
        return False
    try:
        shutil.copy2(bundled, dst)
    except OSError as exc:
        _logger.warning(
            "No se pudo copiar config bundleado a %s (origen: %s): "
            "%s. Se intentara fallback readonly.", dst, source, exc,
        )
        return False
    _logger.info(
        "Se creo %s (primera ejecucion; copia del bundleado %s). "
        "Edita este archivo para personalizar la configuracion del "
        "operario; tus cambios se preservaran entre reinicios del "
        ".exe. Si quieres resetear al estado bundleado, borra este "
        "archivo y reinicia la app.", dst, bundled,
    )
    return True


__all__ = ["resolve_config_path"]


# ---------------------------------------------------------------------------
# Logs: resolucion de carpeta + setup unificado
# ---------------------------------------------------------------------------
# Antes vivian en ``core/application/log_paths.py``. Fusionados aqui
# para centralizar TODO lo de paths + setup en un solo archivo
# (config + logs comparten el patron "template bundleado + copia writable").

# Formato consistente para TODOS los modos. ``[%(name)s]`` permite
# filtrar por fuente (``grep '\[zc.web\]'`` vs ``grep '\[zc.tray\]'``).
LOG_FORMAT = (
    "%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s] %(message)s"
)
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

# Nombre del archivo unico. Todos los modos escriben aqui.
LOG_FILENAME = "zc.log"

# Flag de idempotencia (a nivel modulo). Una vez configurado, las
# llamadas siguientes son no-op (importante para tests que importan
# el modulo muchas veces o para setups multiples accidentales).
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
    escriben directamente.
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


# Loggers externos que, con root en DEBUG, inundan ``zc.log`` con ruido
# operacional (no son errores nuestros). Los silenciamos a WARNING para
# que solo aparezcan cuando ocurra algo realmente anomalo. El root y
# nuestros loggers (``zc.*`` y derivados) siguen en DEBUG.
_NOISY_LOGGERS: tuple[str, ...] = (
    "asyncio",            # "Using proactor: IocpProactor" cada 100ms.
    "PIL",                # "Importing XxxImagePlugin" (~49 lineas).
    "PIL.Image",
    "PIL.PngImagePlugin",
    "werkzeug",           # 1 INFO por HTTP request.
    "urllib3",            # DEBUG de pool/http en operaciones largas.
    "httpcore",
    "httpx",
)


def silence_noisy_loggers() -> None:
    """Sube a ``WARNING`` los loggers externos ruidosos.

    Llamada por :func:`setup_logging` justo despues de instalar el
    bridge. Idempotente: llamada directa no causa doble-emit ni
    conflictos si :func:`setup_logging` la vuelve a invocar.

    Casos cubiertos (todos verificados en el smoke del operario,
    ``logs/zc.log`` tenia +500 lineas de estos):

    - ``asyncio``: emite ``Using proactor: IocpProactor`` cada ~100ms
      cuando algun subproceso nuestro crea un event loop.
    - ``PIL``: emite ``Importing XxxImagePlugin`` para cada formato
      de imagen al instanciar (Pillow carga plugins lazy).
    - ``werkzeug``: 1 INFO por cada HTTP request del dev server Flask.
    - ``urllib3/httpcore/httpx``: DEBUG verbose de conexiones HTTP.
    """
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def setup_logging(mode: str = "default") -> Path:
    """Setup unificado de logging. Llamar UNA vez al inicio de cada entrypoint.

    Args:
        mode: Identificador del componente. Se usa como prefijo del
            logger root (``logging.root.name = f"zc.{mode}"``) para
            distinguir fuentes en el log unificado. Valores
            habituales: ``"web"``, ``"mcp"``, ``"tray"``, ``"worker"``.
            ``"default"`` no anade prefijo (``zc`` a secas).

    Returns:
        ``Path`` al archivo de log (``<log_dir>/zc.log``).
    """
    global _setup_done

    if _setup_done:
        return resolve_log_dir() / LOG_FILENAME

    log_dir = resolve_log_dir()
    log_file = log_dir / LOG_FILENAME

    # Nombre del root logger (visible en cada linea como ``[zc.web]``).
    root_name = f"zc.{mode}" if mode and mode != "default" else "zc"
    logging.root.name = root_name

    # Level: DEBUG por defecto en archivo (capturamos todo lo de la
    # app, incluidos los ``logger.debug`` que ahora emiten los 5 OT
    # handlers repetitivos). Stdout tambien a DEBUG para ver el DEBUG
    # en consola cuando se ejecuta en modo dev. Operario puede subir a
    # WARNING para silenciar librerias externas con ``ZC_STDOUT_LEVEL``.
    stdout_level_name = os.environ.get("ZC_STDOUT_LEVEL", "DEBUG").upper()
    stdout_level = getattr(logging, stdout_level_name, logging.DEBUG)
    file_level = logging.DEBUG  # siempre: queremos DEBUG en zc.log.

    logging.root.setLevel(file_level)  # root acepta todo (DEBUG+)

    # Limpiar handlers previos (basicConfig previo, uvicorn por
    # defecto, etc.) para evitar duplicacion cuando se llama 2 veces.
    for h in list(logging.root.handlers):
        logging.root.removeHandler(h)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT)

    # FileHandler: append mode (multiples procesos al mismo archivo
    # OK con lock). UTF-8 para tildes y emojis de logs.
    file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(file_level)
    logging.root.addHandler(file_handler)

    # StreamHandler: solo si stdout existe (no windowed de PyInstaller).
    if sys.stdout is not None:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(stdout_level)
        logging.root.addHandler(stream_handler)

    # uvicorn: limpiar StreamHandler propios y propagar al root.
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

    # Bridge logging <-> LogBuffer (consola web SPA).
    # Tras esto, ``logger.web/ok/warning/error(...)`` enrutaran a la web
    # ademas de al archivo. ``info/debug`` se quedan solo en archivo.
    install_web_level()
    install_log_buffer_handler()

    # Silenciar loggers externos que, en DEBUG, inundan ``zc.log`` con
    # ruido puramente operacional (no son errores nuestros). El root
    # sigue en DEBUG para capturar todo de ``zc.*`` y derivados.
    silence_noisy_loggers()

    _setup_done = True
    _logger.info(
        "setup_logging: mode=%s root_name=%s log_file=%s "
        "file_level=%s stdout_level=%s (ZC_STDOUT_LEVEL=%s)",
        mode, root_name, log_file,
        logging.getLevelName(file_level),
        logging.getLevelName(stdout_level),
        os.environ.get("ZC_STDOUT_LEVEL", "DEBUG"),
    )

    return log_file


__all__ = [
    "resolve_config_path",
    "resolve_log_dir",
    "setup_logging",
    "silence_noisy_loggers",
    "LOG_FORMAT",
    "LOG_FILENAME",
]
