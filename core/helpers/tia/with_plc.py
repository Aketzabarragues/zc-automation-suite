"""Helper para setear el PLC activo en AppState.

Patron stateless (D6 del plan multi-PLC): cada endpoint que dispare un FB
recibe plc_name en el body y debe invocar with_plc(state, plc_name)
antes de invocar el FB. Esto asegura que state.selected_plc queda
sincronizado con el plc_name que va a usar el FB (defensa redundante
adicional al on_start del propio FB).

Uso:
    from core.helpers.tia.with_plc import with_plc

    @bp.post("/sync/commit")
    def commit():
        body = request.get_json()
        plc_name = body.get("plc_name", "")
        with_plc(app_state, plc_name)
        fb = engine.syn_fb("disp_sincronizar")
        fb.start(plc_name=plc_name)
"""
from __future__ import annotations

import logging

from core.runtime.app_state import AppState


_logger = logging.getLogger(__name__)


def with_plc(app_state: AppState, plc_name: str) -> None:
    """Setea el PLC activo en app_state.selected_plc.

    Idempotente: llamar varias veces con el mismo plc_name es seguro.

    Args:
        app_state: instancia Singleton de AppState.
        plc_name: nombre del PLC (strict equality con TIA Portal, D11).
            Si esta vacio, NO modifica selected_plc (mantiene el valor
            que ya estaba; el caller deberia asegurarse de pasar un
            plc_name valido).
    """
    if not plc_name:
        _logger.warning(
            "with_plc: plc_name vacio, selected_plc queda en %r",
            app_state.selected_plc,
        )
        return
    if app_state.selected_plc != plc_name:
        _logger.info("selected_plc: %r -> %r", app_state.selected_plc, plc_name)
        app_state.selected_plc = plc_name


__all__ = ["with_plc"]