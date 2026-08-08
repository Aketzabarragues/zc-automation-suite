"""Caso de Uso: cálculo de diferencias entre estado deseado y actual.

Motor puro de diffs: recibe el estado actual del PLC (exportado a XML)
y el estado deseado (del Excel), y devuelve la lista de operaciones
necesarias para sincronizar el PLC bajo una transacción atómica.

Restricción arquitectónica: este módulo es OFFLINE; no importa
``siemens_tia_scripting``.
"""
from __future__ import annotations

from typing import Any


class CalculateConstantsDiffUseCase:
    """Calcula el batch de operaciones para sincronizar PLC con Excel."""

    @staticmethod
    def execute(
        plc_name: str,
        config_table_name: str,
        current_state: dict[str, str],
        desired_state: dict[str, int],
    ) -> list[dict[str, Any]]:
        """Compara estado actual vs. deseado y devuelve operaciones a aplicar.

        Args:
            plc_name:          Nombre del PLC destino (para los args).
            config_table_name: Tabla donde residen las PlcUserConstant.
            current_state:     ``{valor_int: nombre}`` desde TIA Portal.
                               El estado REAL del PLC.
            desired_state:     ``{nombre: valor_int}`` desde el Excel.
                               El estado DESEADO a alcanzar.

        Returns:
            Lista de operaciones ``[{"command": str, "args": dict}, ...]``
            lista para ``TIAProcessGateway.execute_transactional_batch``.

        Notas:
            - **Update**: Si la constante existe en ambos estados con
              valor distinto → emite ``update_user_constant_value``.
            - **Create**: Deshabilitado (TIA Portal no soporta la
              creación de PlcUserConstant por API nativa; requiere
              inyección directa sobre el XML en una fase posterior).
            - **Delete**: Deshabilitado por defecto (las constantes
              rara vez se borran en producción). Implementación
              disponible en el bloque comentado al final del método.
        """
        # ``current_state`` tiene forma ``{valor: nombre}``. Lo invertimos
        # UNA sola vez para comparar contra ``desired_state`` (``{nombre: valor}``)
        # con búsquedas O(1) por nombre.
        current_by_name: dict[str, str] = {
            name: value for value, name in current_state.items()
        }

        operations: list[dict[str, Any]] = []

        # ── Lógica Update ─────────────────────────────────────────────
        for constant_name, desired_value in desired_state.items():
            current_value_str = current_by_name.get(constant_name)
            if current_value_str is None:
                # La constante existe en desired pero no en current.
                # Create pendiente de soporte nativo en TIA Portal.
                # operations.append({
                #     "command": "create_user_constant",
                #     "args": {
                #         "plc_name": plc_name,
                #         "table_name": config_table_name,
                #         "constant_name": constant_name,
                #         "new_value": int(desired_value),
                #     },
                # })
                continue
            try:
                current_value = int(current_value_str)
            except (TypeError, ValueError):
                continue
            if current_value == desired_value:
                continue
            operations.append(
                {
                    "command": "update_user_constant_value",
                    "args": {
                        "plc_name": plc_name,
                        "table_name": config_table_name,
                        "constant_name": constant_name,
                        "new_value": int(desired_value),
                    },
                }
            )

        # ── Lógica Delete (opcional / futura fase) ────────────────────
        # Deshabilitada por defecto. Descomentar si el dominio lo requiere.
        # for _value_str, name in current_state.items():
        #     if name not in desired_state:
        #         operations.append({
        #             "command": "delete_user_constant",
        #             "args": {
        #                 "plc_name": plc_name,
        #                 "table_name": config_table_name,
        #                 "constant_name": name,
        #             },
        #         })

        return operations
