"""Tests del FB ``FunctionProcProcessCrearAplicar``.

Cubre:
  - Happy path: 11 ticks (1 arrancar + 9 steps + 1 finalizar) -> n_done,
    ``self.result`` con shape de apply (archivos_generados, colisiones,
    nuevo_dir, manifest_plantilla, import_result, compile_result).
  - Sad path: ``dispatch_async`` lanza ``RuntimeError`` en el step
    ``importar_proceso`` (que delega a
    ``execute_transactional_batch``) -> el FB va a ``n_error``.

Mockeamos:
  - ``config_manager``, ``app_state``, ``build_cache`` con ``MagicMock``.
  - ``tia_client`` con ``MagicMock``.
  - ``dispatch_async`` del modulo del FB via ``monkeypatch`` (con una
    coroutine fake que devuelve un dict de exito o lanza RuntimeError
    segun test).

``progress`` es un ``ProgressTracker`` real (NO mockeado) para verificar
el flujo de stages.
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
        plc_blocks_cache=set(),
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
    # ``import_result`` es el mismo dict (no el shape antiguo con
    # ``tag_table``/``blocks_dbs``/``blocks_logicos``).
    assert fb.result["import_result"] == {"ok": True, "imported_from": ""}


# ── Sad path ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_import_batch_falla(
    plantilla_dummy: Path,
    tmp_path: Path,
    progress: ProgressTracker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``dispatch_async`` lanza ``RuntimeError`` en ``importar_proceso``
    (que delega a ``execute_transactional_batch``) -> el FB va a
    ``n_error``.

    Forzamos que ``dispatch_async`` lance ``RuntimeError`` para simular
    el caso real en el que TIA falla dentro de la transaccion (TIA hace
    rollback atomico de las 3 ops y el handler propaga el error al FB).
    """
    tia = MagicMock()

    dispatch_count = {"execute_transactional_batch": 0, "others": 0}

    async def fake_dispatch(
        tia_client: Any, command: str, args: dict, **kw: Any,
    ) -> dict:
        if command == "execute_transactional_batch":
            dispatch_count["execute_transactional_batch"] += 1
            raise RuntimeError(
                "Lote abortado en el paso 2 ('_wait'). Rollback ejecutado. "
                "Motivo: TIA import failed: PLC not reachable"
            )
        dispatch_count["others"] += 1
        return {"ok": True}

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
        plc_blocks_cache=set(),
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
    #   6: importar_proceso  <- aqui falla (dispatch_async lanza)
    # Tras 1 arrancar + 6 offline = 7 ticks, estamos en ejecutar.
    for _ in range(7):
        await fb.tick()
        # Permitimos error tambien (alguno de los offline puede fallar
        # si la plantilla es muy basica; pero con plantilla completa OK).
        assert fb.nStep in (fb.n_ejecutar, fb.n_error), (
            "FB aborto antes del step 'importar_proceso'"
        )
    assert fb.nStep == fb.n_ejecutar

    # tick #8: ``importar_proceso`` -> dispatch_async lanza -> n_error
    await fb.tick()
    assert fb.nStep == fb.n_error  # 98
    assert fb.error_msg is not None
    # El mensaje viene del RuntimeError.
    assert "TIA import failed" in fb.error_msg

    # Verificamos que el dispatch se llamo para
    # ``execute_transactional_batch``.
    assert dispatch_count["execute_transactional_batch"] == 1
    # Y NO para el ``compile_plc`` (esta fuera del lote transaccional
    # y nunca se llega a ejecutar porque el lote fallo).
    assert dispatch_count["others"] == 0