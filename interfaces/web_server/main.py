"""Interfaces Layer - Web Server (FastAPI).

Composition Root alternativo al MCP: expone los mismos servicios del
subdominio alimentación vía HTTP/REST + UI HTML (SPA Vue 3 en
``static/index.html``).

Reglas arquitectónicas:
  - SOLO importa desde ``infrastructure/`` y ``application/``.
  - Recibe UNA instancia Singleton de ``TIAProcessGateway`` por DI.
  - Toda la lógica de Diff pertenece a la capa de Aplicación (Casos
    de Uso), nunca al router HTTP ni al frontend.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any

# Permitir imports desde el raíz del repo cuando se ejecuta vía
# ``uvicorn interfaces.web_server.main:app``.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from application.log_buffer import get_log_buffer
from application.state import AppState, get_app_state
from application.use_cases.sync_dispositivos_dimensions import (
    SyncDispositivosDimensionsUseCase,
)
from application.use_cases.sync_dispositivos_instances import (
    SyncDispositivosInstancesUseCase,
)
from infrastructure.alimentacion.parsers.alimentacion_excel_parser import (
    AlimentacionExcelParser,
)
from infrastructure.config_manager import ConfigManager
from infrastructure.gateway import TIAProcessGateway


STATIC_DIR = Path(__file__).parent / "static"


# ── App Factory ────────────────────────────────────────────────────────


def create_app(gateway: TIAProcessGateway | None = None) -> FastAPI:
    """Crea la app FastAPI con UNA instancia inyectada de TIAProcessGateway.

    Args:
        gateway: Instancia Singleton del gateway. Si es ``None``, crea
            una nueva (modo desarrollo). En producción se inyecta
            desde ``main.py --web`` para garantizar una sola instancia.
    """
    if gateway is None:
        gateway = TIAProcessGateway()

    config_manager = ConfigManager("infrastructure/config.json")
    state = get_app_state()
    use_case_dimensions = SyncDispositivosDimensionsUseCase(state=state)
    use_case_instances = SyncDispositivosInstancesUseCase(
        gateway=gateway, state=state
    )

    app = FastAPI(title="ZC Automation Suite - Web Server")
    _register_routes(
        app,
        gateway,
        config_manager,
        use_case_dimensions,
        use_case_instances,
    )

    # Montar estáticos en /. El parámetro html=True hace que sirva
    # index.html cuando se accede a la raíz.
    if STATIC_DIR.exists():
        app.mount(
            "/",
            StaticFiles(directory=str(STATIC_DIR), html=True),
            name="static",
        )

    return app


# ── Pydantic models (request bodies) ──────────────────────────────────


class OpenNewPortalRequest(BaseModel):
    project_file_path: str


class DimensionsRequest(BaseModel):
    excel_path: str


class InstancesPreviewRequest(BaseModel):
    plc_name: str


class InstancesCommitRequest(BaseModel):
    plc_name: str
    prevision: dict[str, Any]


# ── Routes ────────────────────────────────────────────────────────────


def _register_routes(
    app: FastAPI,
    gateway: TIAProcessGateway,
    config_manager: ConfigManager,  # noqa: ARG001 (reservado)
    use_case_dimensions: SyncDispositivosDimensionsUseCase,
    use_case_instances: SyncDispositivosInstancesUseCase,
) -> None:
    """Registra todos los endpoints REST en la app."""

    log = get_log_buffer()

    # ── Índice (cuando NO se montan estáticos, p.ej. en tests) ──
    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        """Sirve la SPA (Vue 3 + Tailwind). Si no se monta automáticamente
        por StaticFiles (p.ej. en tests), devolvemos un placeholder."""
        spa = STATIC_DIR / "index.html"
        if spa.exists():
            return spa.read_text(encoding="utf-8")
        return (
            "<h1>ZC Automation Suite</h1>"
            "<p>static/index.html no encontrado.</p>"
        )

    # ── Conectar a TIA Portal ────────────────────────────────────────
    @app.post("/api/v1/portal/attach")
    async def portal_attach() -> dict[str, Any]:
        try:
            ok = await gateway.attach_portal()
        except Exception as exc:
            log.error(f"attach_portal failed: {exc}")
            raise HTTPException(
                status_code=500, detail=f"attach_portal failed: {exc}"
            ) from exc
        log.success("Hot-attach a TIA Portal OK" if ok else "attach_portal falló")
        return {"ok": ok}

    @app.post("/api/v1/portal/open-new")
    async def portal_open_new(req: OpenNewPortalRequest) -> dict[str, Any]:
        try:
            ok = await gateway.open_new_portal(req.project_file_path)
        except Exception as exc:
            log.error(f"open_new_portal failed: {exc}")
            raise HTTPException(
                status_code=500, detail=f"open_new_portal failed: {exc}"
            ) from exc
        log.success(
            f"Cold start OK con proyecto '{req.project_file_path}'"
            if ok else "open_new_portal falló"
        )
        return {"ok": ok}

    # ── Listar PLCs ────────────────────────────────────────────────
    @app.get("/api/v1/plcs")
    async def listar_plcs() -> dict[str, Any]:
        try:
            plcs = await gateway.get_plcs(force_refresh=True)
        except Exception as exc:
            log.error(f"get_plcs failed: {exc}")
            raise HTTPException(
                status_code=500, detail=f"get_plcs failed: {exc}"
            ) from exc
        log.info(f"PLC listados: {len(plcs)}")
        return {"plcs": plcs}

    # ── Carga maestra del Excel ────────────────────────────────────
    @app.post("/api/v1/excel/upload")
    async def excel_upload(file: UploadFile = File(...)) -> dict[str, Any]:
        """Recibe un .xlsx, lo parsea con AlimentacionExcelParser y
        popula el AppState (Singleton) con las listas tipadas.

        Returns:
            Resumen de cantidades por tipo, p.ej. ``{"DispED": 15, ...}``.
        """
        # Guardar temporalmente el .xlsx recibido (el parser necesita ruta).
        suffix = Path(file.filename or "upload.xlsx").suffix or ".xlsx"
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix, prefix="zcupload_"
        ) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = Path(tmp.name)

        log.info(f"Excel recibido: {file.filename} ({len(content)} bytes)")
        try:
            parser = AlimentacionExcelParser()
            state = get_app_state()

            # 1) Extraer dispositivos tipados.
            dispositivos_por_tipo = parser.extraer_dtos(tmp_path)

            # Resetear y popular el AppState con el resultado del Excel.
            state.reset()
            for tipo, dispositivos in dispositivos_por_tipo.items():
                target_list = getattr(state, f"dispositivos_{tipo.lower()}", None)
                if target_list is not None:
                    target_list.extend(dispositivos)

            # 2) Extraer dimensiones tipadas.
            dimensiones = parser.extraer_dimensiones(tmp_path)
            state.dimensiones = dimensiones

            # Resumen de cantidades para mostrar en la SPA.
            summary = {
                tipo: len(列表)
                for tipo, 列表 in dispositivos_por_tipo.items()
            }
        except Exception as exc:
            log.error(f"excel_upload failed: {exc}")
            raise HTTPException(
                status_code=400, detail=f"excel_upload failed: {exc}"
            ) from exc
        finally:
            tmp_path.unlink(missing_ok=True)

        log.success(
            f"Excel cargado: {sum(summary.values())} dispositivos en "
            f"{len(summary)} tipos"
        )
        return {
            "summary": summary,
            "dimensiones": {
                "num_disp_ed": dimensiones.num_disp_ed,
                "num_disp_ea": dimensiones.num_disp_ea,
                "num_disp_sa": dimensiones.num_disp_sa,
                "num_disp_v": dimensiones.num_disp_v,
                "num_disp_m": dimensiones.num_disp_m,
                "num_disp_m_vf": dimensiones.num_disp_m_vf,
            },
        }

    # ── Pre-Flight: generar prevision SIN mutar el PLC ─────────────
    @app.post("/api/v1/sync/preview")
    async def sync_preview(req: InstancesPreviewRequest) -> dict[str, Any]:
        """Lee XML actual + AppState y devuelve el Diff sin tocar TIA."""
        log.info(f"Generando prevision para PLC '{req.plc_name}'...")
        try:
            prevision = await use_case_instances.generar_prevision(req.plc_name)
        except Exception as exc:
            log.error(f"generar_prevision failed: {exc}")
            raise HTTPException(
                status_code=500,
                detail=f"generar_prevision failed: {exc}",
            ) from exc
        log.success(
            f"Prevision lista: "
            f"{len(prevision.get('agregados', []))} adds, "
            f"{len(prevision.get('eliminados', []))} removes, "
            f"{len(prevision.get('renombrados', []))} renames"
        )
        return prevision

    # ── Commit: aplicar prevision al PLC ───────────────────────────
    @app.post("/api/v1/sync/commit")
    async def sync_commit(req: InstancesCommitRequest) -> dict[str, Any]:
        """Aplica la prevision al PLC dentro de un lote transaccional.

        Requiere obligatoriamente una prevision previa del endpoint
        /sync/preview (el operario debe validarla antes de pulsar
        "Aplicar Cambios en TIA Portal" en la SPA).
        """
        log.info(
            f"Aplicando prevision al PLC '{req.plc_name}' "
            f"({len(req.prevision.get('agregados', []))} adds, "
            f"{len(req.prevision.get('eliminados', []))} removes, "
            f"{len(req.prevision.get('renombrados', []))} renames)..."
        )
        try:
            result = await use_case_instances.ejecutar_transaccion(
                req.plc_name, req.prevision
            )
        except Exception as exc:
            log.error(f"ejecutar_transaccion failed: {exc}")
            raise HTTPException(
                status_code=500,
                detail=f"ejecutar_transaccion failed: {exc}",
            ) from exc
        log.success(f"Transaccion completada: {result.get('operations')} ops")
        return result

    # ── Log buffer (polling desde la SPA) ──────────────────────────
    @app.get("/api/v1/logs")
    async def get_logs() -> dict[str, Any]:
        """Devuelve snapshot de mensajes para que la SPA los muestre."""
        return {"logs": get_log_buffer().snapshot()}

    @app.post("/api/v1/logs/clear")
    async def clear_logs() -> dict[str, Any]:
        """Vacía el buffer de logs (botón 'Limpiar consola' en SPA)."""
        get_log_buffer().clear()
        return {"cleared": True}


# ── ASGI app (uvicorn interfaces.web_server.main:app) ──────────────


app: FastAPI = create_app()
