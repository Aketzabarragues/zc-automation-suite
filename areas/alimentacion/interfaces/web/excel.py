"""Router Excel: ``/api/v1/excel/...``.

Handler ``POST /api/v1/excel/upload`` puro: recibe el ``.xlsx``,
lo escribe a un tempfile, delega en ``UploadExcelUseCase`` y
devuelve su response. **No contiene lógica de negocio** (parse,
cache, volcado al ``AppState``, summary) — eso vive en el use
case (``areas/alimentacion/application/use_cases/upload_excel.py``)
y se testea de forma aislada en
``tests/test_upload_excel_use_case.py``.

Migrado a data-driven: en vez de hardcodear los 6 tipos legacy,
se itera ``ConfigManager.list_hw_types_active()`` y se usa
``get_excel_target_for(hw)`` para resolver la clave canónica del
Excel por cada hw_type. Cuando mañana se active un 7º tipo en el
config (``sd``, ``m_sina``, ``tq``, ``tq_ae``), este endpoint lo
recoge sin cambios (delegando en el use case, que también es
data-driven).

Flujo:
  1. Recibe el ``UploadFile`` (multipart).
  2. ``progress.begin(operation="upload_excel", ..., stages=[...])``.
  3. Escribe el contenido a un ``tempfile.NamedTemporaryFile``
     (``zcupload_*.xlsx``).
  4. ``UploadExcelUseCase.execute(tmp_path)`` — parsea, cachea,
     vuelca al ``AppState`` y construye el summary.
  5. ``progress.finish(success=True)`` y devuelve el response del
     use case. En error, ``progress.finish(success=False)`` y
     propaga el ``HTTPException`` que ya emite el use case.
  6. ``finally: tmp_path.unlink(missing_ok=True)`` — limpieza
     defensiva del tempfile.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from areas.alimentacion.application.use_cases.upload_excel import (
    UploadExcelUseCase,
)
from areas.alimentacion.infrastructure.cache import ExcelCacheManager
from core.application.log_buffer import LogBuffer
from core.application.progress_buffer import ProgressTracker
from core.application.state import AppState
from core.infrastructure.config_manager import ConfigManager
from core.infrastructure.gateway import TIAConnectionError
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
    """Recibe un .xlsx y delega en ``UploadExcelUseCase``.

    La orquestación HTTP es la única responsabilidad del handler:
    extraer el archivo de la request, persistirlo a un tempfile
    temporal, abrir el ``ProgressTracker``, invocar el use case y
    devolver su response. La lógica de parseo, cache y volcado al
    ``AppState`` vive en el use case (testeable sin FastAPI).
    """
    filename = file.filename or "upload.xlsx"
    suffix = Path(filename).suffix or ".xlsx"
    # ── Progress tracking (overlay SPA) ────────────────
    # 2 stages: parsear_excel → volcar_appstate. El use case
    # emite start_stage/finish_stage sobre los IDs que
    # declaramos aquí. El handler abre y cierra la operación.
    progress.begin(
        operation="upload_excel",
        label=f"Cargando Excel: {filename}",
        stages=["parsear_excel", "volcar_appstate"],
    )
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix, prefix="zcupload_"
        ) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = Path(tmp.name)
        logger.info(
            f"[excel/upload] Recibiendo archivo '{filename}' ({len(content)} bytes)."
        )

        use_case = UploadExcelUseCase(
            excel_cache_manager=ExcelCacheManager,
            config_manager=config_manager,
            app_state=state,
            progress_tracker=progress,
            log=logger,
        )
        result = await use_case.execute(tmp_path)
        progress.finish(success=True)
        return result
    except TIAConnectionError as exc:
        # Defensivo: ``UploadExcelUseCase`` no toca el gateway, pero
        # si en una iteración futura añade alguna llamada, queremos
        # que la respuesta sea 503 con ``X-Error-Type`` por
        # coherencia con el resto de routers del área.
        if progress.active:
            progress.finish(success=False, error=str(exc))
        raise HTTPException(
            status_code=503,
            detail=(
                f"TIA Portal no responde: {exc}. "
                "Reconecta el portal y vuelve a seleccionar el PLC."
            ),
            headers={"X-Error-Type": "TIAConnectionError"},
        ) from exc
    except Exception as exc:
        # El use case ya llamó ``progress.finish(success=False)``
        # y ``logger.error(...)`` y emitió ``HTTPException(400)``.
        # Aquí solo aseguramos que el tracker quede cerrado en
        # cualquier otro fallo (p. ej. error al escribir el
        # tempfile o al construir el use case).
        if progress.active:
            progress.finish(success=False, error=str(exc))
        raise
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


__all__ = ["router"]
