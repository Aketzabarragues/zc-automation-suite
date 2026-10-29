"""Tests de ``core.composition.plc_function_base.FunctionBase``.

Ciclo vigente: el dispatcher OB1 ejecuta el FB completo con
``execute(**params)`` (sync) en su hilo ``plc-ob1``. Cubre:

  - ``execute()`` recorre los steps y deja el FB en ``n_done``.
  - El tracker recibe begin/start/finish por cada etapa.
  - Un ``run_step`` que devuelve una corrutina es un error de
    programacion: ``execute()`` lo dice de forma explicita.
  - Una excepcion de runtime se captura: el FB queda en ``n_error`` con
    ``error_msg`` poblado.
  - ``NotImplementedError`` y ``AssertionError`` se propagan (errores de
    programacion, no se silencian).
  - La transicion a ``n_error`` se notifica (el HMI la ve por SSE).
  - Un step que excede el timeout deja el FB en ``n_error``.
  - Cancelacion cooperativa: ``request_cancel(reason)`` marca el flag y el
    hilo ejecutor cierra el FB en ``n_error`` al devolver el control.
  - ``execute()`` es re-arrancable, y se ignora si el FB ya esta activo o
    hay otra ejecucion en curso.
"""
from __future__ import annotations

import inspect
import threading
import time
from typing import Any

import pytest

from core.composition.plc_function_base import FunctionBase
from core.runtime.progress_buffer import ProgressTracker


# ---------------------------------------------------------------------
# Camino vigente: execute() (sync, lo conduce el dispatcher OB1)
# ---------------------------------------------------------------------


class _SyncFB(FunctionBase):
    """FB de test con ``run_step`` sync (contrato del camino vigente)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.calls: list[int] = []

    def run_step(self, idx: int, **params: Any) -> str:
        self.calls.append(idx)
        return f"paso {idx}"

    def on_finish(self, **params: Any) -> None:
        self.result = {"ok": True, "pasos": list(self.calls)}


def test_execute_happy_path() -> None:
    """``execute()`` corre el FB entero y deja ``nStep = n_done``."""
    tracker = ProgressTracker()
    fb = _SyncFB("sync_fb", "Sync FB", ["p1", "p2"], tracker=tracker)

    result = fb.execute(plc_name="PLC1")

    assert fb.nStep == fb.n_done
    assert fb.is_terminal() is True
    assert result == {"ok": True, "pasos": [0, 1]}
    assert fb.error_msg is None


def test_execute_emite_el_tracker_por_etapa() -> None:
    """El tracker recibe begin/start/finish por cada etapa."""
    tracker = ProgressTracker()
    fb = _SyncFB("sync_fb", "Sync FB", ["p1", "p2"], tracker=tracker)

    fb.execute()

    snap = tracker.snapshot()
    assert snap.operation == "sync_fb"
    assert snap.total == 2
    assert snap.current == 2
    assert snap.percent == 100
    assert snap.active is False


def test_execute_rechaza_un_run_step_async() -> None:
    """Un ``run_step`` async es un error de programacion: lo dice claro.

    Los FBs se ejecutan en el hilo del dispatcher del OB1, sin event
    loop. Si el ``run_step`` devuelve una corrutina, ``execute()`` lo
    dice explicitamente en vez de propagar la corrutina sin ejecutar.
    """
    class _AsyncFB(FunctionBase):
        async def run_step(self, idx: int, **params: Any) -> str:
            return f"async {idx}"

    fb = _AsyncFB("legacy", "Legacy", ["p1"], tracker=ProgressTracker())
    fb.execute()

    assert fb.nStep == fb.n_error
    assert "corrutina" in (fb.error_msg or "")
    assert "deben ser sync" in (fb.error_msg or "")


def test_execute_excepcion_pone_fb_en_n_error() -> None:
    """Una excepcion de runtime se captura: el FB queda en n_error."""
    class _BoomFB(FunctionBase):
        def run_step(self, idx: int, **params: Any) -> str:
            raise RuntimeError("se rompio")

    fb = _BoomFB("boom", "Boom", ["p1"], tracker=ProgressTracker())
    fb.execute()

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "RuntimeError" in fb.error_msg
    assert "se rompio" in fb.error_msg


def test_execute_notimplemented_propagates() -> None:
    """``NotImplementedError`` es error de programacion: no se silencia.

    Pero el FB NO debe quedar bricked en ``n_ejecutar``: se marca
    terminal para que no se re-intente en bucle.
    """
    fb = FunctionBase("stub", "Stub", ["p1"], tracker=ProgressTracker())
    with pytest.raises(NotImplementedError, match="run_step"):
        fb.execute()
    assert fb.nStep == fb.n_error
    assert fb.is_terminal() is True


def test_execute_notifica_la_transicion_a_error() -> None:
    """La transicion a ``n_error`` se publica (el HMI la ve por SSE)."""
    events: list[tuple[int, int]] = []

    class _BoomFB(FunctionBase):
        def run_step(self, idx: int, **params: Any) -> str:
            raise RuntimeError("boom")

    fb = _BoomFB("boom", "Boom", ["p1"], tracker=ProgressTracker())
    fb._on_nstep_change = lambda old, new: events.append((old, new))
    fb.execute()

    assert (fb.n_ejecutar, fb.n_error) in events


def test_execute_ignorado_si_hay_una_ejecucion_en_curso() -> None:
    """Un ``execute()`` concurrente se ignora: no duplica steps.

    El FB se ejecuta en el hilo del dispatcher OB1, pero puede ser
    disparado desde otro hilo mientras el primero sigue dentro de un
    step. Sin exclusion mutua, el step corria dos veces y el FB se
    quedaba en ``n_finalizar`` (no terminal).
    """
    started = threading.Event()
    gate = threading.Event()
    calls: list[int] = []

    class _BlockingFB(FunctionBase):
        def run_step(self, idx: int, **params: Any) -> str:
            calls.append(idx)
            started.set()
            gate.wait(timeout=5)
            return "ok"

    fb = _BlockingFB("bloquea", "Bloquea", ["p1", "p2"], tracker=ProgressTracker())

    runner = threading.Thread(target=fb.execute)
    runner.start()
    started.wait(timeout=5)

    segundo = fb.execute()  # segunda llamada mientras corre la primera: se omite
    gate.set()
    runner.join(timeout=5)

    assert segundo is None  # la llamada omitida no devuelve resultado
    assert calls == [0, 1]  # ningun step duplicado
    assert fb.nStep == fb.n_done
    assert fb.error_msg is None


def test_execute_timeout_de_step() -> None:
    """Un step que excede ``STEP_TIMEOUT_S`` deja el FB en n_error."""
    class _SlowFB(FunctionBase):
        def run_step(self, idx: int, **params: Any) -> str:
            time.sleep(2)
            return "tarde"

    fb = _SlowFB(
        "lento", "Lento", ["p1"], tracker=ProgressTracker(), step_timeout_s=0.05,
    )
    fb.execute()

    assert fb.nStep == fb.n_error
    assert "TimeoutError" in (fb.error_msg or "")


def test_execute_cancelado_durante_un_step() -> None:
    """Cancelacion pedida durante un step deja el FB en n_error.

    ``request_cancel(reason)`` marca el flag de cancelacion (un
    ``threading.Event``) y NO transiciona ``nStep``: el hilo ejecutor ve
    el flag al devolver el control del step y cierra el FB en
    ``n_error``, con el tracker ya cerrado por error.
    """
    tracker = ProgressTracker()
    started = threading.Event()
    gate = threading.Event()

    class _BlockingFB(FunctionBase):
        def run_step(self, idx: int, **params: Any) -> str:
            started.set()
            gate.wait(timeout=5)
            return "ok"

    fb = _BlockingFB("bloquea", "Bloquea", ["p1"], tracker=tracker)

    def _cancelar() -> None:
        started.wait(timeout=5)
        fb.request_cancel("cancelado por el operario")
        gate.set()

    worker = threading.Thread(target=_cancelar)
    worker.start()
    fb.execute()
    worker.join(timeout=5)

    assert fb.nStep == fb.n_error
    assert "cancelado por el operario" in (fb.error_msg or "")
    assert fb.result is None  # el FB cancelado no publica resultado
    snap = tracker.snapshot()
    assert snap.active is False
    assert "cancelado por el operario" in (snap.error or "")


def test_execute_rearranca() -> None:
    """El FB es reusable: ``execute()`` se puede llamar N veces."""
    fb = _SyncFB("sync_fb", "Sync FB", ["p1"], tracker=ProgressTracker())

    fb.execute(v=1)
    assert fb.nStep == fb.n_done
    fb.execute(v=2)
    assert fb.nStep == fb.n_done
    assert fb.calls == [0, 0]


def test_execute_ignorado_si_el_fb_esta_activo() -> None:
    """Con el FB activo, ``execute()`` no hace nada."""
    fb = _SyncFB("sync_fb", "Sync FB", ["p1"], tracker=ProgressTracker())
    fb.nStep = fb.n_ejecutar

    fb.execute()

    assert fb.calls == []
    assert fb.nStep == fb.n_ejecutar


# ---------------------------------------------------------------------
# Cancelacion cooperativa sync: request_cancel() (OB1)
# ---------------------------------------------------------------------


def test_request_cancel_en_fb_terminal_no_hace_nada() -> None:
    """En estado terminal no hay nada que cancelar.

    ``request_cancel()`` devuelve ``False`` y no toca ni el flag de
    cancelacion ni ``error_msg``: un FB ya cerrado no se re-marca.
    """
    fb = _SyncFB("sync_fb", "Sync FB", ["p1"], tracker=ProgressTracker())
    assert fb.nStep == fb.n_idle

    ok = fb.request_cancel("cancelado por el operario")

    assert ok is False
    assert fb._cancelled.is_set() is False
    assert fb.error_msg is None
    assert fb.nStep == fb.n_idle


def test_request_cancel_en_fb_activo_pide_la_cancelacion() -> None:
    """Con el FB activo, ``request_cancel()`` activa el flag y fija el motivo."""
    fb = _SyncFB("sync_fb", "Sync FB", ["p1"], tracker=ProgressTracker())
    fb.nStep = fb.n_ejecutar

    ok = fb.request_cancel("cancelado por el operario")

    assert ok is True
    assert fb._cancelled.is_set() is True
    assert fb.error_msg == "cancelado por el operario"


def test_request_cancel_no_cambia_nstep() -> None:
    """``request_cancel()`` NO transiciona ``nStep``.

    El estado lo cierra el hilo ejecutor cuando el step en curso
    devuelve el control; cambiarlo aqui seria una carrera con el step.
    """
    eventos: list[tuple[int, int]] = []
    fb = _SyncFB("sync_fb", "Sync FB", ["p1"], tracker=ProgressTracker())
    fb._on_nstep_change = lambda old, new: eventos.append((old, new))
    fb.nStep = fb.n_ejecutar

    fb.request_cancel("cancelado por el operario")

    assert fb.nStep == fb.n_ejecutar
    assert eventos == []  # no se notifica ninguna transicion


def test_request_cancel_no_pisa_un_error_previo() -> None:
    """Un ``error_msg`` ya informative tiene prioridad sobre el motivo de parada."""
    fb = _SyncFB("sync_fb", "Sync FB", ["p1"], tracker=ProgressTracker())
    fb.nStep = fb.n_ejecutar
    fb.error_msg = "RuntimeError: TIA Portal se cayo"

    ok = fb.request_cancel("cancelado por el operario")

    assert ok is True
    assert fb.error_msg == "RuntimeError: TIA Portal se cayo"
    assert fb._cancelled.is_set() is True


def test_request_cancel_es_sync_y_no_necesita_event_loop() -> None:
    """``request_cancel()`` no es una corrutina: se puede llamar sin event loop.

    Es lo que permite al OB1 pedir la cancelacion desde un hilo de
    Flask mientras el hilo ejecutor esta dentro de un step.
    """
    assert inspect.iscoroutinefunction(FunctionBase.request_cancel) is False

    fb = _SyncFB("sync_fb", "Sync FB", ["p1"], tracker=ProgressTracker())
    fb.nStep = fb.n_ejecutar
    resultados: list[bool] = []
    errores: list[BaseException] = []

    def _llamar() -> None:
        try:
            resultados.append(fb.request_cancel("desde otro hilo"))
        except BaseException as exc:  # noqa: BLE001 - se verifica abajo
            errores.append(exc)

    worker = threading.Thread(target=_llamar)
    worker.start()
    worker.join(timeout=5)

    assert worker.is_alive() is False
    assert errores == []
    assert resultados == [True]
    assert fb._cancelled.is_set() is True


def test_request_cancel_durante_un_step_cierra_el_fb_en_n_error() -> None:
    """Cancelacion pedida durante un step: el ejecutor cierra el FB.

    ``request_cancel()`` solo marca el flag; cuando el step devuelve el
    control, el base ve el flag y transiciona a ``n_error`` con el
    motivo de la parada.
    """
    started = threading.Event()
    gate = threading.Event()

    class _BlockingFB(FunctionBase):
        def run_step(self, idx: int, **params: Any) -> str:
            started.set()
            gate.wait(timeout=5)
            return "ok"

    fb = _BlockingFB("bloquea", "Bloquea", ["p1"], tracker=ProgressTracker())

    worker = threading.Thread(target=fb.execute)
    worker.start()
    started.wait(timeout=5)

    ok = fb.request_cancel("cancelado por el operario")
    gate.set()
    worker.join(timeout=5)

    assert ok is True
    assert fb.nStep == fb.n_error
    assert "cancelado por el operario" in (fb.error_msg or "")

