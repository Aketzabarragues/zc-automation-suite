"""Tests de ``core.infrastructure.tia.tia_cache``.

Cubre:
  - ``plc_blocks_put`` + ``plc_blocks_get`` roundtrip keyed por plc_name.
  - ``plc_blocks_clear`` con y sin ``plc_name``.
  - ``plc_blocks_list``.
  - ``on_plc_change`` invalida el PLC previo.
  - ``scan_plc_blocks`` integration con worker TIA mockeado.
  - ``slot="plc_blocks"`` en cada mutacion (dispara ``on_change``).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from core.data.data_block_cache import DataBloqueCache
from core.infrastructure.tia.tia_cache import (
    on_plc_change,
    plc_blocks_clear,
    plc_blocks_get,
    plc_blocks_list,
    plc_blocks_put,
    scan_plc_blocks,
)
from core.runtime.app_cache import AppCache


@pytest.fixture
def cache() -> AppCache:
    return AppCache()


def _make_blocks(plc: str, n: int = 1) -> DataBloqueCache:
    return DataBloqueCache(
        plc_name=plc,
        blocks={},
        tag_tables={},
        udts={},
        scanned_at=datetime(2026, 9, 1),
    )


# ── plc_blocks_put / get / list ───────────────────────────────────────


def test_put_get_roundtrip(cache: AppCache) -> None:
    """``put`` + ``get`` recuperan el mismo cache para ``plc_name``."""
    bloques = _make_blocks("S7-1500")
    plc_blocks_put(cache, "S7-1500", bloques)
    assert plc_blocks_get(cache, "S7-1500") is bloques
    assert plc_blocks_get(cache, "OTHER") is None
    assert "S7-1500" in plc_blocks_list(cache)


# ── plc_blocks_clear ──────────────────────────────────────────────────


def test_clear_all_vacia_todos_los_plcs(cache: AppCache) -> None:
    """``clear()`` con ``plc_name=None`` borra TODOS los PLCs."""
    plc_blocks_put(cache, "A", _make_blocks("A"))
    plc_blocks_put(cache, "B", _make_blocks("B"))
    plc_blocks_clear(cache)
    assert plc_blocks_list(cache) == []


def test_clear_solo_un_plc(cache: AppCache) -> None:
    """``clear(plc_name="A")`` borra solo el de A, no el resto."""
    plc_blocks_put(cache, "A", _make_blocks("A"))
    plc_blocks_put(cache, "B", _make_blocks("B"))
    plc_blocks_clear(cache, "A")
    assert plc_blocks_get(cache, "A") is None
    assert plc_blocks_get(cache, "B") is not None


def test_clear_plc_inexistente_es_noop(cache: AppCache) -> None:
    """``clear(plc_name="X")`` sin entry previa: no falla."""
    plc_blocks_clear(cache, "X")  # no raise


# ── on_plc_change ─────────────────────────────────────────────────────


def test_on_plc_change_invalida_old(cache: AppCache) -> None:
    """Cambiar de PLC invalida el cache del previo."""
    plc_blocks_put(cache, "A", _make_blocks("A"))
    on_plc_change(cache, "A", "B")
    assert plc_blocks_get(cache, "A") is None


def test_on_plc_change_mismo_plc_no_hace_nada(cache: AppCache) -> None:
    """Re-seleccionar el mismo PLC no invalida."""
    plc_blocks_put(cache, "A", _make_blocks("A"))
    on_plc_change(cache, "A", "A")
    assert plc_blocks_get(cache, "A") is not None


# ── slot= emite on_change ─────────────────────────────────────────────


def test_plc_blocks_put_emite_on_change_con_slot(cache: AppCache) -> None:
    """``plc_blocks_put`` dispara ``on_change(slot="plc_blocks")``."""
    captured: list[tuple[str, str | None, str | None, object]] = []

    def cb(slot, area_id, plc_name, value):
        captured.append((slot, area_id, plc_name, value))

    cache.on_change(cb)
    try:
        plc_blocks_put(cache, "S7-1500", _make_blocks("S7-1500"))
    finally:
        cache.on_change(None)

    assert len(captured) == 1
    slot, area_id, plc_name, value = captured[0]
    assert slot == "plc_blocks"
    assert area_id is None  # slot global
    assert plc_name is None  # slot global
    assert "S7-1500" in value  # type: ignore[operator]


def test_plc_blocks_clear_all_emite_on_change_con_slot(
    cache: AppCache,
) -> None:
    """``clear()`` (all) dispara ``on_change(slot="plc_blocks")``."""
    plc_blocks_put(cache, "A", _make_blocks("A"))

    captured: list[tuple[str, str | None, str | None, object]] = []

    def cb(slot, area_id, plc_name, value):
        captured.append((slot, area_id, plc_name, value))

    cache.on_change(cb)
    try:
        plc_blocks_clear(cache)
    finally:
        cache.on_change(None)

    assert any(c[0] == "plc_blocks" for c in captured)


def test_plc_blocks_clear_un_plc_emite_on_change_con_slot(
    cache: AppCache,
) -> None:
    """``clear(plc_name="A")`` dispara ``on_change(slot="plc_blocks")``."""
    plc_blocks_put(cache, "A", _make_blocks("A"))

    captured: list[tuple[str, str | None, str | None, object]] = []

    def cb(slot, area_id, plc_name, value):
        captured.append((slot, area_id, plc_name, value))

    cache.on_change(cb)
    try:
        plc_blocks_clear(cache, "A")
    finally:
        cache.on_change(None)

    assert any(c[0] == "plc_blocks" for c in captured)


# ── scan_plc_blocks (integration) ─────────────────────────────────────


def test_scan_plc_blocks_llama_worker_y_puebla_cache(
    cache: AppCache,
) -> None:
    """``scan_plc_blocks`` despacha ``scan_blocks`` al worker y almacena el resultado."""
    fake_resp = {
        "ok": True,
        "result": {
            "plc_name": "S7-1500",
            "blocks": [],
            "tag_tables": [],
            "udts": [],
            "scanned_at": datetime(2026, 9, 1).isoformat(),
        },
    }
    fake_client = MagicMock()
    fake_client.submit_and_wait.return_value = fake_resp

    with patch(
        "core.infrastructure.tia.tia_loop.tia_client",
        fake_client,
    ):
        result = scan_plc_blocks(
            "S7-1500",
            tia_client=fake_client,
            app_cache=cache,
        )

    assert result.plc_name == "S7-1500"
    assert plc_blocks_get(cache, "S7-1500") is result
    fake_client.submit_and_wait.assert_called_once()
    call_args = fake_client.submit_and_wait.call_args
    assert call_args[0][0] == "scan_blocks"
    assert call_args[0][1] == {"plc_name": "S7-1500"}


def _scan_ok(plc: str = "S7-1500") -> dict:
    """Respuesta OK del comando ``scan_blocks``."""
    return {
        "ok": True,
        "result": {
            "plc_name": plc,
            "blocks": [],
            "tag_tables": [],
            "udts": [],
            "scanned_at": datetime(2026, 9, 1).isoformat(),
        },
    }


def test_scan_plc_blocks_fuerza_refresh_mantiene_la_cache_durante_el_scan(
    cache: AppCache,
) -> None:
    """``force_refresh=True`` NO vacia la entry antes de escanear.

    El scan tarda 15-26 s en un PLC grande. Invalidar antes dejaria
    al HMI sin arbol de bloques durante todo el scan ("Cache no
    disponible").
    """
    anterior = _make_blocks("S7-1500")
    plc_blocks_put(cache, "S7-1500", anterior)

    visto_durante: dict[str, object] = {}

    def _submit(*args, **kwargs):
        # Estado de la cache en el momento en que el worker escanea.
        visto_durante["valor"] = plc_blocks_get(cache, "S7-1500")
        return _scan_ok()

    fake_client = MagicMock()
    fake_client.submit_and_wait.side_effect = _submit

    with patch(
        "core.infrastructure.tia.tia_loop.tia_client",
        fake_client,
    ):
        scan_plc_blocks(
            "S7-1500",
            force_refresh=True,
            tia_client=fake_client,
            app_cache=cache,
        )

    # Durante el scan la entry anterior seguia visible.
    assert visto_durante["valor"] is anterior
    # Y al terminar la entry es la nueva.
    fresh = plc_blocks_get(cache, "S7-1500")
    assert fresh is not None
    assert fresh.plc_name == "S7-1500"
    assert fresh is not anterior


def test_scan_plc_blocks_fuerza_refresh_invalida_si_el_scan_lanza(
    cache: AppCache,
) -> None:
    """Si el scan lanza excepcion, la entry se invalida.

    Datos viejos son peores que no tener datos: tras un apply, el
    nombre del bloque en TIA ya cambio y la cache vieja mentiria.
    """
    plc_blocks_put(cache, "S7-1500", _make_blocks("S7-1500"))
    fake_client = MagicMock()
    fake_client.submit_and_wait.side_effect = RuntimeError("timeout del worker")

    with patch(
        "core.infrastructure.tia.tia_loop.tia_client",
        fake_client,
    ):
        with pytest.raises(RuntimeError, match="timeout del worker"):
            scan_plc_blocks(
                "S7-1500",
                force_refresh=True,
                tia_client=fake_client,
                app_cache=cache,
            )

    assert plc_blocks_get(cache, "S7-1500") is None


def test_scan_plc_blocks_fuerza_refresh_invalida_si_la_respuesta_falla(
    cache: AppCache,
) -> None:
    """Si el worker responde ``ok=False``, la entry se invalida."""
    plc_blocks_put(cache, "S7-1500", _make_blocks("S7-1500"))
    fake_client = MagicMock()
    fake_client.submit_and_wait.return_value = {
        "ok": False,
        "error": "TIA Portal no responde",
    }

    with patch(
        "core.infrastructure.tia.tia_loop.tia_client",
        fake_client,
    ):
        with pytest.raises(RuntimeError, match="TIA Portal no responde"):
            scan_plc_blocks(
                "S7-1500",
                force_refresh=True,
                tia_client=fake_client,
                app_cache=cache,
            )

    assert plc_blocks_get(cache, "S7-1500") is None


def test_scan_plc_blocks_sin_force_refresh_conserva_la_cache_si_falla(
    cache: AppCache,
) -> None:
    """Sin ``force_refresh`` un scan fallido NO invalida la entry.

    El refresco opportunistico no puede dejar al operario sin datos
    que ya tenia: solo el ``force_refresh`` (apply) asume que lo
    anterior quedo obsoleto.
    """
    anterior = _make_blocks("S7-1500")
    plc_blocks_put(cache, "S7-1500", anterior)
    fake_client = MagicMock()
    fake_client.submit_and_wait.return_value = {
        "ok": False,
        "error": "TIA Portal no responde",
    }

    with patch(
        "core.infrastructure.tia.tia_loop.tia_client",
        fake_client,
    ):
        with pytest.raises(RuntimeError, match="TIA Portal no responde"):
            scan_plc_blocks(
                "S7-1500",
                tia_client=fake_client,
                app_cache=cache,
            )

    assert plc_blocks_get(cache, "S7-1500") is anterior


def test_scan_plc_blocks_worker_falla_lanza_runtime_error(
    cache: AppCache,
) -> None:
    """Si el worker responde ``ok=False``, ``RuntimeError`` accionable."""
    fake_client = MagicMock()
    fake_client.submit_and_wait.return_value = {
        "ok": False,
        "error": "TIA Portal no responde",
    }

    with patch(
        "core.infrastructure.tia.tia_loop.tia_client",
        fake_client,
    ):
        with pytest.raises(RuntimeError, match="TIA Portal no responde"):
            scan_plc_blocks(
                "S7-1500",
                tia_client=fake_client,
                app_cache=cache,
            )
