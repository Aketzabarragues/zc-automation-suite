"""Function Block TEST: dummy FB para validar el engine + progress tracker.

El caller la instancia con ``titulo`` y ``steps`` (lista de
``{nombre, duracion_s}``); cada ejecucion emite eventos SSE
``progress`` al bus por stage (begin / start / finish) y cierra
con ``finish(success=True)``.

Cuando se migren los FBs reales del area (Fase 2), este test FB
sigue siendo util como smoke del propio base.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from core.composition.plc_function_base import FunctionBase
from core.runtime.progress_buffer import ProgressTracker, get_progress_tracker

logger = logging.getLogger(__name__)


class FunctionTest(FunctionBase):
    """FB test parametrizable. Emite eventos progress por stage.

    State machine:
      10  arrancar  (emit progress_tracker.begin)
      20  ejecutar  (1 step por tick; permanece hasta agotar steps)
      95  finalizar (emit progress_tracker.finish)
      99  done      (terminal)
    """

    n_arrancar = 10
    n_ejecutar = 20
    n_finalizar = 95

    def __init__(
        self,
        nombre: str = "Template",
        titulo: str = "Demo Template",
        steps: list[dict[str, Any]] | None = None,
        tracker: ProgressTracker | None = None,
    ) -> None:
        super().__init__(nombre)
        self.titulo = titulo
        # Default razonable si el caller no pasa steps: 4 pasos x 1s.
        # Asi ``FunctionTemplate()`` sigue funcionando en tests basicos.
        self.steps: list[dict[str, Any]] = (
            steps if steps is not None
            else [
                {"nombre": "paso_1", "duracion_s": 1.0},
                {"nombre": "paso_2", "duracion_s": 1.0},
                {"nombre": "paso_3", "duracion_s": 1.0},
                {"nombre": "paso_4", "duracion_s": 1.0},
            ]
        )
        # Inyeccion opcional del tracker (default: singleton global).
        # Tests / smoke pueden pasar uno propio para aislar estado.
        self._tracker = tracker if tracker is not None else get_progress_tracker()
        self._step_idx: int = 0

    async def _start_locked(self, **params: Any) -> bool:
        """Override del base: tras pasar a nStep=10, emite ``begin()``."""
        ok = await super()._start_locked(**params)
        if not ok:
            return False
        self._step_idx = 0
        return True

    async def _tick_locked(self) -> None:
        assert self._lock.locked()
        if self.nStep == self.n_idle:
            return
        if self.nStep == self.n_arrancar:
            self._step_arrancar()
        elif self.nStep == self.n_ejecutar:
            await self._step_ejecutar()
        elif self.nStep == self.n_finalizar:
            self._step_finalizar()

    # ------------------------------------------------------------------
    # Pasos del state machine
    # ------------------------------------------------------------------

    def _step_arrancar(self) -> None:
        """nStep 10 -> 20. Emite ``begin`` con titulo + stages."""
        logger.info("[%s] arrancando (titulo=%s, %d steps)",
                    self.nombre, self.titulo, len(self.steps))
        self._tracker.begin(
            operation=self.nombre,
            label=self.titulo,
            stages=[s["nombre"] for s in self.steps],
        )
        self.nStep = self.n_ejecutar

    async def _step_ejecutar(self) -> None:
        """nStep 20: ejecuta un step y permanece, o transiciona a 95."""
        idx = self._step_idx
        step = self.steps[idx]
        nombre = step["nombre"]
        duracion = float(step["duracion_s"])
        logger.info(
            "[%s] step %d/%d (%s, %.2fs)",
            self.nombre, idx + 1, len(self.steps), nombre, duracion,
        )
        self._tracker.start_stage(nombre)
        await asyncio.sleep(duracion)
        self._tracker.finish_stage(nombre, detail=f"OK en {duracion:.2f}s")
        self._step_idx += 1
        if self._step_idx < len(self.steps):
            # Permanece en n_ejecutar: el siguiente tick ejecuta el
            # siguiente step. Asi el ciclo del engine maneja los
            # espacios entre stages de forma natural.
            return
        self.nStep = self.n_finalizar

    def _step_finalizar(self) -> None:
        """nStep 95 -> 99. Emite ``finish(success=True)`` y vuelca result."""
        logger.info("[%s] done", self.nombre)
        self._tracker.finish(success=True)
        self.result = {
            "ok": True,
            "titulo": self.titulo,
            "steps_completed": self._step_idx,
            "total_steps": len(self.steps),
        }
        self.nStep = self.n_done


__all__ = ["FunctionTest"]
