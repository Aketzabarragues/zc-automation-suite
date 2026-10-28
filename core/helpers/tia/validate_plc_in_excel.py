"""Helper para validar que el PLC seleccionado de TIA existe en el Excel.

Si el operario selecciona un PLC de TIA (vía ``PlcPanelView``) cuyo
nombre no esta en la ``Tabla_PLC`` del Excel cargado, el cache activo
(ya filtrado por plc_name) queda vacio y el sync atacaria TIA para
borrarlo TODO sin sentido.

Este helper se invoca en ``on_start`` de cada FB (igual que
``validate_plc_in_tia``). Falla-late con ``ValueError`` claro,
incluyendo la lista de PLCs disponibles en el Excel para guiar al
operario al fix correcto (subir otro Excel o seleccionar otro PLC).

NOTA sobre propagacion del error: como vive en ``on_start``, el
``ValueError`` lo captura el base y el FB transiciona a ``n_error``.
El router ya respondio ``202`` (el trabajo estaba encolado), asi que el
operario ve el error por push: evento SSE ``fb_state`` con
``error_msg`` y el stage en rojo en el tracker.
"""
from __future__ import annotations

import logging

from core.runtime.app_cache import AppCache
from core.runtime.excel_cache import excel_get_full


_logger = logging.getLogger(__name__)


def validate_plc_in_excel(app_cache: AppCache, plc_name: str, area_id: str) -> None:
    """Valida que ``plc_name`` esta en la ``Tabla_PLC`` del Excel cargado.

    Args:
        app_cache: contenedor del proceso (``AppCache``).
        plc_name: nombre del PLC (strict equality, D11).
        area_id: area del cache a leer. Obligatorio.

    Raises:
        ValueError: si no hay Excel cargado, si ``plc_name`` esta
            vacio, o si ``plc_name`` no esta en
            ``cache.plcs``.
    """
    if not plc_name:
        raise ValueError(
            "validate_plc_in_excel: plc_name vacio"
        )
    cache = excel_get_full(app_cache, area_id)
    if cache is None:
        raise ValueError(
            "No hay Excel cargado. Sube primero el archivo con "
            "POST /api/v1/excel/upload antes de lanzar un sync/preview."
        )
    # ``cache.plcs`` es la lista informativa de PLCs del Excel
    # (``Tabla_PLC``). Strict equality (D11).
    plc_names = [p.plc for p in cache.plcs]
    if plc_name not in plc_names:
        raise ValueError(
            f"PLC '{plc_name}' no esta en el Excel cargado. "
            f"PLCs en Excel: {plc_names}. "
            f"Sube un Excel que incluya este PLC o selecciona otro PLC de TIA."
        )
    _logger.debug(
        "validate_plc_in_excel: PLC %r OK (en Excel: %s)",
        plc_name, plc_names,
    )


__all__ = ["validate_plc_in_excel"]