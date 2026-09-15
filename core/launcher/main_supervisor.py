"""Aloja Flask daemon y main loop en hilos daemon; auto-restart con backoff.

Dos hilos daemon:
  - ``flask-daemon``: werkzeug serve_forever (threaded=True).
  - ``main-loop``: drena la cola TIA + tickea el Engine.

Comparten ``SyncTIAClient``, ``Engine`` y ``EventBusSync`` (thread-safe).
Shutdown via ``threading.Event``: stop() señaliza, ambos hilos salen limpios.

API:
  - start()              -> arranca ambos hilos (idempotente).
  - stop(timeout)        -> señaliza parada, espera a ambos hilos.
  - is_alive() -> bool   -> True si Flask bindeado + main loop vivo.
  - restart_count        -> contador de reinicios tras crash.

Flask se levanta con ``threaded=True``: el SSE de larga vida no
bloquea las demás requests HTTP. Para 1 operario (<10 req/s) OK.
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
from typing import Any

from werkzeug.serving import make_server


class MainServiceSupervisor:
    """Flask daemon + main loop en hilos daemon; auto-restart con backoff."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5000,
        tick_period_s: float = 0.1,
        no_engine: bool = False,
        config_manager: Any = None,
        event_bus: Any = None,
    ) -> None:
        self.host = host
        self.port = port
        self.tick_period_s = tick_period_s
        self.no_engine = no_engine
        self.config_manager = config_manager
        self.event_bus = event_bus  # si None, _build_components crea uno
        self.log = logging.getLogger("zc.main")

        self._stop_event = threading.Event()
        self._flask_thread: threading.Thread | None = None
        self._loop_thread: threading.Thread | None = None
        self._flask_server = None  # type: ignore[assignment]
        self._healthy = threading.Event()
        self.restart_count = 0
        self._lifecycle_lock = threading.Lock()

    def start(self) -> None:
        """Lanza Flask daemon + main loop (idempotente)."""
        with self._lifecycle_lock:
            if self._is_running():
                self.log.debug("start() llamado pero ya estaba vivo; no-op.")
                return
            self._stop_event.clear()
            self._healthy.clear()
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
                target=self._run_main_loop_forever,
                name="main-loop",
                daemon=True,
            )
            self._flask_thread.start()
            self._loop_thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Solicita el cierre de los hilos y espera (orden inverso).

        Orden: main-loop -> flask -> tia-loop. tia-loop al final
        para que el wrapper siga vivo mientras Flask drena respuestas
        pendientes a commands ya encolados.
        """
        with self._lifecycle_lock:
            self._stop_event.set()
            if self._flask_server is not None:
                try:
                    self._flask_server.shutdown()
                except Exception as exc:  # noqa: BLE001
                    self.log.warning("flask server.shutdown() falló: %s", exc)
            flask_t = self._flask_thread
            loop_t = self._loop_thread
            tia_client = self._components[0] if self._components else None
        # Join fuera del lock para no bloquear otros callers.
        for label, thread in (("main-loop", loop_t), ("flask", flask_t)):
            if thread is None:
                continue
            thread.join(timeout=timeout)
            if thread.is_alive():
                self.log.warning(
                    "Hilo %s no terminó en %.1fs; se abandona (daemon).",
                    label, timeout,
                )
            else:
                self.log.info("Hilo %s terminado limpiamente.", label)
        # tia-loop al final: drena la cola pendiente y luego sale.
        if tia_client is not None:
            tia_client.stop_tia_loop(timeout=timeout)
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

    def wait_until_alive(self, timeout_s: float = 10.0) -> bool:
        """Espera a que Flask esté bindeado + main loop vivo. Útil para tests."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.is_alive():
                return True
            time.sleep(0.1)
        return False

    def _is_running(self) -> bool:
        return (
            (self._flask_thread is not None and self._flask_thread.is_alive())
            or (self._loop_thread is not None and self._loop_thread.is_alive())
        )

    def _build_components(self):
        """Crea tia_client, engine, event_bus, flask_app. Compartidos entre hilos.

        Orden importante:
          1. tia_client + start_tia_loop() ANTES de Flask. Si falla la
             carga del wrapper .NET, _build_components() lanza y Flask
             nunca arranca (fail-fast, el operario ve el error al
             pulsar "Iniciar web").
          2. engine + event_bus + flask_app.
          3. wire_all() cablea LogBuffer, ProgressTracker, tia_client y
             engine al bus SSE.
        """
        from core.infrastructure.tia.tia_loop import SyncTIAClient
        from core.infrastructure.tia.tia_handlers import register_core_commands
        from core.composition.plc_engine import Engine
        from core.runtime.sse.sse_event_bus_sync import EventBusSync
        from core.web_server.app_flask import create_app

        tia_client = SyncTIAClient()
        register_core_commands(tia_client)
        engine = Engine(tick_period_s=self.tick_period_s) if not self.no_engine else None
        if engine is not None:
            # Registrar los FBs del area (template + futuros reales).
            from core.runtime.log_buffer import get_log_buffer
            from areas.alimentacion import register as register_alimentacion
            register_alimentacion(
                engine,
                config_manager=self.config_manager,
                tia_client=tia_client,
                log=get_log_buffer(),
            )
        event_bus = self.event_bus if self.event_bus is not None else EventBusSync()
        flask_app = create_app(
            tia_client=tia_client,
            engine=engine,
            event_bus=event_bus,
            config_manager=self.config_manager,
        )
        # Cablea los 5 publishers al bus ANTES de arrancar el tia-loop
        # para que ``on_loop_status`` capture el evento "running=true"
        # en cuanto el hilo arranca. Idempotente si los hooks no existen
        # (log warn + skip).
        from core.runtime.log_buffer import get_log_buffer
        from core.runtime.progress_buffer import get_progress_tracker
        from core.runtime.sse.sse_publishers import wire_all
        wire_all(
            log_buffer=get_log_buffer(),
            progress_tracker=get_progress_tracker(),
            tia_client=tia_client,
            engine=engine,
            bus=event_bus,
        )
        # tia-loop arranca ultimo: si la carga del wrapper falla, los
        # publishers ya estan cableados (al menos log+progress), y el
        # fallo se loggea a LogBuffer para que el operario lo vea en
        # la consola.
        tia_client.start_tia_loop()
        return tia_client, engine, event_bus, flask_app

    def _run_flask_forever(self) -> None:
        """Hilo daemon: werkzeug serve_forever, vigila, reinicia con backoff."""
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
                    self.restart_count, exc, traceback.format_exc(),
                )

            if self._stop_event.is_set():
                break
            self.log.info(
                "Reintento del Flask daemon en %.1fs (intento #%d).",
                backoff, self.restart_count,
            )
            if self._stop_event.wait(timeout=backoff):
                break
            backoff = min(backoff * 2, 30.0)

    def _serve_flask_once(self) -> None:
        """Sirve Flask hasta que stop() lo apague."""
        _, _, _, flask_app = self._components
        server = make_server(
            host=self.host,
            port=self.port,
            app=flask_app,
            threaded=True,  # multi-thread: el SSE de larga vida no bloquea el resto de requests
        )
        self._flask_server = server
        self.log.info(
            "Flask daemon arrancando en http://%s:%d (threaded=True).",
            self.host, self.port,
        )
        self._healthy.set()
        try:
            server.serve_forever()
        finally:
            self._healthy.clear()
            self._flask_server = None

    def _run_main_loop_forever(self) -> None:
        """Hilo daemon: engine tick en bucle. TIA tiene su propio hilo."""
        _, engine, _, _ = self._components

        self.log.info(
            "Main loop arrancando (tick=%dms, engine=%s).",
            int(self.tick_period_s * 1000),
            "ON" if engine is not None else "OFF",
        )
        try:
            while not self._stop_event.is_set():
                # Tick engine. (TIA tiene su propio hilo tia-loop.)
                if engine is not None:
                    try:
                        engine.run_cycle()
                    except Exception as exc:  # noqa: BLE001
                        self.log.exception("Main loop: engine.run_cycle() failed: %s", exc)
                # Sleep con stop_event.wait para responder rápido al shutdown.
                if self._stop_event.wait(timeout=self.tick_period_s):
                    break
        except Exception as exc:  # noqa: BLE001
            self.log.error("Main loop crasheó: %s\n%s", exc, traceback.format_exc())
        finally:
            self.log.info("Main loop: bye.")


__all__ = ["MainServiceSupervisor"]
