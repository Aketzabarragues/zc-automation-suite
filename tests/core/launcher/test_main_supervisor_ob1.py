"""tests.core.launcher.test_main_supervisor_ob1 - cableado del dispatcher OB1.

El supervisor es el dueno del ciclo de vida del dispatcher OB1 (hilo
``plc-ob1`` propiedad del ``Engine``). Estos tests aislan el cableado en
los metodos privados ``_start_ob1`` / ``_stop_ob1`` y verifican el orden
de parada sin montar Flask ni TIA reales.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.launcher.main_supervisor import MainServiceSupervisor


def _supervisor() -> MainServiceSupervisor:
    """Supervisor construido sin arrancar nada (sin engine real)."""
    return MainServiceSupervisor(host="127.0.0.1", port=0, no_engine=True)


def _components(engine: object | None = None) -> tuple:
    """Tupla de componentes: (tia_client, engine, event_bus, flask_app)."""
    return (MagicMock(), engine, MagicMock(), MagicMock())


def test_start_ob1_arranca_el_dispatcher() -> None:
    """_start_ob1 llama a engine.start_ob1() una sola vez."""
    sup = _supervisor()
    engine = MagicMock()
    sup._components = _components(engine)

    sup._start_ob1()

    engine.start_ob1.assert_called_once_with()


def test_start_ob1_no_hace_nada_sin_engine() -> None:
    """Sin engine (no_engine=True), _start_ob1 es no-op."""
    sup = _supervisor()
    sup._components = _components(None)

    sup._start_ob1()  # no debe lanzar


def test_start_ob1_tolera_excepcion() -> None:
    """Un fallo al arrancar el dispatcher no aborta el arranque de la app."""
    sup = _supervisor()
    engine = MagicMock()
    engine.start_ob1.side_effect = RuntimeError("boom")
    sup._components = _components(engine)

    sup._start_ob1()  # no debe propagar la excepcion

    engine.start_ob1.assert_called_once_with()


def test_stop_ob1_para_el_dispatcher() -> None:
    """_stop_ob1 llama a engine.stop_ob1(timeout=...)."""
    sup = _supervisor()
    engine = MagicMock()
    sup._components = _components(engine)

    sup._stop_ob1(timeout=3.0)

    engine.stop_ob1.assert_called_once_with(timeout=3.0)


def test_stop_ob1_no_hace_nada_sin_engine() -> None:
    """Sin engine, _stop_ob1 es no-op."""
    sup = _supervisor()
    sup._components = _components(None)

    sup._stop_ob1(timeout=3.0)  # no debe lanzar


def test_stop_ob1_tolera_excepcion() -> None:
    """Un fallo al parar el dispatcher no aborta el cierre de la app."""
    sup = _supervisor()
    engine = MagicMock()
    engine.stop_ob1.side_effect = RuntimeError("boom")
    sup._components = _components(engine)

    sup._stop_ob1(timeout=3.0)  # no debe propagar la excepcion

    engine.stop_ob1.assert_called_once_with(timeout=3.0)


def test_start_arranca_el_dispatcher_ob1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """start() cablea el arranque del dispatcher OB1 tras construir componentes."""
    monkeypatch.chdir(tmp_path)
    import core.launcher.main_supervisor as mod

    sup = _supervisor()
    engine = MagicMock()
    tia_client = MagicMock()
    sup._build_components = lambda: (tia_client, engine, MagicMock(), MagicMock())

    # Hilos falsos: start() no debe levantar Flask ni el main-loop real.
    monkeypatch.setattr(
        mod, "threading", SimpleNamespace(Thread=lambda **kwargs: MagicMock())
    )

    sup.start()

    engine.start_ob1.assert_called_once_with()
    tia_client.start_tia_loop.assert_not_called()


def test_el_supervisor_no_arranca_ningun_loop_async(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El unico camino de ejecucion es el dispatcher OB1.

    El engine conserva los metodos del tick legacy, pero el supervisor no
    los arranca. Este guard lo fija: si alguien reintrodujera el hilo
    ``main-loop``, la suite lo detecta en vez de dejarlo pasar en silencio.
    """
    monkeypatch.chdir(tmp_path)
    import core.launcher.main_supervisor as mod

    sup = _supervisor()
    engine = MagicMock()
    tia_client = MagicMock()
    sup._build_components = lambda: (tia_client, engine, MagicMock(), MagicMock())
    monkeypatch.setattr(
        mod, "threading", SimpleNamespace(Thread=lambda **kwargs: MagicMock())
    )

    sup.start()

    engine.start_ob1.assert_called_once_with()
    engine.start_loop.assert_not_called()
    engine.run_cycle.assert_not_called()
    engine.tick_once.assert_not_called()


def test_stop_para_el_dispatcher_antes_que_el_worker_tia(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stop() apaga el dispatcher OB1 antes que el worker TIA."""
    monkeypatch.chdir(tmp_path)  # no tocar el .build_cache real
    monkeypatch.setattr(
        "core.runtime.app_cache.get_app_cache", lambda: MagicMock()
    )

    orden: list[str] = []
    sup = _supervisor()
    tia_client = MagicMock()
    engine = MagicMock()
    engine.stop_ob1.side_effect = lambda **kwargs: orden.append("ob1")
    tia_client.stop_tia_loop.side_effect = lambda **kwargs: orden.append("tia")
    sup._components = (tia_client, engine, MagicMock(), MagicMock())

    sup.stop(timeout=1.0)

    assert orden == ["ob1", "tia"]
    engine.stop_ob1.assert_called_once_with(timeout=1.0)
    tia_client.stop_tia_loop.assert_called_once_with(timeout=1.0)
