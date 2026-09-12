"""Tests para ``launcher.ob1_supervisor.Ob1ServiceSupervisor`` (Fase 4 / 4.N3).

Cubre el ciclo de vida del supervisor OB1 (Flask + OB1 main loop):
  - start/stop limpio
  - is_alive refleja el estado real
  - Flask responde en /ping y /cycle_count
  - /cycle_count refleja el engine tickeando del OB1 loop
  - start/stop idempotentes
  - auto-restart si Flask crashea

Los tests usan puertos reales (no mockean werkzeug) para ser fieles al
comportamiento en producción. Cada test usa un puerto distinto
(19000+offset) para que pytest no choque.

Marcados como ``@pytest.mark.slow`` porque el startup del Flask + OB1
tarda ~300-500ms por test.
"""
from __future__ import annotations

import logging
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from launcher.ob1_supervisor import Ob1ServiceSupervisor  # noqa: E402


def _port(test_id: int) -> int:
    """Puerto único por test, en rango alto para no chocar con nada."""
    return 19500 + test_id


@pytest.fixture
def port(request) -> int:
    """Cada test recibe un puerto distinto basado en hash del nombre."""
    return _port(abs(hash(request.node.name)) % 1000)


@pytest.fixture
def supervisor(port, tmp_path) -> Ob1ServiceSupervisor:
    """Supervisor OB1 con puerto único y log a tmp_path."""
    log_file = tmp_path / "ob1.log"
    logger = logging.getLogger(f"test_ob1_{port}")
    logger.handlers.clear()
    logger.addHandler(logging.FileHandler(log_file, encoding="utf-8"))
    logger.setLevel(logging.INFO)
    logger.propagate = False

    s = Ob1ServiceSupervisor(
        host="127.0.0.1",
        port=port,
        tick_period_s=0.05,
    )
    s.log = logger
    yield s
    # Cleanup: si el test olvidó parar, lo paramos aquí.
    try:
        if s.is_alive():
            s.stop(timeout=3.0)
    except Exception:
        pass


def _http_get(url: str, timeout: float = 2.0) -> tuple[int, str]:
    """GET helper: retorna (status, body)."""
    resp = urllib.request.urlopen(url, timeout=timeout)
    return resp.status, resp.read().decode("utf-8")


@pytest.mark.slow
def test_start_stop_is_clean(supervisor):
    """start() arranca ambos hilos; stop() los para limpiamente."""
    assert not supervisor.is_alive()
    supervisor.start()
    assert supervisor.wait_until_alive(timeout_s=5.0)
    assert supervisor.is_alive()
    supervisor.stop(timeout=5.0)
    assert not supervisor.is_alive()
    # Tras stop, los hilos deben estar None (limpieza completa).
    assert supervisor._flask_thread is None
    assert supervisor._loop_thread is None
    assert supervisor._components is None


@pytest.mark.slow
def test_start_is_idempotent(supervisor):
    """Llamar start() dos veces no debe levantar hilos duplicados."""
    supervisor.start()
    assert supervisor.wait_until_alive(timeout_s=5.0)
    flask_thread_1 = supervisor._flask_thread
    loop_thread_1 = supervisor._loop_thread

    # Segundo start: debe ser no-op (mismos hilos).
    supervisor.start()
    assert supervisor._flask_thread is flask_thread_1
    assert supervisor._loop_thread is loop_thread_1

    supervisor.stop(timeout=5.0)


@pytest.mark.slow
def test_flask_responds_to_ping(supervisor):
    """Flask daemon expone /ping con 200 OK tras arrancar."""
    supervisor.start()
    assert supervisor.wait_until_alive(timeout_s=5.0)
    status, body = _http_get(f"http://127.0.0.1:{supervisor.port}/ping")
    assert status == 200
    # Werkzeug anade un '\n' al body por la convencion HTTP.
    assert body.strip() == '{"pong":true}'


@pytest.mark.slow
def test_cycle_count_reflects_ob1_loop(supervisor):
    """El OB1 main loop tickea el engine; /cycle_count refleja su counter."""
    supervisor.start()
    assert supervisor.wait_until_alive(timeout_s=5.0)

    # Esperamos ~300ms para que el OB1 loop tickee varias veces.
    time.sleep(0.3)

    status, body = _http_get(f"http://127.0.0.1:{supervisor.port}/cycle_count")
    assert status == 200
    # body es {"cycles":N}; parseamos simple.
    import json

    data = json.loads(body)
    assert "cycles" in data
    assert data["cycles"] >= 1, f"OB1 loop debería haber tickeado >= 1 vez: {data}"

    # Una segunda lectura tras otro wait debe ser MAYOR (engine.tickea).
    time.sleep(0.2)
    status2, body2 = _http_get(f"http://127.0.0.1:{supervisor.port}/cycle_count")
    data2 = json.loads(body2)
    assert data2["cycles"] > data["cycles"], (
        f"cycle_count no incrementa: {data['cycles']} -> {data2['cycles']}"
    )


@pytest.mark.slow
def test_stop_without_start_is_safe(supervisor):
    """stop() sin start() previo no debe lanzar excepciones."""
    # No llamamos start. stop() debe ser no-op limpio.
    supervisor.stop(timeout=1.0)
    assert not supervisor.is_alive()


@pytest.mark.slow
def test_restart_count_zero_on_clean_start_stop(supervisor):
    """restart_count=0 tras start/stop limpios (sin crashes)."""
    supervisor.start()
    assert supervisor.wait_until_alive(timeout_s=5.0)
    assert supervisor.restart_count == 0
    supervisor.stop(timeout=5.0)
    assert supervisor.restart_count == 0


@pytest.mark.slow
def test_wait_until_alive_returns_false_if_not_started(supervisor):
    """wait_until_alive retorna False si start() no se llamó."""
    assert supervisor.wait_until_alive(timeout_s=1.0) is False


@pytest.mark.slow
def test_double_stop_is_safe(supervisor):
    """stop() dos veces seguidas no debe lanzar excepciones."""
    supervisor.start()
    assert supervisor.wait_until_alive(timeout_s=5.0)
    supervisor.stop(timeout=5.0)
    # Segundo stop: no-op limpio.
    supervisor.stop(timeout=1.0)
    assert not supervisor.is_alive()
