# ZC Automation Suite

Capa de integración IT/OT para inspección y automatización de proyectos en **Siemens TIA Portal** mediante el SDK oficial **TIA Scripting Python**.

La aplicación conecta un Excel corporativo (fuente maestra de dispositivos y procesos), una SPA web para el operario y el PLC (TIA Portal V15.1+). El operario lanza desde la SPA operaciones pesadas contra el PLC: sincronizar comentarios de slots de DBs, generar previews de cambios, subir Excel, redimensionar `N_MAX`, crear procesos desde plantilla.

![Python 3.12+](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-yellow) ![TIA Portal](https://img.shields.io/badge/TIA%20Portal-V15.1%2B-green) ![Plataforma](https://img.shields.io/badge/plataforma-Windows%20%7C%20single--tenant-blue)

---

## 1. Qué hace

- Lee un `.xlsm` maestro con dispositivos, parámetros, `N_MAX` y procesos.
- Extrae los `.s7dcl`/`.s7res` de los DBs del PLC a `exports/` (formato SimaticSD).
- Modifica offline los comentarios de slots `PReal`/`PInt`/`Alarmas` con asignación determinista de IDs MLC (`MLC_<5 hex>`).
- Re-importa los archivos modificados al PLC en su jerarquía original (TIA Portal hace match UPDATE por nombre y ruta).
- Genera previews (diff de cambios) antes de aplicar nada.
- Aplica las operaciones transaccionalmente con `start_transaction`/`end_transaction` (rollback atómico si algo falla).

Lo que evita: reescribir manualmente comentarios de slots en TIA Portal cuando el proceso crece (decenas de slots, varios procesos estándar). El operario dispara el sync, ve el progreso, los comentarios se actualizan atómicamente.

## 2. Quick start

```powershell
# Setup (Windows + venv)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Recompilar Tailwind tras añadir clases nuevas
.\run_tailwind.bat

# Lanzar la app (bandeja + web embebido)
.\run_app.bat

# O solo el servidor web (sin bandeja) en http://127.0.0.1:9484
python main.py --web 127.0.0.1:9484

# Tests
python -m pytest tests/ -v

# Empaquetar el .exe
python build_exe.py
```

El primer arranque crea `<exe_dir>/config/config.json` (copia del bundleado). La SPA está en `http://127.0.0.1:9484/`. Para QA sin TIA Portal: `?demo=1`.

## 3. Stack y arquitectura

| Capa | Tecnología | Por qué |
|---|---|---|
| Backend | Python 3.12+, Flask (sync) | Tipado estático, sync encaja con la naturaleza I/O-bound del worker OT |
| Worker OT | Hilo persistente TIA Scripting Python (COM/.NET) + cola FIFO + 6 estados | TIA Openness API no es thread-safe con los RCW; un hilo por sesion evita crashes |
| Excel | `.xlsm` maestro + `excel_cache.py` + parsers por dominio | El Excel es la fuente de verdad de dispositivos, parámetros y `N_MAX` |
| SPA | Vue 3 ESM sin build step, Tailwind v4 offline | Cero CDN = deploy offline = no se rompe sin red |
| Empaquetado | PyInstaller + `tempfile.mkdtemp()` para `.pyd`/`.dll` de Siemens | `.exe` único portable en máquinas Windows con TIA Portal |
| MCP | (planificado, no implementado aun) | Integracion con Cline / Claude Desktop para operario tecnico |

El `core/` contiene todo transversal sin saber de áreas. Cada `areas/<area>/` es un Bounded Context autocontenido que se autodescribe vía `AreaSpec` (ver `AGENTS.md`).

## 4. Estructura del repositorio

```
zc-automation-suite/
├── main.py                     # Entry point: --web (bandeja + web embebido)
├── config/                     # config.json (template bundleado + copia writable)
├── core/
│   ├── composition/            # plc_engine.py + plc_function_base.py (FBs) + app_area_registry.py
│   ├── runtime/                # AppCache, ProgressTracker, SSE event bus, area_preview_cache
│   ├── infrastructure/
│   │   ├── tia/                # tia_loop.py + tia_client.py + 8 catalogos de comandos
│   │   ├── config/             # config_manager.py + config_paths.py
│   │   └── ...                 # log_buffer, app_cache, etc.
│   ├── web_server/             # Flask + routers + static/js (SPA)
│   ├── helpers/                # simatic_sd/ + simatic_ml/ + tia/ (DRY transversal)
│   └── launcher/               # main_supervisor.py + tray_app.py (bandeja)
├── areas/
│   └── alimentacion/           # Bounded Context "alimentación"
│       ├── data/               # DTOs del dominio + catalogs (disp_catalog, proc_catalog)
│       ├── helpers/excel/      # excel_parser_*.py + excel_upload.py
│       ├── functions/          # function_*.py (FBs del área: sync, preview, etc.)
│       ├── frontend/           # SPA components + manifest.js + routers Flask
│       ├── __init__.py         # AREA_SPEC + register_alimentacion
│       └── ...
├── vendor/                     # assets propietarios (TIA Scripting SDK v1.4.3)
├── tests/
│   ├── areas/alimentacion/     # tests del área (data, functions, frontend, helpers/excel)
│   ├── core/                   # tests del core (composition, infrastructure, helpers, runtime)
│   └── ...
├── docs/                       # MIGRATION_PLAYBOOK.md, REFACTOR_SUMMARY.md, HOWTO_*.md
├── build_exe.py                # PyInstaller
├── run_app.bat                 # Lanzar app (bandeja)
├── run_tailwind.bat            # Recompilar Tailwind
└── pytest.ini, AGENTS.md, README.md, .clinerules, .opencode/
```

## 5. Conceptos clave

- **Área** (Bounded Context): paquete autocontenido bajo `areas/<area_id>/` con su propio dominio, use cases, adaptadores, UI y comandos TIA. Se autodescribe vía `AreaSpec`.
- **Function Block (FB)**: clase heredera de `core.composition.FunctionBase` que orquesta una operación larga contra TIA Portal con `nStep` + progress tracking visible para el operario.
- **TIA Command**: callable registrado en `COMMAND_REGISTRY` (genérico) o en `areas/<area>/infrastructure/tia/extra_commands.py::register()` (específico del área). El worker OT los ejecuta en su subproceso persistente.
- **Slot**: índice numérico dentro de un array (`PReal[1..N]`, `PInt[1..N]`, etc.). Tiene un MLC adyacente opcional que el helper usa como marcador.
- **MLC ID**: `MLC_<5 hex>` generado deterministamente con `uuid4().hex[:5]`. Vive en el `.s7res` del DB (formato YAML plano).
- **Subpath TIA**: jerarquía interna del PLC (p. ej. `ZC_Plantillas/50010_ProcesoEstandar/53010_Parametros/`). TIA Openness usa `block.get_path()` para resolverla.

Multi-PLC: el Excel puede contener N PLCs (cada DTO lleva su `plc_name`). El estado del operario expone `excel_cache_full` (datos UI, sin filtrar) y `excel_cache_active` (datos que consumen los FBs, filtrado por `selected_plc`). `with_plc(state, plc_name)` es el único punto que regenera el cache activo. `validate_plc_in_tia` y `validate_plc_in_excel` fallan rápido (4xx/5xx) si el PLC no está en TIA o en el Excel cargado.

## 6. Tests y validación

```powershell
# Todos los tests
python -m pytest tests/ -v

# Solo los helpers de un área
python -m pytest tests/areas/alimentacion/ -v

# Solo el core transversal
python -m pytest tests/core/ -v

# Con el árbol de tests exhaustivo (incluye integración)
python -m pytest tests/areas/alimentacion/ tests/core/ tests/interfaces/ -v
```

**Convenciones**:
- Mockear gateway con `MagicMock(spec=SyncTIAClient)`. Nunca mockear el worker directamente.
- Para `ProgressTracker`, instanciar uno limpio (`ProgressTracker()`) y pasarlo al FB.
- Naming: `tests/<subdir>/test_<modulo>.py`.
- Para áreas: `tests/areas/<area>/<subdir>/test_<feature>.py`.

### QA manual (sin TIA Portal)

La SPA tiene `?demo=1` para QA sin TIA Portal:

```
http://127.0.0.1:9484/?demo=1
```

Esto evita el flujo de attach al worker OT y usa un cliente TIA mockeado.

## 7. Build y empaquetado (.exe)

```powershell
python build_exe.py
# Resultado: dist\zc_automation_suite.exe
```

Detalles:
- PyInstaller con `.spec` autogenerado (modo windowed, sin consola).
- El `.pyd` de Siemens se stagea en `tempfile.mkdtemp()` con nombre canónico (`siemens_tia_scripting.pyd`).
- UPX excluido para `*.dll` y `*.pyd` (corrompe los .NET nativos).
- Tras empaquetar, `dist/` queda como entregable. `_MEIPASS` se borra al salir del .exe.

## 8. Convenciones operativas

| Tema | Convención |
|---|---|
| Estilo código | PEP 8 + type hints. PowerShell estricto (no `&&`, usar `;`). |
| Commits | 1-2 archivos por commit, mensajes en archivo (PowerShell con `-m` multilínea falla). Usar `git commit -F <archivo>`. |
| Borrado | `mavis-trash` (recuperable), nunca `rm` directo. |
| Tests | `python -m pytest tests/ -v` antes de cada commit. |
| Tema UI | "Industrial Claro": `bg-accent` azul Siemens `rgb(0 52 102)`. |
| Naming | Prefijos `disp_*` / `proc_*` primero en helpers (regla del operario). |
| Sync OT | `start_transaction` / `end_transaction` (rollback atómico) si transaccional. |
| TIA Openness | `target_folder_path=None` (default) hace match UPDATE; `""` hace CREATE y falla con "already exists". |

### Logging (1 llamada → archivo + web)

Un único `logging.getLogger(__name__)` enruta a archivo (`zc.log`) y consola SPA:

| Nivel | Archivo | Consola web (color) | Cuándo usarlo |
|---|---|---|---|
| `DEBUG` (10) | ✅ | ❌ | Trazas internas (transiciones TIA, ticks del engine). Solo archivo. |
| `INFO` (20) | ✅ | ❌ | Requests HTTP, eventos del ciclo de vida. Solo archivo. |
| `logger.web(...)` (25) | ✅ `[WEB]` | ✅ neutro | Mensaje contextual que el operario debe ver durante la operación. |
| `logger.ok(...)` (26) | ✅ `[OK]` | ✅ verde | Cierre exitoso de operación. |
| `WARNING` (30) | ✅ | ✅ ámbar | Alerta operativa (compilación parcial, fila descartada). |
| `ERROR` (40) | ✅ | ✅ rojo | Error recuperable (export fallido, parseo roto). |
| `CRITICAL` (50) | ✅ | ✅ rojo | Crash irrecuperable. |

Reglas operativas:
- 1 sola llamada: `logger.web/ok/warning/error(...)`. El handler enruta automáticamente.
- `WEB` = "el operario debe ver esto, contexto neutro". `OK` = "operación exitosa, confirmada".

## 9. Dónde seguir

- **Reglas arquitectónicas críticas**: `.clinerules` (siempre cargado).
- **Cómo extender la app** (nuevas áreas, FBs, dispositivos, vistas SPA, comandos MCP): `AGENTS.md`.
- **Playbook de migración** (use case → FB): `docs/MIGRATION_PLAYBOOK.md`.
- **Historia del proyecto**: `git log -- <path>`.