"""El contrato de ``Job``: pasos, progreso, cancelacion y nivel del log.

Ningun test toca TIA de verdad: el modulo ``siemens_tia_scripting`` y el
portal son dobles propios (los define ``conftest.py``).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from zc_suite.nucleo.tia import servicio as tia

RAIZ = Path(__file__).resolve().parents[3]


def test_empezar_declara_todos_los_pasos(
    entorno: Any,
    esperar_job: Callable[..., Any],
    eventos_de: Callable[..., Any],
    trabajo_con_pasos: Callable[..., Any],
) -> None:
    servicio, _ts, eventos = entorno

    job_id = servicio.lanzar(trabajo_con_pasos)
    esperar_job(eventos, job_id)

    avances = eventos_de(eventos, "progress")
    inicial = avances[0]
    assert inicial["active"] is True
    assert inicial["total"] == 2
    assert inicial["current"] == 0
    assert inicial["percent"] == 0
    assert [etapa["id"] for etapa in inicial["stages"]] == ["exportar", "comparar"]
    assert all(etapa["status"] == "pending" for etapa in inicial["stages"])


def test_los_pasos_avanzan_de_running_a_done(
    entorno: Any,
    esperar_job: Callable[..., Any],
    eventos_de: Callable[..., Any],
    trabajo_con_pasos: Callable[..., Any],
) -> None:
    servicio, _ts, eventos = entorno

    job_id = servicio.lanzar(trabajo_con_pasos)
    esperar_job(eventos, job_id)

    estados = [
        (etapa["id"], etapa["status"])
        for carga in eventos_de(eventos, "progress")
        for etapa in carga["stages"]
    ]
    assert ("exportar", "running") in estados
    assert ("exportar", "done") in estados
    assert ("comparar", "done") in estados


def test_el_detalle_del_paso_se_publica(
    entorno: Any,
    esperar_job: Callable[..., Any],
    eventos_de: Callable[..., Any],
    trabajo_con_pasos: Callable[..., Any],
) -> None:
    servicio, _ts, eventos = entorno

    job_id = servicio.lanzar(trabajo_con_pasos)
    esperar_job(eventos, job_id)

    detalles = [
        etapa["detail"]
        for carga in eventos_de(eventos, "progress")
        for etapa in carga["stages"]
        if etapa["id"] == "exportar"
    ]
    assert "3 bloques" in detalles


def test_el_progreso_final_cierra_el_trabajo(
    entorno: Any,
    esperar_job: Callable[..., Any],
    eventos_de: Callable[..., Any],
    trabajo_con_pasos: Callable[..., Any],
) -> None:
    servicio, _ts, eventos = entorno

    job_id = servicio.lanzar(trabajo_con_pasos)
    esperar_job(eventos, job_id)

    finales = [carga for carga in eventos_de(eventos, "progress") if carga["active"] is False]
    assert finales
    assert finales[-1]["finished_at"] is not None
    assert finales[-1]["current"] == 2
    assert finales[-1]["percent"] == 100


def test_un_paso_no_declarado_falla(entorno: Any, esperar_job: Callable[..., Any]) -> None:
    servicio, _ts, eventos = entorno

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["uno"])
        with job.paso("otro"):
            pass
        return {}

    job_id = servicio.lanzar(trabajo)
    evento = esperar_job(eventos, job_id)

    assert evento["estado"] == "error"
    assert "otro" in str(evento["error"])


def test_la_excepcion_de_un_paso_marca_error_y_relanza(
    entorno: Any,
    esperar_job: Callable[..., Any],
    eventos_de: Callable[..., Any],
) -> None:
    servicio, _ts, eventos = entorno

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["uno"])
        with job.paso("uno"):
            raise ValueError("reventon")
        return {}

    job_id = servicio.lanzar(trabajo)
    evento = esperar_job(eventos, job_id)

    assert evento["estado"] == "error"
    assert "reventon" in str(evento["error"])
    etapas = evento["resultado"] if evento["resultado"] else None
    assert etapas is None
    estados = [
        etapa["status"]
        for carga in eventos_de(eventos, "progress")
        for etapa in carga["stages"]
        if etapa["id"] == "uno"
    ]
    assert "error" in estados


def test_la_cancelacion_se_respeta_entre_pasos(
    entorno: Any,
    esperar_job: Callable[..., Any],
) -> None:
    servicio, _ts, eventos = entorno
    arranque = threading.Event()

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["uno", "dos"])
        with job.paso("uno"):
            arranque.set()
            job.cancelar()
        with job.paso("dos"):
            pass
        return {}

    job_id = servicio.lanzar(trabajo)
    evento = esperar_job(eventos, job_id)

    assert arranque.wait(5.0)
    assert evento["estado"] == "cancelado"


def test_el_log_del_trabajo_se_publica(
    entorno: Any,
    esperar_job: Callable[..., Any],
    eventos_de: Callable[..., Any],
) -> None:
    servicio, _ts, eventos = entorno

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["uno"])
        job.log("mensaje de operario")
        with job.paso("uno"):
            pass
        return {}

    job_id = servicio.lanzar(trabajo)
    esperar_job(eventos, job_id)

    logs = eventos_de(eventos, "log")
    assert any(carga["mensaje"] == "mensaje de operario" for carga in logs)


def test_un_paso_fallido_deja_el_error_en_su_detail(
    entorno: Any,
    esperar_job: Callable[..., Any],
    eventos_de: Callable[..., Any],
) -> None:
    """El faceplate tiene que decir por que fallo el paso."""
    servicio, ts, eventos = entorno
    ts.error_attach = "No matching TIA Portal version could be found."

    job_id = servicio.lanzar(tia.conectar)
    esperar_job(eventos, job_id)

    detalles = [
        etapa["detail"]
        for carga in eventos_de(eventos, "progress")
        for etapa in carga["stages"]
        if etapa["id"] == "abrir_portal"
    ]
    assert any(d and "TIA Portal abierto" in d for d in detalles)


def test_un_tia_error_se_registra_como_warning_sin_traceback(
    entorno: Any,
    caplog: pytest.LogCaptureFixture,
    esperar_job: Callable[..., Any],
) -> None:
    servicio, ts, eventos = entorno
    ts.error_attach = "No matching TIA Portal version could be found."

    with caplog.at_level(logging.WARNING):
        job_id = servicio.lanzar(tia.conectar)
        esperar_job(eventos, job_id)

    registros = [r for r in caplog.records if r.name.startswith("zc_suite.nucleo.tia")]
    assert registros
    assert all(r.levelno == logging.WARNING for r in registros)
    assert all(not r.exc_info for r in registros)


def test_una_excepcion_inesperada_si_lleva_traceback(
    entorno: Any,
    caplog: pytest.LogCaptureFixture,
    esperar_job: Callable[..., Any],
) -> None:
    servicio, _ts, eventos = entorno

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["uno"])
        with job.paso("uno"):
            raise RuntimeError("reventon inesperado")
        return {}

    with caplog.at_level(logging.ERROR):
        job_id = servicio.lanzar(trabajo)
        esperar_job(eventos, job_id)

    registros = [r for r in caplog.records if r.name.startswith("zc_suite.nucleo.tia")]
    assert any(r.levelno == logging.ERROR for r in registros)
    assert any(r.exc_info for r in registros)


def test_empezar_acepta_identificadores_solos(
    entorno: Any,
    esperar_job: Callable[..., Any],
    eventos_de: Callable[..., Any],
) -> None:
    servicio, _ts, eventos = entorno

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", ["exportar", "comparar"])
        with job.paso("exportar"):
            pass
        return {}

    job_id = servicio.lanzar(trabajo)
    esperar_job(eventos, job_id)

    avances = eventos_de(eventos, "progress")
    etapas = avances[0]["stages"]
    assert [e["id"] for e in etapas] == ["exportar", "comparar"]
    assert [e["label"] for e in etapas] == ["Exportar", "Comparar"]


def test_empezar_acepta_etiquetas_por_paso(
    entorno: Any,
    esperar_job: Callable[..., Any],
    eventos_de: Callable[..., Any],
) -> None:
    servicio, _ts, eventos = entorno

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar(
            "Trabajo",
            [("cargar_sdk", "Cargar SDK"), ("abrir_portal", "Enganchar TIA Portal")],
        )
        with job.paso("cargar_sdk"):
            pass
        return {}

    job_id = servicio.lanzar(trabajo)
    esperar_job(eventos, job_id)

    avances = eventos_de(eventos, "progress")
    etapas = avances[0]["stages"]
    assert [e["id"] for e in etapas] == ["cargar_sdk", "abrir_portal"]
    assert [e["label"] for e in etapas] == ["Cargar SDK", "Enganchar TIA Portal"]


def test_los_pasos_repetidos_siguen_fallando(entorno: Any, esperar_job: Callable[..., Any]) -> None:
    servicio, _ts, eventos = entorno

    def trabajo(job: Any) -> dict[str, Any]:
        job.empezar("Trabajo", [("a", "A"), ("a", "A otra vez")])
        return {}

    job_id = servicio.lanzar(trabajo)
    evento = esperar_job(eventos, job_id)

    assert evento["estado"] == "error"
    assert "repetidos" in str(evento["error"])
