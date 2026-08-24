"""Tests para ``launcher.web_supervisor.WebServiceSupervisor``.

Cubre el ciclo de vida del supervisor del web server:
  - start/stop limpio
  - is_alive refleja el estado real
  - auto-restart cuando uvicorn sale inesperadamente
  - start/stop idempotentes

Los tests usan puertos reales (no mockean uvicorn) para ser fieles al
comportamiento en producción. Cada test usa un puerto distinto
(9000+offset) para que pytest -k o pytest-xdist no choquen.

Marcados como ``@pytest.mark.slow`` porque algunos (restart) tardan
2-3s por el backoff exponencial.
"""
from __future__ import annotations

import time
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from launcher.web_supervisor import WebServiceSupervisor  # noqa: E402


def _port(test_id: int) -> int:
    """Puerto único por test, en rango alto para no chocar con nada."""
    return 19000 + test_id


@pytest.fixture
def port(request):
    """Cada test recibe un puerto distinto basado en su posición."""
    # nodeid es 'tests/test_web_supervisor.py::test_X'; usamos hash estable.
    return _port(abs(hash(request.node.name)) % 1000)


@pytest.fixture
def web(port, tmp_path) -> WebServiceSupervisor:
    """Supervisor con puerto único y log a tmp_path."""
    # Forzamos un log a tmp para no contaminar %LOCALAPPDATA%.
    import logging

    log_file = tmp_path / "web.log"
    logger = logging.getLogger(f"test_web_{port}")
    logger.handlers.clear()
    logger.addHandler(logging.FileHandler(log_file, encoding="utf-8"))
    logger.setLevel(logging.INFO)
    logger.propagate = False

    s = WebServiceSupervisor(host="127.0.0.1", port=port)
    s.log = logger
    yield s
    # Cleanup: si el test olvidó parar, lo paramos aquí.
    try:
        s.stop(timeout=2.0)
    except Exception:
        pass


def test_start_stop_clean(web: WebServiceSupervisor) -> None:
    """start() + stop() deja is_alive() en False."""
    web.start()
    try:
        # Dar tiempo a uvicorn a bindear.
        deadline = time.time() + 8.0
        while time.time() < deadline and not web.is_alive():
            time.sleep(0.1)
        assert web.is_alive(), f"web no arranco en el puerto {web.port}"
    finally:
        web.stop(timeout=3.0)
    assert not web.is_alive()


def test_alive_after_start(web: WebServiceSupervisor) -> None:
    """Tras start y un breve sleep, is_alive() es True."""
    web.start()
    try:
        deadline = time.time() + 8.0
        while time.time() < deadline and not web.is_alive():
            time.sleep(0.1)
        assert web.is_alive()
    finally:
        web.stop(timeout=3.0)


def test_restart_on_uvicorn_exit(web: WebServiceSupervisor) -> None:
    """Forzar should_exit en el server interno → supervisor relanza."""
    web.start()
    try:
        # Esperar a que esté vivo.
        deadline = time.time() + 8.0
        while time.time() < deadline and not web.is_alive():
            time.sleep(0.1)
        assert web.is_alive()
        # Forzar salida del uvicorn SIN pedir stop global.
        # (Esto emula un crash silencioso.)
        assert web._server is not None
        web._server.should_exit = True
        # El supervisor debe detectar la salida y reiniciar.
        # Backoff = 1s, así que esperamos ~3-4s para confirmar.
        time.sleep(4.0)
        assert web.restart_count >= 1, (
            f"restart_count={web.restart_count}, esperaba >=1"
        )
        # Tras el reinicio, debería estar vivo de nuevo.
        deadline = time.time() + 8.0
        while time.time() < deadline and not web.is_alive():
            time.sleep(0.1)
        assert web.is_alive()
    finally:
        web.stop(timeout=3.0)


def test_stop_is_idempotent(web: WebServiceSupervisor) -> None:
    """Llamar stop() dos veces no debe crashear."""
    web.start()
    deadline = time.time() + 8.0
    while time.time() < deadline and not web.is_alive():
        time.sleep(0.1)
    web.stop(timeout=3.0)
    # Segunda llamada: no debe lanzar.
    web.stop(timeout=1.0)
    assert not web.is_alive()


def test_double_start_no_op(web: WebServiceSupervisor) -> None:
    """start() dos veces no debe crear dos hilos."""
    web.start()
    first_thread = web._thread
    deadline = time.time() + 8.0
    while time.time() < deadline and not web.is_alive():
        time.sleep(0.1)
    web.start()  # segunda llamada: no-op
    assert web._thread is first_thread
    web.stop(timeout=3.0)


def test_is_alive_false_before_start(port, tmp_path) -> None:
    """Un supervisor recién creado no está vivo."""
    import logging

    s = WebServiceSupervisor(host="127.0.0.1", port=port)
    s.log = logging.getLogger(f"test_web_init_{port}")
    assert not s.is_alive()
