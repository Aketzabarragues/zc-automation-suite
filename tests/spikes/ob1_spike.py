"""
OB1 Spike — minimum viable (Fase 4 / paso 4.0.1).

Valida el modelo OB1 antes de tocar codigo de produccion. NO es parte del
runtime de la app; vive en tests/spikes/ para descartarse limpiamente si
el approach no funciona.

Componentes del spike:
- SyncTIAClient: stub que reemplaza el subproceso persistente + IPC.
  API publica: dispatch(command, args) -> dict (sync), register_command().
  Mecanismo interno: cola FIFO para que el hilo Flask pueda enqueuear
  comandos y el hilo OB1 los drene secuencialmente.
- Engine: contador de ciclos trivial. El real vive en core/plc/engine.py.
- OB1 loop: hilo principal, 10 Hz (100 ms). Cada ciclo: drena cola TIA,
  tick engine, publica evento de ciclo en cola SSE.
- Flask: hilo daemon con 3 endpoints (/ping, /cycle_count, /stream).
  Comunicacion Flask <-> OB1 via queue.Queue thread-safe.

Reglas del spike:
- Sin asyncio. Sin uvicorn. Sin asyncio.subprocess.
- Sin subproceso de Python (solo hilos del proceso del spike).
- Sin siemens_tia_scripting (es stub). Sin TIA Portal.
- Endpoints: GET /ping, GET /cycle_count, GET /stream.

Ejecucion:
    python tests/spikes/ob1_spike.py

Validacion manual en otra ventana:
    curl.exe http://127.0.0.1:5000/ping
    curl.exe http://127.0.0.1:5000/cycle_count
    curl.exe -N http://127.0.0.1:5000/stream

Salida esperada:
- /ping: {"pong": true} en <100 ms (latencia directa, sin OB1).
- /cycle_count: counter incrementandose (1, 2, 3, ...).
- /stream: eventos SSE data: {"type": "cycle", "n": N} cada ~100 ms.

Ctrl+C detiene el spike. El hilo Flask (daemon) muere automaticamente
cuando sale el hilo principal.
"""
from __future__ import annotations

import json
import queue
import threading
import time
from typing import Callable

from flask import Flask, Response, jsonify


# ---------------------------------------------------------------------------
# SyncTIAClient: stub del futuro tia_client.py (paso 4.1.x).
# API sync, sin asyncio, sin subproceso. Vive en el mismo proceso que Flask.
# ---------------------------------------------------------------------------
class SyncTIAClient:
    """Stub de TIA client para validar el modelo OB1."""

    def __init__(self) -> None:
        self._commands: dict[str, Callable[[dict], dict]] = {}
        self._pending: queue.Queue[tuple[str, dict]] = queue.Queue()

    def register_command(self, name: str, handler: Callable[[dict], dict]) -> None:
        """Registra un handler sync. Handler signature: (args) -> result_dict."""
        self._commands[name] = handler

    def dispatch(self, command: str, args: dict | None = None) -> dict:
        """Dispatcher sincrono (llamado desde el hilo OB1). Retorna dict."""
        handler = self._commands.get(command)
        if handler is None:
            return {"ok": False, "error": f"unknown_command:{command}"}
        try:
            return {"ok": True, "result": handler(args or {})}
        except Exception as exc:  # noqa: BLE001 - spike, capturar todo
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def submit(self, command: str, args: dict | None = None) -> None:
        """Encola comando para que OB1 lo procese (thread-safe, no bloquea)."""
        self._pending.put((command, args or {}))

    def dispatch_pending(self) -> int:
        """Drena la cola FIFO y ejecuta cada comando. Retorna # procesados.
        Llamado desde el hilo OB1, una vez por ciclo.
        """
        processed = 0
        while True:
            try:
                command, args = self._pending.get_nowait()
            except queue.Empty:
                return processed
            self.dispatch(command, args)
            processed += 1


# ---------------------------------------------------------------------------
# Engine: contador trivial. El real esta en core/plc/engine.py (4.2.1).
# ---------------------------------------------------------------------------
class Engine:
    """Stub cyclic engine. Solo mantiene cycle_count."""

    def __init__(self) -> None:
        self.cycle_count: int = 0

    def run_cycle(self) -> None:
        """Un tick del ciclo OB1. El real procesa FBs, aqui solo cuenta."""
        self.cycle_count += 1


# ---------------------------------------------------------------------------
# Singletons del spike (suficiente para validar el modelo).
# ---------------------------------------------------------------------------
tia_client = SyncTIAClient()
engine = Engine()
event_queue: queue.Queue[dict] = queue.Queue(maxsize=1000)
shutdown_event = threading.Event()

# Registrar comandos de ejemplo para que `dispatch()` tenga algo que hacer.
# En 4.1.2 el real los importa del registry existente.
tia_client.register_command(
    "ping_tia",
    lambda args: {"pong": True, "echoed": args},
)
tia_client.register_command(
    "increment_counter",
    lambda args: {"cycles": engine.cycle_count, "by": args.get("by", 1)},
)


# ---------------------------------------------------------------------------
# Flask app: 3 endpoints, vive en hilo daemon.
# ---------------------------------------------------------------------------
def _create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/ping")
    def ping():
        """Latencia directa, sin tocar OB1."""
        return jsonify({"pong": True})

    @app.get("/cycle_count")
    def cycle_count():
        """Lee counter del hilo OB1.
        CPython int reads son GIL-atomic -> es seguro cross-thread.
        """
        return jsonify({"cycles": engine.cycle_count})

    @app.get("/stream")
    def stream():
        """SSE: emite eventos de ciclo desde la cola del hilo OB1.
        Keepalive cada 1s para que werkzeug no cierre por inactividad.
        """
        def gen():
            while not shutdown_event.is_set():
                try:
                    event = event_queue.get(timeout=1.0)
                except queue.Empty:
                    # SSE comment (línea ':...') = ping que no genera evento
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(event)}\n\n"
        return Response(gen(), mimetype="text/event-stream")

    return app


# ---------------------------------------------------------------------------
# OB1 main loop: vive en el hilo principal, 10 Hz.
# ---------------------------------------------------------------------------
def start_loop_forever() -> None:
    """Arranca Flask daemon y entra al loop OB1. Ctrl+C detiene."""
    flask_thread = threading.Thread(
        target=lambda: _create_app().run(
            host="127.0.0.1",
            port=5000,
            debug=False,
            use_reloader=False,
            threaded=True,
        ),
        name="flask-daemon",
        daemon=True,
    )
    flask_thread.start()

    print("[ob1-spike] Flask daemon: http://127.0.0.1:5000")
    print("[ob1-spike] Endpoints: GET /ping, GET /cycle_count, GET /stream")
    print("[ob1-spike] OB1 main loop @ 10 Hz. Ctrl+C to stop.")
    print("[ob1-spike] Stack: 1 hilo OB1 (main) + 1 hilo Flask (daemon).")

    interval_s = 0.1
    try:
        while not shutdown_event.is_set():
            tia_client.dispatch_pending()
            engine.run_cycle()
            try:
                event_queue.put_nowait(
                    {"type": "cycle", "n": engine.cycle_count},
                )
            except queue.Full:
                # Si el consumidor SSE va lento, descartamos eventos
                # (el counter sigue incrementandose, no es bloqueante).
                pass
            time.sleep(interval_s)
    except KeyboardInterrupt:
        print("\n[ob1-spike] Ctrl+C received. Shutting down.")
        shutdown_event.set()
        # Daemon Flask thread muere solo cuando sale el main thread.


if __name__ == "__main__":
    start_loop_forever()
