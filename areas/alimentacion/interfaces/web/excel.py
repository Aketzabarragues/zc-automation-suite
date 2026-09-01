"""Router Excel: ``/api/v1/excel/...``.

Carga el ``ExcelLoader`` + ``ExcelCacheManager`` y popula el
``AppState`` Singleton. Toda la lógica de ficheros temporales y
validación de errores vivirá aquí; los routers no importan nada
de Siemens.

Migrado a data-driven: en vez de hardcodear los 6 tipos legacy,
se itera ``ConfigManager.list_hw_types_active()`` y se usa
``get_app_state_attr_for(hw)`` + ``get_excel_target_for(hw)``
para resolver el nombre del atributo del AppState y la clave
canónica del Excel por cada hw_type. Cuando mañana se active
un 7º tipo en el config (``sd``, ``m_sina``, ``tq``, ``tq_ae``),
este endpoint lo recoge sin cambios.

Flujo (Fase 5 del plan ``_plan/04_excel_cache_phased_plan.md``):
  1. Recibe el .xlsx (multipart upload).
  2. ``asyncio.to_thread(loader.load, tmp_path)`` — abre el workbook
     UNA vez y construye el ``ExcelCache`` (no bloquea el event loop).
  3. ``ExcelCacheManager.put(cache)`` — cachea para coroutines que
     esperen con ``wait_for_first_load``.
  4. ``state.excel_cache = cache`` + ``state.excel_path = path``.
  5. Back-compat con la SPA: puebla ``state.dispositivos_<hw>`` y
     ``state.dimensiones`` desde el cache (los routers y la SPA
     actuales siguen leyéndolos de ahí).
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from areas.alimentacion.infrastructure.cache import ExcelCacheManager
from areas.alimentacion.infrastructure.loaders import ExcelLoader
from core.application.log_buffer import LogBuffer
from core.application.progress_buffer import ProgressTracker
from core.application.state import AppState
from core.infrastructure.config_manager import ConfigManager
from interfaces.web_server.dependencies import (
    get_app_state,
    get_config_manager,
    get_logger,
    get_progress_tracker,
)


router = APIRouter(prefix="/api/v1/excel", tags=["Excel"])


@router.post("/upload")
async def upload_excel(
    file: UploadFile = File(...),
    state: AppState = Depends(get_app_state),
    logger: LogBuffer = Depends(get_logger),
    config_manager: ConfigManager = Depends(get_config_manager),
    progress: ProgressTracker = Depends(get_progress_tracker),
) -> dict[str, Any]:
    """Recibe un .xlsx, lo parsea y popula el ``AppState``.

    Data-driven: itera ``cm.list_hw_types_active()`` y, para cada
    tipo, escribe la lista parseada en el atributo del AppState
    correspondiente (``state.dispositivos_<hw>`` legacy o, para
    tipos nuevos, ``state.set_devices(hw, devices)``). El
    backend ya tiene CM inyectado en ``app.state``; este router
    no hace ninguna llamada a TIA Portal.
    """
    suffix = Path(file.filename or "upload.xlsx").suffix or ".xlsx"
    # ── Progress tracking (overlay SPA) ────────────────
    # 3 stages: recibir_archivo → parsear_excel → volcar_appstate.
    progress.begin(
        operation="upload_excel",
        label=f"Cargando Excel: {file.filename or 'upload.xlsx'}",
        stages=["recibir_archivo", "parsear_excel", "volcar_appstate"],
    )
    try:
        progress.start_stage("recibir_archivo")
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix, prefix="zcupload_"
        ) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = Path(tmp.name)
        progress.finish_stage(
            "recibir_archivo", f"{len(content)} bytes recibidos"
        )

        logger.info(
            f"📥 Recibiendo Excel: '{file.filename}' ({len(content)} bytes)"
        )
        try:
            progress.start_stage("parsear_excel")
            logger.info("🔍 Parseando estructura del Excel...")
            # El loader es sync (abre el workbook con openpyxl). Lo
            # envolvemos en ``asyncio.to_thread`` para no bloquear el
            # event loop del FastAPI (D3 del plan).
            loader = ExcelLoader(config_manager=config_manager)
            cache = await asyncio.to_thread(loader.load, tmp_path)
            await ExcelCacheManager.put(cache)
            progress.finish_stage(
                "parsear_excel",
                f"{sum(len(v) for v in cache.dispositivos.values())} "
                f"dispositivos parseados",
            )

            progress.start_stage("volcar_appstate")
            # Back-compat con la SPA: poblar ``state.dispositivos_<hw>``
            # desde ``cache.dispositivos`` (las 6 listas como listas
            # mutables; la SPA sigue esperando ``list``, no ``tuple``).
            for hw, devices_tuple in cache.dispositivos.items():
                state.set_devices(hw, list(devices_tuple))
            state.dimensiones = cache.n_max
            # El cache vive en el área de alimentación, pero AppState
            # lo expone como placeholder ``Any`` (ver ``state.py``).
            state.excel_cache = cache
            state.excel_path = cache.excel_path
            progress.finish_stage("volcar_appstate", "Estado actualizado")

            # ``summary`` con la shape legacy: ``{tipo_canonica: count}``.
            # Como el cache no expone directamente las claves canónicas
            # (``DispED``...), derivamos el summary a partir de los
            # ``hw_type`` de ``config_manager``.
            summary: dict[str, int] = {}
            for hw in config_manager.list_hw_types_active():
                target = config_manager.get_excel_target_for(hw)
                if target is None:
                    continue
                canonica = target.get("canonical", "")
                if not canonica:
                    continue
                devices_tuple = cache.dispositivos.get(hw, ())
                summary[canonica] = len(devices_tuple)
            total_hw = sum(summary.values())
            logger.success(
                f"✅ Carga maestra completada: {total_hw} dispositivos "
                f"extraídos ({len(summary)} tipos)."
            )
            for tipo, qty in summary.items():
                logger.info(f"   • {tipo}: {qty} elementos")
            progress.finish(success=True)
        except Exception as exc:
            progress.finish(success=False, error=str(exc))
            logger.error(f"❌ Fallo crítico al parsear el Excel: {exc}")
            raise HTTPException(
                status_code=400, detail=f"excel_upload failed: {exc}"
            ) from exc
        finally:
            tmp_path.unlink(missing_ok=True)
    except HTTPException:
        # Ya manejado arriba; asegurar que progress se cierre en error.
        progress.finish(success=False)
        raise
    except Exception as exc:
        progress.finish(success=False, error=str(exc))
        raise

    return {
        "ok": True,
        "summary": summary,
        "total_dispositivos": sum(summary.values()),
        # ``to_api_dict()`` en vez de ``dataclasses.asdict``: oculta
        # el campo ``extras`` (interno / futuro) de la respuesta al
        # cliente del upload. Mismo shape que ``dataclasses.asdict``
        # salvo por la ausencia de ``extras``.
        "dimensiones": cache.n_max.to_api_dict(),
    }


__all__ = ["router"]
