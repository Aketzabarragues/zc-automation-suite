"""Tests del FB ``FunctionProcCrearSincronizar``.

Cubre el camino sync del OB1 (``fb.execute(**params)``):
  - Happy path: las 10 etapas se recorren y el FB termina en ``n_done``.
    ``self.result`` trae la shape de apply (archivos_generados,
    colisiones, nuevo_dir, manifest_plantilla, process_label,
    import_result, compile_result) y el orden de los comandos enviados
    al worker OT.
  - Sad path: ``execute_transactional_batch`` retorna
    ``{"ok": False, ...}`` -> el FB va a ``n_error`` (rollback atomico
    del lote) y nunca lanza ``compile_plc``.
  - Contrato sync: los handlers de step y los que hablan con el worker OT
    son funciones normales, no corrutinas.
  - Log de cierre: el FB emite ``logger.ok`` con los contadores reales
    cuando el apply termina bien, y no lo emite si el apply falla.

Mockeamos:
  - ``config_manager`` y ``build_cache`` con ``MagicMock``.
  - ``tia_client`` con ``MagicMock`` y ``submit_and_wait`` mockeado por
    comando (el FB llama al worker OT de forma sync).

``progress`` es un ``ProgressTracker`` real (NO mockeado) para verificar
el flujo de stages.

Contrato verificado por los tests: el FB detecta ``lote.ok=False`` y va
a ``n_error``, dejando el PLC en el mismo estado previo al apply
(rollback atomico del lote transaccional).
"""
from __future__ import annotations

import inspect
import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from areas.alimentacion.functions.function_proc_crear_sincronizar import (
    FunctionProcCrearSincronizar,
)
from core.infrastructure.log.log_web_bridge import OK_LEVEL
from core.runtime.progress_buffer import ProgressTracker


# Logger del FB: el log de cierre lo emite el FB, no el router.
APPLY_LOGGER = "areas.alimentacion.functions.function_proc_crear_sincronizar"


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
            "descripcion": "Proceso de tests con 1 FC y 1 DB",
            "dependencias": ["DB1_SYS"],
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


# Respuestas del worker OT. La shape es la del dispatcher:
# ``{"ok": True, "result": <dict del handler>}`` o
# ``{"ok": False, "error": "<msg>"}``.
LIST_PLCS_OK: dict[str, Any] = {
    "ok": True,
    "result": {"plcs": [{"name": "S7-1500"}]},
}

BATCH_OK: dict[str, Any] = {
    "ok": True,
    "result": {
        "success": True,
        "operations_executed": 3,
        "details": [
            {"step": 1, "command": "import_plc_tags_xml",
             "result": {"imported_from": ""}},
            {"step": 2, "command": "_wait",
             "result": "sleep 2.0s"},
            {"step": 3, "command": "import_blocks_sd",
             "result": {"imported_from": ""}},
        ],
    },
}

COMPILE_OK: dict[str, Any] = {
    "ok": True,
    "result": {"had_errors": False},
}

# El refresh del BloqueCache (stage 9) es tolerante a fallos: el FB
# loggea un warning y continua el apply. En el test no hay TIA, asi que
# el comando se responde con un error explicito.
SCAN_BLOCKS_KO: dict[str, Any] = {
    "ok": False,
    "error": "scan_blocks no disponible en test offline",
}


def make_tia_client(
    responses: dict[str, Any],
    calls: list[str] | None = None,
) -> MagicMock:
    """Crea el mock del cliente TIA con ``submit_and_wait`` mockeado.

    ``submit_and_wait`` devuelve la shape del dispatcher del worker OT:
    ``{"ok": True, "result": <dict del handler>}`` o
    ``{"ok": False, "error": "<msg>"}``.

    ``responses`` mapea nombre de comando -> respuesta. Un comando sin
    respuesta mockeada lanza ``AssertionError`` (fallo de test visible,
    no fallo silencioso del FB). Si se pasa ``calls``, se appende el
    nombre de cada comando enviado al worker.
    """
    tia = MagicMock()

    def _submit_and_wait(
        command: str,
        args: dict | None = None,
        timeout: float = 30.0,
    ) -> dict:
        if calls is not None:
            calls.append(command)
        if command not in responses:
            raise AssertionError(
                f"submit_and_wait no mockeado para el comando {command!r}"
            )
        return responses[command]

    tia.submit_and_wait = MagicMock(side_effect=_submit_and_wait)
    return tia


def make_fb(
    tia_client: MagicMock,
    progress: ProgressTracker,
) -> FunctionProcCrearSincronizar:
    """Crea un FB con deps mockeadas pero tracker real."""
    config = MagicMock()
    build_cache_root = MagicMock()
    return FunctionProcCrearSincronizar(
        nombre="proc_process_crear_aplicar_test",
        config_manager=config,
        tia_client=tia_client,
        build_cache=build_cache_root,
        tracker=progress,
    )


# ── Camino sync (OB1) ────────────────────────────────────────────────


def test_apply_happy_path_sync_execute(
    plantilla_dummy: Path,
    tmp_path: Path,
    progress: ProgressTracker,
) -> None:
    """Camino OB1: ``execute()`` sync completa el apply sin event loop."""
    comandos: list[str] = []
    tia = make_tia_client(
        {
            "list_plcs": LIST_PLCS_OK,
            "execute_transactional_batch": BATCH_OK,
            "compile_plc": COMPILE_OK,
            "scan_blocks": SCAN_BLOCKS_KO,
        },
        calls=comandos,
    )
    fb = make_fb(tia, progress)

    fb.execute(
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

    assert fb.nStep == fb.n_done
    assert fb.is_terminal() is True
    assert fb.error_msg is None
    assert fb.result["process_label"] == "60010_EXP"
    assert fb.result["import_result"]["ok"] is True
    assert fb.result["compile_result"]["ok"] is True
    # ``compile_plc`` mockeado devolvio la shape del dispatcher:
    # ``{"ok": True, "result": {"had_errors": False}}``.
    assert fb.result["compile_result"] == {
        "ok": True,
        "result": {"had_errors": False},
    }
    # ``import_result`` tiene el shape consolidado del lote
    # (execute_transactional_batch) con ``success``,
    # ``operations_executed`` y ``details``: tags + wait + blocks.
    ir = fb.result["import_result"]
    lote = ir["result"]
    assert lote["success"] is True
    assert lote["operations_executed"] == 3
    assert len(lote["details"]) == 3
    assert lote["details"][0]["command"] == "import_plc_tags_xml"
    assert lote["details"][1]["command"] == "_wait"
    assert lote["details"][2]["command"] == "import_blocks_sd"
    # Orden de comandos contra el worker OT: validacion del PLC,
    # lote transaccional, compile y refresh del BloqueCache.
    assert comandos == [
        "list_plcs",
        "execute_transactional_batch",
        "compile_plc",
        "scan_blocks",
    ]


def test_apply_lote_transaccional_falla(
    plantilla_dummy: Path,
    tmp_path: Path,
    progress: ProgressTracker,
) -> None:
    """``execute_transactional_batch`` retorna ``{ok: False, ...}``
    -> el FB va a ``n_error``.

    El step ``importar_proceso`` ejecuta UN SOLO comando
    (``execute_transactional_batch``) que internamente corre las 3
    ops (tags + wait + blocks) bajo una transaccion TIA. Aqui
    forzamos que el lote retorne fallo (simula el caso en el que
    TIA no puede hacer commit del lote por algun motivo:
    bloque conflictivo, transaccion corrupta, etc.). El FB detecta
    el fallo y va a ``n_error`` sin ejecutar ``compile_plc``.
    """
    comandos: list[str] = []

    tia = make_tia_client(
        {
            "list_plcs": LIST_PLCS_OK,
            "execute_transactional_batch": {
                "ok": False,
                "error": (
                    "Lote abortado en el paso 3 ('import_blocks_sd'). "
                    "Rollback ejecutado. Motivo: OpennessAccessException: "
                    "Error when calling method 'CommitOnDispose' of type "
                    "'Siemens.Engineering.Transaction'. Commit of a "
                    "Transaction is not allowed after an exception is "
                    "thrown due to potential project data corruption."
                ),
            },
        },
        calls=comandos,
    )

    fb = make_fb(tia, progress)

    fb.execute(
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

    assert fb.nStep == fb.n_error  # 98
    assert fb.error_msg is not None
    # El mensaje viene del RuntimeError que lanza el FB cuando el
    # lote transaccional retorna ok=False.
    assert "execute_transactional_batch fallo" in fb.error_msg
    assert "CommitOnDispose" in fb.error_msg

    # Verificamos que se llamo al comando del lote (solo 1; los
    # imports viven dentro del lote, no como comandos separados).
    assert comandos.count("execute_transactional_batch") == 1
    # ``compile_plc`` NUNCA se llamo (el FB aborto antes).
    assert "compile_plc" not in comandos


# ── Contrato sync (hilo OB1) ─────────────────────────────────────────


def test_los_handlers_declarados_son_sync() -> None:
    """El FB ya no es una corrutina: se ejecuta en un hilo sync.

    Contrato del hilo OB1: los handlers de step (y los que hablan con
    el worker OT) son funciones normales, no corrutinas.
    """
    for spec in FunctionProcCrearSincronizar.pasos_declarados():
        assert not inspect.iscoroutinefunction(
            getattr(FunctionProcCrearSincronizar, spec.metodo)
        ), f"{spec.metodo} debe ser sync"
    assert not inspect.iscoroutinefunction(
        FunctionProcCrearSincronizar._stage_7_importar_proceso
    )
    assert not inspect.iscoroutinefunction(
        FunctionProcCrearSincronizar._stage_8_compilar_bloques
    )


# ── Log de cierre (lo emite el FB, no el router) ─────────────────────


def _apply_cierres(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Mensajes OK emitidos por el FB del apply."""
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == APPLY_LOGGER and record.levelno == OK_LEVEL
    ]


def test_apply_emite_el_log_de_cierre_con_los_valores_reales(
    plantilla_dummy: Path,
    tmp_path: Path,
    progress: ProgressTracker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """El FB emite el log de cierre con los contadores reales.

    El router responde 202 antes de que el apply se ejecute, asi que el
    cierre lo hace el FB (que ya tiene ``self.result``): el numero de
    archivos generados y el estado del compile son los de verdad.
    """
    tia = make_tia_client({
        "list_plcs": LIST_PLCS_OK,
        "execute_transactional_batch": BATCH_OK,
        "compile_plc": COMPILE_OK,
        "scan_blocks": SCAN_BLOCKS_KO,
    })
    fb = make_fb(tia, progress)

    with caplog.at_level(logging.DEBUG, logger=APPLY_LOGGER):
        fb.execute(
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

    assert fb.nStep == fb.n_done  # 99
    n_generados = len(fb.result["archivos_generados"])
    assert n_generados > 0, "el apply deberia haber generado archivos"
    assert _apply_cierres(caplog) == [
        f"Proceso {fb.result['process_label']} creado en 'S7-1500': "
        f"{n_generados} archivos generados, compile=OK."
    ]


def test_apply_no_emite_el_log_de_cierre_si_falla(
    plantilla_dummy: Path,
    tmp_path: Path,
    progress: ProgressTracker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Si el lote transaccional falla, no hay log de cierre.

    El log de cierre se reserva al trabajo que termina bien; el error
    ya lo emite la base del FB.
    """
    tia = make_tia_client({
        "list_plcs": LIST_PLCS_OK,
        "execute_transactional_batch": {"ok": False, "error": "lote abortado"},
    })
    fb = make_fb(tia, progress)

    with caplog.at_level(logging.DEBUG, logger=APPLY_LOGGER):
        fb.execute(
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

    assert fb.nStep == fb.n_error  # 98
    assert fb.error_msg is not None
    assert _apply_cierres(caplog) == []