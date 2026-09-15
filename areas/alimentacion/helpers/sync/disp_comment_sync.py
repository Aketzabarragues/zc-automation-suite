"""Helper IT para sincronizar comentarios por instancia de los 6 DBs de disp.

Pieza del flujo post-``apply_disp`` (N_MAX) + ``compile_plc``
(redimensionado): recibe el AppState con los dispositivos cargados
desde el Excel, y para cada DB de dispositivo (ED/EA/SA/V/M/M_VF)
escribe el comentario de cada instancia (``comentario_db``) en el
Source Document correspondiente (``.s7dcl``/``.s7res``) y reimporta
el bloque a TIA Portal.

Flujo sept-2026 (fix del SOBREESCRIBIR entre handlers):
  1. Export de los 6 DBs a ``exports/bloques/`` UNA VEZ.
  2. Copytree ``exports/bloques/`` -> ``modified/bloques/`` UNA VEZ.
  3. Batch: 6 invocaciones separadas a
     ``update_disp_comments_db_<hw>`` (1 dispatch por hw_type).
     Cada handler abre/cierra su propia tx TIA, evitando el
     rollback silencioso de TIA V21 al mezclar 6 imports en 1 sola
     tx.

Restricciones arquitectonicas (.clinerules):
  - NO importa ``siemens_tia_scripting``.
  - Toda interaccion con TIA Portal pasa por ``tia_client`` (Singleton
    core, inyectable como kwarg).
  - Cero rutas hardcodeadas: la carpeta destino, los nombres de los
    DBs y los nombres de los arrays se leen del ``ConfigManager``.
"""
from __future__ import annotations

import shutil
from functools import partial
from pathlib import Path
from typing import Any

from areas.alimentacion.data.data_DispSlotMap import disp_build_slot_maps


async def apply_disp_comments(
    plc_name: str,
    *,
    app_state: Any,
    config_manager: Any,
    build_cache_root: Path,
    tia_client: Any,
) -> dict[str, Any]:
    """Aplica los comentarios por instancia a los 6 DBs de dispositivos.

    Cada hw_type abre/cierra su propia tx TIA (un dispatch por hw).

    Args:
        plc_name: nombre del PLC destino.
        app_state: ``AppState`` con los dispositivos cargados del Excel.
        config_manager: ``ConfigManager`` del departamento activo.
        build_cache_root: raiz del ``BuildCache`` del area
            (``<cwd>/.build_cache`` por convencion).
        tia_client: cliente TIA (Singleton core o mock) usado para
            los dispatches ``export_block`` y ``update_disp_comments_db_<hw>``.

    Returns:
        ``dict`` con shape::

            {
              "plc_name":            str,
              "success":             True,
              "applied":             True,
              "operations_executed": int,
              "summary": {
                "disp_dbs_updated":  int,
                "total_ops":         int,
              },
              "details":  list[dict],   # del worker
              "warnings": list[str],
            }
    """
    # ── 1. Validar AppState ──
    if not app_state.all_devices():
        warning = (
            "AppState esta vacio. Cargue primero el Excel con "
            "POST /api/v1/excel/upload."
        )
        return {
            "plc_name": plc_name,
            "success": True,
            "applied": True,
            "operations_executed": 0,
            "summary": {"disp_dbs_updated": 0, "total_ops": 0},
            "details": [],
            "warnings": [warning],
        }

    # ── 2. Construir slot_maps ──
    from areas.alimentacion.helpers.build_cache import build_cache

    slot_maps_data = disp_build_slot_maps(app_state, config_manager)
    slot_maps = slot_maps_data.slot_maps
    db_names = slot_maps_data.db_names
    db_array_names = slot_maps_data.db_array_names
    warnings = list(slot_maps_data.warnings)

    target_folder = config_manager.get_tia_folder_dispositivos()

    # ── 3. Preparar modified_bloques (clean + copytree) ──
    disp_ctx = build_cache(root=build_cache_root).dispositivos
    modified_bloques = disp_ctx.modified_bloques
    if modified_bloques.exists():
        shutil.rmtree(modified_bloques)
    modified_bloques.mkdir(parents=True, exist_ok=True)
    exports_bloques = disp_ctx.exports_bloques

    # ── 4. Export UNA VEZ + copytree ──
    for hw_type, db_name in db_names.items():
        await _dispatch_async(
            tia_client,
            "export_block",
            {
                "plc_name": plc_name,
                "block_name": db_name,
                "target_dir": str(exports_bloques),
            },
        )

    if exports_bloques.exists():
        shutil.copytree(
            str(exports_bloques),
            str(modified_bloques),
            dirs_exist_ok=True,
        )

    # ── 5. Batch: 6 dispatches separados (1 por hw_type) ──
    details: list[dict[str, Any]] = []
    ops_executed = 0

    for hw_type, db_name in db_names.items():
        slot_map = slot_maps.get(hw_type, {})
        # El handler espera ``{slot_str: texto}`` (la conversion a int
        # la hace internamente via ``slot_map_int = {int(k): v ...}``).
        slot_map_str: dict[str, str] = {
            str(slot): text for slot, text in slot_map.items()
        }
        db_array_name = db_array_names.get(hw_type, "")
        cmd = f"update_disp_comments_db_{hw_type}"
        resp = await _dispatch_async(
            tia_client,
            cmd,
            {
                "plc_name": plc_name,
                "db_name": db_name,
                "db_array_name": db_array_name,
                "slot_map": slot_map_str,
                "work_dir": str(modified_bloques),
                "target_folder": target_folder,
            },
        )
        if resp.get("ok"):
            ops_executed += 1
        details.append({
            "hw_type": hw_type,
            "db_name": db_name,
            "ok": resp.get("ok", False),
            "result": resp.get("result"),
            "error": resp.get("error"),
        })

    return {
        "plc_name": plc_name,
        "success": True,
        "applied": True,
        "operations_executed": ops_executed,
        "summary": {
            "disp_dbs_updated": ops_executed,
            "total_ops": ops_executed,
        },
        "details": details,
        "warnings": warnings,
    }


async def _dispatch_async(
    tia_client: Any,
    command: str,
    args: dict[str, Any],
    timeout_s: float = 300.0,
) -> dict[str, Any]:
    """Envia un comando al worker OT via ``submit_and_wait`` (sync) + to_thread.

    Encapsula el patron comun del area: ``submit_and_wait`` es sync
    (bloquea el thread), asi que lo envolvemos en ``asyncio.to_thread``
    para no bloquear el event loop del FB.
    """
    import asyncio
    dispatch = partial(
        tia_client.submit_and_wait, command, args, timeout_s,
    )
    return await asyncio.to_thread(dispatch)


__all__ = ["apply_disp_comments"]
