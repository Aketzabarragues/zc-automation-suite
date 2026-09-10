# Plan de migración a arquitectura PLC-style (IEC 61131-3)

> **Estado:** propuesta, pendiente de aprobación.
> **Fecha:** 2026-09-09
> **Operario:** Aketza
> **HEAD actual:** `9133c65 refactor(disp): unificar handler de comentarios en 1 sola tx con 6 ops`
> **Working tree:** limpio
> **Auditoría previa:** `_plan/17_frontend_simplification_audit.md`

---

## §1. Contexto y motivación

### 1.1 El problema

El frontend actual funciona, pero el operario siente que "cada uno va a lo suyo":

- 3 `setInterval` en `main.js` (logs 1s, progress 500ms, TIA 2s) que preguntan sin parar.
- 5 `if/else` anidados en `Dispositivos.js::ejecutarCommit` para manejar el commit.
- 4 paths de error distintos para `TIAConnectionError` (código duplicado en 4 sitios).
- El state machine del operario está implícito (botón deshabilitado, mensaje de alerta) — no hay un `nStep` discreto que diga "estás en el paso 2 de 3".

La cabeza del operario es de PLC (IEC 61131-3: SFC, CASE, `nStep`, marcas de bit). El modelo mental "REST asíncrono + reactividad Vue 3" no encaja con su esquema.

### 1.2 La solución

Migrar a un modelo **PLC-like explícito** en el backend + **HMI pasivo** en el frontend:

- **FBs (Function Blocks)** con `nStep` discreto (10, 20, 30, …, 99 = error).
- **DBs (Data Blocks)** como memoria compartida (dataclasses in-memory).
- **Engine** = el OB1 que tickea todos los FBs activos cada 100ms y publica cambios.
- **SSE** = el canal de notificación del HMI (1 conexión abierta, push, sin polling).
- **Web** = HMI puro: arranca FBs vía POST, escucha SSE, pinta `nStep` + `progress`. **No pregunta, no orquesta, no encadena awaits.**

### 1.3 Lo que NO cambia

- ✅ El **worker persistente** (`core/infrastructure/tia/worker_tia.py`) — el attach a TIA Portal sigue siendo persistente. El Engine lo envuelve, no lo reemplaza.
- ✅ El **gráfico** (UI, tema Industrial Claro, `styles.css`, `input.css`, componentes Vue) — el operario confirma que le gusta.
- ✅ Los **tests existentes** del worker, del config, del excel parser, del frontend.
- ✅ El **backend de FastAPI** (la app, los routers existentes que se mantienen).

---

## §2. El modelo objetivo

### 2.1 Mapeo IEC 61131-3 → Python/FastAPI/Vue 3

| Concepto IEC | En el proyecto |
|---|---|
| **FB (Function Block)** con `nStep` | Clase Python con método `tick()` que avanza etapas |
| **DB (Data Block)** | Dataclass compartida, accesible desde los FBs |
| **OB1 (scan cíclico)** | `Engine._loop()` que tickea FBs cada 100ms |
| **`EN` / `ENO`** | `start()` / retorno de `tick()` (None = OK, exception = ERROR) |
| **Bits M (merkers)** | Atributos del `DB_EstadoConexion` |
| **Mailbox HMI↔PLC** | Endpoints REST + SSE |
| **HMI** | SPA con el composable `usePlc` |

### 2.2 Reglas arquitectónicas

1. **Core = 100% trasversal.** Solo vive en `core/` lo que TODAS las áreas necesitan: conexión con TIA, state machine del worker, engine, event bus, routers genéricos.
2. **FBs específicos de cada área.** Los FBs de alimentación (SincronizarDispositivos, LeerExcel, etc.) viven en `areas/alimentacion/plc/`. Las áreas futuras traerán los suyos.
3. **DBs por área.** Las DBs de alimentación (DB_Excel_Alim, DB_CachePLC_Alim) viven en `areas/alimentacion/plc/data.py`. La única DB trasversal es `DB_EstadoConexion` (en `core/plc/plc.py`).
4. **El router del core es genérico.** `POST /api/v1/plc/fb/{name}/start` busca el FB en `engine.fbs` por nombre. No conoce FBs específicos.
5. **El HMI no orquesta.** Solo arranca FBs (`plc.startFb(name, params)`) y escucha SSE.
6. **El worker persistente sigue siendo persistente.** El Engine arranca el `worker_tia` al iniciar la app y lo deja vivo. El FB_ConexionTIA solo le dice `attach`/`detach`/`list_plcs`.

### 2.3 Convenciones de nombres (acordadas con el operario)

- `data.py` (no `dbs.py`): las DBs trasversales o por área.
- `functions.py` (no `fbs.py`): los FBs por área.
- `plc.py` (en `core/`): el Engine + FB_Base + DB_EstadoConexion trasversal.
- `worker_bridge.py` (en `core/`): adapter FBs → worker_tia.

---

## §3. Estructura de archivos final

```
zc-automation-suite/
├── .gitignore
├── .gitattributes
├── README.md
├── LICENSE
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── main_tray.py                          # ÚNICO entry point
├── build_exe.py
├── pytest.ini
├── conftest.py
├── ruff.toml
│
├── PLC_IE_61131_MIGRATION.md             # este documento
│
├── tests/
│   ├── core/                             # tests del core trasversal
│   │   ├── test_plc_engine.py
│   │   ├── test_fb_base.py
│   │   ├── test_event_bus.py
│   │   ├── test_db_estado_conexion.py
│   │   ├── test_routers_plc.py
│   │   ├── test_routers_areas.py
│   │   ├── test_routers_catalog.py
│   │   ├── test_routers_logs.py
│   │   ├── test_routers_progress.py
│   │   ├── test_routers_health.py
│   │   ├── test_config_manager.py
│   │   ├── test_config_paths.py
│   │   ├── test_log_buffer.py
│   │   ├── test_log_paths.py
│   │   ├── test_progress_buffer.py
│   │   ├── test_excel_parser.py
│   │   ├── test_excel_cache.py
│   │   ├── test_worker_tia.py
│   │   └── test_pyinstaller_siemens_loader.py
│   │
│   ├── areas/                            # tests por área (FBs específicos)
│   │   ├── test_area_registry.py
│   │   ├── test_manifest_drift.py
│   │   └── alimentacion/
│   │       ├── test_register.py
│   │       ├── test_functions_sincronizar_dispositivos.py
│   │       ├── test_functions_leer_excel.py
│   │       ├── test_functions_cachear_bloques.py
│   │       └── test_functions_sincronizar_comentarios.py
│   │
│   └── frontend/                         # smoke tests de la SPA
│       ├── test_spa_wiring.py
│       ├── test_composables.py
│       ├── test_components_essential.py
│       └── test_manifest_drift.py
│
├── core/                                 # TRASVERSAL — solo lo común a todas las áreas
│   ├── plc/                              # el "PLC" base
│   │   ├── __init__.py
│   │   ├── plc.py                        # Engine + FB_Base + DB_EstadoConexion + event bus
│   │   └── worker_bridge.py              # adapter FBs → worker_tia
│   ├── infrastructure/
│   │   ├── tia/worker_tia.py             # subproceso persistente + COM a TIA Portal
│   │   ├── config/
│   │   │   ├── config_manager.py
│   │   │   ├── config_paths.py
│   │   │   └── schema.py
│   │   ├── logging/
│   │   │   ├── log_buffer.py
│   │   │   ├── log_paths.py
│   │   │   └── progress_buffer.py
│   │   ├── excel/
│   │   │   ├── excel_parser.py
│   │   │   └── excel_cache.py
│   │   └── pyinstaller/
│   │       └── siemens_loader.py
│   ├── interfaces/
│   │   └── web_server/
│   │       ├── app.py
│   │       ├── deps.py
│   │       ├── exceptions.py
│   │       └── routers/
│   │           ├── plc.py                # GENÉRICO: POST /plc/fb/{name}/start + GET /plc/events
│   │           ├── areas.py
│   │           ├── catalog.py
│   │           ├── logs.py
│   │           ├── progress.py
│   │           └── health.py
│   └── application/
│       └── state.py
│
├── areas/                                # BOUNDED CONTEXTS — FBs específicos
│   ├── __init__.py
│   ├── _registry.py
│   └── alimentacion/
│       ├── __init__.py                   # AREA_SPEC + register(engine, app)
│       ├── manifest.py
│       ├── plc/
│       │   ├── __init__.py               # register_plc(engine)
│       │   ├── data.py                   # DB_Excel_Alim, DB_CachePLC_Alim
│       │   └── functions.py              # 4 FBs específicos de alimentación
│       ├── routers.py                    # endpoints específicos (NO FBs)
│       └── frontend/
│           ├── manifest.js
│           ├── lib/disp_status.js
│           └── components/
│               ├── Sidebar.js
│               ├── AreaLanding.js
│               ├── MainTabs.js
│               ├── DispositivosPanel.js
│               ├── ProcesosPanel.js
│               ├── DefinicionProgramacion.js
│               ├── Dispositivos.js
│               ├── Procesos.js
│               ├── PlcStatusCard.js
│               ├── BlocksTable.js
│               └── ProcesosSyncView.js
│
└── interfaces/
    └── web_server/                       # FastAPI static + JS
        ├── static/
        │   ├── index.html
        │   ├── Logos Zeus Control.png
        │   ├── styles.css
        │   ├── favicon.ico
        │   ├── src/input.css
        │   └── js/
        │       ├── main.js
        │       ├── api.js
        │       ├── composables/
        │       │   ├── usePlc.js
        │       │   ├── useTiaError.js
        │       │   └── useTabStrip.js
        │       ├── components/
        │       │   ├── Welcome.js
        │       │   ├── ConsolaLogs.js
        │       │   ├── ShellTopbar.js
        │       │   ├── ShellSidebar.js
        │       │   ├── TiaConnectionIndicator.js
        │       │   ├── WorkerStatusIndicator.js
        │       │   ├── FlowProgress.js
        │       │   └── EmptyState.js
        │       └── vendor/vue.esm-browser.prod.js
        ├── run_tailwind.bat
        └── run_pyinstaller.bat
```

---

## §4. Plan de PRs

3 PRs secuenciales. Cada PR es autocontenido, testeable, y deja el sistema en un estado funcional. **El operario puede parar después de cualquier PR y tener algo que funciona** (con la salvedad de que PR 1 deja la SPA sin cambios y PR 3 deja la API antigua en desuso).

| PR | Título | Esfuerzo | Riesgo | Resultado al cerrar |
|---|---|---:|---|---|
| **PR 1** | El PLC base (Engine + FB_Base + DB_EstadoConexion + FB_ConexionTIA + router genérico) | 2-3 días | medio (SSE nuevo) | Backend puede recibir POST /plc/fb/ConexionTIA/start + servir SSE. Worker persistente sigue arrancando. |
| **PR 2** | Las áreas registran FBs (alimentación enchufa sus 4 FBs) | 2-3 días | bajo | Los 4 FBs de alimentación se pueden arrancar vía POST, se ven en el SSE, y los `tests/areas/alimentacion/test_*.py` pasan. |
| **PR 3** | El HMI pasivo (usePlc.js + migración de Dispositivos.js + componentes) | 2-3 días | medio (cambios UI, validar con S7-1500) | El frontend arranca FBs por SSE, sin polling, sin 5 if/else anidados. |
| **PR 4** (opcional) | Limpieza final (borrar código obsoleto, polling, setInterval) | 1 día | bajo | Repo en estado "mínimo", sin código muerto. |

**Total: 7-10 días de trabajo.**

---

## §5. PR 1 — El PLC base

### 5.1 Objetivo

Crear el "PLC" en Python: Engine + FB_Base + DB_EstadoConexion + event bus + 1 FB de prueba (FB_ConexionTIA) + el router genérico que arranca FBs por nombre y sirve SSE. El worker_tia se mantiene intacto; el Engine lo envuelve.

### 5.2 Archivos

**CREAR:**

- `core/plc/__init__.py` (~15 líneas): exporta `Engine`, `FB_Base`, `register_fb`, `ENGINE`.
- `core/plc/plc.py` (~250 líneas): Engine + FB_Base + DB_EstadoConexion + FB_ConexionTIA + event bus. **Trasversal puro.**
- `core/plc/worker_bridge.py` (~60 líneas): adapter FBs → worker_tia. Métodos: `attach()`, `detach()`, `list_plcs()`, `commit_devices_sync(plc_name, prevision)`, `generate_sync_preview(plc_name)`, `parse_excel(bytes)`, `scan_plc_blocks(plc_name)`. **Es la fachada que los FBs llaman.** Si en el futuro cambian las llamadas al worker, solo cambia este archivo.
- `core/interfaces/web_server/routers/plc.py` (~80 líneas): 2 endpoints.
- `core/interfaces/web_server/deps.py` (~30 líneas): `Depends(ENGINE)` + `Depends(WorkerBridge)`.

**MODIFICAR:**

- `core/interfaces/web_server/app.py`: añadir `app.include_router(plc_router, prefix="/api/v1")` y en el `lifespan` arrancar `ENGINE.start_loop()` + `ENGINE.attach_worker(worker_bridge)`.
- `main_tray.py`: ningún cambio si ya arranca la app.
- `pyproject.toml`: añadir la dependencia de `sse-starlette` si se usa (alternativa: usar `StreamingResponse` nativo de FastAPI — **preferimos esta**, sin dep extra).

**NO TOCAR (aún):** la SPA, los use_cases existentes, los routers de áreas/catalog/logs/progress/health (siguen funcionando como antes).

### 5.3 Diseño detallado de los archivos clave

Ver **Apéndice A** para el código completo de:
- `core/plc/plc.py` (Engine + FB_Base + DB_EstadoConexion + FB_ConexionTIA)
- `core/plc/worker_bridge.py` (la fachada)
- `core/interfaces/web_server/routers/plc.py` (los 2 endpoints)

### 5.4 Tests

| Test | Cubre |
|---|---|
| `test_plc_engine.py::test_loop_ticks_active_fbs` | El Engine tickea los FBs con `nStep > 0` cada 100ms. |
| `test_plc_engine.py::test_loop_skips_idle_fbs` | Los FBs con `nStep == 0` o terminal NO se tickean. |
| `test_plc_engine.py::test_loop_publishes_state_change` | Cuando un FB cambia de `nStep`, se publica al event bus. |
| `test_fb_base.py::test_fb_start_resets_state` | `start()` resetea `nStep`, `nError`, `error_msg`. |
| `test_fb_base.py::test_fb_terminal_states` | `nStep == 0` o `>= 40` (terminal) no avanza. |
| `test_event_bus.py::test_subscribe_receives_events` | 2 conexiones SSE reciben el mismo evento. |
| `test_event_bus.py::test_unsubscribe_stops_events` | Tras `unsubscribe`, no se reciben más eventos. |
| `test_db_estado_conexion.py::test_default_state` | `state == "idle"`, `worker_alive == False`. |
| `test_routers_plc.py::test_post_start_fb_unknown_returns_404` | `POST /plc/fb/NoExiste/start` → 404. |
| `test_routers_plc.py::test_post_start_fb_known_returns_ok` | `POST /plc/fb/ConexionTIA/start` → 200 + `nStep` actualizado. |
| `test_routers_plc.py::test_get_events_sse_streams` | `GET /plc/events` con `Accept: text/event-stream` → 200 + `Content-Type: text/event-stream`. |

### 5.5 Validación manual (antes de mergear)

1. `pytest tests/core/ -v` → todos verdes.
2. `python main_tray.py` → la app arranca sin errores.
3. En otra terminal, `curl -N http://127.0.0.1:8000/api/v1/plc/events` → debe quedarse esperando y mostrar el snapshot inicial.
4. En otra terminal, `curl -X POST http://127.0.0.1:8000/api/v1/plc/fb/ConexionTIA/start` → el FB arranca, el SSE emite eventos, `nStep` avanza 10 → 20 → 30.
5. Verificar que el log del worker muestra "attach OK" y "PLCs listados" (lo que ya hace el worker actual).
6. **NO** abrir la SPA en el navegador todavía — la UI sigue usando el flujo viejo (polling). Es esperado.

### 5.6 Riesgos

- **SSE con PyInstaller:** hay que validar que `StreamingResponse` funciona bien cuando se empaqueta. Si da problemas, fallback: `sse-starlette` (1 dep extra).
- **El `worker_tia` debe seguir arrancando igual que antes.** El `Engine.attach_worker(worker_bridge)` no debe cambiar el ciclo de vida del subproceso. Validar que `worker_alive` se mantiene en `True` a lo largo de los ticks.
- **CORS / proxies:** SSE a veces se corta por proxies corporativos. Como la app es desktop + local, no debería pasar. Pero el test manual debe ser en el mismo Windows que la operario.

---

## §6. PR 2 — Las áreas registran FBs

### 6.1 Objetivo

El área `alimentacion` enchufa sus 4 FBs específicos (SincronizarDispositivos, LeerExcel, CachearBloquesPLC, SincronizarComentarios) y sus 2 DBs (DB_Excel_Alim, DB_CachePLC_Alim) al Engine trasversal. El router genérico los encuentra por nombre y los arranca vía POST.

### 6.2 Archivos

**CREAR:**

- `areas/alimentacion/plc/__init__.py` (~20 líneas): `register_plc(engine, worker_bridge)` que crea las 2 DBs y registra los 4 FBs.
- `areas/alimentacion/plc/data.py` (~50 líneas): 2 dataclasses.
- `areas/alimentacion/plc/functions.py` (~250 líneas): 4 clases FB.
- `tests/areas/alimentacion/test_register.py` (~50 líneas).
- `tests/areas/alimentacion/test_functions_*.py` (4 archivos, ~80 líneas c/u).

**MODIFICAR:**

- `areas/alimentacion/__init__.py`: añadir `register(engine, app)` que llama a `register_plc(engine)` y monta el router de áreas.
- `core/interfaces/web_server/app.py`: añadir `from areas.alimentacion import register as register_alimentacion` y `register_alimentacion(ENGINE, app)` en el lifespan.

**NO TOCAR (aún):** la SPA, `main_tray.py`, el `worker_tia`.

### 6.3 Diseño del `register_plc`

```python
# areas/alimentacion/plc/__init__.py
def register_plc(engine, worker_bridge):
    """Enchufa los FBs y DBs específicos de alimentación en el Engine del core."""
    from .data import DB_Excel_Alim, DB_CachePLC_Alim
    from .functions import (
        FB_SincronizarDispositivos,
        FB_LeerExcel,
        FB_CachearBloquesPLC,
        FB_SincronizarComentarios,
    )
    engine.register_db("excel_alim", DB_Excel_Alim)
    engine.register_db("cache_plc_alim", DB_CachePLC_Alim)
    engine.register_fb("SincronizarDispositivos", FB_SincronizarDispositivos(
        bridge=worker_bridge,
        db_excel=DB_Excel_Alim,
        db_cache_plc=DB_CachePLC_Alim,
        db_estado=engine.db_estado,           # trasversal, del core
    ))
    engine.register_fb("LeerExcel", FB_LeerExcel(
        bridge=worker_bridge,
        db_excel=DB_Excel_Alim,
        db_cache_plc=DB_CachePLC_Alim,
    ))
    engine.register_fb("CachearBloquesPLC", FB_CachearBloquesPLC(
        bridge=worker_bridge,
        db_cache_plc=DB_CachePLC_Alim,
        db_estado=engine.db_estado,
    ))
    engine.register_fb("SincronizarComentarios", FB_SincronizarComentarios(
        bridge=worker_bridge,
        db_cache_plc=DB_CachePLC_Alim,
        db_excel=DB_Excel_Alim,
    ))
```

### 6.4 Diseño de los 4 FBs (resumen, código completo en Apéndice A.4)

| FB | Etapas (`nStep`) | Qué hace |
|---|---|---|
| `FB_SincronizarDispositivos` | 10 validar → 20 commit atómico → 30 refrescar prevision → 40 done | El "commit dispositivos" completo, antes partido en 2 awaits en el frontend. |
| `FB_LeerExcel` | 10 parsear → 20 volcar al AppState → 30 invalidar cache PLC → 40 done | El "subir Excel + refrescar" del frontend, ahora 1 flow. |
| `FB_CachearBloquesPLC` | 10 escanear bloques → 20 cachear localmente → 30 done | El "↻ Actualizar" del BloquesCacheView, ahora 1 flow. |
| `FB_SincronizarComentarios` | 10 preview → 20 aplicar atómico → 30 done | El sync comentarios de procesos. |

### 6.5 Tests de los FBs

Cada FB se testea con mocks del `worker_bridge` (no se necesita TIA Portal real). Patrón:

```python
# tests/areas/alimentacion/test_functions_sincronizar_dispositivos.py
@pytest.mark.asyncio
async def test_fb_sync_avanzando_nSteps_en_orden():
    bridge = MagicMock()
    bridge.commit_devices_sync = AsyncMock(return_value={"ok": True, "operations_executed": 47, "post_sync_preview": {...}})
    bridge.generate_sync_preview = AsyncMock(return_value={...})
    db_excel = DB_Excel_Alim()
    db_cache = DB_CachePLC_Alim()
    db_estado = DB_EstadoConexion()
    fb = FB_SincronizarDispositivos(bridge=bridge, db_excel=db_excel, db_cache_plc=db_cache, db_estado=db_estado)
    fb.start(plc_name="PLC_1", prevision={"todos": []})
    assert fb.nStep == 10
    await fb.tick()  # validar
    assert fb.nStep == 20
    await fb.tick()  # commit
    assert fb.nStep == 30
    assert bridge.commit_devices_sync.await_count == 1
    await fb.tick()  # refrescar
    assert fb.nStep == 40
    assert fb.nError == 0
```

### 6.6 Validación manual

1. `pytest tests/areas/alimentacion/ -v` → todos verdes.
2. `python main_tray.py` → arranca, en el log debe verse "Engine started, FBs registered: ConexionTIA, SincronizarDispositivos, LeerExcel, CachearBloquesPLC, SincronizarComentarios".
3. `curl -N http://127.0.0.1:8000/api/v1/plc/events` → snapshot inicial con `fbs` listado: ConexionTIA, SincronizarDispositivos, LeerExcel, etc.
4. `curl -X POST http://127.0.0.1:8000/api/v1/plc/fb/ConexionTIA/start` → arranca, SSE emite eventos hasta `nStep == 30` (conectado).
5. Validar con S7-1500 real: pulsar el botón "Conectar" del TiaConnectionIndicator, ver que la grid de PLCs aparece (a través del polling viejo, todavía, porque la SPA no ha migrado — esperado).
6. **NO** abrir todavía `usePlc` en la SPA. Solo validar por `curl`.

### 6.7 Riesgos

- Los FBs del área dependen del `worker_bridge` (no del `worker_tia` directamente). Si el bridge cambia su API, hay que actualizar las firmas. **Documentar el contrato del bridge en el docstring de cada FB.**
- Las áreas futuras (envasado) traerán sus propios FBs y DBs. Validar que el patrón `register_plc(engine, worker_bridge)` escala.

---

## §7. PR 3 — El HMI pasivo

### 7.1 Objetivo

La SPA deja de hacer polling y de orquestar. El composable `usePlc` abre 1 conexión SSE, expone los DBs y FBs como `reactive`, y `startFb(name, params)` dispara el FB del backend. Los componentes se vuelven "tontos": leen `plc.FBs.SincronizarDispositivos.nStep` y pintan.

### 7.2 Archivos

**CREAR:**

- `interfaces/web_server/static/js/composables/usePlc.js` (~100 líneas): el composable principal.
- `interfaces/web_server/static/js/composables/useTiaError.js` (~20 líneas): encapsula `if (r.errorType === "TIAConnectionError")`.
- `interfaces/web_server/static/js/composables/useTabStrip.js` (~50 líneas, opcional): extrae el patrón de 5 strips de tabs.
- `interfaces/web_server/static/js/components/FlowProgress.js` (~80 líneas): reemplaza al `ProgressIndicator.js`. Lee `plc.FBs[fbName]` y pinta el `nStep` + `progress` + `step_name`.
- `interfaces/web_server/static/js/components/EmptyState.js` (~25 líneas): extraído de 6 sitios.
- `tests/frontend/test_composables.py` (~80 líneas): smoke tests del composable.

**MODIFICAR (simplificar):**

- `interfaces/web_server/static/js/main.js`: borrar los 3 `setInterval`. Dejar solo el bootstrap.
- `interfaces/web_server/static/js/api.js`: borrar `apiAttachPortal`, `apiOpenNewPortal`. Reducir a ~80 líneas.
- `interfaces/web_server/static/js/components/ProgressIndicator.js` → renombrar a `FlowProgress.js` y migrar a leer de `usePlc` (en lugar de `store.progress`).
- `interfaces/web_server/static/js/components/ShellTopbar.js`: usar `usePlc().DBs.estado` en lugar de `store.tiaConnection`.
- `interfaces/web_server/static/js/components/TiaConnectionIndicator.js`: usar `usePlc().DBs.estado`.
- `interfaces/web_server/static/js/components/WorkerStatusIndicator.js`: igual.
- `areas/alimentacion/frontend/components/Dispositivos.js`: `ejecutarCommit` de 50 líneas a 15 (1 composable + 1 switch sobre `event.state`).
- `areas/alimentacion/frontend/components/ProcesosSyncView.js`: `handleApply` y `handleGeneratePreview` colapsados.
- `areas/alimentacion/frontend/components/DefinicionProgramacion.js`: `handleExcel` simplificado.
- `areas/alimentacion/frontend/components/BloquesCacheView.js`: partido en `PlcStatusCard.js` + `BlocksTable.js`.

**BORRAR:**

- `interfaces/web_server/static/js/store.js` (1.196 líneas). Su funcionalidad vive ahora en el composable `usePlc` (DBs y FBs como `reactive`).

### 7.3 Diseño del `usePlc.js`

Ver **Apéndice B** para el código completo.

### 7.4 Tests

- `test_composables.py::test_usePlc_exposes_dbs_and_fbs`: el composable exporta DBs, FBs, lastResult, startFb, isIdle, isRunning, isDone, isError.
- `test_composables.py::test_usePlc_opens_sse_on_mount`: al montar, abre EventSource.
- `test_composables.py::test_usePlc_closes_sse_on_unmount`: al desmontar, cierra EventSource.
- `test_composables.py::test_usePlc_updates_state_on_event`: cuando llega un evento por SSE, `plc.FBs[nombre]` se actualiza reactivamente.
- `test_composables.py::test_startFb_posts_to_router`: `startFb(name, params)` hace POST a `/api/v1/plc/fb/{name}/start`.

### 7.5 Validación manual (CRÍTICA — S7-1500 real)

1. `pytest tests/ -v` → todos verdes.
2. `python main_tray.py` → arranca.
3. Abrir `http://127.0.0.1:8000/?demo=1` en el navegador.
4. **Verificar visualmente:**
   - Welcome se muestra con el logo y la grid de áreas.
   - Click en "Alimentación" → entra al área.
   - El sidebar muestra las 4 sub-vistas, el ShellTopbar muestra el breadcrumb.
   - El `TiaConnectionIndicator` del ShellTopbar muestra el estado del worker (idle/connecting/connected).
5. **Pulsar "Conectar":** el círculo del topbar pasa a ámbar pulsante (connecting), luego a verde (connected). El bloque de estado del BloquesCacheView muestra el nombre del proyecto y la grid de PLCs.
6. **Seleccionar un PLC:** la grid de BloquesCacheView marca el PLC como seleccionado, dispara `FB_CachearBloquesPLC` automáticamente.
7. **Pulsar "Generar Previsión" en Dispositivos:** el botón cambia a "Generando... XX%", `nStep` avanza, al final muestra el resultado. **Cero polling en la consola del navegador** (verificar en DevTools Network).
8. **Pulsar "Aplicar Cambios":** similar, con el commit de 5-300 segundos. El operario ve el `nStep` avanzar (validando → commiteando → refrescando).
9. **Subir un Excel (.xlsx) en Definición Programación:** `FB_LeerExcel` se dispara, el operario ve el progreso.
10. **Probar el sync de comentarios en Procesos:** `FB_SincronizarComentarios`.
11. **Pulsar "Desconectar":** el worker pasa a `idle`, la grid de PLCs se vacía.

### 7.6 Riesgos

- **Validación con S7-1500 real es OBLIGATORIA.** No mergear sin probar en HW real. Los flujos de tiempo (5-300s) son donde aparecen los bugs.
- **El SSE puede tener un buffer pequeño.** Si el operario no ve la UI por 30 segundos y el buffer del SSE se llena, perdemos eventos. `asyncio.Queue(maxsize=200)` debería bastar; validar.
- **El `reactive` de Vue 3 con objetos anidados** (DB_EstadoConexion.project es un objeto) puede tener problemas de reactividad si se hace `Object.assign`. **Usar siempre `Object.assign(reactive_obj, nuevos_campos)`** y nunca reasignar.
- **El store.js se borra.** Si algún componente (legacy) sigue importando de él, fallará. Validar con `grep -r "from .*store.js" interfaces/ areas/`.

---

## §8. PR 4 (opcional) — Limpieza final

### 8.1 Objetivo

Borrar todo el código obsoleto que dejó la migración:
- `core/application/use_cases/*` (reemplazados por FBs del área).
- `core/infrastructure/gateway.py` (reemplazado por `worker_bridge.py`).
- Polling en `main.js` (si quedó algo).
- Tests obsoletos que cubrían use_cases.

### 8.2 Archivos a borrar

- `core/application/use_cases/commit_devices_sync.py`
- `core/application/use_cases/generate_sync_preview.py`
- `core/application/use_cases/scan_plc_blocks.py`
- `core/application/use_cases/upload_excel.py`
- `core/application/use_cases/sync_procesos_comments.py`
- `core/infrastructure/gateway.py`
- Los `tests/core/test_use_cases_*.py` correspondientes.

### 8.3 Validación

- `grep -r "from core.application.use_cases" core/ areas/ tests/` → 0 resultados.
- `grep -r "from core.infrastructure.gateway" core/ areas/ tests/` → 0 resultados.
- `pytest tests/ -v` → todos verdes.

---

## §9. Criterios de éxito (cuándo está "hecho")

✅ **PR 1 cerrado** cuando:
- `pytest tests/core/ -v` pasa (≥10 tests nuevos).
- `curl /plc/events` funciona y emite snapshot + eventos.
- El worker_tia sigue arrancando con el Engine al lado (validar con S7-1500).
- 0 cambios en la SPA (sigue funcionando como antes).

✅ **PR 2 cerrado** cuando:
- `pytest tests/areas/alimentacion/ -v` pasa (≥5 tests nuevos).
- Los 4 FBs de alimentación se pueden arrancar vía POST y llegan a `nStep == 40`.
- El snapshot SSE los lista.

✅ **PR 3 cerrado** cuando:
- `pytest tests/frontend/ -v` pasa.
- La SPA funciona end-to-end con un S7-1500 real: Conectar, listar PLCs, generar prevision, aplicar, sync comentarios, subir Excel, desconectar.
- DevTools Network muestra 0 polling a `/api/v1/logs` y `/api/v1/progress/current`. Solo 1 EventSource a `/api/v1/plc/events`.
- El store.js está borrado.
- Los 5 if/else anidados de `ejecutarCommit` son 1 switch sobre `event.state`.

✅ **PR 4 cerrado** cuando:
- `grep` no encuentra referencias a los use_cases ni al gateway.
- Todos los tests siguen pasando.

---

## §10. Riesgos y notas globales

### 10.1 Compatibilidad con el worker persistente

- El `worker_tia.py` se mantiene **INTACTO**. El Engine lo envuelve vía `worker_bridge.py`, no lo reemplaza.
- El subproceso sigue arrancando al iniciar la app, igual que hoy.
- El attach a TIA Portal sigue siendo persistente. Si el operario cambia de área o hace F5, el worker no se reinicia.
- **Validar con S7-1500 en cada PR** que el attach se mantiene.

### 10.2 Compatibilidad con tests existentes

- Los tests del frontend (`test_frontend_*.py`) validan la presencia de símbolos. Si borramos `apiAttachPortal` o `apiOpenNewPortal`, hay que actualizar los tests. **Verificar antes de borrar.**
- Los tests del worker, del config, del excel parser, del log buffer: **no se tocan.**
- Los tests de `test_manifest_drift.py` (JS == Python): se mantienen.

### 10.3 Compatibilidad con el `.exe` de PyInstaller

- `sse-starlette` se evita (preferimos `StreamingResponse` nativo de FastAPI) para no añadir deps.
- `main_tray.py` no cambia.
- Validar el empaquetado al final del PR 3 (no antes, sería perder tiempo).

### 10.4 Compatibilidad con la SPA (gráfico)

- El operario confirma que el gráfico se queda como está.
- Los componentes Vue existentes se mantienen (solo se les cambia la fuente de datos: de `store` a `usePlc`).
- El tema Industrial Claro, `input.css`, `styles.css`: **no se tocan**.

### 10.5 Cosas que NO se deben tocar

1. `core/infrastructure/tia/worker_tia.py` (el subproceso persistente).
2. `interfaces/web_server/static/styles.css` y `src/input.css` (el tema).
3. `interfaces/web_server/static/js/components/ShellTopbar.js` y `ShellSidebar.js` (solo se les cambia la fuente de datos, no la estructura).
4. El Manifest y `area-loader.js` (multi-área sin build step).

### 10.6 Orden de ejecución recomendado

PR 1 → PR 2 → PR 3 → PR 4. **No saltar PRs.** Cada uno valida el anterior y deja el sistema en un estado funcional. Si PR 1 falla, replanificar antes de PR 2.

### 10.7 Si algo falla

- **Si SSE no funciona en PyInstaller:** añadir `sse-starlette` (1 dep) y migrar.
- **Si el SSE se corta con un proxy corporativo:** añadir un heartbeat cada 30s (enviar `event: ping\n\n` aunque no haya cambios).
- **Si el operario reporta "no veo el progreso":** probablemente es un bug en la reactividad de Vue 3 con `Object.assign` sobre `reactive`. **NO** reasignar `reactive_obj = new_obj`, siempre `Object.assign(reactive_obj, ...)`.
- **Si el S7-1500 no responde a un comando:** verificar que `worker_bridge.commit_devices_sync()` está envolviendo bien el `gateway` original o llamando directamente al `worker_tia` con msgpack.

---

## Apéndice A — Código del PLC base

### A.1 `core/plc/plc.py`

```python
# core/plc/plc.py
#
# El "PLC" base: Engine + FB_Base + DB_EstadoConexion + event bus.
# Trasversal a todas las áreas. Los FBs específicos viven en areas/<area>/plc/functions.py.

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional


# ─── DB TRASVERSAL ────────────────────────────────────────────────
# Vive aquí porque TODAS las áreas necesitan leer/escribir este estado.
# Los DBs específicos de área (DB_Excel_Alim, etc.) viven en areas/<area>/plc/data.py.

@dataclass
class DB_EstadoConexion:
    """DB Estado Conexion. Lo que el HMI muestra en el topbar.
    Escrito por FB_ConexionTIA y por el worker_bridge (heartbeat)."""
    worker_alive: bool = False           # subproceso Python vivo
    tia_state: str = "idle"              # idle | connecting | connected | error
    project_name: str = ""
    project_path: str = ""
    plcs: list = field(default_factory=list)
    last_error: str = ""
    last_ping_ok_unix: float = 0.0


# ─── FB BASE ──────────────────────────────────────────────────────
# Heredan de aquí los FBs del core (FB_ConexionTIA) y los de las áreas.

class FB_Base:
    """Base común: nStep + nError + tick() abstracto.
    Convenciones:
        nStep == 0            → idle (no hace nada)
        0 < nStep < n_done    → ejecutando una etapa
        nStep == n_done       → done (estado terminal OK)
        nStep == 99           → error (estado terminal ERROR)
    """
    n_done: int = 99   # override en subclase: 30, 40, etc.
    n_error: int = 99

    def __init__(self, nombre: str):
        self.nombre = nombre
        self.nStep = 0
        self.nError = 0
        self.error_msg = ""
        self.progress = 0           # 0..100
        self.step_name = ""         # etiqueta humano-legible
        self.result = None          # último resultado (cuando nStep == n_done)

    def start(self, **params) -> None:
        """El HMI llama a start() para arrancar el FB. Sobrescribir si necesita params."""
        if self.nStep not in (0, self.n_done, self.n_error):
            return                  # ya está corriendo, ignora
        self.nStep = 10
        self.nError = 0
        self.error_msg = ""
        self.progress = 0
        self.result = None
        self._on_start(**params)    # hook para subclases

    def _on_start(self, **params) -> None:
        """Override en subclase para procesar los params de start()."""
        pass

    async def tick(self) -> None:
        """El Engine llama a tick() cada 100ms. Override obligatorio en subclase."""
        raise NotImplementedError

    def get_state(self) -> dict:
        """Snapshot del estado del FB para publicar al SSE."""
        return {
            "type": "fb",
            "name": self.nombre,
            "nStep": self.nStep,
            "nError": self.nError,
            "error": self.error_msg,
            "progress": self.progress,
            "step_name": self.step_name,
        }


# ─── FB TRASVERSAL: ConexionTIA ───────────────────────────────────
# Lo necesita TODAS las áreas (todas conectan a TIA Portal).

class FB_ConexionTIA(FB_Base):
    """FB ConexionTIA.
        Etapa 10 - Conecta con TIA Portal
        Etapa 20 - Listar PLCs del proyecto
        Etapa 30 - Conectado (terminal OK)
        Etapa 99 - Error (terminal ERROR)
    """
    n_done = 30
    n_error = 99

    def __init__(self, worker_bridge, db_estado: DB_EstadoConexion):
        super().__init__("ConexionTIA")
        self.bridge = worker_bridge
        self.db = db_estado

    def _on_start(self) -> None:
        self.step_name = "Conectando con TIA"

    async def tick(self) -> None:
        if self.nStep in (0, self.n_done, self.n_error):
            return
        try:
            if self.nStep == 10:
                self.db.tia_state = "connecting"
                self.step_name = "Conectando con TIA"
                await self.bridge.attach()
                self.progress = 50
                self.nStep = 20

            elif self.nStep == 20:
                self.step_name = "Listando PLCs"
                plcs = await self.bridge.list_plcs()
                self.db.plcs = plcs
                self.db.project_name = self.bridge.project_name
                self.db.project_path = self.bridge.project_path
                self.db.tia_state = "connected"
                self.progress = 100
                self.step_name = "Conectado"
                self.nStep = 30  # done

        except Exception as e:
            self.nError = 1
            self.error_msg = str(e)
            self.nStep = 99
            self.db.tia_state = "error"
            self.db.last_error = str(e)

    def disconnect(self) -> None:
        """Llamado por el HMI (botón Desconectar)."""
        if self.nStep == 30:
            self.bridge.detach()
            self.nStep = 0
            self.db.tia_state = "idle"
            self.db.plcs = []


# ─── ENGINE — el OB1 ──────────────────────────────────────────────

class Engine:
    """El OB1. Cada 100ms tickea los FBs activos y publica su estado al bus SSE.
    Cuando un FB llega a su nStep terminal (done o error), publica el resultado
    y se queda en ese estado hasta el próximo start()."""

    TICK_INTERVAL = 0.1   # 100ms

    def __init__(self):
        self.fbs: dict[str, FB_Base] = {}
        self.dbs: dict[str, object] = {}
        self.db_estado = DB_EstadoConexion()    # trasversal, siempre presente
        self.dbs["estado_conexion"] = self.db_estado
        self._subs: set[asyncio.Queue] = set()
        self._task: Optional[asyncio.Task] = None
        self.worker_bridge = None                # inyectado en attach_worker

    # ── Registro de FBs y DBs (llamado por las áreas en register_plc) ──

    def register_fb(self, name: str, fb: FB_Base) -> None:
        self.fbs[name] = fb

    def register_db(self, name: str, db: object) -> None:
        self.dbs[name] = db

    # ── Worker bridge (llamado por app.py en el lifespan) ──

    def attach_worker(self, worker_bridge) -> None:
        self.worker_bridge = worker_bridge
        # El FB_ConexionTIA recibe el bridge (si está registrado, lo buscamos)
        for fb in self.fbs.values():
            if isinstance(fb, FB_ConexionTIA):
                fb.bridge = worker_bridge

    # ── Loop principal (OB1) ──

    def start_loop(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.TICK_INTERVAL)
            for fb in list(self.fbs.values()):
                if fb.nStep in (0, fb.n_done, fb.n_error):
                    continue
                prev_step = fb.nStep
                try:
                    await fb.tick()
                except Exception as e:
                    fb.nError = 1
                    fb.error_msg = f"tick() lanzó excepción: {e}"
                    fb.nStep = fb.n_error
                if fb.nStep != prev_step or fb.progress != getattr(fb, "_last_published_progress", -1):
                    self._publish_fb_state(fb)
                    fb._last_published_progress = fb.progress

    # ── Bus SSE ──

    def _publish_fb_state(self, fb: FB_Base) -> None:
        event = fb.get_state()
        if fb.nStep == fb.n_done:
            event["type"] = "done"
            event["result"] = fb.result
        elif fb.nStep == fb.n_error:
            event["type"] = "error"
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # cliente lento, descartamos

    def _publish_db(self, db_name: str, data: dict) -> None:
        event = {"type": "db", "name": db_name, "data": data}
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def get_snapshot(self) -> dict:
        """Snapshot completo: todos los DBs y FBs. El HMI lo recibe al conectar."""
        return {
            "type": "snapshot",
            "dbs": {
                name: dataclass_to_dict(db)
                for name, db in self.dbs.items()
            },
            "fbs": {
                fb.nombre: fb.get_state()
                for fb in self.fbs.values()
            },
        }


def dataclass_to_dict(obj) -> dict:
    """Convierte un dataclass a dict, recursivamente."""
    if hasattr(obj, "__dataclass_fields__"):
        return {k: dataclass_to_dict(v) for k, v in obj.__dict__.items()}
    if isinstance(obj, list):
        return [dataclass_to_dict(v) for v in obj]
    if isinstance(obj, dict):
        return {k: dataclass_to_dict(v) for k, v in obj.items()}
    return obj


# Singleton global
ENGINE = Engine()
```

### A.2 `core/plc/worker_bridge.py`

```python
# core/plc/worker_bridge.py
#
# Fachada que los FBs llaman. Encapsula worker_tia. Si en el futuro cambia
# la API del worker, solo cambia este archivo.

from typing import Any


class WorkerBridge:
    """Adaptador entre FBs y worker_tia. Métodos async, retornan dicts simples.

    Los FBs NO importan worker_tia directamente. Solo importan esta clase.
    Esto permite mockear el bridge en tests."""

    def __init__(self, worker_tia):
        self._worker = worker_tia
        self.project_name = ""
        self.project_path = ""

    # ── Conexión ──

    async def attach(self) -> None:
        """Attach a TIA Portal. Es persistente: el worker queda vivo."""
        # Llamar al método del worker (msgpack stdin/stdout)
        # (Implementación específica según worker_tia.py actual)
        await self._worker.attach()

    async def detach(self) -> None:
        await self._worker.detach()

    async def list_plcs(self) -> list[dict]:
        """Retorna [{name, short_designation}, ...]"""
        return await self._worker.list_plcs()

    # ── Dispositivos ──

    async def commit_devices_sync(self, plc_name: str, prevision: dict) -> dict:
        """Commit atómico. Retorna {ok, operations_executed, post_sync_preview, ...}"""
        return await self._worker.commit_devices_sync(plc_name, prevision)

    async def generate_sync_preview(self, plc_name: str) -> dict:
        return await self._worker.generate_sync_preview(plc_name)

    # ── Excel ──

    async def parse_excel(self, file_bytes: bytes) -> dict:
        return await self._worker.parse_excel(file_bytes)

    # ── Bloques PLC ──

    async def scan_plc_blocks(self, plc_name: str) -> dict:
        return await self._worker.scan_plc_blocks(plc_name)

    # ── Comentarios ──

    async def sync_procesos_comments(self, proc_uid: int, plc_name: str, prevision: dict) -> dict:
        return await self._worker.sync_procesos_comments(proc_uid, plc_name, prevision)
```

### A.3 `core/interfaces/web_server/routers/plc.py`

```python
# core/interfaces/web_server/routers/plc.py
#
# Router GENÉRICO: no conoce los FBs específicos. Los busca en ENGINE.fbs por nombre.
# Cualquier área puede registrar FBs y el router los maneja sin cambios.

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
import asyncio
import json

from core.plc.plc import ENGINE

router = APIRouter(prefix="/plc")


@router.post("/fb/{name}/start")
async def start_fb(name: str, request: Request):
    """Arranca un FB por nombre. El body es un dict con los params que el FB espera."""
    if name not in ENGINE.fbs:
        raise HTTPException(404, f"FB '{name}' no registrado")
    fb = ENGINE.fbs[name]
    # Parsear body si viene JSON; si no, params vacíos.
    if request.headers.get("content-type", "").startswith("application/json"):
        body = await request.json()
    else:
        body = {}
    try:
        fb.start(**body)
    except TypeError as e:
        raise HTTPException(400, f"FB '{name}' no acepta esos params: {e}")
    return {"started": name, "nStep": fb.nStep}


@router.post("/fb/ConexionTIA/disconnect")
async def disconnect_tia():
    """Disconnect explícito del worker TIA (botón Desconectar del HMI)."""
    if "ConexionTIA" not in ENGINE.fbs:
        raise HTTPException(404, "FB ConexionTIA no registrado")
    fb = ENGINE.fbs["ConexionTIA"]
    if hasattr(fb, "disconnect"):
        fb.disconnect()
    return {"disconnected": True, "nStep": fb.nStep}


@router.get("/events")
async def plc_events():
    """SSE: snapshot inicial + stream de eventos de TODOS los DBs y FBs."""
    async def gen():
        q = ENGINE.subscribe()
        try:
            # Snapshot inicial para que el HMI tenga el estado actual
            yield f"data: {json.dumps(ENGINE.get_snapshot())}\n\n"
            while True:
                event = await q.get()
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            ENGINE.unsubscribe(q)
    return StreamingResponse(gen(), media_type="text/event-stream")
```

### A.4 `areas/alimentacion/plc/functions.py` (resumen)

```python
# areas/alimentacion/plc/functions.py
# 4 FBs específicos de alimentación. Cada uno con su nStep discreto.

from core.plc.plc import FB_Base
from .data import DB_Excel_Alim, DB_CachePLC_Alim
from core.plc.plc import DB_EstadoConexion


class FB_SincronizarDispositivos(FB_Base):
    """FB Sincronizar Dispositivos.
        10 validar → 20 commit atómico → 30 refrescar → 40 done
    """
    n_done = 40

    def __init__(self, bridge, db_excel: DB_Excel_Alim, db_cache_plc: DB_CachePLC_Alim, db_estado: DB_EstadoConexion):
        super().__init__("SincronizarDispositivos")
        self.bridge = bridge
        self.db_excel = db_excel
        self.db_cache = db_cache_plc
        self.db_estado = db_estado

    def _on_start(self, plc_name: str, prevision: dict) -> None:
        self._plc_name = plc_name
        self._prevision = prevision
        self.step_name = "Validando prevision"

    async def tick(self) -> None:
        if self.nStep in (0, self.n_done, self.n_error):
            return
        try:
            if self.nStep == 10:
                if not self._prevision.get("todos"):
                    raise ValueError("Prevision vacia")
                self.progress = 10
                self.step_name = "Validando prevision"
                self.nStep = 20

            elif self.nStep == 20:
                self.step_name = "Commiteando contra TIA"
                result = await self.bridge.commit_devices_sync(self._plc_name, self._prevision)
                if not result.get("ok"):
                    raise RuntimeError(result.get("error", "commit devolvio !ok"))
                self.result = result
                self.progress = 80
                self.nStep = 30

            elif self.nStep == 30:
                self.step_name = "Refrescando prevision"
                new_prevision = await self.bridge.generate_sync_preview(self._plc_name)
                if self.result:
                    self.result["post_sync_preview"] = new_prevision
                self.progress = 100
                self.step_name = "Hecho"
                self.nStep = 40

        except Exception as e:
            self.nError = 1
            self.error_msg = str(e)
            self.nStep = 99
            # Invalidar cache PLC si TIA se cayó
            if "TIA" in str(e) or "not responding" in str(e).lower():
                self.db_cache.plc_name = ""
                self.db_cache.bloques = []


class FB_LeerExcel(FB_Base):
    """FB Leer Excel.
        10 parsear → 20 volcar al DB → 30 invalidar cache PLC → 40 done
    """
    n_done = 40

    def __init__(self, bridge, db_excel: DB_Excel_Alim, db_cache_plc: DB_CachePLC_Alim):
        super().__init__("LeerExcel")
        self.bridge = bridge
        self.db_excel = db_excel
        self.db_cache = db_cache_plc

    def _on_start(self, file_bytes: bytes, filename: str) -> None:
        self._bytes = file_bytes
        self._filename = filename
        self.step_name = "Parseando Excel"

    async def tick(self) -> None:
        if self.nStep in (0, self.n_done, self.n_error):
            return
        try:
            if self.nStep == 10:
                self.step_name = "Parseando Excel"
                self._parsed = await self.bridge.parse_excel(self._bytes)
                self.progress = 60
                self.nStep = 20

            elif self.nStep == 20:
                self.step_name = "Volcando al AppState"
                self.db_excel.loaded = True
                self.db_excel.filename = self._filename
                self.db_excel.data = self._parsed
                self.progress = 90
                self.nStep = 30

            elif self.nStep == 30:
                self.step_name = "Invalidando cache PLC"
                if self.db_cache.plc_name:
                    self.db_cache.bloques = []
                    self.db_cache.tag_tables = []
                    self.db_cache.udts = []
                self.progress = 100
                self.step_name = "Hecho"
                self.nStep = 40

        except Exception as e:
            self.nError = 1
            self.error_msg = str(e)
            self.nStep = 99


class FB_CachearBloquesPLC(FB_Base):
    """FB Cachear Bloques PLC.
        10 escanear → 20 cachear → 30 done
    """
    n_done = 30

    def __init__(self, bridge, db_cache_plc: DB_CachePLC_Alim, db_estado: DB_EstadoConexion):
        super().__init__("CachearBloquesPLC")
        self.bridge = bridge
        self.db_cache = db_cache_plc
        self.db_estado = db_estado

    def _on_start(self, plc_name: str) -> None:
        self._plc_name = plc_name
        self.step_name = "Escaneando bloques del PLC"

    async def tick(self) -> None:
        if self.nStep in (0, self.n_done, self.n_error):
            return
        try:
            if self.nStep == 10:
                self.step_name = "Escaneando bloques"
                snap = await self.bridge.scan_plc_blocks(self._plc_name)
                self.result = snap
                self.progress = 70
                self.nStep = 20

            elif self.nStep == 20:
                self.step_name = "Volcando al cache local"
                self.db_cache.plc_name = self._plc_name
                self.db_cache.bloques = self.result.get("blocks", []) if self.result else []
                self.db_cache.tag_tables = self.result.get("tag_tables", []) if self.result else []
                self.db_cache.udts = self.result.get("udts", []) if self.result else []
                self.progress = 100
                self.step_name = "Hecho"
                self.nStep = 30

        except Exception as e:
            self.nError = 1
            self.error_msg = str(e)
            self.nStep = 99


class FB_SincronizarComentarios(FB_Base):
    """FB Sincronizar Comentarios de Procesos.
        10 preview → 20 aplicar atómico → 30 done
    """
    n_done = 30

    def __init__(self, bridge, db_cache_plc: DB_CachePLC_Alim, db_excel: DB_Excel_Alim):
        super().__init__("SincronizarComentarios")
        self.bridge = bridge
        self.db_cache = db_cache_plc
        self.db_excel = db_excel

    def _on_start(self, proc_uid: int, plc_name: str, prevision: dict) -> None:
        self._proc_uid = proc_uid
        self._plc_name = plc_name
        self._prevision = prevision
        self.step_name = "Generando preview de comentarios"

    async def tick(self) -> None:
        if self.nStep in (0, self.n_done, self.n_error):
            return
        try:
            if self.nStep == 10:
                self.step_name = "Generando preview"
                # El bridge ya hace preview+apply en una llamada; si en el
                # futuro se separan, añadir nStep 15 aquí.
                result = await self.bridge.sync_procesos_comments(
                    self._proc_uid, self._plc_name, self._prevision
                )
                if not result.get("ok"):
                    raise RuntimeError(result.get("error", "sync devolvio !ok"))
                self.result = result
                self.progress = 100
                self.step_name = "Hecho"
                self.nStep = 30

        except Exception as e:
            self.nError = 1
            self.error_msg = str(e)
            self.nStep = 99
```

### A.5 `areas/alimentacion/plc/data.py`

```python
# areas/alimentacion/plc/data.py
# DBs específicos del área de alimentación.

from dataclasses import dataclass, field
import time


@dataclass
class DB_Excel_Alim:
    """DB del Excel de alimentación. Formato específico del área."""
    loaded: bool = False
    filename: str = ""
    loaded_at: float = 0.0
    data: dict = field(default_factory=dict)


@dataclass
class DB_CachePLC_Alim:
    """DB del cache de bloques del PLC de alimentación.
    Se invalida cuando el operario sube un Excel o se desconecta TIA."""
    plc_name: str = ""
    bloques: list = field(default_factory=list)
    tag_tables: list = field(default_factory=list)
    udts: list = field(default_factory=list)
    scanned_at: float = 0.0
```

### A.6 `areas/alimentacion/plc/__init__.py`

```python
# areas/alimentacion/plc/__init__.py
# register_plc: enchufa los FBs y DBs específicos de alimentación en el Engine.

def register_plc(engine, worker_bridge) -> None:
    from .data import DB_Excel_Alim, DB_CachePLC_Alim
    from .functions import (
        FB_SincronizarDispositivos,
        FB_LeerExcel,
        FB_CachearBloquesPLC,
        FB_SincronizarComentarios,
    )

    db_excel = DB_Excel_Alim()
    db_cache = DB_CachePLC_Alim()
    engine.register_db("excel_alim", db_excel)
    engine.register_db("cache_plc_alim", db_cache)

    engine.register_fb("SincronizarDispositivos", FB_SincronizarDispositivos(
        bridge=worker_bridge,
        db_excel=db_excel,
        db_cache_plc=db_cache,
        db_estado=engine.db_estado,
    ))
    engine.register_fb("LeerExcel", FB_LeerExcel(
        bridge=worker_bridge,
        db_excel=db_excel,
        db_cache_plc=db_cache,
    ))
    engine.register_fb("CachearBloquesPLC", FB_CachearBloquesPLC(
        bridge=worker_bridge,
        db_cache_plc=db_cache,
        db_estado=engine.db_estado,
    ))
    engine.register_fb("SincronizarComentarios", FB_SincronizarComentarios(
        bridge=worker_bridge,
        db_cache_plc=db_cache,
        db_excel=db_excel,
    ))
```

---

## Apéndice B — Código del HMI

### B.1 `interfaces/web_server/static/js/composables/usePlc.js`

```js
// interfaces/web_server/static/js/composables/usePlc.js
//
// El HMI: arranca FBs, escucha SSE, expone DBs y FBs como reactivos.
// La web NO pregunta NUNCA. Solo escucha.

import { reactive, ref, onMounted, onUnmounted } from "/js/vendor/vue.esm-browser.prod.js";

const DBs = reactive({
    estado_conexion: {                    // trasversal, del core
        worker_alive: false,
        tia_state: "idle",
        project_name: "",
        project_path: "",
        plcs: [],
        last_error: "",
        last_ping_ok_unix: 0,
    },
    // Las áreas registran sus DBs aquí dinámicamente al hacer register_plc.
    excel_alim: null,
    cache_plc_alim: null,
});

const FBs = reactive({
    // El core registra ConexionTIA; las áreas registran los suyos.
    ConexionTIA: { nStep: 0, nError: 0, error: "", progress: 0, step_name: "" },
    SincronizarDispositivos: { nStep: 0, nError: 0, error: "", progress: 0, step_name: "" },
    LeerExcel: { nStep: 0, nError: 0, error: "", progress: 0, step_name: "" },
    CachearBloquesPLC: { nStep: 0, nError: 0, error: "", progress: 0, step_name: "" },
    SincronizarComentarios: { nStep: 0, nError: 0, error: "", progress: 0, step_name: "" },
});

const lastResult = ref(null);
let eventSource = null;

function connect() {
    if (eventSource) return;
    eventSource = new EventSource("/api/v1/plc/events");
    eventSource.onmessage = (ev) => {
        const e = JSON.parse(ev.data);
        if (e.type === "snapshot") {
            // Reemplazar (no Object.assign, porque la estructura puede cambiar)
            Object.assign(DBs, e.dbs);
            Object.assign(FBs, e.fbs);
        } else if (e.type === "fb") {
            if (FBs[e.name]) {
                Object.assign(FBs[e.name], e);
            }
        } else if (e.type === "done") {
            if (e.result !== undefined) {
                lastResult.value = e.result;
            }
        } else if (e.type === "error") {
            // El componente decide cómo pintar el error
            console.error(`[PLC] FB '${e.name}' error: ${e.error}`);
        }
    };
    eventSource.onerror = () => {
        // EventSource reconecta automáticamente. Logueamos para debug.
        console.warn("[PLC] SSE connection lost, will retry...");
    };
}

function disconnect() {
    if (eventSource) { eventSource.close(); eventSource = null; }
}

async function startFb(name, body) {
    const r = await fetch(`/api/v1/plc/fb/${encodeURIComponent(name)}/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
    });
    if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${r.status}`);
    }
    return r.json();
}

export function usePlc() {
    onMounted(connect);
    onUnmounted(disconnect);
    return {
        DBs,
        FBs,
        lastResult,
        startFb,
        isIdle:    (name) => FBs[name]?.nStep === 0,
        isRunning: (name) => FBs[name]?.nStep > 0 && FBs[name]?.nStep < 99 && FBs[name]?.nStep !== 40 && FBs[name]?.nStep !== 30,
        isDone:    (name) => FBs[name]?.nStep === 40 || FBs[name]?.nStep === 30,
        isError:   (name) => FBs[name]?.nStep === 99,
    };
}
```

### B.2 `areas/alimentacion/frontend/components/Dispositivos.js` (migrado)

```js
// Antes: 5 if/else anidados en ejecutarCommit.
// Ahora: 1 composable, 1 switch sobre el state del FB.
import { usePlc } from "/js/composables/usePlc.js";

export default {
    setup() {
        const plc = usePlc();

        async function ejecutarCommit() {
            if (!store.previewData) return;     // store mínimo solo para el cache de prevision
            const total = ...;                 // cálculo del summary
            if (!confirm(`¿Aplicar ${total} cambios?`)) return;
            try {
                await plc.startFb("SincronizarDispositivos", {
                    plc_name: store.selectedPlc,
                    prevision: store.previewData,
                });
                // El SSE ya actualizó plc.FBs.SincronizarDispositivos.nStep.
                if (plc.isDone("SincronizarDispositivos")) {
                    const result = plc.lastResult.value;
                    if (result?.post_sync_preview) {
                        store.previewData = result.post_sync_preview;
                    }
                    pushLog(`✅ ${result?.operations_executed || 0} ops aplicadas`, "success");
                } else if (plc.isError("SincronizarDispositivos")) {
                    const err = plc.FBs.SincronizarDispositivos.error;
                    if (err?.includes("TIA")) {
                        pushLog("TIA Portal no responde", "error");
                        // limpiar cache PLC via otro FB o reset directo
                    } else {
                        pushLog(err, "error");
                    }
                }
            } catch (e) {
                pushLog(String(e.message || e), "error");
            }
        }

        return { plc, ejecutarCommit /* ... resto ... */ };
    },
    template: /* html */ `
        <button @click="ejecutarCommit"
            :disabled="plc.isRunning('SincronizarDispositivos')"
            data-testid="dispositivos-aplicar">
            <span v-if="plc.isIdle('SincronizarDispositivos')">✅ Aplicar Cambios</span>
            <span v-else-if="plc.isRunning('SincronizarDispositivos')">
                {{ plc.FBs.SincronizarDispositivos.step_name }} —
                {{ plc.FBs.SincronizarDispositivos.progress }}%
            </span>
            <span v-else-if="plc.isDone('SincronizarDispositivos')">✅ Aplicado</span>
            <span v-else>❌ Error</span>
        </button>
    `,
};
```

---

## Apéndice C — Checklist de validación

### Pre-PR 1
- [ ] `grep -r "core.plc" core/` → 0 resultados (PLC no existe aún).
- [ ] El worker_tia actual arranca con `python main_tray.py`.

### Post-PR 1
- [ ] `pytest tests/core/ -v` → ≥10 tests verdes.
- [ ] `curl -N http://127.0.0.1:8000/api/v1/plc/events` → SSE abierto.
- [ ] `curl -X POST http://127.0.0.1:8000/api/v1/plc/fb/ConexionTIA/start` → 200 + `nStep: 10`.
- [ ] El SSE emite eventos con `nStep: 10 → 20 → 30`.
- [ ] El worker_tia sigue arrancando y respondiendo a ping.
- [ ] `python main_tray.py` arranca sin traceback.

### Post-PR 2
- [ ] `pytest tests/areas/alimentacion/ -v` → ≥5 tests verdes.
- [ ] El snapshot SSE lista los 5 FBs (ConexionTIA + 4 de alimentación).
- [ ] `curl -X POST .../plc/fb/SincronizarDispositivos/start -d '{"plc_name":"PLC_1","prevision":{...}}'` → 200.
- [ ] Validar con S7-1500 real: arrancar FB_SincronizarDispositivos, ver que el commit se ejecuta.

### Post-PR 3
- [ ] `pytest tests/frontend/ -v` → todos verdes.
- [ ] `grep -r "from .*store.js" interfaces/ areas/` → 0 resultados.
- [ ] DevTools Network: 0 polls a `/api/v1/logs`, `/api/v1/progress/current`. Solo 1 EventSource a `/api/v1/plc/events`.
- [ ] Validar con S7-1500 real end-to-end:
  - [ ] Conectar → verde en el topbar.
  - [ ] Listar PLCs → grid aparece.
  - [ ] Generar prevision → "Generando... XX%".
  - [ ] Aplicar → "Commiteando... XX%" → "Refrescando... XX%" → "✅ Aplicado".
  - [ ] Subir Excel → "Parseando... XX%".
  - [ ] Sync comentarios → "Generando preview... XX%".
  - [ ] Desconectar → gris en el topbar, grid vacía.

### Post-PR 4 (opcional)
- [ ] `grep -r "core.application.use_cases" core/ areas/ tests/` → 0 resultados.
- [ ] `grep -r "core.infrastructure.gateway" core/ areas/ tests/` → 0 resultados.
- [ ] `pytest tests/ -v` → todos verdes.

---

*Plan generado el 2026-09-09. Pendiente de aprobación. NO se ha modificado código todavía.*
