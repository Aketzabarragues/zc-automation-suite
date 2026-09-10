"""Application Layer - Log Buffer (Singleton).

Buffer circular thread-safe que la SPA consulta via polling para
mostrar mensajes de trazabilidad al operario.

Estrategia: cualquier módulo del backend (gateway, use cases,
modifiers) puede llamar ``log_buffer.info("...")`` y el mensaje
aparece automáticamente en la consola inferior de la SPA sin acoplarse
a la implementación del transporte (HTTP, MCP, CLI, ...).
"""

from __future__ import annotations

from collections import deque
from datetime import datetime
from threading import Lock
from typing import Any


class LogBuffer:
    """Buffer FIFO circular thread-safe de mensajes de log.

    Mantiene como máximo ``maxlen`` mensajes (los más antiguos se
    descartan al llegar nuevos). Cada mensaje tiene ``timestamp`` y
    ``level`` (info / success / warning / error).
    """

    def __init__(self, maxlen: int = 200) -> None:
        self._buffer: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._lock: Lock = Lock()

    def _push(self, level: str, message: str) -> None:
        """Inserta un mensaje con timestamp."""
        entry = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "level": level,
            "message": message,
        }
        with self._lock:
            self._buffer.append(entry)

    # ── API pública por nivel ──────────────────────────────────────────

    def info(self, message: str) -> None:
        self._push("info", message)

    def success(self, message: str) -> None:
        self._push("success", message)

    def warning(self, message: str) -> None:
        self._push("warning", message)

    def error(self, message: str) -> None:
        self._push("error", message)

    # ── Lectura (usada por polling de la SPA) ─────────────────────────

    def snapshot(self) -> list[dict[str, Any]]:
        """Devuelve una copia inmutable de los mensajes actuales."""
        with self._lock:
            return list(self._buffer)

    def clear(self) -> None:
        """Vacía el buffer."""
        with self._lock:
            self._buffer.clear()


# ── Singleton thread-safe ────────────────────────────────────────────


_buffer: LogBuffer | None = None
_buffer_lock: Lock = Lock()


def get_log_buffer() -> LogBuffer:
    """Devuelve la instancia Singleton de ``LogBuffer``."""
    global _buffer
    if _buffer is None:
        with _buffer_lock:
            if _buffer is None:
                _buffer = LogBuffer()
    return _buffer


__all__ = ["LogBuffer", "get_log_buffer"]
