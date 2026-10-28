"""Aloja Flask daemon y dispatcher OB1 en hilos daemon.

Dos hilos daemon:
  - ``flask-daemon``: werkzeug serve_forever (threaded=True).
  - ``plc-ob1``: dispatcher del OB1 (hilo propiedad del Engine).

El worker TIA tiene su propio hilo (``tia_loop``), no lo crea el
supervisor.

Comparten ``SyncTIAClient``, ``Engine`` y ``EventBusSync`` (thread-safe).
Shutdown via ``threading.Event``: stop() señaliza, los hilos salen limpios.

API:
  - start()              -> arranca el dispatcher OB1 + Flask (idempotente).
  - stop(timeout)        -> señaliza parada, espera a los hilos en orden.
  - is_alive() -> bool   -> True si Flask bindeado.
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

from core.runtime.log_buffer import get_log_buffer


# Subdirs de ``<cwd>/.build_cache/`` que NO son areas registradas
# (viven en ``core/``) y aun asi deben limpiarse al cerrar la app.
# Coinciden 1:1 con el ``area_id`` del ``_workdir_layout`` correspondiente.
_CORE_BUILD_CACHE_SUBDIRS: tuple[str, ...] = (
    "blocks_edit",
)


class MainServiceSupervisor:
    """HMI + OB1 + WORKER: ciclo de vida de los hilos del proceso.

    Contrato de arranque:
      - ``start()`` construye las componentes, arranca el dispatcher OB1
        del ``Engine`` y luego el hilo de Flask.

    Contrato de parada (orden inverso al de arranque):
      - flask -> dispatcher OB1 -> tia-loop.

    El dispatcher OB1 se para antes que el worker TIA: los FBs que
    ejecuta usan ``submit_and_wait``, asi que un trabajo en curso
    necesita el worker vivo para poder terminar.
    """

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
        self._flask_server = None  # type: ignore[assignment]
        self._healthy = threading.Event()
        self.restart_count = 0
        self._lifecycle_lock = threading.Lock()

    def start(self) -> None:
        """Lanza el dispatcher OB1 y el daemon de Flask (idempotente)."""
        with self._lifecycle_lock:
            if self._is_running():
                self.log.debug("start() llamado pero ya estaba vivo; no-op.")
                return
            self._stop_event.clear()
            self._healthy.clear()
            # Cleanup de .build_cache/<area>/ al arrancar (simetrico con
            # stop()). Un fallo aqui NO aborta el supervisor: la app
            # debe poder arrancar aunque el cleanup falle para que el
            # operario vea el error en consola.
            if self.config_manager is not None:
                try:
                    self._cleanup_build_cache()
                except Exception as exc:  # noqa: BLE001
                    self.log.warning(
                        "start: _cleanup_build_cache() fallo (no aborta arranque): %s",
                        exc,
                    )
            try:
                self._components = self._build_components()
            except Exception as exc:  # noqa: BLE001
                self.log.error("start: _build_components() falló: %s", exc)
                return
            # Dispatcher OB1: sin el, engine.submit() deja los trabajos
            # en cola para siempre. Un fallo aqui NO aborta el arranque.
            self._start_ob1()
            self._flask_thread = threading.Thread(
                target=self._run_flask_forever,
                name="flask-daemon",
                daemon=True,
            )
            self._flask_thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Solicita el cierre de los hilos y espera (orden inverso).

        Orden: flask -> dispatcher OB1 -> tia-loop. El dispatcher OB1
        se para antes que el worker TIA para que un trabajo en curso
        pueda terminar contra el worker; el tia-loop al final para que
        el wrapper siga vivo mientras Flask drena respuestas pendientes
        a commands ya encolados.
        """
        with self._lifecycle_lock:
            self._stop_event.set()
            if self._flask_server is not None:
                try:
                    self._flask_server.shutdown()
                except Exception as exc:  # noqa: BLE001
                    self.log.warning("flask server.shutdown() falló: %s", exc)
            flask_t = self._flask_thread
            tia_client = self._components[0] if self._components else None
        # Join fuera del lock para no bloquear otros callers.
        if flask_t is not None:
            flask_t.join(timeout=timeout)
            if flask_t.is_alive():
                self.log.warning(
                    "Hilo flask no terminó en %.1fs; se abandona (daemon).",
                    timeout,
                )
            else:
                self.log.info("Hilo flask terminado limpiamente.")
        # Dispatcher OB1 antes del tia-loop: los FBs que ejecuta usan el
        # worker TIA (submit_and_wait) y deben poder terminar. A esta
        # altura self._components sigue vivo (se limpia al final).
        self._stop_ob1(timeout)
        # tia-loop al final: drena la cola pendiente y luego sale.
        if tia_client is not None:
            tia_client.stop_tia_loop(timeout=timeout)
        # Cleanup del ``.build_cache/<area>/`` de staging tras apagar la
        # app. Los exports, modified y preview de la sesion ya no son
        # utiles (el commit es atomico: si fallo, el PLC no cambio; si
        # salio bien, el siguiente sync re-exportara de cero). Iteramos
        # todas las areas registradas para futuro-proof (hoy solo hay
        # ``alimentacion``; ``trazabilidad``, ``recetas``, etc. entran
        # solas).
        self._cleanup_build_cache()
        # Limpia el AppCache global: la proxima invocacion de ``start()``
        # re-registrara las areas via ``AreaSpec.contributes_caches`` (que
        # llama ``app_cache.register_area(...)``). Sin esto, el 2do start
        # del ciclo Parar web / Iniciar web revienta con
        # ``area 'alimentacion' ya registrada``.
        try:
            from core.runtime.app_cache import get_app_cache
            get_app_cache().clear()
        except Exception as exc:  # noqa: BLE001
            self.log.warning(
                "stop: get_app_cache().clear() fallo (no aborta): %s",
                exc,
            )
        self._healthy.clear()
        self._flask_thread = None
        self._components = None

    def _start_ob1(self) -> None:
        """Arranca el dispatcher del OB1. No-op si no hay engine.

        Un fallo aqui NO aborta el arranque de la app: el operario ve
        el error en consola y puede seguir usando la web.
        """
        components = getattr(self, "_components", None)
        engine = components[1] if components else None
        if engine is None:
            return
        try:
            engine.start_ob1()
        except Exception as exc:  # noqa: BLE001
            self.log.warning(
                "start: engine.start_ob1() fallo (no aborta arranque): %s", exc
            )

    def _stop_ob1(self, timeout: float) -> None:
        """Para el dispatcher del OB1. No-op si no hay engine.

        Se invoca antes de parar el worker TIA: los FBs que ejecuta el
        dispatcher usan ``submit_and_wait``, asi que un trabajo en curso
        necesita el worker vivo para poder terminar.
        """
        components = getattr(self, "_components", None)
        engine = components[1] if components else None
        if engine is None:
            return
        try:
            engine.stop_ob1(timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            self.log.warning("stop: engine.stop_ob1() fallo (no aborta): %s", exc)

    def is_alive(self) -> bool:
        """True si la web y el dispatcher del OB1 estan corriendo."""
        return (
            self._healthy.is_set()
            and self._flask_thread is not None
            and self._flask_thread.is_alive()
        )

    def _cleanup_build_cache(self) -> None:
        """Borra ``<cwd>/.build_cache/<subdir>/`` para areas + core dirs.

        Lo llama ``stop()`` al apagar la app. Idempotente: si el
        directorio no existe (sesion nunca hizo export), ``rmtree``
        con ``ignore_errors=True`` es un no-op.

        La raiz ``.build_cache/`` se preserva (puede contener otras
        areas que aun no se han apagado, o artefactos historicos que
        el operario quiera inspeccionar). Solo borramos las
        subcarpetas por area/core.

        Por que NO usamos ``WorkdirContextLayout.clean()``:
        ``clean()`` borra solo ``exports/`` y ``modified/`` y deja
        ``preview/``. Aqui queremos limpieza TOTAL al apagar para
        no acumular exports de sesiones pasadas en el repo. Si el
        operario quiere mantener preview historico, basta con no
        llamar a ``stop()`` (o comentar este metodo).

        ``_CORE_BUILD_CACHE_SUBDIRS`` agrupa subdirs no-registrados
        como areas (ej. ``blocks_edit`` del editor de bloques).
        Mismo patron que las areas: ``.build_cache/<subdir>/``.
        """
        import os
        import shutil
        from pathlib import Path

        root = Path(os.getcwd()) / ".build_cache"
        if not root.exists():
            return

        try:
            from core.composition.app_area_registry import AreaRegistry
            area_ids = [spec.id for spec in AreaRegistry.discover().all()]
        except Exception as exc:  # noqa: BLE001
            # Si el registry falla (e.g. shutdown ya en curso), caemos
            # al fallback conservador: NO borrar nada. El operario lo
            # puede limpiar a mano. Mejor acumular que romper.
            self.log.warning(
                "Cleanup .build_cache: AreaRegistry indisponible (%s); "
                "se omite el cleanup automatico.",
                exc,
            )
            return

        # Unico cleanup: areas + subdirs core. ``blocks_edit`` vive en
        # core/ y por tanto NO aparece en AreaRegistry.
        subdirs = list(area_ids) + list(_CORE_BUILD_CACHE_SUBDIRS)
        if not subdirs:
            return

        for subdir in subdirs:
            area_dir = root / subdir
            if not area_dir.exists():
                continue
            try:
                shutil.rmtree(area_dir)
                self.log.info(
                    "Cleanup .build_cache: borrado %s",
                    area_dir,
                )
            except Exception as exc:  # noqa: BLE001
                # Archivos en uso por TIA u otro proceso: no abortamos
                # el shutdown, solo dejamos rastro para que el operario
                # lo limpie a mano.
                self.log.warning(
                    "Cleanup .build_cache: no se pudo borrar %s (%s)",
                    area_dir, exc,
                )

    def wait_until_alive(self, timeout_s: float = 10.0) -> bool:
        """Espera a que Flask esté bindeado + dispatcher vivo. Útil para tests."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.is_alive():
                return True
            time.sleep(0.1)
        return False

    def _is_running(self) -> bool:
        return self._flask_thread is not None and self._flask_thread.is_alive()

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
        from core.infrastructure.tia.tia_commands_catalog import register_all_commands
        from core.composition.plc_engine import Engine
        from core.runtime.app_cache import get_app_cache
        from core.runtime.sse.sse_event_bus_sync import EventBusSync
        from core.web_server.app_flask import create_app

        tia_client = SyncTIAClient()
        register_all_commands(tia_client)
        # Cablear los comandos TIA extra de cada area (transaccionales,
        # comments por hw/proc, commits online/offline de dispositivos,
        # etc). El area aporta el callable via
        # ``AreaSpec.contributes_tia_commands``; el supervisor lo invoca
        # pasandole el ``tia_client`` para que registre sus handlers
        # con ``tia_client.register_command(...)``. Sin este wiring los
        # comandos del area lanzan ``unknown_command:<name>`` al
        # primer dispatch.
        from core.composition.app_area_registry import AreaRegistry
        for spec in AreaRegistry.discover().all():
            if spec.contributes_tia_commands is not None:
                spec.contributes_tia_commands(tia_client)
        engine = Engine(tick_period_s=self.tick_period_s) if not self.no_engine else None
        if engine is not None:
            # Registrar FBs core (generic, sin acoplamiento al area).
            # Deben ir ANTES de los areas para que cualquier consumer
            # que los busque por nombre los encuentre ya en el engine.
            from core.composition.register_core_fbs import (
                register as register_core_fbs,
            )
            register_core_fbs(
                engine,
                tia_client=tia_client,
            )
            # Registrar los FBs del area (template + futuros reales).
            from areas.alimentacion import register as register_alimentacion
            register_alimentacion(
                engine,
                config_manager=self.config_manager,
                tia_client=tia_client,
            )
        # AppCache unico: contenedor del proceso. Los publishers SSE y
        # los routers Flask lo leen via ``current_app.config['APP_CACHE']``
        # / ``wire_all(..., app_cache)``.
        app_cache = get_app_cache()
        # Cablear las areas via ``contributes_caches``. Cada area aporta
        # su propio ``AreaCache`` (e.g. ``AlimentacionAreaCache``) y lo
        # registra en ``app_cache``. Tras este bucle, las areas estan
        # disponibles para los routers y FBs.
        from core.composition.app_area_registry import AreaRegistry
        for spec in AreaRegistry.discover().all():
            if spec.contributes_caches is not None:
                spec.contributes_caches(app_cache)
        event_bus = self.event_bus if self.event_bus is not None else EventBusSync()
        flask_app = create_app(
            tia_client=tia_client,
            engine=engine,
            event_bus=event_bus,
            config_manager=self.config_manager,
            app_cache=app_cache,
        )
        # Cablea los 5 publishers al bus ANTES de arrancar el tia-loop
        # para que ``on_loop_status`` capture el evento "running=true"
        # en cuanto el hilo arranca. Idempotente si los hooks no existen
        # (log warn + skip).
        from core.runtime.progress_buffer import get_progress_tracker
        from core.runtime.sse.sse_publishers import wire_all
        wire_all(
            log_buffer=get_log_buffer(),
            progress_tracker=get_progress_tracker(),
            tia_client=tia_client,
            engine=engine,
            bus=event_bus,
            app_cache=app_cache,
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


__all__ = ["MainServiceSupervisor"]
