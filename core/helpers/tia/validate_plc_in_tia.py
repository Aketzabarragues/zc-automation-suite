"""Validacion de plc_name contra los PLCs reales en TIA Portal.

Cada FB que ataca TIA recibe un ``plc_name`` y debe verificar que ese PLC
existe en TIA antes de operar. Este helper encapsula la llamada a
``list_plcs`` y la comprobacion strict equality.

Uso:
    from core.helpers.tia.validate_plc_in_tia import validate_plc_in_tia

    # en on_start de un FB:
    validate_plc_in_tia(self._tia_client, plc_name)

Contrato de fallos:
    - ``ValueError``: ``plc_name`` vacio, o no esta entre los PLCs de TIA.
    - ``RuntimeError``: TIA respondio con error, o no devolvio ningun PLC.
    - Timeout del worker TIA: NO es un fallo. La cola del worker es FIFO
      y de un solo hilo, asi que ``list_plcs`` expira si el worker esta
      ocupado con otra operacion. Eso no dice nada sobre si el PLC existe,
      asi que la validacion se omite y el FB sigue; el error real (si lo
      hay) aparece en el primer comando TIA del FB, con su mensaje propio.
"""
from __future__ import annotations

import logging
from typing import Any


_logger = logging.getLogger(__name__)


def validate_plc_in_tia(tia_client: Any, plc_name: str, timeout: float = 2.0) -> None:
    """Verifica que ``plc_name`` exista en TIA Portal.

    Llama a ``list_plcs`` con timeout corto y comprueba strict equality
    contra los nombres de PLC del proyecto TIA activo.

    Si el worker TIA esta ocupado y la llamada expira, no se aborta: se
    loggea un warning y la validacion se omite (ver docstring del modulo).

    Args:
        tia_client: instancia de ``SyncTIAClient`` (TIA loop).
        plc_name: nombre del PLC que el caller quiere atacar.
        timeout: segundos maximos de espera para la respuesta de TIA.

    Raises:
        RuntimeError: si TIA no responde, no hay PLCs, o el wrapper
            no esta attached.
        ValueError: si ``plc_name`` no esta en la lista de PLCs de TIA.
            El mensaje incluye los PLCs disponibles para que el
            operario sepa que opciones tiene.
    """
    if not plc_name:
        raise ValueError("validate_plc_in_tia: plc_name vacio")

    # 1. Llamar a list_plcs (bloqueante, con timeout).
    try:
        response = tia_client.submit_and_wait("list_plcs", timeout=timeout)
    except TimeoutError:
        _logger.warning(
            "validate_plc_in_tia: list_plcs no respondio en %ss "
            "(worker TIA ocupado). Se omite la validacion del PLC '%s'.",
            timeout,
            plc_name,
        )
        return

    if not response.get("ok", False):
        error = response.get("error", "unknown")
        raise RuntimeError(
            f"validate_plc_in_tia: list_plcs fallo: {error}"
        )

    # 2. Extraer nombres de PLCs.
    payload = response.get("result", {}) or {}
    plcs_payload = payload.get("plcs", []) or []
    plc_names = [p.get("name", "") for p in plcs_payload if p.get("name")]

    if not plc_names:
        raise RuntimeError(
            "validate_plc_in_tia: TIA no devolvio PLCs. "
            "Asegurate de que el proyecto tiene al menos un PLC."
        )

    # 3. Validar strict equality.
    if plc_name not in plc_names:
        available = sorted(plc_names)
        raise ValueError(
            f"PLC '{plc_name}' no existe en TIA Portal. "
            f"PLCs disponibles: {available}"
        )

    _logger.debug("validate_plc_in_tia: PLC '%s' OK", plc_name)


__all__ = ["validate_plc_in_tia"]
