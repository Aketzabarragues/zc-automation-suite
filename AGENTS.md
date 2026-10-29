# AGENTS.md — Guía de extensión para zc-automation-suite

> Documento vivo para agentes AI (mavis, otros) y humanos que extiendan
> el proyecto. Si una convención cambia, edita aquí y avisa al equipo.
>
> Reglas arquitectónicas críticas en `.clinerules` (corto, se carga siempre).
> Convenciones operativas y "cómo extender" están aquí (medio, se consulta).

## TL;DR del modelo de tres pilares

El flujo del operario es siempre el mismo:

```
HMI --> pulsador --> OB1 --> FB --> WORKER (TIA)
```

- **HMI** = la web (Flask + SPA Vue 3 sin build step). El pulsador hace un
  POST al router y el router no espera al resultado.
- **OB1** = el dispatcher. Es el `Engine` (`core/composition/plc_engine.py`):
  una cola de trabajos + un hilo dedicado (`plc-ob1`) que consume la cola y
  ejecuta cada FB completo. `engine.submit(fb_name, **params)` encola el
  trabajo y devuelve un `job_id`; el router responde `202` con ese id.
- **FB** = la unidad de trabajo (`core/composition/plc_function_base.py`).
  Son **sync**: `run_step(self, idx: int, **params: Any) -> str`. El hilo del
  OB1 los ejecuta con `fb.execute(**params)`.
- **WORKER** = el hilo dedicado de TIA Portal
  (`core/infrastructure/tia/tia_loop.py`): `threading.Thread` daemon +
  `queue.Queue`. Es el único lugar autorizado para tocar los RCW de .NET.
  Arranca en `idle` (sin portal attached), y el frontend le envía un
  `attach_portal` explícito cuando el operario pulsa "Conectar" desde la
  topbar, y un `detach_portal` cuando pulsa "Desconectar". El hilo NO muere
  entre comandos — eso elimina pagar el coste de arranque del CLR + attach
  (~5s) en cada operación.

El resultado **no vuelve en el body del HTTP**: vuelve por push. El FB
publica su estado por SSE (evento `fb_state`) y deja el resultado en los slots
del `AppCache` en su `on_finish` (la SPA los lee por SSE `cache_changed`).

Hay dos hilos dedicados, no uno: el OB1 ejecuta FBs y el worker TIA ejecuta
comandos contra el portal. El hilo del worker no es opcional: los RCW de .NET
no son thread-safe y Flask corre con `threaded=True`, así que sin él varios
requests entrarían al portal a la vez. El dispatcher OB1 se documenta en
`.clinerules` §1; el worker (state machine de 6 estados y comandos de ciclo de
vida) en `.clinerules` §2.

---

## Arquitectura: cómo añadir una nueva feature

> El layout del repositorio sigue **Bounded Contexts** (plan de
> reorganización). `core/` contiene TODO lo transversal sin
> saber de áreas; cada `areas/<area>/` es un paquete autocontenido
> que se autodescribe vía `AreaSpec`. Antes de añadir una feature
> dentro de un área, lee **"Cómo añadir una nueva área"** más abajo.

### 1. Nueva operación contra TIA Portal
1. Decide si la operación es **genérica** (la usan todas las áreas
   futuras) o **específica del área**:
   - **Genérica:** edita `core/infrastructure/tia/tia_commands_catalog.py`
     (o el submódulo de la categoría correspondiente: `tia_cmd_lifecycle`,
     `tia_cmd_project`, `tia_cmd_inspect`, `tia_cmd_compile`, `tia_cmd_export`,
     `tia_cmd_import_`, `tia_cmd_user_consts`, `tia_cmd_batch`), añade
     handler con firma `(args: dict, tia_client: SyncTIAClient) -> dict`
     (alias `HandlerSig`) y regístralo en `CATALOGO`.
   - **Específica de un área:** edita
     `areas/<area>/infrastructure/tia/extra_commands.py`, implementa
     `def register(tia_client: SyncTIAClient) -> None` que registra
     N comandos vía `tia_client.register_command(name, handler)`. El
     supervisor (`core/launcher/main_supervisor._build_components()`)
     invoca `spec.contributes_tia_commands(tia_client)` tras
     `register_all_commands(tia_client)` en el arranque del web.
     Patrón declarado en `AreaSpec` pero ningún área del repo lo ha
     materializado todavía (la lógica transaccional se compone hoy con
     `execute_transactional_batch` desde los FBs).
2. Si es transaccional, respeta el ciclo `start_transaction` /
   `end_transaction` (rollback atómico con `end_transaction(rollback=True)`).
3. Mapea objetos nativos (.NET) a primitivos Python antes de emitir JSON
   (ver `.clinerules` §3).
4. El cliente del worker expone
   `submit_and_wait(command, args=None, timeout=30.0)`: encola el comando
   en el worker y **bloquea** hasta tener respuesta. El bloqueo es
   intencionado: el FB corre en el hilo del OB1, que existe para eso. El
   `timeout` es la espera de la respuesta del worker; el timeout del step
   vive aparte, en `FunctionBase.STEP_TIMEOUT_S`.
5. La lógica se implementa como **FB** (Function Block, state machine
   con `on_start` / `run_step` / `on_finish`) en
   `areas/<área>/functions/function_<x>.py`. Los tres hooks son **sync**:
   `def run_step(self, idx: int, **params: Any) -> str`. El FB registra su
   progreso vía `ProgressTracker` y delega al worker con
   `self._tia_client.submit_and_wait("comando", args, timeout=T)` — sin
   wrappers: el FB ya corre en un hilo dedicado. Para lotes transaccionales
   el comando es `execute_transactional_batch`.
6. El router Flask expone el endpoint, toma el engine de
   `current_app.config["ENGINE"]` y encola el trabajo con
   `engine.submit("<nombre_fb>", **params)`. No espera al resultado. Los
   routers genéricos viven en `core/web_server/routers/`; los del área en
   `areas/<area>/frontend/` (routers Flask del área, ej.
   `alimentacion/frontend/excel_router.py`).
7. Tests: mockea el cliente con `MagicMock(spec=SyncTIAClient)`,
   nunca el worker directamente.

### 2. Nuevo endpoint REST
1. Añade el handler en el router correspondiente:
   - Genérico: `core/web_server/routers/<recurso>.py` con un
     `Blueprint` de Flask (no `APIRouter`; el shell es Flask, no
     FastAPI). Ejemplos: `portal.py`, `plc.py`, `diagnostics.py`.
   - Del área: `areas/<área>/frontend/<x>_router.py` con un
     `Blueprint` Flask. Ejemplos en alimentación: `excel_router.py`,
     `disp_sync_router.py`, `proc_process_crear_router.py`.
2. El shell Flask (`core/web_server/app_flask.py::create_app`)
   descubre los blueprints de las áreas vía
   `AreaRegistry.discover().for_each("contributes_routers", app=app)`.
   Cada área monta sus routers desde su callable
   `contributes_routers` (en `alimentacion` se llama
   `_build_all_routers(app)`).
3. Lee las dependencias de `current_app.config` (`ENGINE`, `TIA_CLIENT`,
   `EVENT_BUS`, `_LAZY_*`) o de los singletons (`get_app_cache()`,
   `get_progress_tracker()`). NUNCA importes globales directamente
   en el router.
4. Si la operación es >500 ms, la emite un FB con `ProgressTracker`
   (`begin/start_stage/finish_stage/finish`): el router solo encola.
5. Devuelve siempre un dict (Flask lo serializa a JSON con `jsonify`).
6. Si el endpoint encola un trabajo, el contrato de respuesta es:
   - `202` + `{"ok": True, "job_id": "<hex>"}`: encolado.
   - `400`: validacion de entrada (faltan parametros obligatorios).
   - `409`: el FB ya tiene un trabajo en curso (`FBBusyError`).
   - `500`: el FB no esta registrado en el engine, o no se pudo encolar.
   El resultado NO va en el body: llega al HMI por SSE (`fb_state`).
7. Test: usa `TestClient` de Flask con `MagicMock(spec=SyncTIAClient)`,
   mismo patrón que `tests/test_areas_endpoint.py`.

### 3. Nueva vista en la SPA
1. Crea `areas/<area>/frontend/components/<Vista>.js` con Vue 3 ESM.
   Exporta un `default { name, setup, template }`. NO añadas
   componentes en `core/web_server/static/js/components/areas/`
   (esa carpeta ya no existe).
2. El template es un `template: /* html */ \`...\`` (template string).
3. PROHIBIDO: string literals multi-línea dentro de arrays de `:class`.
   Cada literal va en una sola línea. Salto de línea entre clases OK.
4. Estado reactivo en `store.js` (singleton `reactive` global).
5. Fetch en `api.js` (función pura, devuelve `{ ok, status, data }`).
6. Registra el componente en `areas/<area>/frontend/manifest.js` (un
   `build()` que devuelve `{ components, routes, sidebar, landing, loaders }`).
   El shell SPA (`core/web_server/static/js/main.js`) lo carga
   dinámicamente vía `area-loader.js` al entrar al área.
7. Estilos: solo tokens semánticos del tema. Tras añadir clases,
   **recompila Tailwind** (ver `.clinerules` §9). El config ya
   incluye `./areas/**/frontend/**/*.js` en `content`, así que las
   nuevas clases se detectan automáticamente.

### 4. Nuevo campo / tipo de dispositivo (data-driven, en el área)
1. Catálogo del área: añade el dataclass en
   `areas/<área>/__init__.py` (ver `_build_alim_catalog_combined` como
   referencia en `alimentacion/__init__.py`).
2. `core/infrastructure/config/config_manager.py`: añade mapeo
   `hw_type` → tabla PLC.
3. Parser Excel: `areas/<área>/helpers/excel/excel_parser_<tipo>.py`
   (uno por tipo de dispositivo; ver `alimentacion/helpers/excel/`
   como referencia; no hay parser Excel genérico en core hoy).
4. El `GET /api/v1/catalog` lo recoge automáticamente (data-driven).
5. NO tocar nada en la SPA: aparece solo en el sidebar/tabs.

### 5. Tools MCP (FastMCP) — NO IMPLEMENTADO TODAVÍA

> Estado: el campo `contributes_mcp_tools: Callable[[Any], None] | None`
> está declarado en `AreaSpec` (`core/composition/app_area_registry.py`)
> pero **ningún área del repo lo usa** y no hay tools MCP wired up al
> shell. Esta sección documenta el patrón previsto; cuando se
> materialice, sigue estas reglas.

1. Decide si el tool es **genérico** o **del área**:
   - **Genérico:** el módulo del shell MCP no existe todavía;
     cuando se cree vivirá en `core/interfaces/mcp_server.py`
     (pendiente, no figura en `main.py` como `--mcp`).
   - **Del área:** crea `areas/<área>/interfaces/mcp/tools.py` (la
     carpeta `interfaces/` tampoco existe en `alimentacion/` aún),
     implementa `register(mcp)` y dentro declara los `@mcp.tool()`.
     El shell MCP descubriría los tools del área vía
     `AreaRegistry.for_each("contributes_mcp_tools", mcp=mcp)`.
2. El handler debe ser async, recibir argumentos tipados, llamar al
   FB correspondiente y devolver dict.
3. La descripción del tool es el contrato con el LLM. Sé claro y
   específico (parámetros, retorno, errores esperados).
4. Las tools del área **NO replican lógica de negocio**: delegan en
   los mismos FBs que los routers web.
5. Test: tests automatizados con `MagicMock` cubriendo cada tool.
   QA manual con cliente MCP real (Cline, Claude Desktop).

### 6. Cómo añadir una nueva área
1. Crear `areas/<area_id>/` con `__init__.py` que defina
   `AREA_SPEC = AreaSpec(...)` (dataclass frozen en
   `core/composition/app_area_registry.py`).
2. Layout real del área (ver `alimentacion/` como referencia):
   - `data/`: artefactos cacheados (Excel cache, etc.).
   - `helpers/`: lógica pura del área (sub-paquetes por dominio:
     `excel/`, `layout/`, `sync/`, etc.).
   - `state/`: estado del área (`area_cache.py`, modelos
     congelados para `AppCache.register_area(...)`).
   - `functions/`: FBs (Function Blocks) — un módulo por FB,
     clase + `FunctionBase.__init__` + hooks `on_start` /
     `run_step` / `on_finish`.
   - `frontend/`: SPA del área (componentes Vue 3 ESM en
     `components/`, `manifest.js` con `build()` que devuelve
     `{ components, routes, sidebar, landing, loaders }`,
     routers Flask del área como `<x>_router.py`).
   - `_area_id.py`: constante `AREA_ID = "<area_id>"` (convenio).
3. Catálogo del área: `contributes_catalog` en `AREA_SPEC` (ver
   `_build_alim_catalog_combined` como referencia). `GET /api/v1/catalog`
   lo recoge automáticamente (data-driven).
4. Si aporta comandos TIA extra:
   `areas/<área>/infrastructure/tia/extra_commands.py` con
   `def register(tia_client: SyncTIAClient) -> None` (que llama
   `tia_client.register_command(...)`). El supervisor lo invoca
   una vez al arrancar el web. Patrón documentado pero ningún
   área lo ha materializado todavía.
5. Si aporta tools MCP: `contributes_mcp_tools` en `AREA_SPEC` —
   declarado pero NO implementado en el repo. Ver §5.
6. `register(engine, *, config_manager=None, tia_client=None,
   build_cache=None, app_cache=None)` en
   `areas/<área>/__init__.py` registra los FBs en el engine.
   `log` no se inyecta: usa `logging.getLogger(__name__)`.
7. Añadir el bloque en `config/config.json` bajo
   `departments.<area_id>`.
8. Tests: `tests/areas/<area_id>/test_<feature>.py` (ver
   `tests/areas/alimentacion/...` como referencia; mockear el
   cliente con `MagicMock(spec=SyncTIAClient)`).

Convenciones:
- Las áreas **NO importan** `siemens_tia_scripting` directamente
  (regla `.clinerules` §1). Solo aportan `Callable` que el worker
  invocará en su proceso. Los handlers extra pueden usar comandos
  genéricos del catálogo (`CATALOGO["export_blocks"](...)`) para
  participar de transacciones atómicas con ellos.
- El worker OT se mantiene 100% genérico; las áreas aportan comandos
  vía `AreaSpec.contributes_tia_commands`. El wiring está en
  `core/launcher/main_supervisor._build_components()` (no hay
  command loader separado).
- El shell SPA NO importa componentes de áreas directamente. Todo
  se carga vía `area-loader.js` + manifest.
- `store.areaManifest` guarda el manifest del área activa.
  `store.currentView` se valida contra `store.areaManifest.routes`.

### 7. FB template y playbook de creación

> Patrón de creación de un FB nuevo en el área. Aplica a todas las
> áreas y a cualquier lógica transaccional que necesite steps
> secuenciales con progreso visible. Detalle histórico del refactor
> A.1 en `docs/MIGRATION_PLAYBOOK.md` (congelado como referencia;
> la realidad actual difiere en los paths).

**Referencia canónica**: FB `excel_cargar`
(`areas/alimentacion/functions/function_excel_cargar.py` +
`helpers/excel/excel_upload.py` + `frontend/excel_router.py`).
Replica su estructura.

**5 pasos para añadir un FB nuevo**:
1. Lógica pura: `helpers/<dominio>/<use_case>.py` con kwargs
   explícitos, sin Singletons.
2. FB: `functions/function_<x>.py`, copia la plantilla de
   `function_excel_cargar.py`. Renombra clase y `nombre` canónico;
   define Zona 0/3 y los hooks `on_start` / `run_step` / `on_finish`.
3. Registrar el FB en
   `areas/<área>/__init__.py::register(engine, *, config_manager=None,
   tia_client=None, build_cache=None, app_cache=None)`. No se
   inyecta `log`: usa `logging.getLogger(__name__)`.
4. Router Flask: `frontend/<use_case>_router.py`; montar desde
   `__init__.py::_build_all_routers(app)`. Encolar con
   `engine.submit("<nombre_fb>", **params)` y responder `202` con el
   `job_id`; propagar `FBBusyError` como 409.
5. Smoke en vivo + tests en `tests/areas/<área>/...`.

**Gotchas** (detalle en `docs/MIGRATION_PLAYBOOK.md`):
- `LogBuffer.info(message)` solo acepta 1 arg. Usar f-strings.
- `_stats` lo inicializa `FunctionBase.__init__`; no redeclararlo.
- FB re-arrancable: `execute()` acepta desde `n_done`/`n_error` y limpia
  el estado por llamada (`_stats`, `error_msg`, `result`, `_step_idx`).
- `run_step` es sync: si devuelve una corrutina, el base lanza
  `TypeError` (los FBs se ejecutan en el hilo del OB1).
- Lazy import del helper dentro de `run_step` (evita ciclos).
- Mapear objetos nativos TIA a primitivos antes de `self.result`.

---

## Convenciones operativas

### Push frontend (SSE)
- **Logs y progreso llegan por SSE**, no por polling: el navegador abre
  `GET /stream` (`core/web_server/app_flask.py`) y consume los eventos
  `log`, `progress`, `tia_state`, `fb_state`, `cache_changed` y
  `cache_snapshot` en `core/web_server/static/js/main.js`.
- **El resultado de un trabajo vuelve por push, no en el body del POST.**
  El router responde `202` con el `job_id` y el estado del FB llega por
  el evento SSE `fb_state`, con payload
  `{name, nStep, is_terminal, job_id, result, error_msg}`. El `job_id`
  permite correlacionar el evento con el trabajo que pidio el HMI.
- **Los datos del resultado viven en el `AppCache`**: el FB los publica en
  su `on_finish` y la SPA los lee por SSE `cache_changed`.
- En el SPA, `store.fbStates` guarda el ultimo estado de cada FB y
  `waitForFbJob(jobId, fbName, timeoutMs)` (en `/js/store.js`) espera al
  estado terminal del trabajo y lo devuelve.
- El frontend SOLO lee el tracker (nunca escribe). El backend es
  la única fuente de verdad. El operario limpia explícitamente con
  `apiClearProgress()` cuando quiere.
- `GET /api/v1/progress/current` existe en `diagnostics.py` pero **no
  tiene consumidor**: no lo uses como si fuera el mecanismo vigente.

### Dispatcher OB1 (`core/composition/plc_engine.py`)
- `Engine` es el OB1: cola de trabajos + hilo dedicado `plc-ob1`. El hilo
  NO usa asyncio; ejecuta cada trabajo con `fb.execute(**params)`.
- `engine.submit(fb_name, **params) -> job_id`: encola el trabajo y
  devuelve el id. Lanza `FBBusyError` si el FB no existe o ya tiene un
  trabajo en curso (el router lo traduce a 409).
- `engine.cancel_job(job_id, reason)`: cancela el trabajo en cola o pide
  la cancelacion cooperativa al FB en curso.
- `engine.get_job(job_id)` / `list_jobs()` / `current_job_for(fb_name)`:
  consulta del estado de los trabajos.
- `engine.start_ob1()` / `stop_ob1(timeout)` / `ob1_running()`: ciclo de
  vida del hilo. Los arranca y detiene el supervisor
  (`core/launcher/main_supervisor.py`); el OB1 se para antes que el worker
  TIA, para que un trabajo en curso pueda terminar.
- **Orden de arranque** (`main_supervisor.start()`): worker TIA
  (`tia_client.start_tia_loop()`) → dispatcher OB1 (`engine.start_ob1()`)
  → hilo de Flask. El wrapper .NET se carga antes que Flask: si falla,
  `_build_components()` lanza y la app no arranca.
- **Orden de parada** (el inverso): Flask → OB1 → worker TIA.
- Un FB solo admite un trabajo en curso. Un fallo de un FB no mata el
  dispatcher: el error queda en el job y el hilo sigue vivo.
- `FunctionBase.execute(**params)` es el entry point del dispatcher:
  ejecuta el FB completo (`on_start` -> steps -> `on_finish`) y devuelve
  `self.result`. No propaga excepciones de runtime (las captura, las deja
  en `error_msg` y transiciona a `n_error`); si propaga
  `NotImplementedError` y `AssertionError`.
- `FunctionBase.request_cancel(reason)` es la cancelacion cooperativa
  sync y thread-safe: se puede pedir desde el hilo de Flask mientras el
  hilo del OB1 se ejecuta dentro de un step.
- El `ProgressTracker` es single-slot: solo hay un trabajo en curso a la
  vez.

### Timeouts de fetch (cliente)
- **2 buckets en uso** definidos en `core/web_server/static/js/api.js`:
  - `FAST_TIMEOUT_MS = 120_000` (2 min, default): lecturas puras
    (PLC list, logs, progress, catalog, memory, tia/connection,
    blocks, etc). Tipicamente <1s pero pueden dispararse a 30-60s
    en cold-start del backend.
  - `MEDIUM_TIMEOUT_MS = 300_000` (5 min): attach, open, preview,
    commit, upload Excel, connect. Tocan TIA Portal en cold-start,
    hacen export masivo o encolan un trabajo en el OB1 (responden
    202 de inmediato).
- **Ya no hay un tercer bucket**: `SLOW_TIMEOUT_MS` (600 s) se retiró al
  migrar los endpoints a 202. El trabajo pesado contra TIA (commit
  transaccional, preview) lo ejecuta el hilo del OB1, no el request: el
  router responde `202` con el `job_id` y el resultado llega por SSE. El
  `STEP_TIMEOUT_S` del FB (o el `timeout` que pase a `submit_and_wait`)
  acota el trabajo, no la respuesta HTTP.
- **Regla nueva al añadir endpoint**: clasificar el endpoint en uno
  de los 2 buckets y pasar el `timeoutMs` correspondiente al
  `_request()`. Si dudas, empieza por MEDIUM y sube si Aketza
  reporta timeouts.
- **Mensaje de timeout humano**: `_request()` NO muestra el
  `String(e)` crudo (`"AbortError: signal is aborted without reason"`).
  En su lugar, un mensaje con el tiempo esperado + hint accionable
  ("comprueba el estado del worker TIA" / "reinicia la app"). El
  operario debe ver algo accionable, no un `DOMException` interno
  del navegador.
- **Mismatched client/server**: el timeout del cliente debe ser
  siempre MAYOR que el `timeout` que el FB pase a `submit_and_wait`.
  Si lo reduces, asegúrate de que el cliente sigue siendo mayor (sube
  el bucket FAST/MEDIUM si hace falta).

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
- **Backend:** `pytest tests/` corre TODOS los tests. 1449 tests
  actualmente (1446 pasan, 3 skipped). Deben pasar todos antes de commit.
- **Naming:** `tests/test_<modulo>.py`. Mismo nombre que el archivo
  que prueban. Para áreas, `tests/test_area_<area>_<feature>.py`.
- **Mockear el cliente del worker** con `MagicMock(spec=SyncTIAClient)`.
  Para ProgressTracker, instanciar uno limpio (`ProgressTracker()`)
  y pasarlo al use case (no mockear el tracker).
- **Frontend:** sin tests automatizados (SPA ESM sin build step).
  QA manual con `?demo=1` y servidor de pruebas.

### Catálogo de comandos del worker OT

- `core/infrastructure/tia/tia_commands_catalog.py` es el punto único
  de verdad. Unión de los 9 módulos por categoría:

  | Categoría | Módulo | Comandos |
  |---|---|---|
  | Lifecycle (3) | `tia_cmd_lifecycle` | `attach_portal`, `detach_portal`, `open_new_portal` |
  | Project (3) | `tia_cmd_project` | `open_project`, `save_project`, `close_project` |
  | Inspect (5) | `tia_cmd_inspect` | `ping`, `list_plcs`, `list_blocks`, `get_project_info`, `scan_blocks` |
  | Compile (2) | `tia_cmd_compile` | `compile_plc`, `compile_blocks` |
  | Export (3) | `tia_cmd_export` | `export_blocks`, `export_udts`, `export_tables` |
  | Import (4) | `tia_cmd_import_` | `import_blocks_sd`, `import_plc_tags_xml`, `import_tag_table`, `import_block` |
  | User consts (4) | `tia_cmd_user_consts` | `get_user_constants`, `delete_user_constant`, `update_user_constant_value`, `update_user_constant_name` |
  | Blocks (1) | `tia_cmd_blocks` | `update_block_property` |
  | Batch (2) | `tia_cmd_batch` | `execute_batch`, `execute_transactional_batch` |

  Total: **27 comandos core** registrados en `CATALOGO` y cargados
  en el `SyncTIAClient` por `register_all_commands(client)` en el
  arranque del worker (no hay command loader separado).
- Los comandos de ciclo de vida (`attach_portal`, `detach_portal`) viven
  en `tia_cmd_lifecycle` y reasignan el portal con
  `tia_client.attach_wrapper(...)`. No los dupliques en otro módulo.
- Las áreas aportan comandos adicionales vía
  `areas/<área>/infrastructure/tia/extra_commands.py::register(tia_client)`
  — callable `(tia_client: SyncTIAClient) -> None` que llama
  `tia_client.register_command(name, handler)`. El supervisor
  (`core/launcher/main_supervisor._build_components()`) lo invoca
  tras `register_all_commands(tia_client)`. Patrón documentado pero
  ningún área del repo lo ha materializado todavía.
- **Firma de handler:** `Callable[[dict, SyncTIAClient], dict]`
  (alias `HandlerSig` en `tia_loop.py`). Acceso a `portal`/`ts`
  via `tia_client.wrapper` / `tia_client.ts` (single-threaded;
  los toca el `tia_loop`).
- **CRÍTICO:** los handlers extra NO importan `siemens_tia_scripting`
  directamente — ya está cargado en el proceso del worker y
  accesible via `tia_client.wrapper`.
- **Sí pueden** usar comandos genéricos del catálogo
  (`CATALOGO["export_blocks"](...)`) para participar de
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
  `AppCache` (`core/runtime/app_cache.py`) con `force_refresh=True`
  para bypass explícito.

### Paths de export/modificación (workdirs)
- Los workdirs de export/modificación siguen la convención:
  `.build_cache/<área>/<contexto>/{exports,modified,preview}`.
  `BuildCache` en `areas/<área>/helpers/layout/build_cache.py` es
  el punto de entrada (parametrizado por `area_id`); `SdPair` y
  `XmlTarget` en `core/infrastructure/tia/tia_export_paths.py`
  resuelven paths de archivos individuales.
- Es convención de la app, NO config del proyecto. No hay
  `ZC_BUILD_CACHE_DIR` todavía (YAGNI). Si lo necesitas, replica
  el patrón de `log_paths.py` (ZC_LOG_DIR).
- `ContextCache.clean()` borra y recrea `exports/` y `modified/`
  antes del apply; `preview/` NO se toca (puede contener dry-runs
  en curso o artefactos históricos que el operario quiere
  consultar).

### Path del config.json del usuario
- Patrón "template bundleado + copia writable al lado del .exe":
  `ConfigManager()` sin argumentos delega en
  `core/infrastructure/config/config_paths.py:resolve_config_path()`.
- Resolución: `$ZC_CONFIG_DIR/config.json` (override) →
  frozen: `<exe_dir>/config/config.json` (se copia del bundleado en
  primera ejecución) → dev: `<cwd>/config/config.json` (el
  del repo, sin copia) → fallback readonly al bundleado si no se
  puede escribir la ruta del usuario.
- Política: **el usuario gana siempre**. NO sobreescribimos un
  `config.json` existente. El operario borra el archivo a mano si
  quiere resetear al bundleado (primera ejecución = siguiente
  arranque copia el bundleado de nuevo).
- Compat: callers que pasan `config_path=` explícito (los tests y el
  router de plantillas) siguen funcionando idéntico. El
  resolver solo actúa cuando no se pasa path (o se pasa `None`).

### Convenciones frontend (Vue 3 ESM)
- **Sin build step:** el navegador carga módulos ESM directamente
  desde `/js/`. No usar `import.meta`, no usar TypeScript.
- **Estado global** en `store.js` con `reactive({...})`. Exportar
  `store` y helpers (`pushLog`, `goToArea`, etc.).
- **Fetch puro** en `api.js`: cada función devuelve
  `{ ok, status, data }`. NO toca `store` directamente.
- **Actualizaciones del store:** por SSE (`GET /stream`), no por polling.
  `main.js` no usa `setInterval`; los eventos del bus son la unica fuente.
- **ProgressIndicator.js** es el ÚNICO componente de feedback de
  operaciones largas. Va anclado al final del `AlimentacionSidebar`
  (`mt-auto`).

### Vue 3 sin build step — acceso a `store` desde templates
- **Problema:** si un componente hace
  `import { store } from "/js/store.js"` y NO retorna `store` desde
  el `setup()`, el template ve `store` como `undefined` y lanza
  `TypeError: Cannot read properties of undefined (reading
  'memoryState')` (o cualquier propiedad análoga).
- **Causa raíz:** Vue 3 con template compiler en runtime (sin build
  step) NO expone los `import` a nivel de módulo al scope del
  template. El template solo tiene acceso a lo que el `setup()`
  retorna explícitamente; el resto del módulo es invisible para él.
- **Solución:** encapsular el acceso a `store` en un `computed` y
  retornarlo del `setup()`. Ejemplo:

  ```javascript
  const data = computed(() => store.memoryState?.datos || null);
  return { data };
  // Template: <p>{{ data }}</p>
  ```

- **Caso real:** commit `19c8266` — `DispositivosPanel` intentaba
  acceder a `store.memoryState` directamente desde el template y
  reventaba con `Cannot read properties of undefined`. Lo arreglamos
  con `deviceCountsByTab`, un `computed` que lee
  `store.memoryState.dispositivos` y lo expone al template vía el
  objeto retornado por `setup()`. Regla general: cualquier cosa del
  módulo (`store`, helpers, refs importadas) que el template deba
  leer debe salir del `setup()`.

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
| Servidor dev (web) | `python main.py --web 127.0.0.1:9484` |
| Launcher bandeja | `python main.py` |
| Recompilar CSS | `tailwindcss-extra.exe -i core/web_server/static/src/input.css -o core/web_server/static/styles.css --minify` (también `run_tailwind.bat` si existe) |
| Build .exe | `python build_exe.py` |
| Test E2E manual | abrir `http://127.0.0.1:9484/` (demo: `?demo=1`) |

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
6. **El FB devuelve una corrutina:** `run_step` es sync (el FB corre en el
   hilo del OB1). Si devuelve una corrutina, el base lanza `TypeError`.
7. **El router devuelve 409 y el operario no ve nada:** el FB ya tenia un
   trabajo en curso. Un FB solo admite un trabajo a la vez.

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
| Cambios en TIA worker, modificadores XML/SD, parsers Excel, worker OT | `tia-ot-worker` |
| Routers Flask, use cases, `app_flask.py`, dependencias, tools MCP | `backend-api` |
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
