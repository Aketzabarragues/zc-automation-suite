# Refactor: convertir el worker actual en SSE

## Objetivo

El legacy actual (`main`, HEAD `9133c65`) ya tiene worker persistente en el backend (`core/infrastructure/gateway.py::TIAProcessGateway` con `_start_persistent_worker`, `_heartbeat_loop`, `_read_worker_stdout_forever`). Lo que **NO** tiene es **Server-Sent Events (SSE)** para que el frontend deje de pollear.

El frontend legacy hace **3 `setInterval`** en `interfaces/web_server/static/js/main.js`:
- línea 233: `setInterval(..., 1000)` → `apiFetchLogs()`.
- línea 241: `setInterval(..., 500)` → `apiFetchProgress()`.
- línea 266: `setInterval(..., 2000)` → `store.refreshTiaConnection()`.

**Objetivo de este refactor**: añadir un endpoint SSE al backend que emita el estado del gateway, y sustituir los 3 `setInterval` del frontend por **1 solo `EventSource`**.

## Reglas duras del operario

- **TODO el legacy: ni una línea cambia sin pedir.** Este refactor es **aditivo**: añade piezas nuevas sin modificar el código existente. El switch final (quitar el polling) se hace DESPUÉS de validar que el SSE funciona.
- **Cada pieza se valida con el operario antes de la siguiente.**
- **Frontend: clonar, no rediseñar.** No se cambian iconos, copy, colores, layout. Solo se sustituye el polling por EventSource.
- **No se añaden áreas nuevas.** El legacy tiene `alimentacion`; sigue teniendo `alimentacion`.
- **No se introduce Vue 3 sin build step.** El frontend sigue siendo Vue 3 (legacy). El `EventSource` se enchufa al `store.js` o al `main.js`, no se reescribe nada.

## Contexto técnico (lo que el agente debe leer primero)

1. `PLC_IE_61131_GREENFIELD.md` (en la rama preservada `greenfield/iec-61131-3`, SHA `58b064e`) — referencia intelectual. **NO es la guía de este refactor.** Pero tiene el SSE-shape que queremos replicar en `main`.
2. `_plan/17_frontend_simplification_audit.md` — mapa del frontend legacy (necesario para entender qué se rompe).
3. `core/infrastructure/gateway.py` (110 KB) — el `TIAProcessGateway`. Leer la sección `_start_persistent_worker` (línea 564+), `_heartbeat_loop` (línea 688+), `_read_worker_stdout_forever` (línea 807+). El state machine del TIA está en `self._connection_state` (valores: `"disconnected" | "connecting" | "connected" | "error"`).
4. `core/application/progress_buffer.py` (15 KB) — `ProgressTracker` (buffer del backend que ya mantiene `current`, `total`, `percent`, `stages`, `error`).
5. `core/application/log_buffer.py` (2.8 KB) — `LogBuffer` (mensajes del operario).
6. `interfaces/web_server/static/js/store.js` (52 KB) — el `reactive({...})` singleton que el frontend usa. Tiene `tiaConnection`, `progress`, `logs`, etc. El `refreshTiaConnection` se llama desde el `setInterval` de 2s.
7. `interfaces/web_server/static/js/api.js` (15 KB) — las funciones `apiFetchLogs`, `apiFetchProgress`, `apiFetchTiaConnection`, etc.
8. `interfaces/web_server/static/js/main.js` (12 KB) — los 3 `setInterval` a sustituir.
9. `interfaces/web_server/routers/` — directorio de routers. Mirar el patrón (dependencias, estructura, etc.).

## Lecciones del greenfield (las que aplican a este refactor)

El greenfield dejó un plan con lecciones que aplican. **NO copies el código del greenfield al main** (eso es cherry-pick destructivo). Pero sí respeta estos patrones:

- **1 EventSource por sesión**, no N. Auto-reconnect nativo del navegador.
- **Snapshot inicial completo** al abrir la conexión, luego eventos incrementales.
- **Deep merge defensivo** en la aplicación de snapshots (lección X1): si un campo falta, conservar el previo, no pisar con `undefined`.
- **3 tipos de eventos** mínimo:
  - `{"type": "snapshot", "dbs": {...}, "fbs": {...}, "logs": [...], "progress": {...}}` — al abrir.
  - `{"type": "tia_state", "state": "...", "worker_alive": true/false, "last_error": "..."}` — al cambiar la conexión.
  - `{"type": "log", "level": "...", "message": "...", "timestamp": "..."}` — al añadir un log.
  - `{"type": "progress", "current": N, "total": M, "percent": P, "stages": [...], "error": "..."}` — al cambiar el progreso.
- **NO polling.** La regla es estricta: el frontend deja de hacer `setInterval` para el estado.
- **`asyncio.Queue` por suscriptor** en el backend. Si hay N suscriptores, hay N queues; cada una con `put` no-bloqueante y `get` con timeout.

## Plan de ataque (3 fases, aditivo)

### Fase 0 — Análisis (lectura, sin tocar nada)

El agente debe:

1. Leer los 9 archivos del "Contexto técnico" arriba.
2. Identificar **qué datos hay que exponer por SSE**:
   - Estado de la conexión TIA (`tia_state`, `worker_alive`, `last_error`, `project_name`, `project_path`, `plcs`).
   - `ProgressTracker` (current, total, percent, stages, error).
   - `LogBuffer` (mensajes nuevos).
3. Identificar **cómo el gateway actual notifica cambios**:
   - ¿Hay hooks cuando cambia `self._connection_state`? ¿Cuándo se añaden logs al `LogBuffer`? ¿Cuándo se actualiza el `ProgressTracker`?
   - Si NO hay hooks, hay que añadirlos en el `TIAProcessGateway` y en los `ProgressTracker`/`LogBuffer` (con permiso explícito del operario).
4. Proponer el **shape del endpoint SSE**: `GET /api/v1/stream` con `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `Connection: keep-alive`.
5. Proponer el **contrato del frontend**: `EventSource("/api/v1/stream")` con `onopen`, `onmessage`, `onerror`. El `onmessage` parsea el JSON y actualiza el `store` legacy (NO se reescribe el store, solo se actualiza desde el SSE en vez de desde el polling).
6. Hacer un `git diff --stat` del estado actual para confirmar que no se ha tocado nada.
7. **Reporte al operario**: lista de archivos a tocar en cada fase, shape del SSE, contrato del frontend, riesgos identificados.

**Cierre de Fase 0:** el operario aprueba el plan antes de pasar a Fase 1.

### Fase 1 — Backend: añadir el endpoint SSE (aditivo)

**Scope:**
- Añadir `core/web/routers/stream.py` con `GET /api/v1/stream` (SSE).
- Crear `core/web/event_bus.py` (helper) con `EventBus` que tenga `subscribe() -> asyncio.Queue` y `publish(event)`.
- Enganchar el `TIAProcessGateway`, el `ProgressTracker` y el `LogBuffer` al `EventBus` cuando el operario dé OK para añadir los hooks (esto puede ser aditivo si los hooks no requieren tocar el código existente; si sí, se discute).
- Registrar el router en `interfaces/web_server/app.py` (sin tocar otros routers).
- Tests del endpoint SSE (con `TestClient` o `httpx.AsyncClient` que consuma el SSE y verifique que recibe el snapshot inicial y al menos 1 evento).

**Lo que NO se hace:**
- No se modifica `gateway.py` en esta fase (a menos que los hooks requieran cambios). Si los hooks requieren cambios, se propone al operario y se discute antes de tocar.
- No se modifican los routers existentes.
- No se introduce autenticación (mantener la convención actual de no auth).

**Criterios de aceptación Fase 1:**
- `curl -N http://127.0.0.1:8000/api/v1/stream` devuelve el snapshot inicial en formato SSE.
- Si el operario cambia el `ProgressTracker` (vía algún endpoint existente o vía `attach`), el SSE emite un evento `progress`.
- Si el operario añade un log (vía `LogBuffer`), el SSE emite un evento `log`.
- Si el operario conecta/desconecta TIA, el SSE emite un evento `tia_state`.
- Los tests legacy siguen pasando (`pytest tests/ -q` no debe romperse).
- El polling legacy SIGUE funcionando (no se quita nada en esta fase).

**Reporte al operario:** listado de archivos creados/modificados, output literal de `curl -N`, output de los tests.

### Fase 2 — Frontend: añadir EventSource (aditivo)

**Scope:**
- Añadir un módulo `interfaces/web_server/static/js/sse.js` (pequeño, ~50 líneas) con la clase `SseClient` que abre 1 `EventSource("/api/v1/stream")` y expone `on('snapshot'|'tia_state'|'log'|'progress', callback)`.
- En `interfaces/web_server/static/js/main.js`, **AÑADIR** (no sustituir) un `import` del `SseClient` y un bloque que abra el SSE al arrancar la SPA.
- Los handlers del SSE actualizan `store.tiaConnection`, `store.progress`, `store.logs` (los mismos campos que ya actualiza el polling).
- **CRÍTICO:** el polling (`setInterval`) sigue funcionando. Si el SSE llega, el store se actualiza por el SSE; si no llega (backend sin SSE), el polling sigue alimentando el store. Esto es defensa contra fallos.

**Lo que NO se hace:**
- No se quita el `setInterval` (eso es la Fase 3).
- No se rediseña el `store.js` ni los componentes Vue.
- No se introduce un nuevo `composables/` o estructura (eso era del greenfield).

**Criterios de aceptación Fase 2:**
- Al abrir la SPA, F12 console muestra 1 `EventSource` abierto a `/api/v1/stream` y los 3 `setInterval` también.
- Si el operario hace un cambio en el backend (ej. añade un log), el frontend lo refleja vía SSE.
- Si el operario desconecta el SSE (apaga el backend), el frontend no se rompe — el polling sigue alimentando el store.
- El frontend se ve EXACTAMENTE igual que antes (no se ha tocado copy, iconos, layout).

**Reporte al operario:** screenshot o descripción del F12 console (1 EventSource + 3 setInterval), y de un cambio en backend reflejado en el frontend.

### Fase 3 — Switch: quitar el polling (con permiso)

**Scope:**
- En `main.js`, **QUITAR** los 3 `setInterval` y sus handlers.
- Confirmar que el `EventSource` es la única fuente de actualización.

**Lo que NO se hace:**
- No se rediseña nada más.
- No se quita el código de polling de `api.js` (puede quedar como fallback; se discute).

**Criterios de aceptación Fase 3:**
- `grep -r "setInterval" interfaces/web_server/static/js/` → solo 0 referencias (excepto en el `SseClient` si tiene algún setInterval interno, que NO debería).
- El frontend sigue funcionando como antes.
- Los tests legacy siguen pasando.

**Reporte al operario:** confirmacion de los criterios, output de los tests.

## Acceptance global (cierre del refactor)

1. **Cero `setInterval` en el frontend** (Fase 3).
2. **1 `EventSource` por sesión** (Fase 2-3).
3. **Snapshot inicial correcto** al abrir la conexión.
4. **Eventos incrementales** cuando cambia el estado.
5. **Tests legacy siguen pasando** en cada fase.
6. **El frontend se ve exactamente igual** (copy, iconos, colores, layout).
7. **Validado contra TIA Portal real** del operario (S7-1500) en al menos 1 fase.

## Comandos útiles para el agente

```powershell
# Ver el estado del repo
cd 'D:/Zeus Control/Proyectos/GitHub/zc-automation-suite'
git status
git log --oneline -5

# Probar el SSE manualmente
curl.exe -N http://127.0.0.1:8000/api/v1/stream

# Lanzar la app
python main.py --web 127.0.0.1:8000

# Tests
pytest tests/ -v
```

## Out of scope (lo que este refactor NO toca)

- **No se añade `tia_conexion` ni áreas nuevas.** El Welcome del legacy sigue mostrando solo `alimentacion`.
- **No se introduce el `usePlc()` composable** del greenfield. El frontend sigue con `store.js`.
- **No se rediseña el `ShellTopbar`, `ShellSidebar`, `Welcome`, `BloquesCacheView`, `ProcesosSyncView`, ni ningún otro componente Vue.**
- **No se cambia el copy, los iconos, los colores, las fuentes, el tema.**
- **No se introduce el modelo de Function Blocks (`FB_Base`, `Engine`, `nStep`).** El legacy sigue con su patrón actual de routers + use cases.
- **No se borra la rama `greenfield/iec-61131-3`** (sigue preservada en local + origin como referencia).

## Riesgos identificados

1. **El `TIAProcessGateway` NO tiene hooks explícitos** cuando cambia `self._connection_state`. Para emitir eventos SSE, hay que añadir los hooks (puede requerir modificar `gateway.py`). **Esto se discute con el operario antes de tocar.**
2. **El `ProgressTracker` y el `LogBuffer` SÍ tienen API para mutar** (métodos `update`, `append`, etc.). El SSE se engancha con un wrapper que observe las mutaciones (posible con un wrapper o con hooks explícitos en cada método de mutación).
3. **El frontend legacy es Vue 3 con `reactive` global.** El SSE actualiza el `store` directamente (no se introduce `usePlc` ni Proxy).
4. **El operario quiere ver la demo antes de pasar a Fase 3.** Si la Fase 2 convence, se discute el switch a Fase 3.

## Cierre con el operario

Al final de cada fase, el agente debe:
1. Reportar con output literal de los comandos de aceptación.
2. Listar archivos modificados con `git diff --stat`.
3. Confirmar que los tests pasan.
4. Pedir permiso explícito para la siguiente fase.

**El operario tiene veto absoluto en cada paso.** Si dice "para" en cualquier momento, se para y se discute.
