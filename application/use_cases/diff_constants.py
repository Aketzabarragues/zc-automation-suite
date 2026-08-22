"""Casos de Uso: cálculo de diferencias entre estado deseado y actual.

Motor puro de diffs para PlcUserConstant. Recibe el estado actual del PLC
(exportado a XML o leído por COM) y el estado deseado (del Excel), y
devuelve la lista de operaciones necesarias para sincronizar el PLC bajo
una transacción atómica.

Restricción arquitectónica: este módulo es OFFLINE; no importa
``siemens_tia_scripting``.

Dos tipos de diff
-----------------
El subdominio de constantes tiene **dos naturalezas distintas** que
requieren lógicas de diff diferentes:

1. **N_MAX (dimensiones)**
   - El nombre es la KEY estable (``N_MAX_DISP_ED``, ``N_MAX_DISP_EA``...).
   - Lo que cambia es el VALOR (ej. ``25`` → ``30``).
   - Operación: ``update_user_constant_value``.

2. **Dispositivos**
   - El VALOR es el UID estable del dispositivo (entero único).
   - Lo que cambia es el NOMBRE (etiqueta humana).
   - Operación: ``update_user_constant_name``.

Esta separación es FUNDAMENTAL porque mezclar ambos diffs lleva a errores
sutiles (renombrar constantes N_MAX o cambiar valores de dispositivos).
"""
from __future__ import annotations

from typing import Any


class CalculateConstantsDiffUseCase:
    """Motor puro de diffs para PlcUserConstant (N_MAX y Dispositivos)."""

    # ──────────────────────────────────────────────────────────────────
    # Diff 1: N_MAX (cambio de VALOR, key estable = nombre)
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def calculate_nmax_diff(
        plc_name: str,
        config_table_name: str,
        current_state: dict[str, int],
        desired_state: dict[str, int],
    ) -> list[dict[str, Any]]:
        """Calcula operaciones para sincronizar constantes N_MAX.

        Estrategia: diff por **nombre** (key estable). Si el valor en
        TIA difiere del Excel, emite ``update_user_constant_value``.

        Args:
            plc_name:          Nombre del PLC destino (para los args).
            config_table_name: Tabla donde residen las PlcUserConstant N_MAX.
            current_state:     ``{nombre: valor_int}`` desde TIA Portal
                               (resultado de ``SimaticMLTagParser.parse_user_constants``).
                               Ej: ``{"N_MAX_DISP_ED": 25, "N_MAX_DISP_EA": 10}``.
            desired_state:     ``{nombre: valor_int}`` desde el Excel.
                               Ej: ``{"N_MAX_DISP_ED": 30, "N_MAX_DISP_EA": 15}``.

        Returns:
            Lista de operaciones ``[{"command": str, "args": dict}, ...]``
            con shape compatible con ``TIAProcessGateway.execute_transactional_batch``.

        Notas:
            - **Create**: NO se emite. Si una constante N_MAX no existe en
              TIA pero sí en el Excel, se ignora (las N_MAX son un conjunto
              cerrado y conocido: ``N_MAX_DISP_ED``, ``N_MAX_DISP_EA``…).
              Si necesitas crear nuevas, usa ``create_user_constant`` desde
              un flujo de inyección XML explícito (no soportado vía COM).
            - **Delete**: NO se emite. Las N_MAX tampoco se eliminan en
              producción.
        """
        # ``current_state`` ya viene con forma ``{nombre: valor}`` del
        # parser (key estable = nombre, evita colisiones por valor
        # repetido entre varias N_MAX).
        operations: list[dict[str, Any]] = []

        for constant_name, desired_value in desired_state.items():
            current_value = current_state.get(constant_name)
            if current_value is None:
                # La constante no existe en TIA → no la creamos vía COM.
                # (Esto es coherente con la política "N_MAX es conjunto cerrado".)
                continue
            if current_value == int(desired_value):
                continue  # ya está en el valor deseado
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

        return operations

    # ──────────────────────────────────────────────────────────────────
    # Diff 2: Dispositivos (cambio de NOMBRE, key estable = valor)
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def calculate_device_rename_diff(
        plc_name: str,
        config_table_name: str,
        current_state: dict[str, str],
        desired_state: dict[str, int],
    ) -> list[dict[str, Any]]:
        """Calcula operaciones para renombrar PlcUserConstant de dispositivos.

        Estrategia: diff por **valor** (UID estable del dispositivo). Si el
        nombre en TIA difiere del nombre en Excel, emite
        ``update_user_constant_name``. El valor NUNCA se toca.

        Args:
            plc_name:          Nombre del PLC destino.
            config_table_name: Tabla donde residen las PlcUserConstant de
                               dispositivos (ej. ``2000_Disp_ED``).
            current_state:     ``{valor_int_str: nombre}`` desde TIA.
                               Ej: ``{"1": "V_001", "2": "V_002"}``.
            desired_state:     ``{nombre: valor_int}`` desde el Excel.
                               Ej: ``{"V_VA_101": 1, "V_VA_102": 2}``.

        Returns:
            Lista de operaciones ``[{"command": str, "args": dict}, ...]``
            con ``update_user_constant_name`` (preservando el valor).

        Notas:
            - El **valor** es el UID estable del dispositivo; nunca cambia.
            - Si un valor existe en desired pero no en current → se ignora
              (caso de dispositivo nuevo; requiere inyección XML offline).
            - Si un valor existe en current pero no en desired → se ignora
              (caso de dispositivo eliminado; requiere eliminación COM
              explícita o de tabla entera, gestionada por ``plc_tag_table_manager``).
        """
        operations: list[dict[str, Any]] = []

        for desired_name, desired_value in desired_state.items():
            try:
                desired_value_int = int(desired_value)
            except (TypeError, ValueError):
                continue
            desired_value_str = str(desired_value_int)

            # Buscar la constante actual por VALOR (identidad estable).
            current_name = current_state.get(desired_value_str)
            if current_name is None:
                # No existe en TIA → no se puede renombrar; requiere CREATE.
                continue
            if current_name == desired_name:
                continue  # ya tiene el nombre correcto (idempotente)

            operations.append(
                {
                    "command": "update_user_constant_name",
                    "args": {
                        "plc_name": plc_name,
                        "table_name": config_table_name,
                        "current_name": current_name,
                        "new_name": desired_name,
                        # NO se incluye new_value: el valor se preserva.
                    },
                }
            )

        return operations


__all__ = ["CalculateConstantsDiffUseCase"]
