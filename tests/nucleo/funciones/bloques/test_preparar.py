"""Tests del FB que prepara los bloques del editor."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from zc_suite.nucleo.funciones.bloques.preparar import preparar


def test_preparar_en_v21_exporta_y_parsea(
    entorno: Any,
    esperar_job: Callable[[list[tuple[str, dict[str, Any]]], str], dict[str, Any]],
    pasos: Callable[[list[tuple[str, dict[str, Any]]]], list[str]],
) -> None:
    servicio, _ts, bloques, eventos = entorno

    job_id = servicio.lanzar(preparar, plc="ZC_PLC_STD", nombres=["DB10"])
    evento = esperar_job(eventos, job_id)

    assert evento["estado"] == "ok"
    assert pasos(eventos) == ["validar", "leer", "exportar", "parsear", "combinar"]
    assert bloques[0].exportado is True
    preparado = evento["resultado"]["bloques"][0]
    assert preparado["extended"]["title"] == "El titulo"
    assert preparado["extended"]["comment"] == "El comentario"


def test_preparar_en_v18_salta_la_exportacion(
    entorno_v18: Any,
    esperar_job: Callable[[list[tuple[str, dict[str, Any]]], str], dict[str, Any]],
    pasos: Callable[[list[tuple[str, dict[str, Any]]]], list[str]],
) -> None:
    servicio, _ts, bloques, eventos = entorno_v18

    job_id = servicio.lanzar(preparar, plc="ZC_PLC_STD", nombres=["DB10"])
    evento = esperar_job(eventos, job_id)

    assert evento["estado"] == "ok"
    assert pasos(eventos) == ["validar", "leer", "combinar"]
    assert bloques[0].exportado is False
    preparado = evento["resultado"]["bloques"][0]
    assert preparado["extended"]["comment"] == ""
    assert preparado["extended"]["title"] is None


def test_preparar_sin_bloques_falla(
    entorno: Any,
    esperar_job: Callable[[list[tuple[str, dict[str, Any]]], str], dict[str, Any]],
) -> None:
    servicio, _ts, _bloques, eventos = entorno

    job_id = servicio.lanzar(preparar, plc="ZC_PLC_STD", nombres=[])
    evento = esperar_job(eventos, job_id)

    assert evento["estado"] == "error"
    assert "No hay bloques seleccionados" in evento["error"]


def test_preparar_deja_los_ficheros_para_inspeccionarlos(
    entorno: Any,
    esperar_job: Callable[[list[tuple[str, dict[str, Any]]], str], dict[str, Any]],
    tmp_path: Path,
) -> None:
    """Los ficheros exportados se quedan, para poder mirar por que fallo."""
    servicio, _ts, _bloques, eventos = entorno
    preview = tmp_path / "editor_bloques" / "preview"

    job_id = servicio.lanzar(preparar, plc="ZC_PLC_STD", nombres=["DB10"])
    esperar_job(eventos, job_id)

    assert (preview / "DB10.s7dcl").is_file()
    assert (preview / "DB10.s7res").is_file()


def test_preparar_vacia_el_preview_al_empezar(
    entorno: Any,
    esperar_job: Callable[[list[tuple[str, dict[str, Any]]], str], dict[str, Any]],
    tmp_path: Path,
) -> None:
    """Cada prepare parte de un preview limpio."""
    servicio, _ts, _bloques, eventos = entorno
    preview = tmp_path / "editor_bloques" / "preview"
    preview.mkdir(parents=True)
    (preview / "Viejo.s7dcl").write_text("x", encoding="utf-8")

    job_id = servicio.lanzar(preparar, plc="ZC_PLC_STD", nombres=["DB10"])
    esperar_job(eventos, job_id)

    assert not (preview / "Viejo.s7dcl").exists()
    assert (preview / "DB10.s7dcl").is_file()
