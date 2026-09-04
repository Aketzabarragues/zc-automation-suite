# ZC Automation Suite

> Herramienta de integración IT/OT para la automatización e inspección de proyectos en **Siemens TIA Portal Openness** mediante el SDK oficial **TIA Scripting Python (SIOS 109742322)**.

![Arquitectura](https://img.shields.io/badge/arquitectura-Process--per--Call-blue) ![Layout](https://img.shields.io/badge/layout-Bounded%20Contexts-orange) ![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-yellow) ![TIA Portal](https://img.shields.io/badge/TIA%20Portal-V15.1%2B-green) ![Licencia](https://img.shields.io/badge/licencia-MIT-lightgrey)

---

## Tabla de Contenidos

1. [Visión General](#-visión-general)
2. [Requisitos del Entorno](#-requisitos-del-entorno)
3. [Modos de Ejecución](#-modos-de-ejecución)
4. [Arquitectura del Sistema](#-arquitectura-del-sistema)
5. [Estructura del Repositorio](#-estructura-del-repositorio)
6. [Descripción Carpeta por Carpeta](#-descripción-carpeta-por-carpeta)
7. [Patrones de Uso](#-patrones-de-uso)
8. [Configuración Dinámica](#-configuración-dinámica)
9. [Bounded Contexts y AreaRegistry](#-bounded-contexts-y-arearegistry)
10. [Build y Despliegue](#-build-y-despliegue)
11. [Testing](#-testing)
12. [Convenciones de Desarrollo](#-convenciones-de-desarrollo)
13. [Troubleshooting](#-troubleshooting)
14. [Cómo Contribuir](#-cómo-contribuir)
15. [Licencia](#-licencia)

---

## 🎯 Visión General

ZC Automation Suite es una capa de integración que conecta **aplicaciones asíncronas en Python** (clientes MCP/LLM, servidores web FastAPI) con el entorno **síncrono y nativo de TIA Portal Openness** (COM/.NET).

El proyecto resuelve el problema clásico de TIA Openness: la **incompatibilidad entre el modelo asíncrono de Python y el modelo síncrono COM** de Siemens (los punteros RCW de .NET **no son thread-safe**). Para evitar errores de tipo `COMException` o corromper el RCW, ZC Automation Suite implementa el patrón **Process-per-Call**: cada comando contra TIA Portal se ejecuta en un **subproceso efímero** que nace, ejecuta y muere, comunicándose con el proceso padre únicamente vía **JSON sobre `stdin`/`stdout`**.

### Características clave

- 🧱 **Bounded Contexts**: el código se organiza en `core/` (transversal) y `areas/<área>/` (cada departamento con su dominio, aplicación, infraestructura, interfaces y frontend). Las áreas se autodescriben con un `AreaSpec` y se descubren dinámicamente vía `AreaRegistry`.
- 🔌 **Doble adaptador**: misma lógica de negocio servida vía **FastMCP** (LLM) y vía **FastAPI** (humano vía navegador), con SPA Vue 3 (ESM sin build step).
- ️🛡️ **Lotes transaccionales con rollback automático**: si una operación falla a mitad de un lote, TIA Portal revierte todas las anteriores (`start_transaction` / `end_transaction(rollback=True)`).
- 🔁 **Idempotencia** en modificadores offline XML/SCL: aplicar dos veces el mismo cambio no duplica instancias.
- 📦 **Build `--onefile`** con PyInstaller, incluyendo el `.pyd` nativo de Siemens en el bundle sin contaminar el repositorio.
- 🧷 **Tipado fuerte** end-to-end: dataclasses `frozen=True` + Protocols (`IHardwareDevice`) desde el Excel hasta el PLC.
- 📊 **Progress tracking** en operaciones >500 ms vía `ProgressTracker` y panel lateral fijo en la SPA.

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

### 2. Modo Servidor Web FastAPI (UI para operario)

```cmd
python main.py --web
:: Equivalente a: python main.py --web 127.0.0.1:8000
```

Levanta FastAPI + Uvicorn en `http://127.0.0.1:8000`. Sirve la SPA Vue 3 (`/static/`) y los routers REST (`/api/v1/...`). El shell (`interfaces/web_server/app.py::create_app`) descubre los routers de las áreas vía `AreaRegistry.discover().for_each("contributes_routers", app=app)`.

### 3. Modo Launcher con Bandeja del Sistema (dev)

```cmd
python main_tray.py
:: o doble-clic sobre run_tray.bat
```

`main_tray.py` (composition root del launcher, **NO** del runtime) levanta `pystray` con menú `Iniciar web` / `Parar web` / `Abrir panel web` / `Estado` / `Salir`. Internamente usa `launcher/web_supervisor.py` para arrancar/parar el servidor web bajo demanda del operario.

### 4. Modo Worker OT (subproceso aislado)

```cmd
echo {"command": "list_plcs", "args": {}} | python main.py --worker
```

Este modo **NO se invoca manualmente en producción**; el `TIAProcessGateway` lo lanza internamente por cada comando. Útil para depuración directa del motor OT.

### 5. Modo Ejecutable Empaquetado (PyInstaller)

Genera un `dist\zc_automation_suite.exe` standalone con la bandeja + web supervisor + binarios nativos de Siemens embebidos (`.pyd` + 10 `.dll` + `log4net.xml`):

```cmd
python build_exe.py
:: → dist\zc_automation_suite.exe
```

**UX del `.exe`** (doble-clic):

- Aparece icono en la bandeja del sistema (sin ventana de consola).
- Click-derecho → menú: `Iniciar web` / `Parar web` / `Abrir panel web` / `Estado` / `Salir`.
- `Iniciar web` arranca el servidor FastAPI en `http://127.0.0.1:8000`.
- `Abrir panel web` abre el navegador en esa URL.

**Modo `--worker` (uso interno, no invocable manualmente por operarios)**:

El gateway re-invoca el mismo `.exe` con `--worker` para aislar cada comando OT en un subproceso efímero (patrón process-per-call). Para depurar manualmente:

```cmd
echo {"command":"list_plcs","args":{}} | dist\zc_automation_suite.exe --worker
```

**Restricciones del build** (heredadas del legacy y de la arquitectura):

- El `.pyd` y TODAS las `.dll` se stagean en un `tempfile.mkdtemp()`, NUNCA en la raíz del repo. Cero Código Sucio: tras el build no queda ningún `.pyd`/`.dll`/`.xml` en el working tree.
- El `.spec` se auto-genera en el mismo tempdir y se borra tras el build. No es un archivo tracked.
- UPX excluido para `*.dll` y `*.pyd` (UPX corrompe los ensamblados .NET nativos de Siemens).
- Modo FastMCP STDIO (`--mcp`) **no se incluye** en el `.exe` — queda como modo dev (`python main.py`). El `.exe` es para la UX de operario (bandeja + web), no para clientes LLM.

---

## 🏛️ Arquitectura del Sistema

### Diagrama de capas y Bounded Contexts

```
┌──────────────────────────────────────────────────────────────────────┐
│                       interfaces/  +  core/interfaces/               │  ← Capa de Presentación
│   ┌──────────────────────────┐    ┌──────────────────────────────┐   │     (FastMCP, FastAPI,
│   │  mcp_server.py (shell)   │    │  web_server/app.py (shell)   │   │      SPA Vue 3 ESM)
│   └────────────┬─────────────┘    └──────────────┬───────────────┘   │
│                │ usa                              │ usa                │
│   ┌────────────▼─────────────────────────────────▼───────────────┐   │
│   │  core/application/   ← orquestación transversal             │   │  ← Capa de Aplicación
│   │   area_registry.py  · state.py · progress_buffer.py         │   │     (casos de uso,
│   │                            · log_buffer.py                    │   │      singletons)
│   └────────────┬─────────────────────────────────────────────────┘   │
│                │ usa                                                  │
│   ┌────────────▼─────────────────────────────────────────────────┐   │
│   │  core/infrastructure/  ← OT + IO transversales                │   │  ← Capa de Infraestructura
│   │   gateway.py · config_manager.py · parsers/ · xml/ · sd/      │   │     (gateway, parsers,
│   │   tia/worker_tia.py (generic) · tia/command_loader.py         │   │      modificadores XML/SD)
│   └────────────┬─────────────────────────────────────────────────┘   │
│                │ usa (solo modelos)                                   │
│   ┌────────────▼──────────────┐                                      │  ← Capa de Dominio
│   │  core/models/             │                                      │     (dataclasses frozen,
│   │   (placeholders)          │                                      │      Protocol, lógica pura)
│   └───────────────────────────┘                                      │
│                                                                     │
│ ┌─────────────────────────────────────────────────────────────────┐ │
│ │  areas/<área>/  ← Bounded Context autocontenido por departamento│ │
│ │   alimentacion/                                                 │ │
│ │    domain/  application/  infrastructure/                       │ │
│ │    interfaces/  frontend/                                       │ │
│ │    __init__.py exporta un AreaSpec (AreaRegistry lo descubre)   │ │
│ └─────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘

Dirección de dependencias: ↑ solo hacia arriba. NUNCA hacia abajo.
Las áreas importan del core; el core NO conoce las áreas.
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

### Command loader del worker OT

`core/infrastructure/tia/worker_tia.py` solo contiene los **comandos genéricos** del registry (`COMMAND_REGISTRY`). Las áreas aportan comandos adicionales transaccionales vía `areas/<área>/infrastructure/tia/extra_commands.py::register(registry)`. El command loader (`core/infrastructure/tia/command_loader.py::load_extra_commands`) los descubre automáticamente al arrancar el worker iterando `AreaRegistry.discover().all()`. Los handlers extra reciben `(portal, ts, args)` y **pueden** invocar comandos genéricos del registry (`COMMAND_REGISTRY["export_block"](...)`) para participar de transacciones atómicas con ellos.

---

## 📂 Estructura del Repositorio

```
zc-automation-suite/
├── .clinerules                  # Reglas arquitectónicas críticas (cortas, se cargan siempre)
├── .gitignore                   # Exclusiones estándar Python + custom
├── .repomixignore               # Exclusiones para repomix (snapshot IA)
├── AGENTS.md                    # Guía de extensión (Bounded Contexts, convenciones)
├── LICENSE                      # MIT License
├── README.md                    # Este archivo
├── main.py                      # Composition Root CLI (--mcp / --web / --worker)
├── main_tray.py                 # Composition Root del launcher (system tray dev)
├── build_exe.py                 # Orquestador PyInstaller (.pyd staging)
├── requirements.txt             # Dependencias Python
├── run_app.bat / run_app_tray.bat / run_tray.bat / run_build.bat / run_tailwind.bat / run_repomix.bat
├── tailwind.config.js + tailwindcss-extra.exe
│
├── core/                        # ──── Capa transversal ────
│   ├── __init__.py
│   ├── models/                  # Scaffolding (placeholders)
│   ├── application/             # area_registry · state · progress_buffer · log_buffer
│   ├── infrastructure/          # gateway · config_manager · parsers · xml · sd · tia
│   │   └── tia/                 # worker_tia.py (genérico) + command_loader.py
│   └── interfaces/              # mcp_server.py (shell MCP)
│
├── areas/                       # ──── Bounded Contexts por departamento ────
│   ├── __init__.py
│   └── alimentacion/            # Departamento Alimentación
│       ├── __init__.py          # Exporta AREA_SPEC
│       ├── domain/              # catalog · models/
│       ├── application/         # use_cases/ · state_extensions
│       ├── infrastructure/      # config_defaults · parsers · sd · tia/extra_commands
│       ├── interfaces/          # mcp/tools.py · web/{alimentacion,sync,excel}.py
│       └── frontend/            # components/ · manifest.js · manifest.py
│
├── launcher/                    # ──── Bandeja del sistema (dev) ────
│   ├── tray_app.py              # Menú pystray
│   ├── web_supervisor.py        # Lifecycle del web server
│   ├── make_icon.py + icon.ico
│
├── interfaces/                  # ──── Capa de presentación web ────
│   └── web_server/              # app.py (shell) + dependencies + routers/ + static/
│       └── routers/             # areas · area_manifests · catalog · diagnostics · portal
│
├── infrastructure/              # Solo `config.json` (movido a este path para compat)
│   └── config.json
│
├── scripts/                     # Smoke tests manuales del operario
├── tests/                       # 254 tests pytest (252 ok + 2 skipped)
├── docs/                        # Documentación adicional
├── _legacy_reference/           # Código histórico (NO importar, en .gitignore)
├── _plan/                       # Notas de planificación internas (en .gitignore)
├── _source/                     # Volcados del operario (.s7dcl/.s7res de TIA, en .gitignore)
└── logs/                        # Logs runtime (en .gitignore)
```

**Notas operativas** sobre los `.gitignore` (no commitear):

- `_source/`, `_plan/`, `.minimax/`, `_trash_temp/`, `tailwindcss-extra.exe`, `*.pyd` y todo lo listado en `.gitignore` es **opcional** del operario o del runtime. El repo funciona sin ellos.
- `_legacy_reference/` contiene el proyecto antiguo. Se conserva por referencia histórica; **NO se importa** desde el código nuevo (ver `.clinerules` §5).

---

## 📖 Descripción Carpeta por Carpeta

### 📁 Raíz

#### `main.py` — *Composition Root del runtime*

Enrutador CLI delgado. Según el flag, delega a uno de los tres modos:

- **`--worker`** → `core.infrastructure.tia.worker_tia.main()` (modo OT, usado internamente por el gateway).
- **`--web [host:port]`** → arranca FastAPI/uvicorn con la única instancia de `TIAProcessGateway` inyectada en `create_app(gateway)`.
- **`(default)` o `--mcp`** → `core.interfaces.mcp_server.run_mcp_stdio()` (modo presentación FastMCP).

**Importaciones tardías**: importa los módulos pesados solo cuando se invocan (`fastmcp` solo si `--mcp`, `uvicorn` solo si `--web`).

#### `main_tray.py` — *Composition Root del launcher*

Entry point del modo dev con bandeja. NO es la versión empaquetada (eso es PyInstaller). Su responsabilidad exclusiva: configurar logging, leer env vars de host/puerto, crear `WebServiceSupervisor` y bloquear el main thread con `pystray`. Al "Salir" del menú, detiene el web limpiamente. **NO instancia el gateway** (lo hace el supervisor al construir la app).

#### `build_exe.py` — *Compilador PyInstaller*

Genera `dist/zc_automation_suite.exe` standalone incluyendo el `.pyd` nativo de Siemens.

**Pipeline**:
1. `ensure_pyinstaller()` → valida PyInstaller.
2. `resolve_pyd_source()` → `importlib.util.find_spec()` para localizar el `.pyd` en el venv.
3. `stage_pyd_with_canonical_name()` → copia a `tempfile.mkdtemp()` con nombre canónico.
4. `build()` → invoca `PyInstaller --onefile --add-data <pyd>.`.
5. `finally` → `shutil.rmtree()` del staging.

#### `requirements.txt` — *Dependencias Python*

```
fastmcp>=0.1.0    # Framework MCP agéntico
mcp>=1.0.0        # SDK MCP base
pyinstaller>=6.0.0  # Compilación a ejecutable
fastapi>=0.100.0  # Servidor web (web_server/app.py)
uvicorn>=0.20.0   # ASGI server para FastAPI
openpyxl>=3.0.0   # Lectura/escritura de Excel (.xlsx)
pytest>=8.0.0     # Suite de tests
```

Nota: **`siemens_tia_scripting` NO está aquí** — se instala manualmente desde la `.whl` oficial porque es un binario nativo propietario.

#### `.clinerules` — *Reglas arquitectónicas inmutables*

Reglas de oro del proyecto (cortas, se cargan siempre). 9 secciones: arquitectura process-per-call, ciclo de vida del worker, no retención de estado OT, API Siemens V1.2.1, código legacy, código limpio, progress tracking, single-tenant, CSS/frontend build.

#### `AGENTS.md` — *Guía de extensión*

Documento vivo para agentes AI y humanos. Cubre "Cómo añadir una nueva feature" (operación OT, endpoint REST, vista SPA, nuevo tipo de dispositivo, comando MCP) y "Cómo añadir una nueva área" paso a paso. Convenciones operativas y atajos de desarrollo. Se consulta cuando se va a tocar el código.

### 📁 `core/` — Capa transversal

`core/` contiene TODO lo que varias áreas comparten. NO conoce las áreas concretas (la única excepción es `core.application.area_registry` que itera el paquete `areas/` por convención).

#### `core/application/area_registry.py` — *AreaSpec + AreaRegistry + ListAreasUseCase*

**El corazón del patrón Bounded Contexts.** Define:

- `AreaSpec` (dataclass frozen): contrato de área con 8 hooks opcionales (`contributes_routers`, `contributes_tia_commands`, `contributes_mcp_tools`, `contributes_frontend_manifest`, `contributes_state_extensions`, `contributes_config_defaults`, `contributes_catalog`, más `id`/`label`/`icon`/`config_block`).
- `AreaRegistry` (Singleton): `discover()` itera `areas/*/`, importa cada `__init__.py`, captura el `AREA_SPEC` y los cachea. `for_each(hook, **kwargs)` invoca el hook en cada spec que lo implemente.
- `AreaInfo` (DTO) + `ListAreasUseCase`: presentación de áreas al frontend SPA (consumido por `GET /api/v1/areas`).

```python
from core.application.area_registry import AreaInfo, ListAreasUseCase, AreaSpec, AreaRegistry
```

#### `core/application/state.py` — *AppState Singleton*

Estado de aplicación single-tenant: contiene las dimensiones N_MAX y las 6 listas de dispositivos cargadas desde Excel. **No persistir** entre reinicios (ver `.clinerules` §8). Las áreas extienden `AppState` con properties de back-compat vía `contributes_state_extensions`.

#### `core/application/progress_buffer.py` — *ProgressTracker*

Tracker de operaciones largas para el panel `ProgressIndicator` de la SPA. API: `begin / start_stage / finish_stage / error_stage / finish / clear / snapshot`. La propiedad `active` permite que un orquestador detecte si ya hay una operación en curso (evita pisar el tracker). Ver `.clinerules` §7.

#### `core/application/log_buffer.py` — *LogBuffer*

Buffer de logs expuesto vía `GET /api/v1/logs` y consumido por la SPA (panel "Consola"). Polling a 1s en frontend.

#### `core/infrastructure/gateway.py` — *TIAProcessGateway*

**El ÚNICO módulo que sabe cómo lanzar el subproceso OT.** Toda la comunicación con TIA Portal pasa por aquí.

**API pública** (resumen):
- **Ciclo de vida del proyecto**: `open_project()`, `save_project()`, `close_project()`.
- **Inspección con caché**: `get_plcs(force_refresh=False)`, `get_blocks(plc_name, folder_path, force_refresh=False)`.
- **Compilación**: `compile_plc(plc_name) -> bool` (invierte la semántica del booleano nativo de Siemens).
- **Export SimaticSD (.s7dcl)**: `export_blocks_sd()`, `export_udts_sd()`.
- **Export SimaticML (XML)**: `export_plc_tags_xml()`, `export_tag_table(plc_name, table_name)`.
- **Import**: `import_blocks_sd()`, `import_plc_tags_xml()`, `import_block()`, `import_tag_table()`.
- **Constantes N_MAX**: `get_user_constants()`, `update_user_constant_value()`, `update_user_constant_name()`, `delete_user_constant()`.
- **Lotes transaccionales**: `execute_transactional_batch(operations, undo_text)`.
- **Caché**: `clear_cache()`.

**Mecanismo clave**: `_dispatch_worker(command, args)` lanza `asyncio.create_subprocess_exec` con `sys.executable -u main.py --worker`, envía el payload JSON por STDIN, lee la ÚLTIMA línea `{...}` de STDOUT como respuesta (filtro contra interferencias), aplica timeout de 45s. Detecta `sys.frozen` (PyInstaller) vs desarrollo y ajusta los argumentos del subproceso.

```python
from core.infrastructure.gateway import TIAProcessGateway
```

#### `core/infrastructure/config_manager.py` — *ConfigManager*

Lee `infrastructure/config.json` y expone el mapeo entre tipos de dispositivo del Excel y nombres reales de tablas en TIA Portal. Soporta multi-departamento (`department="alimentacion"`). API: `get_global_config_table_name()`, `get_dispositivo_config(key)`, `get_tag_table_name(key)`, `get_db_name(key)`, `get_db_array_name(key)`, `list_keys()`, `get_tia_folder_proceso()`, `get_tia_folder_dispositivos()`, `get_tia_folder_nmax()`.

**Resolución del path** (vía `core/infrastructure/config_paths.py:resolve_config_path()` cuando se llama sin `config_path`):
- `$ZC_CONFIG_DIR/config.json` si está definido.
- **Frozen** (`.exe`): `<exe_dir>/config/config.json`. Si no existe, se copia del bundleado en primera ejecución (el operario puede editarlo sin recompilar).
- **Dev** (`python main_tray.py`): `<cwd>/infrastructure/config.json` (el del repo, sin copia).
- Fallback readonly al bundleado si no se puede escribir (CD-ROM, red readonly).

Política: **el usuario gana siempre**. NO se sobreescribe un `config.json` existente. Para resetear, borrar el archivo y reiniciar.

```python
from core.infrastructure.config_manager import ConfigManager

# Modo típico (dev o frozen con auto-copia):
config = ConfigManager()  # usa resolve_config_path()

# Explícito (compat 100% con código legacy y tests):
config = ConfigManager("infrastructure/config.json")

# Multi-departamento:
config = ConfigManager(department="alimentacion")
```

#### `core/infrastructure/parsers/excel_parser.py` — *Parser Excel genérico*

Extrae dos tipos de datos del mismo libro: **dimensiones** (`N_MAX_`, `Num_Disp_`) y **DTOs por hoja** (forma cruda). `load_workbook(read_only=True, data_only=True)` para mínimo impacto de memoria.

#### `core/infrastructure/xml/` — *Manipulación SimaticML*

- `modifiers.py` — `TagTableModifier` (clona nodos `PlcTag` desde plantilla; idempotente).
- `tag_table_parser.py` — `SimaticMLTagParser.parse_user_constants()` (extrae `PlcUserConstant` con wildcard XPath `{*}`).
- `user_constants_modifier.py` — `UserConstantsModifier` (añade `PlcUserConstant` con estructura canónica completa).
- `plc_tag_table_manager.py` — `PlcTagTableManager` (crea PlcTagTable nuevas / marca para eliminación).

Tras el PR `855b414` los modifiers rompen un ciclo de imports local con un `Protocol` declarado en el propio módulo, evitando que la capa de aplicación tenga que importar tipos del OT.

#### `core/infrastructure/sd/modifiers.py` — *Modificador .s7dcl*

`SDModifier.insert_calls(call_names)` inyecta llamadas de instancia entre los marcadores `// AUTO_GEN_START` / `// AUTO_GEN_END`. Idempotente.

#### `core/infrastructure/tia/worker_tia.py` — *Motor OT (subprocess)* ⭐

**EL ÚNICO ARCHIVO DEL PROYECTO QUE IMPORTA `siemens_tia_scripting`** (los handlers de áreas no importan el wrapper; reciben `(portal, ts, args)`).

**Ciclo de vida** (en `main()`):
1. Carga dinámica del wrapper vía `_load_siemens_wrapper()` (sys.path + PATH + os.add_dll_directory).
2. `ts.set_logging(path="worker_openness.log", console=False)` — silencia stdout C++.
3. Reconfigura I/O a UTF-8 (la reconfig de `main.py` no se hereda al subproceso).
4. Lee payload JSON de STDIN.
5. Valida `command` ∈ `COMMAND_REGISTRY`.
6. `ts.attach_portal(portal_mode=ts.Enums.PortalMode.AnyUserInterface)`.
7. Despacha al handler.
8. Emite JSON final a STDOUT.
9. `finally`: `portal.detach()` (libera RCW de .NET).

**COMMAND_REGISTRY genérico** (~23 comandos): ciclo de vida, inspección, compilación, export/import SimaticSD y SimaticML, constantes N_MAX, lotes transaccionales.

**Comandos prohibidos en lotes** (`_TRANSACTION_FORBIDDEN_COMMANDS`): `open_project`, `close_project`, `save_project`, `list_plcs`, `compile_plc`, `execute_transactional_batch`.

#### `core/infrastructure/tia/command_loader.py` — *load_extra_commands*

Descubre y carga los comandos extra aportados por las áreas. Itera `AreaRegistry.discover().all()` e invoca `contributes_tia_commands(registry)` en cada spec, que **muta in-place** el `COMMAND_REGISTRY` del worker. Se llama una sola vez al arrancar el worker (justo antes del `main()`).

#### `core/interfaces/mcp_server.py` — *Shell FastMCP*

Factoría que construye un servidor FastMCP con las tools genéricas + las tools aportadas por las áreas vía `AreaRegistry.discover().for_each("contributes_mcp_tools", mcp=mcp)`. Es la **cara agéntica** del sistema (LLM/MCP).

```python
from core.interfaces.mcp_server import create_mcp_server
```

#### `core/models/` — *Scaffolding*

Placeholders para los modelos del dominio. La mayoría de modelos del proyecto actual viven en `areas/alimentacion/domain/models/` (modelos del bounded context). Esta carpeta se conserva por la convención histórica del layout Clean.

### 📁 `areas/alimentacion/` — Bounded Context del departamento Alimentación

Paquete autocontenido que **se autodescribe** con un `AreaSpec` en su `__init__.py`. Aporta los 7 extension points disponibles hoy:

- **Modelos de dominio** en `domain/models/dispositivos.py` (Dispositivo, DispED/EA/SA/V/M/M_VF, DimensionesDispositivos).
- **Catálogo de presentación** en `domain/disp_catalog.py::build_catalog` (consumido por `GET /api/v1/catalog`).
- **Casos de uso de sync** en `application/use_cases/`:
  - `disp_diff_constants.py::DispCalculateConstantsDiffUseCase` (motor puro de diffs N_MAX y renombres).
  - `disp_sync_instances.py::DispSyncInstancesUseCase` (sync completo N_MAX + devices, preview/apply en una sola transacción COM).
  - `disp_sync_comentarios.py::DispComentariosSyncUseCase` (aplicar comentarios por instancia).
- **Parser Excel corporativo** en `infrastructure/parsers/alimentacion_excel_parser.py` (compone `ExcelParser` y devuelve `dict[str, list[IHardwareDevice]]` tipado).
- **Modificadores SD offline** en `infrastructure/sd/` (comentarios por instancia + registro MLC).
- **Comandos transaccionales extra al COMMAND_REGISTRY** en `infrastructure/tia/extra_commands.py`:
  - 6 × `update_disp_comments_db_<hw>` (uno por tipo de dispositivo).
  - `commit_devices_sync` (orquestador transaccional que llama a `COMMAND_REGISTRY["execute_transactional_batch"]`).
- **3 routers web** en `interfaces/web/` (`alimentacion`, `sync`, `excel`) cableados a `contributes_routers`.
- **4 tools MCP** en `interfaces/mcp/tools.py` (preview/commit, aplicar comentarios, upload excel) cableadas a `contributes_mcp_tools`.
- **Manifest del área para la SPA** en `frontend/manifest.js` (shape JS) y `frontend/manifest.py` (espejo Python, URLs strings).
- **Back-compat de las 6 properties legacy en AppState** vía `application/disp_state_extensions.install`.
- **Defaults defensivos del ConfigManager** vía `infrastructure/config_defaults.install`.

### 📁 `launcher/` — Bandeja del sistema (modo dev)

- `tray_app.py` — `run_tray()` arma el icono `pystray`, el menú y el loop. NO instancia el gateway.
- `web_supervisor.py` — `WebServiceSupervisor` (start/stop/is_alive del proceso uvicorn en background, gestión de logs).
- `make_icon.py` + `icon.ico` — Asset del icono.

### 📁 `interfaces/web_server/` — Shell FastAPI

- `app.py` — `create_app(gateway)` es el composition root del shell web. Crea la app FastAPI, monta `STATIC_DIR` y los routers. Itera `AreaRegistry.discover().for_each("contributes_routers", app=app)` para incluir routers de las áreas.
- `dependencies.py` — `get_gateway`, `get_app_state`, `get_config_manager`, `get_logger`, `get_progress_tracker` (instancias Singleton vía `Depends`).
- `routers/`:
  - `areas.py` — `GET /api/v1/areas` (lista de áreas vía `ListAreasUseCase`).
  - `area_manifests.py` — `GET /api/v1/areas/<id>/manifest` (manifest del área para la SPA).
  - `catalog.py` — `GET /api/v1/catalog` (fusión de los `contributes_catalog` de todas las áreas).
  - `diagnostics.py` — `GET /api/v1/progress` y `GET /api/v1/logs` (paneles de feedback).
  - `portal.py` — endpoints de ciclo de vida TIA (open/close/save/list_plcs/list_blocks/compile).
- `static/` — SPA Vue 3 ESM (`index.html`, `styles.css`, `js/{main,store,api,area-loader}.js`, `js/components/{ConsolaLogs,ProgressIndicator,Welcome}.js`, `src/input.css`).

### 📁 `infrastructure/`

Solo contiene `config.json` (mapeo multi-departamento). El resto de la infraestructura está en `core/infrastructure/`. Este `infrastructure/config.json` se mantiene en su path histórico para que el `ConfigManager` (que lo busca relativo al CWD) siga funcionando.

### 📁 `tests/`

254 tests pytest (252 ok + 2 skipped por dependencia opcional de `_source/`). Se ejecutan con `python -m pytest tests/ -v` y deben pasar todos antes de commitear. Patrones de mock: `MagicMock(spec=TIAProcessGateway)` para el gateway; el `ProgressTracker` se instancia real y se inyecta al use case. Naming: `test_<modulo>.py` o `test_area_<área>_<feature>.py`.

### 📁 `scripts/`

Smoke tests manuales del operario (`smoke_main_tray.py`, `test_industrial_theme.py`, `test_nmax_apply.py`, `test_rename_device.py`). **No** los ejecuta CI; son utilidades de debugging rápido.

---

## 🔧 Patrones de Uso

### Ejemplo 1: Listar PLCs vía worker OT

```bash
echo '{"command":"list_plcs","args":{}}' | python main.py --worker
```

**Respuesta**:
```json
{"ok": true, "result": ["PLC1_Alimentacion", "PLC2_Empaquetado"]}
```

---

### Ejemplo 2: Compilar un PLC (semántica booleana invertida)

```python
# Desde el cliente MCP/LLM o el router FastAPI
has_errors = await gateway.compile_plc("PLC1_Alimentacion")
if has_errors is False:
    print("Compilación exitosa")
else:
    print("Hay errores, revisar TIA Portal")
```

---

### Ejemplo 3: Sincronizar N_MAX + dispositivos desde Excel (previsualizar)

```python
from core.infrastructure.gateway import TIAProcessGateway
from core.infrastructure.config_manager import ConfigManager
from core.application.state import get_app_state
from areas.alimentacion.application.use_cases.disp_sync_instances import (
    DispSyncInstancesUseCase,
)

gateway = TIAProcessGateway()
config = ConfigManager("infrastructure/config.json")
state = get_app_state()  # Singleton con Excel ya cargado

use_case = DispSyncInstancesUseCase(
    gateway=gateway, config_manager=config, state=state,
)

# PREVIEW: solo calcula diff, NO toca TIA.
prevision = await use_case.generar_prevision("PLC1_Alimentacion")
print(prevision["summary"])  # {agregados, eliminados, renombrados, nmax...}

# APPLY: el mismo use case recalcula y aplica en UNA transacción COM.
# El body de /api/v1/sync/commit es {plc_name, prevision}; los flags
# de bypass legacy (enable_nmax, enable_renames, enable_devices) se
# eliminaron — la transacción es siempre completa.
result = await use_case.ejecutar_transaccion(
    plc_name="PLC1_Alimentacion",
    prevision=prevision,
)
# Tras éxito, invocar compile_plc para asentar el modelo de memoria.
await gateway.compile_plc("PLC1_Alimentacion")
```

---

### Ejemplo 4: Listar áreas operativas

```python
from core.application.area_registry import (
    AreaInfo, ListAreasUseCase, AreaSpec, AreaRegistry,
)
from core.infrastructure.config_manager import ConfigManager

cm = ConfigManager("infrastructure/config.json")
areas: list[AreaInfo] = ListAreasUseCase(cm).execute()
# → [{key:"alimentacion", label:"Área Alimentación", icon:"🍞", available:True}, ...]

# Para iterar los hooks de las áreas (p. ej. el shell web):
for spec in AreaRegistry.discover().all():
    print(spec.id, spec.label)
```

---

### Ejemplo 5: Lote transaccional genérico

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

## ⚙️ Configuración Dinámica

`infrastructure/config.json` define el mapeo entre tipos lógicos del dominio y nombres reales de tablas PLC, DBs y carpetas en TIA Portal, agrupado por **departamento** (Bounded Context).

### Estructura completa

```json
{
  "_comment": "Configuración multi-departamento. Cada departamento encapsula su jerarquía TIA y sus tipos de dispositivo. Para añadir un nuevo departamento, duplicar el bloque 'alimentacion' bajo 'departments' y ajustar los valores.",
  "departments": {
    "alimentacion": {
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

La estructura está envuelta en `departments.<nombre>` para que en el futuro se añadan más departamentos sin colisionar. Para añadir uno nuevo:

1. Duplicar el bloque `alimentacion` bajo `departments` con el nombre del nuevo departamento.
2. Ajustar `global_config_table_name`, `tia_folders` y `Dispositivos` según la realidad del PLC.
3. Instanciar el `ConfigManager` apuntando al nuevo departamento:
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

### Claves soportadas (dentro de `departments.<departamento>`)

| Clave | Tipo | Descripción |
|---|---|---|
| `global_config_table_name` | `str` | Nombre de la tabla PLC con las PlcUserConstant N_MAX. |
| `tia_folders.proceso` | `str` | Carpeta TIA con los bloques del proceso. |
| `tia_folders.dispositivos` | `str` | Carpeta TIA con las tablas de dispositivos. |
| `tia_folders.nmax` | `str` | Carpeta TIA donde reside `000_Config_Dispositivos`. Default: `000_Sistema`. |
| `Dispositivos.<key>.db_name` | `str` | Nombre del DB asociado al tipo. |
| `Dispositivos.<key>.db_array_name` | `str` | Nombre del array dentro del DB. |
| `Dispositivos.<key>.tag_table` | `str` | Nombre de la PlcTagTable del tipo. |
| `Dispositivos.<key>.config_table` | `str` | PlcTagTable con las N_MAX (típicamente `000_Config_Dispositivos`). |

### Tipos de dispositivo soportados (departamento `alimentacion`)

| key | DB | Tag Table | Descripción |
|---|---|---|---|
| `ed` | `DB2000_ED` | `2000_Disp_ED` | Entradas Digitales |
| `ea` | `DB2001_EA` | `2000_Disp_EA` | Entradas Analógicas |
| `sa` | `DB2006_SA` | `2000_Disp_SA` | Salidas Analógicas |
| `v` | `DB2010_V` | `2000_Disp_V` | Válvulas |
| `m` | `DB2015_M` | `2000_Disp_M` | Motores |
| `m_vf` | `DB2016_M_VF` | `2000_Disp_M_VF` | Motores con Variador de Frecuencia |

### Fallbacks defensivos

- `global_config_table_name` ausente → retorna `"000_Config_Dispositivos"`.
- Bloque `departments` ausente → defaults en todos los getters.
- Sección `Dispositivos` ausente → `list_keys()` retorna `[]`.
- Sección `tia_folders` ausente → defaults a `"003_Procesos"`, `"2000_Dispositivos"` y `"000_Sistema"`.
- `tia_folders.nmax` ausente → default `"000_Sistema"`.
- Departamento solicitado no existe → fallback al primer departamento disponible (con warning).
- `key` no existe → `None` + `logger.warning` (NO raise).
- Campos parciales en un tipo → valores vacíos (`""`).

**El caso de uso NUNCA debe hardcodear nombres de tabla** (legacy usaba hardcodes como `"000_Config_Dispositivos"` que se han eliminado).

---

## 🧩 Bounded Contexts y AreaRegistry

El proyecto se organiza en **Bounded Contexts**: cada departamento (alimentación, futuras áreas) vive en `areas/<área>/` con su propio `domain/`, `application/`, `infrastructure/`, `interfaces/` y `frontend/`. El `core/` contiene lo transversal (gateway, config, parsers genéricos, shell MCP/web, registro de áreas).

### El contrato `AreaSpec`

Cada área declara en su `__init__.py` un `AreaSpec` (dataclass frozen) con los extension points que implementa:

```python
from core.application.area_registry import AreaSpec

AREA_SPEC = AreaSpec(
    id="alimentacion",
    label="Alimentación",
    icon="🍞",
    config_block="alimentacion",
    contributes_routers=register_routers,             # FastAPI
    contributes_tia_commands=register_tia,            # COMMAND_REGISTRY
    contributes_mcp_tools=register_mcp,               # @mcp.tool()
    contributes_frontend_manifest=build_manifest,     # SPA
    contributes_state_extensions=install_state,       # AppState back-compat
    contributes_config_defaults=install_defaults,     # ConfigManager defaults
    contributes_catalog=build_alim_catalog,           # GET /api/v1/catalog
)
```

### Cómo se invoca

Los composition roots (web `app.py`, MCP `mcp_server.py`, TIA worker `command_loader.py`) descubren las áreas con `AreaRegistry.discover()` e invocan los hooks con `for_each(hook, **kwargs)`:

```python
from core.application.area_registry import AreaRegistry

# Descubrir una sola vez al arrancar.
for spec in AreaRegistry.discover().all():
    print(spec.id, spec.label)

# Iterar los routers del área en el shell FastAPI:
AreaRegistry.discover().for_each("contributes_routers", app=fastapi_app)

# Iterar los comandos OT extra del área en el worker:
AreaRegistry.discover().for_each("contributes_tia_commands", registry=COMMAND_REGISTRY)
```

`GET /api/v1/catalog` (router en `interfaces/web_server/routers/catalog.py`) itera `for spec in AreaRegistry.discover().all()` y fusiona los diccionarios que cada área aporta en su hook `contributes_catalog`. El shell NO conoce áreas concretas: una nueva área que implemente `contributes_catalog` aparece automáticamente.

### Cómo añadir una nueva área

Pasos resumidos (ver `AGENTS.md` para el detalle completo):

1. Crear `areas/<area_id>/` con `__init__.py` que defina `AREA_SPEC = AreaSpec(...)`.
2. Si el área tiene modelos de dominio: `areas/<area>/domain/`.
3. Si tiene casos de uso: `areas/<area>/application/use_cases/`.
4. Si tiene adaptadores: `areas/<area>/infrastructure/`.
5. Si tiene comandos TIA transaccionales: `areas/<area>/infrastructure/tia/extra_commands.py` con `register(registry)`.
6. Si tiene routers FastAPI: `areas/<area>/interfaces/web/` con `register_routers(app)`.
7. Si tiene tools MCP: `areas/<area>/interfaces/mcp/tools.py` con `register(mcp)`.
8. Si tiene UI: `areas/<area>/frontend/components/` + `areas/<area>/frontend/manifest.js` + `manifest.py`.
9. Añadir el bloque en `infrastructure/config.json` bajo `departments.<area_id>`.
10. Tests: `tests/test_area_<area_id>_*.py` con `MagicMock(spec=TIAProcessGateway)`.

Las áreas **NO importan** `siemens_tia_scripting` directamente (regla `.clinerules` §1): solo aportan `Callable` que el worker invocará en su proceso. Los handlers extra pueden usar comandos genéricos del registry (`COMMAND_REGISTRY["export_block"](...)`) para participar de transacciones atómicas con ellos.

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

**Artefacto final**: `dist/zc_automation_suite.exe` — un único binario que incluye:
- Intérprete Python embebido.
- `main.py` + todo el código del proyecto (core, areas, launcher, interfaces).
- El `.pyd` nativo de Siemens.
- Las dependencias (`fastmcp`, `openpyxl`, etc.).

### Ejecución del binario

```cmd
dist\zc_automation_suite.exe
:: o doble-clic: arranca la bandeja del sistema
```

---

## 🧪 Testing

```cmd
pip install pytest
python -m pytest tests/ -v
```

**Estado actual**: 254 tests (252 ok + 2 skipped por dependencia opcional de `_source/`).

### Convenciones

- **Backend**: mockear el gateway con `MagicMock(spec=TIAProcessGateway)`. Para `ProgressTracker`, instanciar uno limpio (`ProgressTracker()`) y pasarlo al use case (no mockear el tracker).
- **Frontend**: sin tests automatizados (SPA ESM sin build step). QA manual con `?demo=1` y servidor de pruebas.
- **Naming**: `tests/test_<modulo>.py` o `tests/test_area_<área>_<feature>.py`.

### Tests de humo (scripts/)

Los scripts en `scripts/` (smoke `main_tray`, test del tema industrial, N_MAX apply, rename device) son utilidades **manuales** del operario, no se ejecutan en CI.

---

## 📋 Convenciones de Desarrollo

Resumen de las directrices en `.clinerules` (corto) y `AGENTS.md` (medio):

1. **Aislamiento de capas**:
   - `core/` no importa de `interfaces/`. Las áreas importan del core; el core no conoce las áreas (excepto `area_registry.py` por convención).
   - Las áreas no importan entre sí: comparten vía `core/`.

2. **Aislamiento IT/OT**:
   - **`siemens_tia_scripting` SOLO se importa en `core/infrastructure/tia/worker_tia.py`**. Los handlers de áreas (en `areas/<área>/infrastructure/tia/extra_commands.py`) reciben `(portal, ts, args)` y NO importan el wrapper.
   - Cualquier intento de importarlo en otra capa es un bug crítico.

3. **Tipado estricto**: todas las funciones públicas llevan anotaciones de tipo. Sin `Any` en modelos de dominio.

4. **Python moderno**: `from __future__ import annotations`, `match/case` cuando aplique, `asyncio.to_thread` para CPU-bound.

5. **No retención de estado OT**: el worker mapea objetos nativos a primitivos (`list`, `dict`, `str`, `bool`) antes de emitir JSON.

6. **Compatibilidad**: Python 3.12, 3.13, 3.14. Sin 3.11 ni anteriores.

7. **Idempotencia**: cualquier modificador offline (XML/SD) debe ser idempotente — aplicar dos veces no duplica instancias.

8. **Lotes transaccionales**: usar `gateway.execute_transactional_batch` para todas las mutaciones múltiples atómicas.

9. **Progress tracking** (`.clinerules` §7): operaciones >500 ms DEBEN emitir progreso a `ProgressTracker`. Tests mockean `ProgressTracker` directamente, NO el endpoint.

10. **Single-tenant** (`.clinerules` §8): `ProgressTracker`, `LogBuffer`, `AppState` son Singletons. Si llega un nuevo `begin()` con uno activo, OVERWRITE + warning. NUNCA persistir entre reinicios.

11. **CSS / Frontend** (`.clinerules` §9): tras añadir clases nuevas en cualquier `.js` de `static/js/`, SIEMPRE recompilar Tailwind:
    ```
    tailwindcss-extra.exe -i interfaces/web_server/static/src/input.css -o interfaces/web_server/static/styles.css --minify
    ```
    (o `run_tailwind.bat` si existe). Sin CDN, sin daisyUI, sin CSS externo. Tema: tokens semánticos `bg-surface*`, `text-ink*`, `bg-accent`, `border-line`. PROHIBIDO string literals multi-línea dentro de arrays de `:class`.

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
| Tests fallan con `ImportError: cannot import name 'X' from 'core.X'` | Algún módulo quedó con un import legacy de la etapa pre-refactor. | Buscar el import roto y actualizarlo a la ruta nueva (`core.application.X`, `core.infrastructure.X`, `areas.<area>.X`). |
| `POST /api/v1/sync/commit` rechaza flags `enable_nmax/enable_renames/enable_devices` | Los flags se eliminaron en PR `729ec5b`; el body es solo `{plc_name, prevision}`. | Quitar los flags del body. La transacción es siempre completa. |

---

## 🤝 Cómo Contribuir

Para mantener la coherencia arquitectónica:

1. Lee **`.clinerules`** (reglas críticas, se carga siempre) y **`AGENTS.md`** (convenciones operativas) antes de cualquier cambio significativo.
2. Si añades una **operación OT genérica** (la usan todas las áreas), edita `core/infrastructure/tia/worker_tia.py`, añade el handler y regístralo en `COMMAND_REGISTRY`. Si es **específica de un área**, edita `areas/<área>/infrastructure/tia/extra_commands.py` con su `register(registry)` (el `command_loader` lo descubre al arrancar).
3. Si modificas un **caso de uso** (`core/application/` o `areas/<área>/application/`), respeta el contrato de DI: el use case recibe gateway, config_manager y (si aplica) state/progress por constructor. NO usa Singleton/global.
4. Si modificas el **dominio** (`core/models/` o `areas/<área>/domain/`), respeta las restricciones: sin `siemens_tia_scripting`, sin `Any` en atributos, sin openpyxl.
5. Tras añadir **clases Tailwind nuevas** en cualquier `.js` de `static/js/`, SIEMPRE recompila Tailwind (ver `.clinerules` §9).
6. Ejecuta `python -m pytest tests/ -v` antes de commitear — 254 tests deben pasar.
7. Verifica que los modificadores offline siguen siendo idempotentes.
8. Cualquier **plan de orquestación AI** (mavis-team, planes de trabajo) debe ir a `.minimax/`, que ya está en `.gitignore`. No commitear esos YAML.
9. Los **volcados de TIA** del operario (`.s7dcl`, `.s7res`, XMLs del PLC de producción) van a `_source/` (también en `.gitignore`). No commitearlos.
10. Una sola rama (`main`). La rama `Main` con mayúscula huérfana se eliminó; no reintroducirla.

---

## 📄 Licencia

Este proyecto está licenciado bajo la **MIT License**. Ver el archivo [LICENSE](LICENSE) para los detalles completos.

```
MIT License
Copyright (c) 2026 Aketzabarragues
```

---

**¿Encontraste un bug o tienes una sugerencia?** Por favor abre un issue en el repositorio incluyendo:
- Logs del worker (`worker_openness.log`).
- Payload JSON exacto que disparó el problema.
- Versión de TIA Portal y Python.
