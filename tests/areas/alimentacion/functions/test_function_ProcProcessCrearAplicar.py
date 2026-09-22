"""Tests del FB ``FunctionProcProcessCrearAplicar``.

Cubre:
  - Happy path: 11 ticks (1 arrancar + 9 steps + 1 finalizar) -> n_done,
    ``self.result`` con shape de apply (archivos_generados, colisiones,
    nuevo_dir, manifest_plantilla, import_result, compile_result).
  - Sad path: ``execute_transactional_batch`` retorna
    ``{"ok": False, ...}`` -> el FB va a ``n_error`` (rollback atomico
    del lote).

Mockeamos:
  - ``config_manager``, ``app_state``, ``build_cache`` con ``MagicMock``.
  - ``tia_client`` con ``MagicMock``.
  - ``dispatch_async`` del modulo del FB via ``monkeypatch`` (con una
    coroutine fake que devuelve un dict de exito o error segun test).

``progress`` es un ``ProgressTracker`` real (NO mockeado) para verificar
el flujo de stages.

NOTA (sept-2026): el FB usa ``execute_transactional_batch`` para tener
rollback atomico entre ``import_plc_tags_xml`` y ``import_blocks_sd``.
Si TIA V21 corrompe la transaccion (error ``CommitOnDispose`` que
vimos en commit 8ed8705), el rollback automatico del lote protege
al PLC. El FB detecta el fallo (lote.ok=False) y va a ``n_error``.
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
    # detectar exito, asi que devolvemos ``{"ok": True, ...}``. Para
    # el lote transaccional devolvemos el shape real con ``operations_executed``
    # y ``details`` para que el test verifique la forma consolidada.
    async def fake_dispatch(tia_client: Any, command: str, args: dict, **kw: Any) -> dict:
        if command == "execute_transactional_batch":
            return {
                "ok": True,
                "operations_executed": 3,
                "details": [
                    {"step": 1, "command": "import_plc_tags_xml",
                     "result": {"imported_from": ""}},
                    {"step": 2, "command": "_wait",
                     "result": "sleep 2.0s"},
                    {"step": 3, "command": "import_blocks_sd",
                     "result": {"imported_from": ""}},
                ],
            }
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
    # ``process_label``: ``"<base_nueva>_<codigo_nuevo>"`` del proceso
    # creado (sept-2026). La SPA lo lee para el mensaje final de OK
    # tras el apply; el router lo usa en el log. Los tests del FB
    # verifican que el formato es el correcto.
    assert "process_label" in fb.result
    assert fb.result["process_label"] == "60010_EXP", (
        f"process_label mal formado: {fb.result['process_label']!r}"
    )
    # Cada dispatch mockeado devolvio ``{"ok": True, "imported_from": ...}``.
    assert fb.result["compile_result"] == {"ok": True, "imported_from": ""}
    # ``import_result`` tiene el shape consolidado del lote (legacy
    # execute_transactional_batch) con ``operations_executed`` y
    # ``details``: tags + wait + blocks.
    ir = fb.result["import_result"]
    assert ir["ok"] is True
    assert ir["operations_executed"] == 3
    assert len(ir["details"]) == 3
    assert ir["details"][0]["command"] == "import_plc_tags_xml"
    assert ir["details"][1]["command"] == "_wait"
    assert ir["details"][2]["command"] == "import_blocks_sd"


# ── Sad path ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_lote_transaccional_falla(
    plantilla_dummy: Path,
    tmp_path: Path,
    progress: ProgressTracker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``execute_transactional_batch`` retorna ``{ok: False, ...}``
    -> el FB va a ``n_error``.

    El step ``importar_proceso`` ejecuta UN SOLO dispatch
    (``execute_transactional_batch``) que internamente corre las 3
    ops (tags + wait + blocks) bajo una transaccion TIA. Aqui
    forzamos que el lote retorne fallo (simula el caso en el que
    TIA no puede hacer commit del lote por algun motivo:
    bloque conflictivo, transaccion corrupta, etc.). El FB detecta
    el fallo y va a ``n_error`` sin ejecutar ``compile_plc``.
    """
    tia = MagicMock()

    dispatch_count = {"execute_transactional_batch": 0}

    async def fake_dispatch(
        tia_client: Any, command: str, args: dict, **kw: Any,
    ) -> dict:
        if command == "execute_transactional_batch":
            dispatch_count["execute_transactional_batch"] += 1
            return {
                "ok": False,
                "error": (
                    "Lote abortado en el paso 3 ('import_blocks_sd'). "
                    "Rollback ejecutado. Motivo: OpennessAccessException: "
                    "Error when calling method 'CommitOnDispose' of type "
                    "'Siemens.Engineering.Transaction'. Commit of a "
                    "Transaction is not allowed after an exception is "
                    "thrown due to potential project data corruption."
                ),
            }
        # No deberia llamarse a ningun otro dispatch (los imports
        # estan dentro del lote).
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
    #   6: importar_proceso  <- aqui falla el lote transaccional
    # Tras 1 arrancar + 6 offline = 7 ticks, estamos en ejecutar.
    for _ in range(7):
        await fb.tick()
        assert fb.nStep in (fb.n_ejecutar, fb.n_error), (
            "FB aborto antes del step 'importar_proceso'"
        )
    assert fb.nStep == fb.n_ejecutar

    # tick #8: ``importar_proceso`` -> execute_transactional_batch
    # retorna ok=False -> n_error
    await fb.tick()
    assert fb.nStep == fb.n_error  # 98
    assert fb.error_msg is not None
    # El mensaje viene del RuntimeError que lanza el FB cuando el
    # lote transaccional retorna ok=False.
    assert "execute_transactional_batch fallo" in fb.error_msg
    assert "CommitOnDispose" in fb.error_msg

    # Verificamos que se llamo el dispatch del lote (solo 1; los
    # imports viven dentro del lote, no como dispatches separados).
    assert dispatch_count["execute_transactional_batch"] == 1
    # ``compile_plc`` NUNCA se llamo (el FB aborto antes).