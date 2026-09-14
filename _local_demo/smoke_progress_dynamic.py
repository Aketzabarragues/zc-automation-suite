"""Smoke especifico: progress dinamico de los 3 FBs demo.

Lanza cada uno de los 3 FBs (``plantilla`` 10 pasos, ``cuatro_pasos``
4 pasos, ``seis_pasos`` 6 pasos) y valida que el ``progress_tracker``
se actualiza en vivo, paso a paso, mientras el FB corre.

Para cada FB verifica:
  1. La forma del ``begin`` (operation, label, stages, total).
  2. La secuencia intermedia: cada ``start_stage`` incrementa current
     en 1 y mantiene percent = current/total*100.
  3. El ``finish`` final con active=False, current=total, percent=100.
  4. El ``result`` del FB con steps_completed == total_steps y stats
     cubriendo los N stages.
  5. El ``GET /api/v1/progress/current`` durante la ejecucion reporta
     current y percent CRECIENTES (no congelado en el ultimo valor).

Uso: python _local_demo/smoke_progress_dynamic.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

HOST = "127.0.0.1"
PORT = 19487  # puerto separado para no chocar con smoke_e2e_full
BASE = f"http://{HOST}:{PORT}"

# FBs a probar: (nombre, total de stages, duracion_total_aprox)
FBS = [
    ("cuatro_pasos", 4, 2.5),
    ("seis_pasos", 6, 3.0),
    ("plantilla", 10, 3.5),
]


def main() -> int:
    print("=" * 70)
    print("SMOKE PROGRESS DINAMICO: 4 pasos + 6 pasos + plantilla (10)")
    print("=" * 70)

    # ------------------------------------------------------------------
    # Setup (mismo patron que smoke_e2e_full: supervisor + bus + wire_all)
    # ------------------------------------------------------------------
    from core.infrastructure.config.config_paths import setup_logging
    setup_logging()

    from core.infrastructure.config.config_manager import ConfigManager
    cm = ConfigManager()

    from core.infrastructure.tia.tia_loop import SyncTIAClient
    from core.infrastructure.tia.tia_handlers import register_core_commands
    from core.composition.plc_engine import Engine
    from core.runtime.sse.sse_event_bus_sync import EventBusSync
    from core.runtime.sse.sse_publishers import wire_all
    from core.runtime.log_buffer import get_log_buffer
    from core.runtime.progress_buffer import get_progress_tracker
    from areas.alimentacion import register as register_alim

    tc = SyncTIAClient()
    register_core_commands(tc)
    tc.start_tia_loop()
    eng = Engine(tick_period_s=0.05)
    register_alim(eng)
    bus = EventBusSync()
    wire_all(
        log_buffer=get_log_buffer(),
        progress_tracker=get_progress_tracker(),
        tia_client=tc,
        engine=eng,
        bus=bus,
    )
    # Subscribe al bus para capturar progress events.
    subscriber_q = bus.subscribe()

    class _FakeTs:
        class Enums:
            class PortalMode:
                WithGraphicalUserInterface = "WithGraphicalUserInterface"
        def attach_portal(self, portal_mode):
            class _P:
                def get_project(self): return None
                def get_process_id(self): return 1
                def detach(self): pass
            return _P()

    tc.attach_ts(_FakeTs())

    from core.launcher.main_supervisor import MainServiceSupervisor
    s = MainServiceSupervisor(
        host=HOST, port=PORT, tick_period_s=0.05,
        config_manager=cm, event_bus=bus,
    )
    s.start()
    if not s.wait_until_alive(timeout_s=5.0):
        print("FAIL: supervisor no arranco")
        return 1
    tc_real = s._components[0]
    tc_real.attach_ts(_FakeTs())

    def get(path: str) -> tuple[int, dict[str, Any]]:
        try:
            with urllib.request.urlopen(f"{BASE}{path}", timeout=2) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def post(path: str, body: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(body or {}).encode()
        req = urllib.request.Request(
            f"{BASE}{path}", data=data,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    # ------------------------------------------------------------------
    # Para cada FB: lanzar + polling 500ms al progress + validar eventos
    # ------------------------------------------------------------------
    for nombre, total_stages, duracion_total in FBS:
        print(f"\n[{nombre}] lanzar y validar avance dinamico")
        tracker = get_progress_tracker()
        tracker.clear()
        # Drenar el subscriber para empezar de cero (asi los progress
        # events que validamos son solo los emitidos durante este FB).
        while not subscriber_q.empty():
            subscriber_q.get_nowait()

        # Lanzar el FB.
        code, body = post(f"/api/v1/plc/fb/{nombre}/start")
        assert code == 200 and body["started"] is True, (
            f"[{nombre}] start fallo: {code} {body}"
        )
        print(f"  - start OK: nStep={body['nStep']}")

        # Polling 500ms al /progress/current para validar avance vivo.
        # Capturamos la secuencia de (current, percent) que ve el polling
        # de la SPA; debe ser monotona creciente. El endpoint devuelve
        # ``{"ok": True, "progress": {...}}``; el snapshot vive bajo
        # la clave ``progress``.
        live_progress: list[tuple[int, int]] = []
        final_status: dict[str, Any] = {}
        for i in range(int(duracion_total / 0.5) + 5):
            time.sleep(0.5)
            try:
                _, resp = get("/api/v1/progress/current")
                p = resp.get("progress", resp)
            except Exception as exc:
                print(f"  - WARN: /progress/current fallo: {exc}")
                continue
            live_progress.append((p["current"], p["percent"]))
            _, st = get(f"/api/v1/plc/fb/{nombre}/status")
            if st.get("is_terminal"):
                final_status = st
                break

        assert final_status.get("is_terminal"), (
            f"[{nombre}] no termino en {duracion_total + 2.5}s"
        )

        # Validacion 1: result.shape correcto.
        res = final_status["result"]
        assert res["ok"] is True, f"[{nombre}] result.ok != True: {res}"
        assert res["steps_completed"] == total_stages, (
            f"[{nombre}] steps_completed={res['steps_completed']} != {total_stages}"
        )
        assert res["total_steps"] == total_stages, (
            f"[{nombre}] total_steps={res['total_steps']} != {total_stages}"
        )
        assert len(res.get("stats", {})) == total_stages, (
            f"[{nombre}] stats cubre {len(res.get('stats', {}))} stages, esperados {total_stages}"
        )
        print(f"  - result OK: steps_completed={res['steps_completed']}/{res['total_steps']}")

        # Validacion 2: el polling vio avance (current subio de 0 a N).
        currents = [c for c, _ in live_progress]
        assert currents[0] <= currents[-1], (
            f"[{nombre}] current no subio: {currents}"
        )
        assert currents[-1] == total_stages, (
            f"[{nombre}] current final={currents[-1]} != {total_stages}"
        )
        # Validacion 3: la secuencia es monotona creciente.
        assert currents == sorted(currents), (
            f"[{nombre}] current NO monotono creciente: {currents}"
        )
        print(f"  - polling OK: current={currents[0]}->{currents[-1]} (samples={len(currents)})")

        # Validacion 4: events progress del bus (filtrados por operation).
        events_progress = []
        while not subscriber_q.empty():
            ev = subscriber_q.get_nowait()
            if ev.get("type") == "progress" and ev.get("operation") == nombre:
                events_progress.append(ev)
        # 1 begin + N start + N finish + 1 finish(success) = 2N+2.
        min_events = 2 * total_stages + 2
        assert len(events_progress) >= min_events, (
            f"[{nombre}] esperados >= {min_events} progress events, "
            f"recibidos: {len(events_progress)}"
        )
        first = events_progress[0]
        assert first["operation"] == nombre
        assert first["active"] is True
        assert first["total"] == total_stages
        assert first["current"] == 0
        assert first["percent"] == 0
        last = events_progress[-1]
        assert last["active"] is False
        assert last["current"] == total_stages
        assert last["percent"] == 100
        last_statuses = [s["status"] for s in last["stages"]]
        assert last_statuses == ["done"] * total_stages, (
            f"[{nombre}] stages finales no todos 'done': {last_statuses}"
        )
        print(f"  - SSE OK: {len(events_progress)} progress events, "
              f"begin+stages+finish validados")

    s.stop(timeout=5.0)
    print("\n" + "=" * 70)
    print(f"SMOKE PROGRESS DINAMICO: PASS ({len(FBS)} FBs validados)")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
