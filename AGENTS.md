# AGENTS.md — Guía de extensión para zc-plc-suite

> Documento vivo para agentes AI (mavis, otros) y humanos que extiendan el proyecto. Si una convención cambia, edita aquí y avisa al equipo.
>
> Reglas arquitectónicas críticas en [`.clinerules`](./.clinerules) (corto, se carga siempre). Convenciones operativas y "cómo extender" están aquí (medio, se consulta).

## TL;DR del modelo PLC-style

El backend FastAPI implementa el patrón IEC 61131-3:

- **FB (Function Block):** clase Python con `nStep` discreto (`0 = idle`, `n_done = done`, `n_error = 99 = error`). Tiene `start(**params)` y `tick()`. El Engine tickea los FBs activos cada 100ms.
- **DB (Data Block):** dataclass compartida. `DB_EstadoConexion` es trasversal (vive en `core/plc/plc.py`); las áreas tienen sus propias DBs en `areas/<area>/plc/data.py`.
- **Engine (OB1):** singleton en `core/plc/plc.py`. Loop 100ms, bus SSE por `asyncio.Queue` por suscriptor, registro de FBs/DBs.
- **WorkerBridge:** fachada lock-protegida entre FBs y `worker_tia.py`. Lock desde el primer commit, shutdown handler incluido.
- **HMI:** `usePlc()` composable en el frontend. 1 EventSource, DBs/FBs reactivos, `startFb(name, params)`. **Sin polling.**

## Arquitectura: cómo añadir una nueva feature

> El layout sigue **Bounded Contexts**. `core/` contiene TODO lo transversal sin saber de áreas; cada `areas/<area>/` es un paquete autocontenido. Antes de añadir una feature dentro de un área, lee **"Cómo añadir una nueva área"** más abajo.

### 1. Nuevo Function Block (FB)

1. Decide si el FB es **genérico** (lo usan todas las áreas) o **específico**:
   - **Genérico:** edita `core/plc/plc.py`, añade la clase heredando de `FB_Base`. Define `n_done` (la etapa terminal OK). Implementa `start(**params)` y `tick()`.
   - **Específico:** edita `areas/<area>/plc/functions.py`, misma forma.
2. **Convenciones:**
   - `nStep == 10` = primera etapa. Incrementa de 10 en 10 (10, 20, 30, …) para que se vea claro en logs.
   - Captura excepciones en `tick()`, pon `nError=1`, `error_msg=str(e)`, `nStep=99`. El Engine lo publica al SSE.
   - `start(**params)` debe ser idempotente: si el FB ya está corriendo (`nStep not in {0, n_done, 99}`), ignora.
3. **Regístralo en el `Engine`** vía `engine.register_fb(name, instance)`. Esto se hace en `areas/<area>/plc/__init__.py::register_plc(engine, worker_bridge)`.
4. **Tests:** unit tests con `WorkerBridge` mockeado. Verifica que `tick()` avanza `nStep` correctamente y maneja errores.

### 2. Nuevo Data Block (DB)

1. **Trasversal:** edita `core/plc/plc.py`, añade un `@dataclass` junto a `DB_EstadoConexion`. Regístralo con `engine.register_db(name, instance)` en el mismo archivo.
2. **Específico de área:** edita `areas/<area>/plc/data.py`. Regístralo en `register_plc()`.

### 3. Nuevo endpoint REST

1. **Genérico (operaciones que todas las áreas necesitan):** edita `core/web/routers/plc.py`. Ejemplos: arrancar un FB por nombre (`POST /plc/fb/{name}/start`), listar PLCs, etc.
2. **Específico de área (no FBs):** edita `areas/<area>/routers.py`, expone `router = APIRouter()` con los endpoints del área, y declara `register_routers(app)` en el `__init__.py` del área. El shell FastAPI (`core/web/app.py`) lo monta con `app.include_router(area_router, prefix="/api/v1/areas/<area>")`.
3. **Reglas ineludibles:**
   - Inyecta dependencias vía `Depends(get_engine)` / `Depends(get_worker_bridge)`. NUNCA importes globales directamente.
   - Devuelve siempre un `dict` (FastAPI lo serializa a JSON).
   - Si la operación es >500 ms, dispara un FB en vez de hacer la lógica en el endpoint. El FB tiene su propio progreso vía SSE.
4. **Tests:** usa `TestClient` con `WorkerBridge` mockeado. Mismo patrón que `tests/test_routers_plc.py`.

### 4. Nuevo componente Vue en la SPA

1. **Cross-cutting** (visible en TODAS las áreas): edita `interfaces/web_server/static/js/components/`. Ejemplos: `Welcome`, `ShellTopbar`, `ShellSidebar`, `ConsolaLogs`, `TiaConnectionIndicator`, `WorkerStatusIndicator`, `FlowProgress` (indicador de FB activo), `EmptyState`.
2. **Específico de área:** edita `areas/<area>/frontend/components/`. Registra en `areas/<area>/frontend/manifest.js` (`build()` que devuelve `{ components, sidebar, landing, loaders }`). El shell SPA (`main.js`) lo carga dinámicamente vía `area-loader.js`.
3. **Regla Vue 3 sin build step (CRÍTICA):** el compilador de templates en runtime NO tiene acceso a `import` a nivel de módulo. **TODO** acceso a `store` (o `usePlc()`) desde el template se hace vía `computed` retornado del `setup()`. El template solo lee variables planas.
4. **Estado reactivo en `usePlc().DBs` o `usePlc().FBs`** (NO en un `store.js` local — el store global legacy se eliminó).
5. **Fetch via `usePlc().startFb(name, params)`** — NUNCA `fetch` directo en un componente.
6. **Estilos:** solo tokens semánticos del tema (`bg-surface*`, `text-ink*`, `border-line*`, `bg-accent`). Tras añadir clases, **recompila Tailwind** (ver `.clinerules` §10).

### 5. Cómo añadir una nueva área

1. **Crear `areas/<area_id>/` con `__init__.py`** que defina:
   ```python
   from core.application.area_registry import AreaSpec

   AREA_SPEC = AreaSpec(
       id="<area_id>",
       label="<label humano>",
       icon="<emoji o vacío>",
   )

   def register(engine, app):
       """Llamado por core/web/app.py::create_app() al arrancar."""
       from .plc import register_plc
       register_plc(engine)
       from .routers import router as area_router
       app.include_router(area_router, prefix="/api/v1/areas/<area_id>")
   ```
2. **FBs y DBs del área** en `areas/<area>/plc/`:
   - `data.py` — dataclasses de las DBs específicas.
   - `functions.py` — los FBs, heredando de `FB_Base`.
   - `__init__.py` — `register_plc(engine, worker_bridge)` que crea instancias y llama a `engine.register_fb(name, instance)` para cada FB.
3. **Dominio** en `areas/<area>/domain/` — dataclasses de las entidades del área (si las hay).
4. **Routers del área** en `areas/<area>/routers.py` — para endpoints que NO son FBs.
5. **Frontend** en `areas/<area>/frontend/` — `manifest.js` (`build()`) + `components/`. Los componentes se clonan del legacy (ver Fase 3 del plan).
6. **Tests** en `tests/areas/<area>/` — unit tests con `WorkerBridge` mockeado.
7. **Añadir `register` al lifespan de `core/web/app.py`**:
   ```python
   from areas.<area_id> import register as register_<area_id>
   register_<area_id>(ENGINE, app)
   ```

**Convenciones:**
- Las áreas **NO importan** `siemens_tia_scripting` directamente. Solo aportan FBs que invocan `WorkerBridge`.
- El shell SPA NO importa componentes de áreas directamente. Todo via `area-loader.js` + manifest.
- Las áreas **NO añaden código a `core/`** salvo vía la API pública del Engine (registrar FBs/DBs).

## Convenciones operativas

### HMI pasivo (sin polling)

- **El frontend NO tiene `setInterval`.** Toda la comunicación es push vía SSE.
- `usePlc()` abre 1 `EventSource` al montar el componente raíz, lo cierra al desmontar.
- El SSE entrega snapshot inicial + eventos del Engine (cambios de `nStep`, `progress`, `error`, `done`).

### Timeouts de fetch (cliente)

- **Sin timeouts largos en cliente.** El SSE no necesita timeout (es push). El único fetch con timeout es `startFb()`, que es un POST corto.
- Si un fetch falla, `usePlc().startFb()` rechaza con un error que el componente pinta.

### ProgressTracker → Engine.publish

- El `Engine` publica cambios al bus SSE en cada `tick()` cuando un FB cambia de `nStep` o `progress`.
- El `ProgressIndicator` legacy se reemplaza por `FlowProgress.js`, que lee `plc.FBs[fbName]` reactivamente.

### Engine: ciclo de vida

- `Engine.start_loop()` arranca la task asyncio que tickea cada 100ms.
- `Engine.attach_worker(worker_bridge)` vincula el `WorkerBridge` para que los FBs lo usen.
- `Engine.subscribe()` / `Engine.unsubscribe(queue)` para el bus SSE.
- En el `lifespan` de FastAPI: arrancar el Engine al `startup`, pararlo al `shutdown` (envía un evento final y cierra el loop).

## Compatibilidad con el legacy

- **El legacy vive en `main` (rama operativa) y en `legacy_backup/` (esta rama).**
- El legacy NO se borra hasta Fase 5 (validación final y release).
- Los `_plan/` del legacy (en `legacy_backup/_plan/`) son referencia intelectual viva: `_plan/14_post_worker_persistent_audit.md` (las 3 lecciones X1/X2/X3), `_plan/17_frontend_simplification_audit.md` (la auditoría que justificó SSE).

## Cómo validar antes de mergear

Cada fase cierra con:

1. **Validación técnica:** los 6 tests obligatorios del `.clinerules` §12 (en Fase 1), o los tests específicos de la fase.
2. **Validación con hardware real:** S7-1500 físico. El operario verifica que el flujo funciona end-to-end.
3. **Demo de 30 min al operario** con confirmación explícita ("OK, esto es lo que quiero"). Si dice "no es esto", iterar antes de seguir.

Ver `PLC_IE_61131_GREENFIELD.md` para el plan completo por fase.
