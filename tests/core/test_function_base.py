"""Tests del lock no reentrante en ``core.plc.function_base.FunctionBase``.

Tests del .clinerules (Fase 2).  Cubren:
  - ``start()`` secuencial idempotente: la segunda llamada mientras
    está activo devuelve ``False`` y no pisa el estado.
  - ``start()`` concurrente: N llamadas en paralelo pelean por el
    lock; solo una gana.
  - ``_start_locked()`` sin lock dispara ``AssertionError`` (regla
    del "lock del assert" del greenfield).
  - Tolerancia best-effort de ``tick()``: una excepción de runtime en
    ``_tick_locked()`` se captura y el FB termina en ``n_error`` con
    ``error_msg`` poblado (degradado pero vivo, paso 2.0.4).
  - ``NotImplementedError`` propaga: los errores de programación
    (subclase que olvidó overridear) NO se silencian.
"""
from __future__ import annotations

import asyncio
import inspect
import threading
import time
from typing import Any

import pytest

from core.composition.plc_function_base import FunctionBase
from core.runtime.progress_buffer import ProgressTracker


@pytest.mark.asyncio
async def test_start_secuencial_es_idempotente() -> None:
    """``start()`` no es re-entrante: si ya está activo, ignora y
    devuelve ``False`` sin pisar ``nStep`` ni ``_params``."""
    fb = FunctionBase("test_fb", "Test FB", ["s1"])
    assert fb.nStep == fb.n_idle

    ok1 = await fb.start(param1="x")
    assert ok1 is True
    assert fb.nStep == 10
    assert fb._params == {"param1": "x"}

    ok2 = await fb.start(param1="y")  # intenta pisar
    assert ok2 is False
    assert fb.nStep == 10
    assert fb._params == {"param1": "x"}  # params preservados


@pytest.mark.asyncio
async def test_start_concurrente_solo_una_gana() -> None:
    """N ``start()`` en paralelo compiten por ``self._lock``; solo uno
    arranca, el resto ve ``nStep != n_idle`` y devuelve ``False``."""
    fb = FunctionBase("test_fb", "Test FB", ["s1"])

    results = await asyncio.gather(*(fb.start(i=i) for i in range(5)))

    assert sum(1 for r in results if r) == 1
    assert sum(1 for r in results if not r) == 4
    assert fb.nStep == 10


@pytest.mark.asyncio
async def test_tick_locked_sin_lock_dispara_assert() -> None:
    """Llamar ``_tick_locked()`` sin ``self._lock`` viola el contrato
    del assert del greenfield y debe lanzar ``AssertionError``.

    Antes del refactor, el patron se aplicaba a ``_start_locked()``.
    Tras el refactor OB1, ``start()`` no se separa en wrapper/locked
    (no requiere lock) y solo ``_tick_locked()`` mantiene el assert
    del lock. Este test verifica que el patron se sigue cumpliendo
    en el unico metodo que lo conserva.
    """
    fb = FunctionBase("test_fb", "Test FB", ["s1"])
    with pytest.raises(AssertionError):
        await fb._tick_locked()


# ---------------------------------------------------------------------
# Paso 2.0.4 — tolerancia best-effort
# ---------------------------------------------------------------------


class _ExplodingFB(FunctionBase):
    """FB de test: en ``nStep=10`` lanza ``RuntimeError``."""

    async def _tick_locked(self) -> None:
        assert self._lock.locked()
        if self.nStep == 10:
            raise RuntimeError("TIA Portal se cayó")


@pytest.mark.asyncio
async def test_tick_exception_runtime_pone_fb_en_n_error() -> None:
    """Si ``_tick_locked()`` lanza ``Exception``, el wrapper de
    ``tick()`` la captura (best-effort): log + degradado pero vivo.
    El FB termina en ``n_error`` con ``error_msg`` poblado y
    ``is_terminal()`` True.  El operario ve el error y resetea.
    """
    fb = _ExplodingFB("explota", "Explota", ["s1"])
    await fb.start()
    assert fb.nStep == 10

    await fb.tick()  # NO debe propagar la RuntimeError

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "RuntimeError" in fb.error_msg
    assert "TIA Portal se cayó" in fb.error_msg
    assert fb.is_terminal() is True


@pytest.mark.asyncio
async def test_tick_run_step_sin_override_propagates_notimplemented() -> None:
    """``NotImplementedError`` es error de programación: ``tick()`` la
    deja propagar para que el dev lo vea claro en consola/tests
    (no se silencia con el best-effort).

    Tras el refactor OB1, ``on_start`` / ``on_finish`` tienen
    implementacion por defecto (no-op), pero ``run_step(idx)`` sigue
    siendo abstracto: si la subclase olvido overridearlo, el primer
    ``tick()`` del state machine ``n_ejecutar`` lo lanza y
    ``tick()`` lo propaga (best-effort solo captura ``Exception``,
    no ``NotImplementedError`` ni ``AssertionError``).
    """
    fb = FunctionBase("stub", "Stub", ["s1"])  # NO overridea run_step
    await fb.start()
    # Primer tick: ejecuta _step_arrancar (on_start, no run_step).
    await fb.tick()
    assert fb.nStep == FunctionBase.n_ejecutar  # 20

    # Segundo tick: ejecuta _step_ejecutar (run_step -> NotImplementedError).
    with pytest.raises(NotImplementedError, match="run_step"):
        await fb.tick()


# ---------------------------------------------------------------------
# Camino sync: execute() (el que conduce el OB1)
# ---------------------------------------------------------------------


class _SyncFB(FunctionBase):
    """FB de test con ``run_step`` sync (contrato del camino nuevo)."""

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


def test_execute_y_tick_no_se_solapan() -> None:
    """El engine legacy no puede tickear un FB que se esta ejecutando.

    Sin exclusion mutua, el step corria dos veces y el FB se quedaba en
    ``n_finalizar`` (no terminal): el engine lo re-tickeaba para siempre.
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

    runner = threading.Thread(target=lambda: fb.execute())
    runner.start()
    started.wait(timeout=5)

    asyncio.run(fb.tick())  # el engine legacy intenta tickear: se omite
    gate.set()
    runner.join(timeout=5)

    assert calls == [0, 1]  # ningun step duplicado
    assert fb.nStep == fb.n_done


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
    """Un ``cancel()`` desde otro hilo durante un step deja n_error.

    El flag de cancelacion es un ``threading.Event``: el hilo de Flask
    lo activa y el hilo ejecutor lo ve en la frontera de etapa.
    """
    started = threading.Event()
    gate = threading.Event()

    class _BlockingFB(FunctionBase):
        def run_step(self, idx: int, **params: Any) -> str:
            started.set()
            gate.wait(timeout=5)
            return "ok"

    fb = _BlockingFB("bloquea", "Bloquea", ["p1"], tracker=ProgressTracker())

    def _cancel() -> None:
        started.wait(timeout=5)
        asyncio.run(fb.cancel("cancelado por el operario"))
        gate.set()

    worker = threading.Thread(target=_cancel)
    worker.start()
    fb.execute()
    worker.join(timeout=5)

    assert fb.nStep == fb.n_error
    assert "cancelado por el operario" in (fb.error_msg or "")


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


@pytest.mark.asyncio
async def test_tick_legacy_con_run_step_sync() -> None:
    """El camino legacy (``tick()``) tambien admite un ``run_step`` sync.

    Durante la migracion coexisten FBs async (legacy) y FBs sync (ya
    migrados), y el engine legacy los tickea a todos. Un ``run_step``
    sync no se puede pasar a ``asyncio.wait_for`` (no es corrutina):
    el base lo ejecuta en un hilo daemon con el timeout del base.
    """
    fb = _SyncFB("sync_fb", "Sync FB", ["p1"], tracker=ProgressTracker())

    await fb.start()
    await fb.tick()  # arrancar  (10 -> 20)
    await fb.tick()  # ejecutar  (20 -> 95)
    await fb.tick()  # finalizar (95 -> 99)

    assert fb.calls == [0]
    assert fb.nStep == fb.n_done
    assert fb.error_msg is None


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

