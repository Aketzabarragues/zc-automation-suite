"""zc_suite.logs — el log de la app en fichero.

Porta el setup de logging de la app anterior (``core/infrastructure/config/
config_paths.py``): un unico fichero ``logs/zc.log`` con DEBUG, rotado y en
UTF-8, mas la consola cuando existe.

Reglas:

- **El fichero siempre tiene DEBUG**. La consola sube con
  ``ZC_STDOUT_LEVEL`` (por defecto DEBUG).
- **La consola solo se instala si hay consola**. El ``.exe`` va con
  ``console=False``: ahi ``sys.stdout`` es ``None`` y un ``StreamHandler``
  escribiria en la nada (o reventaria). Sin consola no hay handler de
  consola.
- **El log va junto al ejecutable** (``<exe>/logs/zc.log``). En desarrollo,
  en el repo (``<repo>/logs/zc.log``). ``$ZC_LOG_DIR`` lo puede forzar.
- Las excepciones no controladas se escriben en el log: el hook de
  ``sys`` y el de ``threading``.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

logger = logging.getLogger(__name__)

#: Formato de las lineas del log.
LOG_FORMAT = "%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s] %(message)s"

#: Formato de la fecha de las lineas del log.
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

#: Nombre del fichero de log.
LOG_FILENAME = "zc.log"

#: Subcarpeta bajo el ejecutable donde viven los logs.
SUBCARPETA_LOGS = "logs"

#: Variable de entorno que fija la carpeta de logs.
ENV_LOG_DIR = "ZC_LOG_DIR"

#: Variable de entorno que fija el nivel de la consola.
ENV_STDOUT_LEVEL = "ZC_STDOUT_LEVEL"

#: Tamano maximo de cada fichero de log, en bytes.
MAX_BYTES = 10_000_000

#: Cuantos ficheros rotados se guardan (``zc.log.1``, ``zc.log.2``...).
BACKUP_COUNT = 3

#: Loggers externos que, con el root en DEBUG, inundan el fichero con ruido
#: operacional (no son errores nuestros). Se suben a ``WARNING``.
LOGGERS_RUIDOSOS: tuple[str, ...] = (
    "asyncio",
    "PIL",
    "PIL.Image",
    "PIL.PngImagePlugin",
    "werkzeug",
    "urllib3",
    "httpcore",
    "httpx",
)

#: Raiz del repo (para el modo desarrollo).
RAIZ = Path(__file__).resolve().parents[2]

#: Flag de idempotencia: el setup se hace una sola vez por proceso.
_setup_hecho = False


def carpeta_de_logs() -> Path:
    """La carpeta donde se escribe el log.

    Prioridad:

    1. ``$ZC_LOG_DIR``.
    2. Empaquetado: ``<carpeta_del_exe>/logs``.
    3. Desarrollo: ``<repo>/logs``.
    4. Si nada de eso se puede crear, la carpeta de la aplicacion en
       ``AppData``.

    Returns:
        La carpeta, que **siempre existe** tras la llamada.
    """
    override = os.environ.get(ENV_LOG_DIR, "").strip()
    if override:
        candidata = Path(override)
        if _intentar_crear(candidata):
            return candidata

    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else RAIZ
    candidata = base / SUBCARPETA_LOGS
    if _intentar_crear(candidata):
        return candidata

    reserva = Path.home() / "AppData" / "Local" / "zc-automation-suite" / SUBCARPETA_LOGS
    reserva.mkdir(parents=True, exist_ok=True)
    logger.warning(
        "No se pudo usar la carpeta de logs por defecto; usando la reserva: %s",
        reserva,
    )
    return reserva


def _intentar_crear(carpeta: Path) -> bool:
    """Crea la carpeta. ``True`` si existe tras la llamada."""
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("No se pudo crear la carpeta de logs en %s: %s", carpeta, exc)
        return False
    return True


def ruta_log() -> Path:
    """El fichero de log."""
    return carpeta_de_logs() / LOG_FILENAME


def silenciar_loggers_ruidosos() -> None:
    """Sube a ``WARNING`` los loggers externos ruidosos."""
    for nombre in LOGGERS_RUIDOSOS:
        logging.getLogger(nombre).setLevel(logging.WARNING)


def configurar_logging() -> Path:
    """Prepara el logging de la app. Idempotente.

    Returns:
        La ruta del fichero de log.
    """
    global _setup_hecho
    if _setup_hecho:
        return ruta_log()

    carpeta = carpeta_de_logs()
    fichero = carpeta / LOG_FILENAME

    nivel_consola_nombre = os.environ.get(ENV_STDOUT_LEVEL, "DEBUG").upper()
    nivel_consola = getattr(logging, nivel_consola_nombre, logging.DEBUG)

    logging.root.setLevel(logging.DEBUG)
    for manejador in list(logging.root.handlers):
        logging.root.removeHandler(manejador)

    formato = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT)

    fichero_manejador = RotatingFileHandler(
        fichero,
        mode="a",
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    fichero_manejador.setFormatter(formato)
    fichero_manejador.setLevel(logging.DEBUG)
    logging.root.addHandler(fichero_manejador)

    # El .exe va sin consola: ahi sys.stdout es None y un StreamHandler
    # no tendria donde escribir.
    if sys.stdout is not None:
        consola = logging.StreamHandler(sys.stdout)
        consola.setFormatter(formato)
        consola.setLevel(nivel_consola)
        logging.root.addHandler(consola)

    silenciar_loggers_ruidosos()
    _setup_hecho = True
    logger.info(
        "Logging preparado: fichero=%s nivel_fichero=%s nivel_consola=%s",
        fichero,
        logging.getLevelName(logging.DEBUG),
        logging.getLevelName(nivel_consola),
    )
    return fichero


def instalar_hooks_de_excepcion() -> None:
    """Escribe en el log las excepciones no controladas.

    Cubre el hilo principal (``sys.excepthook``) y los hilos que mueren
    (``threading.excepthook``). Sin esto, una excepcion en un hilo
    disappears: solo sale por consola, y el ``.exe`` no tiene consola.
    """
    excepcion_original = sys.excepthook

    def _hook(tipo: type[BaseException], valor: BaseException, traza: object) -> None:
        logger.critical(
            "Excepcion no controlada en el hilo principal.",
            exc_info=(tipo, valor, traza),
        )
        if excepcion_original is not None:
            excepcion_original(tipo, valor, traza)

    sys.excepthook = _hook

    def _hook_de_hilo(args: threading.ExceptHookArgs) -> None:
        nombre = getattr(args.thread, "name", "?")
        logger.critical(
            "Excepcion no controlada en el hilo '%s'.",
            nombre,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = _hook_de_hilo
