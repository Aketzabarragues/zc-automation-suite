"""Supervisor del OB1 (Fase 4 / 4.N1).

Aloja el Flask daemon y el OB1 main loop en hilos daemon. Auto-restart
con backoff si cualquiera de los dos muere por error no solicitado.

Diseño (sept-2026):
  - El OB1 main loop vive en un hilo daemon dedicado (``ob1-loop``).
    NO en el main thread (ese lo ocupa pystray en modo bandeja).
  - El Flask server vive en otro hilo daemon (``flask-daemon``).
  - Ambos hilos comparten el mismo ``SyncTIAClient`` (es thread-safe
    via ``queue.Queue`` interna), ``Engine`` (sync, ticks desde el OB1
    loop) y ``EventBusSync`` (queue.Queue, thread-safe).
  - El shutdown se propaga via ``threading.Event``: cuando ``stop()``
    se llama, ambos hilos ven el flag y salen limpiamente.

API pública (idéntica a ``WebServiceSupervisor`` para que el tray menu
sea intercambiable):
  - ``start()``             -> arranca ambos hilos (idempotente).
  - ``stop(timeout)``       -> señaliza parada, espera a ambos hilos.
  - ``is_alive() -> bool``  -> True si Flask esta healthy + OB1 vivo.
  - ``restart_count``       -> contador de reinicios.

Trade-off aceptado: Flask dev server es single-threaded (``threaded=False``),
asi que HTTP requests serializan contra el OB1 main loop en el mismo
proceso. Para 1 operario, <10 req/s, OK.
"""
from __future__ import annotations

import logging
import threading
import time
import traceback

from werkzeug.serving import make_server


class Ob1ServiceSupervisor:
    """Ejecuta Flask daemon + OB1 main loop en hilos daemon; auto-restart."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5000,
        tick_period_s: float = 0.1,
        no_engine: bool = False,
    ) -> None:
        self.host = host
        self.port = port
        self.tick_period_s = tick_period_s
        self.no_engine = no_engine
        self.log = logging.getLogger("zc.tray.ob1")

        self._stop_event = threading.Event()
        # Hilos daemon.
        self._flask_thread: threading.Thread | None = None
        self._loop_thread: threading.Thread | None = None
        # Flask server (para shutdown limpio).
        self._flask_server = None  # type: ignore[assignment]
        # Estado: True cuando ambos hilos están corriendo.
        self._healthy = threading.Event()
        self.restart_count = 0
        # Lock para serializar start/stop desde el hilo del tray icon.
        self._lifecycle_lock = threading.Lock()

    # ── API pública ───────────────────────────────────────────────
    def start(self) -> None:
        """Lanza Flask daemon + OB1 main loop (idempotente)."""
        with self._lifecycle_lock:
            if self._is_running():
                self.log.debug("start() llamado pero ya estaba vivo; no-op.")
                return
            self._stop_event.clear()
            self._healthy.clear()
            # Construir components ANTES de lanzar los hilos (sin race).
            try:
                self._components = self._build_components()
            except Exception as exc:  # noqa: BLE001
                self.log.error("start: _build_components() falló: %s", exc)
                return
            self._flask_thread = threading.Thread(
                target=self._run_flask_forever,
                name="flask-daemon",
                daemon=True,
            )
            self._loop_thread = threading.Thread(
                target=self._run_ob1_loop_forever,
                name="ob1-loop",
                daemon=True,
            )
            self._flask_thread.start()
            self._loop_thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Solicita el cierre de ambos hilos y espera."""
        with self._lifecycle_lock:
            self._stop_event.set()
            # Señal de parada limpia para werkzeug (si está vivo).
            if self._flask_server is not None:
                try:
                    self._flask_server.shutdown()
                except Exception as exc:  # noqa: BLE001
                    self.log.warning("flask server.shutdown() falló: %s", exc)
            flask_t = self._flask_thread
            loop_t = self._loop_thread
        # Join fuera del lock para no bloquear otros callers.
        for label, thread in (("flask", flask_t), ("ob1-loop", loop_t)):
            if thread is None:
                continue
            thread.join(timeout=timeout)
            if thread.is_alive():
                self.log.warning(
                    "Hilo %s no terminó en %.1fs; se abandona (daemon).",
                    label,
                    timeout,
                )
            else:
                self.log.info("Hilo %s terminado limpiamente.", label)
        self._healthy.clear()
        self._flask_thread = None
        self._loop_thread = None
        self._components = None

    def is_alive(self) -> bool:
        """True si ambos hilos están corriendo."""
        return (
            self._healthy.is_set()
            and self._flask_thread is not None
            and self._flask_thread.is_alive()
            and self._loop_thread is not None
            and self._loop_thread.is_alive()
        )

    # ── Internals ─────────────────────────────────────────────────
    def _is_running(self) -> bool:
        return (
            (self._flask_thread is not None and self._flask_thread.is_alive())
            or (self._loop_thread is not None and self._loop_thread.is_alive())
        )

    def _build_components(self):
        """Crea tia_client, engine, event_bus, flask_app.

        Se llama UNA VEZ en start(); los objetos se comparten entre los
        dos hilos. Los re-creamos en cada reinicio tras crash.
        """
        from core.infrastructure.tia_client import (
            SyncTIAClient,
            register_core_commands,
        )
        from core.plc.engine import Engine
        from core.sse.event_bus_sync import EventBusSync
        from interfaces.web_server.app_flask import create_app

        tia_client = SyncTIAClient()
        register_core_commands(tia_client)
        engine = Engine(tick_period_s=self.tick_period_s) if not self.no_engine else None
        event_bus = EventBusSync()
        flask_app = create_app(
            tia_client=tia_client,
            engine=engine,
            event_bus=event_bus,
        )
        return tia_client, engine, event_bus, flask_app

    def _run_flask_forever(self) -> None:
        """Hilo daemon: arranca werkzeug make_server, vigila, reinicia."""
        backoff = 1.0
        while not self._stop_event.is_set():
            try:
                self._serve_flask_once()
                # werkzeug retorna cuando shutdown() se llama.
                self.log.info("Flask daemon: server exited (shutdown solicitado).")
                break
            except Exception as exc:  # noqa: BLE001
                self._healthy.clear()
                self.restart_count += 1
                self.log.error(
                    "Flask daemon crasheó (restart #%d): %s\n%s",
                    self.restart_count,
                    exc,
                    traceback.format_exc(),
                )

            if self._stop_event.is_set():
                break
            self.log.info(
                "Reintento del Flask daemon en %.1fs (intento #%d).",
                backoff,
                self.restart_count,
            )
            if self._stop_event.wait(timeout=backoff):
                break
            backoff = min(backoff * 2, 30.0)

    def _serve_flask_once(self) -> None:
        """Construye y sirve Flask hasta que ``stop()`` lo apague."""
        # Las components se construyen en start() (compartidas con OB1 loop).
        # Aqui solo creamos el server de werkzeug.
        _, _, _, flask_app = self._components
        server = make_server(
            host=self.host,
            port=self.port,
            app=flask_app,
            threaded=False,  # single-threaded: serializa contra OB1
        )
        self._flask_server = server
        self.log.info(
            "Flask daemon arrancando en http://%s:%d (threaded=False).",
            self.host,
            self.port,
        )
        self._healthy.set()
        try:
            server.serve_forever()
        finally:
            self._healthy.clear()
            self._flask_server = None

    def _run_ob1_loop_forever(self) -> None:
        """Hilo daemon: OB1 main loop (dispatch TIA + engine tick)."""
        tia_client, engine, _, _ = self._components

        self.log.info(
            "OB1 main loop arrancando (tick=%dms, engine=%s).",
            int(self.tick_period_s * 1000),
            "ON" if engine is not None else "OFF",
        )
        try:
            while not self._stop_event.is_set():
                # 1. Drenar cola TIA (commands submitted por Flask thread).
                try:
                    tia_client.dispatch_pending()
                except Exception as exc:  # noqa: BLE001
                    self.log.exception("OB1 loop: dispatch_pending() failed: %s", exc)
                # 2. Tick engine.
                if engine is not None:
                    try:
                        engine.run_cycle()
                    except Exception as exc:  # noqa: BLE001
                        self.log.exception("OB1 loop: engine.run_cycle() failed: %s", exc)
                # 3. Sleep (cede CPU al Flask daemon y otros hilos).
                #    Esperamos al stop_event con timeout para responder rápido.
                if self._stop_event.wait(timeout=self.tick_period_s):
                    break
        except Exception as exc:  # noqa: BLE001
            self.log.error("OB1 loop crasheó: %s\n%s", exc, traceback.format_exc())
        finally:
            self.log.info("OB1 main loop: bye.")

    # ── Diagnostics ──────────────────────────────────────────────
    def wait_until_alive(self, timeout_s: float = 10.0) -> bool:
        """Espera a que Flask esté bindeado + OB1 loop vivo. Útil para tests."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.is_alive():
                return True
            time.sleep(0.1)
        return False


__all__ = ["Ob1ServiceSupervisor"]
