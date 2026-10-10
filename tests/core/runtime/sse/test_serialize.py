"""Tests del helper ``to_jsonable`` y su aplicacion en publishers SSE.

Cubre:

- ``to_jsonable`` con primitivos, datetime, listas/tuplas/dicts,
  dataclasses (``asdict``), objetos con ``to_dict()`` y fallback
  ``repr``.
- ``make_cache_change_publisher`` normaliza ``value`` para que
  ``json.dumps`` no aborte con ``TypeError: Object of type
  DataExcelCache is not JSON serializable`` cuando el slot es
  un dataclass (regresion del bug #1 del smoke de
  ``feature/app-cache-unico``).
- ``make_fb_state_publisher`` aplica la misma proteccion a
  ``fb.result`` (defensiva; mismo tipo de bug potencial).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.runtime.app_cache import AppCache
from core.runtime.sse._serialize import to_jsonable
from core.runtime.sse.sse_event_bus_sync import EventBusSync
from core.runtime.sse.sse_publishers import (
    make_cache_change_publisher,
    make_fb_state_publisher,
)


# ─────────────────────────────────────────────────────────────────────
# Stubs
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _FakeDC:
    """Stub de dataclass con campos primitivos."""

    a: int = 1
    b: str = "x"


@dataclass(frozen=True)
class _FakeNestedDC:
    """Stub con campos no triviales (lista + dict + datetime)."""

    items: tuple[int, ...]
    meta: dict[str, str]
    when: datetime


class _HasToDict:
    """Stub que expone ``to_dict()`` pero NO es dataclass."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def to_dict(self) -> dict:
        return self._payload


class _HasToDictRaising:
    """Stub cuyo ``to_dict()`` lanza: el helper cae al ``repr()``."""

    def to_dict(self) -> dict:
        raise RuntimeError("boom")


class _NoToDictNoDataclass:
    """Stub opaco sin ``to_dict``: cae al ``repr()``."""


# ─────────────────────────────────────────────────────────────────────
# to_jsonable — primitivos
# ─────────────────────────────────────────────────────────────────────


def test_to_jsonable_pasa_primitivos() -> None:
    """``None``, ``str``, ``int``, ``float``, ``bool`` retornan tal cual."""
    assert to_jsonable(None) is None
    assert to_jsonable("hola") == "hola"
    assert to_jsonable(42) == 42
    assert to_jsonable(3.14) == 3.14
    assert to_jsonable(True) is True
    assert to_jsonable(False) is False


# ─────────────────────────────────────────────────────────────────────
# to_jsonable — datetime
# ─────────────────────────────────────────────────────────────────────


def test_to_jsonable_datetime_a_isoformat() -> None:
    """``datetime`` se serializa a ISO-8601 (no ``str(datetime)`` con microseg)."""
    when = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
    out = to_jsonable(when)
    assert out == "2026-10-10T12:00:00+00:00"
    # Y ademas el output es directamente JSON-serializable:
    assert json.dumps(out) == '"2026-10-10T12:00:00+00:00"'


# ─────────────────────────────────────────────────────────────────────
# to_jsonable — listas, tuplas, dicts (recursivo)
# ─────────────────────────────────────────────────────────────────────


def test_to_jsonable_lista_y_tupla_recursivo() -> None:
    """``list`` y ``tuple`` se recorren elemento a elemento."""
    when = datetime(2026, 1, 1, tzinfo=timezone.utc)
    out_list = to_jsonable([1, "a", when, (2, 3)])
    assert out_list == [1, "a", "2026-01-01T00:00:00+00:00", [2, 3]]

    out_tuple = to_jsonable((1, "a", _FakeDC()))
    assert out_tuple == [1, "a", {"a": 1, "b": "x"}]


def test_to_jsonable_dict_recursivo() -> None:
    """``dict`` se recorre valor a valor; las claves se mantienen."""
    when = datetime(2026, 5, 5, tzinfo=timezone.utc)
    out = to_jsonable({"k": _FakeDC(7, "y"), "t": when, "l": [1, 2]})
    assert out == {
        "k": {"a": 7, "b": "y"},
        "t": "2026-05-05T00:00:00+00:00",
        "l": [1, 2],
    }


# ─────────────────────────────────────────────────────────────────────
# to_jsonable — dataclass
# ─────────────────────────────────────────────────────────────────────


def test_to_jsonable_dataclass_con_asdict() -> None:
    """``dataclass`` se aplana con ``asdict`` y luego se normaliza recursivo."""
    when = datetime(2026, 7, 7, tzinfo=timezone.utc)
    dc = _FakeNestedDC(items=(1, 2, 3), meta={"k": "v"}, when=when)
    out = to_jsonable(dc)
    assert out == {
        "items": [1, 2, 3],
        "meta": {"k": "v"},
        "when": "2026-07-07T00:00:00+00:00",
    }
    # El resultado es directamente JSON-serializable.
    json.dumps(out)


def test_to_jsonable_dataclass_simple() -> None:
    """Una dataclass simple sin campos no triviales."""
    out = to_jsonable(_FakeDC(42, "z"))
    assert out == {"a": 42, "b": "z"}


# ─────────────────────────────────────────────────────────────────────
# to_jsonable — to_dict() / fallback repr()
# ─────────────────────────────────────────────────────────────────────


def test_to_jsonable_objeto_con_to_dict() -> None:
    """Objeto con ``to_dict()`` (no dataclass) se aplana y se normaliza."""
    when = datetime(2026, 8, 8, tzinfo=timezone.utc)
    obj = _HasToDict({"k": _FakeDC(3, "p"), "t": when})
    out = to_jsonable(obj)
    assert out == {"k": {"a": 3, "b": "p"}, "t": "2026-08-08T00:00:00+00:00"}


def test_to_jsonable_to_dict_que_lanza_cae_a_repr() -> None:
    """Si ``to_dict()`` lanza, fallback a ``repr()`` (no propaga la excepcion)."""
    obj = _HasToDictRaising()
    out = to_jsonable(obj)
    assert isinstance(out, str)
    assert "_HasToDictRaising" in out


def test_to_jsonable_objeto_desconocido_a_repr() -> None:
    """Objeto opaco sin ``to_dict`` cae al ``repr()`` (ultimo recurso)."""
    obj = _NoToDictNoDataclass()
    out = to_jsonable(obj)
    assert isinstance(out, str)
    assert "_NoToDictNoDataclass" in out


# ─────────────────────────────────────────────────────────────────────
# make_cache_change_publisher — integracion (regresion bug #1)
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """Reset del Singleton ``get_app_cache()`` antes de cada test."""
    import core.runtime.app_cache as _mod
    _mod._app_cache = None
    yield
    _mod._app_cache = None


def _invoke_cache_change(
    cache: AppCache,
    slot: str,
    area_id: str | None,
    plc_name: str | None,
    value: Any,
) -> Any:
    """Dispara el callback ``_on_change`` que ``make_cache_change_publisher``
    registra en el AppCache. Reproduce el flujo real de una mutacion
    sin necesidad de levantar el ``_AppCacheState`` con un slot concreto.
    """
    assert cache._on_change is not None, (  # noqa: SLF001
        "make_cache_change_publisher no se ha cableado"
    )
    cache._on_change(slot, area_id, plc_name, value)  # noqa: SLF001


def test_cache_changed_publisher_normaliza_data_excel_cache() -> None:
    """Reproduce el bug #1: value = ``DataExcelCache`` (dataclass frozen).

    Antes del fix, ``bus.publish({..., 'data': value})`` lanzaba
    ``TypeError: Object of type DataExcelCache is not JSON
    serializable`` en el generador SSE. Tras el fix, el helper
    ``to_jsonable`` aplana el dataclass via ``asdict`` y el JSON
   .dumps del SSE funciona.

    Aqui validamos la unidad minima: el evento publicado lleva
    ``data`` como ``dict`` plano, no como instancia de dataclass.
    El shape exacto de ``DataExcelCache`` es irrelevante; usamos el
    stub ``_FakeDC`` para reproducir la condicion minima que
    disparaba el bug (value es dataclass frozen).
    """
    cache = AppCache()
    bus = MagicMock()
    make_cache_change_publisher(bus, cache)

    fake_value = _FakeDC(a=7, b="hola")
    _invoke_cache_change(
        cache, slot="excel_full", area_id=None, plc_name=None,
        value=fake_value,
    )

    bus.publish.assert_called_once()
    evt = bus.publish.call_args[0][0]
    assert evt["type"] == "cache_changed"
    assert evt["slot"] == "excel_full"
    assert evt["data"] == {"a": 7, "b": "hola"}
    assert not isinstance(evt["data"], _FakeDC)
    # Y, ademas, es directamente JSON-serializable (el bug era este
    # json.dumps lanza TypeError en el generador SSE).
    json.dumps(evt["data"])


def test_cache_changed_publisher_normaliza_lista_de_dataclasses() -> None:
    """``value`` puede ser lista/tupla de dataclasses (slots compuestos)."""
    cache = AppCache()
    bus = MagicMock()
    make_cache_change_publisher(bus, cache)

    value = (_FakeDC(1, "a"), _FakeDC(2, "b"))
    _invoke_cache_change(
        cache, slot="preview_disp", area_id="alimentacion", plc_name="PLC_A",
        value=value,
    )

    evt = bus.publish.call_args[0][0]
    assert evt["type"] == "cache_changed"
    assert evt["area_id"] == "alimentacion"
    assert evt["plc_name"] == "PLC_A"
    assert evt["data"] == [{"a": 1, "b": "a"}, {"a": 2, "b": "b"}]
    # Y JSON.dumps del evento completo funciona (el bug original
    # exacto era aqui: el gen SSE revienta al serializar el value).
    json.dumps(evt)


def test_cache_changed_publisher_preserva_primitivos() -> None:
    """Los publishers anteriores pasaban ``str``/``dict``; siguen igual."""
    cache = AppCache()
    bus = MagicMock()
    make_cache_change_publisher(bus, cache)

    _invoke_cache_change(
        cache, slot="selected_plc", area_id=None, plc_name=None,
        value="PLC_X",
    )
    evt = bus.publish.call_args[0][0]
    assert evt["data"] == "PLC_X"


def test_cache_changed_publisher_preserva_dict_simple() -> None:
    """``value`` = dict plano: pasa sin conversion estructural."""
    cache = AppCache()
    bus = MagicMock()
    make_cache_change_publisher(bus, cache)

    _invoke_cache_change(
        cache, slot="preview_disp", area_id="alimentacion", plc_name=None,
        value={"ok": True},
    )
    evt = bus.publish.call_args[0][0]
    assert evt["data"] == {"ok": True}


# ─────────────────────────────────────────────────────────────────────
# make_fb_state_publisher — normaliza result
# ─────────────────────────────────────────────────────────────────────


def test_fb_state_publisher_normaliza_result_dataclass() -> None:
    """``fb.result`` puede ser un dataclass: el publisher lo aplana.

    Misma clase de bug que en ``cache_changed``: si el FB termina
    con un dataclass en ``self.result``, json.dumps del SSE
    revienta. El helper ``to_jsonable`` lo aplana via ``asdict``.
    """
    bus = EventBusSync()
    engine = MagicMock()
    sub = bus.subscribe()  # nos suscribimos ANTES de publicar

    pub = make_fb_state_publisher(bus, engine)

    fake_fb = MagicMock()
    fake_fb.nStep = 5
    fake_fb.is_terminal.return_value = True
    fake_fb.result = _FakeDC(99, "r")
    fake_fb.error_msg = None

    pub("subir_excel", fake_fb)

    evt = sub.get_nowait()
    assert evt["type"] == "fb_state"
    assert evt["name"] == "subir_excel"
    assert evt["nStep"] == 5
    assert evt["is_terminal"] is True
    assert evt["result"] == {"a": 99, "b": "r"}
    assert not isinstance(evt["result"], _FakeDC)
    json.dumps(evt)


def test_fb_state_publisher_result_primitivo_se_preserva() -> None:
    """``fb.result`` primitivo pasa sin cambio."""
    bus = EventBusSync()
    engine = MagicMock()
    sub = bus.subscribe()

    pub = make_fb_state_publisher(bus, engine)

    fake_fb = MagicMock()
    fake_fb.nStep = 1
    fake_fb.is_terminal.return_value = False
    fake_fb.result = "ok"
    fake_fb.error_msg = None

    pub("subir_excel", fake_fb)

    evt = sub.get_nowait()
    assert evt["result"] == "ok"