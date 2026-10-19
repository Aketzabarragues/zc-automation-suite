"""Tests del FB core ``FunctionBlockEditPrepare``.

Cubre:

  - Happy path: 3 bloques pre-poblados en ``app_cache.plc_blocks`` -> 5
    steps -> 3 DTOs con los 10 campos del DTO ``DataBloquePLC`` en
    ``app_cache.block_edit_prepared``.
  - Seleccion vacia -> ``ValueError`` fail-fast en ``on_start``.
  - Bloque seleccionado no esta en ``plc_blocks.blocks`` -> skip con
    warning, dispatch NO se llama, merge con 0 entries.
  - PLC sin cache (``plc_blocks`` no tiene el plc_name) -> ``RuntimeError``
    fail-fast en ``leer_tia``.
  - ``export_block`` retorna ``ok=False`` para 1 bloque -> ese bloque
    queda con ``title=None, comment=None``; los otros 2 mantienen
    title/comment parseados del SCL.
  - Inyeccion de ``layout=BlocksEditLayout(root=tmp_path)`` -> los
    exports SD van a ``tmp_path/preview/`` (plano, sin subdir por PLC).
  - El ``target_dir`` pasado a ``dispatch`` es un path absoluto (no
    contiene ``..`` ni empieza con ``./``).

Mockeamos:

  - ``tia_client`` con ``MagicMock(spec=SyncTIAClient)``. Su ``dispatch``
    retorna ``{"ok": True}`` o ``{"ok": False}`` segun el test. NO se
    accede a ``wrapper`` (el FB no navega el arbol TIA).
  - ``app_cache`` es un ``AppCache`` real con ``plc_blocks[plc_name]``
    pre-poblado via ``plc_blocks_put`` (mismo patron que usa el worker
    OT tras un ``scan_blocks``).

El progress tracker es real (``ProgressTracker()``) para verificar que
el flujo de stages dispara las señales correctas.
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
from core.data.data_block_cache import DataBloqueCache
from core.data.data_block_plc import DataBloquePLC
from core.helpers.blocks_edit._workdir_layout import BlocksEditLayout
from core.infrastructure.tia.tia_cache import plc_blocks_put
from core.infrastructure.tia.tia_loop import SyncTIAClient
from core.runtime.app_cache import AppCache
from core.runtime.progress_buffer import ProgressTracker

FIXTURES_BLOQUES = Path(__file__).resolve().parent.parent.parent / "fixtures" / "source" / "Bloques"


# ── Helpers ─────────────────────────────────────────────────────────


def _make_cached_dto(
    name: str,
    number: int,
    tipo: str = "DB",
    ruta: str = "",
    author: str | None = "HCR",
    version: str | None = "1.0",
    programming_language: str | None = "SCL",
    memory_layout: str | None = "Optimized",
) -> DataBloquePLC:
    """DTO pre-poblado simulando lo que ``scan_blocks`` dejaria en el cache.

    ``comment`` siempre ``None`` (el scan no lo expone); ``title`` queda
    ``None`` tambien para que el parser SCL sea quien lo popule. Las otras
    4 props extendidas ya vienen del scan (via ``_extract_extended_properties``).
    """
    return DataBloquePLC(
        nombre=name,
        numero=number,
        tipo=tipo,
        ruta=ruta,
        title=None,
        comment=None,
        author=author,
        version=version,
        programming_language=programming_language,
        memory_layout=memory_layout,
    )


def _seed_plc_blocks(
    app_cache: AppCache,
    plc_name: str,
    blocks: list[DataBloquePLC],
) -> DataBloqueCache:
    """Pre-popula ``app_cache.plc_blocks[plc_name]`` con la lista de DTOs.

    Mismo patron que ``scan_plc_blocks`` despues de un escaneo: delega
    en ``plc_blocks_put`` para que el slot se actualice de forma atomica
    bajo el lock del ``AppCache``.
    """
    cache = DataBloqueCache(
        plc_name=plc_name,
        blocks={
            DataBloquePLC.normalize_name(b.nombre): b for b in blocks
        },
    )
    plc_blocks_put(app_cache, plc_name, cache)
    return cache


def _make_tia_client(
    export_dispatch: Any | None = None,
) -> MagicMock:
    """Mock de ``SyncTIAClient`` con ``dispatch`` configurable.

    El default simula el handler unificado ``export_blocks`` (FASE 2.6):
    retorna ``exported_names`` con los nombres pasados en ``block_names``
    para que el FB prepare pueda resolver ``sd_path`` por cada bloque.
    """
    tia_client = MagicMock(spec=SyncTIAClient)
    tia_client.dispatch.side_effect = (
        export_dispatch
        if export_dispatch is not None
        else lambda cmd, args: {
            "ok": True,
            "result": {
                "exported_to": args.get("target_dir", ""),
                "count": len(args.get("block_names", [])),
                "exported_names": list(args.get("block_names", [])),
                "skipped_names": [],
            },
        }
    )
    return tia_client


def _copy_s7dcl_export(cmd: str, args: dict[str, Any]) -> dict:
    """Dispatch que materializa el ``.s7dcl`` del fixture en ``target_dir``.

    Simula al handler unificado ``export_blocks`` (FASE 2.6): dado
    ``args`` con ``block_names`` (lista) y ``target_dir``, copia cada
    ``<name>.s7dcl`` del fixture al directorio destino. Asi el parser
    SCL del step ``parsear_scl`` puede leer los archivos reales y
    devolver los MLC IDs correctos.

    Bloques cuyo ``.s7dcl`` no exista en el fixture se reportan en
    ``skipped_names`` (mismo comportamiento que el handler real).
    """
    target = Path(args["target_dir"])
    block_names = args.get("block_names") or []
    exported = []
    skipped = []
    for name in block_names:
        src = FIXTURES_BLOQUES / f"{name}.s7dcl"
        if not src.exists():
            skipped.append(name)
            continue
        shutil.copy(src, target / f"{name}.s7dcl")
        exported.append(name)
    return {
        "ok": True,
        "result": {
            "exported_to": str(target),
            "count": len(exported),
            "exported_names": exported,
            "skipped_names": skipped,
        },
    }


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
    layout: BlocksEditLayout | None = None,
) -> FunctionBlockEditPrepare:
    return FunctionBlockEditPrepare(
        nombre="block_edit_prepare",
        tia_client=tia_client,
        app_cache=app_cache,
        tracker=progress,
        layout=layout,
    )


def _run_fb(fb: FunctionBlockEditPrepare, **start_kwargs: Any) -> None:
    """Helper: arranca + 5 steps + finalizar = 7 ticks.

    El FB ejecuta ``validar`` -> ``leer_tia`` -> ``exportar_sd`` ->
    ``parsear_scl`` -> ``merge_cache`` y termina. El primer tick pasa de
    ``arrancar`` a ``ejecutar``; los 5 siguientes avanzan por cada step;
    el septimo tick ejecuta ``finalizar`` y deja el FB en ``n_done``.
    """
    asyncio.run(fb.start(**start_kwargs))
    for _ in range(7):
        asyncio.run(fb.tick())


# ── 1. Happy path ──────────────────────────────────────────────────


def test_happy_path_3_bloques_usa_cache_plc_blocks(
    app_cache: AppCache,
    real_progress: ProgressTracker,
) -> None:
    """3 bloques pre-poblados en ``plc_blocks`` -> 3 DTOs mergeados.

    Verifica que el FB itera ``app_cache.plc_blocks`` (no navega el
    arbol TIA): el mock de ``tia_client`` solo expone ``dispatch`` y NO
    tiene ``wrapper`` accesible (el spec del mock se cumple aunque
    ``wrapper`` sea un MagicMock auto-creado, pero el FB no lo usa).
    """
    blocks = [
        _make_cached_dto("DB2000_ED", 2000, "DB", "DB2000_ED"),
        _make_cached_dto("FC2000_ZC_ED", 2000, "FC", "FC2000_ZC_ED"),
        _make_cached_dto("OB1_MAIN", 1, "OB", "OB1_MAIN"),
    ]
    _seed_plc_blocks(app_cache, "PLC_1", blocks)
    tia_client = _make_tia_client(_copy_s7dcl_export)
    fb = _make_fb(app_cache, tia_client, real_progress)

    selected = ["DB2000_ED", "FC2000_ZC_ED", "OB1_MAIN"]
    _run_fb(fb, plc_name="PLC_1", selected_block_paths=selected)

    assert fb.nStep == fb.n_done
    assert fb.is_terminal() is True
    assert fb.error_msg is None

    # Result con la shape de prepare.
    assert fb.result is not None
    assert fb.result["ok"] is True
    assert fb.result["plc_name"] == "PLC_1"
    assert fb.result["n_blocks"] == 3

    # Cache con los 3 bloques.
    cached = app_cache.get_block_edit_prepared("PLC_1")
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
        assert d["author"] == "HCR"
        assert d["version"] == "1.0"
        assert d["programming_language"] == "SCL"
        assert d["memory_layout"] == "Optimized"


# ── 2. Seleccion vacia -> ValueError ────────────────────────────────


def test_block_edit_prepare_empty_selection_raises_value_error(
    app_cache: AppCache,
    real_progress: ProgressTracker,
) -> None:
    """``selected_block_paths=[]`` -> ``on_start`` lanza ValueError.

    El primer ``tick()`` captura el raise y pone el FB en ``n_error``
    con ``error_msg`` poblado (patron ``FunctionBase``).
    """
    _seed_plc_blocks(app_cache, "PLC_1", [])
    tia_client = _make_tia_client()
    fb = _make_fb(app_cache, tia_client, real_progress)

    asyncio.run(fb.start(plc_name="PLC_1", selected_block_paths=[]))
    asyncio.run(fb.tick())

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "selected_block_paths" in fb.error_msg


# ── 3. Bloque no esta en el cache -> skip silencioso ────────────────


def test_no_op_sin_bloques_en_cache(
    app_cache: AppCache,
    real_progress: ProgressTracker,
) -> None:
    """El bloque seleccionado no esta en ``plc_blocks.blocks`` -> skip.

    El operario puede tener bloques en la UI que no esten escaneados
    (race condition tras un re-scan). El FB no falla: emite un warning
    por bloque no encontrado y merge con 0 entries. ``dispatch`` NO se
    invoca (no hay nada que exportar).
    """
    _seed_plc_blocks(
        app_cache, "PLC_1",
        [_make_cached_dto("DB9999_FOO", 9999, "DB", "DB9999_FOO")],
    )
    tia_client = _make_tia_client(_copy_s7dcl_export)
    fb = _make_fb(app_cache, tia_client, real_progress)

    _run_fb(
        fb,
        plc_name="PLC_1",
        selected_block_paths=["DB2000_ED"],  # NO esta en el cache.
    )

    assert fb.nStep == fb.n_done
    assert fb.error_msg is None
    assert fb.result["n_blocks"] == 0
    assert fb.result["plc_name"] == "PLC_1"

    # dispatch NO se llamo (no hay bloques para exportar).
    tia_client.dispatch.assert_not_called()
    # Cache del prepare: plc_name presente pero dict vacio.
    assert app_cache.get_block_edit_prepared("PLC_1") == {}


# ── 4. PLC sin cache en plc_blocks -> RuntimeError ──────────────────


def test_sin_cache_plc_blocks_raises(
    app_cache: AppCache,
    real_progress: ProgressTracker,
) -> None:
    """``plc_blocks`` no tiene entrada para el plc -> ``RuntimeError``.

    El operario debe ejecutar ``scan_blocks`` antes de ``prepare``.
    Sin cache, el FB fail-fas en ``leer_tia`` con un mensaje claro
    (incluye el nombre del PLC) y NO toca TIA (no hace dispatch).
    """
    tia_client = _make_tia_client()
    fb = _make_fb(app_cache, tia_client, real_progress)

    asyncio.run(fb.start(
        plc_name="PLC_1",
        selected_block_paths=["DB2000_ED"],
    ))

    # tick #1: arrancar -> ejecutar (on_start OK).
    asyncio.run(fb.tick())
    assert fb.nStep == fb.n_ejecutar

    # tick #2: validar (ok, retorna string).
    asyncio.run(fb.tick())
    assert fb.nStep == fb.n_ejecutar

    # tick #3: leer_tia falla con RuntimeError.
    asyncio.run(fb.tick())

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "plc_blocks no cacheado" in fb.error_msg
    assert "PLC_1" in fb.error_msg
    # El FB fail-fast antes de tocar TIA.
    tia_client.dispatch.assert_not_called()


# ── 5. export_block falla para 1 bloque ────────────────────────────


def test_export_raises_continues_with_others(
    app_cache: AppCache,
    real_progress: ProgressTracker,
) -> None:
    """``export_block`` retorna ``ok=False`` para FC: queda sin title/comment.

    El bloque afectado se queda en el cache con ``title=None`` y
    ``comment=None`` (no se pudo parsear SCL). Los otros props
    extendidos (vienen del cache IT) se mantienen. El resto de bloques
    pasan al cache con todos los campos poblados.
    """
    blocks = [
        _make_cached_dto("DB2000_ED", 2000, "DB", "DB2000_ED"),
        _make_cached_dto("FC2000_ZC_ED", 2000, "FC", "FC2000_ZC_ED"),
        _make_cached_dto("OB1_MAIN", 1, "OB", "OB1_MAIN"),
    ]
    _seed_plc_blocks(app_cache, "PLC_1", blocks)

    fail_targets = {"FC2000_ZC_ED"}

    def _export_dispatch(cmd: str, args: dict) -> dict:
        # Simula el handler real: exporta los que TIA acepta y reporta los
        # fallidos en ``skipped_names``. ``ok=True`` global aunque algun
        # bloque falle (mismo comportamiento que ``_h_export_blocks``).
        # Ademas materializa los ``.s7dcl`` de los exportados para que
        # ``parsear_scl`` pueda leerlos del workdir.
        wanted = list(args.get("block_names", []))
        exported = [n for n in wanted if n not in fail_targets]
        skipped = [n for n in wanted if n in fail_targets]
        # Materializa los SD de los bloques exportados en target_dir.
        target = Path(args.get("target_dir", ""))
        target.mkdir(parents=True, exist_ok=True)
        for name in exported:
            src = FIXTURES_BLOQUES / f"{name}.s7dcl"
            if src.exists():
                shutil.copy(src, target / f"{name}.s7dcl")
        return {
            "ok": True,
            "result": {
                "exported_to": str(target),
                "count": len(exported),
                "exported_names": exported,
                "skipped_names": skipped,
            },
        }

    tia_client = _make_tia_client(_export_dispatch)
    fb = _make_fb(app_cache, tia_client, real_progress)

    _run_fb(
        fb,
        plc_name="PLC_1",
        selected_block_paths=["DB2000_ED", "FC2000_ZC_ED", "OB1_MAIN"],
    )

    assert fb.nStep == fb.n_done
    cached = app_cache.get_block_edit_prepared("PLC_1")

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
    # El resto de campos extendidos (vienen del cache IT) sí están.
    assert fc_dto.author == "HCR"
    assert fc_dto.version == "1.0"
    assert fc_dto.programming_language == "SCL"
    assert fc_dto.memory_layout == "Optimized"


# ── 6. layout injection: exports van a tmp_path/preview/ (plano) ──────


def test_layout_injection(
    app_cache: AppCache,
    real_progress: ProgressTracker,
    tmp_path: Path,
) -> None:
    """``layout=BlocksEditLayout(root=tmp_path)`` -> exports a tmp_path.

    Verifica que el ``layout`` inyectado via constructor se usa para
    resolver el directorio de exports. El SD exportado (via dispatch
    que copia del fixture) termina en ``tmp_path/preview/`` plano,
    tal como dicta la convencion de ``BlocksEditLayout.preview_dir``
    (sin subdir por PLC, mismo patron que las areas).
    """
    _seed_plc_blocks(
        app_cache, "PLC_1",
        [_make_cached_dto("DB2000_ED", 2000, "DB", "DB2000_ED")],
    )
    layout = BlocksEditLayout(root=tmp_path)
    tia_client = _make_tia_client(_copy_s7dcl_export)
    fb = _make_fb(app_cache, tia_client, real_progress, layout=layout)

    _run_fb(
        fb,
        plc_name="PLC_1",
        selected_block_paths=["DB2000_ED"],
    )

    assert fb.nStep == fb.n_done
    assert fb.error_msg is None

    # El SD exportado esta en tmp_path/preview/DB2000_ED.s7dcl (PLANO).
    expected = tmp_path / "preview" / "DB2000_ED.s7dcl"
    assert expected.exists(), (
        f"SD no se exporto al path inyectado: {expected}"
    )

    # El cache del prepare tiene el DTO mergeado.
    dto = app_cache.get_block_edit_prepared("PLC_1")["DB2000_ED"]
    assert isinstance(dto, DataBloquePLC)
    assert dto.title is not None  # parser SCL lo populo.


# ── 7. dispatch target_dir es absoluto ─────────────────────────────


def test_dispatch_args_usan_path_absoluto(
    app_cache: AppCache,
    real_progress: ProgressTracker,
    tmp_path: Path,
) -> None:
    """El ``target_dir`` pasado a ``export_block`` es un path absoluto.

    Requisito del SDK Openness de TIA: ``directoryInfo cannot be a
    relative path``. El layout (default o inyectado) garantiza paths
    absolutos via ``os.getcwd()`` al construir el root.
    """
    _seed_plc_blocks(
        app_cache, "PLC_1",
        [_make_cached_dto("DB2000_ED", 2000, "DB", "DB2000_ED")],
    )
    layout = BlocksEditLayout(root=tmp_path)
    tia_client = _make_tia_client(_copy_s7dcl_export)
    fb = _make_fb(app_cache, tia_client, real_progress, layout=layout)

    _run_fb(
        fb,
        plc_name="PLC_1",
        selected_block_paths=["DB2000_ED"],
    )

    # dispatch fue llamado una vez con el export de DB2000_ED (1 IPC, no N).
    assert tia_client.dispatch.call_count >= 1
    # Buscar la call a export_blocks.
    found = False
    for call in tia_client.dispatch.call_args_list:
        args_dict = call.args[1] if len(call.args) > 1 else call.kwargs.get("args", {})
        if "DB2000_ED" in args_dict.get("block_names", []):
            target_dir = args_dict["target_dir"]
            p = Path(target_dir)
            assert p.is_absolute(), (
                f"target_dir no es absoluto: {target_dir!r}"
            )
            assert ".." not in p.parts, (
                f"target_dir contiene '..': {target_dir!r}"
            )
            assert not str(p).startswith("./"), (
                f"target_dir empieza con './': {target_dir!r}"
            )
            found = True
    assert found, "no se encontro la call a dispatch('export_blocks', ...)"


# ── 8. clean_preview al inicio de exportar_sd ──────────────────────


def test_segundo_prepare_borra_sd_previos(
    app_cache: AppCache,
    real_progress: ProgressTracker,
    tmp_path: Path,
) -> None:
    """Un 2º ``prepare`` borra los ``.s7dcl`` del prepare anterior.

    Caso: el operario prepara A, B, C. Luego elimina C de TIA Portal
    (o deselecciona bloques) y vuelve a preparar solo A. Sin el
    ``clean_preview()`` al inicio de ``exportar_sd``, B.s7dcl y
    C.s7dcl quedarían en disco contaminando cualquier inspección
    posterior.

    Como el layout es plano (``preview/`` sin subdir por PLC), el
    ``clean_preview()`` borra TODO el directorio: tras el 2º prepare
    con seleccion reducida, ``preview/`` contiene SOLO los bloques
    del nuevo prepare.
    """
    layout = BlocksEditLayout(root=tmp_path)
    blocks_3 = [
        _make_cached_dto("DB2000_ED", 2000, "DB", "DB2000_ED"),
        _make_cached_dto("FC2000_ZC_ED", 2000, "FC", "FC2000_ZC_ED"),
        _make_cached_dto("OB1_MAIN", 1, "OB", "OB1_MAIN"),
    ]
    _seed_plc_blocks(app_cache, "PLC_1", blocks_3)
    tia_client = _make_tia_client(_copy_s7dcl_export)

    # ── 1er prepare: A, B, C ──
    fb1 = _make_fb(app_cache, tia_client, real_progress, layout=layout)
    _run_fb(
        fb1,
        plc_name="PLC_1",
        selected_block_paths=["DB2000_ED", "FC2000_ZC_ED", "OB1_MAIN"],
    )
    assert fb1.nStep == fb1.n_done

    preview_dir = layout.preview_dir
    assert (preview_dir / "DB2000_ED.s7dcl").exists()
    assert (preview_dir / "FC2000_ZC_ED.s7dcl").exists()
    assert (preview_dir / "OB1_MAIN.s7dcl").exists()

    # ── 2º prepare: solo A (B y C quedan fuera) ──
    _seed_plc_blocks(app_cache, "PLC_1", [blocks_3[0]])  # solo DB en cache
    fb2 = _make_fb(app_cache, tia_client, real_progress, layout=layout)
    _run_fb(
        fb2,
        plc_name="PLC_1",
        selected_block_paths=["DB2000_ED"],
    )
    assert fb2.nStep == fb2.n_done

    # Solo A.s7dcl esta; B.s7dcl y C.s7dcl fueron barridos por clean_preview.
    remaining = sorted(p.name for p in preview_dir.iterdir())
    assert remaining == ["DB2000_ED.s7dcl"], (
        f"se esperaban solo DB2000_ED.s7dcl, hay: {remaining}"
    )
