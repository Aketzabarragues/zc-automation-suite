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

import pytest

from core.composition.plc_function_base import FunctionBase


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

