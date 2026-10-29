"""Tests del Engine (dispatcher OB1): cola, hilo ejecutor y hook de cambios.

Cubre el camino de ejecucion vigente: ``submit()`` encola el trabajo,
el hilo ``plc-ob1`` lo ejecuta completo con ``fb.execute()``, y el hook
``on_fb_change`` notifica cada cambio de nStep (el canal del push al
HMI).
"""
from __future__ import annotations

import threading
import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.composition.plc_engine import Engine, FBBusyError
from core.composition.plc_function_base import FunctionBase


def test_el_hook_on_fb_change_se_invoca_en_cada_cambio_de_nstep():
    """El dispatcher notifica al bus cada vez que el FB cambia de nStep.

    El Engine expone un hook ``on_fb_change(name, fb)`` que el caller
    (tipicamente el publisher SSE) cablea. ``register_fb()`` lo conecta
    a ``fb._on_nstep_change`` para que cualquier cambio de nStep se
    retransmita automaticamente: es el canal por el que el HMI recibe el
    estado del trabajo.
    """
    on_change = MagicMock()
    engine = Engine()
    engine.on_fb_change = on_change

    fb = _RealFB()
    engine.register_fb("real_fb", fb)

    job_id = engine.submit("real_fb")
    engine.start_ob1()
    try:
        _wait_terminal(engine, job_id)
    finally:
        engine.stop_ob1()

    assert on_change.called, "el hook no recibio ninguna notificacion"
    nombres = [call.args[0] for call in on_change.call_args_list]
    assert "real_fb" in nombres


def test_el_engine_no_expone_la_api_de_tick():
    """El unico camino de ejecucion es el dispatcher OB1.

    El camino por tick (start_loop / stop_loop / tick_once / run_cycle)
    se retiró: el Engine solo encola trabajos y su hilo los ejecuta.
    """
    engine = Engine()
    for nombre in ("start_loop", "stop_loop", "tick_once", "run_cycle"):
        assert not hasattr(engine, nombre), (
            f"el Engine sigue exponiendo {nombre}()"
        )


# ------------------------------------------------------------------
# OB1: cola de trabajos + hilo dispatcher
# ------------------------------------------------------------------

_TERMINAL = ("done", "error", "cancelled", "busy")


def _mock_fb(*, result: object = "ok", error_msg: str | None = None) -> MagicMock:
    """FB mock con el contrato minimo que consume el dispatcher.

    ``MagicMock(spec=FunctionBase)`` deja ``is_terminal()`` como un
    MagicMock (truthy) y no expone los atributos de instancia
    (``error_msg`` / ``nStep``), asi que se configuran a mano.
    """
    fb = MagicMock(spec=FunctionBase)
    fb.is_terminal.return_value = True
    fb.error_msg = error_msg
    fb.nStep = FunctionBase.n_idle
    fb.request_cancel.return_value = True
    fb.execute.return_value = result
    return fb


class _RealFB(FunctionBase):
    """FB de verdad (no mock) para comprobar el cableado del hook.

    Un ``MagicMock(spec=FunctionBase)`` no ejecuta el metodo real, asi
    que para comprobar que la notificacion de cambios llega al bus
    hace falta un FB de verdad.
    """

    def __init__(self, nombre: str = "real_fb") -> None:
        super().__init__(nombre=nombre, titulo="FB real", steps=["p1"])

    def run_step(self, idx: int, **params: Any) -> str:
        return f"paso {idx}"


def _wait_until(
    engine: Engine,
    job_id: str,    predicate,
    timeout_s: float = 5.0,
):
    """Polling: espera a que el job cumpla ``predicate``.

    Devuelve el ultimo estado visto (puede no ser terminal si se
    agota el timeout).
    """
    deadline = time.monotonic() + timeout_s
    job = engine.get_job(job_id)
    while time.monotonic() < deadline:
        job = engine.get_job(job_id)
        if job is not None and predicate(job):
            return job
        time.sleep(0.02)
    return job


def _wait_terminal(engine: Engine, job_id: str, timeout_s: float = 5.0):
    """Polling: espera a que el job llegue a un estado terminal."""
    return _wait_until(
        engine, job_id, lambda j: j.status in _TERMINAL, timeout_s=timeout_s,
    )


def test_submit_devuelve_job_id_y_deja_el_job_en_cola():
    """submit() encola el trabajo y devuelve un job_id opaco y unico."""
    engine = Engine()
    engine.register_fb("fb_a", _mock_fb())

    job_id = engine.submit("fb_a", ruta="x")

    assert isinstance(job_id, str)
    assert job_id != ""
    jobs = engine.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].job_id == job_id
    assert jobs[0].status == "queued"
    assert jobs[0].fb_name == "fb_a"
    assert jobs[0].params == {"ruta": "x"}
    assert engine.get_job(job_id) is jobs[0]


def test_submit_con_fb_desconocido_lanza_fbbusyerror():
    """Un FB que no existe no se encola: FBBusyError."""
    engine = Engine()

    with pytest.raises(FBBusyError):
        engine.submit("no_existe")

    assert engine.list_jobs() == []


def test_submit_con_fb_activo_lanza_fbbusyerror_y_no_encola():
    """Un FB con una ejecucion en curso rechaza el trabajo nuevo."""
    engine = Engine()
    fb = _mock_fb()
    fb.is_terminal.return_value = False
    fb.nStep = FunctionBase.n_ejecutar
    engine.register_fb("fb_ocupado", fb)

    with pytest.raises(FBBusyError):
        engine.submit("fb_ocupado")

    assert engine.list_jobs() == []


def test_cancel_job_de_job_en_cola_lo_marca_cancelled():
    """Cancelar un job en cola lo cierra sin llegar a ejecutarse."""
    engine = Engine()
    fb = _mock_fb()
    engine.register_fb("fb_a", fb)

    job_id = engine.submit("fb_a")
    assert engine.cancel_job(job_id, reason="parada manual") is True

    job = engine.get_job(job_id)
    assert job is not None
    assert job.status == "cancelled"
    assert job.error == "parada manual"
    assert job.finished_at is not None
    # El FB no se ha ejecutado: el job se cancelo en la cola.
    fb.execute.assert_not_called()


def test_cancel_job_con_job_id_inexistente_devuelve_false():
    """Un job_id que no existe no se puede cancelar."""
    engine = Engine()

    assert engine.cancel_job("no-existe") is False


def test_ob1_ejecuta_el_job_y_lo_deja_en_done():
    """El hilo dispatcher ejecuta el FB y el job acaba en done."""
    engine = Engine()
    fb = _mock_fb(result={"ok": True})
    engine.register_fb("fb_a", fb)

    job_id = engine.submit("fb_a", ruta="datos.xlsx")
    engine.start_ob1()
    try:
        job = _wait_terminal(engine, job_id)
    finally:
        engine.stop_ob1()

    assert job is not None
    assert job.status == "done"
    assert job.result == {"ok": True}
    assert job.error is None
    assert job.finished_at is not None
    assert job.started_at is not None
    fb.execute.assert_called_once_with(ruta="datos.xlsx")


def test_ob1_job_con_error_queda_en_error_y_el_hilo_sigue_vivo():
    """Si el FB revienta, el job queda en error y el dispatcher sobrevive."""
    engine = Engine()
    fb_roto = _mock_fb()
    fb_roto.execute.side_effect = RuntimeError("boom")
    engine.register_fb("fb_roto", fb_roto)
    fb_ok = _mock_fb(result="listo")
    engine.register_fb("fb_ok", fb_ok)

    job_id = engine.submit("fb_roto")
    engine.start_ob1()
    try:
        job = _wait_terminal(engine, job_id)
        assert job is not None
        assert job.status == "error"
        assert "boom" in (job.error or "")
        assert engine.ob1_running() is True

        # El dispatcher sigue vivo: acepta y ejecuta otro trabajo.
        job_id_2 = engine.submit("fb_ok")
        job2 = _wait_terminal(engine, job_id_2)
    finally:
        engine.stop_ob1()

    assert job2 is not None
    assert job2.status == "done"
    assert job2.result == "listo"


def test_stop_ob1_es_idempotente_y_deja_el_hilo_parado():
    """stop_ob1() se puede llamar varias veces y deja ob1_running() False."""
    engine = Engine()
    engine.register_fb("fb_a", _mock_fb())

    engine.start_ob1()
    assert engine.ob1_running() is True

    engine.stop_ob1()
    assert engine.ob1_running() is False

    # Idempotente: segunda y tercera llamada no fallan.
    engine.stop_ob1()
    engine.stop_ob1()
    assert engine.ob1_running() is False


def test_current_job_for_devuelve_el_job_en_curso_y_luego_none():
    """current_job_for() apunta al job en curso mientras dura."""
    engine = Engine()
    gate = threading.Event()
    fb = _mock_fb()

    def _execute_bloqueante(**_params):
        gate.wait(timeout=5.0)
        return "listo"

    fb.execute.side_effect = _execute_bloqueante
    engine.register_fb("fb_a", fb)

    job_id = engine.submit("fb_a")
    engine.start_ob1()
    try:
        job = _wait_until(engine, job_id, lambda j: j.status == "running")
        assert job is not None
        assert job.status == "running"
        assert engine.current_job_for("fb_a") is job
        # Otro FB no tiene job en curso.
        assert engine.current_job_for("fb_b") is None
    finally:
        gate.set()
        engine.stop_ob1()

    _wait_terminal(engine, job_id)
    assert engine.current_job_for("fb_a") is None


def test_jobs_processed_cuenta_los_trabajos_cerrados():
    """Cada trabajo que el dispatcher lleva a terminal cuenta un ciclo."""
    engine = Engine()
    engine.register_fb("fb_a", _mock_fb(result="listo"))

    assert engine.jobs_processed == 0

    job_id = engine.submit("fb_a")
    engine.start_ob1()
    try:
        job = _wait_terminal(engine, job_id)
    finally:
        engine.stop_ob1()

    assert job is not None
    assert job.status == "done"
    assert engine.jobs_processed == 1


def test_jobs_processed_cuenta_tambien_los_trabajos_fallidos():
    """Un trabajo que termina en error tambien es un ciclo del OB1."""
    engine = Engine()
    engine.register_fb("fb_a", _mock_fb(error_msg="boom"))

    job_id = engine.submit("fb_a")
    engine.start_ob1()
    try:
        job = _wait_terminal(engine, job_id)
    finally:
        engine.stop_ob1()

    assert job is not None
    assert job.status == "error"
    assert engine.jobs_processed == 1


def test_on_fb_change_asignado_tarde_cablea_los_fbs_ya_registrados():
    """El bus SSE se cablea DESPUES de registrar los FBs.

    Ese es el orden del arranque real: si el hook no se re-cablea al
    asignarlo, ningun cambio de nStep llega al bus y el push del
    resultado no funciona.
    """
    engine = Engine()
    fb = _RealFB()
    engine.register_fb("fb_a", fb)

    cambios: list[str] = []
    engine.on_fb_change = lambda name, _fb: cambios.append(name)

    fb.nStep = fb.n_ejecutar
    fb._notify_nstep_change(fb.n_idle, fb.n_ejecutar)

    assert cambios == ["fb_a"]


def test_on_fb_change_a_none_desconecta_los_fbs():
    """Poner el hook a None deja de notificar."""
    engine = Engine()
    fb = _RealFB()
    engine.register_fb("fb_a", fb)

    cambios: list[str] = []
    engine.on_fb_change = lambda name, _fb: cambios.append(name)
    engine.on_fb_change = None

    fb.nStep = fb.n_ejecutar
    fb._notify_nstep_change(fb.n_idle, fb.n_ejecutar)

    assert cambios == []
