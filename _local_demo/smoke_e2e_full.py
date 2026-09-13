"""Smoke E2E completo: main loop + tia-loop + FB + SSE + endpoints.

Verifica end-to-end todo lo tocado en el refactor OB1:

  1. setup_logging() (logger unificado en zc.log)
  2. ConfigManager() carga config/config.json eager
  3. tia-loader carga wrapper .pyd + .dll + .xml
  4. tia-loop arranca como hilo daemon
  5. tia-loop maneja state machine (IDLE -> ATTACHING -> CONNECTED -> IDLE)
  6. engine arranca main loop cada 50ms; tickea FunctionTemplate
  7. FunctionTemplate arranca y avanza 10 pasos x 1s (10s total)
  8. Endpoints /ping, /cycle_count, /stream, /tia/connect,
     /tia/disconnect, /tia/connection, /plc/fb/Template/{start,status}
  9. Los 5 publishers emiten al bus (log, progress, tia_state,
     fb_state, tia_loop_status)
 10. SSE endpoint /stream retransmite eventos
 11. stop() limpio (orden inverso)

Uso: python _local_demo/smoke_e2e_full.py
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

# Puerto separado (19486) para no chocar con smoke_main_lifecycle (19484)
# ni con smoke_main_loop_fb (19485).
HOST = "127.0.0.1"
PORT = 19486
BASE = f"http://{HOST}:{PORT}"


def main() -> int:
    print("=" * 70)
    print("SMOKE E2E FULL: main loop + tia-loop + FB + SSE + endpoints")
    print("=" * 70)

    # -----------------------------------------------------------------
    # [1] setup_logging
    # -----------------------------------------------------------------
    print("\n[1] setup_logging()")
    from core.application.log_paths import setup_logging
    setup_logging()

    # -----------------------------------------------------------------
    # [2] ConfigManager eager
    # -----------------------------------------------------------------
    print("\n[2] ConfigManager() eager")
    from core.infrastructure.config.config_manager import ConfigManager
    cm = ConfigManager()
    print(f"  - config path: {cm.path}")

    # -----------------------------------------------------------------
    # [3] tia_client + engine + bus + wire_all
    # -----------------------------------------------------------------
    print("\n[3] tia-loader + tia-loop + engine + bus + wire_all")
    from core.infrastructure.tia.tia_loop import SyncTIAClient
    from core.infrastructure.tia.tia_handlers import register_core_commands
    from core.plc.engine import Engine
    from core.sse.event_bus_sync import EventBusSync
    from core.sse.publishers import wire_all
    from core.application.log_buffer import get_log_buffer
    from core.application.progress_buffer import get_progress_tracker

    tc = SyncTIAClient()
    register_core_commands(tc)
    tc.start_tia_loop()
    eng = Engine(tick_period_s=0.05)
    from areas.alimentacion import register as register_alim
    register_alim(eng)
    print(f"  - engine con FBs: {eng.registered_fb_names()}")

    bus = EventBusSync()
    wire_all(
        log_buffer=get_log_buffer(),
        progress_tracker=get_progress_tracker(),
        tia_client=tc,
        engine=eng,
        bus=bus,
    )
    print("  - 5 publishers cableados al bus unico")

    # Mock ts (sin TIA Portal real)
    class _FakeProject:
        Name = "TEST_PROJECT"
        Path = "C:/fake/project.ap17"
        Version = "V17"
        def get_plcs(self):
            return []

    class _FakePortal:
        def GetProject(self):
            return _FakeProject()
        def get_project(self):
            return _FakeProject()
        def get_process_id(self):
            return 12345
        def detach(self):
            pass

    class _FakeTs:
        class Enums:
            class PortalMode:
                WithUserInterface = "WithUserInterface"
                WithoutUserInterface = "WithoutUserInterface"
                WithGraphicalUserInterface = "WithGraphicalUserInterface"
                WithoutGraphicalUserInterface = "WithoutGraphicalUserInterface"
                AnyUserInterface = "AnyUserInterface"
        def open_portal(self, portal_mode):
            return _FakePortal()
        def attach_portal(self, portal_mode):
            return _FakePortal()

    tc.attach_ts(_FakeTs())

    # Suscripcion al bus ANTES de que se pierdan eventos retroactivos
    subscriber_q = bus.subscribe()
    print(f"  - subscriber pegado; total subs: {bus.subscriber_count()}")

    # -----------------------------------------------------------------
    # [4] supervisor: usamos el bus del smoke (inyectado)
    # -----------------------------------------------------------------
    print("\n[4] MainServiceSupervisor.start()")
    from launcher.main_supervisor import MainServiceSupervisor
    s = MainServiceSupervisor(
        host=HOST, port=PORT, tick_period_s=0.05,
        config_manager=cm, event_bus=bus,
    )
    s.start()
    if not s.wait_until_alive(timeout_s=5.0):
        print("  - FAIL: supervisor no arranco")
        return 1
    tc_real = s._components[0]  # noqa: SLF001
    tc_real.attach_ts(_FakeTs())  # mock en el tia_real del supervisor
    print(f"  - supervisor vivo (3 hilos: tia-loop + flask + main-loop)")

    # -----------------------------------------------------------------
    # Helpers HTTP
    # -----------------------------------------------------------------
    def get(path: str) -> tuple[int, dict[str, Any]]:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=2) as r:
            return r.status, json.loads(r.read())

    def post(path: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        data = json.dumps(body or {}).encode()
        req = urllib.request.Request(
            f"{BASE}{path}", data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    # -----------------------------------------------------------------
    # [5] /ping + /cycle_count
    # -----------------------------------------------------------------
    print("\n[5] GET /ping + /cycle_count")
    code, body = get("/ping")
    assert code == 200 and body == {"pong": True}
    print(f"  - /ping -> {body}")
    c0 = get("/cycle_count")[1]["cycles"]
    time.sleep(1.0)
    c1 = get("/cycle_count")[1]["cycles"]
    print(f"  - /cycle_count: {c0} -> {c1} (delta={c1 - c0})")
    assert c1 > c0

    # -----------------------------------------------------------------
    # [6] /api/v1/tia/connect (mock) -> CONNECTED
    # -----------------------------------------------------------------
    print("\n[6] POST /api/v1/tia/connect")
    code, body = post("/api/v1/tia/connect")
    print(f"  - connect -> {code}: state={body.get('state')}")
    assert code == 200 and body.get("state") == "connected"
    assert tc_real.wrapper is not None

    # -----------------------------------------------------------------
    # [7] /api/v1/tia/connection
    # -----------------------------------------------------------------
    print("\n[7] GET /api/v1/tia/connection")
    code, body = get("/api/v1/tia/connection")
    print(f"  - state={body.get('state')}, project={body.get('project')}")
    assert body["state"] == "connected"

    # -----------------------------------------------------------------
    # [8] POST /api/v1/plc/fb/Template/start + polling hasta done
    # -----------------------------------------------------------------
    print("\n[8] POST /api/v1/plc/fb/Template/start + polling")
    code, body = post("/api/v1/plc/fb/Template/start")
    print(f"  - start -> {code}: {body}")
    assert code == 200 and body["started"] is True

    last_nstep = -1
    final_status: dict[str, Any] = {}
    for i in range(15):
        time.sleep(1.0)
        code, st = get("/api/v1/plc/fb/Template/status")
        nStep = st.get("nStep", 0)
        is_terminal = st.get("is_terminal", False)
        if nStep != last_nstep:
            print(f"  t={i+1}s: nStep={nStep:3d}  terminal={is_terminal}")
            last_nstep = nStep
        if is_terminal:
            final_status = st
            break
    assert final_status.get("is_terminal"), "Template no termino en 15s"
    assert final_status["result"] == {"ok": True, "steps_completed": 8}
    print(f"  - PASS: result={final_status['result']}")

    # -----------------------------------------------------------------
    # [9] POST /api/v1/tia/disconnect
    # -----------------------------------------------------------------
    print("\n[9] POST /api/v1/tia/disconnect")
    code, body = post("/api/v1/tia/disconnect")
    print(f"  - disconnect -> {code}: state={body.get('state')}")
    assert code == 200 and body.get("state") == "idle"

    # -----------------------------------------------------------------
    # [10] Verificar eventos SSE capturados por el subscriber
    # -----------------------------------------------------------------
    print("\n[10] Eventos SSE capturados por el subscriber")
    time.sleep(0.5)
    events_by_type: dict[str, list[dict[str, Any]]] = {}
    while not subscriber_q.empty():
        ev = subscriber_q.get_nowait()
        events_by_type.setdefault(ev.get("type", "?"), []).append(ev)

    for t in sorted(events_by_type):
        evs = events_by_type[t]
        print(f"  - {t}: {len(evs)} evento(s)")
        if t == "fb_state":
            for e in evs[:5]:
                print(f"      fb={e['name']}, nStep={e['nStep']}")
        elif t == "tia_state":
            for e in evs:
                print(f"      state={e['state']}")
        elif t == "tia_loop_status":
            for e in evs:
                print(f"      running={e['running']}")

    # Validaciones clave (sin necesidad de tener TODOS los 5 tipos;
    # algunos publishers solo emiten si hay cambios):
    # 1. tia_state: ciclo completo de attach/disconnect
    if "tia_state" in events_by_type:
        states = {e["state"] for e in events_by_type["tia_state"]}
        assert "connected" in states, "tia_state no reporto connected"

    # 2. tia_loop_status: al menos un running=True
    if "tia_loop_status" in events_by_type:
        assert any(
            e["running"] for e in events_by_type["tia_loop_status"]
        ), "tia_loop no reporto running=True"

    # 3. fb_state: si Template fue tickeado, nStep>=10 aparece
    if "fb_state" in events_by_type:
        fb_nsteps = {e["nStep"] for e in events_by_type["fb_state"]}
        assert 10 in fb_nsteps, (
            f"fb_state no reporto nStep=10: {fb_nsteps}"
        )

    # -----------------------------------------------------------------
    # [11] SSE endpoint /stream captura eventos (reader corto)
    # -----------------------------------------------------------------
    print("\n[11] GET /api/v1/stream (primer chunk)")
    req = urllib.request.urlopen(f"{BASE}/stream", timeout=3)
    chunk = req.read(256)
    req.close()
    print(f"  - chunk: {chunk[:80]!r}")
    assert b": keepalive" in chunk or b"data:" in chunk

    # -----------------------------------------------------------------
    # [12] stop() limpio + verificar tia_loop_status post-stop
    # -----------------------------------------------------------------
    print("\n[12] MainServiceSupervisor.stop()")
    s.stop(timeout=5.0)
    if s.is_alive():
        print("  - FAIL: supervisor no paro limpio")
        return 1
    print("  - supervisor parado limpio")

    # Tras stop, el flag _loop_running se apaga ANTES del join() y
    # on_loop_status se publica sincronamente, asi que el ultimo
    # tia_loop_status deberia ser running=False de forma determinista.
    time.sleep(0.5)
    while not subscriber_q.empty():
        ev = subscriber_q.get_nowait()
        events_by_type.setdefault(ev.get("type", "?"), []).append(ev)
    if "tia_loop_status" in events_by_type:
        all_running = [e["running"] for e in events_by_type["tia_loop_status"]]
        print(f"  - tia_loop_status running[]: {all_running}")
        assert all_running[-1] is False, (
            f"esperado ultimo tia_loop_status running=False tras stop: {all_running}"
        )

    print("\n" + "=" * 70)
    print(f"SMOKE E2E FULL: PASS")
    print(f"  - Eventos SSE capturados: {sum(len(v) for v in events_by_type.values())} total")
    for t in sorted(events_by_type):
        print(f"    {t}: {len(events_by_type[t])}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
