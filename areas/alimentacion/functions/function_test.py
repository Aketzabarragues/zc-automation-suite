"""Function Block TEST: dummy FB que simula una sincronizacion real.

Pensado para que el operario vea como un FB con HMI (progress_tracker
integrado en el base) organiza sus etapas al estilo SCL: cada step
es una rama de un CASE dentro de ``run_step``, con su logica y su
detail. No usa TIA Portal ni Excel: las 4 etapas son sleeps + datos
ficticios para validar el flujo.

Stage map (4 etapas, CASE en ``run_step``):
  parsear_excel    -> duerme 0.3s, devuelve "142 filas"
  validar_N_MAX    -> duerme 0.3s, devuelve "N_MAX OK"
  exportar_TIA     -> duerme 0.5s, devuelve "12 bloques exportados"
  importar_TIA     -> duerme 0.5s, devuelve "87 dispositivos"

El "salto" entre etapas lo gestiona el base (``_step_idx++`` tras
cada ``run_step``), no este FB. Este FB solo implementa cada etapa
como una rama del CASE. Mismo patron que un FB de TIA donde el OB1
lleva el contador y el FB aporta los metodos.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from core.composition.plc_function_base import FunctionBase
from core.runtime.progress_buffer import ProgressTracker

logger = logging.getLogger(__name__)


class FunctionTest(FunctionBase):
    """FB dummy realista: 4 etapas con CASE en ``run_step``."""

    STEP_TIMEOUT_S = 30.0

    # Constantes de etapas (mismo nombre que en el CASE; facil de testear)
    STEP_PARSEAR = "parsear_excel"
    STEP_VALIDAR = "validar_N_MAX"
    STEP_EXPORTAR = "exportar_TIA"
    STEP_IMPORTAR = "importar_TIA"

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
                {"nombre": self.STEP_PARSEAR, "duracion_s": 0.3},
                {"nombre": self.STEP_VALIDAR, "duracion_s": 0.3},
                {"nombre": self.STEP_EXPORTAR, "duracion_s": 0.5},
                {"nombre": self.STEP_IMPORTAR, "duracion_s": 0.5},
            ],
            tracker=tracker,
        )
        # Estado interno acumulado durante la ejecucion. Cada step
        # lo rellena; on_finish lo vuelca a self.result["stats"].
        self._stats: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Hooks del base
    # ------------------------------------------------------------------

    def on_start(self, **params: Any) -> None:
        """Pre-flight: leer params.

        En un FB real aqui se validarian los IN del FB (plc_name,
        ruta del excel, etc.) y se lanzaria ValueError si falta algo.
        En el test dejamos la validacion laxa (warning + placeholder)
        para que el smoke pueda correr sin pasar todos los params.
        """
        plc_name = params.get("plc_name", "")
        if not plc_name:
            logger.warning(
                "[%s] plc_name no proporcionado; usando placeholder",
                self.nombre,
            )
            plc_name = "(sin_plc)"
        self._plc_name: str = plc_name
        logger.info("[%s] on_start: plc_name=%s", self.nombre, plc_name)

    async def run_step(self, idx: int, **params: Any) -> str:
        """CASE por nombre de step. Cada rama duerme + devuelve detail.

        Equivalente SCL::

            CASE self.steps[idx].nombre OF
                "parsear_excel":  ...
                "validar_N_MAX":  ...
                "exportar_TIA":   ...
                "importar_TIA":   ...
            END_CASE;

        El detail retornado se publica al HMI via
        ``tracker.finish_stage(nombre, detail=...)``.
        """
        step_nombre = self.steps[idx]["nombre"]
        duracion = float(self.steps[idx].get("duracion_s", 0.0))
        logger.info(
            "[%s] CASE %s (idx=%d, %.2fs)",
            self.nombre, step_nombre, idx, duracion,
        )
        # CASE step_nombre OF  -- logica por etapa
        match step_nombre:
            case self.STEP_PARSEAR:
                await asyncio.sleep(duracion)
                filas = 142
                self._stats[self.STEP_PARSEAR] = {"filas": filas}
                return f"{filas} filas parseadas"

            case self.STEP_VALIDAR:
                await asyncio.sleep(duracion)
                self._stats[self.STEP_VALIDAR] = {"n_max_ok": True}
                return "N_MAX OK"

            case self.STEP_EXPORTAR:
                await asyncio.sleep(duracion)
                bloques = 12
                self._stats[self.STEP_EXPORTAR] = {"bloques": bloques}
                return f"{bloques} bloques exportados"

            case self.STEP_IMPORTAR:
                await asyncio.sleep(duracion)
                dispositivos = 87
                self._stats[self.STEP_IMPORTAR] = {"dispositivos": dispositivos}
                return f"{dispositivos} dispositivos importados"

            case _:
                # Stage desconocido: lanzar para que el base vaya a n_error.
                raise ValueError(f"step no soportado: {step_nombre!r}")

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` con la shape legacy + stats agregados."""
        self.result = {
            "ok": True,
            "titulo": self.titulo,
            "steps_completed": self._step_idx,
            "total_steps": len(self.steps),
            "plc_name": getattr(self, "_plc_name", None),
            "stats": dict(self._stats),
        }


__all__ = ["FunctionTest"]
