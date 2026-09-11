"""
SyncTIAClient — cliente sync al wrapper siemens_tia_scripting (DA-014).

Skeleton (Fase 4 / paso 4.1.1). Comandos core se migran en 4.1.2.
Areas registran comandos extra en 4.1.3.

Reemplaza gateway.py + worker_tia.py. Vive en el mismo proceso que Flask
y el loop OB1. NO subproceso. NO asyncio. NO IPC.

Modelo OB1:
- Hilo OB1 (main loop) llama dispatch() y dispatch_pending() por ciclo.
- Hilo Flask encola comandos via submit() (thread-safe, queue.Queue).
- Hilo OB1 es el UNICO que llama metodos sobre tia_client.wrapper
  (acceso single-threaded al wrapper .NET, evita RCW races).

Carga del wrapper:
- El skeleton NO carga siemens_tia_scripting.pyd (eso requiere stage en
  tempfile y queda fuera de este paso).
- main.py (4.5.1) hace: tia_client.attach_wrapper(loader.load()).
- Tests inyectan mocks via attach_wrapper().
"""
from __future__ import annotations

import logging
import queue
from typing import Callable

logger = logging.getLogger(__name__)

# Firma de un handler: recibe args dict, retorna dict serializable.
# Los handlers acceden al wrapper via tia_client.wrapper.
HandlerSig = Callable[[dict], dict]


class SyncTIAClient:
    """Cliente sync al wrapper TIA. OB1-friendly, sin subproceso."""

    def __init__(self) -> None:
        self._handlers: dict[str, HandlerSig] = {}
        self._pending: queue.Queue[tuple[str, dict]] = queue.Queue()
        # Placeholder; main.py attach_wrapper() lo rellena en arranque.
        # Antes de attach, dispatch() funciona solo con handlers que no
        # tocan el wrapper (util para tests y para el spike).
        self._wrapper = None

    # ----------------------------------------------------------- API publica
    def register_command(self, name: str, handler: HandlerSig) -> None:
        """Registra un handler para `name`. Llamado por areas al import."""
        if name in self._handlers:
            raise ValueError(f"command already registered: {name}")
        self._handlers[name] = handler
        logger.debug("registered command: %s", name)

    def dispatch(self, command: str, args: dict | None = None) -> dict:
        """Dispatcher sync. Solo llamado desde el hilo OB1.

        Shape de retorno: {"ok": True, "result": <dict>} o
        {"ok": False, "error": "<msg>"}.
        """
        handler = self._handlers.get(command)
        if handler is None:
            return {"ok": False, "error": f"unknown_command:{command}"}
        try:
            return {"ok": True, "result": handler(args or {})}
        except Exception as exc:  # noqa: BLE001 - captura cualquier fallo de handler
            logger.exception("dispatch failed: %s", command)
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def submit(self, command: str, args: dict | None = None) -> None:
        """Encola comando para drenar en el proximo ciclo OB1. Thread-safe.

        Pensado para que el hilo Flask encole sin bloquear.
        """
        self._pending.put((command, args or {}))

    def dispatch_pending(self) -> int:
        """Drena cola FIFO y ejecuta cada comando. Solo hilo OB1.

        Retorna el numero de comandos procesados en este drain.
        """
        processed = 0
        while True:
            try:
                cmd, args = self._pending.get_nowait()
            except queue.Empty:
                return processed
            self.dispatch(cmd, args)
            processed += 1

    # --------------------------------------------------------------- helpers
    def attach_wrapper(self, wrapper) -> None:
        """Adjunta un wrapper ya cargado (mock en tests, .pyd real en main).

        Solo el hilo OB1 debe llamarlo.
        """
        self._wrapper = wrapper

    @property
    def wrapper(self):
        """Accessor del wrapper siemens_tia_scripting.

        Acceso single-threaded: solo el hilo OB1 debe llamar metodos sobre
        el objeto retornado (los RCW .NET no son thread-safe).
        """
        return self._wrapper

    def has_command(self, name: str) -> bool:
        return name in self._handlers

    def registered_commands(self) -> list[str]:
        return sorted(self._handlers.keys())


# Singleton de proceso. main.py (4.5.1) hace tia_client = SyncTIAClient().
# Los modulos que quieran un mock en tests pueden sobreescribirlo.
tia_client = SyncTIAClient()
