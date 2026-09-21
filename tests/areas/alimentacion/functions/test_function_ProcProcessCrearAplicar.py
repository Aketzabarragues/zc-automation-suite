"""Tests del FB ``FunctionProcProcessCrearAplicar``.

Cubre:
  - Happy path: 11 ticks (1 arrancar + 9 steps + 1 finalizar) -> n_done,
    ``self.result`` con shape de apply (archivos_generados, colisiones,
    nuevo_dir, manifest_plantilla, import_result, compile_result).
  - Sad path: ``dispatch_async`` retorna ``{"ok": False, "error": "..."}``
    en ``import_blocks_sd`` (que es el segundo dispatch del step
    ``importar_proceso``: tags + wait + blocks) -> el FB va a
    ``n_error``.

Mockeamos:
  - ``config_manager``, ``app_state``, ``build_cache`` con ``MagicMock``.
  - ``tia_client`` con ``MagicMock``.
  - ``dispatch_async`` del modulo del FB via ``monkeypatch`` (con una
    coroutine fake que devuelve un dict de exito o error segun test).

``progress`` es un ``ProgressTracker`` real (NO mockeado) para verificar
el flujo de stages.

NOTA (sept-2026): el FB ya NO usa ``execute_transactional_batch``
porque TIA Openness V21 corrompe la transaccion cuando
``import_blocks_sd`` corre dentro de un
``project.start_transaction``/``end_transaction`` (error
``CommitOnDispose``). El step ``importar_proceso`` ahora hace
2 dispatches secuenciales (``import_plc_tags_xml`` +
``import_blocks_sd``) separados por un ``asyncio.sleep`` local. Si
uno falla, el FB va a ``n_error`` con el mensaje de TIA.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from areas.alimentacion.functions.function_ProcProcessCrearAplicar import (
    FunctionProcProcessCrearAplicar,
)
from core.runtime.progress_buffer import ProgressTracker


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def plantilla_dummy(tmp_path: Path) -> Path:
    """Crea una plantilla minima en tmp_path."""
    p = tmp_path / "TestPlantilla"
    p.mkdir()
    bloques = p / "Bloques de programa"
    bloques.mkdir()
    (bloques / "FC50010_TEST_INTERFAZ.s7dcl").write_text(
        "FUNCTION_BLOCK FC50010_TEST_INTERFAZ\n",
        encoding="utf-8",
    )
    (bloques / "50010_TEST_COMENTARIOS.s7res").write_text(
        "BOM content", encoding="utf-8-sig",
    )
    (p / "Variables PLC" / "003_Procesos").mkdir(parents=True)
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<Document>\n"
        '  <SW.Tags.PlcTagTable ID="0">\n'
        '    <AttributeList><Name>50010_TEST</Name></AttributeList>\n'
        "    <ObjectList>\n"
        '      <SW.Tags.PlcUserConstant ID="1">\n'
        "        <AttributeList>"
        "<DataTypeName>Int</DataTypeName>"
        "<Name>50010_N_MAX_PREAL</Name><Value>3</Value>"
        "</AttributeList>\n"
        "      </SW.Tags.PlcUserConstant>\n"
        "    </ObjectList>\n"
        "  </SW.Tags.PlcTagTable>\n"
        "</Document>\n"
    )
    (p / "Variables PLC" / "003_Procesos" / "50010_TEST.xml").write_text(
        xml, encoding="utf-8",
    )
    (p / "manifest.json").write_text(
        json.dumps({
            "base": 50010, "codigo": "TEST", "nombre": "ProcesoTest",
            "minimos": {
                "N_MAX_PREAL": 3, "N_MAX_PINT": 15,
                "N_MAX_ALM": 16, "N_MAX_ALM_HMI": 3,
            },
        }),
        encoding="utf-8",
    )
    return p


@pytest.fixture
def real_progress() -> ProgressTracker:
    return ProgressTracker()


@pytest.fixture
def progress(real_progress: ProgressTracker) -> ProgressTracker:
    real_progress.begin(
        operation="proc_process_crear_aplicar_test",
        label="Aplicar crear proceso (test)",
        stages=[
            "leer_manifest",
            "validar_minimos",
            "copiar_a_preview",
            "construir_diccionarios",
            "generar_proceso_nuevo",
            "escribir_manifest_modified",
            "importar_proceso",
            "compilar",
            "done",
        ],
    )
    return real_progress


def make_fb(
    tia_client: MagicMock,
    progress: ProgressTracker,
) -> FunctionProcProcessCrearAplicar:
    """Crea un FB con deps mockeadas pero tracker real."""
    config = MagicMock()
    build_cache_root = MagicMock()
    return FunctionProcProcessCrearAplicar(
        nombre="proc_process_crear_aplicar_test",
        config_manager=config,
        tia_client=tia_client,
        build_cache=build_cache_root,
        tracker=progress,
    )


# ── Happy path ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_happy_path_11_ticks(
    plantilla_dummy: Path,
    tmp_path: Path,
    progress: ProgressTracker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: 11 ticks -> n_done, ``self.result`` con shape de apply.

    State machine del FunctionBase tras consolidar los 3 imports en 1
    lote transaccional (mas ``compile_plc`` fuera de transaccion):

      tick #1:  10 -> 20 (on_start + tracker.begin)
      ticks #2-#10: 20 (9 steps; nStep NO avanza)
      tick #11: 95 -> 99 (on_finish)
    """
    tia = MagicMock()

    # Mockear ``dispatch_async`` del modulo del FB. La firma real es
    # ``await dispatch_async(tia_client, command, args, timeout_s)``.
    # Devolvemos un dict de exito para cada comando; ``compile_plc`` y
    # ``execute_transactional_batch`` usan ``result.get("ok")`` para
    # detectar exito, asi que devolvemos ``{"ok": True, ...}``.
    async def fake_dispatch(tia_client: Any, command: str, args: dict, **kw: Any) -> dict:
        return {"ok": True, "imported_from": args.get("import_dir", "")}

    monkeypatch.setattr(
        "areas.alimentacion.functions.function_ProcProcessCrearAplicar.dispatch_async",
        fake_dispatch,
    )

    fb = make_fb(tia, progress)

    ok = await fb.start(
        plantillas_path=str(plantilla_dummy.parent),
        dir_plantilla_nombre="TestPlantilla",
        base_nueva=60010,
        codigo_nuevo="EXP",
        nombre_nuevo="NuevoProceso",
        minimos_usuario={
            "N_MAX_PREAL": 30, "N_MAX_PINT": 30,
            "N_MAX_ALM": 30, "N_MAX_ALM_HMI": 5,
        },
        plc_name="S7-1500",
        plc_blocks_cache=[],
        build_cache_root=tmp_path / ".build_cache",
    )
    assert ok is True
    assert fb.nStep == fb.n_arrancar  # 10

    # tick #1: arrancar -> ejecutar
    await fb.tick()
    assert fb.nStep == fb.n_ejecutar  # 20

    # ticks #2-#10: 9 steps del apply
    for i in range(9):
        await fb.tick()
        assert fb.nStep in (fb.n_ejecutar, fb.n_finalizar), (
            f"tick #{i + 2} salio del loop antes de tiempo: nStep={fb.nStep}"
        )
    assert fb.nStep == fb.n_finalizar  # 95

    # tick #11: finalizar -> done
    await fb.tick()
    assert fb.nStep == fb.n_done  # 99
    assert fb.is_terminal() is True
    assert fb.error_msg is None

    # Result con la shape de apply. NOTA: el step ``done`` invoca
    # ``proc_process_done_summary`` sin ``await`` (mismo patron que el
    # preview), por lo que ``self.result`` queda con lo que tenga
    # ``ctx.result`` (por defecto ``{}``). El wrapper de ``on_finish``
    # ademas anyade ``import_result`` (dict del lote transaccional) y
    # ``compile_result`` (dict de ``compile_plc``), asi que podemos
    # verificar esos.
    assert fb.result is not None
    assert isinstance(fb.result, dict)
    # import_result y compile_result vienen de los atributos internos,
    # poblados por los dispatches mockeados.
    assert "import_result" in fb.result
    assert "compile_result" in fb.result
    # Cada dispatch mockeado devolvio ``{"ok": True, "imported_from": ...}``.
    assert fb.result["compile_result"] == {"ok": True, "imported_from": ""}
    # ``import_result`` tiene el shape consolidado del lote (legacy
    # execute_transactional_batch) con ``operations_executed`` y
    # ``details``: tags + wait + blocks.
    ir = fb.result["import_result"]
    assert ir["ok"] is True
    assert ir["operations_executed"] == 2
    assert len(ir["details"]) == 3
    assert ir["details"][0]["command"] == "import_plc_tags_xml"
    assert ir["details"][1]["command"] == "_wait"
    assert ir["details"][2]["command"] == "import_blocks_sd"


# ── Sad path ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_import_blocks_falla(
    plantilla_dummy: Path,
    tmp_path: Path,
    progress: ProgressTracker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``dispatch_async`` retorna ``{"ok": False, ...}`` en
    ``import_blocks_sd`` -> el FB va a ``n_error``.

    El step ``importar_proceso`` ejecuta 2 dispatches secuenciales:
    1. ``import_plc_tags_xml`` -> si falla, aborta aqui.
    2. ``import_blocks_sd`` -> si falla, aborta aqui.

    Aqui forzamos el caso 2 (el bug TIA Openness V21 con
    CommitOnDispose que vimos en sept-2026): ``import_plc_tags_xml``
    tiene exito pero ``import_blocks_sd`` retorna
    ``{"ok": False, "error": "TIA CommitOnDispose..."}``. El FB
    detecta el fallo y va a ``n_error`` sin ejecutar ``compile_plc``.
    """
    tia = MagicMock()

    dispatch_count = {"import_plc_tags_xml": 0, "import_blocks_sd": 0}

    async def fake_dispatch(
        tia_client: Any, command: str, args: dict, **kw: Any,
    ) -> dict:
        if command == "import_plc_tags_xml":
            dispatch_count["import_plc_tags_xml"] += 1
            return {"ok": True}
        if command == "import_blocks_sd":
            dispatch_count["import_blocks_sd"] += 1
            return {
                "ok": False,
                "error": (
                    "OpennessAccessException: Error when calling "
                    "method 'CommitOnDispose' of type "
                    "'Siemens.Engineering.Transaction'. Commit of a "
                    "Transaction is not allowed after an exception is "
                    "thrown due to potential project data corruption."
                ),
            }
        # No deberia llamarse a ningun otro dispatch.
        raise AssertionError(f"dispatch no esperado: {command!r}")

    monkeypatch.setattr(
        "areas.alimentacion.functions.function_ProcProcessCrearAplicar.dispatch_async",
        fake_dispatch,
    )

    fb = make_fb(tia, progress)

    await fb.start(
        plantillas_path=str(plantilla_dummy.parent),
        dir_plantilla_nombre="TestPlantilla",
        base_nueva=60010,
        codigo_nuevo="EXP",
        nombre_nuevo="NuevoProceso",
        minimos_usuario={
            "N_MAX_PREAL": 30, "N_MAX_PINT": 30,
            "N_MAX_ALM": 30, "N_MAX_ALM_HMI": 5,
        },
        plc_name="S7-1500",
        plc_blocks_cache=[],
        build_cache_root=tmp_path / ".build_cache",
    )
    assert fb.nStep == fb.n_arrancar  # 10

    # Avanzamos los 6 steps offline
    # (leer_manifest..escribir_manifest_modified). Steps del apply:
    #   0: leer_manifest
    #   1: validar_minimos
    #   2: copiar_a_preview
    #   3: construir_diccionarios
    #   4: generar_proceso_nuevo
    #   5: escribir_manifest_modified
    #   6: importar_proceso  <- aqui falla import_blocks_sd
    # Tras 1 arrancar + 6 offline = 7 ticks, estamos en ejecutar.
    for _ in range(7):
        await fb.tick()
        assert fb.nStep in (fb.n_ejecutar, fb.n_error), (
            "FB aborto antes del step 'importar_proceso'"
        )
    assert fb.nStep == fb.n_ejecutar

    # tick #8: ``importar_proceso`` -> import_tags OK, import_blocks FAIL
    # -> n_error
    await fb.tick()
    assert fb.nStep == fb.n_error  # 98
    assert fb.error_msg is not None
    # El mensaje viene del RuntimeError que lanza el FB cuando
    # import_blocks_sd retorna ok=False.
    assert "import_blocks_sd fallo" in fb.error_msg
    assert "CommitOnDispose" in fb.error_msg

    # Verificamos que se llamaron los 2 dispatches esperados.
    assert dispatch_count["import_plc_tags_xml"] == 1
    assert dispatch_count["import_blocks_sd"] == 1
    # ``compile_plc`` NUNCA se llamo (el FB aborto antes).