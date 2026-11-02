"""Test de integracion del flujo completo: HMI -> OB1 -> FB -> push.

Es el contrato de los tres pilares:

  1. El router (HMI) encola el trabajo con ``engine.submit()`` y
     responde ``202`` con el ``job_id``, sin bloquear.
  2. El OB1 (dispatcher del Engine) consume la cola y ejecuta el FB
     completo con ``fb.execute()``, sin event loop.
  3. El resultado llega al HMI por push: el evento SSE ``fb_state`` con
     el ``job_id`` del trabajo y el ``result`` del FB.

Este test ejercita los tres pilares de verdad (Engine real, bus real,
FB real), no mocks del dispatcher.
"""
from __future__ import annotations

import queue
from typing import Any

from core.composition.fb_step import step
from core.composition.plc_engine import Engine
from core.composition.plc_function_base import FunctionBase
from core.runtime.progress_buffer import ProgressTracker
from core.runtime.sse.sse_event_bus_sync import EventBusSync
from core.runtime.sse.sse_publishers import make_fb_state_publisher


class _DemoFB(FunctionBase):
    """FB de demo: 2 steps sync que no tocan TIA."""

    def __init__(self, nombre: str = "demo_fb") -> None:
        super().__init__(
            nombre=nombre,
            titulo="FB de demo",
            tracker=ProgressTracker(),
        )
        self.detalle: list[str] = []

    @step("uno", descripcion="Primer paso de demo")
    def _stage_1_uno(self) -> str:
        self.detalle.append("uno")
        return "hecho uno"

    @step("dos", descripcion="Segundo paso de demo")
    def _stage_2_dos(self) -> str:
        self.detalle.append("dos")
        return "hecho dos"

    def on_finish(self, **params: Any) -> None:
        self.result = {"ok": True, "pasos": list(self.detalle)}


def _drenar(q: queue.Queue) -> list[dict[str, Any]]:
    """Saca todos los eventos pendientes del suscriptor."""
    eventos = []
    while True:
        try:
            eventos.append(q.get_nowait())
        except queue.Empty:
            return eventos


def test_flujo_completo_hmi_ob1_fb_push() -> None:
    bus = EventBusSync()
    suscriptor = bus.subscribe()

    engine = Engine()
    fb = _DemoFB()
    engine.register_fb("demo_fb", fb)
    engine.on_fb_change = make_fb_state_publisher(bus, engine)

    # 1. HMI: el router encola el trabajo y devuelve el job_id.
    job_id = engine.submit("demo_fb")
    assert job_id
    assert engine.get_job(job_id).status == "queued"

    # 2. OB1: el dispatcher arranca y ejecuta el FB.
    engine.start_ob1()
    try:
        job = engine.get_job(job_id)
        limite = 5.0
        transcurrido = 0.0
        while job.status not in ("done", "error", "cancelled") and transcurrido < limite:
            import time
            time.sleep(0.02)
            transcurrido += 0.02
            job = engine.get_job(job_id)
    finally:
        engine.stop_ob1()

    assert job.status == "done", job.error
    assert job.result == {"ok": True, "pasos": ["uno", "dos"]}
    assert engine.jobs_processed == 1

    # 3. Push: el HMI recibe el estado del FB por SSE, con el job_id.
    eventos = _drenar(suscriptor)
    fb_states = [e for e in eventos if e.get("type") == "fb_state"]
    assert fb_states, eventos

    terminal = [e for e in fb_states if e.get("is_terminal")]
    assert terminal, fb_states
    assert terminal[-1]["job_id"] == job_id
    assert terminal[-1]["name"] == "demo_fb"
    assert terminal[-1]["result"] == {"ok": True, "pasos": ["uno", "dos"]}
    assert terminal[-1]["error_msg"] is None
