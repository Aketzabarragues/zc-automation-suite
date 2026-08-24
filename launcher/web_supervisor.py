"""Supervisor del web server FastAPI con auto-restart.

Aloja el servidor FastAPI/uvicorn en un hilo daemon y lo reinicia
automáticamente si muere por un error no solicitado. La parada explícita
(vía ``stop()``) NO dispara restart.

API pública (gemela de ``MCPServiceSupervisor``):
  - ``start()``             → lanza el hilo (idempotente).
  - ``stop(timeout)``       → señaliza parada limpia, espera al hilo.
  - ``is_alive() -> bool``  → True si el supervisor está corriendo.
  - ``restart_count``       → contador de reinicios (para el menú "Estado").

Notas sobre el worker OT:
  - El worker OT (process-per-call) lo sigue lanzando el gateway
    existente (``TIAProcessGateway._dispatch_worker``) por cada comando.
    Esta capa NO lanza workers persistentes: respetar el patrón
    process-per-call del manual V1.2.1 es innegociable.
  - "El worker se reinicia solo si muere" ya lo cumple el gateway: cada
    llamada crea un subproceso nuevo. Esta capa solo asegura que el
    **proceso web** (el que aloja el gateway) esté vivo.
"""
from __future__ import annotations

import logging
import threading
import traceback

import uvicorn


class WebServiceSupervisor:
    """Ejecuta uvicorn en un hilo daemon; auto-restart con backoff."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8000) -> None:
        self.host = host
        self.port = port
        self.log = logging.getLogger("zc_tray.web")
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._server: uvicorn.Server | None = None
        self._healthy = threading.Event()
        self.restart_count = 0
        # Lock para serializar arranques/paradas (start/stop pueden
        # llamarse desde el hilo del tray icon).
        self._lifecycle_lock = threading.Lock()

    # ── API pública ───────────────────────────────────────────────
    def start(self) -> None:
        """Lanza el hilo supervisor (idempotente)."""
        with self._lifecycle_lock:
            if self._thread and self._thread.is_alive():
                self.log.debug("start() llamado pero ya estaba vivo; no-op.")
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_forever,
                name="zc-web-supervisor",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Solicita el cierre del web server y espera al hilo."""
        with self._lifecycle_lock:
            self._stop_event.set()
            if self._server is not None:
                # Señal de parada limpia para uvicorn.
                self._server.should_exit = True
            thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
            if thread.is_alive():
                self.log.warning(
                    "El hilo supervisor no terminó en %.1fs; se abandona (daemon).",
                    timeout,
                )
            else:
                self.log.info("Hilo supervisor terminado limpiamente.")

    def is_alive(self) -> bool:
        """True si el web server está actualmente levantado."""
        return (
            self._healthy.is_set()
            and self._thread is not None
            and self._thread.is_alive()
        )

    # ── Bucle supervisor ─────────────────────────────────────────
    def _run_forever(self) -> None:
        """Bucle principal: arranca, vigila, reinicia con backoff."""
        backoff = 1.0
        while not self._stop_event.is_set():
            try:
                self._serve_once()
                # Si retorna sin excepción, uvicorn salió solo.
                # Si NO fue shutdown solicitado, es crash silencioso
                # → re-entrar al bucle para reiniciar.
                if self._stop_event.is_set():
                    self.log.info("Web server detenido por solicitud de shutdown.")
                    break
                self.restart_count += 1
                self.log.warning(
                    "Web server salió inesperadamente; restart #%d programado.",
                    self.restart_count,
                )
            except Exception as exc:  # noqa: BLE001
                self._healthy.clear()
                self.restart_count += 1
                self.log.error(
                    "Web server crasheó (restart #%d): %s\n%s",
                    self.restart_count,
                    exc,
                    traceback.format_exc(),
                )

            if self._stop_event.is_set():
                break

            # Backoff antes de reintentar (cap a 30s).
            self.log.info(
                "Reintento del web server en %.1fs (intento #%d).",
                backoff,
                self.restart_count,
            )
            if self._stop_event.wait(timeout=backoff):
                break
            backoff = min(backoff * 2, 30.0)

    def _serve_once(self) -> None:
        """Construye la app y corre uvicorn hasta que pare."""
        # Importación tardía: respeta el orden de inicialización de
        # pystray (algunos backends de pystray requieren que el main
        # thread sea el del icono).
        from infrastructure.gateway import TIAProcessGateway
        from interfaces.web_server.app import create_app

        gateway = TIAProcessGateway()
        app = create_app(gateway)
        config = uvicorn.Config(
            app,
            host=self.host,
            port=self.port,
            log_level="info",
            access_log=False,  # Evita duplicar info en el log file.
        )
        self._server = uvicorn.Server(config)
        self._healthy.set()
        self.log.info("Web server arrancando en http://%s:%d", self.host, self.port)
        try:
            self._server.run()
        finally:
            self._healthy.clear()
            self._server = None


__all__ = ["WebServiceSupervisor"]
