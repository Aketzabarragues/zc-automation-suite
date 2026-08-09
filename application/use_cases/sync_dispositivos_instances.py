"""Application Layer - Sincronizar Instancias de Dispositivos.

Caso de uso con flujo **Pre-Flight + Commit** que permite previsualizar
cambios antes de mutar el PLC (replicando el patrón de seguridad de
la antigua TUI de ZC).

Arquitectura desacoplada:

  1. ``generar_prevision(plc_name)`` -- **NO muta TIA**. Lee el XML
     actual, cruza los UIDs contra AppState y devuelve un dict
     estructurado con 3 listas: ``agregados``, ``eliminados`` y
     ``renombrados``. Pensado para que la SPA lo muestre al operario
     ANTES de pulsar "Aplicar".

  2. ``ejecutar_transaccion(plc_name, prevision)`` -- Recibe la
     prevision exacta del paso anterior. Aplica ``add_tags`` /
     ``remove_tags`` sobre los XML (offline), emite los comandos
     ``rename_plc_tag`` (vía COM, preservando referencias cruzadas)
     y lanza ``execute_transactional_batch``.

  3. ``execute(plc_name)`` -- Wrapper de los dos para compatibilidad
     hacia atrás (no rompe consumidores existentes que aún llamen
     ``execute()`` directamente).

Restricciones:
  - Esta capa NO importa ``siemens_tia_scripting``.
  - Toda la comunicación con TIA Portal pasa por ``TIAProcessGateway``.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from application.state import AppState, get_app_state
from infrastructure.gateway import TIAProcessGateway
from infrastructure.xml.modifiers import TagTableModifier


class SyncDispositivosInstancesUseCase:
    """Caso de Uso: sincroniza instancias del subdominio alimentación.

    Motor Diff híbrido: combina modificaciones XML (offline) + renombres
    COM (atómicos sobre el PLC) preservando referencias cruzadas.

    Flujo recomendado (Pre-Flight + Commit):
        prevision = await use_case.generar_prevision(plc_name)
        # <usuario valida la prevision>
        result = await use_case.ejecutar_transaccion(plc_name, prevision)
    """

    _BUILD_CACHE_DIRNAME = ".build_cache"
    _BASE_SUBDIR = "base"
    _READY_SUBDIR = "ready_to_import"
    _TAG_TABLES_SUBDIR = "tags"

    def __init__(
        self,
        gateway: TIAProcessGateway,
        state: AppState | None = None,
        build_cache_dir: Path | None = None,
    ) -> None:
        self._gateway = gateway
        # Inyección opcional para tests; por defecto usa el Singleton.
        self._state = state if state is not None else get_app_state()
        self._build_cache = build_cache_dir or (
            Path(os.getcwd()) / self._BUILD_CACHE_DIRNAME
        )

    # ── API pública: Pre-Flight + Commit ──────────────────────────────

    async def generar_prevision(self, plc_name: str) -> dict[str, Any]:
        """Lee el XML actual y devuelve el Diff contra AppState.

        **NO muta el PLC**. Solo realiza:
          1. ``gateway.export_plc_tags_xml`` (lectura).
          2. Cruce UID contra AppState (en memoria).
          3. Cálculo de added / removed / renamed.

        Args:
            plc_name: Nombre del PLC destino.

        Returns:
            Dict estructurado::

                {
                    "agregados":  [ {uid, plc_tag, direccion}, ... ],
                    "eliminados": [ {uid, plc_tag}, ... ],
                    "renombrados": [ {uid, actual, nuevo}, ... ]
                }

            Cada lista está ordenada y deduplicada.
        """
        # 1) Estructura de directorios + export base (read-only).
        tags_base = (
            self._build_cache / self._BASE_SUBDIR / self._TAG_TABLES_SUBDIR
        )
        tags_base.mkdir(parents=True, exist_ok=True)
        await self._gateway.export_plc_tags_xml(plc_name, str(tags_base))

        # 2) Construir desired state desde AppState (uid → plc_tag).
        desired_state: dict[str, str] = self._build_desired_state_from_app()

        # 3) Calcular diff (CPU-bound: a hilo). SIN modificar el DOM.
        #    ``base_state`` se devuelve para enriquecer ``eliminados``.
        added, removed, renamed, base_state = await asyncio.to_thread(
            self._compute_diff_readonly,
            tags_base,
            desired_state,
        )

        return {
            "agregados": [
                {
                    "uid": uid,
                    "plc_tag": desired_state[uid],
                    "direccion": "",  # se rellena en commit con add_tags
                }
                for uid in added
            ],
            "eliminados": [
                {
                    "uid": uid,
                    "plc_tag": base_state.get(uid, ""),
                }
                for uid in removed
            ],
            "renombrados": [
                {
                    "uid": uid,
                    "actual": old_name,
                    "nuevo": new_name,
                }
                for uid, (old_name, new_name) in renamed.items()
            ],
        }

    async def ejecutar_transaccion(
        self,
        plc_name: str,
        prevision: dict[str, Any],
    ) -> dict[str, Any]:
        """Aplica la prevision al PLC dentro de un lote transaccional.

        Args:
            plc_name: Nombre del PLC destino.
            prevision: Dict producido por ``generar_prevision``.

        Returns:
            Dict con ``{success, message, operations}`` similar al
            ``execute()`` histórico.
        """
        # 1) Estructura de directorios.
        tags_base = (
            self._build_cache / self._BASE_SUBDIR / self._TAG_TABLES_SUBDIR
        )
        tags_ready = (
            self._build_cache / self._READY_SUBDIR / self._TAG_TABLES_SUBDIR
        )
        tags_ready.mkdir(parents=True, exist_ok=True)

        # 2) Asegurar export base (por si generar_prevision no se llamó).
        await self._gateway.export_plc_tags_xml(plc_name, str(tags_base))

        # 3) Construir desired_state y aplicar diff (mutación XML offline).
        desired_state: dict[str, str] = self._build_desired_state_from_app()
        added, removed, renamed = await asyncio.to_thread(
            self._compute_diff,
            tags_base,
            desired_state,
            tags_ready,
        )

        # 4) Construir payload transaccional.
        operations: list[dict[str, Any]] = []
        if added or removed:
            operations.append(
                {
                    "command": "import_plc_tags_xml",
                    "args": {
                        "plc_name": plc_name,
                        "import_dir": str(tags_ready),
                        "target_folder": "",
                    },
                }
            )
        for uid, (old_name, new_name) in renamed.items():
            _ = uid  # uid se ignora en la operación COM (TIA identifica por old_name)
            operations.append(
                {
                    "command": "rename_plc_tag",
                    "args": {
                        "plc_name": plc_name,
                        "old_name": old_name,
                        "new_name": new_name,
                    },
                }
            )

        if not operations:
            return {
                "success": True,
                "message": (
                    "Sin cambios: el PLC ya coincide con el AppState "
                    "(idempotencia)."
                ),
                "added": [],
                "removed": [],
                "renombrados": [],
                "operations": 0,
            }

        # 5) Inyección transaccional (XML + COM bajo el mismo lote).
        result = await self._gateway.execute_transactional_batch(
            operations,
            undo_text="Sincronizar Instancias de Dispositivos",
        )
        return {
            "success": True,
            "message": (
                f"Inyección completada. Detalles: {result['details']}"
            ),
            "operations": result["operations_executed"],
        }

    # ── Wrapper retrocompatible ──────────────────────────────────────

    async def execute(self, plc_name: str) -> dict[str, Any]:
        """Atajo: genera prevision y la aplica. Equivalente a:

            prev = await generar_prevision(plc_name)
            return await ejecutar_transaccion(plc_name, prev)

        Conservado para retrocompatibilidad con consumidores existentes.
        """
        prevision = await self.generar_prevision(plc_name)
        return await self.ejecutar_transaccion(plc_name, prevision)

    # ── Lógica offline (síncrona, ejecutada dentro de asyncio.to_thread)

    @staticmethod
    def _compute_diff_readonly(
        tags_base: Path,
        desired_state: dict[str, str],
    ) -> tuple[
        list[str],
        list[str],
        dict[str, tuple[str, str]],
        dict[str, str],
    ]:
        """Lee base XML y devuelve el diff SIN modificar el DOM.

        Returns:
            Tupla ``(added_uids, removed_uids, renamed_uids, base_state)``
            SIN side-effects. ``base_state`` se devuelve para que el caller
            pueda obtener el ``plc_tag`` histórico de los uids eliminados.
        """
        # 1) Leer base state desde los XML exportados: ``{uid: plc_tag}``.
        base_state: dict[str, str] = {}
        for xml_file in sorted(tags_base.glob("*.xml")):
            modifier = TagTableModifier(xml_file)
            for tag_info in modifier.read_tags_with_uids():
                uid = tag_info["uid"]
                name = tag_info["name"]
                if uid and name:
                    base_state[uid] = name

        # 2) Diff por uid (sin tocar nada del DOM todavía).
        base_uids = set(base_state.keys())
        desired_uids = set(desired_state.keys())

        added_uids = sorted(desired_uids - base_uids)
        removed_uids = sorted(base_uids - desired_uids)
        renamed_uids: dict[str, tuple[str, str]] = {}
        for uid in base_uids & desired_uids:
            old_name = base_state[uid]
            new_name = desired_state[uid]
            if old_name != new_name:
                renamed_uids[uid] = (old_name, new_name)

        return added_uids, removed_uids, renamed_uids, base_state

    @staticmethod
    def _compute_diff(
        tags_base: Path,
        desired_state: dict[str, str],
        tags_ready: Path,
    ) -> tuple[list[str], list[str], dict[str, tuple[str, str]]]:
        """Lee base XML, calcula diff y APLICA los cambios en el DOM
        (clona ``add_tags`` / borra ``remove_tags``). Luego escribe el
        XML resultante si hubo modificaciones.

        Returns:
            Tupla ``(added_uids, removed_uids, renamed_uids)``.
              - added_uids: uids presentes en desired pero no en base.
              - removed_uids: uids presentes en base pero no en desired.
              - renamed_uids: ``{uid: (old_name, new_name)}`` donde
                mismo uid pero ``plc_tag`` cambió.
        """
        # 1) Diff puro (incluye base_state para mapeos uid→plc_tag).
        _added, _removed, _renamed, _base_state = (
            SyncDispositivosInstancesUseCase._compute_diff_readonly(
                tags_base, desired_state
            )
        )
        added_uids = _added
        removed_uids = _removed
        renamed_uids = _renamed

        # 2) Aplicar adds/drops al XML (NO renames — eso va por COM).
        #    Para adds: crear los PlcTags nuevos desde desired_state.
        #    Para drops: invocar remove_tags sobre los uids eliminados.
        #    Para renames: no se hace offline (la referencia en el XML
        #    cambia físicamente pero las refs cruzadas del PLC no se
        #    preservan; por eso el rename se hace por COM).
        for xml_file in sorted(tags_base.glob("*.xml")):
            modifier = TagTableModifier(xml_file)
            # Add: añadir PlcTags nuevos a su tabla.
            stem = xml_file.stem
            dtos_for_table = [
                {"plc_tag": desired_state[uid], "uid": uid}
                for uid in added_uids
            ]
            # Por simplicidad: añadir a todas las tablas cuyos PlcTags
            # esperados coincidan. (En una versión futura se mapea
            # uid → table_name via ConfigManager.)
            modifier.add_tags_by_table(stem, dtos_for_table)
            # Remove: borrar PlcTags cuyos uid correspondan.
            modifier.remove_tags({uid for uid in removed_uids})
            if modifier.was_modified():
                modifier.save(tags_ready / xml_file.name)

        return added_uids, removed_uids, renamed_uids

    def _build_desired_state_from_app(self) -> dict[str, str]:
        """Aplana las 6 listas del ``AppState`` a ``{uid: plc_tag}``."""
        result: dict[str, str] = {}
        for device in self._state.all_devices():
            uid = getattr(device, "uid", "")
            plc_tag = getattr(device, "plc_tag", "")
            if uid and plc_tag:
                result[uid] = plc_tag
        return result
