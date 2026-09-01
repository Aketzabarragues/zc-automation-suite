"""Tools MCP del área de alimentación (paridad con endpoints web).

Estas tools NO replican lógica de negocio: delegan en los mismos
use cases que los routers FastAPI del área. La simetría Web ↔ MCP
es deliberada: si cambia el comportamiento de un flujo, cambia en
un único sitio.

Lista de tools:
  - tia_sync_disp_preview      → wrapper de POST /api/v1/sync/preview
  - tia_sync_disp_commit       → wrapper de POST /api/v1/sync/commit
  - tia_apply_disp_comentarios → wrapper de
                                 POST /api/v1/alimentacion/aplicar-comentarios-disp
  - tia_upload_excel           → wrapper de POST /api/v1/excel/upload
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: "FastMCP") -> None:
    """Registra las 4 tools del área en el FastMCP shell.

    Esta función es el ``contributes_mcp_tools`` del ``AreaSpec`` del
    área. Se invoca desde ``core/interfaces/mcp_server.py`` al final
    de ``create_mcp_server`` vía
    ``AreaRegistry.discover().for_each("contributes_mcp_tools", mcp=mcp)``.

    Las dependencias (gateway, config_manager, app_state, logger) se
    recuperan del shell vía ``get_mcp_deps()`` (Composition Root
    ligero poblado en ``create_mcp_server``).
    """
    from core.interfaces.mcp_server import get_mcp_deps

    deps = get_mcp_deps()

    # ── 1. tia_sync_disp_preview ────────────────────────────────────
    @mcp.tool()
    async def tia_sync_disp_preview(plc_name: str) -> dict[str, Any]:
        """Calcula el diff completo N_MAX + devices sin tocar TIA.

        PRECONDICIÓN: el operario ya cargó el Excel con
        ``tia_upload_excel`` (si no, el diff se calcula sobre el
        AppState actual, que puede estar vacío).

        Args:
            plc_name: Nombre del PLC en TIA Portal (debe estar
                abierto vía ``tia_attach_portal`` o ``tia_open_new_portal``).

        Returns:
            Shape legacy esperado por la SPA:
            ``{agregados, eliminados, renombrados, todos, nmax, summary}``.
            Cada cambio incluye ``{table, type, uid, numero, actual,
            nuevo, status}``.

        Errores:
            - RuntimeError si TIA no está conectado.
            - FileNotFoundError si no se puede exportar el árbol de
              tags del PLC.
        """
        from areas.alimentacion.application.use_cases.sync_dispositivos_instances import (
            SyncDispositivosInstancesUseCase,
        )

        uc = SyncDispositivosInstancesUseCase(
            gateway=deps["gateway"],
            config_manager=deps["config_manager"],
            state=deps["app_state"],
        )
        return await uc.generar_prevision(plc_name)

    # ── 2. tia_sync_disp_commit ─────────────────────────────────────
    @mcp.tool()
    async def tia_sync_disp_commit(
        plc_name: str, prevision: dict[str, Any]
    ) -> dict[str, Any]:
        """Aplica el sync completo N_MAX + devices en UNA transacción COM.

        El use case recalcula el diff desde el AppState (NO usa la
        ``prevision`` del argumento para evitar race conditions).
        La transacción incluye import_plc_tags_xml (devices add/remove,
        offline) + rename_plc_tag (devices rename, COM online) +
        update_user_constant_value (N_MAX, COM online), bajo un
        ``start_transaction`` / ``end_transaction`` con rollback
        atómico si algo falla.

        Args:
            plc_name: Nombre del PLC en TIA Portal.
            prevision: Preview devuelto por ``tia_sync_disp_preview``
                (informativo, NO se aplica tal cual — ver nota arriba).

        Returns:
            ``{plc_name, operations}`` con el número de operaciones
            aplicadas.

        IMPORTANTE: tras este commit, el operario DEBE invocar
        ``tia_compile_plc`` para que TIA recalcule las dimensiones
        de los DBs (N_MAX cambió).

        Errores:
            - RuntimeError si TIA no está conectado o la transacción falla.
        """
        from areas.alimentacion.application.use_cases.sync_dispositivos_instances import (
            SyncDispositivosInstancesUseCase,
        )

        uc = SyncDispositivosInstancesUseCase(
            gateway=deps["gateway"],
            config_manager=deps["config_manager"],
            state=deps["app_state"],
        )
        return await uc.ejecutar_transaccion(plc_name, prevision)

    # ── 3. tia_apply_disp_comentarios ───────────────────────────────
    @mcp.tool()
    async def tia_apply_disp_comentarios(plc_name: str) -> dict[str, Any]:
        """Aplica comentarios por instancia a los 6 DBs de dispositivos.

        Pieza del flujo post-sync: tras ``tia_sync_disp_commit`` +
        ``tia_compile_plc`` (DBs redimensionados), escribe el
        ``comentario_db`` de cada instancia de los DBs (ED/EA/SA/V/M/M_VF)
        en formato SimaticML y reimporta los bloques bajo UNA sola
        transacción COM con rollback atómico.

        PRECONDICIÓN: AppState con dispositivos cargados
        (``tia_upload_excel`` antes) + N_MAX aplicado (``tia_sync_disp_commit``
        + ``tia_compile_plc`` antes).

        Args:
            plc_name: Nombre del PLC en TIA Portal.

        Returns:
            ``{plc_name, success, applied, operations_executed, summary,
            details, warnings}``.

        Errores:
            - RuntimeError si AppState vacío o TIA no conectado.
        """
        from areas.alimentacion.application.use_cases.sync_comentarios_disp import (
            DispComentariosSyncUseCase,
        )
        from core.application.progress_buffer import get_progress_tracker

        uc = DispComentariosSyncUseCase(
            gateway=deps["gateway"],
            config_manager=deps["config_manager"],
            app_state=deps["app_state"],
            progress=get_progress_tracker(),
        )
        return await uc.apply_comentarios_disp(plc_name)

    # ── 4. tia_upload_excel ─────────────────────────────────────────
    @mcp.tool()
    async def tia_upload_excel(file_path: str) -> dict[str, Any]:
        """Carga un Excel corporativo en el AppState (no toca TIA).

        Parsea el Excel desde ``file_path`` y popula el AppState
        con los dispositivos por tipo. Equivalente al endpoint
        ``POST /api/v1/excel/upload`` pero el path viene del LLM,
        no de un multipart upload.

        Flujo (Fase 5 del plan ``_plan/04_excel_cache_phased_plan.md``):
        usa ``ExcelLoader`` (sync, abre el workbook UNA vez) +
        ``ExcelCacheManager`` (Singleton IT del cache).

        Args:
            file_path: Ruta absoluta al archivo ``.xlsx``.

        Returns:
            ``{ok, summary: {tipo: count}, total_dispositivos, dimensiones}``.

        Errores:
            - FileNotFoundError si la ruta no existe.
            - ValueError si el Excel no tiene la estructura esperada.
        """
        import asyncio

        from areas.alimentacion.infrastructure.cache import ExcelCacheManager
        from areas.alimentacion.infrastructure.loaders import ExcelLoader

        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Excel no encontrado: {file_path}")

        state = deps["app_state"]
        cm = deps["config_manager"]

        # El loader es sync (abre el workbook con openpyxl). Lo
        # envolvemos en ``asyncio.to_thread`` para no bloquear el
        # event loop del MCP server (D3 del plan).
        loader = ExcelLoader(config_manager=cm)
        cache = await asyncio.to_thread(loader.load, path)
        await ExcelCacheManager.put(cache)

        # Back-compat con la SPA y los routers actuales: poblar
        # ``state.dispositivos_<hw>`` desde ``cache.dispositivos``.
        for hw, devices_tuple in cache.dispositivos.items():
            state.set_devices(hw, list(devices_tuple))
        state.dimensiones = cache.n_max
        state.excel_cache = cache
        state.excel_path = cache.excel_path

        # ``summary`` con la shape legacy: ``{tipo_canonica: count}``.
        summary: dict[str, int] = {}
        for hw in cm.list_hw_types_active():
            target = cm.get_excel_target_for(hw)
            if target is None:
                continue
            canonica = target.get("canonical", "")
            if not canonica:
                continue
            devices_tuple = cache.dispositivos.get(hw, ())
            summary[canonica] = len(devices_tuple)

        return {
            "ok": True,
            "summary": summary,
            "total_dispositivos": sum(summary.values()),
            "dimensiones": cache.n_max.to_api_dict(),
        }


__all__ = ["register"]
