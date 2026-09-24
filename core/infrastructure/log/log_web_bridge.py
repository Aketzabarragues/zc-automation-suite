"""Bridge entre ``logging`` Python y ``LogBuffer`` (consola web de la SPA).

Une los dos sistemas de log que hoy conviven en la app:

  - ``logging`` stdlib: archivo ``zc.log`` + ``stdout``. Captura TODO
    (DEBUG/INFO/WEB/OK/WARNING/ERROR/CRITICAL).
  - ``LogBuffer`` Singleton: buffer FIFO circular que la SPA lee por
    polling para mostrar mensajes al operario.

Hoy coexisten con duplicacion manual en los FBs:

    self._log.info("...")   # web
    logger.info("...")       # archivo

Tras este bridge, **1 sola llamada** enruta a ambos destinos:

    log = logging.getLogger(__name__)
    log.web("preview calculado: 8 disp")  # archivo [WEB] + web neutro
    log.ok("sync completo: 8 disp")       # archivo [OK] + web VERDE
    log.warning("slot duplicado")         # archivo + web amber

API publica:
  - ``install_web_level()``: registra los custom levels WEB (25) y OK
    (26) en ``logging``, y monkey-patcha ``Logger.web`` y ``Logger.ok``.
    Idempotente.
  - ``install_log_buffer_handler()``: instala ``LogBufferHandler`` en
    el root logger. Idempotente.
  - ``LogBufferHandler``: handler que captura records con level >= WEB
    (25) y los publica en el ``LogBuffer`` Singleton. Mapea
    ``OK (26) -> "success"`` (verde en SPA via CSS existente).
  - Constantes ``WEB_LEVEL=25``, ``OK_LEVEL=26``.

El ``LogBuffer`` API publica (``info/success/warning/error/snapshot/clear``)
no se toca: el handler usa el metodo interno ``_push(level, message)``.
Tests y endpoint ``GET /api/v1/diagnostics/logs`` siguen funcionando.

Restricciones:
  - NO importa ``siemens_tia_scripting``.
  - Sin estado mutable propio salvo el handler instalado en root.
  - Idempotente: se puede llamar varias veces sin duplicar handlers.
"""
from __future__ import annotations

import logging

from core.runtime.log_buffer import get_log_buffer


# Custom levels (entre INFO=20 y WARNING=30).
WEB_LEVEL: int = 25
WEB_LEVEL_NAME: str = "WEB"
OK_LEVEL: int = 26
OK_LEVEL_NAME: str = "OK"


# ── Monkey-patch de Logger.web / Logger.ok ─────────────────────────


def _web(self: logging.Logger, message: object, *args: object, **kwargs: object) -> None:
    """Logger.web(): archivo + LogBuffer (consola web, neutro).

    Equivalente a ``self.log(WEB_LEVEL, message, *args, **kwargs)``.
    """
    if self.isEnabledFor(WEB_LEVEL):
        self._log(WEB_LEVEL, message, args, **kwargs)  # type: ignore[arg-type]


def _ok(self: logging.Logger, message: object, *args: object, **kwargs: object) -> None:
    """Logger.ok(): archivo + LogBuffer (verde, success).

    Equivalente a ``self.log(OK_LEVEL, message, *args, **kwargs)``.
    """
    if self.isEnabledFor(OK_LEVEL):
        self._log(OK_LEVEL, message, args, **kwargs)  # type: ignore[arg-type]


def install_web_level() -> None:
    """Registra ``WEB`` (25) y ``OK`` (26) en ``logging``.

    Idempotente: si ``Logger.web`` o ``Logger.ok`` ya existen, no los
    pisa (mitigacion de riesgo en tabla §Riesgos del plan).
    """
    logging.addLevelName(WEB_LEVEL, WEB_LEVEL_NAME)
    logging.addLevelName(OK_LEVEL, OK_LEVEL_NAME)
    if not hasattr(logging.Logger, "web"):
        logging.Logger.web = _web  # type: ignore[attr-defined]
    if not hasattr(logging.Logger, "ok"):
        logging.Logger.ok = _ok  # type: ignore[attr-defined]


# ── Handler que enruta records WEB+ al LogBuffer ────────────────────


class LogBufferHandler(logging.Handler):
    """Captura records con level >= ``WEB_LEVEL`` (25) y los publica.

    Level por defecto: ``WEB_LEVEL`` (25). Captura WEB, OK, WARNING,
    ERROR y CRITICAL. NO captura INFO (20) ni DEBUG (10): esos se
    quedan solo en archivo (``zc.log``) y ``stdout`` por diseño (la
    consola web no debe mostrar trazas internas como ticks del OB1,
    transiciones TIA o access logs de werkzeug).

    Mapeo a ``LogBuffer.level``:
      - ``OK`` (26) -> ``"success"`` (verde en SPA via CSS).
      - ``WARNING`` (30) -> ``"warning"`` (amber).
      - ``ERROR``/``CRITICAL`` -> ``"error"`` (red).
      - ``WEB`` (25) -> ``"info"`` (neutro).

    El ``LogBuffer`` ya genera timestamp ISO en ``_push``; este handler
    solo aporta ``"[<logger_name>] <message>"`` para que el operario
    vea el origen del mensaje.
    """

    def __init__(self, level: int = WEB_LEVEL) -> None:
        super().__init__(level=level)
        self._buffer = get_log_buffer()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = f"[{record.name}] {record.getMessage()}"
            level = self._map_level(record.levelno)
            self._buffer._push(level, message)
        except Exception:
            # ``handleError`` de ``logging.Handler`` imprime traceback
            # del fallo de ``emit`` a ``stderr`` (no rompe el flujo).
            self.handleError(record)

    @staticmethod
    def _map_level(pynum: int) -> str:
        # OK (26) -> "success" (verde en SPA).
        # Limite estricto ``< WARNING`` para NO capturar WARNING como OK.
        if OK_LEVEL <= pynum < logging.WARNING:
            return "success"
        if pynum >= logging.CRITICAL:
            return "error"
        if pynum >= logging.ERROR:
            return "error"
        if pynum >= logging.WARNING:
            return "warning"
        # WEB (25) cae aqui (entre INFO y WARNING, pero fuera del rango OK).
        return "info"


def install_log_buffer_handler() -> None:
    """Instala ``LogBufferHandler`` en el root logger.

    Idempotente: si ya hay un ``LogBufferHandler`` en root, no añade
    otro. Util para tests y para entrypoints que llaman a
    ``setup_logging()`` mas de una vez.
    """
    for h in logging.root.handlers:
        if isinstance(h, LogBufferHandler):
            return
    handler = LogBufferHandler(level=WEB_LEVEL)
    logging.root.addHandler(handler)


__all__ = [
    "WEB_LEVEL",
    "OK_LEVEL",
    "WEB_LEVEL_NAME",
    "OK_LEVEL_NAME",
    "LogBufferHandler",
    "install_web_level",
    "install_log_buffer_handler",
]
