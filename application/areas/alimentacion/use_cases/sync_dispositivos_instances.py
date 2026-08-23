"""Application Layer - Sincronizar Instancias de Dispositivos (N_MAX + devices).

Caso de uso: realiza el sync completo entre el Excel corporativo (v\u00eda
``AppState``) y el PLC de TIA Portal en UNA sola transacci\u00f3n COM \u00fanica.

El flujo de ``generar_prevision`` calcula:

  1. **N_MAX** (dimensiones): diff por nombre entre
     ``000_Config_Dispositivos.xml`` (TIA) y ``AppState.dimensiones``
     (Excel). Emite operaciones ``update_user_constant_value`` (online).
  2. **Devices** (instancias): diff por UID (valor) entre las 6 tablas
     ``2000_Disp_*`` (TIA) y ``AppState.dispositivos_*`` (Excel).
     Emite operaciones ``update_user_constant_name`` (online rename)
     y, si hay add/remove, ``import_plc_tags_xml`` (offline XML).

El flujo de ``ejecutar_transaccion`` empaqueta TODAS las operaciones
(online + offline) en una sola llamada a
``gateway.execute_transactional_batch``, que el worker ejecuta bajo
``start_transaction`` / ``end_transaction`` con rollback at\u00f3mico.

Shape del preview (back-compat con la SPA):
  - ``agregados`` / ``eliminados`` / ``renombrados`` (listas de devices).
  - ``todos`` (lista unificada con ``{table, type, uid, numero, actual,
    nuevo, status}``).
  - ``nmax`` (``{current, desired, todos, summary}`` para la vista N_MAX).
  - ``summary`` (contadores globales).

Restricci\u00f3n:
  - NO importa ``siemens_tia_scripting``.
  - Los nombres de tabla PLC se resuelven v\u00eda ``ConfigManager``.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from application.areas.alimentacion.use_cases.diff_constants import (
    CalculateConstantsDiffUseCase,
)
from application.state import AppState, get_app_state
from infrastructure.config_manager import ConfigManager
from infrastructure.gateway import TIAProcessGateway
from infrastructure.xml.modifiers import TagTableModifier


_logger = logging.getLogger(
    f"{__name__}.SyncDispositivosInstancesUseCase"
)


class SyncDispositivosInstancesUseCase:
    """Caso de Uso: sincroniza N_MAX + instancias del subdominio alimentacion.

    El mapeo ``hw_type \u2194 atributo AppState`` se obtiene del
    ``ConfigManager`` (v\u00eda ``get_app_state_attr_for(hw)``). Los 6
    legacy (``ed/ea/sa/v/m/m_vf``) siguen funcionando id\u00e9ntico.

    Atributos de la release actual (N_MAX + devices):
      - ``generar_prevision(plc_name)`` \u2192 diff completo (N_MAX + devices).
      - ``ejecutar_transaccion(plc_name, prevision)`` \u2192 transacci\u00f3n \u00fanica.
      - ``execute(plc_name)`` \u2192 helper que encadena ambos.
    """

    _BUILD_CACHE_DIRNAME = ".build_cache"
    _BASE_SUBDIR = "base"
    _READY_SUBDIR = "ready_to_import"
    _TAG_TABLES_SUBDIR = "tags"

    def __init__(
        self,
        gateway: TIAProcessGateway,
        config_manager: ConfigManager,
        state: AppState | None = None,
        build_cache_dir: Path | None = None,
    ) -> None:
        self._gateway = gateway
        self._config = config_manager
        self._state = state if state is not None else get_app_state()
        self._build_cache = build_cache_dir or (
            Path(os.getcwd()) / self._BUILD_CACHE_DIRNAME
        )

    # ──────────────────────────────────────────────────────────────────
    # API pública
    # ──────────────────────────────────────────────────────────────────

    async def generar_prevision(self, plc_name: str) -> dict[str, Any]:
        """Calcula el diff completo: N_MAX + devices.

        Steps:
          1. Export bulk del PLC al directorio ``.build_cache/base/tags/``.
          2. Calcula el diff de devices (instancias) con
             ``_compute_diff_readonly`` sobre los 6 XMLs
             ``2000_Disp_*``.
          3. Calcula el diff de N_MAX con ``_extract_nmax_diff`` sobre
             ``000_Config_Dispositivos.xml``.
          4. Devuelve el shape legacy esperado por la SPA:
             ``{agregados, eliminados, renombrados, todos, nmax, summary}``.
        """
        tags_base = (
            self._build_cache / self._BASE_SUBDIR / self._TAG_TABLES_SUBDIR
        )
        tags_base.mkdir(parents=True, exist_ok=True)
        await self._gateway.export_plc_tags_xml(plc_name, str(tags_base))

        desired_state_per_table = self._build_desired_state_from_app()
        added_p, removed_p, renamed, base_state_per_table = (
            await asyncio.to_thread(
                self._compute_diff_readonly,
                tags_base,
                desired_state_per_table,
            )
        )

        # N_MAX: lee la tabla de configuraci\u00f3n global.
        nmax_block = await asyncio.to_thread(
            self._extract_nmax_diff, tags_base
        )

        # Listas legacy (back-compat con la SPA actual).
        agregados: list[dict[str, Any]] = [
            {"uid": uid, "table": tk, "plc_tag": td.get(uid, "")}
            for tk, td in desired_state_per_table.items()
            for uid in added_p.get(tk, []) if uid in td
        ]
        eliminados: list[dict[str, Any]] = [
            {"uid": uid, "table": tk, "plc_tag": tb.get(uid, "")}
            for tk, tb in base_state_per_table.items()
            for uid in removed_p.get(tk, []) if uid in tb
        ]
        renombrados: list[dict[str, Any]] = [
            {
                "uid": uid.split(":", 1)[1] if ":" in uid else uid,
                "table": uid.split(":", 1)[0] if ":" in uid else "",
                "actual": old,
                "nuevo": new,
            }
            for uid, (old, new) in renamed.items()
        ]

        # Lista UNIFICADA para la vista de pesta\u00f1as.
        def _type_from_table(table_key: str) -> str:
            """``2000_Disp_ED`` \u2192 ``"ed"``, ``2000_Disp_M_VF`` \u2192 ``"m_vf"``."""
            stem = table_key.split("_Disp_", 1)[-1]
            return stem.lower()

        todos: list[dict[str, Any]] = []
        for table_key, base in base_state_per_table.items():
            type_key = _type_from_table(table_key)
            renamed_for_table: dict[str, str] = {}
            for uid, (_old, new) in renamed.items():
                if uid.startswith(f"{table_key}:"):
                    renamed_for_table[uid.split(":", 1)[1]] = new

            removed_uids = set(removed_p.get(table_key, []))

            for uid_str, plc_tag in base.items():
                try:
                    numero = int(uid_str)
                except (TypeError, ValueError):
                    numero = 0
                if uid_str in renamed_for_table:
                    todos.append({
                        "table": table_key,
                        "type": type_key,
                        "uid": uid_str,
                        "numero": numero,
                        "actual": plc_tag,
                        "nuevo": renamed_for_table[uid_str],
                        "status": "renombrar",
                    })
                elif uid_str in removed_uids:
                    todos.append({
                        "table": table_key,
                        "type": type_key,
                        "uid": uid_str,
                        "numero": numero,
                        "actual": plc_tag,
                        "nuevo": None,
                        "status": "eliminar",
                    })
                else:
                    todos.append({
                        "table": table_key,
                        "type": type_key,
                        "uid": uid_str,
                        "numero": numero,
                        "actual": plc_tag,
                        "nuevo": plc_tag,
                        "status": "sin_cambios",
                    })

        for table_key, desired in desired_state_per_table.items():
            type_key = _type_from_table(table_key)
            for uid_str in added_p.get(table_key, []):
                try:
                    numero = int(uid_str)
                except (TypeError, ValueError):
                    numero = 0
                todos.append({
                    "table": table_key,
                    "type": type_key,
                    "uid": uid_str,
                    "numero": numero,
                    "actual": None,
                    "nuevo": desired.get(uid_str, ""),
                    "status": "agregar",
                })

        todos.sort(
            key=lambda r: (
                r["type"],
                r["numero"] if isinstance(r["numero"], int) else 0,
            )
        )

        return {
            "agregados": agregados,
            "eliminados": eliminados,
            "renombrados": renombrados,
            "todos": todos,
            "nmax": nmax_block,
            "summary": {
                "agregados": len(agregados),
                "eliminados": len(eliminados),
                "renombrados": len(renombrados),
                "sin_cambios": sum(
                    1 for r in todos if r["status"] == "sin_cambios"
                ),
                "total": len(todos),
            },
        }

    async def ejecutar_transaccion(
        self, plc_name: str, prevision: dict[str, Any]
    ) -> dict[str, Any]:
        """Ejecuta el diff completo (N_MAX + devices) en UNA transacci\u00f3n \u00fanica.

        Empaqueta TODAS las operaciones online (N_MAX + device renames)
        y offline (device add/remove via XML) en una sola lista que
        ``gateway.execute_transactional_batch`` ejecuta bajo una
        \u00fanica ``start_transaction`` / ``end_transaction`` con rollback
        at\u00f3mico.

        Args:
            plc_name: Nombre del PLC destino.
            prevision: Resultado de ``generar_prevision``. NO se usa
                directamente (se recalcula desde el AppState para
                evitar race conditions); se conserva en la firma por
                back-compat con la SPA.
        """
        tags_base = (
            self._build_cache / self._BASE_SUBDIR / self._TAG_TABLES_SUBDIR
        )
        tags_ready = (
            self._build_cache / self._READY_SUBDIR / self._TAG_TABLES_SUBDIR
        )
        tags_ready.mkdir(parents=True, exist_ok=True)
        await self._gateway.export_plc_tags_xml(plc_name, str(tags_base))

        desired_state_per_table = self._build_desired_state_from_app()
        added, removed, renamed = await asyncio.to_thread(
            self._compute_diff, tags_base, desired_state_per_table, tags_ready
        )

        # ── Construir la lista de operaciones para la transacción única ──
        operations: list[dict[str, Any]] = []

        # =====================================================================
        # === RENOMBRADO de devices (PlcUserConstants)                    ===
        # ===                                                              ===
        # === Las variables del Excel (plc_tag) se persisten como         ===
        # === PlcUserConstants en las tag tables 2000_Disp_*. El rename   ===
        # === se hace con update_user_constant_name (no rename_plc_tag,  ===
        # === que opera sobre PlcTag y falla con "No se encontro        ===
        # === PlcTag con Name=..." en este caso).                          ===
        # ===                                                              ===
        # === add/remove (import_plc_tags_xml) sigue comentado porque     ===
        # === requiere modificar el XML offline, validar, e importar, lo  ===
        # === cual entramos en otra release.                               ===
        # =====================================================================
        for uid_with_table, (old, new) in renamed.items():
            # uid_with_table es "table_key:uid_str" (p.ej. "2000_Disp_ED:5").
            # Extraemos el table_key para usarlo como ``table_name``.
            table_key, _, _ = uid_with_table.partition(":")
            operations.append({
                "command": "update_user_constant_name",
                "args": {
                    "plc_name": plc_name,
                    "table_name": table_key,
                    "current_name": old,
                    "new_name": new,
                },
            })

        # ONLINE: update_user_constant_value (N_MAX). Siempre activo.
        nmax_ops = self._compute_nmax_ops_for_apply(plc_name, tags_base)
        operations.extend(nmax_ops)

        if not operations:
            return {
                "success": True,
                "message": "Sin cambios: el PLC ya coincide con el AppState.",
                "added": [], "removed": [], "renombrados": [],
                "operations": 0,
            }

        result = await self._gateway.execute_transactional_batch(
            operations,
            undo_text="Sincronizar N_MAX + Dispositivos",
        )
        return {
            "success": True,
            "message": f"Inyeccion completada. Detalles: {result['details']}",
            "operations": result["operations_executed"],
            "n_max_updates": len(nmax_ops),
        }

    async def execute(self, plc_name: str) -> dict[str, Any]:
        """Helper: generar previsi\u00f3n + ejecutar transacci\u00f3n en una llamada."""
        prevision = await self.generar_prevision(plc_name)
        return await self.ejecutar_transaccion(plc_name, prevision)

    # ──────────────────────────────────────────────────────────────────
    # N_MAX: diff y ops (NUEVO en esta release)
    # ──────────────────────────────────────────────────────────────────

    def _compute_nmax_ops_for_apply(
        self, plc_name: str, tags_base: Path
    ) -> list[dict[str, Any]]:
        """Calcula las ops ``update_user_constant_value`` para N_MAX.

        Reutiliza ``_extract_nmax_diff`` para leer TIA + AppState, y
        ``CalculateConstantsDiffUseCase.calculate_nmax_diff`` para
        emitir las ops. Se ejecuta en el hilo del caller (no
        necesita ``asyncio.to_thread`` porque no hay I/O).
        """
        nmax_block = self._extract_nmax_diff(tags_base)
        # Re-leer el estado actual desde el bloque (es idempotente).
        current = nmax_block["current"]
        desired = nmax_block["desired"]
        nmax_table = self._config.get_global_config_table_name()
        return CalculateConstantsDiffUseCase.calculate_nmax_diff(
            plc_name=plc_name,
            config_table_name=nmax_table,
            current_state=current,
            desired_state=desired,
        )

    def _extract_nmax_diff(self, tags_base: Path) -> dict[str, Any]:
        """Calcula el diff de N_MAX entre el TIA (export bulk) y ``AppState.dimensiones``.

        Las N_MAX son PlcUserConstant de la tabla
        ``000_Config_Dispositivos`` que **siempre existen** en TIA
        (son las 6 dimensiones: ED, EA, SA, V, M, M_VF). No se crean
        ni se eliminan: solo se **modifica su valor**. Por tanto, los
        \u00fanicos estados posibles son:

          - ``actualizar``  : el valor cambia X \u2192 Y.
          - ``sin_cambios`` : el valor coincide.
        """
        from infrastructure.xml.tag_table_parser import SimaticMLTagParser

        nmax_folder = self._config.get_tia_folder_nmax()
        nmax_table = self._config.get_global_config_table_name()
        xml_path = tags_base / nmax_folder / f"{nmax_table}.xml"

        # 1. Estado actual en TIA.
        current: dict[str, int] = {}
        if xml_path.is_file():
            try:
                current = SimaticMLTagParser.parse_user_constants(xml_path)
            except Exception as e:
                _logger.error(f"[N_MAX] Parse FAIL {xml_path}: {e}")
        else:
            _logger.warning(
                f"[N_MAX] XML esperado no encontrado: {xml_path}"
            )

        # 2. Estado deseado desde AppState.dimensiones (data-driven).
        d = self._state.dimensiones
        desired: dict[str, int] = {}
        for nmax_name in self._config.list_nmax_active():
            v = d.get(nmax_name)
            if v is None:
                v = 0
            desired[nmax_name] = int(v)

        # 3. Diff unificado: las N_MAX siempre existen en ambos lados.
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

        return {
            "current": current,
            "desired": desired,
            "todos": todos,
            "summary": {
                "actualizar": sum(
                    1 for r in todos if r["status"] == "actualizar"
                ),
                "sin_cambios": sum(
                    1 for r in todos if r["status"] == "sin_cambios"
                ),
                "total": len(todos),
            },
        }

    # ──────────────────────────────────────────────────────────────────
    # Diff de devices (helpers internos)
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_diff_readonly(
        tags_base: Path,
        desired_state_per_table: dict[str, dict[str, str]],
    ) -> tuple[
        dict[str, list[str]],
        dict[str, list[str]],
        dict[str, tuple[str, str]],
        dict[str, dict[str, str]],
    ]:
        """Calcula el diff de devices en modo read-only (no modifica XML)."""
        base_state_per_table: dict[str, dict[str, str]] = {}
        for table_key in desired_state_per_table.keys():
            xml_path = tags_base / f"{table_key}.xml"
            if not xml_path.is_file():
                matches = list(tags_base.glob(f"**/{table_key}.xml"))
                if matches:
                    xml_path = matches[0]
                else:
                    continue
            modifier = TagTableModifier(xml_path)
            table_constants: dict[str, str] = {}
            for value_str, plc_tag in (
                modifier.read_user_constants_with_uids().items()
            ):
                if value_str and plc_tag:
                    table_constants[value_str] = plc_tag
            if table_constants:
                base_state_per_table[table_key] = table_constants

        added_per_table: dict[str, list[str]] = {}
        removed_per_table: dict[str, list[str]] = {}
        renamed_per_table: dict[str, tuple[str, str]] = {}

        for table_key, desired in desired_state_per_table.items():
            base = base_state_per_table.get(table_key, {})
            base_values = set(base.keys())
            desired_values = set(desired.keys())
            added = sorted(desired_values - base_values)
            removed = sorted(base_values - desired_values)
            renamed: dict[str, tuple[str, str]] = {}
            for uid in base_values & desired_values:
                if base[uid] != desired[uid]:
                    renamed[f"{table_key}:{uid}"] = (base[uid], desired[uid])
            if added:
                added_per_table[table_key] = added
            if removed:
                removed_per_table[table_key] = removed
            renamed_per_table.update(renamed)

        return (
            added_per_table,
            removed_per_table,
            renamed_per_table,
            base_state_per_table,
        )

    @staticmethod
    def _compute_diff(
        tags_base: Path,
        desired_state_per_table: dict[str, dict[str, str]],
        tags_ready: Path,
    ) -> tuple[list[str], list[str], dict[str, tuple[str, str]]]:
        """Calcula el diff de devices y modifica los XMLs en ``tags_ready``.

        Devuelve la lista plana de a\u00f1adidos, eliminados y renombrados
        (los renombrados con prefijo ``table_key:uid``).
        """
        _added, _removed, _renamed, _ = (
            SyncDispositivosInstancesUseCase._compute_diff_readonly(
                tags_base, desired_state_per_table
            )
        )
        for table_key, desired in desired_state_per_table.items():
            xml_path = tags_base / f"{table_key}.xml"
            if not xml_path.is_file():
                matches = list(tags_base.glob(f"**/{table_key}.xml"))
                if matches:
                    xml_path = matches[0]
                else:
                    continue
            modifier = TagTableModifier(xml_path)
            stem = xml_path.stem
            table_added = _added.get(table_key, [])
            table_removed = _removed.get(table_key, [])
            dtos_for_table = [
                {"plc_tag": desired[uid], "uid": uid}
                for uid in table_added
            ]
            modifier.add_tags_by_table(stem, dtos_for_table)
            modifier.remove_tags(set(table_removed))
            if modifier.was_modified():
                modifier.save(tags_ready / xml_path.name)
        all_added = [uid for adds in _added.values() for uid in adds]
        all_removed = [uid for rems in _removed.values() for uid in rems]
        return all_added, all_removed, _renamed

    def _build_desired_state_from_app(self) -> dict[str, dict[str, str]]:
        """Construye ``{tag_table: {uid: plc_tag}}`` desde el ``AppState``.

        Itera ``ConfigManager.list_hw_types_active()`` (data-driven)
        y usa ``get_app_state_attr_for(hw)`` para acceder a la lista
        de dispositivos del estado.
        """
        result: dict[str, dict[str, str]] = {}
        for hw_type in self._config.list_hw_types_active():
            tag_table = self._config.get_tag_table_name(hw_type)
            if tag_table is None:
                continue
            attr_name = self._config.get_app_state_attr_for(hw_type)
            if attr_name is None:
                continue
            devices = getattr(self._state, attr_name, [])
            table_dict: dict[str, str] = {}
            for device in devices:
                numero = int(getattr(device, "numero", 0) or 0)
                plc_tag = str(getattr(device, "plc_tag", "") or "")
                if numero > 0 and plc_tag:
                    table_dict[str(numero)] = plc_tag
            if table_dict:
                result[tag_table] = table_dict
        return result


__all__ = ["SyncDispositivosInstancesUseCase"]
