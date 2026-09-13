"""Smoke E2E: main loop + engine + FunctionBlock Template (10 pasos).

Arrancca el supervisor (tia-loop + engine + Flask + main-loop) y
verifica que:
  1. El Template FB esta registrado en el engine.
  2. POST /api/v1/plc/fb/Template/start arranca el FB (nStep=10).
  3. El main loop tickea el engine cada 100ms; el FB avanza de nStep
     10 -> 20 -> ... -> 99 (done) en ~10 segundos.
  4. GET /api/v1/plc/fb/Template/status refleja el avance y termina
     con result = {ok: True, steps_completed: 8}.

Uso: python _local_demo/smoke_main_loop_fb.py
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# Puerto separado (19485) para no chocar con smoke_main_lifecycle.py
HOST = "127.0.0.1"
PORT = 19485
BASE = f"http://{HOST}:{PORT}"


def main() -> int:
    print("=" * 60)
    print("SMOKE MAIN-LOOP + FB TEMPLATE")
    print("=" * 60)

    print("\n[1] setup_logging()")
    from core.application.log_paths import setup_logging
    setup_logging()

    print("\n[2] ConfigManager() + MainServiceSupervisor")
    from core.infrastructure.config_manager import ConfigManager
    from launcher.main_supervisor import MainServiceSupervisor
    cm = ConfigManager()
    s = MainServiceSupervisor(host=HOST, port=PORT, tick_period_s=0.1, config_manager=cm)
    s.start()
    if not s.wait_until_alive(timeout_s=5.0):
        print("  - FAIL: supervisor no arranco")
        return 1
    print("  - supervisor vivo")

    def get(path: str) -> dict:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=2) as r:
            return json.loads(r.read())

    def post(path: str, body: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(body or {}).encode()
        req = urllib.request.Request(
            f"{BASE}{path}", data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    print("\n[3] POST /api/v1/plc/fb/Template/start (arranca el FB)")
    code, body = post("/api/v1/plc/fb/Template/start", {})
    print(f"  - start() -> {code}: {body}")
    if code != 200 or not body.get("started"):
        print("  - FAIL: start() no devolvio started=true")
        return 1
    assert body["nStep"] == 10, body

    print("\n[4] Polling /status cada 1.5s (esperamos ~12s a done)")
    last_nstep = -1
    for i in range(15):
        try:
            st = get("/api/v1/plc/fb/Template/status")
        except urllib.error.URLError:
            break
        nStep = st.get("nStep", 0)
        is_terminal = st.get("is_terminal", False)
        if nStep != last_nstep:
            print(f"  t={i*1.5:5.1f}s: nStep={nStep:3d}  terminal={is_terminal}")
            last_nstep = nStep
        if is_terminal:
            print(f"\n[5] Result final:")
            print(f"  result = {st.get('result')}")
            assert st.get("result") == {"ok": True, "steps_completed": 8}, st
            print("  - PASS: Template termino correctamente")
            break
        import time
        time.sleep(1.5)
    else:
        print("  - FAIL: Template no termino en 22s")
        return 1

    print("\n[6] stop()")
    s.stop(timeout=5.0)
    if s.is_alive():
        print("  - FAIL: supervisor no paro limpio")
        return 1
    print("  - supervisor parado limpio")

    print("\n" + "=" * 60)
    print("SMOKE MAIN-LOOP + FB: PASS")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
