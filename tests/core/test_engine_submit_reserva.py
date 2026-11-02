"""Reserva de FB en ``Engine.submit()``.

Un FB solo admite un trabajo en curso. La comprobacion de ocupacion
tiene que hacerse sobre los **trabajos** (``queued`` / ``running``), no
sobre el estado ``nStep`` del FB: ese estado no cambia hasta que el
dispatcher empieza a ejecutarlo, asi que entre el ``submit()`` y el
arranque del trabajo el FB sigue apareciendo como terminal y admitia un
segundo trabajo. Con dos trabajos encolados del mismo FB, el OB1 lo
ejecuta dos veces (doble sincronizacion contra TIA).

Estos tests fijan ese comportamiento.
"""
from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from core.composition.fb_step import step
from core.composition.plc_engine import Engine, FBBusyError
from core.composition.plc_function_base import FunctionBase
from core.runtime.progress_buffer import ProgressTracker


class _ContadorFB(FunctionBase):
    """FB de un solo step que cuenta sus ejecuciones."""

    def __init__(self, nombre: str = "contador") -> None:
        super().__init__(
            nombre=nombre,
            titulo="Contador",
            tracker=ProgressTracker(),
        )
        self.ejecuciones = 0

    @step("uno", descripcion="Cuenta una ejecucion")
    def _stage_1_uno(self) -> str:
        self.ejecuciones += 1
        return f"ejecucion {self.ejecuciones}"

    def on_finish(self, **params: Any) -> None:
        self.result = {"ejecuciones": self.ejecuciones}


def _esperar_terminal(engine: Engine, job_id: str, timeout: float = 5.0) -> None:
    """Espera a que el trabajo llegue a un estado terminal."""
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        job = engine.get_job(job_id)
        if job is not None and job.status in ("done", "error", "cancelled"):
            return
        time.sleep(0.01)
    raise AssertionError(f"el trabajo {job_id} no llego a estado terminal")


def test_el_segundo_submit_del_mismo_fb_se_rechaza() -> None:
    engine = Engine()
    engine.register_fb("contador", _ContadorFB())

    job_id = engine.submit("contador")
    assert job_id

    with pytest.raises(FBBusyError):
        engine.submit("contador")


def test_el_fb_se_ejecuta_una_sola_vez() -> None:
    """El bug: dos submits pasaban los dos y el FB corria dos veces."""
    engine = Engine()
    fb = _ContadorFB()
    engine.register_fb("contador", fb)

    job_id = engine.submit("contador")
    engine.start_ob1()
    try:
        _esperar_terminal(engine, job_id)
    finally:
        engine.stop_ob1()

    assert fb.ejecuciones == 1
    assert engine.get_job(job_id).status == "done"


def test_submits_simultaneos_del_mismo_fb_solo_aceptan_uno() -> None:
    """Dos peticiones HTTP simultaneas al mismo FB (doble clic)."""
    engine = Engine()
    engine.register_fb("contador", _ContadorFB())

    n = 8
    barrera = threading.Barrier(n)
    aceptados: list[str] = []
    rechazados: list[Exception] = []
    lock = threading.Lock()

    def intento() -> None:
        barrera.wait()
        try:
            job_id = engine.submit("contador")
        except FBBusyError as exc:
            with lock:
                rechazados.append(exc)
        else:
            with lock:
                aceptados.append(job_id)

    hilos = [threading.Thread(target=intento) for _ in range(n)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=10)

    assert len(aceptados) == 1, f"se aceptaron {len(aceptados)} trabajos"
    assert len(rechazados) == n - 1


def test_fbs_distintos_se_pueden_encolar_a_la_vez() -> None:
    engine = Engine()
    engine.register_fb("contador_a", _ContadorFB("contador_a"))
    engine.register_fb("contador_b", _ContadorFB("contador_b"))

    job_a = engine.submit("contador_a")
    job_b = engine.submit("contador_b")

    assert job_a != job_b


def test_cancelar_el_trabajo_en_cola_libera_el_fb() -> None:
    """El FB se puede relanzar si el trabajo en cola se cancela."""
    engine = Engine()
    engine.register_fb("contador", _ContadorFB())

    job_id = engine.submit("contador")
    assert engine.cancel_job(job_id, "prueba")

    nuevo = engine.submit("contador")
    assert nuevo != job_id


def test_fb_desconocido_sigue_siendo_error() -> None:
    engine = Engine()
    with pytest.raises(FBBusyError):
        engine.submit("no_existe")
