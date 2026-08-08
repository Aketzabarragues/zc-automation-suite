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

from application.use_cases.sync_hardware_dimensions import (
    SyncHardwareDimensionsUseCase,
)
from application.use_cases.sync_hardware_instances import (
    SyncHardwareInstancesUseCase,
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

    # Inyección del ConfigManager. Ruta por defecto relativa al CWD;
    # ajustar aquí si se desea apuntar a un config alternativo en tests.
    config_manager = ConfigManager("infrastructure/config.json")

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

    # ── Exportación masiva Simatic Source Documents (.s7dcl) ──────────
    @mcp.tool()
    async def tia_export_blocks_sd(plc_name: str, target_dir: str) -> str:
        """Exporta los bloques de programa del PLC como archivos Simatic Source Documents (.s7dcl).

        ⚠️ **Convención de formato**: el sistema trabaja exclusivamente en
        formato ``.s7dcl`` (SimaticSD). El antiguo sufijo ``.scl`` ha quedado
        obsoleto. El archivo se emite con la extensión nativa que TIA Portal
        V21 produce al usar ``export_format=SimaticSD``.

        Args:
            plc_name:  Nombre exacto del PLC en el proyecto.
            target_dir: Ruta ABSOLUTA del directorio destino. Se crea si no existe.
        """
        path = await gateway.export_blocks_sd(plc_name, target_dir)
        return (
            f"Bloques de '{plc_name}' exportados a '{path}' en formato "
            "Simatic Source Documents (.s7dcl)."
        )

    @mcp.tool()
    async def tia_export_udts_sd(plc_name: str, target_dir: str) -> str:
        """Exporta los UDTs (User Data Types) del PLC como archivos Simatic Source Documents (.s7dcl).

        ⚠️ **Convención de formato**: ver ``tia_export_blocks_sd``.

        Args:
            plc_name:  Nombre exacto del PLC en el proyecto.
            target_dir: Ruta ABSOLUTA del directorio destino. Se crea si no existe.
        """
        path = await gateway.export_udts_sd(plc_name, target_dir)
        return (
            f"UDTs de '{plc_name}' exportados a '{path}' en formato "
            "Simatic Source Documents (.s7dcl)."
        )

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
    async def tia_import_blocks_sd(
        plc_name: str,
        import_dir: str,
        target_folder: str | None = None,
    ) -> str:
        """Importa bloques de programa en formato Simatic Source Documents (.s7dcl) desde el disco al PLC.

        ⚠️ **Convención de formato**: el sistema trabaja exclusivamente
        con ``.s7dcl`` (SimaticSD). Carga el ciclo I/O: junto con
        ``tia_export_blocks_sd``, permite migrar bloques entre proyectos
        o entornos.

        Args:
            plc_name:      Nombre exacto del PLC destino.
            import_dir:    Ruta ABSOLUTA del directorio con los archivos .s7dcl
                           (estructura exportada por tia_export_blocks_sd).
            target_folder: Carpeta destino dentro del PLC (opcional).
        """
        result = await gateway.import_blocks_sd(
            plc_name=plc_name,
            import_dir=import_dir,
            target_folder=target_folder,
        )
        if result is True:
            return (
                f"Bloques importados correctamente al PLC '{plc_name}' "
                f"desde '{import_dir}' en formato .s7dcl."
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
        """Ejecuta múltiples comandos de mutación de TIA Portal en una única transacción atómica con rollback.

        NOTA: La compilación (compile_plc) está prohibida dentro de este lote y debe ejecutarse
        como un paso independiente posterior a la transacción.

        Args:
            operations: Lista de operaciones de mutación o importación. El 'command' interno omite el prefijo 'tia_'.
                        Ejemplo: [{"command": "update_user_constant_value", "args": {"plc_name": "PLC1", "table_name": "TEST", "constant_name": "N_MAX", "new_value": 50}}]
            undo_text: Texto para el historial de TIA Portal.
        """
        result = await gateway.execute_transactional_batch(operations, undo_text)
        return f"Transacción completada con éxito. {result['operations_executed']} comandos ejecutados."

    # ── Caso de uso de alto nivel: sincronización Excel → TIA ────────────
    @mcp.tool()
    async def tia_sync_hardware_dimensions_from_excel(
        plc_name: str, excel_path: str
    ) -> str:
        """Sincroniza las dimensiones de hardware (N_MAX) del PLC desde un Excel.

        Orquesta la lectura offline del Excel, el cruce con el estado actual
        de TIA Portal (exportado a XML), y aplica las diferencias bajo una
        transacción atómica con rollback automático.

        El parseo del Excel y del XML se ejecuta en hilos separados
        (``asyncio.to_thread``) para no bloquear el Event Loop del servidor
        MCP; la inyección en TIA Portal se delega al worker OT.

        Args:
            plc_name:  Nombre exacto del PLC en el proyecto TIA Portal.
            excel_path: Ruta absoluta al archivo Excel corporativo (.xlsx).
        """
        use_case = SyncHardwareDimensionsUseCase(gateway, config_manager)
        result = await use_case.execute(plc_name, excel_path)
        return result["message"]

    @mcp.tool()
    async def tia_sync_hardware_instances_from_excel(
        plc_name: str, excel_path: str
    ) -> str:
        """Sincroniza las instancias de hardware del PLC declaradas en un Excel.

        Procesa el Excel **offline**: lee los DTOs de cada hoja, exporta la
        base actual del PLC (variables y bloques), clona y modifica los
        nodos PlcTag XML y los archivos ``.s7dcl`` (inyecta llamadas entre
        los marcadores ``// AUTO_GEN_START`` / ``// AUTO_GEN_END``) y, por
        último, inyecta el resultado en el autómata mediante un lote
        transaccional ``import_plc_tags_xml`` + ``import_blocks_sd``.

        ⚠️ **Convención de formato**: el sistema procesa bloques
        exclusivamente en formato Simatic Source Documents (``*.s7dcl`` /
        SimaticSD). El antiguo sufijo ``.scl`` ya no es soportado.

        Responsabilidad única: este caso de uso NO toca constantes N_MAX
        (eso es ``tia_sync_hardware_dimensions_from_excel``); solo añade
        instancias nuevas.

        ⚠️ **IMPORTANTE** — Tras el éxito de esta operación, el caller DEBE
        invocar ``tia_compile_plc`` para que TIA Portal asiente el modelo
        de memoria del PLC y los bloques newly-injected queden disponibles
        para su uso. Si la operación devolvió ``operations == 0`` (PLC ya
        sincronizado), la compilación sigue siendo recomendable pero no
        obligatoria.

        Args:
            plc_name:  Nombre exacto del PLC.
            excel_path: Ruta absoluta al archivo Excel corporativo (.xlsx).
                        Convención: cada hoja = un tipo de dispositivo
                        (``DispED``, ``DispV``, ``Motores``, ``Valvulas``…);
                        filas = instancias (columna ``nombre`` requerida).
        """
        use_case = SyncHardwareInstancesUseCase(gateway)
        result = await use_case.execute(plc_name, excel_path)
        # Refuerzo del recordatorio para el LLM: tras inyectar, compilar.
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
