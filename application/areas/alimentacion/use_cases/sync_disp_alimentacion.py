"""Caso de uso unificado del área de alimentación: sync de dispositivos con TIA Portal.

Punto de entrada único para sincronizar el Excel corporativo (vía
``AppState``) con el PLC de TIA Portal. Esta release implementa solo el
flujo de modificación **online** de las PlcUserConstant N_MAX; la
arquitectura está preparada para crecer con más tipos de sync (renombrado
de devices, add/remove de PlcTag + .s7dcl, etc.) sin breaking changes.

Responsabilidades de esta release
---------------------------------
- ``preview_disp(plc_name)`` → calcula el diff de N_MAX entre TIA y
  ``AppState.dimensiones`` sin tocar TIA Portal.
- ``apply_disp(plc_name)``   → aplica el diff en UNA transacción COM única,
  delegando en ``gateway.execute_transactional_batch`` (worker ya
  implementa el ciclo ``start_transaction`` / ``end_transaction`` con
  rollback atómico).

Responsabilidades futuras (NO incluidas)
-----------------------------------------
- ``preview_devices`` / ``apply_devices`` → renombrado online de devices.
- ``sync_instances`` → add/remove/rename PlcTag + .s7dcl.
- ``load_excel`` → carga Excel → AppState.

Decisiones de diseño
--------------------
- **Una sola transacción para todos los N_MAX**: ``apply_disp`` no itera
  ``gateway.update_user_constant_value`` N veces (eso abriría N
  transacciones independientes). Construye la lista de ops y se la pasa
  al worker con ``execute_transactional_batch``; el worker hace
  ``start_transaction`` → loop → ``end_transaction(rollback=False)`` o
  ``end_transaction(rollback=True)`` si algo falla.
- **Cero duplicación**: el worker es la única fuente de verdad para la
  transacción. El use case solo construye la lista de ops y delega.
- **Naming a nivel de "dispositivos"**: los métodos ``preview_disp`` /
  ``apply_disp`` no llevan sufijo ``_nmax`` a propósito. Cuando se
  añadan device renames o instance sync, estos métodos se extienden
  internamente (o se añaden ``preview_devices`` / ``apply_devices``) sin
  necesidad de renombrar la API pública.
- **Offline-first read**: la lectura del estado actual del PLC se hace
  con export bulk del árbol + parse selectivo del único XML
  ``000_Sistema/000_Config_Dispositivos.xml``. NO se exportan las 6
  tablas de dispositivos.

Restricción arquitectónica
--------------------------
Este módulo NO importa ``siemens_tia_scripting``. Toda interacción con
TIA Portal pasa por ``TIAProcessGateway`` (que delega al worker OT).
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from application.areas.alimentacion.use_cases.diff_constants import (
    CalculateConstantsDiffUseCase,
)
from application.state import AppState
from infrastructure.config_manager import ConfigManager
from infrastructure.gateway import TIAProcessGateway
from infrastructure.xml.tag_table_parser import SimaticMLTagParser


_logger: logging.Logger = logging.getLogger(
    f"{__name__}.SyncDispAlimentacionUseCase"
)


class SyncDispAlimentacionUseCase:
    """Caso de uso unificado del área de alimentación (TIA Portal sync)."""

    _TEMP_PREFIX = "zc_nmax_"

    def __init__(
        self,
        gateway: TIAProcessGateway,
        config_manager: ConfigManager,
        app_state: AppState,
    ) -> None:
        self._gateway = gateway
        self._config = config_manager
        self._state = app_state

    # ── API pública ────────────────────────────────────────────────────

    async def preview_disp(self, plc_name: str) -> dict[str, Any]:
        """Calcula el diff de N_MAX entre TIA y AppState.

        NO toca TIA Portal. Si ``AppState.dimensiones`` está vacío,
        devuelve ``has_changes=False`` con un warning accionable (el
        operario debe cargar el Excel primero).

        Returns:
            ``dict`` con la forma::

                {
                    # --- Campos NUEVOS (release actual) ---
                    "plc_name": str,
                    "success": True,
                    "preview": True,
                    "has_changes": bool,
                    "current":  {"N_MAX_DISP_ED": 25, ...},
                    "desired":  {"N_MAX_DISP_ED": 30, ...},
                    "ops":      [{"command": ..., "args": ...}, ...],
                    "summary":  {  # mezcla de nuevos + legacy
                        "n_max_updates": int,
                        "total_ops": int,
                        "agregados": 0,        # legacy SPA
                        "renombrados": 0,      # legacy SPA
                        "eliminados": 0,       # legacy SPA
                        "sin_cambios": int,    # legacy SPA
                    },
                    "warnings": list[str],

                    # --- Campos LEGACY (compat con la SPA de alimentacion) ---
                    # En esta release todos los counters de devices están a 0;
                    # cuando crezca el use case con device renames / instance
                    # sync, estos campos se rellenarán con la forma legacy.
                    "agregados":   list,   # siempre [] en esta release
                    "eliminados":  list,   # siempre [] en esta release
                    "renombrados": list,   # siempre [] en esta release
                    "todos":       list,   # siempre [] en esta release
                    "nmax": {
                        "current": {"N_MAX_DISP_ED": 10, ...},
                        "desired": {"N_MAX_DISP_ED": 15, ...},
                        "todos":   [
                            {"name": "N_MAX_DISP_ED",
                             "actual": 10, "nuevo": 15,
                             "status": "actualizar" | "sin_cambios"},
                            ...
                        ],
                        "summary": {
                            "actualizar":  int,
                            "sin_cambios": int,
                            "total":       int,
                        },
                    },
                }
        """
        warnings = self._check_app_state()
        if warnings:
            return self._empty_preview(plc_name, warnings)

        current, current_warnings = await self._read_nmax_current(plc_name)
        warnings.extend(current_warnings)
        desired = self._build_nmax_desired()
        ops = self._compute_nmax_ops(plc_name, current, desired)
        nmax_block = self._build_nmax_block(current, desired)
        return self._build_preview_response(
            plc_name=plc_name,
            current=current,
            desired=desired,
            ops=ops,
            nmax_block=nmax_block,
            warnings=warnings,
        )

    async def apply_disp(self, plc_name: str) -> dict[str, Any]:
        """Aplica el diff de N_MAX en UNA transacción COM única.

        Si el diff está vacío, NO toca TIA (no-op idempotente). Si hay
        ops, las ejecuta vía ``gateway.execute_transactional_batch`` —
        el worker abre la transacción, itera las ops online y cierra con
        rollback atómico si algo falla.

        Returns:
            ``dict`` con la forma::

                {
                    "plc_name": str,
                    "success": True,
                    "applied": True,
                    "operations_executed": int,
                    "summary": {"n_max_updates": int, "total_ops": int},
                    "details": list[dict],  # del worker
                    "warnings": list[str],
                }
        """
        warnings = self._check_app_state()
        if warnings:
            # Mismo short-circuit que preview_disp: no se invoca el
            # gateway si no hay desired.
            return {
                "plc_name": plc_name,
                "success": True,
                "applied": True,
                "operations_executed": 0,
                "summary": {"n_max_updates": 0, "total_ops": 0},
                "details": [],
                "warnings": warnings,
            }

        current, current_warnings = await self._read_nmax_current(plc_name)
        warnings.extend(current_warnings)
        desired = self._build_nmax_desired()
        ops = self._compute_nmax_ops(plc_name, current, desired)

        if not ops:
            _logger.info(
                f"[{plc_name}] apply_disp: diff vacío, no se toca TIA."
            )
            return {
                "plc_name": plc_name,
                "success": True,
                "applied": True,
                "operations_executed": 0,
                "summary": {"n_max_updates": 0, "total_ops": 0},
                "details": [],
                "warnings": warnings,
            }

        config_table = self._config.get_global_config_table_name()
        operations = [
            {
                "command": "update_user_constant_value",
                "args": {
                    "plc_name": plc_name,
                    "table_name": config_table,
                    "constant_name": op["args"]["constant_name"],
                    "new_value": op["args"]["new_value"],
                },
            }
            for op in ops
        ]
        undo_text = f"SyncDispAlimentacion ({plc_name})"

        _logger.info(
            f"[{plc_name}] apply_disp: {len(ops)} update_user_constant_value "
            f"en una sola transacción. undo_text={undo_text!r}."
        )

        result = await self._gateway.execute_transactional_batch(
            operations,
            undo_text=undo_text,
        )
        self._gateway.clear_cache()

        return {
            "plc_name": plc_name,
            "success": True,
            "applied": True,
            "operations_executed": result["operations_executed"],
            "summary": {
                "n_max_updates": len(ops),
                "total_ops": len(ops),
            },
            "details": result.get("details", []),
            "warnings": warnings,
        }

    # ── Helpers privados compartidos (preview_disp + apply_disp) ──────

    def _build_nmax_block(
        self,
        current: dict[str, int],
        desired: dict[str, int],
    ) -> dict[str, Any]:
        """Construye el bloque ``nmax`` legacy con ``{current, desired, todos, summary}``.

        Shape compatible con la SPA de alimentacion (Dispositivos.js):
          - ``todos``: lista de ``{name, actual, nuevo, status}`` con
            ``status ∈ {"actualizar", "sin_cambios"}``.
          - ``summary``: contadores ``{actualizar, sin_cambios, total}``.

        Una N_MAX se considera ``"sin_cambios"`` si el valor en TIA
        coincide con el deseado (incluye el caso ``None`` → 0 cuando
        la N_MAX no existe en TIA y el desired es 0).
        """
        todos: list[dict[str, Any]] = []
        for name in desired.keys():
            cur_val = current.get(name)
            des_val = desired[name]
            if cur_val is not None and cur_val == des_val:
                status = "sin_cambios"
            else:
                status = "actualizar"
            todos.append({
                "name": name,
                "actual": cur_val,
                "nuevo": des_val,
                "status": status,
            })
        n_actualizar = sum(1 for r in todos if r["status"] == "actualizar")
        n_sin_cambios = sum(1 for r in todos if r["status"] == "sin_cambios")
        return {
            "current": dict(current),
            "desired": dict(desired),
            "todos": todos,
            "summary": {
                "actualizar": n_actualizar,
                "sin_cambios": n_sin_cambios,
                "total": len(todos),
            },
        }

    def _build_preview_response(
        self,
        plc_name: str,
        current: dict[str, int],
        desired: dict[str, int],
        ops: list[dict[str, Any]],
        nmax_block: dict[str, Any],
        warnings: list[str],
    ) -> dict[str, Any]:
        """Empaqueta la respuesta de ``preview_disp`` con shape nueva + legacy.

        Mantiene AMBAS shapes en la misma respuesta:
          - **Nueva** (``ops``, ``current``, ``desired``, ``summary.n_max_updates``):
            contrato limpio del use case. Consumidores nuevos (tests,
            scripts, MCP) usan estos campos.
          - **Legacy** (``agregados``, ``eliminados``, ``renombrados``,
            ``todos``, ``nmax``, ``summary.{agregados,renombrados,
            eliminados,sin_cambios,total}``): la SPA de alimentacion
            (Dispositivos.js) lee esta shape. En esta release los
            contadores de devices están a 0 (no aplica a N_MAX); se
            rellenarán cuando crezca el use case con device renames.

        Ambos coexisten sin colisión: los campos nuevos viven en
        ``ops`` / ``summary.n_max_updates`` y los legacy en
        ``agregados`` / ``nmax`` / ``summary.agregados``. El ``summary``
        raíz es un MERGE de ambos para que ambas partes lo lean del
        mismo sitio.
        """
        n_sin_cambios = nmax_block["summary"]["sin_cambios"]
        return {
            # --- Campos nuevos ---
            "plc_name": plc_name,
            "success": True,
            "preview": True,
            "has_changes": bool(ops),
            "current": current,
            "desired": desired,
            "ops": ops,

            # --- Campos legacy (SPA compatibility) ---
            "agregados": [],
            "eliminados": [],
            "renombrados": [],
            "todos": [],
            "nmax": nmax_block,

            # --- Summary mergeado (nuevo + legacy) ---
            "summary": {
                # Nuevos
                "n_max_updates": len(ops),
                "total_ops": len(ops),
                "has_changes": bool(ops),
                # Legacy
                "agregados": 0,
                "renombrados": 0,
                "eliminados": 0,
                "sin_cambios": n_sin_cambios,
                "total": nmax_block["summary"]["total"],
            },

            "warnings": warnings,
        }

    def _check_app_state(self) -> list[str]:
        """Devuelve warnings si ``AppState.dimensiones`` está vacío.

        Política: si las 6 N_MAX del catálogo están a 0, consideramos que
        el operario aún no cargó el Excel. NO abortamos: devolvemos un
        warning accionable y dejamos que el caller decida qué hacer.
        """
        d = self._state.dimensiones
        nmax_names = self._config.list_nmax_active()
        all_zero = all(int(d.get(n) or 0) == 0 for n in nmax_names)
        if all_zero and not self._state.all_devices():
            return [
                "AppState está vacío. Cargue primero el Excel con "
                "POST /api/v1/excel/upload."
            ]
        return []

    def _build_nmax_desired(self) -> dict[str, int]:
        """Lee las N_MAX deseadas de ``AppState.dimensiones``.

        Itera ``ConfigManager.list_nmax_active()`` (data-driven) y, para
        cada nombre, lee el valor del wrapper. Los que no estén en el
        Excel vienen a 0 (estado recién inicializado).
        """
        d = self._state.dimensiones
        desired: dict[str, int] = {}
        for nmax_name in self._config.list_nmax_active():
            v = d.get(nmax_name)
            if v is None:
                v = 0
            desired[nmax_name] = int(v)
        return desired

    async def _read_nmax_current(
        self, plc_name: str
    ) -> tuple[dict[str, int], list[str]]:
        """Lee el estado actual de N_MAX desde TIA Portal.

        Estrategia (offline-first): export bulk + parse selectivo de un
        único XML. NO se exportan las 6 tablas de dispositivos.

        Returns:
            Tupla ``(current, warnings)``. ``current`` es
            ``{nombre: valor_int}`` desde TIA o ``{}`` si el export
            falló o el XML no existe. ``warnings`` es la lista de
            warnings (vacía en el caso feliz).
        """
        nmax_folder = self._config.get_tia_folder_nmax()
        config_table = self._config.get_global_config_table_name()
        warnings: list[str] = []

        temp_dir = Path(tempfile.mkdtemp(prefix=self._TEMP_PREFIX))
        _logger.debug(f"[{plc_name}] Tempdir para export N_MAX: {temp_dir}")
        try:
            try:
                await self._gateway.export_plc_tags_xml(
                    plc_name=plc_name,
                    target_dir=str(temp_dir),
                )
            except Exception as exc:  # noqa: BLE001 (política: no abortar)
                _logger.error(
                    f"[{plc_name}] export_plc_tags_xml FAIL: {exc}"
                )
                warnings.append(
                    f"Export bulk del PLC falló ({exc}). "
                    "preview_disp / apply_disp devolverán 0 ops."
                )
                return {}, warnings

            xml_path = temp_dir / nmax_folder / f"{config_table}.xml"
            if not xml_path.is_file():
                _logger.warning(
                    f"[{plc_name}] XML N_MAX no encontrado: {xml_path}"
                )
                warnings.append(
                    f"XML de N_MAX no encontrado en el árbol exportado "
                    f"({nmax_folder}/{config_table}.xml)."
                )
                return {}, warnings

            try:
                current = SimaticMLTagParser.parse_user_constants(xml_path)
                _logger.info(
                    f"[{plc_name}] N_MAX parseadas ({len(current)}): "
                    f"{current}"
                )
                return current, warnings
            except Exception as exc:  # noqa: BLE001
                _logger.error(
                    f"[{plc_name}] parse_user_constants FAIL: {exc}"
                )
                warnings.append(
                    f"Falló el parseo de {xml_path.name} ({exc})."
                )
                return {}, warnings
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            _logger.debug(f"[{plc_name}] Tempdir limpiado.")

    def _compute_nmax_ops(
        self,
        plc_name: str,
        current: dict[str, int],
        desired: dict[str, int],
    ) -> list[dict[str, Any]]:
        """Calcula el diff N_MAX delegando en el motor puro."""
        config_table = self._config.get_global_config_table_name()
        return CalculateConstantsDiffUseCase.calculate_nmax_diff(
            plc_name=plc_name,
            config_table_name=config_table,
            current_state=current,
            desired_state=desired,
        )

    def _empty_preview(
        self, plc_name: str, warnings: list[str]
    ) -> dict[str, Any]:
        """Shape de preview cuando AppState está vacío (merge nuevo + legacy)."""
        nmax_block = self._build_nmax_block({}, {})
        return {
            "plc_name": plc_name,
            "success": True,
            "preview": True,
            "has_changes": False,
            "current": {},
            "desired": {},
            "ops": [],
            "agregados": [],
            "eliminados": [],
            "renombrados": [],
            "todos": [],
            "nmax": nmax_block,
            "summary": {
                "n_max_updates": 0,
                "total_ops": 0,
                "has_changes": False,
                "agregados": 0,
                "renombrados": 0,
                "eliminados": 0,
                "sin_cambios": nmax_block["summary"]["sin_cambios"],
                "total": nmax_block["summary"]["total"],
            },
            "warnings": warnings,
        }


__all__ = ["SyncDispAlimentacionUseCase"]
