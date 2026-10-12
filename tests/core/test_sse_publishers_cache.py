"""Tests de los publishers SSE del AppCache.

Cubre:

- ``make_cache_snapshot_publisher`` enqueue un ``cache_snapshot``
  en la cola del nuevo suscriptor via ``EventBusSync.set_on_subscribe``.
- ``make_cache_change_publisher`` cablea ``app_cache.on_change`` y
  emite ``cache_changed`` broadcast tras cada ``mutate/mutate_area``
  con ``slot=``.
- ``AppCache.to_api_dict`` produce el shape estable (5 claves
  globales + ``areas`` keyed por area_id).
- Round-trip: tras una mutacion el ``on_change`` recibe los 4 args
  correctos ``(slot, area_id, plc_name, value)``.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.data.data_block_cache import DataBloqueCache
from core.data.data_plc_info import PlcInfo, PlcProject
from core.runtime.app_cache import (
    AppCache,
    _AppCacheState,
    get_app_cache,
)
from core.runtime.sse.sse_event_bus_sync import EventBusSync
from core.runtime.sse.sse_publishers import (
    make_cache_change_publisher,
    make_cache_snapshot_publisher,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """Reset del Singleton ``get_app_cache()`` antes de cada test."""
    import core.runtime.app_cache as _mod
    _mod._app_cache = None
    yield
    _mod._app_cache = None


# ─────────────────────────────────────────────────────────────────────
# AppCache.to_api_dict
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _FakeArea:
    """Stub del Protocol AreaCacheProtocol con campos adicionales."""

    excel_full: Any = None
    excel_active: Any = None
    preview_disp: Any = None
    preview_proc: Any = None
    last_sync_disp_at: Any = None
    last_sync_proc_at: Any = None
    last_disp_commit_summary: Any = None
    last_proc_commit_summary: Any = None

    def reset(self) -> "_FakeArea":
        return _FakeArea()


def test_to_api_dict_shape_vacio() -> None:
    """Cache recien creado: shape con todos los slots en defaults."""
    cache = AppCache()
    snapshot = cache.to_api_dict()

    assert snapshot["selected_plc"] == ""
    assert snapshot["plc_list"] == []
    assert snapshot["plc_blocks"] == {}
    assert snapshot["plc_project"] == {}
    assert snapshot["plc_user_constants"] == {}
    assert snapshot["areas"] == {}


def test_to_api_dict_serializa_plc_list_con_to_dict() -> None:
    """Cada PlcInfo se serializa via ``to_dict``."""
    cache = AppCache()
    cache.mutate(
        lambda s: dataclasses.replace(
            s,
            plc_list=(PlcInfo(name="PLC_A", type="S7-1500", ip="10.0.0.1"),),
            selected_plc="PLC_A",
        ),
    )
    snap = cache.to_api_dict()
    assert snap["plc_list"] == [
        {"name": "PLC_A", "type": "S7-1500", "ip": "10.0.0.1"},
    ]
    assert snap["selected_plc"] == "PLC_A"


def test_to_api_dict_serializa_plc_blocks_via_to_dict() -> None:
    """``DataBloqueCache`` se serializa via su propio ``to_dict``."""
    cache = AppCache()
    cache.mutate(
        lambda s: dataclasses.replace(
            s,
            plc_blocks={
                "PLC_A": DataBloqueCache(
                    plc_name="PLC_A",
                    blocks={},
                    tag_tables={},
                    udts={},
                    scanned_at=datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc),
                ),
            },
        ),
    )
    snap = cache.to_api_dict()
    assert "PLC_A" in snap["plc_blocks"]
    assert snap["plc_blocks"]["PLC_A"]["plc_name"] == "PLC_A"
    assert snap["plc_blocks"]["PLC_A"]["scanned_at"].startswith("2026-10-10")


def test_to_api_dict_serializa_areas_con_datetime_en_iso() -> None:
    """Areas con ``datetime`` -> ISO-8601 (no ``str(datetime)``)."""
    cache = AppCache()
    fake = _FakeArea(
        last_sync_disp_at=datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc),
    )
    cache.register_area("alimentacion", fake)

    snap = cache.to_api_dict()
    row = snap["areas"]["alimentacion"]
    assert row["last_sync_disp_at"].startswith("2026-10-10")


def test_to_api_dict_no_expone_el_lock_internamente() -> None:
    """Varias llamadas devuelven snapshots independientes (no aliasing)."""
    cache = AppCache()
    cache.register_area("a", _FakeArea())
    snap1 = cache.to_api_dict()
    cache.mutate(lambda s: dataclasses.replace(s, selected_plc="X"))
    snap2 = cache.to_api_dict()
    assert snap1["selected_plc"] == ""
    assert snap2["selected_plc"] == "X"


# ─────────────────────────────────────────────────────────────────────
# AppCache.on_change
# ─────────────────────────────────────────────────────────────────────


def test_on_change_es_invocado_en_mutate_con_slot() -> None:
    """``mutate(slot=...)`` dispara el callback con los 4 args."""
    cache = AppCache()
    captured: list[tuple[str, str | None, str | None, object]] = []

    def cb(slot: str, area_id: str | None, plc_name: str | None, value: object) -> None:
        captured.append((slot, area_id, plc_name, value))

    cache.on_change(cb)
    cache.mutate(
        lambda s: dataclasses.replace(s, selected_plc="PLC_X"),
        slot="selected_plc",
    )

    assert len(captured) == 1
    slot, area_id, plc_name, value = captured[0]
    assert slot == "selected_plc"
    assert area_id is None
    assert plc_name is None
    assert value == "PLC_X"


def test_on_change_es_invocado_en_mutate_area_con_slot() -> None:
    """``mutate_area(slot=...)`` dispara el callback con ``area_id``."""
    cache = AppCache()
    fake = _FakeArea()
    cache.register_area("alimentacion", fake)

    captured: list[tuple[str, str | None, str | None, object]] = []

    def cb(slot, area_id, plc_name, value):
        captured.append((slot, area_id, plc_name, value))

    cache.on_change(cb)
    cache.mutate_area(
        "alimentacion",
        lambda a: dataclasses.replace(a, preview_disp={"ok": True}),
        slot="preview_disp",
    )

    assert len(captured) == 1
    slot, area_id, plc_name, value = captured[0]
    assert slot == "preview_disp"
    assert area_id == "alimentacion"
    assert plc_name is None
    assert value == {"ok": True}


def test_on_change_no_es_invocado_sin_slot() -> None:
    """``mutate()`` sin ``slot=`` no dispara el callback."""
    cache = AppCache()
    called = []
    cache.on_change(lambda *args: called.append(args))
    cache.mutate(lambda s: dataclasses.replace(s, selected_plc="X"))
    assert called == []


def test_on_change_se_puede_desregistrar_con_none() -> None:
    """``on_change(None)`` desactiva las notificaciones."""
    cache = AppCache()
    called = []
    cache.on_change(lambda *args: called.append(args))
    cache.mutate(
        lambda s: dataclasses.replace(s, selected_plc="X"),
        slot="selected_plc",
    )
    assert len(called) == 1

    cache.on_change(None)
    cache.mutate(
        lambda s: dataclasses.replace(s, selected_plc="Y"),
        slot="selected_plc",
    )
    assert len(called) == 1  # no incremento


# ─────────────────────────────────────────────────────────────────────
# make_cache_snapshot_publisher
# ─────────────────────────────────────────────────────────────────────


def test_make_cache_snapshot_publisher_enrola_on_subscribe() -> None:
    """La factory registra el callback en ``bus.set_on_subscribe``."""
    bus = EventBusSync()
    cache = AppCache()
    make_cache_snapshot_publisher(bus, cache)
    # El ``bus.set_on_subscribe`` se invoco con un callable (no None).
    assert bus._on_subscribe is not None  # noqa: SLF001


def test_snapshot_se_enqueuea_al_suscribirse() -> None:
    """Al hacer ``bus.subscribe()`` el snapshot se enqueue en la cola."""
    bus = EventBusSync()
    cache = AppCache()
    cache.register_area("alimentacion", _FakeArea())
    make_cache_snapshot_publisher(bus, cache)

    q = bus.subscribe()
    evt = q.get_nowait()
    assert evt["type"] == "cache_snapshot"
    assert "data" in evt
    assert evt["data"]["areas"] == {
        "alimentacion": {
            "excel_full": None,
            "excel_active": None,
            "preview_disp": None,
            "preview_proc": None,
            "last_sync_disp_at": None,
            "last_sync_proc_at": None,
            "last_disp_commit_summary": None,
            "last_proc_commit_summary": None,
        },
    }


def test_snapshot_incluye_los_datos_actuales_del_cache() -> None:
    """El snapshot refleja el estado vivo del AppCache."""
    bus = EventBusSync()
    cache = AppCache()
    cache.mutate(
        lambda s: dataclasses.replace(s, selected_plc="PLC_A"),
    )
    make_cache_snapshot_publisher(bus, cache)

    q = bus.subscribe()
    evt = q.get_nowait()
    assert evt["data"]["selected_plc"] == "PLC_A"


def test_snapshot_no_interfiere_con_eventos_publicados() -> None:
    """El snapshot solo se entrega al suscriptor nuevo; no broadcast."""
    bus = EventBusSync()
    cache = AppCache()
    make_cache_snapshot_publisher(bus, cache)

    q1 = bus.subscribe()  # recibe snapshot
    q2 = bus.subscribe()  # tambien (cada subscribe nuevo)
    bus.publish({"type": "log", "msg": "hello"})

    # Cada cola tiene: snapshot + log
    snap1 = q1.get_nowait()
    assert snap1["type"] == "cache_snapshot"
    log1 = q1.get_nowait()
    assert log1["type"] == "log"

    snap2 = q2.get_nowait()
    assert snap2["type"] == "cache_snapshot"
    log2 = q2.get_nowait()
    assert log2["type"] == "log"


# ─────────────────────────────────────────────────────────────────────
# make_cache_change_publisher
# ─────────────────────────────────────────────────────────────────────


def test_make_cache_change_publisher_cablea_on_change() -> None:
    """La factory registra el callback en ``app_cache.on_change``."""
    cache = AppCache()
    bus = MagicMock()
    make_cache_change_publisher(bus, cache)
    assert cache._on_change is not None  # noqa: SLF001


def test_cache_changed_se_emite_en_mutate_con_slot() -> None:
    """Tras ``mutate(slot=...)`` se hace ``bus.publish(cache_changed)``."""
    cache = AppCache()
    bus = MagicMock()
    make_cache_change_publisher(bus, cache)

    cache.mutate(
        lambda s: dataclasses.replace(s, selected_plc="PLC_X"),
        slot="selected_plc",
    )

    bus.publish.assert_called_once()
    evt = bus.publish.call_args[0][0]
    assert evt["type"] == "cache_changed"
    assert evt["slot"] == "selected_plc"
    assert evt["area_id"] is None
    assert evt["plc_name"] is None
    assert evt["data"] == "PLC_X"


def test_cache_changed_se_emite_en_mutate_area_con_slot() -> None:
    """Tras ``mutate_area(slot=...)`` se hace ``bus.publish`` con area_id."""
    cache = AppCache()
    bus = MagicMock()
    cache.register_area("alimentacion", _FakeArea())
    make_cache_change_publisher(bus, cache)

    cache.mutate_area(
        "alimentacion",
        lambda a: dataclasses.replace(a, preview_disp={"ok": True}),
        slot="preview_disp",
    )

    bus.publish.assert_called_once()
    evt = bus.publish.call_args[0][0]
    assert evt["type"] == "cache_changed"
    assert evt["slot"] == "preview_disp"
    assert evt["area_id"] == "alimentacion"
    assert evt["data"] == {"ok": True}


def test_cache_changed_no_se_emite_sin_slot() -> None:
    """Sin ``slot=``, no se publica ``cache_changed``."""
    cache = AppCache()
    bus = MagicMock()
    make_cache_change_publisher(bus, cache)
    cache.mutate(lambda s: dataclasses.replace(s, selected_plc="X"))
    bus.publish.assert_not_called()


# ─────────────────────────────────────────────────────────────────────
# Integracion EventBusSync + publisher
# ─────────────────────────────────────────────────────────────────────


def test_round_trip_suscriptor_recibe_snapshot_y_deltas() -> None:
    """Suscriptor nuevo: snapshot. Mutacion posterior: delta."""
    cache = AppCache()
    cache.register_area("alimentacion", _FakeArea())
    bus = EventBusSync()
    make_cache_snapshot_publisher(bus, cache)
    make_cache_change_publisher(bus, cache)

    q = bus.subscribe()
    snap = q.get_nowait()
    assert snap["type"] == "cache_snapshot"

    # Tras una mutacion, el suscriptor recibe el delta.
    cache.mutate(
        lambda s: dataclasses.replace(s, selected_plc="PLC_NEW"),
        slot="selected_plc",
    )
    delta = q.get_nowait()
    assert delta["type"] == "cache_changed"
    assert delta["slot"] == "selected_plc"
    assert delta["data"] == "PLC_NEW"


def test_singleton_get_app_cache_es_el_mismo_entre_calls() -> None:
    """El Singleton persiste a lo largo de los tests."""
    c1 = get_app_cache()
    c2 = get_app_cache()
    assert c1 is c2