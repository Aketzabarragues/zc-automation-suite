# Arquitectura

> Documento técnico de referencia. Complementa a [`.clinerules`](../.clinerules) (reglas arquitectónicas críticas) y a [`AGENTS.md`](../AGENTS.md) (guía de extensión paso a paso).
>
> Público: desarrollador que va a tocar el código o extender el sistema.

## Tabla de contenidos

1. [Visión general](#1-visión-general)
2. [Worker OT persistente (state machine)](#2-worker-ot-persistente-state-machine)
3. [Contrato IPC](#3-contrato-ipc)
4. [TIAProcessGateway — API pública](#4-tiaprocessgateway--api-pública)
5. [COMMAND_REGISTRY — comandos del worker](#5-command_registry--comandos-del-worker)
6. [Bounded Contexts y AreaSpec](#6-bounded-contexts-y-areaspec)
7. [Estructura del repositorio](#7-estructura-del-repositorio)
8. [Configuración (`infrastructure/config.json`)](#8-configuración-infrastructureconfigjson)
9. [ProgressTracker, LogBuffer, AppState](#9-progresstracker-logbuffer-appstate)
10. [Convenciones operativas](#10-convenciones-operativas)

---

## 1. Visión general

El proyecto resuelve el problema clásico de TIA Openness: la **incompatibilidad entre el modelo asíncrono de Python y el modelo síncrono COM** de Siemens (los punteros RCW de .NET no son thread-safe). Para evitar `COMException` y corrupciones del RCW, el sistema aísla la carga de `siemens_tia_scripting` en un subproceso separado (el "worker OT"), comunicado con el proceso principal (el "IT") únicamente por JSON sobre `stdin`/`stdout`.

Dos modos de ejecución del worker:

- **Modo persistente** (modo web, principal en producción): el subproceso se queda vivo entre comandos. Un `attach_portal` al inicio, N comandos sobre el mismo attach, `detach_portal` cuando el operario desconecta. Arranca en `idle` (sin portal); el operario decide cuándo conectar desde el topbar.
- **Modo 1-shot** (`--worker`, compatibilidad y tests): un subproceso efímero por comando. Un attach → un comando → un detach → muere.

Ambos modos comparten el mismo `COMMAND_REGISTRY` y los mismos handlers; el gateway elige cuál usar según el contexto (web → persistente; MCP → 1-shot).

### Capas

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
│   │                            · log_buffer.py · log_paths.py    │   │      singletons)
│   └────────────┬─────────────────────────────────────────────────┘   │
│                │ usa                                                  │
│   ┌────────────▼─────────────────────────────────────────────────┐   │
│   │  core/infrastructure/  ← OT + IO transversales                │   │  ← Capa de Infraestructura
│   │   gateway.py · config_manager.py · config_paths.py           │   │     (gateway, parsers,
│   │   build_cache.py · cache/ · parsers/ · xml/ · sd/            │   │      modificadores XML/SD)
│   │   tia/worker_tia.py (genérico) · tia/command_loader.py       │   │
│   └────────────┬─────────────────────────────────────────────────┘   │
│                │ usa (solo modelos)                                   │
│   ┌────────────▼──────────────┐                                      │  ← Capa de Dominio
│   │  core/models/             │                                      │     (dataclasses frozen,
│   │   bloque_cache.py         │                                      │      DTOs)
│   │   bloque_plc.py           │                                      │
│   └───────────────────────────┘                                      │
│                                                                     │
│ ┌─────────────────────────────────────────────────────────────────┐ │
│ │  areas/<área>/  ← Bounded Context autocontenido por departamento│ │
│ │   alimentacion/                                                 │ │
│ │    domain/  application/  infrastructure/                       │ │
│ │    interfaces/  frontend/                                      │ │
│ │    __init__.py exporta un AreaSpec (AreaRegistry lo descubre)   │ │
│ └─────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘

Dirección de dependencias: ↑ solo hacia arriba. NUNCA hacia abajo.
Las áreas importan del core; el core NO conoce las áreas.
```

---

## 2. Worker OT persistente (state machine)

El worker corre como subproceso. Su ciclo de vida (modo persistente) se gestiona desde `core/infrastructure/tia/worker_tia.py::main_persistent_loop`:

```
                    ┌─────────────────────────────────────────────┐
                    │   Subproceso worker (vive toda la sesión)   │
                    │                                             │
   startup ─────►   │   ┌───────┐  attach_portal   ┌──────────┐  │
   (gatewaay         │   │ idle  │ ───────────────►│ connected│  │
    lo lanza)        │   │       │ ◄───────────────│          │  │
                    │   └───────┘  detach_portal   └──────────┘  │
                    │        ▲                       │           │
                    │        │ re-attach defensivo   │           │
                    │        │ (TIA cerrado a media  │           │
                    │        │  sesión)              │           │
                    │        └───────────────────────┘           │
                    └─────────────────────────────────────────────┘
```

**Estados** (gateway: `gateway._connection_state`):

| Estado | Significado | Quién lo dispara |
|---|---|---|
| `idle` | Worker vivo, sin portal attached. Estado inicial. | Startup / `disconnect()` / tras error recuperable. |
| `connecting` | `attach_portal` en curso. | `connect()` al pulsar el botón. |
| `connected` | Portal attached. Listo para comandos. | `attach_portal` OK. |
| `error` | Attach o último comando falló. | Excepción en `connect()` o comando. |

**Comandos del state machine** (no están en `COMMAND_REGISTRY`, se gestionan en línea en `main_persistent_loop`):

- `attach_portal` (args: `{"mode": "WithGraphicalUserInterface" | "WithoutGraphicalUserInterface"}`): llama `ts.attach_portal`, devuelve `{"pid": <int>}` o `{"error": "..."}`.
- `detach_portal`: llama `portal.detach()` si `portal is not None`, devuelve `{"detached": true}`.

**Re-attach defensivo**: si llega un comando y el portal murió (TIA cerrado a media sesión), el worker intenta un re-attach antes de fallar. Limitación conocida: si el operario acaba de pulsar "Desconectar" y llega un comando justo en ese momento, el re-attach puede revivir un portal que el operario quería desconectar. Bajo impacto: basta con re-disconnect.

**Endpoint REST del topbar**:

- `GET  /api/v1/tia/connection` → estado del worker + proyecto + PLCs + `project_changed` (one-shot) + `worker_alive` + `pid`.
- `POST /api/v1/tia/connect` → fuerza el attach.
- `POST /api/v1/tia/disconnect` → fuerza el detach (worker sigue vivo en `idle`).

---

## 3. Contrato IPC

El gateway y el worker se comunican exclusivamente por JSON sobre `stdin`/`stdout` (línea a línea, UTF-8).

**Request** (gateway → worker, una línea por stdin):

```json
{"id": 1, "command": "list_plcs", "args": {}}
```

**Response OK** (worker → gateway, una línea por stdout):

```json
{"id": 1, "ok": true, "result": ["PLC1_Alimentacion", "PLC2_Empaquetado"]}
```

**Response ERROR**:

```json
{"id": 1, "ok": false, "error": "RuntimeError: Timeout tras 300s..."}
```

**Logs internos** (C++/.NET de Siemens, trazas): van a `stderr`. El gateway los ignora.

**Detección de interferencias**: la DLL C++ de Siemens puede loguear en stdout. El gateway extrae la **última línea `{...}`** parseable como JSON, descartando ruido anterior.

**Signal `ready_idle` (id=0, reservado)**: en modo persistente, el worker emite este mensaje justo después de arrancar, antes del primer comando. El gateway lo lee para confirmar que el subproceso está vivo.

**Comando `exit`**: cierra el loop persistente limpiamente.

---

## 4. TIAProcessGateway — API pública

`core/infrastructure/gateway.py::TIAProcessGateway` es el **único módulo** que sabe cómo lanzar el subproceso OT. Toda la comunicación con TIA Portal pasa por aquí.

### Ciclo de vida del worker persistente (solo `persistent=True`)

| Método | Descripción |
|---|---|
| `async start()` | Arranca el subproceso persistente y espera el `ready_idle`. Idempotente. |
| `async connect()` | Envía `attach_portal`, transiciona a `connected`. Lanza `TIAConnectionError` si ya está conectado, si no es persistente, o si el attach falla. |
| `async disconnect()` | Envía `detach_portal`, transiciona a `idle`. El worker **sigue vivo**. |
| `async reconnect()` | disconnect + connect atómico. |
| `async ping() -> dict` | Health check contra el portal attached (no requiere proyecto abierto). |
| `is_worker_alive() -> bool` | True si el subproceso worker está vivo (ortogonal a `state`). |
| `consume_project_changed() -> bool` | One-shot: True si el operario abrió un proyecto distinto en TIA Portal sin pasar por la app. |

### Inspección

| Método | Descripción |
|---|---|
| `async get_plcs(force_refresh=False) -> list[str]` | Lista de PLCs del proyecto activo. |
| `async get_project_info(force_refresh=False) -> dict` | Metadata del proyecto abierto. |
| `async get_blocks(...)` / `async scan_plc_blocks(...)` | Bloques + tag tables + UDTs (cacheados en `gateway._bloques_cache`). |

### Ciclo de vida del proyecto (modo 1-shot o persistente)

| Método | Descripción |
|---|---|
| `async open_new_portal(project_file_path: str) -> bool` | Cold start: lanza TIA Portal NUEVO y abre un proyecto. Requiere path absoluto. |
| `async attach_portal() -> bool` | Hot-attach a una instancia YA EJECUTÁNDOSE. |
| `async open_project(project_file_path: str) -> None` | Abre un proyecto en el portal attached. Invalida caché. Requiere path absoluto. |
| `async save_project() -> None` | Guarda el proyecto activo. |
| `async close_project() -> None` | Cierra el proyecto activo. |

### Compilación y export/import

| Método | Descripción |
|---|---|
| `async compile_plc(plc_name: str) -> bool` | Compila un PLC. **Semántica booleana invertida**: `True` = hay errores (al revés que el API nativo de Siemens). |
| `async export_blocks_sd(plc_name, target_dir) -> str` | Export masivo Simatic Source Documents (`.s7dcl`/`.s7res`). |
| `async export_udts_sd(plc_name, target_dir) -> str` | Igual pero solo UDTs. |
| `async export_plc_tags_xml(...)` | Export masivo SimaticML (XML) de las tag tables de un PLC. |
| `async import_blocks_sd(...)` | Import masivo de `.s7dcl`/`.s7res`. |
| `async import_plc_tags_xml(...)` | Import masivo de XML. |
| `async export_block(...)` / `async import_block(...)` | Bloques granulares. |
| `async export_tag_table(...)` / `async import_tag_table(...)` | Tablas de variables granulares. |

### Constantes de usuario (N_MAX)

| Método | Descripción |
|---|---|
| `async get_user_constants(...)` | Lee PlcUserConstant de una tabla. |
| `async update_user_constant_value(plc_name, table_name, constant_name, new_value)` | Cambia el valor. |
| `async update_user_constant_name(plc_name, table_name, old_name, new_name)` | Renombra. |
| `async delete_user_constant(...)` | Elimina. |

### Lotes transaccionales

| Método | Descripción |
|---|---|
| `async execute_transactional_batch(operations, undo_text)` | Lote con rollback atómico. Comandos prohibidos dentro del lote: `open_project`, `close_project`, `save_project`, `list_plcs`, `compile_plc`, `execute_transactional_batch`. |
| `async commit_devices_sync(...)` | Commit específico del área alimentación: N_MAX + renames + devices en una sola transacción. |
| `async update_disp_instance_comments_batch(...)` | Aplica comentarios a instancias de dispositivos. |

### Excepciones

- `TIAConnectionError(RuntimeError)`: TIA Portal no responde o no se puede adjuntar. Indica que la caché del gateway puede contener datos stale y debe limpiarse.

### Caché

- `clear_cache()`: vacía la caché general y la caché especializada de bloques.

### Timeouts

- Default: `DEFAULT_GATEWAY_TIMEOUT = 300s` (env var `ZC_GATEWAY_TIMEOUT`).
- Timeouts operacionales por comando (constantes de clase, modificables): `READY_IDLE_TIMEOUT_S=60`, `HEARTBEAT_PING_TIMEOUT_S=10`, `DEFAULT_DISPATCH_TIMEOUT_S=180`, `ATTACH_PORTAL_TIMEOUT_S=60`, `DETACH_PORTAL_TIMEOUT_S=10`, `GET_PROJECT_INFO_TIMEOUT_S=10`, `GET_PLCS_TIMEOUT_S=10`.

---

## 5. COMMAND_REGISTRY — comandos del worker

`COMMAND_REGISTRY` (en `core/infrastructure/tia/worker_tia.py`) es un `dict[str, Callable[[portal, ts, args], Any]]`. Se registran **24 comandos genéricos** (verificados en `worker_tia.py:1026-1068`):

**Ciclo de vida del proyecto** (4): `open_new_portal`, `open_project`, `save_project`, `close_project`.

**Inspección** (4): `list_plcs`, `get_project_info`, `list_blocks`, `scan_blocks`.

**Mutación / compilación** (1): `compile_plc`.

**Export masivo SimaticSD** (2): `export_blocks_sd`, `export_udts_sd`.

**Export masivo SimaticML** (1): `export_plc_tags_xml`.

**Import masivo desde disco** (2): `import_blocks_sd`, `import_plc_tags_xml`.

**Bloques y tablas granulares** (4): `export_block`, `import_block`, `export_tag_table`, `import_tag_table`.

**Constantes de usuario (N_MAX)** (4): `get_user_constants`, `update_user_constant_value`, `update_user_constant_name`, `delete_user_constant`.

**Lotes transaccionales** (1): `execute_transactional_batch`.

**Health check** (1): `ping`.

Las áreas aportan **comandos adicionales transaccionales** vía `areas/<área>/infrastructure/tia/extra_commands.py::register(registry)`. El command loader (`core/infrastructure/tia/command_loader.py::load_extra_commands`) los descubre al arrancar el worker iterando `AreaRegistry.discover().all()`.

**Importante**: los comandos del state machine (`attach_portal`, `detach_portal`) NO están en el registry. Los gestiona `main_persistent_loop` en línea porque necesitan reasignar la variable local `portal`.

**Importante**: los handlers de área reciben `(portal, ts, args)` y **no importan** `siemens_tia_scripting`. Pueden invocar comandos genéricos del registry (`COMMAND_REGISTRY["export_block"](portal, ts, args)`) para participar de transacciones atómicas.

---

## 6. Bounded Contexts y AreaSpec

Cada departamento (alimentación, futuras áreas) vive en `areas/<área>/` con su propio `domain/`, `application/`, `infrastructure/`, `interfaces/` y `frontend/`. El `core/` contiene lo transversal.

### El contrato `AreaSpec`

`AreaSpec` es un dataclass `frozen=True` declarado en `core/application/area_registry.py`. Cada área lo define en su `__init__.py`:

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

8 hooks opcionales: `contributes_routers`, `contributes_tia_commands`, `contributes_mcp_tools`, `contributes_frontend_manifest`, `contributes_state_extensions`, `contributes_config_defaults`, `contributes_catalog`, más `id`/`label`/`icon`/`config_block`.

### Cómo se invocan

Los composition roots (web `app.py`, MCP `mcp_server.py`, TIA worker `command_loader.py`) descubren las áreas con `AreaRegistry.discover()` e invocan los hooks con `for_each(hook, **kwargs)`:

```python
from core.application.area_registry import AreaRegistry

# Una sola vez al arrancar.
for spec in AreaRegistry.discover().all():
    print(spec.id, spec.label)

# En el shell FastAPI:
AreaRegistry.discover().for_each("contributes_routers", app=fastapi_app)

# En el worker:
AreaRegistry.discover().for_each("contributes_tia_commands", registry=COMMAND_REGISTRY)
```

`GET /api/v1/catalog` (router en `interfaces/web_server/routers/catalog.py`) itera `for spec in AreaRegistry.discover().all()` y fusiona los diccionarios que cada área aporta en su hook `contributes_catalog`. El shell NO conoce áreas concretas: una nueva área que implemente `contributes_catalog` aparece automáticamente.

### Área actual: `alimentacion`

Departamento de alimentación. Aporta:

- **Modelos de dominio** en `domain/models/dispositivos.py` (Dispositivo, DispED/EA/SA/V/M/M_VF, DimensionesDispositivos).
- **Catálogo de presentación** en `domain/disp_catalog.py::build_catalog` (consumido por `GET /api/v1/catalog`).
- **Casos de uso de sync** en `application/use_cases/`: `disp_diff_constants.py::DispCalculateConstantsDiffUseCase`, `disp_sync_instances.py::DispSyncInstancesUseCase`, `disp_sync_comentarios.py::DispComentariosSyncUseCase`, `proc_sync_comentarios.py`, `scan_plc_blocks.py`, `upload_excel.py`.
- **Parser Excel corporativo** en `infrastructure/parsers/alimentacion_excel_parser.py`.
- **Modificadores SD offline** en `infrastructure/sd/` (comentarios por instancia + registro MLC).
- **Modificadores XML offline** en `infrastructure/xml/` (tag table add/remove, parser).
- **Comandos transaccionales extra al COMMAND_REGISTRY** en `infrastructure/tia/extra_commands.py`: 6 × `update_disp_comments_db_<hw>` (uno por hw_type) + `commit_devices_sync`.
- **5 routers web** en `interfaces/web/` (`disp_comentarios`, `disp_sync`, `excel`, `plc_blocks`, `proc_sync`) cableados a `contributes_routers`.
- **4 tools MCP** en `interfaces/mcp/tools.py` cableadas a `contributes_mcp_tools`.
- **Manifest del área para la SPA** en `frontend/manifest.js` (shape JS) y `frontend/manifest.py` (espejo Python, URLs strings).
- **Back-compat de las 6 properties legacy en AppState** vía `application/disp_state_extensions.install`.
- **Defaults defensivos del ConfigManager** vía `infrastructure/config_defaults.install`.

### Cómo añadir una nueva área

Ver [AGENTS.md](../AGENTS.md) sección "Cómo añadir una nueva área" (pasos numerados). Resumen: crear `areas/<area_id>/` con `__init__.py` que defina `AREA_SPEC`, poblar `domain/`, `application/`, `infrastructure/`, `interfaces/`, `frontend/` según necesidad, añadir el bloque en `infrastructure/config.json` bajo `departments.<area_id>`, y tests en `tests/test_area_<area_id>_*.py`.

---

## 7. Estructura del repositorio

```
zc-automation-suite/
├── .clinerules                  # Reglas arquitectónicas críticas (cortas, se cargan siempre)
├── .gitignore
├── AGENTS.md                    # Guía de extensión (Bounded Contexts, convenciones operativas)
├── LICENSE                      # MIT
├── README.md                    # Este archivo (operario; arquitectura en docs/ARCHITECTURE.md)
├── main.py                      # Composition Root CLI (--mcp / --web / --worker / --worker-persistent)
├── main_tray.py                 # Composition Root del launcher (system tray dev)
├── build_exe.py                 # Orquestador PyInstaller
├── requirements.txt
├── run_app.bat / run_app_tray.bat / run_tray.bat / run_build.bat / run_tailwind.bat / run_repomix.bat
├── tailwind.config.js + tailwindcss-extra.exe
│
├── core/                        # Capa transversal
│   ├── application/             # area_registry · state · progress_buffer · log_buffer · log_paths
│   ├── infrastructure/          # gateway · config_manager · config_paths · build_cache · parsers · xml · sd · tia · cache
│   │   └── tia/                 # worker_tia.py (genérico) + command_loader.py + export_paths.py
│   ├── interfaces/              # mcp_server.py (shell MCP)
│   └── models/                  # bloque_cache.py · bloque_plc.py (DTOs)
│
├── areas/                       # Bounded Contexts por departamento
│   └── alimentacion/            # Departamento Alimentación
│       ├── __init__.py          # Exporta AREA_SPEC
│       ├── _area_id.py
│       ├── domain/              # catalog · models/
│       ├── application/         # use_cases/ · state_extensions · slot_map_builders
│       ├── infrastructure/      # config_defaults · parsers · sd · xml · tia/extra_commands · cache · loaders · build_cache
│       ├── interfaces/          # mcp/tools.py · web/{disp_comentarios,disp_sync,excel,plc_blocks,proc_sync}.py
│       └── frontend/            # components/ · lib/ · manifest.js · manifest.py
│
├── launcher/                    # Bandeja del sistema (dev)
│   ├── tray_app.py              # Menú pystray
│   ├── web_supervisor.py        # Lifecycle del web server
│   ├── make_icon.py + icon.ico
│
├── interfaces/                  # Capa de presentación web
│   └── web_server/              # app.py (shell) + dependencies.py + routers/ + static/
│       └── routers/             # areas · area_manifests · catalog · diagnostics · portal · tia_connection
│
├── infrastructure/              # Solo config.json (configuración multi-departamento)
│
├── docs/                        # Documentación adicional (STATE_MACHINE_REFACTOR.md, ARCHITECTURE.md)
├── tests/                       # 840 tests pytest (837 ok + 3 skipped)
├── _legacy_reference/           # Código histórico (NO importar, en .gitignore)
├── _plan/                       # Notas de planificación internas (en .gitignore)
├── _source/                     # Volcados del operario (.s7dcl/.s7res de TIA, en .gitignore)
└── logs/                        # Logs runtime (en .gitignore)
```

**Notas sobre los `.gitignore`** (no commitear):

- `_source/`, `_plan/`, `.minimax/`, `_trash_temp/`, `tailwindcss-extra.exe`, `*.pyd` y todo lo listado en `.gitignore` es opcional del operario o del runtime. El repo funciona sin ellos.
- `_legacy_reference/` contiene el proyecto antiguo. Se conserva por referencia histórica; **NO se importa** desde el código nuevo.

---

## 8. Configuración (`infrastructure/config.json`)

Define el mapeo entre tipos lógicos del dominio y nombres reales de tablas PLC, DBs y carpetas en TIA Portal, agrupado por **departamento** (Bounded Context).

### Estructura

```json
{
  "_comment": "...",
  "departments": {
    "alimentacion": {
      "_comment_folders": "...",
      "global_config_table_name": "000_Config_Dispositivos",
      "tia_folders": {
        "proceso":      "003_Procesos",
        "dispositivos": "2000_Dispositivos",
        "nmax":         "000_Sistema"
      },
      "n_max_catalog": [
        {
          "name":              "N_MAX_DISP_ED",
          "excel_named_range": "Num_Disp_ED",
          "hw_type":           "ed",
          "plc_tag_table":     "2000_Disp_ED",
          "comment":           "Numero max. entrada digital"
        }
      ],
      "pending_nmax": ["N_MAX_DISP_SD", "..."],
      "pending_dispositivos": {
        "sd":     { "db_name": "DB2002_SD",     "db_array_name": "SD",     "tag_table": "2000_Disp_SD" },
        "m_sina": { "db_name": "DB2017_M_SINA", "db_array_name": "M_SINA", "tag_table": "2000_Disp_M_SINA" },
        "tq":     { "db_name": "DB2018_TQ",     "db_array_name": "TQ",     "tag_table": "2000_Disp_TQ" },
        "tq_ae":  { "db_name": "DB2019_TQ_AE",  "db_array_name": "TQ_AE",  "tag_table": "2000_Disp_TQ_AE" }
      },
      "Dispositivos": {
        "ed":    {"db_name": "DB2000_ED",    "db_array_name": "ED",    "tag_table": "2000_Disp_ED",    "config_table": "000_Config_Dispositivos"},
        "ea":    {"db_name": "DB2001_EA",    "db_array_name": "EA",    "tag_table": "2000_Disp_EA",    "config_table": "000_Config_Dispositivos"},
        "sa":    {"db_name": "DB2006_SA",    "db_array_name": "SA",    "tag_table": "2000_Disp_SA",    "config_table": "000_Config_Dispositivos"},
        "v":     {"db_name": "DB2010_V",     "db_array_name": "V",     "tag_table": "2000_Disp_V",     "config_table": "000_Config_Dispositivos"},
        "m":     {"db_name": "DB2015_M",     "db_array_name": "M",     "tag_table": "2000_Disp_M",     "config_table": "000_Config_Dispositivos"},
        "m_vf":  {"db_name": "DB2016_M_VF",  "db_array_name": "M_VF",  "tag_table": "2000_Disp_M_VF",  "config_table": "000_Config_Dispositivos"}
      },
      "procesos": {
        "n_max_suffixes": {
          "preal": "PREAL",
          "pint":  "PINT",
          "alm":   "ALM"
        }
      }
    }
  }
}
```

### Claves dentro de `departments.<departamento>`

| Clave | Tipo | Descripción |
|---|---|---|
| `global_config_table_name` | `str` | Nombre de la tabla PLC con las PlcUserConstant N_MAX. |
| `tia_folders.proceso` | `str` | Carpeta TIA con los bloques del proceso. |
| `tia_folders.dispositivos` | `str` | Carpeta TIA con las tablas de dispositivos. |
| `tia_folders.nmax` | `str` | Carpeta TIA donde reside `000_Config_Dispositivos`. Default: `000_Sistema`. |
| `n_max_catalog[]` | `array` | Mapeo N_MAX ↔ Excel named range ↔ hw_type ↔ tag table. Una entrada por N_MAX activo. |
| `pending_nmax[]` | `array[str]` | N_MAX legacy aún no activados (sd, tq, etc.). |
| `pending_dispositivos` | `dict` | Tipos de dispositivo legacy aún no activados (sd, m_sina, tq, tq_ae). |
| `Dispositivos.<key>.db_name` | `str` | Nombre del DB asociado al tipo. |
| `Dispositivos.<key>.db_array_name` | `str` | Nombre del array dentro del DB. |
| `Dispositivos.<key>.tag_table` | `str` | Nombre de la PlcTagTable del tipo. |
| `Dispositivos.<key>.config_table` | `str` | PlcTagTable con las N_MAX (típicamente `000_Config_Dispositivos`). |
| `procesos.n_max_suffixes` | `dict` | Sufijos de N_MAX de procesos (PREAL, PINT, ALM). |

### Tipos de dispositivo activos (departamento `alimentacion`)

| key | DB | Tag Table | Descripción |
|---|---|---|---|
| `ed` | `DB2000_ED` | `2000_Disp_ED` | Entradas Digitales |
| `ea` | `DB2001_EA` | `2000_Disp_EA` | Entradas Analógicas |
| `sa` | `DB2006_SA` | `2000_Disp_SA` | Salidas Analógicas |
| `v` | `DB2010_V` | `2000_Disp_V` | Válvulas |
| `m` | `DB2015_M` | `2000_Disp_M` | Motores |
| `m_vf` | `DB2016_M_VF` | `2000_Disp_M_VF` | Motores con Variador de Frecuencia |

### Resolución del path del config

`ConfigManager()` sin argumentos delega en `core/infrastructure/config_paths.py:resolve_config_path()`:

- `$ZC_CONFIG_DIR/config.json` (override).
- **Frozen** (`.exe`): `<exe_dir>/config/config.json`. Si no existe, se copia del bundleado en primera ejecución. El operario puede editarlo sin recompilar.
- **Dev** (`python main_tray.py` o `python main.py`): `<cwd>/infrastructure/config.json` (el del repo, sin copia).
- Fallback readonly al bundleado si no se puede escribir (CD-ROM, red readonly).

**Política**: el usuario gana siempre. NO se sobreescribe un `config.json` existente. Para resetear al bundleado, borrar el archivo y reiniciar.

### Multi-departamento (forward-compatible)

La estructura está envuelta en `departments.<nombre>` para añadir más departamentos sin colisionar. Para añadir uno:

1. Duplicar el bloque `alimentacion` bajo `departments` con el nombre del nuevo departamento.
2. Ajustar `global_config_table_name`, `tia_folders` y `Dispositivos` según la realidad del PLC.
3. Instanciar el `ConfigManager` apuntando al nuevo departamento: `ConfigManager(department="envasado")`.

### Fallbacks defensivos

- `global_config_table_name` ausente → `"000_Config_Dispositivos"`.
- Bloque `departments` ausente → defaults en todos los getters.
- Sección `Dispositivos` ausente → `list_keys()` retorna `[]`.
- Sección `tia_folders` ausente → defaults a `"003_Procesos"`, `"2000_Dispositivos"` y `"000_Sistema"`.
- `tia_folders.nmax` ausente → default `"000_Sistema"`.
- Departamento solicitado no existe → fallback al primer departamento disponible (con warning).
- `key` no existe → `None` + `logger.warning` (NO raise).
- Campos parciales en un tipo → valores vacíos (`""`).

**El caso de uso NUNCA debe hardcodear nombres de tabla.**

---

## 9. ProgressTracker, LogBuffer, AppState

Tres singletons single-tenant en `core/application/`:

### ProgressTracker

Tracker de operaciones largas para el panel `ProgressIndicator` de la SPA.

```
begin(operation, label, stages)  # stages = lista de IDs en orden
start_stage(id, detail=None)      # fail-fast si id no existe
finish_stage(id, detail=None)     # idempotente
error_stage(id, detail)            # no-op si ya terminal
finish(success=True, error=None)   # stages huérfanos en running → error
clear()                            # reset al estado vacío
snapshot()                         # ProgressSnapshot inmutable (tupla)
```

`ProgressTracker.active` (property de solo lectura) detecta si hay operación activa — usado por `generar_prevision` cuando se llama internamente desde `ejecutar_transaccion` (no pisar el tracker del commit).

**Status values** (constantes exportadas): `STAGE_PENDING`, `STAGE_RUNNING`, `STAGE_DONE`, `STAGE_ERROR`.

### LogBuffer

Buffer thread-safe de logs expuesto vía `GET /api/v1/logs` y consumido por la SPA (panel "Consola"). Polling a 1s en frontend.

### AppState

Estado global genérico (data-driven), no ligado a alimentación. Mantiene las listas de dispositivos indexadas por `hw_type`. Se expone vía `get_app_state()` (Singleton thread-safe).

**API pública**: `get_devices`, `set_devices`, `list_hw_types`, `all_devices`, `reset`, `__iter__`, `__contains__`.

Las áreas pueden aportar **propiedades adicionales** (back-compat legacy) vía `AreaSpec.contributes_state_extensions`. El área "alimentación" instala `dispositivos_ed/ea/sa/v/m/m_vf` como properties de sugar que delegan a `get_devices` / `set_devices`.

---

## 10. Convenciones operativas

### Polling frontend

- **Logs**: 1000 ms. `apiFetchLogs()` cada 1s mientras el operario está en un área.
- **Progreso**: 500 ms. `apiFetchProgress()`. **SIEMPRE incondicional** (sin guard de estado) para evitar chicken-and-egg. 2 req/s idle es trivial para FastAPI.
- El frontend SOLO lee el tracker (nunca escribe). El backend es la única fuente de verdad.

### Estilo de código

- **Python moderno**: `from __future__ import annotations`, `match/case` cuando aplique, `asyncio.to_thread` para CPU-bound.
- **Tipado estricto**: todas las funciones públicas llevan anotaciones de tipo. Sin `Any` en modelos de dominio.
- **No retención de estado OT**: el worker mapea objetos nativos a primitivos (`list`, `dict`, `str`, `bool`, `int`) antes de emitir JSON.
- **Aislamiento de capas**: `core/` no importa de `interfaces/`. Las áreas no importan entre sí.
- **Aislamiento IT/OT**: `siemens_tia_scripting` SOLO se importa en `core/infrastructure/tia/worker_tia.py`. Los handlers de áreas reciben `(portal, ts, args)` y NO importan el wrapper.

### Convenciones frontend (Vue 3 ESM)

- **Sin build step**: el navegador carga módulos ESM directamente desde `/js/`. No usar `import.meta`, no usar TypeScript.
- **Estado global** en `store.js` con `reactive({...})`. Exportar `store` y helpers (`pushLog`, `goToArea`, etc.).
- **Fetch puro** en `api.js`: cada función devuelve `{ ok, status, data }`. NO toca `store` directamente.
- **Vue 3 sin build step — acceso a `store` desde templates**: cualquier cosa del módulo (`store`, helpers, refs importadas) que el template deba leer debe salir del `setup()` (encapsular en `computed` y retornarlo).
- **Tema "Industrial Claro"**: tokens semánticos `bg-surface*`, `text-ink*`, `bg-accent`, `border-line`. Acento azul marino Siemens `rgb(0 52 102)`. Status: `text-green-600`, `text-red-600`, `text-amber-600`.
- **PROHIBIDO** string literals multi-línea dentro de arrays de `:class`. Cada clase en una sola línea.

### Paths de export/modificación (workdirs)

Convención: `.build_cache/<área>/<contexto>/{exports,modified,preview}`. `BuildCache` en `core/infrastructure/build_cache.py` es el punto de entrada (parametrizado por `area_id`); `SdPair` y `XmlTarget` en `core/infrastructure/tia/export_paths.py` resuelven paths de archivos individuales.

Es convención de la app, NO config del proyecto. Si necesitas override: replica el patrón de `log_paths.py` (`ZC_LOG_DIR`).

### Cero código sucio

NUNCA dejar `.pyd` / `.dll` en el working tree. Tras empaquetar, `dist/` queda como entregable; `_MEIPASS` se borra al salir del `.exe`. UPX excluido para `*.dll` y `*.pyd` (corrompe los .NET nativos de Siemens).
