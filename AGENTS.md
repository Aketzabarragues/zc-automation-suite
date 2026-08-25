# AGENTS.md — Guía de extensión para zc-automation-suite

> Documento vivo para agentes AI (mavis, otros) y humanos que extiendan
> el proyecto. Si una convención cambia, edita aquí y avisa al equipo.
>
> Reglas arquitectónicas críticas en `.clinerules` (corto, se carga siempre).
> Convenciones operativas y "cómo extender" están aquí (medio, se consulta).

---

## Arquitectura: cómo añadir una nueva feature

### 1. Nueva operación contra TIA Portal
1. Edita `infrastructure/tia/worker_tia.py`: añade handler con firma
   `(portal, ts, args) -> Any` y regístralo en `COMMAND_REGISTRY`.
2. Si es transaccional, respeta el ciclo `start_transaction` /
   `end_transaction` (rollback atómico con `end_transaction(rollback=True)`).
3. Mapea objetos nativos (.NET) a primitivos Python antes de emitir JSON
   (ver `.clinerules` §3).
4. El gateway expone un método async que delega al worker vía
   `self._dispatch_worker("nombre_comando", args)`.
5. El use case orquesta, llama al gateway, y emite progress.
6. El router FastAPI expone el endpoint con `Depends(get_gateway)`.
7. Tests: mockea el gateway con `MagicMock(spec=TIAProcessGateway)`,
   nunca el worker directamente.

### 2. Nuevo endpoint REST
1. Añade el handler en `interfaces/web_server/routers/<area>.py` con
   un `APIRouter`.
2. Registra el router en `interfaces/web_server/app.py::create_app`
   (orden alfabético entre los existentes).
3. Inyecta dependencias vía `Depends(get_gateway | get_app_state |
   get_logger | get_progress_tracker)`. NUNCA importes globales
   directamente en el router.
4. Si la operación es >500 ms, inyecta `ProgressTracker` y emite
   `begin/start_stage/finish_stage/finish`.
5. Devuelve siempre un dict (FastAPI lo serializa a JSON).
6. Test: usa `TestClient` con `MagicMock(spec=TIAProcessGateway)`,
   mismo patrón que `tests/test_areas_endpoint.py`.

### 3. Nueva vista en la SPA
1. Crea `interfaces/web_server/static/js/components/<area>/<Vista>.js`
   con Vue 3 ESM. Exporta un `default { name, setup, template }`.
2. El template es un `template: /* html */ \`...\`` (template string).
3. PROHIBIDO: string literals multi-línea dentro de arrays de `:class`.
   Cada literal va en una sola línea. Salto de línea entre clases OK.
4. Estado reactivo en `store.js` (singleton `reactive` global).
5. Fetch en `api.js` (función pura, devuelve `{ ok, status, data }`).
6. Registra el componente en `main.js` (App.components) y móntalo
   en el template raíz.
7. Estilos: solo tokens semánticos del tema. Tras añadir clases,
   **recompila Tailwind** (ver `.clinerules` §9).

### 4. Nuevo campo / tipo de dispositivo (data-driven)
1. `core/alimentacion/catalog.py`: añade dataclass.
2. `infrastructure/config_manager.py`: añade mapeo `hw_type` → tabla PLC.
3. `infrastructure/parsers/excel_parser.py`: añade parser.
4. El `GET /api/v1/catalog` lo recoge automáticamente (data-driven).
5. NO tocar nada en la SPA: aparece solo en el sidebar/tabs.

### 5. Nuevo comando MCP (FastMCP)
1. Edita `interfaces/mcp_server.py`: añade `@mcp.tool()` decorador.
2. El handler debe ser async, recibir argumentos tipados, llamar al
   use case correspondiente y devolver dict.
3. La descripción del tool es el contrato con el LLM. Sé claro y
   específico (parámetros, retorno, errores esperados).
4. Test: el MCP server no tiene tests automatizados. QA manual con
   cliente MCP real (Cline, Claude Desktop).

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
- **Backend:** `pytest tests/` corre TODOS los tests. 138 tests
  actualmente (119 legacy + 19 nuevos de progress). Deben pasar
  todos antes de commit.
- **Naming:** `tests/test_<modulo>.py`. Mismo nombre que el archivo
  que prueban.
- **Mockear gateway** con `MagicMock(spec=TIAProcessGateway)`.
  Para ProgressTracker, instanciar uno limpio (`ProgressTracker()`)
  y pasarlo al use case (no mockear el tracker).
- **Frontend:** sin tests automatizados (SPA ESM sin build step).
  QA manual con `?demo=1` y servidor de pruebas.

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
| Recompilar CSS | `tailwindcss-extra.exe -i interfaces/web_server/static/src/input.css -o interfaces/web_server/static/styles.css --minify` |
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

## Contacto / dudas

- **Reglas críticas:** `.clinerules` (leer siempre primero).
- **Convenciones operativas:** este archivo.
- **Perfil del usuario:** `C:\Users\ABH\.minimax\memory\user.md` (contexto
  del operario, su estilo, sus preferencias).
- **Perfil del agente:** `C:\Users\ABH\.minimax\memory\main.md` (cosas
  que mavis aprende跨 proyectos).
