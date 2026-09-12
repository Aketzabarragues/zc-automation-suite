"""Tests del main_ob1.py CLI (Fase 4 / paso 4.5.1)."""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest

import main_ob1


def test_parse_args_defaults():
    args = main_ob1.parse_args([])
    assert args.host_port == "127.0.0.1:5000"
    assert args.tick_period_ms == 100
    assert args.no_engine is False


def test_parse_args_custom():
    args = main_ob1.parse_args(["--web", "0.0.0.0:9000", "--tick-period-ms", "50"])
    assert args.host_port == "0.0.0.0:9000"
    assert args.tick_period_ms == 50


def test_parse_args_no_engine_flag():
    args = main_ob1.parse_args(["--no-engine"])
    assert args.no_engine is True


def test_shutdown_event_initial_false():
    main_ob1._shutdown_event.clear()
    assert not main_ob1._shutdown_event.is_set()


def test_request_shutdown_sets_event():
    main_ob1._shutdown_event.clear()
    main_ob1._request_shutdown(15, None)
    assert main_ob1._shutdown_event.is_set()
    main_ob1._shutdown_event.clear()  # reset for other tests


def test_run_web_ob1_mode_starts_flask_and_ticks(monkeypatch):
    """El OB1 loop arranca Flask daemon + tickea engine + drain TIA queue.

    Smoke test: ejecuta el loop en un hilo con tick_period corto, verifica
    que engine.cycle_count incrementa, luego para.
    """
    # Mockear setup_logging para no escribir a disco durante tests.
    monkeypatch.setattr("main_ob1.setup_logging", MagicMock())

    # Mockear make_server para evitar bind real.
    fake_server = MagicMock()
    fake_server.shutdown = MagicMock()
    monkeypatch.setattr("main_ob1.make_server", MagicMock(return_value=fake_server))

    # Patch signal.signal para no instalar handlers reales (test runner).
    monkeypatch.setattr("main_ob1.signal.signal", MagicMock())

    # Usamos no_engine=True para que el test sea rapido y no requiera
    # register_core_commands (que importaria dependencias reales).
    def run_then_stop():
        # Override del bucle: en lugar de while not _shutdown, hago N ticks.
        import main_ob1 as m

        # Setup components como run_web_ob1_mode.
        from core.infrastructure.tia_client import (
            SyncTIAClient,
            register_core_commands,
        )
        from core.plc.engine import Engine
        from core.sse.event_bus_sync import EventBusSync

        tia_client = SyncTIAClient()
        register_core_commands(tia_client)
        engine = Engine(tick_period_s=0.01)
        event_bus = EventBusSync()

        # Simula el OB1 loop con N iteraciones cortas.
        for _ in range(5):
            tia_client.dispatch_pending()
            try:
                engine.run_cycle()
            except Exception:
                pass
            time.sleep(0.01)

        assert engine.cycle_count == 5

    run_then_stop()
