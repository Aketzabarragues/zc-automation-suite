# ZC Automation Suite

> Herramienta de integración IT/OT para la automatización e inspección de proyectos en **Siemens TIA Portal Openness** mediante el SDK oficial **TIA Scripting Python (SIOS 109742322)**.

![Arquitectura](https://img.shields.io/badge/arquitectura-Process--per--Call-blue) ![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-yellow) ![TIA Portal](https://img.shields.io/badge/TIA%20Portal-V15.1%2B-green) ![Licencia](https://img.shields.io/badge/licencia-MIT-lightgrey)

---

##  Tabla de Contenidos

1. [Visión General](#-visión-general)
2. [Requisitos del Entorno](#-requisitos-del-entorno)
3. [Modos de Ejecución](#-modos-de-ejecución)
4. [Arquitectura del Sistema](#-arquitectura-del-sistema)
5. [Estructura del Repositorio](#-estructura-del-repositorio)
6. [Descripción Archivo por Archivo](#-descripción-archivo-por-archivo)
7. [Patrones de Uso](#-patrones-de-uso)
8. [Configuración Dinámica](#-configuración-dinámica)
9. [Build y Despliegue](#-build-y-despliegue)
10. [Testing Manual](#-testing-manual)
11. [Convenciones de Desarrollo](#-convenciones-de-desarrollo)
12. [Troubleshooting](#-troubleshooting)
13. [Licencia](#-licencia)

---

## 🎯 Visión General

ZC Automation Suite es una capa de integración que conecta **aplicaciones asíncronas en Python** (clientes MCP/LLM, servidores web FastAPI) con el entorno **síncrono y nativo de TIA Portal Openness** (COM/.NET).

El proyecto resuelve el problema clásico de TIA Openness: la **incompatibilidad entre el modelo asíncrono de Python y el modelo síncrono COM** de Siemens (los punteros RCW de .NET **no son thread-safe**). Para evitar errores de tipo `COMException` o corromper el RCW, ZC Automation Suite implementa el patrón **Process-per-Call**: cada comando contra TIA Portal se ejecuta en un **subproceso efímero** que nace, ejecuta y muere, comunicándose con el proceso padre únicamente vía **JSON sobre `stdin`/`stdout`**.

### Características clave

- 🧩 **Arquitectura en capas** estricta: `core` (dominio puro) ← `infrastructure` ← `application` ← `interfaces`.
- 🔌 **Doble adaptador**: misma lógica de negocio servida vía **FastMCP** (LLM) y vía **FastAPI** (humano vía navegador).
- ️ **Lotes transaccionales con rollback automático**: si una operación falla a mitad de un lote, TIA Portal revierte todas las anteriores (`start_transaction` / `end_transaction(rollback=True)`).
- 🔁 **Idempotencia** en modificadores offline XML/SCL: aplicar dos veces el mismo cambio no duplica instancias.
- 📦 **Build `--onefile`** con PyInstaller, incluyendo el `.pyd` nativo de Siemens en el bundle sin contaminar el repositorio.
-  **Tipado fuerte** end-to-end: dataclasses `frozen=True` + Protocols (`IHardwareDevice`) desde el Excel hasta el PLC.

---

## ⚙️ Requisitos del Entorno

| Componente | Requisito |
|---|---|
| **Sistema Operativo** | Windows 10 / 11 / Server (64-bit). Solo Windows: TIA Openness requiere COM. |
| **Python** | **3.12.x, 3.13.x o 3.14.x** (64-bit). Sin soporte para 3.11 ni anteriores. |
| **Siemens TIA Portal** | V15.1 o superior con Openness instalado. |
| **Permisos Windows** | El usuario que ejecuta ZC debe pertenecer al grupo `Siemens TIA Openness` (gestionado por `Openness Security Dialog`). |
| **Librería TIA Scripting** | Archivo `.whl` oficial: `pip install siemens_tia_scripting-*.whl`. |
| **Dependencias Python** | Ver `requirements.txt`: `fastmcp`, `mcp`, `pyinstaller`, `fastapi`, `uvicorn`, `openpyxl`. |

### Instalación rápida

```cmd
:: 1. Crear y activar un entorno virtual
python -m venv .venv
.venv\Scripts\activate

:: 2. Instalar dependencias + la wheel oficial de Siemens
pip install -r requirements.txt
pip install siemens_tia_scripting-*.whl

:: 3. Verificar
python -c "import siemens_tia_scripting; print('OK')"
```

---

## 🚀 Modos de Ejecución

El binario `main.py` actúa como **Composition Root**: enruta según flags CLI.

### 1. Modo Servidor FastMCP (STDIO) — por defecto

```cmd
python main.py
:: Equivalente a:
python main.py --mcp
```

Arranca el servidor **FastMCP** sobre STDIN/STDOUT. Backend **headless** puro (sin TUI). Espera invocaciones de tools desde clientes LLM/MCP (Cline, Claude Desktop, etc.). **Este es el modo principal de uso**.

### 2. Modo Worker OT (subproceso aislado)

```cmd
echo {"command": "list_plcs", "args": {}} | python main.py --worker
```

Este modo **NO se invoca manualmente en producción**; el `TIAProcessGateway` lo lanza internamente por cada comando. Útil para depuración directa.

### 3. Modo Servidor Web de Pruebas (FastAPI)

```cmd
python test_web_server.py
:: Levanta http://127.0.0.1:8000 con un formulario para enviar payloads JSON al worker
```

Útil para **testing manual** sin necesidad de un cliente MCP. Ver [sección dedicada](#-testing-manual).

### 4. Modo Ejecutable Empaquetado (PyInstaller)

```cmd
python build_exe.py
:: Genera dist\zc_automation_suite.exe con el .pyd de Siemens embebido
:: Ejecución idéntica al modo FastMCP:
dist\zc_automation_suite.exe
```

---

## 🏛️ Arquitectura del Sistema

### Diagrama de capas y dependencias

```
┌─────────────────────────────────────────────────────────────┐
│                       interfaces/                          │  ← Capa de Presentación
│   ┌────────────────                                       │     (FastMCP, FastAPI)
│   │  mcp_server.py │                                       │
│   └────────┬───────┘                                       │
│            │ usa                                            │
│   ┌────────▼─────────┐                                     │
│   │ application/     │                                     │  ← Capa de Aplicación
│   │  use_cases/      │   (orquestación async de flujos)    │     (Casos de Uso)
│   └────────┬─────────┘                                     │
│            │ usa                                            │
│   ┌────────▼──────────────────────────────┐                │
│   │     infrastructure/                    │                │  ← Capa de Infraestructura
│   │                                       │                │
│   │  gateway.py ──► subprocess --worker ───────► worker_tia.py │  (motor OT)
│   │  config_manager.py                       │            │     │
│   │  parsers/  xml/  sd/  alimentacion/       │            │     │
│   └────────┬──────────────────────────────┘                │
│            │ usa (solo modelos)                              │
│   ┌────────▼─────────┐                                     │
│   │     core/         │                                     │  ← Capa de Dominio
│   │  alimentacion/    │                                     │     (dataclasses frozen,
│   │   models/         │                                     │      Protocol, lógica pura)
│   └──────────────────┘                                     │
└─────────────────────────────────────────────────────────────┘

Dirección de dependencias: ↑ solo hacia arriba. NUNCA hacia abajo.
```

### Patrón Process-per-Call (subprocess worker)

```
                   PROCESO PADRE (IT)                       PROCESO HIJO (OT)
              ┌────────────────────────────┐              ┌───────────────────────────┐
              │ main.py (asyncio/FastMCP)  │              │ main.py --worker          │
              │                            │              │                           │
              │ gateway._dispatch_worker   │  ──stdin──►  │ 1. set_logging(off)       │
              │     (asyncio.subprocess)   │  ──stdout──► │ 2. attach_portal()        │
              │                            │              │ 3. attach.get_project()   │
              │ Lee la ÚLTIMA línea JSON   │              │ 4. handler(portal, ...)   │
              │ (filtro anti-interferencia)│              │ 5. print(json.dumps(...)) │
              │                            │              │ 6. detach() en finally    │
              │ Caché en memoria IT        │  ◄──stderr── │    (logs/trazas C++)      │
              └────────────────────────────┘              └───────────────────────────┘
                                          ~50-200ms por comando
```

**Reglas ineludibles** del worker OT:
1. `siemens_tia_scripting.set_logging(path="worker_openness.log", console=False)` INMEDIATAMENTE al arrancar.
2. `attach_portal()` antes de cualquier operación.
3. `get_project()` valida el proyecto activo.
4. `detach()` OBLIGATORIAMENTE en `finally`.
5. **Nunca** retornar objetos nativos (Plc, ProgramBlock): mapear a primitivos Python.

### Contrato IPC (JSON)

**Input** (por STDIN, una sola línea):
```json
{"command": "list_plcs", "args": {}}
```

**Output** (por STDOUT, una sola línea final):
```json
{"ok": true, "result": ["PLC1", "PLC2"]}
```

**Errores** (STDOUT, `ok=false`):
```json
{"ok": false, "error": "RuntimeError: Timeout tras 45s..."}
```

Los logs internos (C++, .NET, trazas) van a STDERR y son ignorados por el padre.

---

## 📂 Estructura del Repositorio

```
zc-automation-suite/
├── .clinerules                  # Directrices arquitectónicas (reglas de oro)
├── .gitignore                   # Exclusiones estándar Python + custom (_legacy/, .build_cache/)
├── .repomixignore               # Exclusiones para repomix (documentación AI)
├── LICENSE                      # MIT License
├── README.md                    # Este archivo
├── build_exe.py                 # Orquestador PyInstaller (.pyd staging)
├── main.py                      # Composition Root CLI (--mcp / --worker)
├── repomix-output.xml           # Snapshot del repo para consumo AI
├── requirements.txt             # Dependencias Python (fastmcp, mcp, pyinstaller, ...)
├── run_repomix.bat              # Helper Windows: regenera repomix-output.xml
├── test_web_server.py           # FastAPI test harness sobre el worker OT
│
├── application/                 # ──── Capa de Aplicación ────
│   ├── __init__.py              # Docstring del paquete
│   └── use_cases/
│       ├── sync_hardware_dimensions.py  # Caso de uso: Excel → N_MAX
│       ├── sync_hardware_instances.py   # Caso de uso: Excel → PlcTag + .s7dcl
│       └── diff_constants.py            # Motor puro de diffs (Update/Delete/Create)
│
├── core/                        # ──── Capa de Dominio (pura) ────
│   ├── __init__.py
│   ├── models/                  # Scaffolding (los reales viven en _legacy_reference/)
│   │   └── __init__.py
│   └── alimentacion/            # Subdominio: Departamento de Alimentación
│       ├── __init__.py
│       └── models/
│           ├── __init__.py      # Re-exports
│           ├── hardware.py      # Protocol IHardwareDevice + 5 dataclasses frozen
│           └── software.py      # Proceso, Alarma, PInt, PReal (con @property)
│
├── infrastructure/              # ──── Capa de Infraestructura ────
│   ├── __init__.py
│   ├── gateway.py               # TIAProcessGateway: async subprocess dispatcher
│   ├── config_manager.py        # Lee infrastructure/config.json
│   ├── config.json              # Mapeo dinámico: nombre_hoja_excel → tabla_PLC
│   │
│   ├── parsers/                 # Parsers offline (no tocan TIA)
│   │   ├── __init__.py
│   │   └── excel_parser.py      # ExcelParser genérico (extraer_dimensiones + DTOs)
│   │
│   ├── xml/                     # Manipulación SimaticML (XML)
│   │   ├── __init__.py
│   │   ├── modifiers.py         # TagTableModifier (clona nodos PlcTag)
│   │   └── tag_table_parser.py  # SimaticMLTagParser (extrae PlcUserConstant)
│   │
│   ├── sd/                      # Manipulación Simatic Source Documents (.s7dcl)
│   │   ├── __init__.py
│   │   └── modifiers.py         # SDModifier (inserta llamadas entre marcadores)
│   │
│   ├── alimentacion/            # Subdominio: Parsers tipados de alimentación
│   │   ├── __init__.py
│   │   └── parsers/
│   │       ├── __init__.py
│   │       └── alimentacion_excel_parser.py  # AlimentacionExcelParser (compone ExcelParser)
│   │
│   └── tia/                     # ──── Motor OT (subprocess) ────
│       ├── __init__.py
│       └── worker_tia.py        # Único archivo que importa siemens_tia_scripting
│
└── interfaces/                  # ──── Capa de Presentación ────
    ├── __init__.py
    └── mcp_server.py            # FastMCP factory: 22+ tools + ConfigManager + 2 use cases
```

---

## 📖 Descripción Archivo por Archivo

Esta sección documenta el propósito, API pública y relaciones de cada archivo del repositorio, organizado por capa.

### 📁 6.1 Archivos de raíz

#### `main.py` (69 líneas) — *Composition Root*

Enrutador CLI delgado. Según el flag pasado, delega a uno de los dos modos:

- **`--worker`** → llama a `infrastructure.tia.worker_tia.main()` (modo OT, usado internamente por el gateway).
- **`(default)` o `--mcp`** → llama a `interfaces.mcp_server.run_mcp_stdio()` (modo presentación FastMCP).

**Importaciones tardías**: importa los módulos pesados solo cuando se invocan (ej. `fastmcp` solo se carga si se entra en modo MCP), minimizando el tiempo de arranque en modo `--worker`.

**API**: `parse_args()`, `run_worker_mode()`, `run_mcp_mode()`, `main()`.

---

#### `requirements.txt` (6 líneas) — *Dependencias Python*

```
fastmcp>=0.1.0    # Framework MCP agéntico
mcp>=1.0.0        # SDK MCP base
pyinstaller>=6.0.0  # Compilación a ejecutable
fastapi>=0.100.0  # Servidor web de testing (test_web_server.py)
uvicorn>=0.20.0  # ASGI server para FastAPI
openpyxl>=3.0.0   # Lectura/escritura de Excel (.xlsx)
```

Nota: **`siemens_tia_scripting` NO está aquí** — se instala manualmente desde la `.whl` oficial porque es un binario nativo propietario.

---

#### `build_exe.py` (117 líneas) — *Compilador PyInstaller*

Genera un ejecutable `.exe` standalone (`dist/zc_automation_suite.exe`) que incluye el `.pyd` nativo de Siemens.

**Restricciones**:
- Cero código sucio en el repo: el `.pyd` se staga en un **directorio temporal** (`tempfile.mkdtemp(prefix="zc_tia_pyd_")`) y se borra en `finally`.
- Staging con nombre canónico: si el `.pyd` tiene ABI tag (ej. `cp314-win_amd64.pyd`), se renombra a `siemens_tia_scripting.pyd` para que el worker lo encuentre dentro de `_MEIPASS`.

**Pipeline**:
1. `ensure_pyinstaller()` → valida que PyInstaller esté instalado.
2. `resolve_pyd_source()` → usa `importlib.util.find_spec()` para localizar el `.pyd` en el venv.
3. `stage_pyd_with_canonical_name()` → copia a `tempfile.mkdtemp()` con nombre canónico.
4. `build()` → invoca `PyInstaller --onefile --add-data <pyd>.`.
5. `finally` → `shutil.rmtree()` del staging.

---

#### `test_web_server.py` (141 líneas) — *Test Harness FastAPI*

Servidor web de **debugging manual** sobre `127.0.0.1:8000`. Ofrece una UI HTML que permite enviar payloads JSON directamente al subproceso OT.

**Endpoints**:
- `GET /` → sirve un formulario HTML con textarea + botón "Ejecutar Comando".
- `POST /api/v1/worker` → recibe un payload JSON, lanza el worker via `asyncio.create_subprocess_exec`, devuelve el JSON parseado.

Útil para probar el worker sin tener un cliente MCP real configurado.

---

#### `run_repomix.bat` (10 líneas) — *Helper Windows*

Script `.bat` trivial que ejecuta `npx repomix` para regenerar `repomix-output.xml` (snapshot del repo en formato XML apto para consumo por IAs).

---

#### `.clinerules` (37 líneas) — *Directrices Arquitectónicas*

Reglas de oro inmutables del proyecto. Resumen:

1. **Process-per-Call** obligatorio (prohibido importar `siemens_tia_scripting` en IT).
2. **Ciclo de vida del worker**: `set_logging` → `attach_portal` → `get_project` → `detach` en `finally`.
3. **No retener estado OT**: nunca retornar objetos nativos; mapear a primitivos.
4. **API oficial V1.2.1**: usar `export_format=SimaticSD` y consultar `search_tia_manual` ante dudas.
5. **No copiar patrones legacy**: el código de `_legacy_reference/` se reutiliza solo para lógica de negocio puro (parsers Excel/XML).
6. **Python moderno**: tipado estricto, PEP 8, `asyncio.to_thread` para no bloquear el Event Loop.

---

#### `.gitignore` (223 líneas) — *Exclusiones estándar + custom*

Incluye las exclusiones estándar de Python (`__pycache__/`, `*.py[cod]`, etc.) más exclusiones custom al final:
```
# Custom exclusions
_legacy_reference/
temp_*/
.build_cache/
```

---

#### `.repomixignore` (29 líneas) — *Exclusiones para IAs*

Específicas para `repomix-output.xml`: caches Python, artefactos de build, vendored binaries (`lib/siemens_tia_scripting-*.whl`), código legacy.

---

#### `LICENSE` (21 líneas) — *MIT License*

Copyright (c) 2026 Aketzabarragues.

---

### 📁 6.2 Capa de Dominio — `core/`

#### `core/__init__.py` (11 líneas)

Declara que la capa es **estrictamente pura**: no puede importar `siemens_tia_scripting`, ni nada de `infrastructure/` o `interfaces/`. Solo stdlib y tipos primitivos.

---

#### `core/models/__init__.py` (9 líneas)

**SCAFFOLDING**: placeholder para los modelos originales del proyecto antiguo (`_legacy_reference/`). Contiene solo el docstring explicativo.

---

#### `core/alimentacion/__init__.py` (11 líneas) — *Subdominio Alimentación*

Documenta el subdominio "Alimentación" (departamento de producción físico). Establece las tres restricciones del paquete: sin `siemens_tia_scripting`, sin `Any`, sin openpyxl.

---

#### `core/alimentacion/models/__init__.py` (37 líneas)

Re-exports del subdominio:
- **Protocol + Hardware**: `IHardwareDevice`, `DispED`, `DispEA`, `DispV`, `Motor`, `Valvula`.
- **Software (lógica pura)**: `Proceso`, `Alarma`, `PInt`, `PReal`.

Define `__all__` para que `from core.alimentacion.models import *` exponga la API pública.

---

#### `core/alimentacion/models/hardware.py` (87 líneas) — *Modelos de hardware*

**Propósito**: definir el contrato `IHardwareDevice` y las 5 dataclasses `frozen=True` que lo satisfacen estructuralmente (duck typing).

**API pública**:

```python
@runtime_checkable
class IHardwareDevice(Protocol):
    nombre: str
    direccion: str

@dataclass(frozen=True)
class DispED:   nombre: str; direccion: str; db_nombre: str = ""
@dataclass(frozen=True)
class DispEA:   nombre: str; direccion: str; db_nombre: str = ""
@dataclass(frozen=True)
class DispV:    nombre: str; direccion: str
@dataclass(frozen=True)
class Motor:    nombre: str; direccion: str; tipo: str = ""
@dataclass(frozen=True)
class Valvula:  nombre: str; direccion: str; tipo: str = ""
```

**Decisión clave**: usar `Protocol @runtime_checkable` (no herencia) permite que `isinstance(disp, IHardwareDevice)` funcione sin acoplar las dataclasses a una clase base. Los modificadores acceden a atributos vía `getattr(dto, "nombre", "")` — duck typing.

---

#### `core/alimentacion/models/software.py` (55 líneas) — *Modelos de software*

**Propósito**: definir dataclasses `frozen=True` para entidades lógicas del proceso (no se inyectan como PlcTag directos).

**API pública**:
```python
@dataclass(frozen=True)
class Proceso:  nombre: str; descripcion: str = ""
    @property def db_alm_nombre(self) -> str: ...     # "<nombre>_ALM"

@dataclass(frozen=True)
class Alarma:   nombre: str; prioridad: int = 0; mensaje: str = ""
    @property def es_critica(self) -> bool: ...     # prioridad >= 16

@dataclass(frozen=True)
class PInt:     nombre: str; valor: int = 0
@dataclass(frozen=True)
class PReal:    nombre: str; valor: float = 0.0
```

**Propiedades derivadas** (`@property`): encapsulan reglas de negocio (convención de nombres de DB, umbral de criticidad de alarmas) directamente en el modelo, sin acoplar lógica externa.

---

### 📁 6.3 Capa de Infraestructura — `infrastructure/`

#### `infrastructure/__init__.py` (1 línea)

Docstring mínimo del paquete.

---

#### `infrastructure/gateway.py` (408 líneas) — *Orquestador IT-OT*

**Propósito**: el ÚNICO módulo que sabe cómo lanzar el subproceso OT. Toda la comunicación con TIA Portal pasa por aquí.

**Clase principal**: `TIAProcessGateway`

**API pública** (~20 métodos):
- **Ciclo de vida del proyecto**: `open_project()`, `save_project()`, `close_project()`.
- **Inspección con caché**: `get_plcs(force_refresh=False)`, `get_blocks(plc_name, folder_path, force_refresh=False)`.
- **Compilación**: `compile_plc(plc_name) -> bool` (invierte la semántica del booleano nativo de Siemens).
- **Export SimaticSD (.s7dcl)**: `export_blocks_sd()`, `export_udts_sd()`.
- **Export SimaticML (XML)**: `export_plc_tags_xml()`, `export_tag_table(plc_name, table_name)`.
- **Import**: `import_blocks_sd()`, `import_plc_tags_xml()`, `import_block()`, `import_tag_table()`.
- **Constantes N_MAX**: `get_user_constants()`, `update_user_constant_value()`, `update_user_constant_name()`, `delete_user_constant()`.
- **Lotes transaccionales**: `execute_transactional_batch(operations, undo_text)`.
- **Caché**: `clear_cache()`.

**Mecanismo clave**: `_dispatch_worker(command, args)` lanza `asyncio.create_subprocess_exec` con `sys.executable -u main.py --worker`, envía el payload JSON por STDIN, lee la ÚLTIMA línea `{...}` de STDOUT como respuesta (filtro contra interferencias), aplica timeout de 45s.

**Resolución del binario**: detecta `sys.frozen` (PyInstaller) vs desarrollo y ajusta los argumentos del subproceso.

**Caché IT**: `get_plcs` y `get_blocks` cachean respuestas en memoria con claves específicas; se invalidan automáticamente al `open_project` o `update_user_constant_value`.

---

#### `infrastructure/config_manager.py` (59 líneas) — *Gestor de configuración*

**Propósito**: leer `infrastructure/config.json` y exponer el mapeo entre tipos de dispositivo del Excel y nombres reales de tablas en TIA Portal. Evita hardcodear nombres como `"000_Config_Dispositivos"` en los casos de uso.

**API pública**:
```python
class ConfigManager:
    def __init__(config_path="infrastructure/config.json")
    def get_global_config_table_name() -> str
        # Fallback defensivo: "000_Config_Dispositivos"
```

**Garantías**: lanza `FileNotFoundError` si el archivo no existe; deja propagar `json.JSONDecodeError` si está malformado.

---

#### `infrastructure/config.json` (4 líneas)

```json
{
  "_comment": "SCAFFOLDING - Portar config real desde _legacy_reference/. Por ahora solo contiene el mapeo mínimo que el caso de uso necesita para arrancar.",
  "global_config_table_name": "000_Config_Dispositivos"
}
```

Estructura minimalista con `_comment` para documentación y `global_config_table_name` como única clave requerida actualmente.

---

#### `infrastructure/tia/__init__.py` (1 línea)

Docstring del subpaquete TIA (motor OT).

---

#### `infrastructure/tia/worker_tia.py` (756 líneas) — *Motor OT (subprocess)* ⭐

**EL ÚNICO ARCHIVO DEL PROYECTO QUE IMPORTA `siemens_tia_scripting`**.

**Ciclo de vida** (en `main()`):
1. Carga dinámica del wrapper vía `_load_siemens_wrapper()` (sys.path + PATH + os.add_dll_directory).
2. `ts.set_logging(path="worker_openness.log", console=False)` — silencia stdout C++.
3. Lee payload JSON de STDIN.
4. Valida `command` ∈ `COMMAND_REGISTRY`.
5. `ts.attach_portal(portal_mode=ts.Enums.PortalMode.AnyUserInterface)`.
6. Despacha al handler.
7. Emite JSON final a STDOUT.
8. `finally`: `portal.detach()` (libera RCW de .NET).

**COMMAND_REGISTRY** — 23 comandos agrupados por categoría:

| Categoría | Comandos |
|---|---|
| Ciclo de vida | `open_project`, `save_project`, `close_project` |
| Inspección | `list_plcs`, `list_blocks` |
| Compilación | `compile_plc` (semántica booleana invertida) |
| Export SimaticSD | `export_blocks_sd`, `export_udts_sd` |
| Export SimaticML | `export_plc_tags_xml` |
| Import | `import_blocks_sd`, `import_plc_tags_xml`, `import_block`, `import_tag_table` |
| Constantes N_MAX | `get_user_constants`, `update_user_constant_value`, `update_user_constant_name`, `delete_user_constant` |
| Lotes transaccionales | `execute_transactional_batch` |

**Lotes transaccionales** (`_cmd_execute_transactional_batch`):
- Llama `project.start_transaction(undo_text, dialog_text)`.
- Ejecuta cada comando del lote.
- Captura cada `result` en `details: [{step, command, result}, ...]`.
- `except` → `end_transaction(rollback=True)` y propaga `RuntimeError` con el paso exacto del fallo.

**Comandos prohibidos en lotes** (`_TRANSACTION_FORBIDDEN_COMMANDS`): `open_project`, `close_project`, `save_project`, `list_plcs`, `compile_plc`, `execute_transactional_batch` (anidamiento).

**Coerción defensiva** de `target_folder_path=None` → `""` (TIA Portal V21 rechaza `None` en el wrapper .NET aunque el manual lo declare `Optional[str]`).

---

#### `infrastructure/parsers/__init__.py` (6 líneas)

Docstring: parsers offline, no importan `siemens_tia_scripting`.

---

#### `infrastructure/parsers/excel_parser.py` (175 líneas) — *Parser Excel genérico*

**Propósito**: extraer dos tipos de datos del mismo libro Excel:
- **Dimensiones** (`N_MAX_`, `Num_Disp_`) → `dict[str, int]` para `sync_hardware_dimensions`.
- **DTOs por hoja** → `dict[str, list[dict]]` (forma cruda, no tipada).

**API pública**:
```python
class ExcelParser:
    def extraer_dimensiones(excel_path) -> dict[str, int]
    def extraer_dtos(excel_path) -> dict[str, list[dict[str, Any]]]
```

**Optimizaciones**:
- `load_workbook(read_only=True, data_only=True)` — salta fórmulas, mínimo impacto de memoria.
- `_extract_defined_names` filtra por prefijo (`N_MAX_`, `Num_Disp_`) y descarta celdas no casteables a `int`.
- `_extract_dtos_from_workbook` itera todas las hojas; la primera fila es la cabecera, las siguientes son instancias.

**Nota arquitectónica**: `extraer_dtos` retorna dicts crudos. Para el subdominio alimentación se usa `AlimentacionExcelParser` que COMPOENE sobre este parser y añade el tipado fuerte (ver `infrastructure/alimentacion/`).

---

#### `infrastructure/xml/__init__.py` (6 líneas)

Docstring del subpaquete XML.

---

#### `infrastructure/xml/tag_table_parser.py` (73 líneas) — *Parser SimaticML*

**Propósito**: extraer `PlcUserConstant` (valor + nombre) de un `.xml` exportado por `export_tag_table`.

**API pública**:
```python
class SimaticMLTagParser:
    @staticmethod
    def parse_user_constants(xml_file_path) -> dict[str, str]
        # Retorna {valor_int_str: nombre_constante}
```

**Wildcard XPath**: usa la sintaxis `{*}SW.Tags.PlcUserConstant`, `{*}Name`, `{*}Value` introducida en Python 3.8 — evita hardcodear el namespace de Siemens.

**Limitación documentada**: `ET.iter(tag)` NO soporta wildcard `{*}` en Python 3.x; usamos `root.findall(".//{*}...")` que sí lo acepta.

**Defensa**: descarta entradas con `Value` no casteable a `int` (constantes Real, String, Bool).

---

#### `infrastructure/xml/modifiers.py` (155 líneas) — *Modificador SimaticML*

**Propósito**: clonar nodos `<SW.Tags.PlcTag>` de una plantilla XML y personalizarlos para cada instancia de hardware.

**API pública**:
```python
class XMLModifier:                          # Clase base
    def save(output_path)

class TagTableModifier(XMLModifier):
    def add_tags(dtos: list[IHardwareDevice]) -> int   # idempotente
```

**Cómo funciona `add_tags`**:
1. Busca el primer nodo `{*}SW.Tags.PlcTag` como plantilla (`_find_template_tag`).
2. Recolecta nombres ya existentes (`_existing_tag_names`).
3. Para cada DTO que no esté duplicado:
   - `deepcopy(template)`.
   - Actualiza `Name` con `getattr(dto, "nombre", "")`.
   - Actualiza `Address` (o variantes: `LogicalAddress`, `MemoryArea`) con `getattr(dto, "direccion", "")`.
   - Inserta tras el último PlcTag (`_append_after_last_tag`).
4. Retorna el número de tags añadidos.

**Idempotencia**: si el nombre ya existe en la tabla, no lo duplica.

**Tipado fuerte**: el parámetro `dtos: list[IHardwareDevice]` (Protocol, no `dict`) garantiza que el caller pase objetos del dominio.

---

#### `infrastructure/sd/__init__.py` (8 líneas)

Docstring del subpaquete SD.

---

#### `infrastructure/sd/modifiers.py` (134 líneas) — *Modificador .s7dcl*

**Propósito**: inyectar llamadas de instancia (`Algo();`) en archivos `.s7dcl` exportados por `export_blocks_sd`, entre los marcadores `// AUTO_GEN_START` / `// AUTO_GEN_END`.

**API pública**:
```python
class SDModifier:
    def __init__(sd_path)
    def insert_calls(call_names: list[str]) -> bool   # True si modificó
    def save(output_path)

def collect_call_names(dtos_by_type: dict[str, list[IHardwareDevice]]) -> list[str]
```

**Marcadores**: regex robusta `re.escape(_MARKER_START)\s*\n(?P<body>.*?){re.escape(_MARKER_END)` con flag `re.DOTALL`.

**Idempotencia**: regex `_CALL_PATTERN = r"^\s*(?P<name>...)\s*\(\s*\)\s*;\s*$"` detecta llamadas existentes por nombre; solo inserta las nuevas.

**Tipado**: `collect_call_names` recibe `dict[str, list[IHardwareDevice]]` y extrae nombres vía `getattr(dto, "nombre", "")`.

---

#### `infrastructure/alimentacion/__init__.py` (9 líneas)

Docstring: dependencia unidireccional `infrastructure/ → core/alimentacion/`. Subdominio offline.

---

#### `infrastructure/alimentacion/parsers/__init__.py` (8 líneas)

Docstring: adaptadores Excel → modelos de dominio.

---

#### `infrastructure/alimentacion/parsers/alimentacion_excel_parser.py` (~190 líneas) — *Parser Excel tipado*

**Propósito**: especialización de `ExcelParser` que devuelve **`dict[str, list[IHardwareDevice]]`** (objetos del dominio, no dicts).

**Composición, no herencia**: `class AlimentacionExcelParser` no hereda de `ExcelParser` (hubiera provocado un Liskov violation — `dict` es invariante en el value type). En su lugar, **compone** una instancia interna de `ExcelParser`.

**API pública**:
```python
class AlimentacionExcelParser:
    def __init__()
    def extraer_dtos(excel_path) -> dict[str, list[IHardwareDevice]]
```

**Mapeo hoja → dataclass** (`_SHEET_TYPE_MAP`):
- `"DispED"` → `DispED`
- `"DispEA"` → `DispEA`
- `"DispV"` → `DispV`
- `"Motor"` → `Motor`
- `"Valvula"` → `Valvula`

Hojas desconocidas → ignoradas (forward-compatible).

**Helpers de casteo seguro** (manejan `NaN`, `None`, tipos mixtos):
- `_safe_str(value)` → `""` si NaN/None.
- `_safe_int(value, default=0)` → `default` si falla el casteo.
- `_safe_float(value, default=0.0)` → `default` si falla.
- `_safe_bool(value, default=False)` → `True` solo para literales `True`.

**Casteo tipado**: `_coerce_row_to_model_kwargs` usa `typing.get_type_hints(model_cls)` para resolver forward-refs (`from __future__ import annotations`) y mapear cada columna del Excel al tipo declarado del campo del dataclass.

**Filas inválidas**: las filas sin `nombre` (campo obligatorio) se descartan silenciosamente.

---

#### `infrastructure/tia/__init__.py` (1 línea)

Docstring: subpaquete TIA Portal Openness (motor OT).

---

### 📁 6.4 Capa de Aplicación — `application/`

#### `application/__init__.py` (7 líneas)

Docstring: capa de orquestación entre Dominio, Infraestructura y Presentación.

---

#### `application/use_cases/diff_constants.py` (105 líneas) — *Motor puro de diffs*

**Propósito**: calcular la lista de operaciones `update_user_constant_value` necesarias para sincronizar el estado PLC (`{valor: nombre}`) contra el estado Excel (`{nombre: valor}`).

**Clase principal**:
```python
class CalculateConstantsDiffUseCase:
    @staticmethod
    def execute(plc_name, config_table_name, current_state, desired_state) -> list[dict]
```

**Lógica**:
1. Invierte `current_state` (`{valor: nombre}` → `{nombre: valor}`) para búsquedas O(1).
2. Para cada `(constant_name, desired_value)` en `desired_state`:
   - Busca el valor actual en `current_by_name`.
   - Si difiere → emite `{"command": "update_user_constant_value", "args": {...}}`.
3. **Create** (deshabilitado): comentado, pendiente de soporte nativo en TIA.
4. **Delete** (deshabilitado por defecto): comentado, descomentar si el dominio lo requiere.

---

#### `application/use_cases/sync_hardware_dimensions.py` (138 líneas) — *Sincronización N_MAX* ⭐

**Propósito**: caso de uso principal para sincronizar constantes de dimensionamiento (N_MAX) entre Excel y PLC.

**Flujo orquestado**:
1. Lee Excel → `desired_state: dict[str, int]` (vía `ExcelParser.extraer_dimensiones` en `asyncio.to_thread`).
2. Resuelve el nombre de la tabla vía `ConfigManager.get_global_config_table_name()`.
3. Exporta la tabla PLC a XML → `.build_cache/<tabla>.xml` (vía `gateway.export_tag_table`).
4. Parsea el XML → `current_state: dict[str, str]` (vía `SimaticMLTagParser.parse_user_constants` en `asyncio.to_thread`).
5. Calcula operaciones vía `CalculateConstantsDiffUseCase.execute(...)`.
6. Ejecuta lote transaccional vía `gateway.execute_transactional_batch(...)`.

**Características clave**:
- **No-bloqueo del Event Loop**: parseos CPU-bound (Excel, XML) en `asyncio.to_thread`.
- **Configuración dinámica**: el nombre de tabla PLC se resuelve desde `config.json`, nunca hardcodeado.
- **Idempotencia**: el diff solo emite cambios si difieren.

**API pública**:
```python
class SyncHardwareDimensionsUseCase:
    def __init__(gateway, config_manager, excel_parser=None, build_cache_dir=None)
    async def execute(plc_name, excel_path) -> dict[str, Any]
```

---

#### `application/use_cases/sync_hardware_instances.py` (~165 líneas) — *Sincronización de instancias*

**Propósito**: caso de uso para instanciar variables (PlcTag) y llamadas a bloques (.s7dcl) declaradas en un Excel del departamento de alimentación.

**Flujo orquestado**:
1. Lee Excel → `dtos_by_type: dict[str, list[IHardwareDevice]]` (vía `AlimentacionExcelParser.extraer_dtos` en `asyncio.to_thread`).
2. Exporta la base actual del PLC:
   - Tags XML → `.build_cache/base/tags/` (vía `gateway.export_plc_tags_xml`).
   - Bloques .s7dcl → `.build_cache/base/blocks/` (vía `gateway.export_blocks_sd`).
3. Modifica las plantillas offline (CPU-bound en `asyncio.to_thread`):
   - `TagTableModifier.add_tags(dtos)` → `.build_cache/ready_to_import/tags/`.
   - `SDModifier.update_or_insert_assignment(lhs, line)` → `.build_cache/ready_to_import/blocks/`.
4. Construye payload: `[{"command": "import_plc_tags_xml", ...}, {"command": "import_blocks_sd", ...}]`.
5. Ejecuta lote transaccional vía `gateway.execute_transactional_batch(...)`.

**Convención**: cada hoja del Excel se mapea 1:1 a un archivo XML/SD por nombre de hoja (ej. `DispED.xml`, `DispED.s7dcl`).

**Recordatorio al LLM**: el docstring de la tool MCP `tia_sync_hardware_instances_from_excel` advierte que **el caller debe invocar `tia_compile_plc` después** para asentar el modelo de memoria del PLC.

---

### 📁 6.5 Capa de Presentación — `interfaces/`

#### `interfaces/__init__.py` (13 líneas)

Docstring: aloja adaptadores que exponen el Gateway a distintos clientes (MCP, Web, TUI). Solo puede importar desde `infrastructure/`.

---

#### `interfaces/mcp_server.py` (~520 líneas) — *Servidor FastMCP* ⭐

**Propósito**: factoría que construye un servidor FastMCP exponiendo **22+ tools** que el LLM puede invocar. Es la **cara agéntica** del sistema.

**API pública**:
```python
def create_mcp_server(gateway: TIAProcessGateway) -> FastMCP
def run_mcp_stdio() -> None   # entrypoint para main.py
```

**Tools expuestas** (organizadas por categoría):

| Categoría | Tools |
|---|---|
| Ciclo de vida | `tia_open_project`, `tia_save_project`, `tia_close_project` |
| Inspección | `tia_list_plcs`, `tia_list_blocks` |
| Compilación | `tia_compile_plc` (traduce bool de Siemens a mensaje humano) |
| Export SimaticSD | `tia_export_blocks_sd`, `tia_export_udts_sd` |
| Export SimaticML | `tia_export_plc_tags_xml` |
| Import | `tia_import_blocks_sd`, `tia_import_plc_tags_xml`, `tia_import_block`, `tia_import_tag_table` |
| Constantes N_MAX | `tia_get_user_constants`, `tia_update_user_constant_value`, `tia_update_user_constant_name`, `tia_delete_user_constant` |
| Lotes | `tia_execute_transactional_batch` |
| Casos de Uso de alto nivel | `tia_sync_hardware_dimensions_from_excel`, `tia_sync_hardware_instances_from_excel` |

**Patrón clave**: cada tool declara su contrato (tipos + docstring detallado) para que el LLM descubra capacidades vía introspección del schema MCP. La traducción de tipos nativos de Siemens (ej. booleano invertido de `compile_plc`) a mensajes humanos ocurre en esta capa.

**Inyección de dependencias**:
- `gateway: TIAProcessGateway` (inyectado por `create_mcp_server`).
- `config_manager: ConfigManager` (instanciado internamente, ruta `"infrastructure/config.json"`).
- Use Cases instanciados on-demand dentro de cada tool.

**Docstrings**: exhaustivos, con semántica documentada, advertencias críticas (ej. `tia_close_project` destruye cambios no guardados), y recordatorios al LLM (ej. tras `tia_sync_hardware_instances_from_excel`, invocar `tia_compile_plc`).

---

## 🔧 Patrones de Uso

### Ejemplo 1: Listar PLCs

```bash
echo '{"command":"list_plcs","args":{}}' | python main.py --worker
```

**Respuesta**:
```json
{"ok": true, "result": ["PLC1_Alimentacion", "PLC2_Empaquetado"]}
```

---

### Ejemplo 2: Compilar un PLC

```python
# Desde el cliente MCP/LLM
has_errors = await gateway.compile_plc("PLC1_Alimentacion")
if has_errors is False:
    print("Compilación exitosa")
else:
    print("Hay errores, revisar TIA Portal")
```

---

### Ejemplo 3: Sincronizar N_MAX desde Excel

```python
from infrastructure.gateway import TIAProcessGateway
from infrastructure.config_manager import ConfigManager
from application.use_cases.sync_hardware_dimensions import SyncHardwareDimensionsUseCase

gateway = TIAProcessGateway()
config = ConfigManager("infrastructure/config.json")
use_case = SyncHardwareDimensionsUseCase(gateway, config)

result = await use_case.execute(
    plc_name="PLC1_Alimentacion",
    excel_path="C:/datos/dimensiones_2025.xlsx"
)
print(result["message"])
```

---

### Ejemplo 4: Lote transaccional

```python
operations = [
    {"command": "update_user_constant_value",
     "args": {"plc_name": "PLC1", "table_name": "Config",
              "constant_name": "N_MAX_DISP_ED", "new_value": 50}},
    {"command": "update_user_constant_value",
     "args": {"plc_name": "PLC1", "table_name": "Config",
              "constant_name": "N_MAX_DISP_V", "new_value": 20}},
    # NO incluir compile_plc aquí: está prohibido en lotes.
]

result = await gateway.execute_transactional_batch(
    operations,
    undo_text="Sincronizar Dimensiones (2 cambios)"
)
# Si algo falla, TODO se revierte automáticamente.
```

---

### Ejemplo 5: Instanciación de hardware desde Excel (departamento de alimentación)

```python
from application.use_cases.sync_hardware_instances import SyncHardwareInstancesUseCase

use_case = SyncHardwareInstancesUseCase(gateway)
result = await use_case.execute(
    plc_name="PLC1_Alimentacion",
    excel_path="C:/datos/instances_pastas.xlsx"
)
# Tras éxito, SIEMPRE invocar:
await gateway.compile_plc("PLC1_Alimentacion")
```

**Estructura del Excel** (1 hoja por tipo de dispositivo):
- Hoja `DispED`: columnas `nombre`, `direccion` → filas: `DispED_1`, `%MW100`.
- Hoja `Motor`: columnas `nombre`, `direccion`, `tipo` → filas: `Motor_1`, `%QW200`, `AC`.
- Hoja `Valvula`: columnas `nombre`, `direccion`, `tipo` → filas: `Valvula_1`, `%QX0.0`, `NC`.

---

## ⚙️ Configuración Dinámica

`infrastructure/config.json` define el mapeo entre tipos lógicos del dominio y nombres reales de tablas PLC.

### Estructura

```json
{
  "_comment": "Descripción opcional del archivo",
  "global_config_table_name": "000_Config_Dispositivos"
}
```

### Claves soportadas

| Clave | Tipo | Descripción |
|---|---|---|
| `global_config_table_name` | `str` | Nombre de la tabla PLC que contiene las `PlcUserConstant` (N_MAX). Usado por `sync_hardware_dimensions`. |

### Fallback defensivo

Si el archivo no contiene `global_config_table_name`, `ConfigManager.get_global_config_table_name()` retorna `"000_Config_Dispositivos"` automáticamente (compatibilidad con proyectos legacy).

### Extensibilidad futura

Para añadir más mapeos (ej. tablas por proceso, por departamento), basta con extender `ConfigManager` con nuevos getters y poblar `config.json` con las claves adicionales. **El caso de uso nunca debe hardcodear nombres de tabla.**

---

## 📦 Build y Despliegue

### Compilación a ejecutable standalone

```cmd
:: 1. Activar venv con todas las dependencias
.venv\Scripts\activate

:: 2. Compilar
python build_exe.py
```

El script:
1. Verifica que PyInstaller esté disponible.
2. Localiza el `.pyd` de Siemens en el venv (vía `importlib.util.find_spec`).
3. Lo copia a un **directorio temporal** (`tempfile.mkdtemp(prefix="zc_tia_pyd_")`) con nombre canónico (`siemens_tia_scripting.pyd`).
4. Invoca `PyInstaller --clean --onefile --add-data <staged_pyd>; .`.
5. **Limpia el staging** en `finally`.

**Artefacto final**: `dist/zc_automation_suite.exe` (~30 MB) — un único binario que incluye:
- Intérprete Python embebido.
- `main.py` + todo el código del proyecto.
- El `.pyd` nativo de Siemens.
- Las dependencias (`fastmcp`, `openpyxl`, etc.).

### Ejecución del binario

```cmd
dist\zc_automation_suite.exe
:: Equivalente a python main.py --mcp pero sin dependencia de Python instalado
```

---

## 🧪 Testing Manual

Para probar el worker OT sin tener un cliente MCP real:

```cmd
python test_web_server.py
```

Esto levanta FastAPI/uvicorn en `http://127.0.0.1:8000`:
- `GET /` → formulario HTML con textarea para pegar un payload JSON.
- `POST /api/v1/worker` → ejecuta el payload en el worker OT y devuelve el JSON parseado.

**Payload de ejemplo** para pegar en el textarea:
```json
{
  "command": "list_plcs",
  "args": {}
}
```

La respuesta se muestra formateada en pantalla (verde si `ok=true`, rojo si error).

---

## 📋 Convenciones de Desarrollo

Resumen de las directrices en `.clinerules`:

1. **Aislamiento de capas**:
   - `core/` no importa de `infrastructure/` ni `interfaces/`.
   - `infrastructure/` no importa de `interfaces/`.
   - `interfaces/` solo importa de `infrastructure/`.

2. **Aislamiento IT/OT**:
   - **`siemens_tia_scripting` SOLO se importa en `infrastructure/tia/worker_tia.py`**.
   - Cualquier intento de importarlo en otra capa es un bug crítico.

3. **Tipado estricto**: todas las funciones públicas llevan anotaciones de tipo. Sin `Any` en modelos de dominio.

4. **Python moderno**: `from __future__ import annotations`, `match/case` cuando aplique, `asyncio.to_thread` para CPU-bound.

5. **No retención de estado OT**: el worker mapea objetos nativos a primitivos (`list`, `dict`, `str`, `bool`) antes de emitir JSON.

6. **Compatibilidad**: Python 3.12, 3.13, 3.14. Sin 3.11 ni anteriores.

7. **Idempotencia**: cualquier modificador offline (XML/SD) debe ser idempotente — aplicar dos veces no duplica instancias.

8. **Lotes transaccionales**: usar `gateway.execute_transactional_batch` para todas las mutaciones múltiples atómicas.

---

## 🛠️ Troubleshooting

| Síntoma | Causa probable | Solución |
|---|---|---|
| `RuntimeError: Timeout tras 45s ejecutando el comando 'X'` | El worker OT no responde (diálogo modal abierto en TIA, o TIA colgado). | Cerrar cualquier diálogo modal en TIA Portal. El subproceso es exterminado automáticamente. Aumentar `timeout` en `TIAProcessGateway(timeout=...)`. |
| `RuntimeError: Fallo crítico: attach_portal retornó una referencia nula` | TIA Portal no está abierto, o el usuario no pertenece al grupo `Siemens TIA Openness`. | Abrir TIA Portal. Verificar permisos: `Administración de equipos → Usuarios → Siemens TIA Openness`. |
| `FileNotFoundError: No se encontró el archivo de configuración: 'infrastructure/config.json'` | El archivo `config.json` no existe o está mal ubicado. | Verificar que `infrastructure/config.json` existe. Por defecto se busca relativo al CWD. |
| `ValueError: import_dir debe ser una ruta absoluta` | El caller pasó una ruta relativa. | Pasar siempre rutas absolutas a las tools de import. |
| El worker emite basura no-JSON a STDOUT | La DLL C++ de Siemens está logueando en stdout. | El `_dispatch_worker` del gateway extrae la última línea `{...}` válida, pero puede fallar si hay JSON legítimo más adelante. Verificar que `set_logging(console=False)` esté en el worker. |
| Pylance: `Method "extraer_dtos" overrides class "ExcelParser" in an incompatible manner` | Herencia directa con tipos incompatibles (`dict` invariante). | **Composición** (no herencia): el nuevo parser mantiene una instancia interna del padre. |
| `ET.iter` no encuentra nodos con wildcard `{*}` | Limitación de `xml.etree` en Python 3.x. | Usar `root.findall(".//{*}...")` que sí soporta wildcard. |

---

## � Licencia

Este proyecto está licenciado bajo la **MIT License**. Ver el archivo [LICENSE](LICENSE) para los detalles completos.

```
MIT License
Copyright (c) 2026 Aketzabarragues
```

---

## 🤝 Contribuciones

Para mantener la coherencia arquitectónica:

1. Lee `.clinerules` antes de cualquier cambio significativo.
2. Si añades un comando OT, **debes** actualizar `COMMAND_REGISTRY` en `worker_tia.py` Y la tool correspondiente en `interfaces/mcp_server.py`.
3. Si modificas el dominio (`core/`), respeta las restricciones: sin `siemens_tia_scripting`, sin `Any` en atributos, sin openpyxl.
4. Ejecuta `python -m py_compile <archivo>` antes de commitear.
5. Verifica que los modificadores offline siguen siendo idempotentes.

---

**¿Encontraste un bug o tienes una sugerencia?** Por favor abre un issue en el repositorio incluyendo:
- Logs del worker (`worker_openness.log`).
- Payload JSON exacto que disparó el problema.
- Versión de TIA Portal y Python.
## ðŸ”„ Flujo Unificado de Constantes (N_MAX + Dispositivos)

> **AÃ±adido en esta versiÃ³n.** MigraciÃ³n del flujo legacy anti-histÃ©resis a la
> arquitectura process-per-call. Replicación moderna de los modificadores XML
> offline (`tag_modifier.py`) del proyecto legacy.

### Â¿Por quÃ© un flujo unificado?

TIA Portal Openness tiene un **bug de HistÃ©resis de CompilaciÃ³n**: si las
constantes N_MAX cambian DESPUÃ‰S de importar la PlcTagTable, la compilaciÃ³n
no recalcula las dimensiones de los DBs. El legacy resolviÃ³ este problema
inyectando los valores directamente en el archivo XML antes de importar.

El nuevo flujo mantiene esa estrategia y la extiende para soportar:
- **Cambio de VALOR** (N_MAX): `update_user_constant_value` por COM dentro de transacciÃ³n.
- **Cambio de NOMBRE** (Dispositivos): `update_user_constant_name` por COM (preserva el valor).
- **Crear / Eliminar PlcTagTable enteras** (caso excepcional): offline con `PlcTagTableManager`.

### Flujo end-to-end (7 pasos en UNA transacciÃ³n COM)

```
1. project.start_transaction(undo_text, dialog_text)
2. ONLINE: update_user_constant_value (N_MAX)
3. ONLINE: update_user_constant_name (Dispositivos)
4. ONLINE: export_tag_table â†’ XML temporal
5. OFFLINE: crear/eliminar PlcTagTable + aÃ±adir PlcUserConstant nuevas
6. ONLINE: import_plc_tags_xml â†’ reintegrar XMLs modificados
7. CIERRE: end_transaction(rollback=False) o rollback completo
```

Si el rollback ocurre, el worker restaura los **backups offline** de los
XMLs modificados, garantizando atomicidad REAL (no solo in-memory del COM).

### Componentes nuevos

> **Nota (release 2026-08):** El inyector offline `TagTableValueInjector` (`tabla_injector.py`)
> se eliminÃ³ de la release actual. Su funcionalidad (inyectar N_MAX en XML antes de
> importar) no era invocada por ningÃºn use case de la nueva arquitectura. Se conserva
> como referencia histÃ³rica en `_legacy_reference/ZC_ALM_TOOLS/`.

#### `infrastructure/xml/user_constants_modifier.py` â€” `UserConstantsModifier`
Replica moderna del `TagTableModifier.add_user_constant` legacy. Construye la
estructura canÃ³nica completa de Siemens (`AttributeList` + `MultilingualText`
anidado, cada uno con su propio ID hexadecimal monotÃ³nicamente creciente).
API:

```python
modifier = UserConstantsModifier(xml_path)
modifier.add_user_constant(name="V_VA_101", value=1, comment="...")
modifier.save()
```

#### `infrastructure/xml/plc_tag_table_manager.py` â€” `PlcTagTableManager`
Crea PlcTagTable nuevas (estructura canÃ³nica vacÃ­a lista para importar) y
marca tablas existentes para eliminaciÃ³n por COM. API:

```python
mgr = PlcTagTableManager()
new_path = mgr.create_empty_table("2000_Disp_ED", target_dir)
mgr.mark_for_deletion("2000_Disp_OLD")
```

#### `application/use_cases/diff_constants.py` â€” 2 mÃ©todos de diff
- `CalculateConstantsDiffUseCase.calculate_nmax_diff(...)`: por **nombre** (key estable).
- `CalculateConstantsDiffUseCase.calculate_device_rename_diff(...)`: por **valor** (UID estable).

#### `application/use_cases/sync_constants_unified.py` â€” `SyncConstantsUnifiedUseCase`
Orquestador puro. Llama a `gateway.execute_unified_sync()` con los 3 paquetes:
- `nmax_ops` â†’ `update_user_constant_value`.
- `device_renames` â†’ `update_user_constant_name` (preservando valor).
- `device_offline_changes` â†’ `create`, `delete`, `add_constants` (offline).

#### `infrastructure/tia/worker_tia.py` â€” comando `_cmd_execute_unified_sync`
Implementa los 7 pasos del flujo dentro de UNA transacciÃ³n COM. Registrado
en `COMMAND_REGISTRY` como `execute_unified_sync`.

#### `infrastructure/gateway.py` â€” mÃ©todo `execute_unified_sync()`
Wrapper asÃ­ncrono que delega al worker.

### Ejemplo de uso (alto nivel)

```python
from infrastructure.gateway import TIAProcessGateway
from application.use_cases.sync_constants_unified import SyncConstantsUnifiedUseCase

gateway = TIAProcessGateway()
use_case = SyncConstantsUnifiedUseCase(gateway)

# Estado actual del PLC (N_MAX + dispositivos) â€” vÃ­a gateway.get_user_constants()
nmax_current = {"25": "N_MAX_DISP_ED"}
device_states = {
    "2000_Disp_ED": {
        "current": {"1": "V_001"},
        "desired": {"V_VA_101": 1},
    },
}

result = await use_case.execute(
    plc_name="PLC1_Alimentacion",
    nmax_current_state=nmax_current,
    nmax_desired_state={"N_MAX_DISP_ED": 30},
    device_renames_by_table=device_states,
    device_offline_changes=[
        # {"action": "create", "table_name": "2000_Disp_V"},
        # {"action": "delete", "table_name": "2000_OLD"},
        # {"action": "add_constants", "table_name": "2000_Disp_ED",
        #  "constants": [{"name": "V_NEW", "value": 99, "comment": "..."}]},
    ],
)
```

---

## ðŸ§ª Tests Unitarios (nuevo)

Carpeta `tests/` con tests **OFFLINE** (no requieren TIA Portal).

| Archivo | Cubre |
|---|---|
| *(eliminado en release 2026-08)* `tests/test_tabla_injector.py` | `TagTableValueInjector` (ya no existe; su test fue removido junto al módulo). |
| `tests/test_user_constants_modifier.py` | `UserConstantsModifier` â€” estructura canÃ³nica, IDs incrementales. |
| `tests/test_diff_constants.py` | `CalculateConstantsDiffUseCase` â€” diff N_MAX vs diff dispositivos. |

### EjecuciÃ³n

```cmd
:: Desde la raÃ­z del repo
pip install pytest
python -m pytest tests/ -v
```

### Cobertura

- *(eliminado en release 2026-08)* **TagTableValueInjector**: 6 tests.
- **UserConstantsModifier**: 5 tests (estructura canÃ³nica completa, idempotencia, IDs incrementales, sin comment, validaciÃ³n de nombre vacÃ­o).
- **CalculateConstantsDiffUseCase**: 9 tests (no cambios, cambio de valor N_MAX, ignore de constantes inexistentes, no cambios en dispositivos, rename detectado, valor preservado, valor nuevo ignorado, valor preservado explÃ­citamente, valor cambiado sin rename).

---

## ðŸ†• Changelog de esta versiÃ³n

### Nuevos archivos

| Archivo | LÃ­neas | PropÃ³sito |
|---|---|---|
| `infrastructure/xml/user_constants_modifier.py` | ~200 | AÃ±ade PlcUserConstant con estructura canÃ³nica (replica del legacy). |
| `infrastructure/xml/plc_tag_table_manager.py` | ~175 | Crea/elimina PlcTagTable enteras (offline). |
| `application/use_cases/sync_constants_unified.py` | ~140 | Orquestador puro del flujo unificado. |
| `tests/test_user_constants_modifier.py` | ~110 | Tests del modifier. |
| `tests/test_diff_constants.py` | ~120 | Tests del diff de constantes. |

### Archivos modificados

| Archivo | Cambio |
|---|---|
| `application/use_cases/diff_constants.py` | Refactor: 2 mÃ©todos de diff (`calculate_nmax_diff` + `calculate_device_rename_diff`). |

### Decisiones de diseÃ±o clave

1. **Dos tipos de diff**: `calculate_nmax_diff` (por nombre) y `calculate_device_rename_diff` (por valor). Mezclarlos lleva a errores sutiles.
2. **Workaround de "Histéresis" eliminado** (release 2026-08): la pre-inyección XML offline de N_MAX (`TagTableValueInjector`) se removió. La arquitectura actual confía solo en la transacción COM; si en el futuro se reactiva el workaround, se rescata de `_legacy_reference/`.
3. **TransacciÃ³n unificada con rollback offline manual**: el worker mantiene snapshots de los XMLs antes de modificarlos; si el rollback COM se ejecuta, restaura los snapshots para atomicidad real.
4. **Wildcard XPath `{*}`**: todos los modificadores XML usan esta sintaxis para ser inmunes a cambios de versiÃ³n del esquema SimaticML de Siemens.


## âš™ï¸ ConfiguraciÃ³n DinÃ¡mica

`infrastructure/config.json` define el mapeo entre tipos lÃ³gicos del dominio y nombres reales de tablas PLC, DBs y carpetas en TIA Portal.

### Estructura completa

```json
{
  "_comment": "Configuración multi-departamento. Cada departamento encapsula su jerarquía TIA y sus tipos de dispositivo. Para añadir un nuevo departamento, duplicar el bloque 'alimentacion' bajo 'departments' y ajustar los valores. Si en el futuro se añaden más departamentos, el ConfigManager acepta el parámetro 'department' para resolver el bloque correcto.",
  "_todo_legacy_types": "Los tipos legacy (sd/m_sina/tq/tq_ae/productos) viven en el PLC real dentro de 2000_Dispositivos/ pero NO se configuran aquí. Se activarán cuando se necesite soporte explícito.",
  "departments": {
    "alimentacion": {
      "_comment_folders": "Jerarquía TIA del departamento de alimentación: la tabla N_MAX ('000_Config_Dispositivos') vive en tia_folders.nmax (000_Sistema); las 6 tablas de dispositivos viven en tia_folders.dispositivos (2000_Dispositivos). El sync unificado parsea SOLO esos 7 XMLs del árbol exportado por export_plc_tags_xml; el resto (003_Procesos/*, 000_Traza_*, 2000_Disp_SD, etc.) se ignora.",
      "global_config_table_name": "000_Config_Dispositivos",
      "tia_folders": {
        "proceso":      "003_Procesos",
        "dispositivos": "2000_Dispositivos",
        "nmax":         "000_Sistema"
      },
      "Dispositivos": {
        "ed":    {"db_name": "DB2000_ED",    "db_array_name": "ED",    "tag_table": "2000_Disp_ED",    "config_table": "000_Config_Dispositivos"},
        "ea":    {"db_name": "DB2001_EA",    "db_array_name": "EA",    "tag_table": "2000_Disp_EA",    "config_table": "000_Config_Dispositivos"},
        "sa":    {"db_name": "DB2006_SA",    "db_array_name": "SA",    "tag_table": "2000_Disp_SA",    "config_table": "000_Config_Dispositivos"},
        "v":     {"db_name": "DB2010_V",     "db_array_name": "V",     "tag_table": "2000_Disp_V",     "config_table": "000_Config_Dispositivos"},
        "m":     {"db_name": "DB2015_M",     "db_array_name": "M",     "tag_table": "2000_Disp_M",     "config_table": "000_Config_Dispositivos"},
        "m_vf":  {"db_name": "DB2016_M_VF",  "db_array_name": "M_VF", "tag_table": "2000_Disp_M_VF",  "config_table": "000_Config_Dispositivos"}
      }
    }
  }
}
```

### Multi-departamento (forward-compatible)

La estructura está envuelta en `departments.<nombre>` para que en el
futuro se añadan más departamentos sin colisionar con el bloque
`alimentacion`. Para añadir uno nuevo:

1. Duplicar el bloque `alimentacion` bajo `departments` con el
   nombre del nuevo departamento.
2. Ajustar `global_config_table_name`, `tia_folders` y
   `Dispositivos` según la realidad del PLC.
3. Instanciar el ConfigManager apuntando al nuevo departamento:
   ```python
   cm = ConfigManager("infrastructure/config.json", department="envasado")
   ```

### Jerarquía TIA esperada

```
<PLC>/
├── Tabla de variables estándar.xml                  (ignorada por el sync)
├── 000_Sistema/
│   └── 000_Config_Dispositivos.xml                 ← N_MAX (1 archivo)
│       (N_MAX_DISP_ED, N_MAX_DISP_EA, ...)
├── 003_Procesos/                                    (ignorada por el sync)
│   ├── 50100_CPR.xml
│   └── 500_CIP1/...
└── 2000_Dispositivos/                              ← Dispositivos (6 archivos)
    ├── 2000_Disp_ED.xml
    ├── 2000_Disp_EA.xml
    ├── 2000_Disp_SA.xml
    ├── 2000_Disp_V.xml
    ├── 2000_Disp_M.xml
    └── 2000_Disp_M_VF.xml
    # También pueden existir tablas legacy (2000_Disp_SD, 2000_Disp_TQ, ...);
    # se ignoran porque no están en `Dispositivos.*.tag_table`.
```

El sync unificado (`tia_preview_sync_from_excel` /
`tia_sync_constants_from_excel`) hace **un solo** `export_plc_tags_xml`
bulk con la jerarquía preservada y parsea **únicamente los 7 XMLs**
de las carpetas `tia_folders.nmax` + `tia_folders.dispositivos` que
corresponden a `global_config_table_name` y a los
`Dispositivos.*.tag_table` configurados. El resto del árbol se ignora.

### Claves soportadas (dentro de `departments.<departamento>`)

| Clave | Tipo | Descripción |
|---|---|---|
| `global_config_table_name` | `str` | Nombre de la tabla PLC con las PlcUserConstant N_MAX. |
| `tia_folders.proceso` | `str` | Carpeta TIA que contiene los bloques del proceso (N_MAX). |
| `tia_folders.dispositivos` | `str` | Carpeta TIA que contiene las tablas de dispositivos. |
| `tia_folders.nmax` | `str` | Carpeta TIA donde reside la tabla `000_Config_Dispositivos` (constantes N_MAX). Default: `000_Sistema`. |
| `Dispositivos.<key>.db_name` | `str` | Nombre del DB asociado al tipo (ej. `DB2000_ED`). |
| `Dispositivos.<key>.db_array_name` | `str` | Nombre del array dentro del DB (ej. `ED`). |
| `Dispositivos.<key>.tag_table` | `str` | Nombre de la PlcTagTable del tipo (ej. `2000_Disp_ED`). |
| `Dispositivos.<key>.config_table` | `str` | Nombre de la PlcTagTable donde residen las N_MAX (típicamente `000_Config_Dispositivos`). |

### API de `ConfigManager`

```python
class ConfigManager:
    def __init__(config_path: str | Path, department: str = "alimentacion")
        # Resuelve el sub-bloque del departamento bajo config.departments.

    def get_global_config_table_name() -> str
        # "000_Config_Dispositivos"

    def get_dispositivo_config(key: str) -> DispositivoTIAConfig | None
        # None si el tipo no existe (forward-compatible)
        # Alias deprecado: get_hardware_config(key) -> mismo retorno.

    def get_tag_table_name(key: str) -> str | None
    def get_db_name(key: str) -> str | None
    def get_db_array_name(key: str) -> str | None

    def list_keys() -> list[str]
        # ["ed", "ea", "sa", "v", "m", "m_vf"]
        # Alias deprecado: list_hw_types() -> mismo retorno.

    def get_tia_folder_proceso() -> str
        # "003_Procesos"

    def get_tia_folder_dispositivos() -> str
        # "2000_Dispositivos"

    def get_tia_folder_nmax() -> str
        # "000_Sistema"
```

### Tipos de dispositivo soportados (departamento `alimentacion`)

| key | DB | Tag Table | Descripción |
|---|---|---|---|
| `ed` | `DB2000_ED` | `2000_Disp_ED` | Entradas Digitales |
| `ea` | `DB2001_EA` | `2000_Disp_EA` | Entradas Analógicas |
| `sa` | `DB2006_SA` | `2000_Disp_SA` | Salidas Analógicas |
| `v` | `DB2010_V` | `2000_Disp_V` | Válvulas |
| `m` | `DB2015_M` | `2000_Disp_M` | Motores |
| `m_vf` | `DB2016_M_VF` | `2000_Disp_M_VF` | Motores con Variador de Frecuencia |

### Tipos legacy pendientes (TODO forward-compatible)

Estos tipos aparecen en el log del escaneo TIA del proyecto legacy
(`_legacy_reference/ZC_ALM_TOOLS/dist/.build/tia_wrapper_native.log`) pero
**NO** están configurados explícitamente en `config.json`. Si se necesitan
en el futuro, basta con añadirlos al bloque `Dispositivos` del
departamento activo:

| key (legacy) | Tag Table legacy | DB (estimado) |
|---|---|---|
| `sd` | `2000_Disp_SD` | `DB2002_SD` (estimado) |
| `m_sina` | `2000_Disp_M_SINA` | `DB2717_INST_M_SINA` |
| `tq` | `2000_Disp_TQ` | `DB2040_TQ` (estimado) |
| `tq_ae` | `2000_Disp_TQ_AE` | (estimado) |
| `productos` | `000_Productos` | (N/A — es tabla de productos) |

**Nota**: estos tipos no están operativos en el nuevo repo. La política de
fallback del `ConfigManager` retorna `None` silenciosamente cuando un tipo
no está configurado, por lo que añadir nuevos tipos al JSON no rompe el
código existente.

### Fallbacks defensivos

- `global_config_table_name` ausente → retorna `"000_Config_Dispositivos"`.
- Bloque `departments` ausente → defaults en todos los getters.
- Sección `Dispositivos` ausente → `list_keys()` retorna `[]`.
- Sección `tia_folders` ausente → defaults a `"003_Procesos"`, `"2000_Dispositivos"` y `"000_Sistema"`.
- `tia_folders.nmax` ausente → default `"000_Sistema"`.
- Departamento solicitado no existe → fallback al primer departamento disponible (con warning).
- `key` no existe → `None` + `logger.warning` (NO raise).
- Campos parciales en un tipo → valores vacíos (`""`).

### Extensibilidad

#### Añadir un nuevo tipo de dispositivo

1. Añadir la entrada en el bloque `Dispositivos` del `config.json`.
2. Definir el modelo en `core/alimentacion/models/dispositivos.py`.
3. Mapear la hoja Excel → modelo en `infrastructure/alimentacion/parsers/`.
4. El `ConfigManager` lo expone automáticamente sin tocar código.

#### Añadir un nuevo departamento

1. Duplicar el bloque `alimentacion` bajo `departments` con el nombre
   del nuevo departamento (`"envasado"`, `"paletizado"`, etc.).
2. Ajustar `global_config_table_name`, `tia_folders` y `Dispositivos`
   según la realidad del PLC.
3. Instanciar el ConfigManager apuntando al nuevo departamento:
   ```python
   cm = ConfigManager("infrastructure/config.json", department="envasado")
   ```

**El caso de uso NUNCA debe hardcodear nombres de tabla** (legacy usaba
hardcodes como `"000_Config_Dispositivos"` que se han eliminado en el nuevo
repositorio).

---


## ðŸ”„ Flujo de SincronizaciÃ³n con PatrÃ³n Preview / Apply

> **AÃ±adido en esta versiÃ³n.** Orquestador de alto nivel que combina
> Excel + TIA Portal en una transacciÃ³n COM unificada con pre-flight.

### Â¿Por quÃ© este flujo?

El nuevo flujo resuelve 3 problemas detectados en el legacy:

1. **HistÃ©resis de CompilaciÃ³n**: el legacy inyectaba N_MAX en el XML antes
   de importar (anti-histÃ©resis). El nuevo repo lo hace en una transacciÃ³n
   COM unificada con rollback completo.
2. **Dos naturalezas de constantes**: N_MAX (cambio de VALOR) vs dispositivos
   (cambio de NOMBRE preservando VALOR). Antes eran casos separados.
3. **Falta de pre-flight**: el legacy tenÃ­a `generar_prevision()` pero solo
   para dispositivos. Ahora hay un patrÃ³n preview/apply unificado.

### Componentes del flujo

```
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ STEP 1: Operario carga Excel (tool existente)                  â”‚
â”‚   MCP: tia_sync_dispositivos_dimensions_from_excel             â”‚
â”‚   â””â”€ AlimentacionExcelParser â†’ AppState (Singleton)            â”‚
â”‚      â€¢ AppState.dimensiones = DimensionesDispositivos(...)       â”‚
â”‚      â€¢ AppState.dispositivos_ed/ea/sa/v/m/m_vf = [...]         â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                              â”‚
                              â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ STEP 2 (NUEVO): Operario pide PREVIEW (solo lee, NO toca TIA)  â”‚
â”‚   MCP: tia_preview_sync_from_excel(plc_name)                  â”‚
â”‚                                                                 â”‚
â”‚   Internamente:                                                  â”‚
â”‚   1. Verifica AppState no vacÃ­o (warning si vacÃ­o)              â”‚
â”‚   2. Lee PLC actual vÃ­a gateway.get_user_constants()            â”‚
â”‚      â€¢ N_MAX: gateway.get_user_constants(plc, "000_Config_Dispositivos") â”‚
â”‚      â€¢ Dispositivos: gateway.get_user_constants(plc, "2000_Disp_X")     â”‚
â”‚   3. Calcula diff puro (sin tocar TIA)                         â”‚
â”‚      â€¢ calculate_nmax_diff(): detecta cambios de VALOR           â”‚
â”‚      â€¢ calculate_device_rename_diff(): detecta cambios de NOMBREâ”‚
â”‚   4. Devuelve:                                                   â”‚
â”‚      {                                                           â”‚
â”‚        "summary": {                                              â”‚
â”‚          "n_max_updates": int,                                   â”‚
â”‚          "device_renames": int,                                 â”‚
â”‚          "total_ops": int,                                       â”‚
â”‚          "has_changes": bool                                     â”‚
â”‚        },                                                        â”‚
â”‚        "nmax_ops": [...],                                       â”‚
â”‚        "device_diffs": {"ed": [...], "v": [...]},              â”‚
â”‚        "warnings": [...]                                        â”‚
â”‚      }                                                           â”‚
â”‚                                                                 â”‚
â”‚   Output al LLM: "Hay 3 N_MAX updates y 2 device renames.        â”‚
â”‚                    Â¿Confirmas aplicarlos?"                        â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                              â”‚
                              â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ STEP 3: Operario confirma y aplica (NUEVO)                      â”‚
â”‚   MCP: tia_sync_constants_from_excel(plc_name)                â”‚
â”‚                                                                 â”‚
â”‚   Internamente:                                                  â”‚
â”‚   1. Verifica AppState no vacÃ­o                                 â”‚
â”‚   2. Lee PLC actual (igual que preview)                         â”‚
â”‚   3. Calcula diff (mismo helper compartido)                    â”‚
â”‚   4. Ejecuta transacciÃ³n COM unificada:                        â”‚
â”‚      project.start_transaction()                                â”‚
â”‚      N Ã— update_user_constant_value (N_MAX)                     â”‚
â”‚      M Ã— update_user_constant_name (dispositivos)               â”‚
â”‚      [opcional] export â†’ modify XML â†’ import (offline)         â”‚
â”‚      project.end_transaction(rollback=False/True)              â”‚
â”‚   5. Invalidar cachÃ© del gateway (clear_cache())               â”‚
â”‚                                                                 â”‚
â”‚   Output al LLM: "âœ… Sync ejecutado: 3 N_MAX updates + 2 renames"â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

### Componentes del flujo en el cÃ³digo

| Archivo | Rol |
|---|---|
| `application/use_cases/sync_constants_from_excel.py` â­ | **Orquestador de alto nivel** (preview + apply). Inyecta `AppState`, lee PLC, llama al orquestador unificado. |
| `application/use_cases/sync_constants_unified.py` | Orquestador de **bajo nivel** con 2 mÃ©todos (`preview()` + `execute()`) que comparten `_compute_operations()`. |
| `application/use_cases/diff_constants.py` | Motor puro de diffs (`calculate_nmax_diff`, `calculate_device_rename_diff`). |
| `application/state.py` | **`AppState` Singleton** con 6 listas de dispositivos + `dimensiones`. |
| `infrastructure/config_manager.py` | Resuelve `hw_type â†’ tag_table` desde `config.json`. |
| `infrastructure/gateway.py` | Wrapper async del subprocess worker. Tiene `clear_cache()` para invalidar cachÃ© IT tras sync. |

### API pÃºblica

```python
# Uso de alto nivel (lo que usan las MCP tools):
use_case = SyncConstantsFromExcelUseCase(
    gateway=gateway,
    config_manager=config_manager,
    app_state=get_app_state(),   # Singleton con Excel cargado
)

# PREVIEW: solo calcula, no toca TIA.
preview_result = await use_case.preview(plc_name="PLC1_Alimentacion")
# preview_result["summary"]["has_changes"] == True/False
# preview_result["nmax_ops"]       # lista de ops pendientes
# preview_result["device_diffs"]   # {hw_type: [ops]}

# APPLY: calcula + transacciÃ³n COM unificada + clear_cache().
apply_result = await use_case.execute(plc_name="PLC1_Alimentacion")
```

### Decisiones arquitectÃ³nicas clave

1. **DI explÃ­cita**: el orquestador recibe `gateway`, `config_manager` y
   `app_state` por constructor. NO usa Singleton/global.
2. **PatrÃ³n preview/apply**: ambos mÃ©todos comparten `_compute_operations()`,
   garantizando que la preview y el apply producen exactamente el mismo diff.
3. **Sin re-parsear Excel**: el `AppState` debe estar cargado al menos una
   vez (vÃ­a `tia_sync_dispositivos_dimensions_from_excel`). El orquestador
   NO re-lee el Excel para mantener paridad con el preview.
4. **ValidaciÃ³n previa**: si el `AppState` estÃ¡ vacÃ­o, `preview()` retorna
   warnings pero `execute()` tambiÃ©n puede continuar (operarÃ¡ con diff vacÃ­o).

### MCP Tools expuestas (NUEVAS)

| Tool | Tipo | CuÃ¡ndo usarla |
|---|---|---|
| `tia_preview_sync_from_excel(plc_name)` | Preview | DespuÃ©s de cargar el Excel, antes de confirmar. Devuelve JSON con el diff. |
| `tia_sync_constants_from_excel(plc_name)` | Apply | Tras confirmar el preview. Ejecuta la transacciÃ³n. |

---


## ðŸ”„ Flujo de SincronizaciÃ³n â€” Estrategia EXPORT â†’ PARSE â†’ DIFF

> **AÃ±adido en esta versiÃ³n.** El orquestador exporta cada PlcTagTable
> a una carpeta temporal vÃ­a COM y la parsea con ``SimaticMLTagParser``.
> **NO** se hace la lectura directamente desde el runtime COM en vivo.

### Â¿Por quÃ© export â†’ parse en lugar de COM directo?

El mÃ©todo ``gateway.get_user_constants()`` (que llama a COM en vivo)
puede NO devolver el estado correcto de las tablas si:
- TIA Portal tiene cambios en disco que aÃºn no estÃ¡n commiteados al runtime COM.
- La cachÃ© del wrapper de Siemens difiere del estado en disco.
- Hay tablas que TIA no expone correctamente por COM pero sÃ­ exporta a XML.

La estrategia **export â†’ parse** garantiza que el diff se hace contra
**el mismo XML que TIA efectivamente commitea al re-importar**, que es
la fuente de verdad definitiva.

### Flujo detallado

```
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ STEP 1: Operario carga Excel (tool existente)                  â”‚
â”‚   MCP: tia_sync_dispositivos_dimensions_from_excel             â”‚
â”‚   â””â”€ AlimentacionExcelParser â†’ AppState (Singleton)            â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                              â”‚
                              â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ STEP 2 (NUEVO): Operario pide PREVIEW                          â”‚
â”‚   MCP: tia_preview_sync_from_excel(plc_name)                  â”‚
â”‚                                                                 â”‚
â”‚   SyncConstantsFromExcelUseCase.preview() ejecuta:              â”‚
â”‚   1. Crea carpeta temporal:                                    â”‚
â”‚      temp_dir = tempfile.mkdtemp(prefix="zc_sync_<plc>_")      â”‚
â”‚   2. Exporta 7 PlcTagTable vÃ­a COM:                            â”‚
â”‚      gateway.export_tag_table("PLC1", "000_Config_Dispositivos", temp_dir)
â”‚      gateway.export_tag_table("PLC1", "2000_Disp_ED",           temp_dir)
â”‚      gateway.export_tag_table("PLC1", "2000_Disp_EA",           temp_dir)
â”‚      gateway.export_tag_table("PLC1", "2000_Disp_SA",           temp_dir)
â”‚      gateway.export_tag_table("PLC1", "2000_Disp_V",            temp_dir)
â”‚      gateway.export_tag_table("PLC1", "2000_Disp_M",            temp_dir)
â”‚      gateway.export_tag_table("PLC1", "2000_Disp_M_VF",         temp_dir)
â”‚   3. Parsea cada XML exportado:                                â”‚
â”‚      SimaticMLTagParser.parse_user_constants(temp_dir/X.xml)    â”‚
â”‚      â†’ {valor_int_str: nombre}                                â”‚
â”‚   4. Construye current_state con el formato esperado.          â”‚
â”‚   5. finally: shutil.rmtree(temp_dir)                         â”‚
â”‚   6. Calcula diff (preview = no aplica)                       â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                              â”‚
                              â–¼
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ STEP 3: Operario confirma y aplica                            â”‚
â”‚   MCP: tia_sync_constants_from_excel(plc_name)                â”‚
â”‚   â””â”€ Igual que preview, pero ejecuta transacciÃ³n COM +        â”‚
â”‚      clear_cache() tras Ã©xito.                                â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

### 7 round-trips COM por sync completo

El orquestador hace 7 llamadas a ``gateway.export_tag_table()``:
- **1 para N_MAX**: ``000_Config_Dispositivos``.
- **6 para dispositivos**: ``2000_Disp_ED``, ``2000_Disp_EA``, ``2000_Disp_SA``,
  ``2000_Disp_V``, ``2000_Disp_M``, ``2000_Disp_M_VF``.

Cada exportaciÃ³n genera un archivo ``.xml`` en la carpeta temporal. **NO
se hace ninguna llamada directa a ``get_user_constants()``**.

### Carpeta temporal: ciclo de vida

```
Creada en:    tempfile.mkdtemp(prefix="zc_sync_<plc_name>_")
Usada en:     gateway.export_tag_table() (escritura de XML)
              SimaticMLTagParser.parse_user_constants() (lectura de XML)
Limpiada en:  finally: shutil.rmtree(temp_dir, ignore_errors=True)
```

Si la exportaciÃ³n o el parseo fallan, **la carpeta temporal se limpia
igualmente** (gracias al bloque ``finally``).

### Ventajas vs. COM directo

| Aspecto | COM directo | Export â†’ Parse |
|---|---|---|
| **Fuente de verdad** | Estado en vivo del runtime COM | XML commiteado por TIA en disco |
| **Consistencia con apply** | Puede diferir del import final | Garantiza paridad exacta |
| **Rendimiento** | 7 round-trips COM (~50-200ms cada uno) | Igual (7 round-trips COM) |
| **Manejo de errores** | ExcepciÃ³n del COM | Se loggea + continÃºa con la siguiente tabla |

### MCP Tools expuestas (NUEVAS)

| Tool | Tipo | CuÃ¡ndo usarla |
|---|---|---|
| `tia_preview_sync_from_excel(plc_name)` | Preview | DespuÃ©s de cargar el Excel, antes de confirmar. Devuelve JSON con el diff. |
| `tia_sync_constants_from_excel(plc_name)` | Apply | Tras confirmar el preview. Ejecuta la transacciÃ³n. |

---


