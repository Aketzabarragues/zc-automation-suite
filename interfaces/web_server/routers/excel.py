"""Router Excel: ``/api/v1/excel/...``.

Carga el ``AlimentacionExcelParser`` y popula el ``AppState``
Singleton. Toda la lógica de ficheros temporales y validación de
errores vivirá aquí; los routers no importan nada de Siemens.

Migrado a data-driven: en vez de hardcodear los 6 tipos legacy,
se itera ``ConfigManager.list_hw_types_active()`` y se usa
``get_app_state_attr_for(hw)`` + ``get_excel_target_for(hw)``
para resolver el nombre del atributo del AppState y la clave
canónica del Excel por cada hw_type. Cuando mañana se active
un 7º tipo en el config (``sd``, ``m_sina``, ``tq``, ``tq_ae``),
este endpoint lo recoge sin cambios.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from application.log_buffer import LogBuffer
from application.state import AppState
from infrastructure.alimentacion.parsers.alimentacion_excel_parser import (
    AlimentacionExcelParser,
)
from infrastructure.config_manager import ConfigManager
from interfaces.web_server.dependencies import (
    get_app_state,
    get_config_manager,
    get_logger,
)


router = APIRouter(prefix="/api/v1/excel", tags=["Excel"])


@router.post("/upload")
async def upload_excel(
    file: UploadFile = File(...),
    state: AppState = Depends(get_app_state),
    logger: LogBuffer = Depends(get_logger),
    config_manager: ConfigManager = Depends(get_config_manager),
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
    with tempfile.NamedTemporaryFile(
        delete=False, suffix=suffix, prefix="zcupload_"
    ) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    logger.info(
        f"📥 Recibiendo Excel: '{file.filename}' ({len(content)} bytes)"
    )
    try:
        logger.info("🔍 Parseando estructura del Excel...")
        # Inyectamos el CM al parser para que use la ruta data-driven
        # (override de ``_EXCEL_TARGETS`` si el config define
        # ``excel_target`` por hw_type).
        parser = AlimentacionExcelParser(config_manager=config_manager)
        dispositivos_por_tipo = parser.extraer_dtos(tmp_path)

        # Volcado data-driven: por cada hw_type activo, resolver su
        # atributo del AppState (legacy o dinámico) y la clave
        # canónica del Excel, y asignar la lista (o ``[]``).
        for hw in config_manager.list_hw_types_active():
            target = config_manager.get_excel_target_for(hw)
            attr = config_manager.get_app_state_attr_for(hw)
            if target is None or attr is None:
                continue
            canonica = target.get("canonical", "")
            if not canonica:
                continue
            setattr(state, attr, dispositivos_por_tipo.get(canonica, []))

        dimensiones = parser.extraer_dimensiones(tmp_path)
        state.dimensiones = dimensiones

        summary = {
            tipo: len(lista)
            for tipo, lista in dispositivos_por_tipo.items()
        }
        total_hw = sum(summary.values())
        logger.success(
            f"✅ Carga maestra completada: {total_hw} dispositivos "
            f"extraídos ({len(summary)} tipos)."
        )
        for tipo, qty in summary.items():
            logger.info(f"   • {tipo}: {qty} elementos")
    except Exception as exc:
        logger.error(f"❌ Fallo crítico al parsear el Excel: {exc}")
        raise HTTPException(
            status_code=400, detail=f"excel_upload failed: {exc}"
        ) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    return {
        "ok": True,
        "summary": summary,
        "total_dispositivos": sum(summary.values()),
        # ``to_api_dict()`` en vez de ``dataclasses.asdict``: oculta
        # el campo ``extras`` (interno / futuro) de la respuesta al
        # cliente del upload. Mismo shape que ``dataclasses.asdict``
        # salvo por la ausencia de ``extras``.
        "dimensiones": dimensiones.to_api_dict(),
    }


__all__ = ["router"]
