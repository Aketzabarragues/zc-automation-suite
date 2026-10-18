"""Tests del FB core ``FunctionBlockEditPrepare``.

Cubre:

  - Happy path: 3 bloques -> 5 steps (validar, leer_tia, exportar_sd,
    parsear_scl, merge_cache) -> ``app_cache.block_edit_prepared`` con
    3 entries y los 10 campos del DTO ``DataBloquePLC``.
  - Seleccion vacia -> ``ValueError`` fail-fast en ``on_start``.
  - ``get_property`` lanza para 1 bloque -> los otros 2 entran al
    cache, el bloque afectado NO (warning en logger).
  - ``export_block`` retorna ``ok=False`` para 1 bloque -> ese bloque
    queda con ``title=None, comment=None``; los otros 2 mantienen
    title/comment parseados del SCL.
  - ``tia_client.wrapper = None`` -> ``run_step`` propaga
    ``RuntimeError``.
  - ``tia_client = None`` -> ``run_step`` propaga ``RuntimeError``.

Mockeamos:

  - ``tia_client`` con ``MagicMock(spec=SyncTIAClient)``. Su ``wrapper``
    expone ``get_project()`` -> mock_project -> ``get_plcs()`` ->
    ``mock_plc`` -> ``get_program_blocks()`` -> 3 ``mock_block``.
  - ``dispatch`` retorna ``{"ok": True, "result": {"exported_to": ...}}``
    para ``export_block`` y ``{"ok": False, "error": "..."}`` en los
    sad paths.

Usamos ``AppCache`` real (no ``MagicMock``) para que el FB pueda
adjuntar el slot ``block_edit_prepared`` sin restricciones de spec.

El progress tracker es real (``ProgressTracker()``) para verificar
que el flujo de stages dispara las señales correctas.
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.composition.function_block_edit_prepare import (
    FunctionBlockEditPrepare,
)
from core.data.data_block_plc import DataBloquePLC
from core.infrastructure.tia.tia_loop import SyncTIAClient
from core.runtime.app_cache import AppCache
from core.runtime.progress_buffer import ProgressTracker

FIXTURES_BLOQUES = Path(__file__).resolve().parent.parent.parent / "fixtures" / "source" / "Bloques"


# ── Helpers ─────────────────────────────────────────────────────────


def _make_block_mock(
    name: str,
    number: int,
    header_name: str = "",
    header_author: str = "",
    header_version: str = "0.1",
    programming_language: str = "SCL",
    memory_layout: str = "Optimized",
    raise_on_property: str | None = None,
) -> MagicMock:
    """Mock de ``ProgramBlock`` con props extendidas configurables."""
    block = MagicMock()
    block.name = name
    block.Name = name
    block.get_name.return_value = name

    def _prop(name: str) -> Any:
        if raise_on_property and name == raise_on_property:
            raise RuntimeError(f"{name} no soportado")
        return {
            "Number": number,
            "HeaderName": header_name,
            "HeaderAuthor": header_author,
            "HeaderVersion": header_version,
            "ProgrammingLanguage": programming_language,
            "MemoryLayout": memory_layout,
        }.get(name)

    block.get_property.side_effect = _prop
    return block


def _make_tia_client_with_blocks(
    plc_name: str,
    blocks: list[MagicMock],
    export_dispatch: Any | None = None,
) -> MagicMock:
    """Mock de ``SyncTIAClient`` con wrapper y dispatch configurados."""
    tia_client = MagicMock(spec=SyncTIAClient)
    mock_project = MagicMock()
    mock_plc = MagicMock()
    mock_plc.get_name.return_value = plc_name
    mock_plc.get_program_blocks.return_value = blocks
    mock_project.get_plcs.return_value = [mock_plc]
    tia_client.wrapper.get_project.return_value = mock_project
    tia_client.dispatch.side_effect = (
        export_dispatch
        if export_dispatch is not None
        else lambda cmd, args: {
            "ok": True,
            "result": {"exported_to": args.get("target_dir", "")},
        }
    )
    return tia_client


def _copy_s7dcl(block_name: str, dst_dir: Path) -> Path:
    """Copia el ``.s7dcl`` del fixture al ``dst_dir``. Devuelve destino."""
    src = FIXTURES_BLOQUES / f"{block_name}.s7dcl"
    dst = dst_dir / f"{block_name}.s7dcl"
    shutil.copy(src, dst)
    return dst


@pytest.fixture
def real_progress() -> ProgressTracker:
    """ProgressTracker real (no MagicMock)."""
    return ProgressTracker()


@pytest.fixture
def app_cache() -> AppCache:
    """AppCache real: el FB le adjunta ``block_edit_prepared``."""
    return AppCache()


def _make_fb(
    app_cache: AppCache,
    tia_client: MagicMock | None,
    progress: ProgressTracker,
) -> FunctionBlockEditPrepare:
    return FunctionBlockEditPrepare(
        nombre="block_edit_prepare",
        tia_client=tia_client,
        app_cache=app_cache,
        tracker=progress,
    )


# ── 1. Happy path ──────────────────────────────────────────────────


def test_block_edit_prepare_happy_path_3_bloques(
    app_cache: AppCache,
    real_progress: ProgressTracker,
    tmp_path: Path,
) -> None:
    """3 bloques a root -> 5 steps -> 3 DTOs con 10 campos poblados."""
    blocks = [
        _make_block_mock("DB2000_ED", 2000, "title_db", "HCR", "1.0", "SCL", "Optimized"),
        _make_block_mock("FC2000_ZC_ED", 2000, "title_fc", "HCR", "1.0", "SCL", "Optimized"),
        _make_block_mock("OB1_MAIN", 1, "title_ob", "ABH", "0.1", "LAD", "Standard"),
    ]
    tia_client = _make_tia_client_with_blocks("PLC_1", blocks)
    fb = _make_fb(app_cache, tia_client, real_progress)

    # El export handler mock escribe a tmp_path con el nombre del bloque.
    def _export_dispatch(cmd: str, args: dict) -> dict:
        target = Path(args["target_dir"])
        src = FIXTURES_BLOQUES / f"{args['block_name']}.s7dcl"
        shutil.copy(src, target / f"{args['block_name']}.s7dcl")
        return {"ok": True, "result": {"exported_to": str(target)}}

    tia_client.dispatch.side_effect = _export_dispatch

    selected = ["DB2000_ED", "FC2000_ZC_ED", "OB1_MAIN"]
    ok = asyncio.run(fb.start(plc_name="PLC_1", selected_block_paths=selected))
    assert ok is True

    # Ejecuta los 5 steps (1 arrancar + 5 steps + 1 finalizar = 7 ticks).
    for tick_idx in range(7):
        asyncio.run(fb.tick())
        assert fb.nStep in (
            fb.n_arrancar, fb.n_ejecutar, fb.n_finalizar, fb.n_done,
        ), f"tick #{tick_idx + 1} salio del loop: nStep={fb.nStep}"

    assert fb.nStep == fb.n_done
    assert fb.is_terminal() is True
    assert fb.error_msg is None

    # Result con la shape de prepare.
    assert fb.result is not None
    assert fb.result["ok"] is True
    assert fb.result["plc_name"] == "PLC_1"
    assert fb.result["n_blocks"] == 3

    # Cache con los 3 bloques.
    assert "PLC_1" in app_cache.block_edit_prepared
    cached = app_cache.block_edit_prepared["PLC_1"]
    assert len(cached) == 3

    # Cada DTO con los 10 campos poblados.
    # OB1_MAIN no tiene S7_BlockComment en su header SCL (es valido).
    has_comment = {"DB2000_ED", "FC2000_ZC_ED"}
    for path in selected:
        dto = cached[path]
        assert isinstance(dto, DataBloquePLC)
        d = dto.to_dict()
        assert d["nombre"] in ("DB2000_ED", "FC2000_ZC_ED", "OB1_MAIN")
        assert d["ruta"] == path
        assert d["tipo"] in ("DB", "FC", "OB")
        assert d["title"] is not None  # del SCL (todos tienen S7_BlockTitle)
        if path in has_comment:
            assert d["comment"] is not None
        assert d["author"] in ("HCR", "ABH")
        assert d["version"] in ("1.0", "0.1")
        assert d["programming_language"] in ("SCL", "LAD")
        assert d["memory_layout"] in ("Optimized", "Standard")


# ── 2. Seleccion vacia -> ValueError ────────────────────────────────


def test_block_edit_prepare_empty_selection_raises_value_error(
    app_cache: AppCache,
    real_progress: ProgressTracker,
) -> None:
    """``selected_block_paths=[]`` -> ``on_start`` lanza ValueError.

    El primer ``tick()`` captura el raise y pone el FB en ``n_error``
    con ``error_msg`` poblado (patrón ``FunctionBase``).
    """
    tia_client = _make_tia_client_with_blocks("PLC_1", [])
    fb = _make_fb(app_cache, tia_client, real_progress)

    asyncio.run(fb.start(plc_name="PLC_1", selected_block_paths=[]))
    asyncio.run(fb.tick())

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "selected_block_paths" in fb.error_msg


# ── 3. get_property raise para 1 bloque ─────────────────────────────


def test_block_edit_prepare_get_property_raises_continues_with_others(
    app_cache: AppCache,
    real_progress: ProgressTracker,
    tmp_path: Path,
) -> None:
    """El bloque con ``get_property`` raise se skipea; los otros 2 pasan."""
    blocks = [
        _make_block_mock("DB2000_ED", 2000, "title_db", "HCR", "1.0", "SCL", "Optimized"),
        # Bloque del medio: ``HeaderAuthor`` lanza.
        _make_block_mock(
            "FC2000_ZC_ED", 2000, "title_fc", "HCR", "1.0", "SCL", "Optimized",
            raise_on_property="HeaderAuthor",
        ),
        _make_block_mock("OB1_MAIN", 1, "title_ob", "ABH", "0.1", "LAD", "Standard"),
    ]
    tia_client = _make_tia_client_with_blocks("PLC_1", blocks)

    def _export_dispatch(cmd: str, args: dict) -> dict:
        target = Path(args["target_dir"])
        src = FIXTURES_BLOQUES / f"{args['block_name']}.s7dcl"
        shutil.copy(src, target / f"{args['block_name']}.s7dcl")
        return {"ok": True, "result": {"exported_to": str(target)}}

    tia_client.dispatch.side_effect = _export_dispatch
    fb = _make_fb(app_cache, tia_client, real_progress)

    selected = ["DB2000_ED", "FC2000_ZC_ED", "OB1_MAIN"]
    asyncio.run(fb.start(plc_name="PLC_1", selected_block_paths=selected))

    for _ in range(7):
        asyncio.run(fb.tick())

    assert fb.nStep == fb.n_done
    cached = app_cache.block_edit_prepared["PLC_1"]
    # El bloque del medio NO entra al cache (fallo en leer_tia).
    assert "FC2000_ZC_ED" not in cached
    assert "DB2000_ED" in cached
    assert "OB1_MAIN" in cached
    assert len(cached) == 2


# ── 4. export_block falla para 1 bloque ────────────────────────────


def test_block_edit_prepare_export_raises_continues_with_others(
    app_cache: AppCache,
    real_progress: ProgressTracker,
    tmp_path: Path,
) -> None:
    """``export_block`` retorna ``ok=False`` para FC: queda sin title/comment."""
    blocks = [
        _make_block_mock("DB2000_ED", 2000, "title_db", "HCR", "1.0", "SCL", "Optimized"),
        _make_block_mock("FC2000_ZC_ED", 2000, "title_fc", "HCR", "1.0", "SCL", "Optimized"),
        _make_block_mock("OB1_MAIN", 1, "title_ob", "ABH", "0.1", "LAD", "Standard"),
    ]
    tia_client = _make_tia_client_with_blocks("PLC_1", blocks)

    fail_targets = {"FC2000_ZC_ED"}

    def _export_dispatch(cmd: str, args: dict) -> dict:
        target = Path(args["target_dir"])
        bname = args["block_name"]
        if bname in fail_targets:
            return {"ok": False, "error": "TIA no responde"}
        src = FIXTURES_BLOQUES / f"{bname}.s7dcl"
        shutil.copy(src, target / f"{bname}.s7dcl")
        return {"ok": True, "result": {"exported_to": str(target)}}

    tia_client.dispatch.side_effect = _export_dispatch
    fb = _make_fb(app_cache, tia_client, real_progress)

    selected = ["DB2000_ED", "FC2000_ZC_ED", "OB1_MAIN"]
    asyncio.run(fb.start(plc_name="PLC_1", selected_block_paths=selected))

    for _ in range(7):
        asyncio.run(fb.tick())

    assert fb.nStep == fb.n_done
    cached = app_cache.block_edit_prepared["PLC_1"]

    # DB y OB mantienen title/comment del SCL.
    db_dto = cached["DB2000_ED"]
    assert db_dto.title is not None
    assert db_dto.comment is not None
    ob_dto = cached["OB1_MAIN"]
    # OB1_MAIN no tiene S7_BlockComment en su SCL (es valido).
    assert ob_dto.title is not None
    assert ob_dto.comment is None

    # FC queda con title=None y comment=None (no se parseo SCL).
    fc_dto = cached["FC2000_ZC_ED"]
    assert fc_dto.title is None
    assert fc_dto.comment is None
    # El resto de campos extendidos (vía get_property) sí están.
    assert fc_dto.author == "HCR"
    assert fc_dto.version == "1.0"
    assert fc_dto.programming_language == "SCL"
    assert fc_dto.memory_layout == "Optimized"


# ── 5. wrapper=None -> RuntimeError ────────────────────────────────


def test_block_edit_prepare_missing_portal_raises(
    app_cache: AppCache,
    real_progress: ProgressTracker,
) -> None:
    """``tia_client.wrapper = None`` -> ``run_step`` propaga RuntimeError.

    El FB llega a ``n_error`` con ``error_msg`` mencionando "portal attached".
    """
    tia_client = MagicMock(spec=SyncTIAClient)
    tia_client.wrapper = None  # Explicitly None.
    fb = _make_fb(app_cache, tia_client, real_progress)

    asyncio.run(fb.start(
        plc_name="PLC_1",
        selected_block_paths=["DB2000_ED"],
    ))

    # tick #1: arrancar -> ejecutar (on_start OK).
    asyncio.run(fb.tick())
    assert fb.nStep == fb.n_ejecutar

    # tick #2: leer_tia valida wrapper y lanza RuntimeError.
    asyncio.run(fb.tick())

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "portal attached" in fb.error_msg


# ── 6. tia_client=None -> RuntimeError ─────────────────────────────


def test_block_edit_prepare_tia_client_required(
    app_cache: AppCache,
    real_progress: ProgressTracker,
) -> None:
    """``tia_client = None`` -> ``run_step`` propaga RuntimeError.

    El FB llega a ``n_error`` con ``error_msg`` mencionando "requiere tia_client".
    """
    fb = _make_fb(app_cache, None, real_progress)

    asyncio.run(fb.start(
        plc_name="PLC_1",
        selected_block_paths=["DB2000_ED"],
    ))

    # tick #1: arrancar -> ejecutar (on_start OK).
    asyncio.run(fb.tick())
    assert fb.nStep == fb.n_ejecutar

    # tick #2: leer_tia valida tia_client y lanza RuntimeError.
    asyncio.run(fb.tick())

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "requiere tia_client" in fb.error_msg