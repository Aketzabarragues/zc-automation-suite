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

from core.plc.function_base import FunctionBase


@pytest.mark.asyncio
async def test_start_secuencial_es_idempotente() -> None:
    """``start()`` no es re-entrante: si ya está activo, ignora y
    devuelve ``False`` sin pisar ``nStep`` ni ``_params``."""
    fb = FunctionBase("test_fb")
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
    fb = FunctionBase("test_fb")

    results = await asyncio.gather(*(fb.start(i=i) for i in range(5)))

    assert sum(1 for r in results if r) == 1
    assert sum(1 for r in results if not r) == 4
    assert fb.nStep == 10


@pytest.mark.asyncio
async def test_start_locked_sin_lock_dispara_assert() -> None:
    """Llamar ``_start_locked()`` sin ``self._lock`` viola el contrato
    del assert del greenfield y debe lanzar ``AssertionError``."""
    fb = FunctionBase("test_fb")
    with pytest.raises(AssertionError, match="requiere self._lock cogido"):
        await fb._start_locked()


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
    fb = _ExplodingFB("explota")
    await fb.start()
    assert fb.nStep == 10

    await fb.tick()  # NO debe propagar la RuntimeError

    assert fb.nStep == fb.n_error
    assert fb.error_msg is not None
    assert "RuntimeError" in fb.error_msg
    assert "TIA Portal se cayó" in fb.error_msg
    assert fb.is_terminal() is True


@pytest.mark.asyncio
async def test_tick_notimplemented_propagates() -> None:
    """``NotImplementedError`` es error de programación: ``tick()`` la
    deja propagar para que el dev lo vea claro en consola/tests
    (no se silencia con el best-effort)."""
    fb = FunctionBase("stub")  # NO overridea _tick_locked
    await fb.start()

    with pytest.raises(NotImplementedError, match="_tick_locked"):
        await fb.tick()

