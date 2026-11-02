"""ANTES: el motor de FBs (extracto literal del repo real).

Fichero real: core/composition/plc_function_base.py
Lineas citadas: las del repo en el momento del analisis (commit a5be3d8).

Aqui solo se recorta lo que no aporta al dispatch (cancelacion, timeout
al detalle, publicacion SSE). Todo lo demas es LITERAL.

Este fichero NO se importa ni se ejecuta: es material de analisis.
"""
from __future__ import annotations

import inspect
import logging
import threading
import time
from typing import Any, Callable

logger = logging.getLogger("zc")


class FunctionBase:
    """Base de los Function Blocks (motor del OB1)."""

    n_idle: int = 0
    n_arrancar: int = 10
    n_ejecutar: int = 20
    n_finalizar: int = 95
    n_done: int = 99
    n_error: int = 98

    STEP_TIMEOUT_S: float = 300.0

    def __init__(
        self,
        nombre: str,
        titulo: str,
        steps: list[dict[str, Any]],
        tracker: Any = None,
        step_timeout_s: float | None = None,
    ) -> None:
        self.nombre = nombre
        self.titulo = titulo
        # real L82-85: normaliza a list[dict].
        self.steps: list[dict[str, Any]] = [
            s if isinstance(s, dict) else {"nombre": s}
            for s in steps
        ]
        self._tracker = tracker
        self._step_timeout_s = (
            step_timeout_s if step_timeout_s is not None else self.STEP_TIMEOUT_S
        )
        self._step_idx: int = 0
        self._cancelled = threading.Event()
        self.nStep: int = self.n_idle
        self.error_msg: str | None = None
        self.result: Any = None
        self._params: dict[str, Any] = {}
        self._stats: dict[str, Any] = {}
        self._exec_lock = threading.Lock()
        self._on_nstep_change: Callable[[int, int], None] | None = None

    # ------------------------------------------------------------------
    # Hooks que aportan los FBs
    # ------------------------------------------------------------------

    def on_start(self, **params: Any) -> None:
        """Pre-flight SYNC. Default: no-op."""
        pass

    def run_step(self, idx: int, **params: Any) -> str:
        """Logica del step ``idx``. Devuelve un detail (string) para el HMI.

        CADA FB reimplementa este metodo: 730 lineas de dispatch en los
        12 FBs del repo (286 en el area con tabla STAGES, 474 en core
        con match/case).
        """
        raise NotImplementedError

    def on_finish(self, **params: Any) -> None:
        """Post-proceso. Default: no-op."""
        pass

    # ------------------------------------------------------------------
    # Ejecucion
    # ------------------------------------------------------------------

    def execute(self, **params: Any) -> Any:
        """Ejecuta el FB completo de principio a fin (SINC)."""
        if not self._exec_lock.acquire(blocking=False):
            logger.warning(
                "FB %s: execute() ignorado, ya hay una ejecucion en curso",
                self.nombre,
            )
            return self.result
        try:
            return self._execute_locked(**params)
        finally:
            self._exec_lock.release()

    def _execute_locked(self, **params: Any) -> Any:
        if not self.is_terminal():
            return self.result

        self._reset_state_for_run(params)
        self.nStep = self.n_arrancar
        self._notify_nstep_change(self.n_idle, self.nStep)

        try:
            self._step_arrancar()
            while self.nStep == self.n_ejecutar:
                self._step_ejecutar_sync()
                self._notify_nstep_change(self.nStep, self.nStep)
            return self.result
        except (NotImplementedError, AssertionError) as e:
            self.error_msg = f"{type(e).__name__}: {e}"
            self.nStep = self.n_error
            raise
        except Exception as e:
            self._fail_with(e, "execute()")
        return self.result

    def _step_ejecutar_sync(self) -> None:
        """nStep 20 (sync): ejecuta el step ``_step_idx``."""
        if self._cancelled.is_set():
            raise RuntimeError(self.error_msg or "cancelled")
        idx = self._step_idx
        if idx >= len(self.steps):
            self.nStep = self.n_finalizar
            return
        # real L325: el nombre sale de la declaracion de steps.
        step_nombre = self.steps[idx]["nombre"]
        self._tracker.start_stage(step_nombre)
        _t0 = time.monotonic()
        try:
            detail = self._run_step_with_timeout(idx)
        except TimeoutError:
            self._tracker.error_stage(
                step_nombre, f"timeout >{self._step_timeout_s}s",
            )
            raise
        except Exception:
            self._tracker.error_stage(step_nombre, self.error_msg or "error")
            raise
        self._tracker.finish_stage(
            step_nombre, detail=str(detail) if detail else None,
        )
        self._step_idx += 1
        if self._cancelled.is_set():
            raise RuntimeError(self.error_msg or "cancelled")
        if self._step_idx >= len(self.steps):
            self.nStep = self.n_finalizar

    def _invoke_step_sync(self, idx: int) -> str:
        """Invoca ``run_step`` y devuelve el detail.

        real L357-371 (literal).
        """
        outcome = self.run_step(idx, **self._params)
        if inspect.isawaitable(outcome):
            raise TypeError(
                "run_step devuelve una corrutina: los FBs deben ser sync "
                "(se ejecutan en el hilo del dispatcher del OB1)"
            )
        return outcome
