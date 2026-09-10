"""Supervisor del web server FastAPI con auto-restart.

Aloja uvicorn en un hilo daemon y lo relanza con backoff si muere por
un error no solicitado. Una parada explícita vía ``stop()`` no
dispara restart. El gateway usa ``persistent=True`` para aprovechar
el worker persistente en el flujo de bandeja.

API pública de ``WebServiceSupervisor``:
  - ``start()``             → lanza el hilo (idempotente).
  - ``stop(timeout)``       → señaliza parada limpia, espera al hilo.
  - ``is_alive() -> bool``  → True si el supervisor está corriendo.
  - ``restart_count``       → contador de reinicios (para el menú "Estado").
"""
from __future__ import annotations

import asyncio
import io
import logging
import sys
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
        """Construye la app y corre uvicorn hasta que pare.

        El arranque real del worker persistente lo hace el lifespan de
        FastAPI (``interfaces/web_server/app.py::_tia_lifespan``), no
        esta función. El motivo: ``gateway.start()`` crea un reader
        task asyncio que debe vivir en el mismo event loop que
        uvicorn para que los endpoints HTTP lo puedan usar. Si lo
        lanzáramos aquí con ``asyncio.run``, ese loop se cerraría al
        retornar y el reader task quedaría muerto.
        """
        # Importación tardía: respeta el orden de inicialización de
        # pystray (algunos backends de pystray requieren que el main
        # thread sea el del icono).
        from core.infrastructure.gateway import TIAProcessGateway
        from interfaces.web_server.app import create_app

        gateway = TIAProcessGateway(persistent=True)
        self.log.info(
            "WebServiceSupervisor: gateway preparado (persistent=True). "
            "El worker persistente lo arrancara el lifespan de FastAPI "
            "al startup de uvicorn (mismo event loop, reader task vivo)."
        )
        app = create_app(gateway)
        # Guardamos la referencia al gateway en self para que el
        # ``finally`` de abajo pueda llamar a ``disconnect()`` como
        # red de seguridad. El lifespan de FastAPI ya hace esto al
        # shutdown normal, pero si uvicorn crashea antes del
        # lifespan cleanup, o si la app se destruye por una excepción
        # en startup, esta red evita que el subproceso del worker
        # persistente quede zombi (~200 MB con el .pyd cargado).
        self._gateway = gateway

        # Compatibilidad con modo windowed (pythonw.exe / frozen).
        # uvicorn asume ``sys.stdout.isatty()`` en su formatter de
        # colores; si sys.stdout es ``None`` (modo windowed), crashea
        # durante ``uvicorn.Config.__init__``. Ver docstring de
        # ``_patch_stdio_for_uvicorn`` más abajo.
        with _patch_stdio_for_uvicorn():
            config = uvicorn.Config(
                app,
                host=self.host,
                port=self.port,
                log_level="info",
                access_log=False,  # Evita duplicar info en el log file.
            )
        self._server = uvicorn.Server(config)

        # Reconfigurar loggers de uvicorn JUSTO después de que su
        # ``Config.__init__`` los haya poblado (ver docstring de
        # ``_reconfigure_uvicorn_loggers``).
        _reconfigure_uvicorn_loggers()

        self._healthy.set()
        self.log.info("Web server arrancando en http://%s:%d", self.host, self.port)
        try:
            self._server.run()
        finally:
            # Red de seguridad: si el lifespan de FastAPI no llamó a
            # ``gateway.disconnect()`` (p. ej. uvicorn crashea antes
            # del lifespan cleanup), lo llamamos aquí. ``disconnect()``
            # es idempotente, así que en el path normal donde el
            # lifespan ya llamó, esta segunda llamada es un no-op.
            gateway = getattr(self, "_gateway", None)
            if (
                gateway is not None
                and getattr(gateway, "persistent", False)
                and callable(getattr(gateway, "disconnect", None))
            ):
                try:
                    # ``_serve_once`` es sync y uvicorn crea y destruye
                    # su propio loop internamente. En el path canónico
                    # no hay loop corriendo al llegar aquí, así que
                    # ``asyncio.run()`` es seguro. Si por algún motivo
                    # hubiera loop vivo, el ``except`` de abajo absorbe
                    # el ``RuntimeError`` y no enmascaramos el shutdown.
                    asyncio.run(gateway.disconnect())
                except Exception as exc:  # noqa: BLE001
                    self.log.warning(
                        "gateway.disconnect() en supervisor fallo: %s", exc
                    )
            self._healthy.clear()
            self._server = None


__all__ = ["WebServiceSupervisor", "_reconfigure_uvicorn_loggers", "_patch_stdio_for_uvicorn"]


import contextlib


@contextlib.contextmanager
def _patch_stdio_for_uvicorn() -> object:
    """Reemplaza ``sys.stdout`` / ``sys.stderr`` por ``io.StringIO()`` si
    son ``None``, y los restaura al salir.

    Por qué: ``uvicorn.Config.__init__`` invoca su formatter por
    defecto, que llama ``sys.stdout.isatty()`` para decidir si usar
    colores ANSI. En modo windowed (``pythonw.exe`` o frozen sin
    consola), ``sys.stdout`` es ``None`` y uvicorn crashea con::

        AttributeError: 'NoneType' object has no attribute 'isatty'

    Redirigir a ``io.StringIO()`` evita el crash. Los writes a esos
    buffers descartables se pierden: en modo windowed no hay consola
    donde escribir. Los logs reales van al root logger (``zc_tray``)
    vía ``_reconfigure_uvicorn_loggers``.
    """
    saved_stdout, saved_stderr = sys.stdout, sys.stderr
    try:
        if sys.stdout is None:
            sys.stdout = io.StringIO()
        if sys.stderr is None:
            sys.stderr = io.StringIO()
        yield
    finally:
        sys.stdout, sys.stderr = saved_stdout, saved_stderr


def _reconfigure_uvicorn_loggers() -> None:
    """Quita los ``StreamHandler`` de los loggers de uvicorn y fuerza
    ``propagate=True`` para que los mensajes lleguen al root logger
    con su nivel original (sin recategorizarse por el redirect de
    ``sys.stderr`` en modo windowed).

    Uvicorn añade un ``StreamHandler`` a ``uvicorn``,
    ``uvicorn.error`` y ``uvicorn.access`` durante
    ``uvicorn.Config.__init__``. Si lo dejamos, en modo windowed un
    ``INFO`` de uvicorn acaba logueado como
    ``[ERROR] zc_tray: INFO:     Started server process [28752]``
    porque el redirect de ``main_tray`` recaptura el stream.

    Expuesta a nivel de módulo (prefijo ``_`` = uso interno) para
    que sea testeable sin instanciar ``uvicorn.Config``.
    """
    import logging

    for _uv_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        _uv_logger = logging.getLogger(_uv_name)
        # Eliminar SOLO los ``StreamHandler`` exactos (no subclases
        # como ``FileHandler``, que sí queremos preservar si alguien
        # los añadió explícitamente). ``type(h) is StreamHandler``
        # excluye ``FileHandler`` y otras subclases. Razón: uvicorn
        # usa ``StreamHandler(sys.stderr)`` puro por defecto, y ese
        # stream está siendo capturado por el redirect de
        # ``main_tray``, así que cualquier write acabaría
        # re-clasificándose como ``ERROR``.
        _uv_logger.handlers = [
            h for h in _uv_logger.handlers
            if type(h) is not logging.StreamHandler
        ]
        _uv_logger.propagate = True
