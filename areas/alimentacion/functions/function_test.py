"""Function Block TEST: dummy FB para validar el engine + base.

NO usa TIA Portal ni Excel. Solo aporta declaracion estatica de
steps y la logica minima (``asyncio.sleep``). Sirve para validar
que el engine, el HMI (progress_tracker integrado en el base),
timeouts, cancel() y el flujo end-to-end funcionan correctamente.

Cuando se migren los FBs reales del area (Fase 2), este test FB
sigue siendo util como smoke del propio base.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from core.composition.plc_function_base import FunctionBase
from core.runtime.progress_buffer import ProgressTracker

logger = logging.getLogger(__name__)


class FunctionTest(FunctionBase):
    """FB dummy. Cada step duerme ``duracion_s`` segundos.

    Steps default: 4 x 1s (parametrizable via constructor). Override
    de ``on_finish`` para mantener el shape ``{ok, titulo,
    steps_completed, total_steps}`` que esperan los smokes.
    """

    STEP_TIMEOUT_S = 30.0

    def __init__(
        self,
        nombre: str = "test",
        titulo: str = "Test FB",
        steps: list[dict[str, Any]] | None = None,
        tracker: ProgressTracker | None = None,
    ) -> None:
        super().__init__(
            nombre=nombre,
            titulo=titulo,
            steps=steps if steps is not None else [
                {"nombre": "paso_1", "duracion_s": 1.0},
                {"nombre": "paso_2", "duracion_s": 1.0},
                {"nombre": "paso_3", "duracion_s": 1.0},
                {"nombre": "paso_4", "duracion_s": 1.0},
            ],
            tracker=tracker,
        )

    async def run_step(self, idx: int, **params: Any) -> str:
        """Dummy: duerme lo que diga el step. Devuelve ``OK en Xs``."""
        step = self.steps[idx]
        duracion = float(step.get("duracion_s", 1.0))
        logger.info(
            "[%s] step %d/%d (%s, %.2fs)",
            self.nombre, idx + 1, len(self.steps), step["nombre"], duracion,
        )
        await asyncio.sleep(duracion)
        return f"OK en {duracion:.2f}s"

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` con la shape legacy para los smokes."""
        self.result = {
            "ok": True,
            "titulo": self.titulo,
            "steps_completed": self._step_idx,
            "total_steps": len(self.steps),
        }


__all__ = ["FunctionTest"]
