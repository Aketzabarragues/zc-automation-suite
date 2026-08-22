"""Application Layer - Sincronizar Instancias de Dispositivos.

FIX CRITICO: el matching entre PlcUserConstant del PLC y dispositivos del
AppState debe hacerse POR TABLA, no globalmente.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from application.state import AppState, get_app_state
from infrastructure.config_manager import ConfigManager
from infrastructure.gateway import TIAProcessGateway
from infrastructure.xml.modifiers import TagTableModifier


_logger = logging.getLogger(f"{__name__}.SyncDispositivosInstancesUseCase")


class SyncDispositivosInstancesUseCase:
    """Caso de Uso: sincroniza instancias del subdominio alimentacion."""

    _BUILD_CACHE_DIRNAME = ".build_cache"
    _BASE_SUBDIR = "base"
    _READY_SUBDIR = "ready_to_import"
    _TAG_TABLES_SUBDIR = "tags"

    _HW_TYPE_ATTRS: dict[str, str] = {
        "ed":    "dispositivos_ed",
        "ea":    "dispositivos_ea",
        "sa":    "dispositivos_sa",
        "v":     "dispositivos_v",
        "m":     "dispositivos_m",
        "m_vf":  "dispositivos_m_vf",
    }

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

    async def generar_prevision(self, plc_name: str) -> dict[str, Any]:
        tags_base = (
            self._build_cache / self._BASE_SUBDIR / self._TAG_TABLES_SUBDIR
        )
        tags_base.mkdir(parents=True, exist_ok=True)
        await self._gateway.export_plc_tags_xml(plc_name, str(tags_base))
        desired_state_per_table = self._build_desired_state_from_app()
        added_p, removed_p, renamed, base_state_per_table = (
            await asyncio.to_thread(
                self._compute_diff_readonly, tags_base, desired_state_per_table
            )
        )

        # ── N_MAX: lee la tabla de configuración global ──────────────
        # Se calcula el diff entre las PlcUserConstant N_MAX del TIA
        # y los contadores de ``AppState.dimensiones``. Resultado en
        # el mismo formato unificado que los dispositivos: 1 fila
        # por N_MAX con su status.
        nmax_block = await asyncio.to_thread(
            self._extract_nmax_diff, tags_base
        )

        # ── Listas legacy (back-compat con la SPA actual) ──────────────
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

        # ── Lista UNIFICADA para la vista de pestañas ─────────────────
        # Cada item representa UN dispositivo de la PlcTagTable, con:
        #   - table:     nombre de la tabla (``2000_Disp_ED``…)
        #   - type:      tipo lógico derivado (``ed``, ``ea``, ``v``…)
        #   - uid:       value_str (== str(numero)) del PlcUserConstant
        #   - numero:    int(numero) para ordenación numérica
        #   - actual:    plc_tag actual en TIA (None si no existe)
        #   - nuevo:     plc_tag deseado del AppState (None si se elimina)
        #   - status:    "agregar" | "renombrar" | "eliminar" | "sin_cambios"
        #
        # El orden es por ``numero`` ascendente dentro de cada tabla.
        def _type_from_table(table_key: str) -> str:
            """Deriva el tipo lógico del nombre de la tabla.

            ``2000_Disp_ED`` → ``"ed"``, ``2000_Disp_M_VF`` → ``"m_vf"``.
            """
            stem = table_key.split("_Disp_", 1)[-1]  # "ED", "M_VF", ...
            return stem.lower()

        todos: list[dict[str, Any]] = []

        for table_key, base in base_state_per_table.items():
            type_key = _type_from_table(table_key)
            # `renamed` viene como ``{f"{table_key}:{uid}": (old, new)}``.
            # Lo invertimos por tabla para lookup O(1) por uid.
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

        # Orden estable: por type, luego numero ascendente.
        todos.sort(
            key=lambda r: (
                r["type"],
                r["numero"] if isinstance(r["numero"], int) else 0,
            )
        )

        return {
            # Legacy (back-compat con la SPA actual).
            "agregados":   agregados,
            "eliminados":  eliminados,
            "renombrados": renombrados,
            # Nueva lista unificada (1 fila por dispositivo, con status).
            "todos":       todos,
            # N_MAX: contadores PlcUserConstant de la tabla global.
            "nmax":        nmax_block,
            # Contadores globales (útiles para la pestaña "Resumen").
            "summary": {
                "agregados":    len(agregados),
                "eliminados":   len(eliminados),
                "renombrados":  len(renombrados),
                "sin_cambios":  sum(
                    1 for r in todos if r["status"] == "sin_cambios"
                ),
                "total":        len(todos),
            },
        }

    async def ejecutar_transaccion(
        self, plc_name: str, prevision: dict[str, Any]
    ) -> dict[str, Any]:
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
        operations: list[dict[str, Any]] = []
        if added or removed:
            operations.append({
                "command": "import_plc_tags_xml",
                "args": {
                    "plc_name": plc_name,
                    "import_dir": str(tags_ready),
                    "target_folder": "",
                },
            })
        for uid_with_table, (old, new) in renamed.items():
            _ = uid_with_table
            operations.append({
                "command": "rename_plc_tag",
                "args": {
                    "plc_name": plc_name,
                    "old_name": old,
                    "new_name": new,
                },
            })
        if not operations:
            return {
                "success": True,
                "message": "Sin cambios: el PLC ya coincide con el AppState.",
                "added": [], "removed": [], "renombrados": [], "operations": 0,
            }
        result = await self._gateway.execute_transactional_batch(
            operations, undo_text="Sincronizar Instancias de Dispositivos"
        )
        return {
            "success": True,
            "message": f"Inyeccion completada. Detalles: {result['details']}",
            "operations": result["operations_executed"],
        }

    async def execute(self, plc_name: str) -> dict[str, Any]:
        prevision = await self.generar_prevision(plc_name)
        return await self.ejecutar_transaccion(plc_name, prevision)

    # ──────────────────────────────────────────────────────────────────
    # N_MAX: diff de PlcUserConstant de la tabla de configuración global
    # ──────────────────────────────────────────────────────────────────

    def _extract_nmax_diff(self, tags_base: Path) -> dict[str, Any]:
        """Calcula el diff de N_MAX entre el TIA (export bulk) y ``AppState.dimensiones``.

        Las N_MAX son PlcUserConstant de la tabla
        ``000_Config_Dispositivos`` que **siempre existen** en TIA
        (son las 6 dimensiones: ED, EA, SA, V, M, M_VF). No se crean
        ni se eliminan: solo se **modifica su valor**. Por tanto, los
        únicos estados posibles son:

          - ``actualizar``  : el valor cambia X → Y.
          - ``sin_cambios`` : el valor coincide.

        Estrategia:
          1. Lee el XML de la tabla N_MAX (ruta canónica:
             ``{nmax_folder}/{nmax_table}.xml``) del árbol bulk exportado.
          2. ``current``: ``{nombre: valor}`` (TIA actual).
          3. ``desired``: ``{name: value}`` (AppState.dimensiones,
             siempre con las 6 entradas canónicas; las que no estén
             en el Excel vienen a 0).
          4. ``todos``: lista unificada con ``status`` ∈
             ``{actualizar, sin_cambios}``.

        Returns:
            ``dict`` con ``current``, ``desired``, ``todos`` y
            ``summary``. Si el XML no existe, retorna bloques vacíos
            (no aborta la preflight).

        Side effects: ninguno. Lectura offline de XML ya en disco.
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

        # El parser ya devuelve `{nombre: valor}` (key estable =
        # nombre, evita colisiones por valor repetido entre N_MAX).

        # 2. Estado deseado desde AppState.dimensiones.
        d = self._state.dimensiones
        desired: dict[str, int] = {
            "N_MAX_DISP_ED":   int(getattr(d, "num_disp_ed",   0) or 0),
            "N_MAX_DISP_EA":   int(getattr(d, "num_disp_ea",   0) or 0),
            "N_MAX_DISP_SA":   int(getattr(d, "num_disp_sa",   0) or 0),
            "N_MAX_DISP_V":    int(getattr(d, "num_disp_v",    0) or 0),
            "N_MAX_DISP_M":    int(getattr(d, "num_disp_m",    0) or 0),
            "N_MAX_DISP_M_VF": int(getattr(d, "num_disp_m_vf", 0) or 0),
        }

        # 3. Diff unificado: las N_MAX siempre existen en ambos lados.
        # Si por algún motivo faltara alguna (TIA sin SA), el valor
        # actual sería None y la fila seguiría apareciendo con
        # ``status="sin_cambios"`` para que el operario la vea.
        # El orden de iteración de ``desired.keys()`` es el orden
        # de inserción del dict (ED, EA, SA, V, M, M_VF) — Python
        # 3.7+ lo garantiza, así que NO hace falta re-ordenar.
        todos: list[dict[str, Any]] = []
        for name in desired.keys():
            cur_val = current.get(name)
            des_val = desired[name]
            if cur_val is not None and cur_val == des_val:
                status = "sin_cambios"
            else:
                status = "actualizar"
            todos.append({
                "name":   name,
                "actual": cur_val,
                "nuevo":  des_val,
                "status": status,
            })

        return {
            "current": current,
            "desired": desired,
            "todos":   todos,
            "summary": {
                "actualizar":   sum(1 for r in todos if r["status"] == "actualizar"),
                "sin_cambios":  sum(1 for r in todos if r["status"] == "sin_cambios"),
                "total":        len(todos),
            },
        }

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
            added_per_table, removed_per_table, renamed_per_table,
            base_state_per_table,
        )

    @staticmethod
    def _compute_diff(
        tags_base: Path,
        desired_state_per_table: dict[str, dict[str, str]],
        tags_ready: Path,
    ) -> tuple[list[str], list[str], dict[str, tuple[str, str]]]:
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
        result: dict[str, dict[str, str]] = {}
        for hw_type, attr_name in self._HW_TYPE_ATTRS.items():
            tag_table = self._config.get_tag_table_name(hw_type)
            if tag_table is None:
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
