"""FB demo con 6 pasos (test_2_X) para validar el faceplate SSE dinamico.

Subclase de ``FunctionTemplate``: override solo ``run_step`` (CASE con
6 ramas) y ``on_finish`` (shape con stats). El resto (state machine,
progress_tracker, timeouts, cancel) lo hereda del base.

Uso: validar que el HMI ve el progreso actualizarse en vivo: 6
stages ``test_2_1..test_2_6`` pasan secuencialmente de ``pending``
a ``running`` a ``done`` mientras el ``current`` y ``percent`` suben.
"""
from __future__ import annotations

import asyncio
import logging

from core.runtime.progress_buffer import ProgressTracker

from areas.alimentacion.functions.function_template import FunctionTemplate

logger = logging.getLogger(__name__)


class FunctionSeisPasos(FunctionTemplate):
    """FB demo: 6 pasos ``test_2_X`` con duracion variable y detail."""

    STEP_TIMEOUT_S = 15.0

    def __init__(
        self,
        nombre: str = "seis_pasos",
        titulo: str = "Test FB 6 pasos",
        tracker: ProgressTracker | None = None,
    ) -> None:
        super().__init__(
            nombre=nombre,
            titulo=titulo,
            steps=[
                {"nombre": "test_2_1"},
                {"nombre": "test_2_2"},
                {"nombre": "test_2_3"},
                {"nombre": "test_2_4"},
                {"nombre": "test_2_5"},
                {"nombre": "test_2_6"},
            ],
            tracker=tracker,
        )

    async def run_step(self, idx: int, **params) -> str:
        step_nombre = self.steps[idx]["nombre"]
        logger.info("[%s] CASE %s (idx=%d)", self.nombre, step_nombre, idx)
        match step_nombre:
            case "test_2_1":
                await asyncio.sleep(0.4)
                self._stats[step_nombre] = {"valor": 120}
                return "120 filas parseadas"
            case "test_2_2":
                await asyncio.sleep(0.5)
                self._stats[step_nombre] = {"valor": 85}
                return "85 columnas validadas"
            case "test_2_3":
                await asyncio.sleep(0.4)
                self._stats[step_nombre] = {"valor": "ok"}
                return "validacion N_MAX OK"
            case "test_2_4":
                await asyncio.sleep(0.6)
                self._stats[step_nombre] = {"valor": 32}
                return "32 bloques exportados"
            case "test_2_5":
                await asyncio.sleep(0.5)
                self._stats[step_nombre] = {"valor": 12}
                return "12 transforms aplicados"
            case "test_2_6":
                await asyncio.sleep(0.3)
                self._stats[step_nombre] = {"valor": "ok"}
                return "publicado en TIA"
            case _:
                raise ValueError(f"step no soportado: {step_nombre!r}")

    def on_finish(self, **params) -> None:
        self.result = {
            "ok": True,
            "titulo": self.titulo,
            "steps_completed": self._step_idx,
            "total_steps": len(self.steps),
            "stats": dict(self._stats),
        }


__all__ = ["FunctionSeisPasos"]
