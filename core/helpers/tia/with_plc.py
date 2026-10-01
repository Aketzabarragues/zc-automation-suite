"""Helper para setear el PLC activo en AppState.

Patron stateless (D6 del plan multi-PLC): cada endpoint que dispare un FB
recibe plc_name en el body y debe invocar with_plc(state, plc_name)
antes de invocar el FB. Esto asegura que state.selected_plc queda
sincronizado con el plc_name que va a usar el FB (defensa redundante
adicional al on_start del propio FB).

Sept-2026 (multi-PLC): ademas de setear ``selected_plc``, regenera
``state.excel_cache_active`` desde ``state.excel_cache_full`` filtrado
por el plc_name. Asi los FB que leen de ``excel_cache_active`` ven
siempre los datos del PLC seleccionado, sin tener que filtrar en
runtime.

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
    """Setea el PLC activo en app_state.selected_plc y regenera el cache activo.

    Idempotente: llamar varias veces con el mismo plc_name es seguro
    (no regenera el cache si selected_plc ya coincide).

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
            getattr(app_state, "selected_plc", ""),
        )
        return
    if getattr(app_state, "selected_plc", "") == plc_name:
        return  # idempotente: ya estaba seteado

    _logger.info("selected_plc: %r -> %r", app_state.selected_plc, plc_name)
    app_state.selected_plc = plc_name

    # Regenerar ``excel_cache_active`` desde ``excel_cache_full``
    # filtrado por el plc_name. Asi los FB que lean del cache activo
    # ven los datos correctos sin filtrar en runtime.
    excel_cache_full = getattr(app_state, "excel_cache_full", None)
    if excel_cache_full is not None:
        # Lazy import para evitar ciclo con el helper en runtime.
        from core.runtime.filter_excel_cache import filter_cache_by_plc
        app_state.excel_cache_active = filter_cache_by_plc(
            excel_cache_full, plc_name
        )


__all__ = ["with_plc"]