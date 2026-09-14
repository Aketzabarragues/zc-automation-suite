"""FB demo con 4 pasos (test_1_X) para validar el faceplate SSE dinamico.

Subclase de ``FunctionTemplate``: override solo ``run_step`` (CASE con
4 ramas) y ``on_finish`` (shape con stats). El resto (state machine,
progress_tracker, timeouts, cancel) lo hereda del base.

Uso: validar que el HMI ve el progreso actualizarse en vivo: 4
stages ``test_1_1..test_1_4`` pasan secuencialmente de ``pending``
a ``running`` a ``done`` mientras el ``current`` y ``percent`` suben.
"""
from __future__ import annotations

import asyncio
import logging

from core.runtime.progress_buffer import ProgressTracker

from areas.alimentacion.functions.function_template import FunctionTemplate

logger = logging.getLogger(__name__)


class FunctionCuatroPasos(FunctionTemplate):
    """FB demo: 4 pasos ``test_1_X`` con duracion variable y detail."""

    STEP_TIMEOUT_S = 10.0

    def __init__(
        self,
        nombre: str = "cuatro_pasos",
        titulo: str = "Test FB 4 pasos",
        tracker: ProgressTracker | None = None,
    ) -> None:
        super().__init__(
            nombre=nombre,
            titulo=titulo,
            steps=[
                {"nombre": "test_1_1"},
                {"nombre": "test_1_2"},
                {"nombre": "test_1_3"},
                {"nombre": "test_1_4"},
            ],
            tracker=tracker,
        )

    async def run_step(self, idx: int, **params) -> str:
        step_nombre = self.steps[idx]["nombre"]
        logger.info("[%s] CASE %s (idx=%d)", self.nombre, step_nombre, idx)
        match step_nombre:
            case "test_1_1":
                await asyncio.sleep(0.5)
                self._stats[step_nombre] = {"valor": 42}
                return "42 dispositivos cargados"
            case "test_1_2":
                await asyncio.sleep(0.5)
                self._stats[step_nombre] = {"valor": 18}
                return "18 conexiones validadas"
            case "test_1_3":
                await asyncio.sleep(0.7)
                self._stats[step_nombre] = {"valor": 7}
                return "7 modulos procesados"
            case "test_1_4":
                await asyncio.sleep(0.3)
                self._stats[step_nombre] = {"valor": 99}
                return "99% completado"
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


__all__ = ["FunctionCuatroPasos"]
