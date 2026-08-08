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

from infrastructure.gateway import TIAProcessGateway


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

    # ── Ciclo de vida del proyecto ──────────────────────────────────────
    @mcp.tool()
    async def tia_open_project(project_file_path: str) -> str:
        """Abre un proyecto de TIA Portal desde una ruta absoluta.

        Si ya hay un proyecto abierto, TIA Portal cerrará la sesión activa
        antes de abrir el nuevo proyecto (comportamiento del portal).

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

        ADVERTENCIA CRÍTICA: project.close() destruye permanentemente todos
        los cambios no guardados (manual V1.2.1, sección 2.37.3). Asegúrate
        de invocar tia_save_project() antes si deseas conservar los cambios.
        """
        await gateway.close_project()
        return "Proyecto cerrado. Los cambios no guardados se han perdido."

    # ── Inspección ──────────────────────────────────────────────────────
    @mcp.tool()
    async def tia_list_plcs(force_refresh: bool = False) -> list[str]:
        """Lista los nombres de los PLCs presentes en el proyecto activo."""
        return await gateway.get_plcs(force_refresh=force_refresh)

    @mcp.tool()
    async def tia_list_blocks(
        plc_name: str, folder_path: str | None = None, force_refresh: bool = False
    ) -> list[str]:
        """Lista los bloques de programa pertenecientes a un PLC."""
        return await gateway.get_blocks(
            plc_name=plc_name, folder_path=folder_path, force_refresh=force_refresh
        )

    # ── Mutación / compilación ──────────────────────────────────────────
    @mcp.tool()
    async def tia_compile_plc(plc_name: str) -> str:
        """Compila el software del PLC en TIA Portal.

        Args:
            plc_name: Nombre exacto del PLC.

        Returns:
            Mensaje humano describiendo el resultado. La compilación puede
            tardar varios minutos en proyectos grandes.

        Semántica del booleano nativo (API V1.2.1 §2.2.11):
          - False -> compilación exitosa (sin errores).
          - True  -> la compilación TIENE errores.
        """
        has_errors = await gateway.compile_plc(plc_name)
        if has_errors is False:
            return f"Compilación del PLC '{plc_name}' exitosa (sin errores)."
        return (
            f"Compilación del PLC '{plc_name}' completada con errores. "
            "Revise la ventana de inspección de TIA Portal para más detalles."
        )

    # ── Exportación masiva SimaticSD ────────────────────────────────────
    @mcp.tool()
    async def tia_export_blocks_scl(plc_name: str, target_dir: str) -> str:
        """Exporta los bloques de programa del PLC como archivos .scl (SimaticSD).

        Args:
            plc_name:  Nombre exacto del PLC en el proyecto.
            target_dir: Ruta ABSOLUTA del directorio destino. Se crea si no existe.
        """
        path = await gateway.export_blocks_scl(plc_name, target_dir)
        return f"Bloques de '{plc_name}' exportados a '{path}' en formato SimaticSD."

    @mcp.tool()
    async def tia_export_udts_scl(plc_name: str, target_dir: str) -> str:
        """Exporta los UDTs (User Data Types) del PLC como archivos .scl (SimaticSD).

        Args:
            plc_name:  Nombre exacto del PLC en el proyecto.
            target_dir: Ruta ABSOLUTA del directorio destino. Se crea si no existe.
        """
        path = await gateway.export_udts_scl(plc_name, target_dir)
        return f"UDTs de '{plc_name}' exportados a '{path}' en formato SimaticSD."

    # ── Exportación masiva SimaticML (XML) ──────────────────────────────
    @mcp.tool()
    async def tia_export_plc_tags_xml(plc_name: str, target_dir: str) -> str:
        """Exporta las tablas de variables (PLC tags) del PLC como XML (SimaticML).

        Args:
            plc_name:  Nombre exacto del PLC en el proyecto.
            target_dir: Ruta ABSOLUTA del directorio destino. Se crea si no existe.
                       La jerarquía de carpetas de las tablas se preserva
                       (keep_folder_structure=True).
        """
        path = await gateway.export_plc_tags_xml(plc_name, target_dir)
        return (
            f"Tablas de variables de '{plc_name}' exportadas a '{path}' "
            "en formato SimaticML (XML)."
        )

    # ── Importación masiva desde disco (cierre del ciclo I/O) ───────────
    @mcp.tool()
    async def tia_import_blocks_scl(
        plc_name: str,
        import_dir: str,
        target_folder: str | None = None,
    ) -> str:
        """Importa bloques de programa (.scl) desde el disco al PLC.

        Cierra el ciclo I/O: junto con tia_export_blocks_scl, permite
        migrar bloques entre proyectos o entornos.

        Args:
            plc_name:      Nombre exacto del PLC destino.
            import_dir:    Ruta ABSOLUTA del directorio con los archivos .scl
                           (estructura exportada por tia_export_blocks_scl).
            target_folder: Carpeta destino dentro del PLC (opcional).
        """
        result = await gateway.import_blocks_scl(
            plc_name=plc_name,
            import_dir=import_dir,
            target_folder=target_folder,
        )
        if result is True:
            return (
                f"Bloques importados correctamente al PLC '{plc_name}' "
                f"desde '{import_dir}'."
            )
        return (
            f"La importación de bloques al PLC '{plc_name}' no reportó éxito "
            "explícito. Revise TIA Portal para más detalles."
        )

    @mcp.tool()
    async def tia_import_plc_tags_xml(
        plc_name: str,
        import_dir: str,
        target_folder: str | None = None,
    ) -> str:
        """Importa tablas de variables (PLC tags) en formato XML al PLC.

        Cierra el ciclo I/O: junto con tia_export_plc_tags_xml, permite
        migrar tablas de variables entre proyectos.

        Args:
            plc_name:      Nombre exacto del PLC destino.
            import_dir:    Ruta ABSOLUTA del directorio con los archivos XML.
            target_folder: Carpeta destino dentro del PLC (opcional).
        """
        result = await gateway.import_plc_tags_xml(
            plc_name=plc_name,
            import_dir=import_dir,
            target_folder=target_folder,
        )
        if result is True:
            return (
                f"Tablas de variables importadas correctamente al PLC '{plc_name}' "
                f"desde '{import_dir}'."
            )
        return (
            f"La importación de tablas de variables al PLC '{plc_name}' no "
            "reportó éxito explícito. Revise TIA Portal para más detalles."
        )

    # ── Bloques granulares ──────────────────────────────────────────────
    @mcp.tool()
    async def tia_export_block(plc_name: str, block_name: str, target_dir: str) -> str:
        """Exporta un único bloque de programa del PLC como archivo .scl (SimaticSD).

        Args:
            plc_name:   Nombre exacto del PLC.
            block_name: Nombre exacto del bloque (ej. "DB2000_ED").
            target_dir: Ruta ABSOLUTA del directorio destino. Se crea si no existe.

        Returns:
            Mensaje confirmando la exportación.

        Raises:
            ValueError: Si target_dir no es una ruta absoluta.
            RuntimeError: Si el bloque no existe en el PLC.
        """
        path = await gateway.export_block(plc_name, block_name, target_dir)
        return f"Bloque '{block_name}' de '{plc_name}' exportado a '{path}'."

    @mcp.tool()
    async def tia_import_block(
        plc_name: str, import_dir: str, target_folder: str | None = None
    ) -> str:
        """Importa un único bloque de programa (.scl) desde disco al PLC.

        Args:
            plc_name:      Nombre exacto del PLC destino.
            import_dir:    Ruta ABSOLUTA del directorio con el .scl del bloque.
            target_folder: Carpeta destino dentro del PLC (opcional).
        """
        result = await gateway.import_block(
            plc_name=plc_name,
            import_dir=import_dir,
            target_folder=target_folder,
        )
        return (
            f"Bloque importado correctamente al PLC '{plc_name}' desde '{import_dir}'."
            if result is True
            else f"La importación del bloque al PLC '{plc_name}' no reportó éxito explícito."
        )

    # ── Tablas de variables granulares ──────────────────────────────────
    @mcp.tool()
    async def tia_export_tag_table(
        plc_name: str, table_name: str, target_dir: str
    ) -> str:
        """Exporta una única PlcTagTable del PLC como XML (SimaticML).

        Args:
            plc_name:   Nombre exacto del PLC.
            table_name: Nombre exacto de la tabla (ej. "2000_Disp_ED").
            target_dir: Ruta ABSOLUTA del directorio destino.
        """
        path = await gateway.export_tag_table(plc_name, table_name, target_dir)
        return f"Tabla '{table_name}' de '{plc_name}' exportada a '{path}'."

    @mcp.tool()
    async def tia_import_tag_table(
        plc_name: str, import_dir: str, target_folder: str | None = None
    ) -> str:
        """Importa una única PlcTagTable (XML) desde disco al PLC.

        Args:
            plc_name:      Nombre exacto del PLC destino.
            import_dir:    Ruta ABSOLUTA del directorio con los archivos XML.
            target_folder: Carpeta destino dentro del PLC (opcional).
        """
        result = await gateway.import_tag_table(
            plc_name=plc_name,
            import_dir=import_dir,
            target_folder=target_folder,
        )
        return (
            f"Tabla importada correctamente al PLC '{plc_name}' desde '{import_dir}'."
            if result is True
            else f"La importación de la tabla al PLC '{plc_name}' no reportó éxito explícito."
        )

    # ── Constantes de usuario (N_MAX, dimensionamiento) ─────────────────
    @mcp.tool()
    async def tia_get_user_constants(
        plc_name: str, table_name: str
    ) -> dict[str, str]:
        """Inspecciona las PlcUserConstant de una tabla de variables.

        Devuelve un mapeo {valor: nombre} donde valor es la representación
        entera del N_MAX u otra constante de dimensionamiento del PLC.

        Args:
            plc_name:   Nombre exacto del PLC.
            table_name: Nombre exacto de la tabla de variables.

        Returns:
            dict[str, str] con pares {valor_int: nombre_constante}.
        """
        return await gateway.get_user_constants(plc_name, table_name)

    @mcp.tool()
    async def tia_update_user_constant_value(
        plc_name: str,
        table_name: str,
        constant_name: str,
        new_value: int,
    ) -> str:
        """Actualiza el valor de una PlcUserConstant (típicamente N_MAX).

        IMPORTANTE: Tras modificar N_MAX, es responsabilidad del caller
        invocar `tia_compile_plc` para que TIA Portal recalcule las
        dimensiones de los DataBlocks afectados. Esta tool no compila
        automáticamente para evitar efectos colaterales no intencionales.

        Args:
            plc_name:      Nombre exacto del PLC.
            table_name:    Nombre exacto de la tabla.
            constant_name: Nombre exacto de la constante (case-sensitive).
            new_value:     Nuevo valor entero.
        """
        result = await gateway.update_user_constant_value(
            plc_name=plc_name,
            table_name=table_name,
            constant_name=constant_name,
            new_value=new_value,
        )
        return (
            f"Constante '{constant_name}' actualizada a {new_value} en '{table_name}'."
            if result is True
            else f"No se pudo actualizar la constante '{constant_name}'."
        )

    @mcp.tool()
    async def tia_update_user_constant_name(
        plc_name: str,
        table_name: str,
        current_name: str,
        new_name: str,
    ) -> str:
        """Renombra una PlcUserConstant sin modificar su valor.

        Args:
            plc_name:     Nombre exacto del PLC.
            table_name:   Nombre exacto de la tabla.
            current_name: Nombre actual de la constante.
            new_name:     Nuevo nombre deseado.
        """
        result = await gateway.update_user_constant_name(
            plc_name=plc_name,
            table_name=table_name,
            current_name=current_name,
            new_name=new_name,
        )
        return (
            f"Constante renombrada de '{current_name}' a '{new_name}' en '{table_name}'."
            if result is True
            else f"No se pudo renombrar la constante '{current_name}'."
        )

    @mcp.tool()
    async def tia_delete_user_constant(
        plc_name: str,
        table_name: str,
        constant_name: str,
    ) -> str:
        """Borra una PlcUserConstant de la tabla de variables.

        ADVERTENCIA: la eliminación es destructiva. Tras borrar, los
        DataBlocks que referenciaban esta constante pueden quedar
        inconsistentes hasta una recompilación.

        Args:
            plc_name:      Nombre exacto del PLC.
            table_name:    Nombre exacto de la tabla.
            constant_name: Nombre exacto de la constante a eliminar.
        """
        result = await gateway.delete_user_constant(
            plc_name=plc_name,
            table_name=table_name,
            constant_name=constant_name,
        )
        return (
            f"Constante '{constant_name}' eliminada de '{table_name}'."
            if result is True
            else f"No se pudo eliminar la constante '{constant_name}'."
        )

    # ── Lotes transaccionales (rollback automático) ────────────────────
    @mcp.tool()
    async def tia_execute_transactional_batch(
        operations: list[dict], undo_text: str = "Batch Operation"
    ) -> str:
        """Ejecuta múltiples comandos de TIA Portal en una única transacción atómica con rollback.

        Permite componer flujos complejos (p. ej. update_constant + compile,
        importar varios DBs secuencialmente, etc.) garantizando que TODAS las
        operaciones se apliquen o NINGUNA lo haga. Si cualquier comando del
        lote falla, el motor OT invoca el rollback automático de TIA Portal,
        restaurando el estado del proyecto previo al lote.

        Cada paso emite su valor de retorno nativo (bool de compile_plc, ruta
        de export_*, etc.) en la lista `details`, permitiendo que la capa de
        presentación o el LLM inspeccionen el estado final de las operaciones
        intermedias (no es una caja negra).

        Importante:
          - Los comandos prohibidos dentro de un lote son: open_project,
            close_project, save_project, list_plcs y execute_transactional_batch.
          - Dentro de la lista, el campo 'command' omite el prefijo 'tia_'
            (uso interno del gateway).

        Args:
            operations: Lista de operaciones. Cada elemento es un dict con:
                          - 'command': str (ej. "import_blocks_scl")
                          - 'args':    dict (argumentos del comando)
                        Ejemplo: [{"command": "import_blocks_scl",
                                   "args": {"plc_name": "PLC1",
                                            "import_dir": "C:/tmp"}}]
            undo_text:  Texto para el historial de Undo de TIA Portal.

        Returns:
            Mensaje humano con el resumen del lote, incluyendo el número de
            operaciones ejecutadas y el detalle de cada paso (paso, comando,
            resultado individual).
        """
        result: dict[str, Any] = await gateway.execute_transactional_batch(
            operations, undo_text
        )
        # Resumen legible para el LLM con el desglose devuelto por el motor OT.
        # Serialización explícita (!r) para que tipos no triviales (None, False,
        # listas) se impriman limpios y sean inequívocos.
        summary_lines: list[str] = [
            f"Transacción completada con éxito. "
            f"{result['operations_executed']} comandos ejecutados.",
            "Detalle por paso:",
        ]
        for step in result.get("details", []):
            summary_lines.append(
                f"  - Paso {step['step']}: {step['command']} -> {step['result']!r}"
            )
        return "\n".join(summary_lines)

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
