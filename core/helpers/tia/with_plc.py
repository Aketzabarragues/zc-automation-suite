"""Helper para setear el PLC activo en ``app_cache``.

Patron stateless: cada endpoint que dispare un FB
recibe plc_name en el body y debe invocar ``with_plc(app_cache, plc_name, area_id)``
antes de invocar el FB. Esto asegura que ``app_cache.selected_plc``
queda sincronizado con el plc_name que va a usar el FB (defensa
redundante adicional al on_start del propio FB).

Ademas de setear ``selected_plc``, regenera
``excel_active_by_area[area_id]`` desde ``excel_full_by_area[area_id]``
filtrado por el plc_name. Asi los FB que leen de ``excel_get_active``
ven siempre los datos del PLC seleccionado, sin tener que filtrar en
runtime.

Uso:
    from core.helpers.tia.with_plc import with_plc

    @bp.post("/sync/commit")
    def commit():
        body = request.get_json()
        plc_name = body.get("plc_name", "")
        with_plc(app_cache, plc_name, "alimentacion")
        job_id = engine.submit("disp_sincronizar", plc_name=plc_name)
        return jsonify({"ok": True, "job_id": job_id}), 202
"""
from __future__ import annotations

import dataclasses
import logging

from core.runtime.app_cache import AppCache
from core.runtime.excel_cache import (
    derive_excel_active,
    excel_get_active,
    excel_set_active,
)


_logger = logging.getLogger(__name__)


def with_plc(
    app_cache: AppCache,
    plc_name: str,
    area_id: str,
) -> None:
    """Setea el PLC activo y regenera el cache activo del area.

    Idempotente: llamar varias veces con el mismo plc_name es seguro
    (no regenera el cache si ``selected_plc`` ya coincide).

    Args:
        app_cache: contenedor del proceso.
        plc_name: nombre del PLC (strict equality con TIA Portal).
            Si esta vacio, NO modifica ``selected_plc`` (mantiene el
            valor que ya estaba; el caller deberia asegurarse de pasar
            un plc_name valido).
        area_id: area del cache a regenerar. Obligatorio (el core no
            conoce nombres de areas; el caller lo aporta).
    """
    if not plc_name:
        _logger.warning(
            "with_plc: plc_name vacio, selected_plc queda en %r",
            app_cache.get_state().selected_plc,
        )
        return

    state = app_cache.get_state()
    if state.selected_plc == plc_name and excel_get_active(app_cache, area_id) is not None:
        return  # idempotente: ya estaba seteado

    _logger.info(
        "selected_plc: %r -> %r (area=%s)",
        state.selected_plc, plc_name, area_id,
    )

    def _mutate(s):
        return dataclasses.replace(s, selected_plc=plc_name)

    app_cache.mutate(_mutate, slot="selected_plc")

    derived = derive_excel_active(app_cache, area_id, plc_name)
    if derived is not None:
        excel_set_active(app_cache, area_id, derived)


__all__ = ["with_plc"]