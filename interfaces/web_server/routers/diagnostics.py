"""Router Diagnostics: ``/api/v1/logs`` + ``/api/v1/state/...`` + ``/api/v1/progress/...``.

Endpoints de sólo lectura (IT) para la SPA: vuelca el ``AppState``,
expone el ``LogBuffer`` y el ``ProgressTracker``. Nunca toca la DLL
de Siemens.

Migrado a data-driven: en vez de hardcodear los 6 tipos legacy,
se itera ``ConfigManager.list_hw_types_active()`` y se usa
``get_excel_target_for(hw)["canonical"]`` para resolver la clave
del dict ``dispositivos`` de la respuesta. Cuando mañana se
active un 7º tipo en el config, este endpoint lo recoge sin
cambios.
"""
from __future__ import annotations

import dataclasses
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

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
from core.application.log_buffer import get_log_buffer
from core.application.progress_buffer import get_progress_tracker as _get_progress_singleton


_logger = logging.getLogger(__name__)


class LogEntry(BaseModel):
    """Payload de un push de log desde el frontend al ``LogBuffer``.

    Sept-2026: el frontend (``store.js::_applyTiaSnapshot``) detecta
    cuando TIA se cierra por fuera y, tras limpiar el state PLC-related
    para evitar confusion, deja un aviso en la ConsolaLogs. Como
    ``pushLog`` del frontend solo escribe a ``store.logs`` (memoria
    local, sobreescrita por el poll cada 1s), necesitamos un endpoint
    que persista el mensaje en el ``LogBuffer`` del backend (el que
    se ve en la ConsolaLogs de la SPA).

    Validacion: ``level`` es un Literal para que el frontend NO
    pueda inyectar niveles arbitrarios (defensivo, evita que un
    caller escriba a niveles reservados o inventados).
    """

    message: str = Field(
        ..., min_length=1, max_length=2000, description="Texto del log"
    )
    level: Literal["info", "success", "warning", "error"] = Field(
        default="info", description="Nivel de severidad (mismo enum que LogBuffer)"
    )


def _extract_software_from_cache(state: AppState) -> dict[str, Any]:
    """Extrae los 4 dominios de software + el flag del ``state.excel_cache``.

    Helper introducido en Fase 6 del plan canónico
    (``_plan/04_excel_cache_phased_plan.md``) para añadir los 4
    nuevos campos (``procesos``, ``parametros_int``,
    ``parametros_real``, ``alarmas``) y el flag
    ``software_parsers_implemented`` al response de
    ``GET /api/v1/state/dispositivos`` sin contaminar la función del
    endpoint.

    Política defensiva:
      * Si ``state.excel_cache`` es ``None`` (operario aún no ha
        subido Excel) → los 4 arrays quedan ``[]`` y el flag
        ``false``. La SPA renderiza el banner ámbar.
      * Si el cache tiene los campos pero alguno falla al
        serializar (defensa contra schema drift), se loggea
        WARNING y se devuelve lo que se haya podido extraer.

    Returns:
        Dict con las 5 keys (``procesos``, ``parametros_int``,
        ``parametros_real``, ``alarmas``,
        ``software_parsers_implemented``) listas para ``**`` en el
        response del endpoint.
    """
    empty: dict[str, Any] = {
        "procesos": [],
        "parametros_int": [],
        "parametros_real": [],
        "alarmas": [],
        "software_parsers_implemented": False,
    }
    cache = getattr(state, "excel_cache", None)
    if cache is None:
        return empty
    try:
        return {
            "procesos": [dataclasses.asdict(p) for p in cache.procesos],
            "parametros_int": [dataclasses.asdict(p) for p in cache.parametros_int],
            "parametros_real": [dataclasses.asdict(p) for p in cache.parametros_real],
            "alarmas": [dataclasses.asdict(a) for a in cache.alarmas],
            "software_parsers_implemented": bool(
                getattr(cache, "software_parsers_implemented", False)
            ),
        }
    except Exception as exc:  # defensivo: schema drift del cache
        _logger.warning("Error extrayendo software del cache: %s", exc)
        return empty


router = APIRouter(prefix="/api/v1", tags=["Diagnostics"])


@router.get("/state/dispositivos")
async def state_dispositivos(
    state: AppState = Depends(get_app_state),
    config_manager: ConfigManager = Depends(get_config_manager),
    tracker: ProgressTracker = Depends(get_progress_tracker),
) -> dict[str, Any]:
    """Vuelca el ``AppState`` Singleton a JSON para el Inspector IT.

    - ``dimensiones`` se serializa vía ``to_api_dict()`` (NO
      ``dataclasses.asdict``) para que el campo ``extras`` —
      interno del wrapper, pensado para futuros N_MAX del
      catálogo — NO aparezca en la SPA. Los 6 legacy
      ``num_disp_*`` siguen saliendo con la misma forma exacta
      que antes del refactor.
    - ``dispositivos`` se itera por ``cm.list_hw_types_active()``;
      la clave de cada entrada es la ``canonical`` resuelta vía
      ``cm.get_excel_target_for(hw)`` (``DispED``,
      ``DispEA``, ...). Los 6 legacy actuales salen idéntico
      que antes; los tipos nuevos saldrán automáticamente.
    """
    dispositivos_payload: dict[str, list[dict[str, Any]]] = {}
    tracker.begin(
        operation="refresh_memoria",
        label="Refrescando Inspector de Memoria",
        stages=["dump_state"],
    )
    tracker.start_stage("dump_state", "Serializando AppState para la SPA...")
    try:
        for hw in config_manager.list_hw_types_active():
            target = config_manager.get_excel_target_for(hw)
            if target is None:
                continue
            canonica = target.get("canonical", "")
            if not canonica:
                continue
            dispositivos_payload[canonica] = [
                dataclasses.asdict(d) for d in state.get_devices(hw)
            ]
        tracker.finish_stage("dump_state", f"{len(dispositivos_payload)} tipos")
        tracker.finish(success=True)
    except Exception as exc:
        tracker.finish_stage("dump_state", f"Error: {exc}")
        tracker.finish(success=False, error=str(exc))
        raise

    return {
        "ok": True,
        # ``state.dimensiones`` es ``None`` por default (PR 2 lo dejó
        # como placeholder de back-compat; se popula tras un upload
        # de Excel). Si el operario abre la SPA sin haber subido
        # Excel, devolveríamos un 500 con ``'NoneType' has no
        # attribute 'to_api_dict'``. Devolvemos ``{}`` como modo
        # degradado: la SPA trata ``dimensiones`` como opcional.
        "dimensiones": (
            state.dimensiones.to_api_dict()
            if state.dimensiones is not None
            else {}
        ),
        "dispositivos": dispositivos_payload,
        # ── Fase 6: 4 dominios de software + flag ──────────────────────
        # El flag ``software_parsers_implemented`` permite a la SPA
        # funcionar en modo degradado (banner ámbar) si el backend
        # aún no trae los 4 campos nuevos (caso back-compat con un
        # backend anterior a Fase 5/6 del plan canónico).
        # Si ``state.excel_cache`` es ``None`` (operario aún no ha
        # subido Excel), los 4 arrays quedan ``[]`` y el flag
        # ``false``. Defensivo: usamos ``getattr`` porque
        # ``excel_cache`` es un placeholder ``Any`` declarado en
        # ``AppState`` (ver ``core/application/state.py``).
        ** _extract_software_from_cache(state),
    }


@router.get("/logs")
async def get_logs(
    _logger: LogBuffer = Depends(get_logger),
) -> dict[str, Any]:
    """Devuelve snapshot de mensajes para que la SPA los muestre."""
    return {"logs": get_log_buffer().snapshot()}


@router.post("/logs/clear")
async def clear_logs(
    _logger: LogBuffer = Depends(get_logger),
) -> dict[str, Any]:
    """Vacía el buffer de logs (botón 'Limpiar consola' en SPA)."""
    get_log_buffer().clear()
    return {"cleared": True}


@router.post("/logs", status_code=201)
async def post_log(
    entry: LogEntry,
) -> dict[str, Any]:
    """Push de log desde el frontend al ``LogBuffer`` visible en la ConsolaLogs.

    Caso de uso (sept-2026, pedido operario): cuando TIA Portal se
    cierra por fuera (sin click en "Desconectar"), el worker persistente
    lo detecta por heartbeat y la SPA transiciona ``tiaConnection.state``
    a ``"idle"`` o ``"error"``. Hasta ahora eso solo actualizaba el
    circulo/texto del estado: el resto de caches (plcs, selectedPlc,
    plcBlocksCache, projectInfo, previewData, procesosSync) seguian
    en memoria, dando la falsa sensacion de que el operario seguia
    conectado.

    El fix limpia esos slots en ``_applyTiaSnapshot`` y ademas deja un
    aviso persistente en la ConsolaLogs via este endpoint (el push
    local de ``store.js::pushLog`` no persiste: el poll cada 1s
    sobreescribe ``store.logs`` con la version del backend, asi que
    necesitamos que el mensaje viva en el ``LogBuffer`` backend).

    Politica:
      - ``level`` validado por Pydantic (Literal); el frontend NO
        puede inyectar niveles arbitrarios.
      - Sin autenticacion: el endpoint es interno de la SPA. Si en
        el futuro se expone a un tercero, hay que meter auth + rate
        limiting (un caller hostil podria llenar el buffer).
      - Devuelve 201 Created (estandar REST para creacion de recurso
        en una collection).
    """
    if entry.level == "success":
        get_log_buffer().success(entry.message)
    elif entry.level == "warning":
        get_log_buffer().warning(entry.message)
    elif entry.level == "error":
        get_log_buffer().error(entry.message)
    else:
        get_log_buffer().info(entry.message)
    return {"ok": True, "level": entry.level, "message": entry.message}


# ── Progress tracker (overlay de operaciones largas en la SPA) ─────


@router.get("/progress/current")
async def get_progress(
    _tracker: ProgressTracker = Depends(get_progress_tracker),
) -> dict[str, Any]:
    """Devuelve el snapshot del ``ProgressTracker`` Singleton.

    La SPA hace polling cada 500 ms contra este endpoint; el tracker
    es la única fuente de verdad del progreso (la SPA solo lee).
    """
    snap = _get_progress_singleton().snapshot()
    return {"ok": True, "progress": snap.to_dict()}


@router.post("/progress/clear")
async def clear_progress(
    _tracker: ProgressTracker = Depends(get_progress_tracker),
) -> dict[str, Any]:
    """Resetea el ``ProgressTracker`` al estado vacío.

    Lo dispara el frontend tras el auto-close del overlay (3-5 s
    tras éxito) o cuando el operario pulsa "Cerrar" en estados
    terminales. Idempotente: si ya está vacío, no-op.
    """
    _get_progress_singleton().clear()
    return {"cleared": True}


__all__ = ["router"]
