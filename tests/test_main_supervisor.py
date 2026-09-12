"""Tests para ``launcher.main_supervisor.MainServiceSupervisor``.

Cubre el ciclo de vida del supervisor (Flask + main loop):
  - start/stop limpio
  - is_alive refleja el estado real
  - Flask responde en /ping y /cycle_count
  - /cycle_count refleja el engine tickeando del main loop
  - start/stop idempotentes
  - auto-restart si Flask crashea

Los tests usan puertos reales (no mockean werkzeug). Cada test usa
un puerto distinto (rango alto) para que pytest no choque.
"""
from __future__ import annotations

import json
import logging
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from launcher.main_supervisor import MainServiceSupervisor  # noqa: E402


def _port(test_id: int) -> int:
    """Puerto único por test, en rango alto."""
    return 19500 + test_id


@pytest.fixture
def port(request) -> int:
    return _port(abs(hash(request.node.name)) % 1000)


@pytest.fixture
def supervisor(port, tmp_path) -> MainServiceSupervisor:
    """Supervisor con puerto único y log a tmp_path."""
    log_file = tmp_path / "main.log"
    logger = logging.getLogger(f"test_main_{port}")
    logger.handlers.clear()
    logger.addHandler(logging.FileHandler(log_file, encoding="utf-8"))
    logger.setLevel(logging.INFO)
    logger.propagate = False

    s = MainServiceSupervisor(host="127.0.0.1", port=port, tick_period_s=0.05)
    s.log = logger
    yield s
    try:
        if s.is_alive():
            s.stop(timeout=3.0)
    except Exception:
        pass


def _http_get(url: str, timeout: float = 2.0) -> tuple[int, str]:
    """GET helper: (status, body)."""
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
    assert supervisor._flask_thread is None
    assert supervisor._loop_thread is None
    assert supervisor._components is None


@pytest.mark.slow
def test_start_is_idempotent(supervisor):
    """Llamar start() dos veces no levanta hilos duplicados."""
    supervisor.start()
    assert supervisor.wait_until_alive(timeout_s=5.0)
    flask_thread_1 = supervisor._flask_thread
    loop_thread_1 = supervisor._loop_thread

    supervisor.start()
    assert supervisor._flask_thread is flask_thread_1
    assert supervisor._loop_thread is loop_thread_1

    supervisor.stop(timeout=5.0)


@pytest.mark.slow
def test_flask_responds_to_ping(supervisor):
    """Flask expone /ping con 200 OK."""
    supervisor.start()
    assert supervisor.wait_until_alive(timeout_s=5.0)
    status, body = _http_get(f"http://127.0.0.1:{supervisor.port}/ping")
    assert status == 200
    assert body.strip() == '{"pong":true}'


@pytest.mark.slow
def test_cycle_count_reflects_main_loop(supervisor):
    """El main loop tickea el engine; /cycle_count refleja su counter."""
    supervisor.start()
    assert supervisor.wait_until_alive(timeout_s=5.0)
    time.sleep(0.3)
    status, body = _http_get(f"http://127.0.0.1:{supervisor.port}/cycle_count")
    assert status == 200
    data = json.loads(body)
    assert "cycles" in data
    assert data["cycles"] >= 1, f"Main loop debería haber tickeado >= 1 vez: {data}"

    time.sleep(0.2)
    _, body2 = _http_get(f"http://127.0.0.1:{supervisor.port}/cycle_count")
    data2 = json.loads(body2)
    assert data2["cycles"] > data["cycles"], (
        f"cycle_count no incrementa: {data['cycles']} -> {data2['cycles']}"
    )


@pytest.mark.slow
def test_stop_without_start_is_safe(supervisor):
    """stop() sin start() previo no debe lanzar excepciones."""
    supervisor.stop(timeout=1.0)
    assert not supervisor.is_alive()


@pytest.mark.slow
def test_restart_count_zero_on_clean_start_stop(supervisor):
    """restart_count=0 tras start/stop limpios."""
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
    supervisor.stop(timeout=1.0)
    assert not supervisor.is_alive()
