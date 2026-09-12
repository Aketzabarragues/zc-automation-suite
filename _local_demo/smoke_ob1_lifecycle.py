"""Smoke test final del ciclo de vida OB1 (Fase 4 / DA-014).

Equivalente al flujo del operario con la bandeja:
  1. main.py arranca (modo bandeja)
  2. Operario hace click en "Iniciar web"
  3. Ob1Supervisor arranca Flask + OB1 main loop en hilos
  4. Flask responde /ping y /cycle_count refleja el OB1 loop
  5. Operario hace click en "Parar web"
  6. Ambos hilos paran limpiamente
"""
from __future__ import annotations

import json
import logging
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s [%(name)s] %(message)s")

    print("=" * 60)
    print("FASE 4 / OB1: SMOKE TEST CICLO DE VIDA")
    print("=" * 60)

    print("\n[1] Creando Ob1ServiceSupervisor (equivalente a main.py tray mode)")
    from launcher.ob1_supervisor import Ob1ServiceSupervisor
    s = Ob1ServiceSupervisor(host="127.0.0.1", port=5997, tick_period_s=0.05)
    print(f"  - supervisor creado en {s.host}:{s.port}")

    print('\n[2] Simulando click en "Iniciar web" -> supervisor.start()')
    s.start()
    print("  - esperando Flask + OB1 alive...")
    s.wait_until_alive(timeout_s=5.0)
    print(f"  - vivo: {s.is_alive()}")

    print("\n[3] Verificando /ping (HTTP Flask daemon)")
    resp = urllib.request.urlopen("http://127.0.0.1:5997/ping", timeout=2)
    body = resp.read().decode().strip()
    print(f"  - GET /ping -> {resp.status} {body}")
    assert resp.status == 200
    assert body == '{"pong":true}'

    print("\n[4] Verificando /cycle_count refleja el OB1 loop")
    time.sleep(0.3)
    resp = urllib.request.urlopen("http://127.0.0.1:5997/cycle_count", timeout=2)
    data1 = json.loads(resp.read())
    print(f"  - lectura 1: cycles={data1['cycles']}")
    time.sleep(0.2)
    resp = urllib.request.urlopen("http://127.0.0.1:5997/cycle_count", timeout=2)
    data2 = json.loads(resp.read())
    delta = data2["cycles"] - data1["cycles"]
    print(f"  - lectura 2: cycles={data2['cycles']} (incremento={delta})")
    assert delta > 0, "OB1 loop NO tickeando!"

    print('\n[5] Simulando click en "Parar web" -> supervisor.stop()')
    s.stop(timeout=3.0)
    print(f"  - vivo tras stop: {s.is_alive()}")
    assert not s.is_alive()

    print("\n[6] Verificando que Flask esta muerto")
    try:
        urllib.request.urlopen("http://127.0.0.1:5997/ping", timeout=1)
        print("  - FAIL: Flask sigue respondiendo")
        return 1
    except urllib.error.URLError as exc:
        print(f"  - OK: Flask muerto ({exc.__class__.__name__})")

    print("\n" + "=" * 60)
    print("CICLO DE VIDA OB1: PASS")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
