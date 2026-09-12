"""Tests del wiring main.py ↔ Ob1ServiceSupervisor (Fase 4 / 4.N4).

Patches:
  - ``launcher.tray_app.run_tray`` → capturamos el supervisor y los
    callbacks (on_before_exit) para invocarlos manualmente y simular
    clicks del operario sin arrancar pystray (requiere GUI).

Cubre:
  1. main() crea un Ob1ServiceSupervisor.
  2. El supervisor usa host/port fijos (127.0.0.1:9484).
  3. Click "Iniciar web" → supervisor arranca → Flask + OB1 responden.
  4. Click "Parar web" → supervisor para → Flask dead.
  5. Click "Salir" → on_before_exit() para el supervisor.
"""
from __future__ import annotations

import importlib
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def fresh_main(monkeypatch, tmp_path):
    """Recarga ``main`` con log dir tmp y tray mockeado.

    No invoca main(); expone el supervisor capturado por run_tray.
    """
    monkeypatch.setenv("ZC_LOG_DIR", str(tmp_path))

    captured: dict = {}

    def fake_run_tray(web, icon_path, log, on_before_exit=None):
        captured["web"] = web
        captured["on_before_exit"] = on_before_exit
        captured["done_event"] = threading.Event()
        captured["done_event"].wait(timeout=10.0)

    monkeypatch.setattr("launcher.tray_app.run_tray", fake_run_tray)

    if "main" in sys.modules:
        del sys.modules["main"]
    mod = importlib.import_module("main")

    main_thread = threading.Thread(target=mod.main, name="main_test", daemon=True)
    main_thread.start()

    deadline = time.time() + 5.0
    while "web" not in captured and time.time() < deadline:
        time.sleep(0.05)

    assert "web" in captured, "main no llego a run_tray; posiblemente crasheo antes."
    yield captured

    if "done_event" in captured:
        captured["done_event"].set()
    main_thread.join(timeout=5.0)

    web = captured.get("web")
    if web is not None and web.is_alive():
        try:
            web.stop(timeout=2.0)
        except Exception:
            pass


def _http_get(url: str, timeout: float = 2.0) -> tuple[int, str]:
    """GET helper: retorna (status, body)."""
    resp = urllib.request.urlopen(url, timeout=timeout)
    return resp.status, resp.read().decode("utf-8")


@pytest.mark.slow
def test_main_creates_ob1_supervisor(fresh_main):
    """main() crea un Ob1ServiceSupervisor (no WebServiceSupervisor)."""
    from launcher.ob1_supervisor import Ob1ServiceSupervisor

    web = fresh_main["web"]
    assert isinstance(web, Ob1ServiceSupervisor)


@pytest.mark.slow
def test_main_uses_fixed_host_port(fresh_main):
    """El supervisor usa host/port fijos (127.0.0.1:9484)."""
    web = fresh_main["web"]
    assert web.host == "127.0.0.1"
    assert web.port == 9484


@pytest.mark.slow
def test_iniciar_web_starts_flask_and_ob1(fresh_main):
    """Click "Iniciar web" → Flask responde, OB1 loop tickea."""
    web = fresh_main["web"]
    assert not web.is_alive()

    web.start()
    assert web.wait_until_alive(timeout_s=5.0)

    status, body = _http_get(f"http://127.0.0.1:{web.port}/ping")
    assert status == 200
    assert body.strip() == '{"pong":true}'

    # OB1 loop tickea: cycle_count incrementa.
    time.sleep(0.3)
    status, body = _http_get(f"http://127.0.0.1:{web.port}/cycle_count")
    assert status == 200
    assert json.loads(body)["cycles"] >= 1


@pytest.mark.slow
def test_parar_web_stops_flask_and_ob1(fresh_main):
    """Click "Parar web" → Flask dead, OB1 loop parado."""
    web = fresh_main["web"]
    web.start()
    assert web.wait_until_alive(timeout_s=5.0)

    web.stop(timeout=5.0)
    assert not web.is_alive()

    with pytest.raises(urllib.error.URLError):
        urllib.request.urlopen(f"http://127.0.0.1:{web.port}/ping", timeout=1.0)


@pytest.mark.slow
def test_salir_tray_para_supervisor_via_on_before_exit(fresh_main):
    """Click "Salir" → on_before_exit() llama web.stop()."""
    web = fresh_main["web"]
    web.start()
    assert web.wait_until_alive(timeout_s=5.0)

    fresh_main["on_before_exit"]()
    deadline = time.time() + 5.0
    while web.is_alive() and time.time() < deadline:
        time.sleep(0.1)
    assert not web.is_alive()
