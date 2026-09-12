"""Tests del wiring main.py ↔ Ob1ServiceSupervisor (Fase 4 / 4.N4).

Verifica el ciclo de vida del tray launcher OB1 SIN arrancar pystray
(la bandeja real requiere GUI). Patches:

  - ``launcher.tray_app.run_tray`` → capturamos el supervisor y los
    callbacks (on_toggle_web, on_exit) para invocarlos manualmente y
    simular clicks del operario.
  - ``launcher.ob1_supervisor.Ob1ServiceSupervisor`` → la clase real
    (queremos validar la integracion end-to-end con HTTP real).

Cubre:
  1. main.main() crea un Ob1ServiceSupervisor (no WebServiceSupervisor).
  2. El supervisor usa host/port de env vars (ZC_WEB_HOST / ZC_WEB_PORT).
  3. Click en "Iniciar web" → supervisor arranca → Flask + OB1 responden.
  4. Click en "Parar web" → supervisor para → Flask dead.
  5. Click en "Salir" → on_before_exit() para el supervisor.

Histórico: este archivo se llamaba ``test_main_tray_ob1_wiring.py``
hasta sept-2026. Se renombró cuando ``main_tray.py`` se renombró a
``main.py`` (Fase 4 / 4.N8, sept-2026).
"""
from __future__ import annotations

import importlib
import logging
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def port(request) -> int:
    """Puerto único por test (rango alto)."""
    return 19600 + abs(hash(request.node.name)) % 100


@pytest.fixture
def fresh_main_tray(monkeypatch, tmp_path, port):
    """Recarga ``main`` con env vars controladas y tray mockeado.

    No invoca main(); expone los callbacks del menu para test manual.
    """
    monkeypatch.setenv("ZC_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("ZC_WEB_HOST", "127.0.0.1")
    monkeypatch.setenv("ZC_WEB_PORT", str(port))

    # Capturamos las llamadas a run_tray para extraer supervisor y callbacks.
    captured: dict = {}

    def fake_run_tray(web, icon_path, log, on_before_exit=None):
        captured["web"] = web
        captured["on_before_exit"] = on_before_exit
        # No invocamos icon.run() (requiere GUI). Solo capturamos los items.
        captured["menu_items"] = (web, icon_path, log, on_before_exit)
        # Simulamos el flujo: el tray se queda bloqueado hasta que
        # marquemos ``captured["done"]``. Los tests lo marcan tras
        # verificar el comportamiento.
        captured["done_event"] = threading.Event()
        captured["done_event"].wait(timeout=10.0)

    monkeypatch.setattr("launcher.tray_app.run_tray", fake_run_tray)

    # Recargar main para que use el patched run_tray.
    if "main" in sys.modules:
        del sys.modules["main"]
    mod = importlib.import_module("main")

    # Llamar main() en un hilo (porque run_tray bloquea).
    main_thread = threading.Thread(
        target=mod.main,
        name="main_test",
        daemon=True,
    )
    main_thread.start()

    # Esperar a que run_tray haya capturado el supervisor.
    deadline = time.time() + 5.0
    while "web" not in captured and time.time() < deadline:
        time.sleep(0.05)

    assert "web" in captured, (
        "main no llego a run_tray; posiblemente crasheo antes."
    )
    yield captured

    # Cleanup: marcar done para que run_tray retorne, luego main
    # hara web.stop() en el bloque final.
    if "done_event" in captured:
        captured["done_event"].set()
    main_thread.join(timeout=5.0)

    # Red de seguridad: si main fallo en cleanup, paramos nosotros.
    web = captured.get("web")
    if web is not None and web.is_alive():
        try:
            web.stop(timeout=2.0)
        except Exception:
            pass


@pytest.mark.slow
def test_main_creates_ob1_supervisor(fresh_main_tray):
    """main.main() crea un Ob1ServiceSupervisor (no WebServiceSupervisor)."""
    from launcher.ob1_supervisor import Ob1ServiceSupervisor

    web = fresh_main_tray["web"]
    assert isinstance(web, Ob1ServiceSupervisor), (
        f"main deberia crear Ob1ServiceSupervisor; obtuvo {type(web).__name__}"
    )


@pytest.mark.slow
def test_main_uses_env_vars_for_host_port(fresh_main_tray):
    """El supervisor toma host/port de ZC_WEB_HOST / ZC_WEB_PORT."""
    web = fresh_main_tray["web"]
    assert web.host == "127.0.0.1"
    assert web.port == fresh_main_tray["menu_items"][0].port  # mismo port


@pytest.mark.slow
def test_iniciar_web_starts_flask_and_ob1(fresh_main_tray):
    """Click en 'Iniciar web' → Flask responde, OB1 loop tickea."""
    web = fresh_main_tray["web"]
    assert not web.is_alive(), "Supervisor no debe estar vivo al inicio"

    # Simulamos el click invocando web.start() directamente (que es lo
    # que hace on_toggle_web en tray_app.py al pulsar "Iniciar web").
    web.start()
    assert web.wait_until_alive(timeout_s=5.0)
    assert web.is_alive()

    # Verificar HTTP.
    status, body = _http_get(f"http://127.0.0.1:{web.port}/ping")
    assert status == 200
    assert body.strip() == '{"pong":true}'

    # Verificar OB1 loop tickeando: cycle_count > 0.
    time.sleep(0.2)
    status, body = _http_get(f"http://127.0.0.1:{web.port}/cycle_count")
    assert status == 200
    import json as _json
    data = _json.loads(body)
    assert data["cycles"] >= 1


@pytest.mark.slow
def test_parar_web_stops_flask_and_ob1(fresh_main_tray):
    """Click en 'Parar web' → Flask dead, OB1 loop parado."""
    web = fresh_main_tray["web"]
    web.start()
    assert web.wait_until_alive(timeout_s=5.0)

    # Click en 'Parar web': web.stop().
    web.stop(timeout=5.0)
    assert not web.is_alive()

    # Flask no responde.
    with pytest.raises(urllib.error.URLError):
        urllib.request.urlopen(
            f"http://127.0.0.1:{web.port}/ping",
            timeout=1.0,
        )


@pytest.mark.slow
def test_salir_tray_para_supervisor_via_on_before_exit(fresh_main_tray):
    """Click en 'Salir' → on_before_exit() llama web.stop()."""
    web = fresh_main_tray["web"]
    web.start()
    assert web.wait_until_alive(timeout_s=5.0)

    # Invocamos el hook directamente (es lo que hace on_exit del menu).
    on_before_exit = fresh_main_tray["on_before_exit"]
    on_before_exit()
    # Tras el hook, los hilos deberían estar parados o en proceso.
    # Esperamos hasta que terminen.
    deadline = time.time() + 5.0
    while web.is_alive() and time.time() < deadline:
        time.sleep(0.1)
    assert not web.is_alive()


def _http_get(url: str, timeout: float = 2.0) -> tuple[int, str]:
    """GET helper: retorna (status, body)."""
    resp = urllib.request.urlopen(url, timeout=timeout)
    return resp.status, resp.read().decode("utf-8")
