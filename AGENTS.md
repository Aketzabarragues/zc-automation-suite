# AGENTS.md — Guía de extensión para zc-automation-suite

> Documento vivo para agentes AI (mavis, otros) y humanos que extiendan
> el proyecto. Si una convención cambia, edita aquí y avisa al equipo.
>
> Reglas arquitectónicas críticas en `.clinerules` (corto, se carga siempre).
> Convenciones operativas y "cómo extender" están aquí (medio, se consulta).

---

## Arquitectura: cómo añadir una nueva feature

> El layout del repositorio sigue **Bounded Contexts** (PR 0-7 del
> plan de reorganización). `core/` contiene TODO lo transversal sin
> saber de áreas; cada `areas/<area>/` es un paquete autocontenido
> que se autodescribe vía `AreaSpec`. Antes de añadir una feature
> dentro de un área, lee **"Cómo añadir una nueva área"** más abajo.

### 1. Nueva operación contra TIA Portal
1. Decide si la operación es **genérica** (la usan todas las áreas
   futuras) o **específica del área**:
   - **Genérica:** edita `core/infrastructure/tia/worker_tia.py`,
     añade handler con firma `(portal, ts, args) -> Any` y regístralo
     en `COMMAND_REGISTRY`.
   - **Específica de un área:** edita
     `areas/<area>/infrastructure/tia/extra_commands.py`, implementa
     el handler y regístralo en la función `register(registry)`. El
     command loader del worker (`load_extra_commands`) lo descubre
     automáticamente al arrancar (ver `.clinerules` §1).
2. Si es transaccional, respeta el ciclo `start_transaction` /
   `end_transaction` (rollback atómico con `end_transaction(rollback=True)`).
3. Mapea objetos nativos (.NET) a primitivos Python antes de emitir JSON
   (ver `.clinerules` §3).
4. El gateway expone un método async que delega al worker vía
   `self._dispatch_worker("nombre_comando", args)`.
5. El use case (en `core/application/use_cases/` si es genérico o en
   `areas/<area>/application/use_cases/` si es del área) orquesta,
   llama al gateway, y emite progress.
6. El router FastAPI expone el endpoint con `Depends(get_gateway)`.
   Los routers genéricos viven en `core/interfaces/web_server/routers/`;
   los del área en `areas/<area>/interfaces/web/`.
7. Tests: mockea el gateway con `MagicMock(spec=TIAProcessGateway)`,
   nunca el worker directamente.

### 2. Nuevo endpoint REST
1. Añade el handler en el router correspondiente:
   - Genérico: `core/interfaces/web_server/routers/<area>.py` con
     un `APIRouter`.
   - Del área: `areas/<area>/interfaces/web/<router>.py` y declara
     `register_routers(app)` en el `__init__.py` del paquete.
2. El shell FastAPI (`core/interfaces/web_server/app.py::create_app`)
  Descubre los routers del área vía `AreaRegistry.for_each("contributes_routers", app=app)`.
3. Inyecta dependencias vía `Depends(get_gateway | get_app_state |
   get_logger | get_progress_tracker)`. NUNCA importes globales
   directamente en el router.
4. Si la operación es >500 ms, inyecta `ProgressTracker` y emite
   `begin/start_stage/finish_stage/finish`.
5. Devuelve siempre un dict (FastAPI lo serializa a JSON).
6. Test: usa `TestClient` con `MagicMock(spec=TIAProcessGateway)`,
   mismo patrón que `tests/test_areas_endpoint.py`.

### 3. Nueva vista en la SPA
1. Crea `areas/<area>/frontend/components/<Vista>.js` con Vue 3 ESM.
   Exporta un `default { name, setup, template }`. NO añadas
   componentes en `interfaces/web_server/static/js/components/areas/`
   (esa carpeta ya no existe tras PR 7).
2. El template es un `template: /* html */ \`...\`` (template string).
3. PROHIBIDO: string literals multi-línea dentro de arrays de `:class`.
   Cada literal va en una sola línea. Salto de línea entre clases OK.
4. Estado reactivo en `store.js` (singleton `reactive` global).
5. Fetch en `api.js` (función pura, devuelve `{ ok, status, data }`).
6. Registra el componente en `areas/<area>/frontend/manifest.js` (un
   `build()` que devuelve `{ components, routes, sidebar, landing, loaders }`).
   El shell SPA (`interfaces/web_server/static/js/main.js`) lo carga
   dinámicamente vía `area-loader.js` al entrar al área.
7. Estilos: solo tokens semánticos del tema. Tras añadir clases,
   **recompila Tailwind** (ver `.clinerules` §9). El config ya
   incluye `./areas/**/frontend/**/*.js` en `content`, así que las
   nuevas clases se detectan automáticamente.

### 4. Nuevo campo / tipo de dispositivo (data-driven, en el área)
1. `areas/alimentacion/domain/catalog.py`: añade dataclass.
2. `core/infrastructure/config_manager.py`: añade mapeo `hw_type` → tabla PLC.
3. `core/infrastructure/parsers/excel_parser.py`: añade parser base
   (si es genérico) o `areas/alimentacion/infrastructure/parsers/`
   (si es específico del área).
4. El `GET /api/v1/catalog` lo recoge automáticamente (data-driven).
5. NO tocar nada en la SPA: aparece solo en el sidebar/tabs.

### 5. Nuevo comando MCP (FastMCP)
1. Decide si el tool es **genérico** o **del área**:
   - **Genérico:** edita `core/interfaces/mcp_server.py`, añade
     `@mcp.tool()` decorador en el closure del shell.
   - **Del área:** edita `areas/<area>/interfaces/mcp/tools.py`,
     implementa `register(mcp)` y dentro declara los `@mcp.tool()`.
     El shell MCP descubre los tools del área vía
     `AreaRegistry.for_each("contributes_mcp_tools", mcp=mcp)`.
2. El handler debe ser async, recibir argumentos tipados, llamar al
   use case correspondiente y devolver dict.
3. La descripción del tool es el contrato con el LLM. Sé claro y
   específico (parámetros, retorno, errores esperados).
4. Las tools del área **NO replican lógica de negocio**: delegan en
   los mismos use cases que los routers web.
5. Test: tests automatizados con `MagicMock` cubriendo cada tool.
   QA manual con cliente MCP real (Cline, Claude Desktop).

### 6. Cómo añadir una nueva área
1. Crear `areas/<area_id>/` con `__init__.py` que defina
   `AREA_SPEC = AreaSpec(...)` (dataclass frozen en
   `core/application/area_registry.py`).
2. Si el área tiene modelos de dominio: `areas/<area>/domain/`.
3. Si tiene casos de uso: `areas/<area>/application/use_cases/`.
4. Si tiene adaptadores (parsers, modificadores, etc.):
   `areas/<area>/infrastructure/`.
5. Si tiene comandos TIA transaccionales:
   `areas/<area>/infrastructure/tia/extra_commands.py` con
   `register(registry)`.
6. Si tiene routers FastAPI: `areas/<area>/interfaces/web/` con
   `register_routers(app)` en el `__init__.py` del paquete.
7. Si tiene tools MCP: `areas/<area>/interfaces/mcp/tools.py` con
   `register(mcp)`.
8. Si tiene UI: `areas/<area>/frontend/components/` +
   `areas/<area>/frontend/manifest.js` (un `build()` que devuelve
   `{ components, routes, sidebar, landing, loaders }`).
9. Añadir el bloque en `infrastructure/config.json` bajo
   `departments.<area_id>`.
10. Tests: `tests/test_area_<area_id>_*.py` siguiendo el patrón
    existente (mockear gateway con `MagicMock(spec=TIAProcessGateway)`).

Convenciones:
- Las áreas **NO importan** `siemens_tia_scripting` directamente
  (regla `.clinerules` §1). Solo aportan `Callable` que el worker
  invocará en su proceso. Los handlers extra pueden usar comandos
  genéricos del registry (`COMMAND_REGISTRY["export_block"](...)`)
  para participar de transacciones atómicas con ellos.
- El worker OT se mantiene 100% genérico; las áreas aportan comandos
  vía `AreaSpec.contributes_tia_commands` (el command loader los
  descubre al arrancar).
- El shell SPA NO importa componentes de áreas directamente. Todo
  se carga vía `area-loader.js` + manifest.
- `store.areaManifest` guarda el manifest del área activa.
  `store.currentView` se valida contra `store.areaManifest.routes`.

---

## Convenciones operativas

### Polling frontend
- **Logs:** 1000 ms. `apiFetchLogs()` cada 1s mientras el operario
  está en un área. Solo lectura.
- **Progreso:** 500 ms. `apiFetchProgress()`. **SIEMPRE incondicional**
  (sin guard de estado) para evitar chicken-and-egg. 2 req/s idle
  es trivial para FastAPI.
- El frontend SOLO lee el tracker (nunca escribe). El backend es
  la única fuente de verdad. El operario limpia explícitamente con
  `apiClearProgress()` cuando quiere.

### ProgressTracker — API completa
```
begin(operation, label, stages)  # stages = lista de IDs en orden
start_stage(id, detail=None)      # fail-fast si id no existe
finish_stage(id, detail=None)     # idempotente
error_stage(id, detail)            # no-op si ya terminal
finish(success=True, error=None)   # stages huérfanos en running → error
clear()                            # reset al estado vacío
snapshot()                         # ProgressSnapshot inmutable (tupla)
```

`ProgressTracker.active` (property de solo lectura) detecta si hay
operación activa — usado por `generar_prevision` cuando se llama
internamente desde `ejecutar_transaccion` (no pisar el tracker del
commit).

### Tests
- **Backend:** `pytest tests/` corre TODOS los tests. 233 tests
  actualmente (acumulado de los 138 originales + los tests nuevos
  de PR 0-6: AppState genérico, AreaRegistry, command loader,
  manifest endpoint, MCP shell + 4 tools del área). Deben pasar
  todos antes de commit.
- **Naming:** `tests/test_<modulo>.py`. Mismo nombre que el archivo
  que prueban. Para áreas, `tests/test_area_<area>_<feature>.py`.
- **Mockear gateway** con `MagicMock(spec=TIAProcessGateway)`.
  Para ProgressTracker, instanciar uno limpio (`ProgressTracker()`)
  y pasarlo al use case (no mockear el tracker).
- **Frontend:** sin tests automatizados (SPA ESM sin build step).
  QA manual con `?demo=1` y servidor de pruebas.

### Command loader del worker OT
- `core/infrastructure/tia/worker_tia.py` solo contiene comandos
  **genéricos** (open/close/save/list_plcs/list_blocks/compile_plc/
  export_*/import_*/user_constants/transactional_batch).
- Las áreas aportan comandos adicionales vía
  `areas/<area>/infrastructure/tia/extra_commands.py::register(registry)`.
  El `load_extra_commands()` del command loader los descubre
  automáticamente al arrancar el worker (ver `.clinerules` §1).
- **CRÍTICO:** los handlers extra NO importan `siemens_tia_scripting`
  directamente. Reciben `(portal, ts, args)` del worker y operan
  sobre el `portal` ya inicializado en su proceso.
- **Sí pueden** usar comandos genéricos del registry
  (`COMMAND_REGISTRY["export_block"](...)`) para participar de
  transacciones atómicas con ellos.

### Build / Empaquetado
- **PyInstaller:** `python build_exe.py` → `dist/zc_automation_suite.exe`.
- El `.pyd` de Siemens se stagea en `tempfile.mkdtemp()` con nombre
  canónico (`siemens_tia_scripting.pyd`).
- UPX excluido para `*.dll` y `*.pyd` (corrompe los .NET nativos).
- Modo windowed (sin consola): `console=False` en el `.spec` autogenerado.
- Tras empaquetar, `dist/` queda como entregable; `_MEIPASS` se
  borra al salir del .exe.
- **Cero código sucio:** NUNCA dejar `.pyd` / `.dll` en el working
  tree. Ver `.clinerules` §6.

### Datos
- **NUNCA** retornar objetos nativos TIA (.NET) al proceso IT.
- **SIEMPRE** mapear a `dict` / `list` / `str` / `bool` / `int` en el
  worker, antes de emitir JSON.
- **Cachear** lecturas pesadas (PLCs, bloques, user constants) en
  `gateway._cache` con `force_refresh=True` para bypass explícito.

### Convenciones frontend (Vue 3 ESM)
- **Sin build step:** el navegador carga módulos ESM directamente
  desde `/js/`. No usar `import.meta`, no usar TypeScript.
- **Estado global** en `store.js` con `reactive({...})`. Exportar
  `store` y helpers (`pushLog`, `goToArea`, etc.).
- **Fetch puro** en `api.js`: cada función devuelve
  `{ ok, status, data }`. NO toca `store` directamente.
- **Polling** vía `setInterval` en `main.js` (no en componentes).
- **ProgressIndicator.js** es el ÚNICO componente de feedback de
  operaciones largas. Va anclado al final del `AlimentacionSidebar`
  (`mt-auto`).

### Tema "Industrial Claro"
- Superficies: `bg-surface` (gris muy claro) / `bg-surface-raised`
  (blanco) / `bg-surface-sunken` (input/secondary).
- Bordes: `border-line` (gris medio) / `border-line-strong` (gris
  oscuro para focus).
- Texto: `text-ink` (principal) / `text-ink-muted` (secundario) /
  `text-ink-inverse` (sobre acento).
- Acento: `bg-accent` (azul marino Siemens `rgb(0 52 102)`) /
  `bg-accent-hover` / `bg-accent-subtle` (filas destacadas).
- Status: `text-green-600` (ok), `text-red-600` (error),
  `text-amber-600` (warning).

---

## Atajos de desarrollo

| Tarea | Comando |
|---|---|
| Correr tests | `python -m pytest tests/ -v` |
| Servidor dev (web) | `python main.py --web 127.0.0.1:8000` |
| Servidor dev (MCP) | `python main.py --mcp` |
| Launcher bandeja | `python main_tray.py` (o `run_tray.bat`) |
| Recompilar CSS | `tailwindcss-extra.exe -i interfaces/web_server/static/src/input.css -o interfaces/web_server/static/styles.css --minify` (también `run_tailwind.bat` si existe) |
| Build .exe | `python build_exe.py` |
| Test E2E manual | abrir `http://127.0.0.1:8000/` (demo: `?demo=1`) |

---

## Errores comunes (lecciones aprendidas)

1. **CSS no se aplica:** ¿recompilaste Tailwind tras añadir clases?
   → `.clinerules` §9.
2. **Overlay / panel no aparece:** ¿el navegador está usando
   versión cacheada? → `Ctrl+Shift+R` o ventana incógnito.
3. **Worker OT falla con timeout 45s:** ¿hay un diálogo modal abierto
   en TIA Portal? (común durante `compile_plc` o `open_transaction`).
4. **Tests legacy fallan tras tocar use cases:** ¿añadiste un parámetro
   al constructor? Los tests monkey-patchean métodos. Mantén los
   nuevos parámetros como opcionales con default al Singleton global.
5. **Vue 3 template error "string literal multi-línea":** los
   `template: \`...\`` no admiten literales multi-línea dentro de
   arrays `:class`. Cada clase en una sola línea.

---

## Agentes Mavis disponibles

Para tareas en este repo, el root session (mavis) puede delegar a
4 agentes especializados definidos en `C:/Users/ABH/.minimax/agents/`.
El orquestador decide el routing leyendo la `description:` de cada
agente; **tú solo describes la tarea en lenguaje natural** y mavis
elige al especialista adecuado. No hace falta invocar `/mavis-team`
ni cargar skills manualmente: el routing es automático.

| Tarea | Agente |
|---|---|
| Cambios en TIA worker, modificadores XML/SD, parsers Excel, gateway OT | `tia-ot-worker` |
| Routers FastAPI, use cases, `app.py`, dependencias, tools MCP | `backend-api` |
| Componentes Vue, store, api.js, tema, recompilar Tailwind | `frontend-spa` |
| `build_exe.py`, launcher, tests pytest, `.bat` | `build-and-tests` |

Tareas que cruzan varios scopes las orquesta mavis y delega sub-piezas
en paralelo. Para investigación pura (sin cambios) está `explore`
(built-in); para verificación independiente, `verifier` (built-in).
El skill `mavis-team` solo aplica si pides explícitamente `/mavis-team`
o `/team`.

---

## Contacto / dudas

- **Reglas críticas:** `.clinerules` (leer siempre primero).
- **Convenciones operativas:** este archivo.
- **Perfil del usuario:** `C:\Users\ABH\.minimax\memory\user.md` (contexto
  del operario, su estilo, sus preferencias).
- **Perfil del agente:** `C:\Users\ABH\.minimax\memory\main.md` (cosas
  que mavis aprende跨 proyectos).
