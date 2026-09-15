"""Registro de Function Blocks (FBs) genericos del core en el engine.

Los FBs core son aquellos cuya logica NO depende de un area
especifica (no leen hw_types, n_max_catalog, etc. del ConfigManager
del departamento). Viven en ``core/composition/`` y se registran
aqui, antes de que las areas aporten los suyos.

A medida que se aadan FBs core (p. ej. los A.2-A.6 que sean
genericos), se anaden al cuerpo de ``register()``.

Invocado desde ``core.launcher.main_supervisor._build_components()``
antes de ``register_alimentacion(...)``.
"""
from __future__ import annotations

import logging

from core.runtime.log_buffer import get_log_buffer

logger = logging.getLogger("zc")


def register(engine, *, tia_client=None, log=None) -> None:
    """Registra los FBs core en ``engine``.

    Args:
        engine: instancia de ``core.composition.plc_engine.Engine``.
        tia_client: cliente TIA inyectado (Singleton o mock). Se pasa
            a los FBs que necesitan dispatch contra el worker OT
            (p. ej. ``scan_plc_blocks``).
        log: ``LogBuffer`` para los ``self._log.*`` de los FBs. Si
            None, se usa el Singleton global.

    Raises:
        TypeError: si ``engine`` no expone ``register_fb``.
    """
    if not hasattr(engine, "register_fb"):
        raise TypeError(
            f"engine debe exponer register_fb(); recibio {type(engine).__name__}"
        )

    log = log if log is not None else get_log_buffer()

    from core.composition.function_scan_plc_blocks import FunctionScanPlcBlocks

    engine.register_fb(
        "scan_plc_blocks",
        FunctionScanPlcBlocks(
            nombre="scan_plc_blocks",
            tia_client=tia_client,
            log=log,
        ),
    )
    logger.info(
        "core: FB 'scan_plc_blocks' registrado (FunctionScanPlcBlocks)."
    )


__all__ = ["register"]
