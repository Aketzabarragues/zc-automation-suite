"""Function Block TEMPLATE con 10 pasos discretos (1s cada uno).

Patron para migrar los 7 FBs legacy del area. Cuando funcione, los
FBs reales (SubirExcel, ScanPlcBlocks, Sincronizar*, etc.) se
adaptan a este shape: state machine interna + asyncio.sleep por
paso + self.result con la shape legacy.

State machine (nStep):
  0   idle         (sin start)
  10  arrancar     (pre-flight)
  20  paso 1       (sleep 1s)
  30  paso 2       (sleep 1s)
  40  paso 3       (sleep 1s)
  50  paso 4       (sleep 1s)
  60  paso 5       (sleep 1s)
  70  paso 6       (sleep 1s)
  80  paso 7       (sleep 1s)
  90  paso 8       (sleep 1s)
  95  finalizar
  99  done         (terminal)

Tiempo total de ejecucion: ~10s (10 pasos de 1s + transiciones).

El FB NO usa tia_client ni wrapper. Solo sirve para validar que el
engine, los FBs y el flujo end-to-end funcionan. Cuando migramos los
FBs reales, sustituyen este dummy.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from core.composition.plc_function_base import FunctionBase

logger = logging.getLogger(__name__)


class FunctionTemplate(FunctionBase):
    """FB template. Sin tocar TIA ni Excel. Solo avanza 10 pasos."""

    n_arrancar = 10
    n_finalizar = 95
    # pasos 20, 30, 40, 50, 60, 70, 80, 90 (sleep 1s cada uno)

    def __init__(self, nombre: str = "Template") -> None:
        super().__init__(nombre)
        self.steps_completed: int = 0

    async def _tick_locked(self) -> None:
        assert self._lock.locked()
        if self.nStep == self.n_idle:
            return
        if self.nStep == self.n_arrancar:
            self._step_arrancar()
        elif 20 <= self.nStep < 90:
            await self._step_sleep_one()
        elif self.nStep == 90:
            await self._step_sleep_one()
            self.nStep = self.n_finalizar
        elif self.nStep == self.n_finalizar:
            self._step_finalizar()

    # ------------------------------------------------------------------
    # Pasos del state machine
    # ------------------------------------------------------------------

    def _step_arrancar(self) -> None:
        """nStep 10 -> 20. Pre-flight vacio (no hay params requeridos)."""
        logger.info("[%s] arrancando", self.nombre)
        self.steps_completed = 0
        self.nStep = 20

    async def _step_sleep_one(self) -> None:
        """Pasos 20-90: espera 1s y avanza."""
        self.steps_completed += 1
        logger.info("[%s] paso %d/8", self.nombre, self.steps_completed)
        await asyncio.sleep(1.0)
        self.nStep += 10

    def _step_finalizar(self) -> None:
        """nStep 95 -> 99. Vuelca self.result y transiciona a done."""
        logger.info("[%s] done", self.nombre)
        self.result: dict[str, Any] = {
            "ok": True,
            "steps_completed": self.steps_completed,
        }
        self.nStep = self.n_done


__all__ = ["FunctionTemplate"]
