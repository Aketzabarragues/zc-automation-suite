"""Tests del FB ``FunctionProcCrearGenerarPreview``.

Cubre:
  - Happy path: 11 ticks (1 arrancar + 9 steps + 1 finalizar) -> n_done,
    ``self.result`` con shape de preview (archivos_previstos, colisiones,
    preview_dir, manifest_plantilla, success).
    ``preview_dir`` es el alias historico del campo ``plantilla_copia_dir``
  - Sad path: ``minimos_usuario`` con N_MAX < plantilla -> el FB va a
    ``n_error`` con mensaje mencionando "N_MAX" o "minimos".
  - Sad path: ``plantillas_path=""`` -> el FB va a ``n_error`` con
    mensaje mencionando "plantillas_path".

Mockeamos ``config_manager``, ``tia_client``, ``app_state`` y
``build_cache`` con ``MagicMock``. ``progress`` es un ``ProgressTracker``
real (NO mockeado) para verificar el flujo de stages.

El FB es offline (no toca TIA), asi que NO mockeamos ``dispatch_async``.
"""
from __future__ import annotations

import inspect
import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from areas.alimentacion.functions.function_proc_crear_generar_preview import (
    FunctionProcCrearGenerarPreview,
)
from core.infrastructure.log.log_web_bridge import OK_LEVEL
from core.runtime.progress_buffer import ProgressTracker


# Logger del FB: el log de cierre lo emite el FB, no el router.
PREVIEW_LOGGER = "areas.alimentacion.functions.function_proc_crear_generar_preview"


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
        operation="proc_process_crear_preview_test",
        label="Preview crear proceso (test)",
        stages=[
            "leer_manifest", "validar_minimos", "copiar_a_preview",
            "extraer_variables_xml", "construir_diccionarios",
            "detectar_colisiones", "generar_previstos", "done",
        ],
    )
    return real_progress


def make_fb(progress: ProgressTracker) -> FunctionProcCrearGenerarPreview:
    """Crea un FB con deps mockeadas pero tracker real."""
    config = MagicMock()
    tia = MagicMock()  # el preview NO toca TIA, pero se inyecta por homogeneidad
    build_cache_root = MagicMock()
    return FunctionProcCrearGenerarPreview(
        nombre="proc_process_crear_preview_test",
        config_manager=config,
        tia_client=tia,
        build_cache=build_cache_root,
        tracker=progress,
    )


# ── Happy path ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_preview_happy_path_10_ticks(
    plantilla_dummy: Path,
    tmp_path: Path,
    progress: ProgressTracker,
) -> None:
    """Happy path: 10 ticks -> n_done, ``self.result`` con shape de preview.

    State machine del FunctionBase tras añadir el step
    validar_dependencias (8 stages totales):
      tick #1:  10 -> 20 (on_start + tracker.begin)
      ticks #2-#9: 20 (8 steps; nStep NO avanza)
      tick #10: 95 -> 99 (on_finish)
    """
    fb = make_fb(progress)

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
        plc_blocks_cache=[],
        # Override del build_cache_root para no contaminar el cwd.
        build_cache_root=tmp_path / ".build_cache",
    )
    assert ok is True
    assert fb.nStep == fb.n_arrancar  # 10

    # tick #1: arrancar -> ejecutar
    await fb.tick()
    assert fb.nStep == fb.n_ejecutar  # 20

    # ticks #2-#9: 8 steps (incluye validar_dependencias)
    for i in range(8):
        await fb.tick()
        assert fb.nStep in (fb.n_ejecutar, fb.n_finalizar), (
            f"tick #{i + 2} salio del loop antes de tiempo: nStep={fb.nStep}"
        )
    assert fb.nStep == fb.n_finalizar  # 95

    # tick #10: finalizar -> done
    await fb.tick()
    assert fb.nStep == fb.n_done  # 99
    assert fb.is_terminal() is True
    assert fb.error_msg is None

    preview_dir = (
        tmp_path / ".build_cache" / "alimentacion" / "ProcesoNuevo" / "Plantilla"
    )

    # Result con la shape de preview. El step ``done`` invoca
    # ``proc_process_done_summary`` (sync) que compone ``ctx.result``;
    # ``on_finish`` lo vuelca a ``self.result``.
    assert fb.result is not None
    assert isinstance(fb.result, dict)
    assert fb.result["success"] is True
    assert fb.result["colisiones"] == []
    assert fb.result["manifest_plantilla"]["base"] == 50010
    assert fb.result["dependencias_ok"] == []
    assert fb.result["dependencias_faltantes"] == ["DB1_SYS"]
    assert fb.result["plantilla_copia_dir"] == str(preview_dir)

    # 1 entry por BLOQUE (1 por stem): el .s7dcl y el .s7res del mismo
    # bloque se agrupan en una sola entry.
    assert [p["nombre_nuevo"] for p in fb.result["archivos_previstos"]] == [
        "60010_EXP_COMENTARIOS",
        "FC60010_EXP_INTERFAZ",
    ]

    # Los archivos del preview se clonaron en disco.
    assert preview_dir.exists()
    assert (preview_dir / "Bloques de programa" / "FC50010_TEST_INTERFAZ.s7dcl").is_file()
    assert (preview_dir / "Bloques de programa" / "50010_TEST_COMENTARIOS.s7res").is_file()
    assert (preview_dir / "Variables PLC" / "003_Procesos" / "50010_TEST.xml").is_file()


# ── Sad paths ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_preview_invalid_minimos(
    plantilla_dummy: Path,
    tmp_path: Path,
    progress: ProgressTracker,
) -> None:
    """``minimos_usuario`` con N_MAX < plantilla -> n_error tras validar.

    El 2º step (``validar_minimos``) lanza ``PlantillaMinimosNoCumplidos``;
    el wrapper de la base captura el error y va a ``n_error``.
    """
    fb = make_fb(progress)

    await fb.start(
        plantillas_path=str(plantilla_dummy.parent),
        dir_plantilla_nombre="TestPlantilla",
        base_nueva=60010,
        codigo_nuevo="EXP",
        nombre_nuevo="NuevoProceso",
        # N_MAX_PREAL=1 < plantilla (3) -> falla validar_minimos.
        minimos_usuario={
            "N_MAX_PREAL": 1, "N_MAX_PINT": 30,
            "N_MAX_ALM": 30, "N_MAX_ALM_HMI": 5,
        },
        plc_blocks_cache=[],
        build_cache_root=tmp_path / ".build_cache",
    )
    assert fb.nStep == fb.n_arrancar  # 10

    # tick #1: arrancar -> ejecutar (on_start OK)
    await fb.tick()
    assert fb.nStep == fb.n_ejecutar  # 20

    # tick #2: ejecutar step[0] = leer_manifest OK
    await fb.tick()
    assert fb.nStep == fb.n_ejecutar  # 20

    # tick #3: ejecutar step[1] = validar_minimos falla -> n_error
    await fb.tick()
    assert fb.nStep == fb.n_error  # 98
    assert fb.error_msg is not None
    # El mensaje debe mencionar PlantillaMinimosNoCumplidos o el detalle.
    msg = fb.error_msg.lower()
    assert (
        "plantillaminimosnocumplidos" in msg
        or "minimos" in msg
        or "n_max" in msg
    )


@pytest.mark.asyncio
async def test_preview_no_plantilla_path(
    progress: ProgressTracker,
) -> None:
    """``plantillas_path=""`` -> on_start lanza ValueError -> n_error."""
    fb = make_fb(progress)

    await fb.start(
        plantillas_path="",
        dir_plantilla_nombre="TestPlantilla",
        base_nueva=60010,
        codigo_nuevo="EXP",
        nombre_nuevo="NuevoProceso",
        minimos_usuario={
            "N_MAX_PREAL": 30, "N_MAX_PINT": 30,
            "N_MAX_ALM": 30, "N_MAX_ALM_HMI": 5,
        },
        plc_blocks_cache=[],
    )
    assert fb.nStep == fb.n_arrancar  # 10

    # tick #1: on_start falla -> n_error
    await fb.tick()
    assert fb.nStep == fb.n_error  # 98
    assert fb.error_msg is not None
    assert "plantillas_path" in fb.error_msg


# ── contrato sync (hilo unico OB1) ────────────────────────────────────


def test_run_step_es_sync_no_coroutine() -> None:
    """El FB ya no es una corrutina: ``run_step`` es sync (camino OB1).

    El hilo unico del OB1 invoca el FB sin event loop: un ``run_step``
    async devolveria una corrutina que nadie espera y el step no
    ejecutaria nunca.
    """
    assert not inspect.iscoroutinefunction(
        FunctionProcCrearGenerarPreview.run_step
    ), "run_step debe ser sync; el FB ya no corre en un event loop"

    for _idx, _nombre, attr in FunctionProcCrearGenerarPreview.STAGES:
        assert not inspect.iscoroutinefunction(
            getattr(FunctionProcCrearGenerarPreview, attr)
        ), f"{attr} debe ser sync"


def test_helpers_preview_no_son_corrutinas() -> None:
    """Los 7 helpers module-level del pipeline del preview son sync.

    El shell los invoca desde el hilo unico, sin event loop: un
    ``await`` sobre ellos dejaria la corrutina sin ejecutar
    ("coroutine was never awaited") y el preview no compondria nada.
    """
    from areas.alimentacion.functions.function_proc_crear_generar_preview import (
        proc_process_copiar_a_preview,
        proc_process_detectar_colisiones,
        proc_process_done_summary,
        proc_process_generar_previstos,
        proc_process_leer_manifest,
        proc_process_validar_dependencias,
        proc_process_validar_minimos,
    )

    for helper in (
        proc_process_leer_manifest,
        proc_process_validar_minimos,
        proc_process_copiar_a_preview,
        proc_process_detectar_colisiones,
        proc_process_validar_dependencias,
        proc_process_generar_previstos,
        proc_process_done_summary,
    ):
        assert not inspect.iscoroutinefunction(helper), (
            f"{helper.__name__} debe ser sync"
        )


def test_execute_sync_recorre_las_8_etapas(
    plantilla_dummy: Path,
    tmp_path: Path,
) -> None:
    """``execute()`` (camino sync del OB1) recorre las 8 etapas y termina
    en ``n_done`` sin event loop."""
    fb = FunctionProcCrearGenerarPreview(
        nombre="proc_process_crear_preview_execute_test",
        config_manager=MagicMock(),
        tia_client=MagicMock(),  # el preview NO toca TIA
        build_cache=MagicMock(),
        tracker=ProgressTracker(),
    )

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
        plc_blocks_cache=[],
        build_cache_root=tmp_path / ".build_cache",
    )

    assert fb.nStep == fb.n_done  # 99
    assert fb.error_msg is None
    assert fb.result is not None
    assert fb.result["success"] is True
    assert fb.result["archivos_previstos"]
    assert fb.result["plantilla_copia_dir"] == str(
        tmp_path / ".build_cache" / "alimentacion" / "ProcesoNuevo" / "Plantilla"
    )


def test_execute_sync_minimos_insuficientes_va_a_error(
    plantilla_dummy: Path,
    tmp_path: Path,
) -> None:
    """Camino sync: N_MAX < plantilla -> ``n_error`` (sin event loop)."""
    fb = FunctionProcCrearGenerarPreview(
        nombre="proc_process_crear_preview_execute_error_test",
        config_manager=MagicMock(),
        tia_client=MagicMock(),
        build_cache=MagicMock(),
        tracker=ProgressTracker(),
    )

    fb.execute(
        plantillas_path=str(plantilla_dummy.parent),
        dir_plantilla_nombre="TestPlantilla",
        base_nueva=60010,
        codigo_nuevo="EXP",
        nombre_nuevo="NuevoProceso",
        # N_MAX_PREAL=1 < plantilla (3) -> falla validar_minimos.
        minimos_usuario={
            "N_MAX_PREAL": 1, "N_MAX_PINT": 30,
            "N_MAX_ALM": 30, "N_MAX_ALM_HMI": 5,
        },
        plc_blocks_cache=[],
        build_cache_root=tmp_path / ".build_cache",
    )

    assert fb.nStep == fb.n_error  # 98
    assert fb.error_msg is not None
    assert "minimos" in fb.error_msg.lower()


# ── Log de cierre (lo emite el FB, no el router) ─────────────────────


def _preview_cierres(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Mensajes OK emitidos por el FB del preview."""
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == PREVIEW_LOGGER and record.levelno == OK_LEVEL
    ]


def test_preview_emite_el_log_de_cierre_con_los_valores_reales(
    plantilla_dummy: Path,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """El FB emite el log de cierre con los contadores reales.

    El router responde 202 antes de que el preview se ejecute, asi que
    el cierre lo hace el FB (que ya tiene ``self.result``). El mensaje
    debe llevar el numero real de archivos previstos, no un cero.
    """
    fb = FunctionProcCrearGenerarPreview(
        nombre="proc_process_crear_preview_log_test",
        config_manager=MagicMock(),
        tia_client=MagicMock(),  # el preview NO toca TIA
        build_cache=MagicMock(),
        tracker=ProgressTracker(),
    )

    with caplog.at_level(logging.DEBUG, logger=PREVIEW_LOGGER):
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
            plc_blocks_cache=[],
            build_cache_root=tmp_path / ".build_cache",
        )

    assert fb.nStep == fb.n_done  # 99
    n_previstos = len(fb.result["archivos_previstos"])
    n_colisiones = len(fb.result["colisiones"])
    # La plantilla dummy tiene 1 FC y 1 bloque de comentarios: 2 entries.
    assert n_previstos == 2
    assert n_colisiones == 0
    assert _preview_cierres(caplog) == [
        f"Preview crear proceso 60010/EXP: "
        f"{n_previstos} archivos previstos, {n_colisiones} colision(es)."
    ]


def test_preview_no_emite_el_log_de_cierre_si_falla(
    plantilla_dummy: Path,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Si el preview falla, no hay log de cierre: solo el error.

    El log de cierre se reserva al trabajo que termina bien; el error
    ya lo emite la base del FB.
    """
    fb = FunctionProcCrearGenerarPreview(
        nombre="proc_process_crear_preview_log_error_test",
        config_manager=MagicMock(),
        tia_client=MagicMock(),
        build_cache=MagicMock(),
        tracker=ProgressTracker(),
    )

    with caplog.at_level(logging.DEBUG, logger=PREVIEW_LOGGER):
        fb.execute(
            plantillas_path=str(plantilla_dummy.parent),
            dir_plantilla_nombre="TestPlantilla",
            base_nueva=60010,
            codigo_nuevo="EXP",
            nombre_nuevo="NuevoProceso",
            # N_MAX_PREAL=1 < plantilla (3) -> falla validar_minimos.
            minimos_usuario={
                "N_MAX_PREAL": 1, "N_MAX_PINT": 30,
                "N_MAX_ALM": 30, "N_MAX_ALM_HMI": 5,
            },
            plc_blocks_cache=[],
            build_cache_root=tmp_path / ".build_cache",
        )

    assert fb.nStep == fb.n_error  # 98
    assert fb.error_msg is not None
    assert _preview_cierres(caplog) == []
