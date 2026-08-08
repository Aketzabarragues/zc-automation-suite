"""Caso de Uso: cálculo de diferencias entre estado deseado y actual.

️ SCAFFOLDING — Portar la lógica real desde ``_legacy_reference/``.

Devuelve un lote de operaciones compatible con
``TIAProcessGateway.execute_transactional_batch`` (forma::

    [{"command": "update_user_constant_value", "args": {...}}, ...]
)
"""
from __future__ import annotations

from typing import Any


class CalculateConstantsDiffUseCase:
    """Stub. La lógica de diff real debe portarse desde el repositorio legacy."""

    @staticmethod
    def execute(
        plc_name: str,
        config_table_name: str,
        current_state: dict[str, str],
        desired_state: dict[str, int],
    ) -> list[dict[str, Any]]:
        """Calcula el batch de operaciones para sincronizar PLC con Excel.

        Args:
            plc_name:          Nombre del PLC destino (para los args).
            config_table_name: Tabla donde residen las PlcUserConstant.
            current_state:     ``{valor_int: nombre}`` desde TIA Portal.
            desired_state:     ``{nombre: valor_int}`` desde el Excel.

        Returns:
            Lista de operaciones ``[{"command": str, "args": dict}, ...]``
            lista para ``execute_transactional_batch``.

        Raises:
            NotImplementedError: Hasta que se porten los modelos reales
                desde ``_legacy_reference/``.
        """
        raise NotImplementedError(
            "CalculateConstantsDiffUseCase.execute es un stub. "
            "Portar la lógica desde _legacy_reference/. "
            f"PLC='{plc_name}' tabla='{config_table_name}' "
            f"current_keys={len(current_state)} desired_keys={len(desired_state)}"
        )
