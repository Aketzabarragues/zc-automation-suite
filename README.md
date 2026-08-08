# ZC Automation Suite

Herramienta de integración IT/OT para la automatización e inspección de proyectos en **Siemens TIA Portal Openness** utilizando el SDK de **TIA Scripting Python (SIOS 109742322)**.

## Arquitectura del Sistema

El proyecto está diseñado bajo el patrón **Process-per-Call (Subprocess Worker)** para aislar de forma estricta los punteros COM / .NET RCW no thread-safe de la ejecución asíncrona de Python:

- **Capa IT (`main.py`, `infrastructure/gateway.py`):** Servidor asíncrono (`asyncio`) y FastMCP. Backend headless puro: no incluye TUI ni UI interactiva. Gestiona el estado y la caché IT. NUNCA importa `siemens_tia_scripting`.
- **Capa OT (`infrastructure/tia/worker_tia.py`):** Subproceso efímero de ejecución síncrona. Realiza `attach_portal()`, opera sobre TIA Portal, emite un único payload JSON a `stdout` y ejecuta `detach()` antes de morir.

## Requisitos de Entorno

- **Sistema Operativo:** Windows 10 / 11 / Server.
- **Python:** 3.12.x, 3.13.x o 3.14.x (Arquitectura 64-bit).
- **Siemens TIA Portal:** V15.1 en adelante (con Openness instalado y el usuario asignado al grupo *Siemens TIA Openness*).
- **Librería TIA Scripting:** Archivo `.whl` oficial instalado (`pip install siemens_tia_scripting-*.whl`).

## Modos de Ejecución

### 1. Modo Servidor FastMCP (STDIO) — Por defecto
Ejecución estándar por defecto:
```cmd
python main.py
```

Este es el modo **headless**: el binario levanta el servidor FastMCP
sobre STDIO y queda a la espera de tools invocadas por el cliente
LLM/MCP. **No hay UI interactiva** en este repositorio.

### 2. Modo Servidor FastMCP (STDIO) — Explícito
Para conectar con clientes MCP / LLM (ej. Cline, Claude Desktop):

```cmd
python main.py --mcp
```

### 3. Modo Worker OT (Subproceso Aislado)
Invocado internamente por el gateway (requiere payload JSON en STDIN):

```cmd
echo {"command": "list_plcs", "args": {}} | python main.py --worker
```