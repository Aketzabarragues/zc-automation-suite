"""Logging estructurado (JSON lines) para el worker OT persistente.

Este modulo configura el logger ``zc.worker_ot`` con dos handlers:

  1. **stderr** (formato compacto, INFO+): una linea legible por operario
     humano cuando el worker se ejecuta en primer plano (modo web con
     consola). Formato::

         [2026-09-08 14:23:01.456] [INFO] command_completed {"command": "compile_plc", ...}

  2. **Archivo rotatorio** (formato JSON lines, DEBUG+) en
     ``<log_dir>/worker_ot.log`` donde ``<log_dir>`` es
     ``resolve_log_dir()`` de :mod:`core.application.log_paths`. Misma
     carpeta que ``zc_tray.log``, mismo override por env var
     (``ZC_LOG_DIR``) y mismo fallback a AppData. 10 MB por archivo,
     5 backups = 50 MB maximo.

Reglas de diseno (sept-2026, PR de observabilidad del worker):

- **Idempotencia:** ``configure_worker_logger()`` puede invocarse varias
  veces (p.ej. tras un restart del subproceso) sin duplicar handlers.
- **Tolerancia a fallos:** si el handler de archivo no se puede crear
  (permisos, path invalido), se loguea un warning a stderr y se sigue
  solo con stderr. El worker NO puede fallar por un problema de logging.
- **Sin info sensible:** ``log_event()`` solo recibe ``event`` y campos
  especificos. Los handlers del worker NO deben pasar ``args`` completos
  (pueden llevar passwords de TIA); en su lugar pasan ``args_keys``.
- **Sin payloads grandes:** el ``result`` del comando NO se loguea;
  solo ``result_type`` (nombre de la clase).

Disenado para ser consumido por ``worker_tia.main_persistent_loop``.
El modo 1-shot (``main_oneshot`` / modo MCP) NO usa este modulo: el
gateway MCP sigue emitiendo ``[WORKER TIMING]`` / ``[WORKER ERROR]``
como siempre, sin cambio de comportamiento.
"""
from __future__ import annotations

import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from core.application.log_paths import resolve_log_dir


_LOGGER_NAME = "zc.worker_ot"

# Set cerrado de eventos validos. ``log_event()`` valida contra este set
# para detectar typos; si el evento no esta, se loguea igualmente pero
# se anade ``_unknown_event`` al payload para que el operario lo vea al
# parsear el log. Mantener sincronizado con el diseno del PR.
_KNOWN_EVENTS: frozenset[str] = frozenset({
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
})

# 10 MB por archivo, 5 backups = 50 MB maximo.
_LOG_MAX_BYTES = 10 * 1024 * 1024
_LOG_BACKUP_COUNT = 5

# Bandera a nivel de modulo para idempotencia. El ``logging`` de Python
# ya deduplica handlers identicos al hacer ``addHandler`` con el mismo
# handler, pero un check explicito es mas barato y deja claro el
# contrato. Se usa una lista de un elemento (no bool) para que los
# tests puedan ``monkeypatch.setattr`` y forzar reconfiguracion.
_already_configured: list[bool] = [False]


class JsonLineFormatter(logging.Formatter):
    """Formatea cada log como una linea JSON.

    Cada linea emitida por este formatter es un JSON parseable con la
    forma::

        {
            "ts": 1757080000.123,        # epoch unix con decimales
            "level": "INFO",              # nombre del nivel (str)
            "logger": "zc.worker_ot",     # nombre del logger
            "event": "command_completed", # nombre del evento
            ...campos especificos del evento (command, duration_ms, etc.)
        }

    El ``msg`` que recibe el formatter es el string JSON producido por
    ``log_event()`` con los campos del evento. Aqui se deserializa, se
    mergean los metadatos de Python (``ts``, ``level``, ``logger``) y
    se re-serializa en una sola linea.
    """

    def format(self, record: logging.LogRecord) -> str:
        # 1. Parsear el payload del evento (producido por log_event).
        # Si por algun motivo no es JSON valido (e.g. un mensaje
        # suelto de otro modulo cae en el logger), se degrada a un
        # payload minimo con el mensaje como ``msg`` y sin ``event``.
        try:
            payload = json.loads(record.getMessage())
            if not isinstance(payload, dict):
                payload = {"msg": record.getMessage()}
        except (ValueError, TypeError):
            payload = {"msg": record.getMessage()}

        # 2. Merge con metadatos de Python.
        # ``ts`` en epoch unix con decimales (mas compacto y parseable
        # que ISO 8601 en herramientas tipo jq, dq, pandas). Usamos
        # ``created`` (set por logging al construir el record) y no
        # ``time.time()`` para no añadir variabilidad.
        payload.setdefault("ts", record.created)
        payload.setdefault("level", record.levelname)
        payload.setdefault("logger", record.name)

        # 3. Serializar en una sola linea (ensure_ascii=False para
        # que un error_msg con acentos se vea bien en el log; el
        # archivo se abre con encoding="utf-8").
        return json.dumps(payload, ensure_ascii=False, default=str)


class _CompactStderrFormatter(logging.Formatter):
    """Formatter compacto para stderr (legible por humanos).

    Formato::

        [2026-09-08 14:23:01.456] [INFO] command_completed {"command": "compile_plc", ...}

    El timestamp es la fecha/hora local (no UTC) para que el operario
    vea la hora del reloj del PC, que es la unica referencia que tiene
    al mirar el tray. ``datefmt`` sigue el patron ISO 8601 sin
    separador de zona (lo que el operario espera del formato del
    resto de la app).
    """

    def __init__(self) -> None:
        super().__init__(
            fmt="[%(asctime)s.%(msecs)03d] [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        # El ``message`` es el JSON de log_event(). Para no duplicar
        # el campo event en stderr, lo extraemos del JSON y lo
        # anteponemos al payload como prefijo humano. Asi el operario
        # ve ``[INFO] command_completed {...}`` en vez de
        # ``[INFO] {"event": "command_completed", ...}``.
        #
        # IMPORTANTE: NO mutamos ``record.msg`` (eso contaminaria
        # otros handlers que vean el mismo record, e.g. el
        # ``JsonLineFormatter`` del handler de archivo). Solo
        # sobreescribimos ``record.message`` (atributo de instancia
        # que ``Formatter.format()`` lee via ``formatMessage``).
        try:
            payload = json.loads(record.getMessage())
            event_name = payload.get("event", "")
        except (ValueError, TypeError, AttributeError):
            event_name = ""
            payload = None

        if event_name and isinstance(payload, dict):
            # Reconstruimos el JSON sin ``event`` para no repetirlo.
            fields = {k: v for k, v in payload.items() if k != "event"}
            tail = json.dumps(fields, ensure_ascii=False, default=str)
            record.message = f"{event_name} {tail}"
        else:
            record.message = record.getMessage()

        return super().format(record)


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    **fields: Any,
) -> None:
    """Emite un evento estructurado al logger del worker OT.

    Esta funcion es el ÚNICO punto de entrada para emitir logs
    estructurados desde el worker. Los handlers NO deben llamar a
    ``logger.info(...)`` directamente: eso produciria logs sin la
    clave ``event`` y romperia los parsers del operario.

    Args:
        logger: Logger a usar (tipicamente el devuelto por
            ``configure_worker_logger()``).
        level: Nivel de log (ej. ``logging.INFO``). Usar las
            constantes de ``logging`` o el level numerico.
        event: Nombre del evento. Debe estar en ``_KNOWN_EVENTS``.
            Si no, se anade ``_unknown_event`` al payload y se
            loguea igualmente (fail-open para no perder eventos).
        **fields: Campos especificos del evento. Se serializan como
            JSON. Tipos permitidos: str, int, float, bool, list, dict,
            None. Tipos no serializables se convierten con ``str()``
            (``default=str`` en json.dumps).

    Notas:
        - No loguees args completos (pueden llevar info sensible).
          Pasa solo ``args_keys`` (lista de nombres de los keys).
        - No loguees resultados completos (pueden ser grandes).
          Pasa solo ``result_type`` (nombre de la clase).
    """
    payload: dict[str, Any] = {"event": event, **fields}
    if event not in _KNOWN_EVENTS:
        # Fail-open: anadimos la marca para que el operario detecte
        # el typo al parsear el log, pero NO descartamos el evento.
        payload["_unknown_event"] = event
    logger.log(level, json.dumps(payload, ensure_ascii=False, default=str))


def configure_worker_logger() -> logging.Logger:
    """Configura y devuelve el logger ``zc.worker_ot``.

    Es idempotente: si ya esta configurado, devuelve el logger tal
    cual sin anadir handlers duplicados. Esto es importante porque el
    worker puede reiniciarse (modo dev con pytest, o tras un crash) y
    ``main_persistent_loop`` se vuelve a invocar.

    Configuracion:
      - 2 handlers: stderr (INFO+, compacto) y archivo rotatorio
        (DEBUG+, JSON lines).
      - El archivo se crea en ``<resolve_log_dir()>/worker_ot.log``.
        Si no se puede crear (permisos, path invalido), se loguea un
        warning a stderr y se sigue solo con stderr. El worker NO
        falla por un problema de logging.
      - ``propagate=False`` para que el root logger no duplique los
        mensajes.

    Returns:
        El logger ``zc.worker_ot``, listo para usar con ``log_event()``.
    """
    logger = logging.getLogger(_LOGGER_NAME)

    if _already_configured[0]:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # 1. Handler de stderr: INFO+ en formato compacto.
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.INFO)
    stderr_handler.setFormatter(_CompactStderrFormatter())
    logger.addHandler(stderr_handler)

    # 2. Handler de archivo rotatorio: DEBUG+ en JSON lines.
    try:
        log_dir = resolve_log_dir()
        log_path = log_dir / "worker_ot.log"
        file_handler = RotatingFileHandler(
            filename=str(log_path),
            maxBytes=_LOG_MAX_BYTES,
            backupCount=_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(JsonLineFormatter())
        logger.addHandler(file_handler)
    except Exception as exc:
        # El worker no puede fallar por un problema de logging.
        # Anadimos un NullHandler para que el logger siga funcionando
        # y avisamos a stderr via el propio logger de stderr (que ya
        # esta configurado). Si el stderr tambien falla, el logging
        # simplemente no emite nada, pero el worker sigue.
        logger.addHandler(logging.NullHandler())
        logger.warning(
            "worker_ot: no se pudo configurar el handler de archivo "
            "(%s: %s). Continuando solo con stderr.",
            type(exc).__name__,
            exc,
        )

    _already_configured[0] = True
    return logger


def reset_worker_logger_for_tests() -> None:
    """Limpia la configuracion del logger. Solo para tests.

    Quita todos los handlers del logger ``zc.worker_ot``, borra
    handlers internos (file handler cierra el archivo) y resetea la
    bandera de idempotencia. Asi un test puede llamar a
    ``configure_worker_logger()`` varias veces seguidas y verificar
    que cada invocacion es independiente.
    """
    logger = logging.getLogger(_LOGGER_NAME)
    for handler in list(logger.handlers):
        try:
            handler.close()
        except Exception:
            pass
        logger.removeHandler(handler)
    logger.setLevel(logging.NOTSET)
    logger.propagate = True
    _already_configured[0] = False


__all__ = [
    "JsonLineFormatter",
    "_LOGGER_NAME",
    "configure_worker_logger",
    "log_event",
    "reset_worker_logger_for_tests",
]
