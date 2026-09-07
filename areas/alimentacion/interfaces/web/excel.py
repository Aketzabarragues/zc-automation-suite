"""Router Excel: ``/api/v1/excel/...``.

Handlers ``POST /api/v1/excel/upload`` (multipart) y
``POST /api/v1/excel/reload`` (re-lee desde disco) puros: ambos
delegan en ``UploadExcelUseCase`` y devuelven su response. **No
contienen lógica de negocio** (parse, cache, volcado al
``AppState``, summary) — eso vive en el use case
(``areas/alimentacion/application/use_cases/upload_excel.py``) y
se testea de forma aislada en ``tests/test_upload_excel_use_case.py``.

Migrado a data-driven: en vez de hardcodear los 6 tipos legacy,
se itera ``ConfigManager.list_hw_types_active()`` y se usa
``get_excel_target_for(hw)`` para resolver la clave canónica del
Excel por cada hw_type. Cuando mañana se active un 7º tipo en el
config (``sd``, ``m_sina``, ``tq``, ``tq_ae``), este endpoint lo
recoge sin cambios (delegando en el use case, que también es
data-driven).

Flujo ``/upload`` (sept-2026, revisado tras bug del tempfile):
  1. Recibe el ``UploadFile`` (multipart).
  2. ``progress.begin(operation="upload_excel", ..., stages=[...])``.
  3. Lee el contenido a memoria (``await file.read()``).
  4. **Lo persiste** en una ubicación estable (``<dir>/last_excel_<ext>``,
     sibling del dir de logs). ANTES escribia a un tempfile en
     %TEMP% que se borraba en el ``finally`` → el reload fallaba
     porque ``state.excel_path`` apuntaba a un archivo que ya no
     existía. Ahora la ruta persiste y el reload funciona.
  5. ``UploadExcelUseCase.execute(persistent_path)`` — parsea, cachea,
     vuelca al ``AppState`` (``excel_path=persistent_path``) y
     construye el summary.
  6. ``progress.finish(success=True)`` y devuelve el response del
     use case. En error, ``progress.finish(success=False)`` y
     propaga el ``HTTPException`` que ya emite el use case.

Flujo ``/reload`` (sept-2026, pedido operario):
  1. Lee ``state.excel_path`` (ruta absoluta persistida en el
     primer ``/upload``, ahora ESTABLE gracias al fix del
     tempfile).
  2. Si ``excel_path`` es ``None`` o el archivo ya no existe en
     disco (movido/borrado por el operario), devuelve ``409 Conflict``
     con ``detail`` accionable para que la SPA fuerce la
     re-seleccion.
  3. ``UploadExcelUseCase.execute(excel_path)`` — re-lee desde
     la misma ruta, repuebla el cache y el AppState con el
     contenido ACTUAL del archivo.
  4. Mismo response shape que ``/upload`` (summary, devices, etc.).
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
from core.application.log_paths import resolve_log_dir
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


# ── Persistencia del Excel subido (sept-2026, fix tempfile) ─────
#
# El operario necesita poder "Actualizar" tras editar el Excel
# en otra app. Para que ``/reload`` funcione, la ruta que
# guardamos en ``AppState.excel_path`` debe ser **estable**,
# NO un tempfile en ``%TEMP%`` que se borraba en el ``finally``
# del handler (este era el bug que reporto el operario: el
# ``/reload`` fallaba con 409 "archivo no existe" porque
# ``excel_path`` apuntaba al tempfile ya borrado).
#
# Ubicacion: dir sibling del de logs (``<dir_logs_parent>/cache/``).
# Mismo patron de resolucion que ``resolve_log_dir`` pero con
# subdir distinto (``cache`` en vez de ``logs``) para no mezclar
# logs y datos persistentes. Si no se puede crear (permisos),
# fallback a ``%LocalAppData%/zc-automation-suite/cache/``.


def resolve_excel_cache_dir() -> Path:
    """Devuelve la carpeta estable donde persistir el Excel subido.

    Politica: sibling del dir de logs (``<parent>/cache/`` en vez
    de ``<parent>/logs/``). Si no se puede crear (permisos),
    fallback a ``%LocalAppData%/zc-automation-suite/cache``
    (mismo patron que ``resolve_log_dir``).

    Returns:
        ``Path`` a una carpeta existente. Nunca ``None``.
    """
    log_dir = resolve_log_dir()
    candidate = log_dir.parent / "cache"
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    except OSError:
        fallback = (
            Path.home()
            / "AppData"
            / "Local"
            / "zc-automation-suite"
            / "cache"
        )
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


# Nombre del archivo Excel persistido. Fixed name para que cada
# /upload sobreescriba el anterior — el "activo" es siempre el
# ultimo que subio el operario.
_PERSISTED_EXCEL_BASENAME = "last_excel"


@router.post("/upload")
async def upload_excel(
    file: UploadFile = File(...),
    state: AppState = Depends(get_app_state),
    logger: LogBuffer = Depends(get_logger),
    config_manager: ConfigManager = Depends(get_config_manager),
    progress: ProgressTracker = Depends(get_progress_tracker),
) -> dict[str, Any]:
    """Recibe un .xlsx, lo persiste en disco y delega en ``UploadExcelUseCase``.

    La orquestación HTTP es la única responsabilidad del handler:
    extraer el archivo de la request, **persistirlo** en una
    ubicación estable (sibling del dir de logs, sept-2026 — antes
    era un tempfile que se borraba en el ``finally``, lo que
    rompia ``/reload``), abrir el ``ProgressTracker``, invocar el
    use case y devolver su response. La lógica de parseo, cache
    y volcado al ``AppState`` vive en el use case (testeable sin
    FastAPI).
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
    persisted_path: Path | None = None
    try:
        # Leemos a memoria (no a NamedTemporaryFile, que era lo
        # que nos rompia: ``state.excel_path`` apuntaba al
        # tempfile y se borraba en el ``finally``).
        content = await file.read()
        # Persistimos en una ubicacion estable ANTES de pasar al
        # use case. Asi ``state.excel_path`` apunta a un archivo
        # que vive mas alla de este handler, y ``/reload`` lo
        # puede re-leer sin problemas.
        #
        # Usamos ``write_bytes`` directo (no atomic rename) porque
        # ``os.replace`` falla en Windows cuando el target esta
        # abierto (e.g. openpyxl en un test anterior que aun
        # retiene el handle). ``write_bytes`` abre con ``wb`` que
        # sobreescribe, y al cerrar libera el handle para que el
        # siguiente upload (o un test posterior) pueda
        # sobreescribirlo. La "atomicidad" no es critica aqui:
        # si el write falla a medias, ``content`` esta en
        # memoria del proceso (todavia en ``await file.read()``
        # mas arriba) y el operario puede reintentar el upload.
        cache_dir = resolve_excel_cache_dir()
        persisted_path = cache_dir / f"{_PERSISTED_EXCEL_BASENAME}{suffix}"
        persisted_path.write_bytes(content)
        logger.info(
            f"[excel/upload] Recibiendo archivo '{filename}' "
            f"({len(content)} bytes), persistido en '{persisted_path}'."
        )

        use_case = UploadExcelUseCase(
            excel_cache_manager=ExcelCacheManager,
            config_manager=config_manager,
            app_state=state,
            progress_tracker=progress,
            log=logger,
        )
        result = await use_case.execute(persisted_path)
        progress.finish(success=True)
        return result
    except Exception as exc:
        # El use case ya llamó ``progress.finish(success=False)``
        # y ``logger.error(...)`` y emitió ``HTTPException(400)``.
        # Aquí solo aseguramos que el tracker quede cerrado en
        # cualquier otro fallo (p. ej. error al escribir el
        # archivo persistente o al construir el use case).
        if progress.active:
            progress.finish(success=False, error=str(exc))
        raise
    # NO hay finally que borre el archivo: el archivo es
    # persistente a proposito (sept-2026) para que ``/reload``
    # lo pueda re-leer en futuras llamadas.


@router.post("/reload")
async def reload_excel(
    state: AppState = Depends(get_app_state),
    logger: LogBuffer = Depends(get_logger),
    config_manager: ConfigManager = Depends(get_config_manager),
    progress: ProgressTracker = Depends(get_progress_tracker),
) -> dict[str, Any]:
    """Re-lee el ultimo Excel desde disco (``state.excel_path``).

    Caso de uso (sept-2026, pedido operario): tras cargar un Excel
    inicial con ``/upload``, el operario puede editarlo en otra
    app (Excel) y querer refrescar la SPA sin tener que
    re-seleccionar el archivo. El handler anterior re-enviaba el
    ``File`` cacheado en memoria, que es un **snapshot en el
    momento de la primera subida** — no veia los cambios
    posteriores y, en algunos navegadores, daba
    ``TypeError: Failed to fetch`` al reusar la misma referencia
    de File tras un reset del input.

    Solucion: el backend guarda la ruta absoluta del Excel
    en ``AppState.excel_path``. Desde sept-2026, esa ruta
    apunta a una **ubicacion estable** (sibling del dir de
    logs) gracias al fix de ``/upload`` que persiste el
    archivo en vez de usar un tempfile. Este endpoint re-lee
    desde esa ruta.

    Args: ninguno (lee ``state.excel_path``).

    Returns:
        Mismo shape que ``/upload`` (``summary``, ``devices``,
        ``dimensiones``, etc.). Si el operario no ha subido un
        Excel antes, o el archivo ya no existe en disco, devuelve
        ``409 Conflict`` con ``detail`` accionable para que la SPA
        fuerce la re-seleccion (mismo patron que ``TIAConnectionError``
        en los endpoints de TIA).

    Raises:
        HTTPException 409: si no hay ``state.excel_path`` (no se ha
            subido un Excel antes) o el archivo ya no existe.
        HTTPException 400: si el parseo falla (delegado del use
            case, mismo formato que ``/upload``).
    """
    excel_path_str = state.excel_path
    if not excel_path_str:
        # No se ha subido un Excel antes. La SPA deberia haber
        # bloqueado el boton "Actualizar" en este caso, pero si
        # llega aqui devolvemos 409 con error accionable.
        logger.warning("[excel/reload] Sin excel_path en AppState.")
        raise HTTPException(
            status_code=409,
            detail=(
                "No hay un Excel cargado. Vuelve a subir el archivo "
                "con el botón 'Cargar Excel' antes de refrescar."
            ),
        )
    excel_path = Path(excel_path_str)
    if not excel_path.exists():
        # El archivo fue movido/borrado entre el upload y el
        # reload. La SPA debe forzar re-seleccion.
        logger.warning(
            f"[excel/reload] Archivo no encontrado en disco: {excel_path}"
        )
        raise HTTPException(
            status_code=409,
            detail=(
                f"El archivo Excel ya no existe en disco ({excel_path}). "
                "Vuelve a subirlo desde su nueva ubicación."
            ),
        )

    logger.info(
        f"[excel/reload] Re-leyendo Excel desde '{excel_path}'."
    )
    # Mismo ProgressTracker pattern que /upload. Reutilizamos
    # los 2 stages ("parsear_excel" + "volcar_appstate") para
    # que la SPA pinte el overlay igual que en la primera carga.
    progress.begin(
        operation="reload_excel",
        label=f"Recargando Excel: {excel_path.name}",
        stages=["parsear_excel", "volcar_appstate"],
    )
    try:
        use_case = UploadExcelUseCase(
            excel_cache_manager=ExcelCacheManager,
            config_manager=config_manager,
            app_state=state,
            progress_tracker=progress,
            log=logger,
        )
        result = await use_case.execute(excel_path)
        progress.finish(success=True)
        return result
    except Exception as exc:
        # El use case ya llamó ``progress.finish(success=False)``
        # y ``logger.error(...)`` y emitió ``HTTPException(400)``.
        # Aquí solo aseguramos que el tracker quede cerrado en
        # cualquier otro fallo (p.ej. el archivo se borro entre
        # el exists() check y la lectura por otra ventana).
        if progress.active:
            progress.finish(success=False, error=str(exc))
        raise


__all__ = ["router"]
