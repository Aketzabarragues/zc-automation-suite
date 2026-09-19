"""Tests del helper ``proc_generar_preview``.

Cubre las 5 funciones puras/async del helper:
  - ``proc_check_state``        -> excel_loaded.
  - ``proc_check_blocks``       -> bloques_loaded.
  - ``proc_build_slot_maps``    -> ctx.slot_map (o slot_map_error).
  - ``proc_compute_nmax``       -> ctx.nmax_block.
  - ``proc_export_and_diff``    -> ctx.{preal,pint,alm}_current (o export_error).
  - ``proc_compose_response``   -> ctx.result (shape legacy).

Cada test mockea ``app_state``, ``config_manager``, ``tia_client`` y
``bloques_cache`` con ``MagicMock`` y valida que el ``ctx`` queda en
el estado esperado tras cada llamada.

Restricciones:
  - NO toca el gateway TIA real.
  - NO toca el sistema de archivos (no se exportan DBs reales).
  - El helper es **libre de state machine**: cada test llama a UNA
    funcion del helper por vez y valida el efecto en el ``ctx``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from areas.alimentacion.helpers.proc.proc_generar_preview import (
    ProcPreviewContext,
    proc_check_blocks,
    proc_check_state,
    proc_build_slot_maps,
    proc_compose_response,
    proc_compute_nmax,
    proc_export_and_diff,
)


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_app_state() -> MagicMock:
    """AppState mockeado con ``excel_cache`` poblado."""
    state = MagicMock()
    state.excel_cache = MagicMock()  # no None -> excel cargado
    return state


@pytest.fixture
def mock_app_state_no_excel() -> MagicMock:
    """AppState mockeado SIN ``excel_cache``."""
    state = MagicMock()
    state.excel_cache = None
    return state


@pytest.fixture
def mock_config_manager() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_bloques_cache() -> MagicMock:
    """DataBloqueCache mockeado con plc_name."""
    cache = MagicMock()
    cache.plc_name = "S7-1500"
    return cache


@pytest.fixture
def mock_tia_client() -> MagicMock:
    """Gateway mockeado.

    El gateway real (``SyncTIAClient``) no expone ``export_block`` /
    ``export_plc_tags_xml`` como metodos directos, sino como comandos
    despachados via ``submit_and_wait(command, args, timeout_s)``. El
    helper wrapper compartido ``dispatch_async`` lo invoca con
    ``asyncio.to_thread``. Los tests mockean ``submit_and_wait``
    retornando dicts vacios (los comandos export_* no necesitan
    devolver nada util aqui).
    """
    client = MagicMock()
    client.submit_and_wait = MagicMock(
        return_value={"ok": True, "result": None}
    )
    return client


@pytest.fixture
def make_ctx(
    mock_app_state: MagicMock,
    mock_config_manager: MagicMock,
    mock_tia_client: MagicMock,
    mock_bloques_cache: MagicMock,
):
    """Factory de contextos de prueba con deps inyectadas."""
    def _make(**overrides: Any) -> ProcPreviewContext:
        defaults: dict[str, Any] = {
            "plc_name": "S7-1500",
            "proc_uid": 42,
            "tia_client": mock_tia_client,
            "config_manager": mock_config_manager,
            "app_state": mock_app_state,
            "build_cache_root": Path("/tmp/.build_cache"),
            "bloques_cache": mock_bloques_cache,
        }
        defaults.update(overrides)
        return ProcPreviewContext(**defaults)
    return _make


# ── Helpers para fake slot_map ───────────────────────────────────────


@dataclass
class FakeSlotMap:
    """Replica minima de ``DataProcSlotMap`` para tests."""

    preal: dict[int, str] = field(default_factory=dict)
    pint: dict[int, str] = field(default_factory=dict)
    alm: dict[int, str] = field(default_factory=dict)
    db_param_name: str = "DB42_CPR_PARAM"
    db_alm_name: str = "DB42_CPR_ALM"
    param_subpath: str = ""
    alm_subpath: str = ""
    table_name: str = "42_CPR"
    nmax_names: dict[str, str] = field(default_factory=dict)
    nmax: dict[str, int] = field(default_factory=dict)
    missing_blocks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    satellites_by_array: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: {
            "preal": ("PReal_Vis", "Aux.PReal_ValorAnterior"),
            "pint": ("PInt_Vis", "Aux.PInt_ValorAnterior"),
            "alm": (),
        }
    )


# ── proc_check_state ─────────────────────────────────────────────────


def test_check_state_ok(
    make_ctx: Any,
) -> None:
    """Excel cargado -> ctx.excel_loaded = True."""
    ctx = make_ctx()
    proc_check_state(ctx)
    assert ctx.excel_loaded is True


def test_check_state_no_excel(
    mock_app_state_no_excel: MagicMock,
    make_ctx: Any,
) -> None:
    """Sin excel_cache -> ctx.excel_loaded = False."""
    ctx = make_ctx(app_state=mock_app_state_no_excel)
    proc_check_state(ctx)
    assert ctx.excel_loaded is False


# ── proc_check_blocks ────────────────────────────────────────────────


def test_check_blocks_ok(
    make_ctx: Any,
) -> None:
    """bloques_cache presente -> ctx.bloques_loaded = True."""
    ctx = make_ctx()
    proc_check_blocks(ctx)
    assert ctx.bloques_loaded is True


def test_check_blocks_none(
    make_ctx: Any,
) -> None:
    """bloques_cache None -> ctx.bloques_loaded = False."""
    ctx = make_ctx(bloques_cache=None)
    proc_check_blocks(ctx)
    assert ctx.bloques_loaded is False


# ── proc_build_slot_maps ─────────────────────────────────────────────


def test_build_slot_maps_returns_slot_map(
    make_ctx: Any,
) -> None:
    """Happy path: devuelve un objeto slot_map valido en ctx.slot_map."""
    from unittest.mock import patch
    import areas.alimentacion.data.data_ProcSlotMap as data_mod

    fake_sm = FakeSlotMap(preal={1: "Bomba 1", 2: "Bomba 2"})
    # NOTA: el helper hace ``from data_ProcSlotMap import proc_build_slot_maps``
    # DENTRO de la funcion, por lo que parchear ``data_mod.proc_build_slot_maps``
    # propaga al re-import del helper.
    with patch.object(data_mod, "proc_build_slot_maps", return_value=fake_sm):
        ctx = make_ctx()
        proc_build_slot_maps(ctx)

    assert ctx.slot_map is fake_sm
    assert ctx.slot_map_error is None


def test_build_slot_maps_skips_when_excel_not_loaded(
    mock_app_state_no_excel: MagicMock,
    make_ctx: Any,
) -> None:
    """Sin Excel -> el helper skip, ctx queda limpio."""
    ctx = make_ctx(app_state=mock_app_state_no_excel)
    # Llamar check_state primero (patron del FB: validar antes de actuar).
    proc_check_state(ctx)
    assert ctx.excel_loaded is False
    proc_build_slot_maps(ctx)
    assert ctx.slot_map is None
    assert ctx.slot_map_error is None


def test_build_slot_maps_captures_runtime_error(
    make_ctx: Any,
) -> None:
    """proc_build_slot_maps lanza RuntimeError -> se captura en slot_map_error."""
    import areas.alimentacion.data.data_ProcSlotMap as data_mod
    from unittest.mock import patch

    with patch.object(
        data_mod, "proc_build_slot_maps",
        side_effect=RuntimeError("uid 42 no esta en el Excel"),
    ):
        ctx = make_ctx()
        proc_build_slot_maps(ctx)

    assert ctx.slot_map is None
    assert ctx.slot_map_error is not None
    assert "uid 42" in ctx.slot_map_error


# ── proc_compose_response ────────────────────────────────────────────


def test_compose_response_no_excel(
    mock_app_state_no_excel: MagicMock,
    make_ctx: Any,
) -> None:
    """Sin excel -> precondiciones_ok=False con hint de carga."""
    ctx = make_ctx(app_state=mock_app_state_no_excel)
    proc_check_state(ctx)
    proc_compose_response(ctx)

    assert ctx.result["precondiciones_ok"] is False
    assert len(ctx.result["missing_blocks"]) == 1
    assert "Excel" in ctx.result["missing_blocks"][0]
    assert ctx.result["arrays"] == {}
    assert ctx.result["summary"]["total"] == 0


def test_compose_response_no_bloques(
    make_ctx: Any,
) -> None:
    """Sin bloques -> precondiciones_ok=False con hint de escaneo."""
    ctx = make_ctx(bloques_cache=None)
    proc_check_state(ctx)
    proc_check_blocks(ctx)
    proc_compose_response(ctx)

    assert ctx.result["precondiciones_ok"] is False
    assert len(ctx.result["missing_blocks"]) == 1
    assert "escaneo" in ctx.result["missing_blocks"][0]


def test_compose_response_slot_map_error(
    make_ctx: Any,
) -> None:
    """slot_map_error poblado -> precondiciones_ok=False con el error."""
    import areas.alimentacion.data.data_ProcSlotMap as data_mod
    from unittest.mock import patch

    with patch.object(
        data_mod, "proc_build_slot_maps",
        side_effect=RuntimeError("uid invalido"),
    ):
        ctx = make_ctx()
        proc_check_state(ctx)
        proc_check_blocks(ctx)
        proc_build_slot_maps(ctx)
        proc_compose_response(ctx)

    assert ctx.result["precondiciones_ok"] is False
    assert "uid invalido" in ctx.result["missing_blocks"][0]


def test_compose_response_missing_blocks(
    make_ctx: Any,
) -> None:
    """slot_map.missing_blocks poblado -> precondiciones_ok=False con ellos."""
    import areas.alimentacion.data.data_ProcSlotMap as data_mod
    from unittest.mock import patch

    fake_sm = FakeSlotMap(
        missing_blocks=["DB42_CPR_PARAM no esta en el PLC"],
        warnings=["warning de prueba"],
    )
    with patch.object(data_mod, "proc_build_slot_maps", return_value=fake_sm):
        ctx = make_ctx()
        proc_check_state(ctx)
        proc_check_blocks(ctx)
        proc_build_slot_maps(ctx)
        proc_compose_response(ctx)

    assert ctx.result["precondiciones_ok"] is False
    assert "DB42_CPR_PARAM" in ctx.result["missing_blocks"][0]
    assert ctx.result["db_param_name"] == "DB42_CPR_PARAM"
    assert ctx.result["warnings"] == ["warning de prueba"]


def test_compose_response_happy_path(
    make_ctx: Any,
) -> None:
    """Happy path: precondiciones_ok=True con arrays + summary completos."""
    import areas.alimentacion.data.data_ProcSlotMap as data_mod
    from unittest.mock import patch

    fake_sm = FakeSlotMap(
        preal={1: "Bomba 1", 2: "Bomba 2"},
        pint={1: "Param 1"},
        alm={1: "Alarma 1"},
    )
    fake_current_preal = {1: "Bomba 1", 2: "Bomba OLD"}
    fake_current_pint = {1: "Param 1"}
    fake_current_alm = {1: "Alarma 1"}

    # Monkeypatch export + read_current_comments via ProcCommentUpdater
    with patch.object(data_mod, "proc_build_slot_maps", return_value=fake_sm):
        ctx = make_ctx()
        proc_check_state(ctx)
        proc_check_blocks(ctx)
        proc_build_slot_maps(ctx)
        # Compute nmax returns empty block by default (no nmax_names)
        import asyncio
        asyncio.run(proc_compute_nmax(ctx))
        # Export: simulamos que devuelve los 3 mapas.
        ctx.preal_current = fake_current_preal
        ctx.pint_current = fake_current_pint
        ctx.alm_current = fake_current_alm
        proc_compose_response(ctx)

    assert ctx.result["precondiciones_ok"] is True
    assert ctx.result["missing_blocks"] == []
    assert ctx.result["arrays"]["PReal"]["slot_map"]["1"]["action"] == "sin_cambios"
    assert ctx.result["arrays"]["PReal"]["slot_map"]["2"]["action"] == "renombrar"
    assert ctx.result["arrays"]["PInt"]["slot_map"]["1"]["action"] == "sin_cambios"
    assert ctx.result["arrays"]["ALM"]["slot_map"]["1"]["action"] == "sin_cambios"
    # Summary: 4 slots, 1 renombrar, 3 sin_cambios.
    assert ctx.result["summary"]["total"] == 4
    assert ctx.result["summary"]["renombrados"] == 1
    assert ctx.result["summary"]["sin_cambios"] == 3


def test_compose_response_export_error_adds_warning(
    make_ctx: Any,
) -> None:
    """Si export_and_diff fallo, el result incluye un warning extra."""
    import areas.alimentacion.data.data_ProcSlotMap as data_mod
    from unittest.mock import patch

    fake_sm = FakeSlotMap(
        preal={1: "Bomba 1"},
        pint={},
        alm={},
    )

    with patch.object(data_mod, "proc_build_slot_maps", return_value=fake_sm):
        ctx = make_ctx()
        proc_check_state(ctx)
        proc_check_blocks(ctx)
        proc_build_slot_maps(ctx)
        import asyncio
        asyncio.run(proc_compute_nmax(ctx))
        # Simulamos export fallido (current=None, export_error poblado).
        ctx.preal_current = None
        ctx.pint_current = None
        ctx.alm_current = None
        ctx.export_error = "TIA no responde"
        proc_compose_response(ctx)

    assert ctx.result["precondiciones_ok"] is True
    assert any(
        "Export fallo" in w and "TIA no responde" in w
        for w in ctx.result["warnings"]
    )
    # Como current=None, todos los slots del Excel con desired != "."
    # son "renombrar"; los "." serian "agregar".
    preal_slot_1 = ctx.result["arrays"]["PReal"]["slot_map"]["1"]
    assert preal_slot_1["current"] is None
    assert preal_slot_1["action"] == "renombrar"


# ── proc_compute_nmax ────────────────────────────────────────────────


def test_compute_nmax_no_slot_map(
    make_ctx: Any,
) -> None:
    """Sin slot_map -> nmax_block es empty (no aborta)."""
    import asyncio
    ctx = make_ctx()
    # slot_map es None por defecto.
    asyncio.run(proc_compute_nmax(ctx))
    assert ctx.nmax_block == {
        "current": {}, "desired": {}, "todos": [],
        "summary": {"actualizar": 0, "sin_cambios": 0, "total": 0},
    }


def test_compute_nmax_no_nmax_names(
    make_ctx: Any,
) -> None:
    """slot_map sin nmax_names -> nmax_block empty."""
    import asyncio
    from unittest.mock import patch
    import areas.alimentacion.data.data_ProcSlotMap as data_mod

    fake_sm = FakeSlotMap()  # nmax_names vacio por defecto
    with patch.object(data_mod, "proc_build_slot_maps", return_value=fake_sm):
        ctx = make_ctx()
        proc_build_slot_maps(ctx)
        asyncio.run(proc_compute_nmax(ctx))
    assert ctx.nmax_block["todos"] == []


# ── proc_export_and_diff ─────────────────────────────────────────────


def test_export_and_diff_skips_when_no_slot_map(
    make_ctx: Any,
) -> None:
    """Sin slot_map -> no llama a export_block ni tia_client."""
    import asyncio
    ctx = make_ctx()
    asyncio.run(proc_export_and_diff(ctx))
    ctx.tia_client.export_block.assert_not_called()
    assert ctx.export_error is None


def test_export_and_diff_handles_export_failure(
    make_ctx: Any,
) -> None:
    """Si ``dispatch_async`` lanza RuntimeError -> current=None + export_error poblado."""
    import asyncio
    from unittest.mock import patch
    import areas.alimentacion.data.data_ProcSlotMap as data_mod
    import areas.alimentacion.helpers.proc.proc_generar_preview as helper_mod
    from core.helpers.tia import dispatch_async as dispatch_mod

    fake_sm = FakeSlotMap(preal={1: "Bomba 1"})

    # ``dispatch_async`` falla para export_block -> modo degradado.
    async def bad_dispatch(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("TIA Portal no responde")

    with patch.object(data_mod, "proc_build_slot_maps", return_value=fake_sm), \
         patch.object(helper_mod, "dispatch_async", side_effect=bad_dispatch), \
         patch.object(dispatch_mod, "dispatch_async", side_effect=bad_dispatch):
        ctx = make_ctx()
        proc_build_slot_maps(ctx)
        asyncio.run(proc_export_and_diff(ctx))

    assert ctx.preal_current is None
    assert ctx.pint_current is None
    assert ctx.alm_current is None
    assert ctx.export_error is not None
    assert "TIA Portal no responde" in ctx.export_error
