"""zc_suite.errores — la jerarquia de errores y el nivel con el que se registran.

La app distingue dos familias de fallo:

- **Esperados** (los que el operario puede corregir): cuelgan de ``ZCError``.
  Se registran como ``WARNING`` y **sin traceback**.
- **Inesperados**: cualquier otra excepcion. Se registran como ``ERROR`` y
  **con traceback**.

Este fichero fija esa regla: si alguien mueve un error de rama o cambia la
base, el comportamiento de los logs cambia de golpe.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import pytest

from zc_suite.errores import OperacionError, ZCError
from zc_suite.nucleo.tia.errores import (
    CanceladoError,
    FueraDelHiloError,
    OcupadoError,
    SinPortalError,
    SinProyectoError,
    TIAError,
    TransaccionError,
)
from zc_suite.nucleo.tia.job import Job
from zc_suite.nucleo.tia.servicio import ServicioTIA


class ServicioFalso:
    """El minimo que un ``Job`` necesita: publicar."""

    def __init__(self) -> None:
        self.publicado: list[tuple[str, dict[str, Any]]] = []

    def publicar(self, tipo: str, carga: dict[str, Any]) -> None:
        """Guarda lo publicado."""
        self.publicado.append((tipo, carga))


def _job() -> Job:
    """Un trabajo con un paso declarado."""
    job = Job(job_id="j1", operacion="prueba", servicio=ServicioFalso())
    job.empezar("Trabajo", ["uno"])
    return job


# ── la jerarquia ───────────────────────────────────────────────────────────


def test_los_errores_de_tia_cuelgan_de_la_base_neutra() -> None:
    """``TIAError`` hereda de ``ZCError``."""
    assert issubclass(TIAError, ZCError)


def test_operacion_error_no_es_un_error_de_tia() -> None:
    """``OperacionError`` es neutro: no depende de TIA.

    Es lo que permite que la logica pura de los dominios lance fallos
    esperados sin importar nada de ``nucleo.tia``.
    """
    assert issubclass(OperacionError, ZCError)
    assert not issubclass(OperacionError, TIAError)


def test_los_errores_de_tia_son_de_tia() -> None:
    """Los errores propios del subsistema cuelgan de ``TIAError``."""
    for error in (
        CanceladoError,
        FueraDelHiloError,
        OcupadoError,
        SinPortalError,
        SinProyectoError,
        TransaccionError,
    ):
        assert issubclass(error, TIAError)


# ── el nivel del log ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "error",
    [
        OperacionError("el fichero no esta"),
        SinProyectoError("no hay proyecto abierto"),
        TransaccionError("fallo el commit"),
    ],
)
def test_un_fallo_esperado_se_registra_como_warning_sin_traceback(
    error: Exception,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Un ``ZCError`` se registra en una linea, sin traceback."""
    job = _job()

    with caplog.at_level(logging.WARNING), pytest.raises(type(error)), job.paso("uno"):
        raise error

    registros = [r for r in caplog.records if r.name == "zc_suite.nucleo.tia.job"]
    assert registros
    assert all(r.levelno == logging.WARNING for r in registros)
    assert all(not r.exc_info for r in registros)


def test_una_excepcion_inesperada_se_registra_como_error_con_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Lo que no es un ``ZCError`` se registra con traceback."""
    job = _job()

    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError), job.paso("uno"):
        raise RuntimeError("reventon inesperado")

    registros = [r for r in caplog.records if r.name == "zc_suite.nucleo.tia.job"]
    assert any(r.levelno == logging.ERROR for r in registros)


def test_el_servicio_registra_un_fallo_esperado_sin_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """El hilo de TIA distingue tambien los dos casos.

    Un ``OperacionError`` (fallo esperado) sale como ``WARNING`` y sin
    traceback; lo inesperado sale como ``ERROR`` y con traceback.
    """
    eventos: list[tuple[str, dict[str, Any]]] = []
    servicio = ServicioTIA(publicador=lambda tipo, carga: eventos.append((tipo, carga)))
    servicio.arrancar()

    def trabajo(job: Job) -> dict[str, Any]:
        job.empezar("Trabajo", ["uno"])
        with job.paso("uno"):
            raise OperacionError("el Excel no esta")
        return {}

    try:
        with caplog.at_level(logging.WARNING):
            job_id = servicio.lanzar(trabajo)
            limite = time.monotonic() + 5.0
            while time.monotonic() < limite:
                if any(tipo == "job" and carga["job"] == job_id for tipo, carga in eventos):
                    break
                time.sleep(0.005)
    finally:
        servicio.parar()

    registros = [r for r in caplog.records if r.name.startswith("zc_suite.nucleo.tia")]
    fallos = [r for r in registros if r.levelno == logging.WARNING]
    assert fallos
    assert all(not r.exc_info for r in fallos)
    assert not any(r.levelno == logging.ERROR for r in registros)
