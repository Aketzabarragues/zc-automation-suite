"""Interfaces Layer - FastMCP Server.

Define la capa de presentación agéntica. Expone las herramientas de TIA Portal
a clientes LLM (Claude, GPT, etc.) consumiendo el `TIAProcessGateway` mediante
inyección de dependencias.

Principios arquitectónicos:
  - El Gateway se inyecta vía `create_mcp_server(gateway)`, permitiendo
    mockearlo en tests unitarios sin lanzar procesos de Siemens.
  - Cada tool declara su contrato (tipos + docstring) para que el LLM
    descubra capacidades vía introspección del schema MCP.
  - La traducción de tipos nativos de Siemens (bool invertido de compile,
    rutas de export, etc.) a mensajes humanos ocurre AQUÍ, no en la capa
    de infraestructura.
"""
from __future__ import annotations

import sys
from typing import Any

from fastmcp import FastMCP

from infrastructure.config_manager import ConfigManager
from infrastructure.gateway import TIAProcessGateway

from application.use_cases.sync_dispositivos_dimensions import (
    SyncDispositivosDimensionsUseCase,
)
from application.use_cases.sync_dispositivos_instances import (
    SyncDispositivosInstancesUseCase,
)


def create_mcp_server(gateway: TIAProcessGateway) -> FastMCP:
    """Construye y configura el servidor FastMCP inyectando el Gateway.

    Args:
        gateway: Instancia del orquestador IT hacia el motor OT.
                  Se inyecta para desacoplar la presentación de la
                  construcción del gateway (facilita mocks en tests).

    Returns:
        Instancia `FastMCP` con todas las herramientas registradas,
        lista para invocar `mcp.run(transport="stdio")`.
    """
    mcp = FastMCP("ZC Automation Suite")

    config_manager = ConfigManager("infrastructure/config.json")

    @mcp.tool()
    async def tia_attach_portal() -> str:
        """Hot-attach a una instancia YA EJECUTÁNDOSE de TIA Portal."""
        ok = await gateway.attach_portal()
        return "Portal acoplado." if ok else "Fallo el acople."

    @mcp.tool()
    async def tia_open_new_portal(project_file_path: str) -> str:
        """Cold start: lanza TIA Portal NUEVO y abre un proyecto.

        Args:
            project_file_path: Ruta absoluta al archivo ``.apxx``.
        """
        ok = await gateway.open_new_portal(project_file_path)
        return (
            f"Portal nuevo abierto con proyecto '{project_file_path}'."
            if ok
            else "Fallo."
        )

    @mcp.tool()
    async def tia_open_project(project_file_path: str) -> str:
        """Abre un proyecto de TIA Portal desde una ruta absoluta.

        PRECONDICIÓN: portal ya conectado (``tia_attach_portal`` o
        ``tia_open_new_portal``).

        Args:
            project_file_path: Ruta absoluta al archivo .apxx del proyecto.
        """
        await gateway.open_project(project_file_path)
        return f"Proyecto abierto correctamente: '{project_file_path}'."

    @mcp.tool()
    async def tia_save_project() -> str:
        """Guarda los cambios pendientes del proyecto activo en TIA Portal."""
        await gateway.save_project()
        return "Proyecto guardado correctamente."

    @mcp.tool()
    async def tia_close_project() -> str:
        """Cierra el proyecto activo en TIA Portal.

        ADVERTENCIA: project.close() destruye permanentemente todos los
        cambios no guardados (manual V1.2.1 §2.37.3).
        """
        await gateway.close_project()
        return "Proyecto cerrado. Los cambios no guardados se han perdido."

    @mcp.tool()
    async def tia_list_plcs(force_refresh: bool = False) -> list[str]:
        """Lista los nombres de los PLCs presentes en el proyecto activo."""
        return await gateway.get_plcs(force_refresh=force_refresh)

    @mcp.tool()
    async def tia_list_blocks(
        plc_name: str,
        folder_path: str | None = None,
        force_refresh: bool = False,
    ) -> list[str]:
        """Lista los bloques de programa pertenecientes a un PLC."""
        return await gateway.get_blocks(
            plc_name=plc_name,
            folder_path=folder_path,
            force_refresh=force_refresh,
        )

    @mcp.tool()
    async def tia_compile_plc(plc_name: str) -> str:
        """Compila el software del PLC en TIA Portal.

        Semántica del booleano nativo (API V1.2.1 §2.2.11):
          - False -> compilación exitosa.
          - True  -> compilación con errores.
        """
        has_errors = await gateway.compile_plc(plc_name)
        if has_errors is False:
            return f"Compilación del PLC '{plc_name}' exitosa."
        return (
            f"Compilación del PLC '{plc_name}' con errores. "
            "Revise TIA Portal."
        )

    @mcp.tool()
    async def tia_export_blocks_sd(plc_name: str, target_dir: str) -> str:
        """Exporta los bloques como archivos Simatic Source Documents (.s7dcl).

        El sistema trabaja exclusivamente con ``.s7dcl`` (SimaticSD).
        """
        path = await gateway.export_blocks_sd(plc_name, target_dir)
        return f"Bloques exportados a '{path}' en formato .s7dcl."

    @mcp.tool()
    async def tia_export_udts_sd(plc_name: str, target_dir: str) -> str:
        """Exporta los UDTs como archivos Simatic Source Documents (.s7dcl)."""
        path = await gateway.export_udts_sd(plc_name, target_dir)
        return f"UDTs exportados a '{path}' en formato .s7dcl."

    @mcp.tool()
    async def tia_export_plc_tags_xml(plc_name: str, target_dir: str) -> str:
        """Exporta las tablas de variables (PLC tags) como XML (SimaticML)."""
        path = await gateway.export_plc_tags_xml(plc_name, target_dir)
        return f"Tablas exportadas a '{path}' en formato SimaticML (XML)."

    @mcp.tool()
    async def tia_import_blocks_sd(
        plc_name: str,
        import_dir: str,
        target_folder: str | None = None,
    ) -> str:
        """Importa bloques ``.s7dcl`` desde disco al PLC."""
        result = await gateway.import_blocks_sd(
            plc_name=plc_name,
            import_dir=import_dir,
            target_folder=target_folder,
        )
        return (
            "Bloques importados correctamente."
            if result
            else "Falló la importación."
        )

    @mcp.tool()
    async def tia_import_plc_tags_xml(
        plc_name: str,
        import_dir: str,
        target_folder: str | None = None,
    ) -> str:
        """Importa tablas de variables (XML) desde disco al PLC."""
        result = await gateway.import_plc_tags_xml(
            plc_name=plc_name,
            import_dir=import_dir,
            target_folder=target_folder,
        )
        return (
            "Tablas importadas correctamente."
            if result
            else "Falló la importación."
        )

    @mcp.tool()
    async def tia_export_block(
        plc_name: str, block_name: str, target_dir: str
    ) -> str:
        """Exporta un único bloque como .s7dcl."""
        path = await gateway.export_block(plc_name, block_name, target_dir)
        return f"Bloque '{block_name}' exportado a '{path}'."

    @mcp.tool()
    async def tia_import_block(
        plc_name: str,
        import_dir: str,
        target_folder: str | None = None,
    ) -> str:
        """Importa un único bloque ``.s7dcl`` desde disco al PLC."""
        result = await gateway.import_block(
            plc_name=plc_name,
            import_dir=import_dir,
            target_folder=target_folder,
        )
        return (
            "Bloque importado correctamente."
            if result
            else "Falló la importación."
        )

    @mcp.tool()
    async def tia_export_tag_table(
        plc_name: str, table_name: str, target_dir: str
    ) -> str:
        """Exporta una única PlcTagTable como XML (SimaticML)."""
        path = await gateway.export_tag_table(plc_name, table_name, target_dir)
        return f"Tabla '{table_name}' exportada a '{path}'."

    @mcp.tool()
    async def tia_import_tag_table(
        plc_name: str,
        import_dir: str,
        target_folder: str | None = None,
    ) -> str:
        """Importa una única PlcTagTable (XML) desde disco al PLC."""
        result = await gateway.import_tag_table(
            plc_name=plc_name,
            import_dir=import_dir,
            target_folder=target_folder,
        )
        return (
            "Tabla importada correctamente."
            if result
            else "Falló la importación."
        )

    @mcp.tool()
    async def tia_get_user_constants(
        plc_name: str, table_name: str
    ) -> dict[str, str]:
        """Inspecciona PlcUserConstant. Devuelve ``{valor_int: nombre}``."""
        return await gateway.get_user_constants(plc_name, table_name)

    @mcp.tool()
    async def tia_update_user_constant_value(
        plc_name: str,
        table_name: str,
        constant_name: str,
        new_value: int,
    ) -> str:
        """Actualiza el valor de una PlcUserConstant (típicamente N_MAX).

        Tras modificar N_MAX, el caller DEBE invocar ``tia_compile_plc``
        para que TIA Portal recalcule las dimensiones de los DataBlocks.
        """
        result = await gateway.update_user_constant_value(
            plc_name=plc_name,
            table_name=table_name,
            constant_name=constant_name,
            new_value=new_value,
        )
        return "Constante actualizada." if result else "Falló la actualización."

    @mcp.tool()
    async def tia_update_user_constant_name(
        plc_name: str,
        table_name: str,
        current_name: str,
        new_name: str,
    ) -> str:
        """Renombra una PlcUserConstant sin modificar su valor."""
        result = await gateway.update_user_constant_name(
            plc_name=plc_name,
            table_name=table_name,
            current_name=current_name,
            new_name=new_name,
        )
        return "Constante renombrada." if result else "Falló el renombrado."

    @mcp.tool()
    async def tia_delete_user_constant(
        plc_name: str,
        table_name: str,
        constant_name: str,
    ) -> str:
        """Borra una PlcUserConstant de la tabla de variables."""
        result = await gateway.delete_user_constant(
            plc_name=plc_name,
            table_name=table_name,
            constant_name=constant_name,
        )
        return "Constante eliminada." if result else "Falló la eliminación."

    @mcp.tool()
    async def tia_execute_transactional_batch(
        operations: list[dict], undo_text: str = "Batch Operation"
    ) -> str:
        """Ejecuta múltiples comandos bajo una transacción atómica con rollback.

        NOTA: ``compile_plc`` está prohibido dentro del lote.
        """
        result = await gateway.execute_transactional_batch(operations, undo_text)
        return (
            f"Transacción completada: {result['operations_executed']} "
            "comandos ejecutados."
        )

    @mcp.tool()
    async def tia_sync_dispositivos_dimensions_from_excel(
        excel_path: str,
    ) -> str:
        """Sincroniza dimensiones (N_MAX) desde un Excel al AppState global.

        Lee el Excel corporativo y actualiza el ``AppState.dimensiones``.
        La inyección real contra TIA Portal ocurre en el siguiente paso
        (sincronización de instancias).

        Args:
            excel_path: Ruta absoluta al archivo Excel corporativo (.xlsx).
        """
        _ = config_manager  # reservado para futuro (cross-validation)
        use_case = SyncDispositivosDimensionsUseCase()
        result = await use_case.execute(excel_path)
        return result["message"]

    @mcp.tool()
    async def tia_sync_dispositivos_instances_from_excel(
        plc_name: str, excel_path: str
    ) -> str:
        """Sincroniza instancias de dispositivos (PlcTag + .s7dcl) desde un Excel.

        Procesa el Excel offline: lee los DTOs, exporta la base del PLC,
        clona/modifica nodos PlcTag XML y archivos ``.s7dcl`` (inyecta
        llamadas entre marcadores ``// AUTO_GEN_*``), e inyecta el
        resultado mediante un lote transaccional con motor Diff
        híbrido (XML para adds/drops, COM para renames).

        Responsabilidad única: NO toca constantes N_MAX (eso es
        ``tia_sync_dispositivos_dimensions_from_excel``); solo añade
        instancias nuevas.

        Tras el éxito, el caller DEBE invocar ``tia_compile_plc`` para
        asentar el modelo de memoria del PLC.

        Args:
            plc_name:  Nombre exacto del PLC.
            excel_path: Ruta absoluta al Excel. Convención: cada hoja =
                        un tipo de dispositivo (``DispED``, ``DispV``, ...);
                        filas = instancias (columna ``nombre`` requerida).
        """
        use_case = SyncDispositivosInstancesUseCase(gateway)
        result = await use_case.execute(plc_name, excel_path)
        return (
            f"{result['message']} "
            "Recuerda invocar tia_compile_plc a continuación para asentar "
            "el modelo de memoria del PLC."
        )

    return mcp


def run_mcp_stdio() -> None:
    """Instancia y arranca el servidor MCP en modo STDIO.

    Punto de entrada para el binario en modo presentación IT. Construye
    el Gateway por defecto (timeouts de producción) y delega en el
    factory `create_mcp_server` para mantener la separación de capas.
    """
    try:
        gateway = TIAProcessGateway()
        mcp = create_mcp_server(gateway)
        mcp.run(transport="stdio")
    except Exception as e:
        print(f"Error fatal en servidor MCP: {e}", file=sys.stderr)
        sys.exit(1)
