"""Smoke test manual del tray launcher (solo web).

NO es pytest. Se ejecuta a mano con:

    python scripts/smoke_main_tray.py

Levanta el supervisor del web en un puerto alto para no chocar con
nada, hace health-check HTTP, prueba el auto-restart forzando
should_exit, y limpia al final.

Imprime 'SMOKE OK' si todo fue bien, 'SMOKE FAIL: <motivo>' si falló.
Exit code 0 en exito, 1 en fallo.

Variables de entorno opcionales:
  SMOKE_WEB_PORT  (default 18999)
"""
from __future__ import annotations

import logging
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("smoke_tray")


def _http_get(url: str, timeout: float = 2.0) -> tuple[bool, str]:
    """Hace un GET y devuelve (ok, mensaje). ok=True si respondio algo."""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return True, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def main() -> int:
    web_port = int(os.environ.get("SMOKE_WEB_PORT", "18999"))

    log.info("=" * 60)
    log.info("SMOKE TEST: tray launcher (solo web, dev mode)")
    log.info("  web port: %d", web_port)
    log.info("=" * 60)

    from launcher.web_supervisor import WebServiceSupervisor

    web = WebServiceSupervisor(host="127.0.0.1", port=web_port)

    failures: list[str] = []

    try:
        # ── 1. Start web ──────────────────────────────────────
        log.info("[1/4] Iniciando web supervisor...")
        web.start()
        deadline = time.time() + 15.0
        while time.time() < deadline and not web.is_alive():
            time.sleep(0.2)
        if not web.is_alive():
            failures.append("web no arranco")
        else:
            log.info("    -> web alive=True, restart_count=%d", web.restart_count)

        # ── 2. Health-check web ───────────────────────────────
        log.info("[2/4] Health-check web...")
        if web.is_alive():
            ok, msg = _http_get(f"http://127.0.0.1:{web_port}/")
            log.info("    -> %s (%s)", "OK" if ok else "FAIL", msg)
            if not ok:
                failures.append(f"web no responde: {msg}")
        else:
            failures.append("web no arrancado, salto health-check")

        # ── 3. Test auto-restart de web ───────────────────────
        log.info("[3/4] Test auto-restart de web...")
        if web._server is not None:
            initial_count = web.restart_count
            web._server.should_exit = True
            log.info("    -> Forzando should_exit (simula crash)...")
            deadline = time.time() + 8.0
            while time.time() < deadline and web.restart_count == initial_count:
                time.sleep(0.3)
            if web.restart_count > initial_count:
                log.info(
                    "    -> web se reinicio: %d -> %d",
                    initial_count,
                    web.restart_count,
                )
            else:
                failures.append("web no se reinicio tras should_exit")
        else:
            failures.append("web._server es None, no puedo forzar restart")

        # ── 4. Health-check tras restart ──────────────────────
        log.info("[4/4] Health-check tras restart...")
        deadline = time.time() + 10.0
        while time.time() < deadline and not web.is_alive():
            time.sleep(0.3)
        if web.is_alive():
            ok, msg = _http_get(f"http://127.0.0.1:{web_port}/")
            log.info("    -> %s (%s)", "OK" if ok else "FAIL", msg)
            if not ok:
                failures.append(f"web no responde tras restart: {msg}")
        else:
            failures.append("web no volvio a estar vivo tras restart")

    finally:
        log.info("Cleanup: parando web supervisor...")
        try:
            web.stop(timeout=5.0)
        except Exception as exc:  # noqa: BLE001
            log.warning("Error parando web: %s", exc)

    print()
    print("=" * 60)
    if failures:
        print("SMOKE FAIL:")
        for f in failures:
            print(f"  - {f}")
        print("=" * 60)
        return 1
    print("SMOKE OK")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
