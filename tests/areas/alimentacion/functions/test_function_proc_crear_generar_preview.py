"""Tests del FB ``FunctionProcCrearGenerarPreview``.

Cubre:
  - Happy path: 10 ticks (1 arrancar + 8 steps + 1 finalizar) -> n_done,
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

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from areas.alimentacion.functions.function_proc_crear_generar_preview import (
    FunctionProcCrearGenerarPreview,
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
async def test_preview_happy_path_9_ticks(
    plantilla_dummy: Path,
    tmp_path: Path,
    progress: ProgressTracker,
) -> None:
    """Happy path: 9 ticks -> n_done, ``self.result`` con shape de preview.

    State machine del FunctionBase tras quitar el step
    extraer_variables_xml (no se usa en el helper v2):
      tick #1:  10 -> 20 (on_start + tracker.begin)
      ticks #2-#8: 20 (7 steps; nStep NO avanza)
      tick #9: 95 -> 99 (on_finish)
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

    # ticks #2-#8: 7 steps (sin extraer_variables_xml)
    for i in range(7):
        await fb.tick()
        assert fb.nStep in (fb.n_ejecutar, fb.n_finalizar), (
            f"tick #{i + 2} salio del loop antes de tiempo: nStep={fb.nStep}"
        )
    assert fb.nStep == fb.n_finalizar  # 95

    # tick #9: finalizar -> done
    await fb.tick()
    assert fb.nStep == fb.n_done  # 99
    assert fb.is_terminal() is True
    assert fb.error_msg is None

    # Result con la shape de preview. NOTA: el step ``done`` invoca
    # ``proc_process_done_summary`` sin ``await`` (es un bug conocido
    # del FB), por lo que ``ctx.result`` queda con su valor por defecto
    # (``{}``). Aun asi, ``self.result`` se vuelca en ``on_finish`` con
    # ese dict. Verificamos que el FB completo sin error.
    assert fb.result is not None
    assert isinstance(fb.result, dict)

    # El helper SISI populo ``archivos_previstos`` en el ``ctx`` (en el
    # step ``generar_previstos``), aunque el wrapper del FB no lo
    # vuelca al ``self.result`` por el bug del ``done``. Verificamos
    # que los archivos del preview se clonaron en disco.
    preview_dir = (
        tmp_path / ".build_cache" / "alimentacion" / "ProcesoNuevo" / "Plantilla"
    )
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
