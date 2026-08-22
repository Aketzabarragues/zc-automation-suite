"""Caso de Uso: sincronización unificada de PlcUserConstant (N_MAX + Dispositivos).

Orquesta el flujo completo de sincronización entre el Excel (estado
deseado) y TIA Portal (estado actual) bajo UNA transacción COM unificada
que cubre tanto cambios online (rename, update_value) como offline
(crear/eliminar PlcTagTable, añadir PlcUserConstant nuevas).

Restricción arquitectónica: este módulo es OFFLINE en cuanto a TIA; solo
interactúa con el PLC vía ``TIAProcessGateway`` (que delega al worker OT).

Flujo end-to-end (delegado al worker)
-------------------------------------
1. ``project.start_transaction()``
2. ONLINE: ``update_user_constant_value`` para N_MAX (cambio de valor).
3. ONLINE: ``update_user_constant_name`` para dispositivos (cambio de nombre).
4. ONLINE: ``export_tag_table`` para preparar los XML que se modificarán
   offline.
5. OFFLINE: crear/eliminar PlcTagTable + añadir PlcUserConstant nuevas.
6. ONLINE: ``import_plc_tags_xml`` para reintegrar los XML modificados.
7. CIERRE: ``end_transaction(rollback=False)`` o rollback completo si falla.

Si el rollback ocurre, el worker restaura los backups offline para que la
reversión sea atómica real (no solo in-memory del COM).

Dos modos de operación
----------------------
- ``preview(...)``: calcula los diffs pero **NO** aplica nada. Devuelve las
  operaciones que se aplicarían si el operario confirma.
- ``execute(...)``: calcula los diffs Y aplica la transacción COM unificada.

Ambos métodos comparten la misma lógica de cálculo (``_compute_operations``).

Inyección de dependencias (clean architecture)
----------------------------------------------
Este caso de uso recibe ``ConfigManager`` por constructor (DI explícita).
NO usa Singleton/global: esto permite testing con mocks del ConfigManager
y mantiene la capa de aplicación desacoplada del módulo de infraestructura.

Las tablas PLC de cada tipo de dispositivo (``2000_Disp_ED``,
``2000_Disp_V``, etc.) se resuelven dinámicamente vía
``ConfigManager.get_tag_table_name(hw_type)``. El caller solo necesita
indicar el **tipo lógico** (``"ed"``, ``"v"``, etc.), NO el nombre de la
tabla física.
"""
from __future__ import annotations

import logging
from typing import Any

from application.use_cases.diff_constants import CalculateConstantsDiffUseCase
from infrastructure.config_manager import ConfigManager
from infrastructure.gateway import TIAProcessGateway


_logger: logging.Logger = logging.getLogger(f"{__name__}.SyncConstantsUnifiedUseCase")


# Default undo_text para la transacción unificada.
_DEFAULT_UNDO_TEXT = "Sync Constants Unified (N_MAX + Dispositivos)"


class SyncConstantsUnifiedUseCase:
    """Sincroniza PlcUserConstant entre Excel y TIA Portal en una transacción.

    Es un **orquestador puro**: no contiene lógica de modificación XML
    ni de COM. Solo:
      1. Lee el estado actual del PLC vía gateway.
      2. Calcula diffs puros (``CalculateConstantsDiffUseCase``).
      3. Empaqueta las operaciones online + cambios offline en una sola
         llamada a ``gateway.execute_unified_sync()`` que el worker OT
         ejecuta dentro de ``start_transaction`` / ``end_transaction``.
    """

    def __init__(
        self,
        gateway: TIAProcessGateway,
        config_manager: ConfigManager,
    ) -> None:
        """Inicializa el caso de uso con sus dependencias.

        Args:
            gateway:        Gateway asíncrono hacia el worker OT.
            config_manager: Gestor de configuración con el mapeo
                ``hw_type → tag_table``. Usado para resolver los nombres
                físicos de las PlcTagTable de dispositivos.
        """
        self._gateway = gateway
        self._config = config_manager

    # ── PREVIEW: SOLO calcula diffs, NO toca TIA ──────────────────────
    async def preview(
        self,
        plc_name: str,
        nmax_current_state: dict[str, str],
        nmax_desired_state: dict[str, int],
        device_states_by_type: dict[str, dict[str, dict[str, Any]]],
    ) -> dict[str, Any]:
        """Calcula diffs sin aplicar nada en TIA.

        Args:
            plc_name: Nombre del PLC destino.
            nmax_current_state: ``{valor_str: nombre}`` desde TIA para la
                tabla de N_MAX (resultado de ``gateway.get_user_constants``).
            nmax_desired_state: ``{nombre: valor}`` desde el Excel para N_MAX.
            device_states_by_type: ``{hw_type: {"current": ..., "desired": ...}}``
                por cada tipo de dispositivo.

        Returns:
            ``dict`` con:
              - ``nmax_ops``: lista de operaciones N_MAX pendientes.
              - ``device_diffs``: ``{hw_type: [ops]}`` por tipo de dispositivo.
              - ``summary``: ``{n_max_updates, device_renames, total_ops, has_changes}``.
        """
        return self._compute_operations(
            plc_name=plc_name,
            nmax_current_state=nmax_current_state,
            nmax_desired_state=nmax_desired_state,
            device_states_by_type=device_states_by_type,
        )

    # ── APPLY: ejecuta el sync real ────────────────────────────────────
    async def execute(
        self,
        plc_name: str,
        nmax_current_state: dict[str, str],
        nmax_desired_state: dict[str, int],
        device_states_by_type: dict[str, dict[str, dict[str, Any]]],
        device_offline_changes: list[dict[str, Any]] | None = None,
        undo_text: str = _DEFAULT_UNDO_TEXT,
    ) -> dict[str, Any]:
        """Ejecuta la sincronización unificada (calcula diff + aplica).

        Args:
            plc_name: Nombre del PLC destino.
            nmax_current_state: ``{valor_str: nombre}`` desde TIA.
            nmax_desired_state: ``{nombre: valor}`` desde el Excel.
            device_states_by_type: ``{hw_type: {"current": ..., "desired": ...}}``.
            device_offline_changes: lista opcional de cambios offline
                (crear/eliminar tablas, añadir PlcUserConstant nuevas).
            undo_text: etiqueta visible en el historial de Undo de TIA.

        Returns:
            ``dict`` con el resultado devuelto por el worker.
        """
        if not plc_name:
            raise ValueError("plc_name no puede estar vacío.")

        # 1. Calcular diffs (reusando el helper compartido con preview()).
        ops = self._compute_operations(
            plc_name=plc_name,
            nmax_current_state=nmax_current_state,
            nmax_desired_state=nmax_desired_state,
            device_states_by_type=device_states_by_type,
        )
        nmax_ops = ops["nmax_ops"]
        rename_ops = ops["rename_ops"]

        # 2. Si no hay nada que aplicar, retornar early (idempotencia).
        offline_changes = device_offline_changes or []
        total_ops = len(nmax_ops) + len(rename_ops) + len(offline_changes)
        if total_ops == 0:
            _logger.info("Sin operaciones que aplicar. Sync no-op.")
            return {"success": True, "operations_executed": 0, "details": []}

        _logger.info(
            f"Sync unificado (PLC='{plc_name}'): "
            f"{len(nmax_ops)} update_value (N_MAX) + "
            f"{len(rename_ops)} rename (dispositivos) + "
            f"{len(offline_changes)} offline changes."
        )

        # 3. Delegar al gateway (worker) — transacción COM unificada.
        result = await self._gateway.execute_unified_sync(
            plc_name=plc_name,
            nmax_ops=nmax_ops,
            device_renames=rename_ops,
            device_offline_changes=offline_changes,
            undo_text=undo_text,
        )

        # 4. Invalidar caché tras un sync exitoso.
        self._gateway.clear_cache()

        return result

    # ── HELPER COMPARTIDO (preview + execute) ──────────────────────────
    def _compute_operations(
        self,
        plc_name: str,
        nmax_current_state: dict[str, str],
        nmax_desired_state: dict[str, int],
        device_states_by_type: dict[str, dict[str, dict[str, Any]]],
    ) -> dict[str, Any]:
        """Calcula las operaciones de diff sin tocar TIA.

        Usado tanto por ``preview()`` (devuelve resultado) como por
        ``execute()`` (las aplica).

        Returns:
            ``dict`` con ``nmax_ops``, ``rename_ops``, ``device_diffs`` y
            ``summary``.
        """
        if not plc_name:
            raise ValueError("plc_name no puede estar vacío.")
        if not device_states_by_type:
            _logger.warning(
                f"Sync unificado para PLC '{plc_name}': "
                "sin device_states_by_type. Solo se aplicarán cambios N_MAX."
            )

        # 1. Resolver N_MAX table name desde ConfigManager.
        nmax_table_name = self._config.get_global_config_table_name()

        # 2. Calcular diff N_MAX.
        nmax_ops: list[dict[str, Any]] = (
            CalculateConstantsDiffUseCase.calculate_nmax_diff(
                plc_name=plc_name,
                config_table_name=nmax_table_name,
                current_state=nmax_current_state,
                desired_state=nmax_desired_state,
            )
        )

        # 3. Resolver tag_tables y calcular renames por hw_type.
        rename_ops: list[dict[str, Any]] = []
        device_diffs: dict[str, list[dict[str, Any]]] = {}
        for hw_type, states in device_states_by_type.items():
            tag_table = self._config.get_tag_table_name(hw_type)
            if tag_table is None:
                _logger.warning(
                    f"Tipo de dispositivo '{hw_type}' no configurado en "
                    f"ConfigManager (se omite del sync unificado)."
                )
                continue

            current_state: dict[str, str] = states.get("current", {}) or {}
            desired_state: dict[str, int] = states.get("desired", {}) or {}

            table_renames = (
                CalculateConstantsDiffUseCase.calculate_device_rename_diff(
                    plc_name=plc_name,
                    config_table_name=tag_table,
                    current_state=current_state,
                    desired_state=desired_state,
                )
            )
            rename_ops.extend(table_renames)
            device_diffs[hw_type] = table_renames

        # 4. Calcular resumen.
        summary = {
            "n_max_updates": len(nmax_ops),
            "device_renames": len(rename_ops),
            "total_ops": len(nmax_ops) + len(rename_ops),
            "has_changes": bool(nmax_ops or rename_ops),
        }

        return {
            "nmax_ops": nmax_ops,
            "rename_ops": rename_ops,
            "device_diffs": device_diffs,
            "summary": summary,
        }


__all__ = ["SyncConstantsUnifiedUseCase"]
