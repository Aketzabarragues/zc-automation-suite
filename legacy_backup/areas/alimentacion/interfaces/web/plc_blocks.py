"""Router PlcBlocks: ``/api/v1/plcs/<plc_name>/blocks`` y ``/.../refresh``.

Aportado por el área Alimentación. Expone la caché en memoria de
bloques PLC (DTO ``BloqueCache`` en ``core/models/bloque_cache.py``)
construida por el use case ``ScanPlcBlocksUseCase``.

Endpoints:
  - ``GET  /api/v1/plcs/{plc_name}/blocks``       → snapshot cacheado.
  - ``POST /api/v1/plcs/{plc_name}/blocks/refresh`` → fuerza re-scan.

El shell ``app.py`` descubre este router vía
``AreaRegistry.for_each("contributes_routers", app=app)`` desde
``register_routers`` del paquete ``areas.alimentacion.interfaces.web``;
``app.py`` NO lo importa directamente.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from core.application.log_buffer import LogBuffer
from core.application.progress_buffer import ProgressTracker
from core.infrastructure.gateway import TIAConnectionError, TIAProcessGateway
from interfaces.web_server.dependencies import (
    get_gateway,
    get_logger,
    get_progress_tracker,
)


router = APIRouter(prefix="/api/v1/plcs", tags=["PlcBlocks"])


# Umbral (segundos) bajo el cual un snapshot se considera ``from_cache``.
# Si el ``scanned_at`` del cache tiene menos de este delta contra
# ``now``, devolvemos ``from_cache=True``; en otro caso, se considera
# que fue un re-scan fresco (``from_cache=False``). El use case hace
# la política real de invalidación; esto es solo la señal que la SPA ve.
_CACHE_FRESH_SECONDS: float = 5.0 * 60.0  # 5 minutos


def _build_use_case(
    gateway: TIAProcessGateway,
    progress: ProgressTracker,
) -> Any:
    """Construye el use case con el gateway y el ProgressTracker inyectados.

    Import perezoso: si el módulo del use case todavía no existe en
    esta rama (p. ej. en una rama aislada antes del merge con la
    pista ``tia-ot-worker``), el router sigue siendo importable. La
    excepción solo se lanza al invocar el endpoint, momento en el que
    el módulo del use case ya debe estar presente en el árbol.
    """
    from areas.alimentacion.application.use_cases.scan_plc_blocks import (
        ScanPlcBlocksUseCase,
    )

    return ScanPlcBlocksUseCase(gateway, progress=progress)


def _is_cache_fresh(scanned_at: datetime) -> bool:
    """``True`` si el snapshot tiene menos de ``_CACHE_FRESH_SECONDS``."""
    if scanned_at is None:
        return False
    # ``scanned_at`` puede venir naive (sin tzinfo) si la cache se
    # construyó en un proceso sin zona horaria fijada. En ese caso lo
    # tratamos como UTC para no romper la comparación.
    if scanned_at.tzinfo is None:
        scanned_at = scanned_at.replace(tzinfo=timezone.utc)
    delta = (datetime.now(timezone.utc) - scanned_at).total_seconds()
    return 0 <= delta < _CACHE_FRESH_SECONDS


def _validate_plc_name(plc_name: str) -> None:
    """Lanza ``HTTPException(400)`` si ``plc_name`` está vacío o es solo whitespace."""
    if not plc_name or not plc_name.strip():
        raise HTTPException(
            status_code=400,
            detail="plc_name es obligatorio y no puede estar vacío.",
        )


@router.get("/{plc_name}/blocks")
async def get_plc_blocks(
    plc_name: str,
    gateway: TIAProcessGateway = Depends(get_gateway),
    logger: LogBuffer = Depends(get_logger),
    progress: ProgressTracker = Depends(get_progress_tracker),
) -> dict[str, Any]:
    """Devuelve el snapshot cacheado de bloques + tag_tables del PLC.

    Política:
      - ``from_cache=True``  → snapshot con ``scanned_at < 5 min``.
      - ``from_cache=False`` → snapshot recién escaneado.

    El use case decide si el snapshot se reutiliza o se re-escanea
    (umbral interno del propio use case); aquí solo reportamos el
    resultado a la SPA vía ``from_cache``. El scan se refleja en el
    ``ProgressTracker`` (mismo Singleton que el resto de operaciones
    largas) para que el ``ProgressIndicator`` del sidebar lo muestre
    como un task más, sin widgets nuevos.
    """
    _validate_plc_name(plc_name)
    use_case = _build_use_case(gateway, progress)
    logger.info(
        f"[plc_blocks/get] Solicitando snapshot de bloques para '{plc_name}'."
    )
    try:
        cache = await use_case.ensure_cache(plc_name)
    except HTTPException:
        raise
    except TIAConnectionError as exc:
        logger.error(f"[plc_blocks/get] TIA Portal no responde: {exc}")
        raise HTTPException(
            status_code=503,
            detail=(
                f"TIA Portal no responde: {exc}. "
                "Reconecta el portal y vuelve a seleccionar el PLC."
            ),
            headers={"X-Error-Type": "TIAConnectionError"},
        ) from exc
    except Exception as exc:
        logger.error(f"[plc_blocks/get] Fallo al obtener snapshot: {exc}")
        raise HTTPException(
            status_code=502,
            detail=f"scan_plc_blocks failed: {exc}",
        ) from exc

    payload = cache.to_dict()
    payload["ok"] = True
    payload["from_cache"] = _is_cache_fresh(cache.scanned_at)
    # Log de cierre con el resumen: nº de bloques y tablas del
    # snapshot. La coletilla "(caché)" indica al operario que NO
    # se ha re-escaneado TIA: el snapshot venía de la memoria IT.
    cache_suffix = " (caché)" if payload["from_cache"] else ""
    logger.success(
        f"[plc_blocks/get] Snapshot: {len(cache.blocks)} "
        f"bloques, {len(cache.tag_tables)} tablas{cache_suffix}."
    )
    return payload


@router.post("/{plc_name}/blocks/refresh")
async def refresh_plc_blocks(
    plc_name: str,
    gateway: TIAProcessGateway = Depends(get_gateway),
    logger: LogBuffer = Depends(get_logger),
    progress: ProgressTracker = Depends(get_progress_tracker),
) -> dict[str, Any]:
    """Fuerza un re-scan del PLC, ignorando la caché existente.

    Siempre devuelve ``from_cache=False`` (la respuesta ES el resultado
    del re-scan, no una lectura de caché).
    """
    _validate_plc_name(plc_name)
    use_case = _build_use_case(gateway, progress)
    logger.info(
        f"[plc_blocks/refresh] Re-escaneando bloques para '{plc_name}'."
    )
    try:
        cache = await use_case.ensure_cache(plc_name, force_refresh=True)
    except HTTPException:
        raise
    except TIAConnectionError as exc:
        logger.error(f"[plc_blocks/refresh] TIA Portal no responde: {exc}")
        raise HTTPException(
            status_code=503,
            detail=(
                f"TIA Portal no responde: {exc}. "
                "Reconecta el portal y vuelve a seleccionar el PLC."
            ),
            headers={"X-Error-Type": "TIAConnectionError"},
        ) from exc
    except Exception as exc:
        logger.error(f"[plc_blocks/refresh] Fallo al re-escanear: {exc}")
        raise HTTPException(
            status_code=502,
            detail=f"scan_plc_blocks refresh failed: {exc}",
        ) from exc

    payload = cache.to_dict()
    payload["ok"] = True
    payload["from_cache"] = False  # siempre fresh tras refresh
    logger.success(
        f"[plc_blocks/refresh] Re-escaneo completado: {len(cache.blocks)} "
        f"bloques, {len(cache.tag_tables)} tablas."
    )
    return payload


__all__ = ["router"]
