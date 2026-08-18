"""Router Excel: ``/api/v1/excel/...``.

Carga el ``AlimentacionExcelParser`` y popula el ``AppState``
Singleton. Toda la lógica de ficheros temporales y validación de
errores vivirá aquí; los routers no importan nada de Siemens.
"""
from __future__ import annotations

import dataclasses
import tempfile
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from application.log_buffer import LogBuffer
from application.state import AppState
from core.alimentacion.models.dispositivos import (
    DispEA,
    DispED,
    DispM,
    DispM_VF,
    DispSA,
    DispV,
)
from interfaces.web_server.dependencies import get_app_state, get_logger
from infrastructure.alimentacion.parsers.alimentacion_excel_parser import (
    AlimentacionExcelParser,
)


router = APIRouter(prefix="/api/v1/excel", tags=["Excel"])


@router.post("/upload")
async def upload_excel(
    file: UploadFile = File(...),
    state: AppState = Depends(get_app_state),
    logger: LogBuffer = Depends(get_logger),
) -> dict[str, Any]:
    """Recibe un .xlsx, lo parsea y popula el ``AppState``."""
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
        parser = AlimentacionExcelParser()

        dispositivos_por_tipo = parser.extraer_dtos(tmp_path)

        state.dispositivos_ed = cast(
            list[DispED], dispositivos_por_tipo.get("DispED", [])
        )
        state.dispositivos_ea = cast(
            list[DispEA], dispositivos_por_tipo.get("DispEA", [])
        )
        state.dispositivos_sa = cast(
            list[DispSA], dispositivos_por_tipo.get("DispSA", [])
        )
        state.dispositivos_v = cast(
            list[DispV], dispositivos_por_tipo.get("DispV", [])
        )
        state.dispositivos_m = cast(
            list[DispM], dispositivos_por_tipo.get("DispM", [])
        )
        state.dispositivos_m_vf = cast(
            list[DispM_VF], dispositivos_por_tipo.get("DispM_VF", [])
        )

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
        "dimensiones": dataclasses.asdict(dimensiones),
    }


__all__ = ["router"]
