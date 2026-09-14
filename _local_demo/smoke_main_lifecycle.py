"""Smoke E2E del ciclo de vida del main (sin TIA, sin FBs, sin web de areas).

Verifica el flujo base del supervisor OB1:
  1. setup_logging() arranca el log unificado.
  2. ConfigManager() carga config/config.json sin error.
  3. MainServiceSupervisor levanta Flask + main loop en hilos daemon.
  4. Flask responde /ping, /cycle_count incrementa con el tiempo,
     /stream emite keepalive SSE.
  5. stop() cierra los hilos limpio.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# Puerto separado (19484) para no chocar con la app en 9484.
HOST = "127.0.0.1"
PORT = 19484
BASE = f"http://{HOST}:{PORT}"


def main() -> int:
    print("=" * 60)
    print("SMOKE MAIN (base OB1: sin TIA, sin FBs, sin web de areas)")
    print("=" * 60)

    print("\n[1] setup_logging()")
    from core.infrastructure.config.config_paths import setup_logging
    log_file = setup_logging()
    print(f"  - log unificado: {log_file}")

    print("\n[2] ConfigManager() eager")
    from core.infrastructure.config.config_manager import ConfigManager
    cm = ConfigManager()
    print(f"  - config path: {cm.path}")
    print(f"  - department: {cm.department}")

    print("\n[3] MainServiceSupervisor.start()")
    from core.launcher.main_supervisor import MainServiceSupervisor
    s = MainServiceSupervisor(
        host=HOST, port=PORT, tick_period_s=0.05, config_manager=cm,
    )
    s.start()
    if not s.wait_until_alive(timeout_s=5.0):
        print("  - FAIL: supervisor no arranco en 5s")
        return 1
    print(f"  - supervisor vivo: Flask + main-loop activos")

    print("\n[4] GET /ping")
    body = urllib.request.urlopen(f"{BASE}/ping", timeout=2).read().decode().strip()
    print(f"  - {body}")
    assert body == '{"pong":true}'

    print("\n[5] GET /cycle_count (verifica main loop tickea)")
    c0 = json.loads(urllib.request.urlopen(f"{BASE}/cycle_count", timeout=2).read())["cycles"]
    print(f"  - t0:   cycles={c0}")
    import time
    time.sleep(1.0)
    c1 = json.loads(urllib.request.urlopen(f"{BASE}/cycle_count", timeout=2).read())["cycles"]
    print(f"  - t+1s: cycles={c1}  (delta={c1 - c0})")
    assert c1 > c0, f"main loop no tickea: {c0} -> {c1}"

    print("\n[6] GET /stream (espera keepalive SSE)")
    req = urllib.request.urlopen(f"{BASE}/stream", timeout=3)
    chunk = req.read(64)
    req.close()
    print(f"  - primer chunk: {chunk!r}")
    assert b": keepalive" in chunk or b"data:" in chunk

    print('\n[7] MainServiceSupervisor.stop()')
    s.stop(timeout=3.0)
    if s.is_alive():
        print("  - FAIL: supervisor no paro limpio")
        return 1
    print(f"  - supervisor parado limpio")

    print("\n[8] Flask muerto?")
    try:
        urllib.request.urlopen(f"{BASE}/ping", timeout=1)
        print("  - FAIL: Flask sigue respondiendo")
        return 1
    except urllib.error.URLError:
        print(f"  - OK: Flask cerrado")

    print("\n" + "=" * 60)
    print("SMOKE MAIN: PASS")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
