"""Helper para validar que el PLC seleccionado de TIA existe en el Excel.

Sept-2026 (multi-PLC, propuesta del operario): si el operario
selecciona un PLC de TIA (vía ``PlcPanelView``) cuyo nombre no esta
en la ``Tabla_PLC`` del Excel cargado, el ``excel_cache_active`` (ya
filtrado por plc_name) queda vacio y el sync atacaria TIA para
borrarlo TODO sin sentido.

Este helper se invoca en ``on_start`` de cada FB (igual que
``validate_plc_in_tia``). Falla-late con ``ValueError`` claro,
incluyendo la lista de PLCs disponibles en el Excel para guiar al
operario al fix correcto (subir otro Excel o seleccionar otro PLC).

NOTA sobre propagacion del error: como vive en ``on_start``, el
``ValueError`` se lanza en el primer ``tick()`` del loop async, NO
en el ``await fb.start()``. Eso significa que el endpoint devuelve
200 OK inicialmente y el operario ve el error via progress tracker
o logs. Si quieres feedback inmediato en el HTTP response, hay que
duplicar la validacion en el endpoint (no es scope de este helper).
"""
from __future__ import annotations

import logging
from typing import Any


_logger = logging.getLogger(__name__)


def validate_plc_in_excel(state: Any, plc_name: str) -> None:
    """Valida que ``plc_name`` esta en la ``Tabla_PLC`` del Excel cargado.

    Args:
        state: instancia Singleton de AppState (o cualquier objeto con
            atributo ``excel_cache_full`` de tipo ``DataExcelCache``).
        plc_name: nombre del PLC (strict equality, D11).

    Raises:
        ValueError: si no hay Excel cargado, si ``plc_name`` esta vacio,
            o si ``plc_name`` no esta en ``excel_cache_full.plcs``.
    """
    if not plc_name:
        raise ValueError(
            "validate_plc_in_excel: plc_name vacio"
        )
    cache = getattr(state, "excel_cache_full", None)
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
