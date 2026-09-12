# Plan de Refactor Incremental — Por Pasos Pequeños

> **Lección del greenfield (sept-2026):** tareas grandes = alucinaciones de los agentes. Cada paso modifica 1-2 archivos, < 200 líneas, commiteable solo, verificable independientemente. Si delegamos 1 archivo a la vez, el agente NO inventa nada.

> **Rama actual:** `main` (HEAD `2279887`). Es la única rama operativa; no hay "rama legacy" ni "rama greenfield" operativas (la preservada `greenfield/iec-61131-3` es solo referencia, no se toca).
> **Regla dura:** nada de lo que está en `main` antes del refactor cambia sin pedir. Cada paso se valida con el operario antes del siguiente.

---

## Criterios de "paso pequeño"

Cada paso cumple **TODOS** estos criterios:
- Modifica **1 o 2 archivos como máximo** (1 archivo nuevo + 0-1 archivo modificado).
- Cambios **< 200 líneas por archivo** típicamente (excepciones documentadas).
- **Commiteable solo** (un commit por paso, mensaje descriptivo).
- **Verificable independientemente** (test manual o automatizado que confirma que el paso funciona).
- **No rompe nada existente** (los tests actuales siguen pasando; si se rompen, se documenta y se arregla en el mismo paso).
- **No introduce dependencias nuevas** (sin paquetes externos nuevos; solo stdlib + lo que ya está).

Si un paso no cumple estos criterios, se subdivide.

---

## Reglas del operario (las que NO se rompen)

- **Nada de `main` cambia sin pedir.** Cada paso es aditivo; el switch se hace DESPUÉS de validar.
- **Frontend visual: NO cambia NUNCA.** Copy, iconos, layout, colores, fuentes, tema: intactos. Solo las tripas (cómo se alimenta la UI) cambian. Si en algún paso un componente Vue se ve ligeramente distinto, es un bug, no el plan.
- **No se añaden áreas nuevas.** Solo `alimentacion`.
- **No se introduce Vue 3 sin build step** (la UI ya es Vue 3; no se sustituye por otra cosa).
- **No se borra la rama `greenfield/iec-61131-3`** (es solo referencia; se preserva).
- **No se añaden `sse.js` ni `composables/` ni `usePlc()` si no es estrictamente necesario** para el paso. Si se añaden, se discute con el operario.
- **Frontend: refactorizar el que ya tenemos.** Modificaciones in-place de los archivos actuales (`store.js`, `main.js`, `api.js`, componentes). El `main.js` modifica sus `setInterval` por `EventSource`; el `store.js` se queda como `reactive` y se alimenta del SSE.
- **Cada paso se valida con el operario antes del siguiente.**

---

## FASE 1 — SSE (12 pasos)

> **Patrón de testing en Fase 1** (desvío aceptado, operario 2026-09-10): el endpoint SSE queda abierto en `await queue.get()` esperando eventos. Los clientes HTTP completos (`TestClient`, `httpx.AsyncClient`) se cuelgan esperando EOF. Por tanto:
> - **1.0.3 (skeleton)**: `curl -N` o `TestClient` funciona porque el skeleton cierra tras emitir el snapshot.
> - **1.0.4 y 1.1.1-1.1.4**: **test unit del generador `_stream()` con `__anext__()` directamente** (sin HTTP). Es determinista, rápido y aísla el contrato del generador.
> - **1.1.5 (router)**: smoke test HTTP manual con `curl -N` (validación end-to-end con cliente HTTP real).
> - **Cierre de Fase 1**: demo end-to-end contra TIA Portal real del operario (S7-1500), 30 min.

### 1.0 Análisis y preparación

#### [x] Paso 1.0.1 — `core/sse/__init__.py` (vacío)
- **Archivo**: `core/sse/__init__.py` (NUEVO, 4 líneas).
- **Acción**: crear el paquete.
- **Verificación**: `python -c "import core.sse"` no falla.

#### [x] Paso 1.0.2 — `core/sse/event_bus.py`
- **Archivos**: `core/sse/event_bus.py` (NUEVO, ~60 líneas).
- **Acción**: `class EventBus` con `subscribe() -> asyncio.Queue` y `publish(event: dict)`. Idempotente. Thread-safe.
- **Verificación**: test unitario (1 archivo nuevo en `tests/core/test_event_bus.py`).

#### [x] Paso 1.0.3 — `core/sse/stream.py` (skeleton)
- **Archivos**: `core/sse/stream.py` (NUEVO, ~60 líneas).
- **Acción**: `GET /api/v1/stream` que retorna `text/event-stream` con snapshot vacío `data: {"type": "snapshot", "dbs": {}, "fbs": {}}\n\n`. Sin integración con `EventBus` todavía.
- **Verificación**: `curl -N /api/v1/stream` emite el snapshot vacío.

#### [x] Paso 1.0.4 — `core/sse/stream.py` (integra `EventBus`)
- **Archivos**: `core/sse/stream.py` (modificado, +30 líneas).
- **Acción**: el endpoint se suscribe al `EventBus` y emite cada evento. `asyncio.gather` para snapshot + loop de eventos.
- **Verificación**: **test unit del generador `_stream()` directamente con `__anext__()`** (publicar 1 evento → el generador lo emite). NO usar `TestClient` ni `httpx` — el stream queda abierto en `await queue.get()` y los clientes HTTP se cuelgan esperando EOF. La validación HTTP end-to-end con `curl -N` se hace en el Paso 1.1.5 cuando ya hay eventos reales circulando. **Desvío aceptado (operario, 2026-09-10).**

### 1.1 Integración backend (eventos)

#### [x] Paso 1.1.1 — `LogBuffer` → `EventBus`
- **Archivos**: `core/sse/log_subscribe.py` (NUEVO, ~30 líneas) o integración directa en `stream.py`.
- **Acción**: hook que publica un evento `log` al `EventBus` cada vez que `LogBuffer._push` se llama.
- **Verificación**: **test unit del generador `_stream()` con `__anext__()`** (no HTTP completo). Publica `log_buffer.info("test")` y verifica que `__anext__()` devuelve el chunk SSE con `{"type": "log", "level": "info", "message": "test"}`.

#### [x] Paso 1.1.2 — `ProgressTracker` → `EventBus`
- **Archivos**: `core/application/progress_buffer.py` (modificado, +20 líneas con un hook de publicación).
- **Acción**: cada `update` publica un evento `progress` al `EventBus` con current/total/percent.
- **Verificación**: **test unit del generador `_stream()` con `__anext__()`** (no HTTP completo). Llama `tracker.update(current=50, total=100)` y verifica que el chunk SSE contiene `{"type": "progress", ...}`.

#### [x] Paso 1.1.3 — `TIAProcessGateway._connection_state` → `EventBus`
- **Archivos**: `core/infrastructure/gateway.py` (modificado, ~15 líneas en `_set_state` o equivalente).
- **Acción**: cuando cambia `self._connection_state`, publica un evento `tia_state`.
- **Verificación**: **test unit del generador `_stream()` con `__anext__()`** (no HTTP completo). Llama `gateway.connect()` y verifica que el chunk SSE contiene `{"type": "tia_state", ...}`.
- **Riesgo**: primer toque al `gateway.py`. Se discute con el operario antes.

#### [x] Paso 1.1.4 — `gateway` `plcs` y `project_info` → `EventBus`
- **Archivos**: `core/infrastructure/gateway.py` (modificado, ~20 líneas en `get_plcs` y `get_project_info`).
- **Acción**: cuando se actualiza el cache de plcs o el project info, publica un evento.
- **Verificación**: **test unit del generador `_stream()` con `__anext__()`** (no HTTP completo). Trigger del refresh de cache y verificación del chunk SSE con `{"type": "plcs", ...}` o `{"type": "project_info", ...}`.

#### [x] Paso 1.1.5 — Router SSE en `core/web/app.py`
- **Archivos**: `core/web/app.py` (modificado, +5 líneas para incluir el router del SSE).
- **Acción**: `app.include_router(sse_router, prefix="/api/v1")`.
- **Verificación**: `curl /api/v1/stream` funciona.

### 1.2 Frontend (refactor in-place de `main.js`)

#### [x] Paso 1.2.1 — `main.js` apertura del SSE inline
- **Archivos**: `main.js` (modificado, +15 líneas en el bloque de bootstrap).
- **Acción**: añadir `const sse = new EventSource("/api/v1/stream")` y los handlers `onopen`, `onmessage`, `onerror`. Sin crear un `sse.js` nuevo. Sin clase wrapper. Directo en `main.js`. **La UI no cambia: misma estructura, mismos componentes, mismos copy/iconos/colores. Solo se añade un bloque de código que abre el SSE.**
- **Verificación**: F12 console muestra 1 `EventSource` abierto. La UI se ve EXACTAMENTE igual.

#### [x] Paso 1.2.2 — `main.js` handlers de actualización
- **Archivos**: `main.js` (modificado, +40 líneas en el handler de `onmessage`).
- **Acción**: parsear el JSON del evento (`{"type": "tia_state", "state": "connected"}`, etc.) y actualizar `store.tiaConnection`, `store.progress`, `store.logs` directamente. Sin composables, sin Proxy, sin abstracciones. Acceso directo al `store` (que ya es `reactive`). **La UI visual no cambia; solo cambia cómo se llena el `store` (antes por polling, ahora por SSE).**
- **Verificación**: cambio en backend se refleja en el store vía SSE. La UI actualiza (los indicadores cambian de color, los logs aparecen, el progress bar avanza). La UI visual es idéntica.

#### [x] Paso 1.2.3 — `main.js` coexistencia con polling
- **Archivos**: `main.js` (sin cambios en este paso).
- **Acción**: verificar que los 3 `setInterval` siguen activos (defensa contra fallos del SSE). El SSE actualiza el store cuando llega; el polling también. Si el SSE está caído, el polling mantiene la UI viva.
- **Verificación**: F12 network muestra AMBOS (3 setInterval + 1 EventSource). El store se actualiza por el último que llegue (idempotente).

### 1.3 Switch (quitar polling del `main.js`)

#### [x] Paso 1.3.1 — Quitar los 3 `setInterval` de `main.js`
- **Archivos**: `main.js` (modificado, ~-30 líneas).
- **Acción**: borrar los 3 `setInterval` (logs 1s, progress 500ms, TIA 2s) y sus handlers. El SSE es ahora la única fuente.
- **Verificación**: `grep "setInterval" interfaces/web_server/static/js/main.js` → 0. La UI sigue funcionando idéntica.

#### [x] Paso 1.3.2 — Quitar los `apiFetch*` redundantes de `api.js`
- **Archivos**: `api.js` (modificado, ~-15 líneas).
- **Acción**: borrar `apiFetchLogs`, `apiFetchProgress`, `apiFetchTiaConnection` (ya no se usan desde `main.js`).
- **Verificación**: F12 network no muestra llamadas recurrentes a esos endpoints.

**Total Fase 1**: 12 pasos. ~12 commits.

---

## FASE 2 — Function Blocks (15 pasos)

### 2.0 Infraestructura FBs

> **Convención de granularidad de nStep** (acordada con el operario, DA-004):
>
> - **Mínimo universal**: todo FB respeta `n_idle=0, n_start=10, n_exec=20, n_finish=30, n_error=98, n_done=99`. Esto es el contrato con el Engine (Test 4).
> - **Granularidad interna** (sub-etapas dentro de `n_exec=20` o `n_finish=30`):
>   - **Opción A (recomendada por defecto)**: colapsar. Las sub-etapas corren dentro de `n_exec=20`. La granularidad se reporta externamente via `progress.begin/finish` con stages. El HMI ve los stages via SSE del progreso (no del `fb_changed`).
>   - **Opción B (solo si la op tarda > 30s y el operario lo pide)**: nSteps intermedios (`nStep=21, 22, ...`). El HMI ve cada transición via SSE `fb_changed`.
> - **Cada FB documenta en su docstring** qué sub-etapas corre en cada nStep, y si usa progress.begin/finish para granularidad externa.

#### [x] Paso 2.0.1 — `core/plc/__init__.py` (vacío)
- **Archivo**: `core/plc/__init__.py` (NUEVO, 4 líneas).
- **Acción**: crear el paquete.

#### [x] Paso 2.0.2 — `core/plc/function_base.py` (clase base sola)
- **Archivos**: `function_base.py` (NUEVO, ~80 líneas).
- **Acción**: `class FunctionBase` con `__init__(nombre)`, `nStep=0`, `start(**params)` idempotente, `tick()` que lanza `NotImplementedError` (las subclases lo overridean).
- **Verificación**: test unitario del comportamiento base (idempotencia de start, nStep discreto).

#### [x] Paso 2.0.3 — Test 1 del `.clinerules` (lock no reentrante)
- **Archivos**: `tests/core/test_function_base.py` (NUEVO, +30 líneas).
- **Acción**: test que verifica que `start()` no re-entrante (segunda llamada mientras está activo se ignora).

#### [x] Paso 2.0.4 — `core/plc/function_base.py` (tolerancia best-effort)
- **Archivos**: `function_base.py` (modificado, +20 líneas).
- **Acción**: `tick()` envuelve cada `await` en `try/except`, log + degradado pero vivo.
- **Verificación**: test que dispara una excepción en `tick()` y verifica `nStep=99` + `error_msg`.

#### [x] Paso 2.0.5 — `core/plc/engine.py` (OB1 solo, sin FBs)
- **Archivos**: `engine.py` (NUEVO, ~80 líneas).
- **Acción**: `class Engine` con `start_loop()`, `stop_loop()`, `register_fb(name, fb)`. Loop asyncio 100 ms.
- **Verificación**: test que registra 1 FB y verifica que `tick()` se llama.

#### [x] Paso 2.0.6 — Test 4 del `.clinerules` (Engine no tickea FBs terminales)
- **Archivos**: `tests/core/test_engine.py` (NUEVO, +30 líneas).
- **Acción**: test que verifica que FBs en `nStep=0`, `n_done`, `n_error` no se tickean.

#### [x] Paso 2.0.7 — `core/plc/engine.py` (publica `fb_changed` al `EventBus`)
- **Archivos**: `engine.py` (modificado, +15 líneas).
- **Acción**: tras tickear un FB, si cambió `nStep`, publica un evento `fb_changed` al `EventBus`.
- **Verificación**: test que verifica que el evento se publica.

### 2.1 Migración iterativa de FBs (1 por paso)

#### [x] Paso 2.1.1 — `function_SubirExcel.py` (vacío, stub)
- **Archivos**: `function_SubirExcel.py` (NUEVO, ~20 líneas).
- **Acción**: clase `FunctionSubirExcel(FunctionBase)` con `tick()` que solo incrementa `nStep` (10→20→30) sin lógica.
- **Verificación**: test que verifica el state machine básico.

#### [x] Paso 2.1.2 — `function_SubirExcel.py` (con lógica del use case actual)
- **Archivos**: `function_SubirExcel.py` (modificado, +150 líneas).
- **Acción**: la lógica del `use_cases/upload_excel.py` se adapta al FB.
- **Verificación**: test que mockea el parser y verifica el flujo end-to-end.

#### [x] Paso 2.1.3 — `function_ScanPlcBlocks.py`
- **Mismo patrón que 2.1.1-2.1.2**: stub primero, lógica después. 2 commits.
- **Tests**: 1 test del stub, 1 test de la lógica.

#### [x] Paso 2.1.4 — `function_GenerarPreview.py`
- Idem.

#### [x] Paso 2.1.5 — `function_SincronizarDispositivos.py`
- Idem.

#### [x] Paso 2.1.6 — `function_SincronizarDispComentarios.py`
- Idem.

#### [x] Paso 2.1.7 — `function_SincronizarProcesosComentarios.py`
- Idem.

#### [x] Paso 2.1.8 — `function_DiffConstants.py`
- Idem.

**Total sub-pasos FBs**: 7 FBs × 2 pasos = 14 commits + 7 tests = 21 sub-pasos.

### 2.2 Router genérico

#### [x] Paso 2.2.1 — `core/web/routers/plc.py`
- **Archivos**: `plc.py` (NUEVO, ~60 líneas).
- **Acción**: `POST /api/v1/plc/fb/{name}/start` + `POST /api/v1/plc/fb/{name}/disconnect`.
- **Verificación**: `curl -X POST /plc/fb/SubirExcel/start` arranca el FB y emite el evento `fb_changed`.

**Total Fase 2**: ~24 sub-pasos (incluyendo sub-pasos de cada FB). ~24 commits.

---

## FASE 3 — Data Blocks (13 pasos)

### 3.1 DBs transversales

#### [x] Paso 3.1.1 — `data_estado.py`
- **Archivos**: `data_estado.py` (NUEVO, ~50 líneas).
- **Acción**: `class DataEstado` con campos `worker_alive`, `tia_state`, `project_name`, `project_path`, `plcs`, `last_error`, `last_ping_ok_unix`. Default values.
- **Verificación**: test unitario.

#### [x] Paso 3.1.2 — `data_bloque_cache.py`
- **Archivos**: `core/data/data_bloque_cache.py` (NUEVO, ~70 líneas) + `tests/core/test_data_bloque_cache.py` (7 tests).
- **Acción**: `@dataclass(frozen=False) class DataBloqueCache` con `blocks`/`tag_tables`/`udts`/`plc_name`/`scanned_at`. `default_factory` para los 3 dicts y para `scanned_at` (UTC). `to_dict()` con shape back-compat.
- **Verificación**: 7/7 tests verdes. Suite completa: 1057 pass, 2 fail preexistentes (logging flaky + worker E2E sin TIA).
- **Import**: `BloquePLC` desde legacy `core.models.bloque_plc` (se actualiza en 3.1.3).

#### [x] Paso 3.1.3 — `data_bloque_plc.py`
- **Archivos**: `core/data/data_bloque_plc.py` (NUEVO, ~85 líneas) + `tests/core/test_data_bloque_plc.py` (10 tests).
- **Acción**: `@dataclass(frozen=True) class DataBloquePLC` con `nombre`/`numero`/`tipo`/`ruta`. `normalize_name` (tolera NBSP, espacios, case, sin prefix-strip) + `detect_tipo` (DB/FB/FC/OB/UDT/OTHER, case-insensitive). `to_dict()`.
- **Verificación**: 10/10 tests verdes. Suite: 1067 pass, 2 fail preexistentes.
- **Bonus**: `data_bloque_cache.py` actualizado para importar `DataBloquePLC` (no legacy). `BloquePLC` legacy en `core/models/bloque_plc.py` sigue coexistiendo (DA-006).

#### [x] Paso 3.1.4 — `data_app_state.py`
- **Archivos**: `core/data/data_app_state.py` (NUEVO, ~85 líneas) + `tests/core/test_data_app_state.py` (8 tests).
- **Acción**: `@dataclass(frozen=False) class DataAppState` con 4 campos (`dispositivos`, `dimensiones`, `excel_cache`, `excel_path`). `set_devices()` atajo con copia defensiva. `to_dict()` emite `excel_loaded` flag (NO el cache, contiene objetos no-JSON).
- **Verificación**: 8/8 tests verdes. Suite: 1075 pass, 2 fail preexistentes.
- **Decisión de diseño**: data pura, NO replica API data-driven del legacy (`get_devices`/`list_hw_types`/etc.) ni el Singleton con `Lock` ni la integración con `AreaRegistry.contributes_state_extensions`. El legacy `AppState` (31 importadores) sigue coexistiendo intacto (DA-006).

### 3.2 DBs del área

#### [x] Paso 3.2.1 — `data_DispCatalog.py`
- **Archivos**: `areas/alimentacion/data/data_DispCatalog.py` (NUEVO).
- **Acción**: migrado de `domain/disp_catalog.py`.
- **Verificación**: test.

#### [x] Paso 3.2.2 — `data_Dispositivos.py` (SUBDIVIDIDO)
- **Archivos**: `areas/alimentacion/data/data_Dispositivos.py` (211 lineas) + `areas/alimentacion/data/data_Dimensiones.py` (130 lineas) + sus tests (13 + 13 tests).
- **Acción**: Protocol `Dispositivo` + 6 Disp* (`DispED`, `DispEA`, `DispSA`, `DispV`, `DispM`, `DispM_VF`) en `data_Dispositivos.py`. `DimensionesDispositivos` en `data_Dimensiones.py` (subdivision del plan original: el archivo unico pasaba de 200 lineas, se parte en 2).
- **Verificacion**: 26/26 tests verdes.
- **Bug preexistente detectado**: el filtro de legacy en `from_catalog` solo excluye nombres canonicos, no los `num_disp_*` legacy. Mismo bug en el legacy; queda para Fase 4 (no es migracion 1:1 arreglarlo).

#### [x] Paso 3.2.3 — `data_ExcelCache.py`
- **Archivos**: `areas/alimentacion/data/data_ExcelCache.py` (~90 lineas) + test (7 tests).
- **Acción**: `DataExcelCache(frozen=True)` con 12 campos. `to_dict()` con shape estable (7 keys), omite los 3 lookups precomputados, serializa `n_max` via `to_api_dict()` y las 4 listas via `dataclasses.asdict`. **Hecho al final del bloque** (3.2.4-3.2.7 antes) porque importa los DTOs hoja ya migrados.
- **Verificacion**: 7/7 tests verdes.

#### [x] Paso 3.2.4 — `data_Procesos.py`
- **Archivos**: `areas/alimentacion/data/data_Procesos.py` (~40 lineas) + test (5 tests).
- **Acción**: `DataProcesoPLC(frozen=True)` con los 8 campos del Excel (uid, nombre, codigo + 5 contadores).
- **Verificacion**: 5/5 tests verdes.

#### [x] Paso 3.2.5 — `data_ParametrosInt.py`
- **Archivos**: `areas/alimentacion/data/data_ParametrosInt.py` (~50 lineas) + test (6 tests).
- **Acción**: `DataParamIntPLC(frozen=True)` con 12 campos. `num_lista: int | str` para marcadores semanticos (`"N/A"`, `"TODOS"`).
- **Verificacion**: 6/6 tests verdes.

#### [x] Paso 3.2.6 — `data_ParametrosReal.py`
- **Archivos**: `areas/alimentacion/data/data_ParametrosReal.py` (~45 lineas) + test (5 tests).
- **Acción**: `DataParamRealPLC(frozen=True)` con los 12 campos identicos a `DataParamIntPLC` (R4: tipos nominales distintos aunque campos iguales). Test explicito verifica que `isinstance(pr, DataParamIntPLC) == False`.
- **Verificacion**: 5/5 tests verdes.

#### [x] Paso 3.2.7 — `data_Alarmas.py`
- **Archivos**: `areas/alimentacion/data/data_Alarmas.py` (~40 lineas) + test (4 tests).
- **Acción**: `DataAlarmaPLC(frozen=True)` con 6 campos. R-F4.1: NO tiene atributo `visibilidad` (defensa contra schema drift). Test explicito verifica que `not hasattr(a, "visibilidad")`.
- **Verificacion**: 4/4 tests verdes.

#### [x] Paso 3.2.8 — `data_DispSlotMap.py` (NUEVO, no había legacy)
- **Archivos**: `areas/alimentacion/data/data_DispSlotMap.py` (~50 lineas) + test (6 tests).
- **Acción**: `DataDispSlotMap(frozen=True)` con 4 campos que consolidan la tupla de `disp_build_slot_maps` (slot_maps, db_names, db_array_names, warnings). `to_dict()` convierte slots `int` a `str` (JSON-friendly).
- **Verificacion**: 6/6 tests verdes.

#### [x] Paso 3.2.9 — `data_ProcSlotMap.py`
- **Archivos**: `areas/alimentacion/data/data_ProcSlotMap.py` (~70 lineas) + test (6 tests).
- **Acción**: `DataProcSlotMap(frozen=True)` con 12 campos migrado 1:1 desde `application/proc_slot_map_builder.py::ProcSlotMap`. `to_dict()` convierte slots `int` a `str`.
- **Verificacion**: 6/6 tests verdes.

**Total Fase 3**: 13 pasos. ~13 commits.

### 3.3 Refactor in-place del `store.js` (no se sustituye)

#### [x] Paso 3.3.1 — Eliminar `refreshTiaConnection` (helper redundante)
- **Archivos**: `interfaces/web_server/static/js/store.js` (1 archivo, ~30 lineas borradas) + `tests/test_store_tia_methods.py` (reescrito, 3 tests con polaridad invertida) + `tests/test_store_tia_connection.py` (5 tests eliminados de `refreshTiaConnection`).
- **Acción**: eliminar la funcion `refreshTiaConnection` (era pura dead code desde 1.3.1), limpiarla del `Object.assign(store, ...)`, actualizar docstrings. Invertir la regresion en `test_store_tia_methods.py` para que valide la AUSENCIA del helper.
- **Verificacion**: 1142 pass, 2 fail preexistentes (logging flaky + worker E2E sin TIA), 0 regresiones. -5 tests que validaban la existencia de `refreshTiaConnection`.
- **Caso excepcional**: 1 paso toca 3 archivos (1 de codigo + 2 de tests) por la regla del plan "si se rompen, se documenta y se arreglan en el mismo paso".

#### [ ] Paso 3.3.3 — Catálogo vía SSE (3.3.3.x, 3 sub-pasos)
- **Contexto**: 3.3.2 (`loadCatalog`) NO se puede eliminar hasta que el catálogo llegue por SSE. El catálogo actualmente se carga por `apiFetchCatalog()` en `main.js` (llamada fetch única en bootstrap). El objetivo: el backend emite el catálogo en el snapshot SSE inicial, y `main.js` lo asigna a `store.catalog` cuando llega el evento. Tras eso, `apiFetchCatalog` y `loadCatalog` son dead code.
- **Estado**: BLOQUEADO por **DA-011** (SSE snapshot inicial vacío). Hasta que DA-011 no esté hecho, el snapshot no contiene `dbs` ni `fbs` ni `catalog`; añadir un campo más al snapshot vacío no arregla nada.
- **Sub-pasos previstos** (3 commits, ~65 líneas):
  - 3.3.3.1 — Backend: `GET /api/v1/catalog` queda como está, pero su respuesta se cachea en `core/data/data_app_state.py` (o nuevo `data_Catalog.py`) y el `Engine.snapshot()` (introducido en DA-011) lo incluye bajo `"catalog": {...}`. ~30 líneas.
  - 3.3.3.2 — Frontend: `main.js` añade handler SSE para `type=catalog` que asigna `store.catalog = data`. Borrar la llamada `apiFetchCatalog()` del bootstrap. ~15 líneas.
  - 3.3.3.3 — Test: integración SSE → catalog → store. Mock del gateway con `MagicMock(spec=TIAProcessGateway)`, el `Engine.snapshot()` devuelve el catálogo esperado. ~20 líneas.
- **Verificación**: la SPA carga el catálogo SIN llamada a `/api/v1/catalog` (F12 network muestra solo `/api/v1/stream` en el bootstrap).

#### [=] Paso 3.3.2 — `loadCatalog`: PENDIENTE (NO eliminado)
- **Decisión**: NO se elimina `loadCatalog` en este sprint.  Razon: el plan asume que los helpers de fetch "se han sustituido por SSE", pero el backend NO emite el catalogo por SSE todavia.  Eliminar `loadCatalog` ahora dejaria la SPA sin catalogo (la SPA muestra los device_tabs y nmax desde `store.catalog`; sin el load inicial, cae a fallbacks degradados y la pestaña dinamica de "Definicion programacion" no aparece).
- **Pendiente para una fase futura**: implementar la emision SSE del catalogo en el backend (canal `catalog` o similar) Y actualizar `main.js` para que el handler SSE asigne `store.catalog` cuando llegue el evento.  Tras eso, `loadCatalog` y el `apiFetchCatalog` quedaran como dead code y podran eliminarse.
- **Verificacion de la decision**: grep en `core/sse/` no encuentra emision de `catalog`; grep en `main.js` no encuentra actualizacion de `store.catalog` desde el SSE.  Confirmado: la sustitucion no se ha hecho.

- `store.js` (52 KB) se queda como está en estructura, pero se **refactoriza in-place**:
  - Los campos que vienen del backend (`tiaConnection`, `progress`, `logs`) se mantienen como `reactive({...})`.
  - Se ELIMINAN los helpers de fetch (`refreshTiaConnection`, `loadCatalog`, etc.) que se han sustituido por SSE.
  - Si algún componente importa un helper eliminado, se actualiza el import (1 línea por componente).
  - NO se introduce un `usePlc()` composable ni un `Proxy` delegate. El `store` ES el estado.
- NO se crea `interfaces/web_server/static/js/composables/`.
- **La UI visual no cambia.**

---

## FASE 4 — Refactor OB1 (10 sub-pasos)

> **Patrón arquitectónico nuevo**: single-threaded cyclic main loop (OB1 PLC-style) en el hilo principal + Flask sync en hilo secundario + comunicación vía `queue.Queue` (thread-safe, stdlib) + TIA wrapper llamado directamente sin subproceso.
>
> **Justificación**: ver **DA-014**. La causa raíz del keepalive SSE workaround (DA-012) es arquitectónica: subproceso con PIPE handles en ProactorEventLoop. OB1 la elimina de raíz.
>
> **Regla del plan**: cada sub-paso modifica 1-2 archivos, <200 líneas, commiteable solo, validado con el operario antes del siguiente. Si un sub-paso se complica, se subdivide.
>
> **Estado**: 🟢 Spike 4.0.1 validado y commiteado (`a85857a`). Procediendo con 4.1.x.

### 4.0 Spike técnico OB1 (validación previa)

#### [x] Paso 4.0.1 — Spike OB1 mínimo viable ✅
- **Archivos**: NUEVO script autocontenido `tests/spikes/ob1_spike.py` (o `core/infrastructure/_spike_ob1.py`, ~150 líneas).
- **Acción**: prototipo que demuestra el modelo OB1 sin tocar el código de producción:
  - `SyncTIAClient` stub con 1 comando (`ping`) y 1 método directo (sin asyncio, sin subproceso).
  - Loop OB1 `while True: tia_client.dispatch_pending(); engine.run_cycle(); sleep(100ms)` en hilo principal.
  - Flask en hilo secundario con 1 endpoint que dispatcha al OB1 vía `queue.Queue` + `concurrent.futures.Future`.
  - SSE Flask endpoint que devuelve snapshot hardcodeado (sin engine real, solo smoke test).
  - Validar end-to-end: el endpoint responde, el OB1 tickea, no hay async, no hay subproceso.
- **Verificación**: el operario ejecuta el spike en su máquina, ve que arranca y responde. Si funciona, se procede a 4.1+. Si falla, se diagnostica antes de tocar nada más.
- **Output**: commit con el spike en `tests/spikes/`. Si valida, se mantiene como referencia. Si no, se descarta.
- **Tiempo estimado**: 1 día.
- **Estado**: ✅ Commit `a85857a` en `feature/spike-ob1`. 210 inserciones (175 líneas de código + headers). Operario validó que arranca + 3 endpoints responden + sin subproceso. Stack: Flask 3.1.3 + threading + queue.Queue (sin asyncio, sin uvicorn, sin asyncio.subprocess).

### 4.1 tia_client.py (reemplaza gateway.py + worker_tia.py)

#### [x] Paso 4.1.1 — tia_client.py (skeleton) ✅
- **Archivos**: `core/infrastructure/tia_client.py` (NUEVO, ~80 líneas).
- **Acción**: `class SyncTIAClient` con `__init__()` (carga `siemens_tia_scripting`), `dispatch(command, args)`, `register_command(name, handler)`. **Sin asyncio.** Sin subproceso.
- **Verificación**: tests unitarios con mock del wrapper. No toca producción todavía (se importa solo desde el spike si se valida).
- **Tiempo estimado**: 0.5 día.
- **Estado**: ✅ Commit `2716a29` en `feature/spike-ob1`. 261 inserciones (91 líneas módulo + 107 líneas tests, 13/13 verdes). API: `register_command`/`dispatch`/`submit`/`dispatch_pending`/`attach_wrapper`/`wrapper`/`has_command`/`registered_commands`. Singleton `tia_client`. main.py NO se toca (queda para 4.5.1).

#### [ ] Paso 4.1.2 — tia_client.py (comandos core migrados)
- **Archivos**: `core/infrastructure/tia_client.py` (modificado, +400 líneas → subdividido en 4.1.2a/b/c por regla <200 líneas).
- **Acción**: migrar los handlers de `COMMAND_REGISTRY` desde `worker_tia.py`: `attach_portal`, `list_plcs`, `get_project_info`, `compile_plc`, `export_*`, `import_*`, `get_user_constants`, `update_user_constant_*`, `delete_user_constant`, `execute_transactional_batch`, `ping`. Sin cambios funcionales, solo movimiento de código.
- **Subdivisión planificada** (validar con operario antes de empezar):
  - **4.1.2a — Lifecycle + inspección** (~+150 líneas): `open_new_portal`, `open_project`, `save_project`, `close_project`, `list_plcs`, `get_project_info`, `list_blocks`, `scan_blocks`, `ping`. **9 comandos**.
  - **4.1.2b — Mutación + export/import masivo** (~+150 líneas): `compile_plc`, `export_blocks_sd`, `export_udts_sd`, `export_plc_tags_xml`, `import_blocks_sd`, `import_plc_tags_xml`. **6 comandos**.
  - **4.1.2c — Granular + user constants + transaccional** (~+100 líneas): `export_block`, `import_block`, `export_tag_table`, `import_tag_table`, `get_user_constants`, `update_user_constant_value`, `update_user_constant_name`, `delete_user_constant`, `execute_transactional_batch`. **9 comandos**.
- **Verificación**: tests con mock del wrapper verifican cada comando retorna el shape esperado. Suite completa verde después de cada subdivisión.
- **Tiempo estimado**: 1 día (sin subdivisión) / ~1.5 días (con subdivisión + tests por lote).

#### [ ] Paso 4.1.3 — Áreas registran comandos en tia_client (no en subproceso)
- **Archivos**: `areas/alimentacion/infrastructure/tia/extra_commands.py` → renombrado a `commands.py` (modificado, ~10 líneas: `register(tia_client)` en lugar de `register(registry)`).
- **Acción**: las áreas registran sus comandos directamente en el `tia_client` (mismo proceso, sin IPC). La interfaz `register(tia_client)` se estandariza para que cualquier área pueda usarla.
- **Verificación**: el wiring en `main.py` registra todas las áreas correctamente. Tests de integración con mock verifican que los comandos del área se invocan vía `tia_client.dispatch()`.
- **Tiempo estimado**: 0.5 día.

### 4.2 engine.py OB1 while loop

#### [ ] Paso 4.2.1 — engine.py con loop OB1 sync
- **Archivos**: `core/plc/engine.py` (modificado, refactor ~100 líneas).
- **Acción**: `class Engine` con `run_cycle()` (método sync que ejecuta un ciclo: process commands pendientes → tick FBs no terminales → snapshot → broadcast). El loop `while True: run_cycle(); sleep(100ms)` se hace en `main.py`, NO en el engine. **Sin asyncio.create_task.**
- **Verificación**: tests existentes del engine (Fase 2) siguen verdes con el nuevo método sync. Nuevo test verifica que `run_cycle()` ejecuta un ciclo determinista.
- **Tiempo estimado**: 0.5 día.

### 4.3 event_bus.py con queue.Queue

#### [ ] Paso 4.3.1 — event_bus.py con queue.Queue thread-safe
- **Archivos**: `core/sse/event_bus.py` (modificado, ~30 líneas).
- **Acción**: reemplazar `asyncio.Queue` por `queue.Queue` (thread-safe, stdlib). `subscribe()` retorna una `queue.Queue` por suscriptor. `publish(event)` pone en todas las colas con `put_nowait()`.
- **Verificación**: tests existentes de `event_bus` (Fase 1) siguen verdes con el nuevo transporte. Nuevo test verifica que `publish` desde otro hilo llega a suscriptores en el hilo principal.
- **Tiempo estimado**: 0.5 día.

### 4.4 Flask app + blueprints

#### [ ] Paso 4.4.1 — app.py Flask factory
- **Archivos**: `interfaces/web_server/app.py` (refactor, ~120 líneas).
- **Acción**: `create_app(tia_client, engine, bus, config_manager, progress_tracker)` retorna una `Flask` app con los blueprints montados. **Sin lifespan async.** Sin `uvicorn`. Flask se arranca con `werkzeug.serving.make_server()` en un hilo secundario desde `main.py`.
- **Verificación**: tests existentes que usan `create_app` se actualizan para inyectar `tia_client` en lugar de `gateway`. Mantienen verde.
- **Tiempo estimado**: 0.5 día.

#### [ ] Paso 4.4.2 — Migrar 7 blueprints a Flask
- **Archivos**: `interfaces/web_server/routers/*.py` → `interfaces/web_server/blueprints/*.py` (refactor mecánico, 1:1 FastAPI → Flask). 7 archivos, ~60 líneas cada uno.
- **Acción**: `@router.get("/...")` → `@bp.route("/...", methods=["GET"])`. `request: Request` → `request`. `JSONResponse` → `jsonify`. `StreamingResponse` → `Response(generator(), mimetype="text/event-stream")`. `Depends()` → inyección manual o `flask.g`.
- **Verificación**: cada blueprint mantiene sus tests pasando (adaptados a Flask `test_client`). Suite completa verde.
- **Tiempo estimado**: 2 días.

### 4.5 main.py OB1 main loop

#### [ ] Paso 4.5.1 — main.py con OB1 main loop + Flask en hilo
- **Archivos**: `main.py` (refactor, ~120 líneas).
- **Acción**: `run_web_mode()` reemplaza `asyncio.run(_run_web_mode_async(...))` por:
  - Crear `tia_client = SyncTIAClient()`
  - Registrar áreas (`register_alimentacion(tia_client)`)
  - Crear Flask app (`create_app(tia_client, ...)`)
  - Arrancar Flask en hilo daemon (`werkzeug.serving.make_server(host, port, app).serve_forever()`)
  - OB1 main loop en hilo principal: `while not shutdown_event.is_set(): tia_client.dispatch_pending_commands(); engine.run_cycle(); sleep_to_next_cycle(100ms)`
  - On Ctrl+C: shutdown_event.set(), Flask server.shutdown(), tia_client.detach()
- **Verificación**: el operario arranca con `python main.py --web`, ve la UI, hace click en algún FB, el ciclo responde. **Sin subproceso** en Task Manager.
- **Tiempo estimado**: 0.5 día.

### 4.6 Eliminar código legacy

#### [ ] Paso 4.6.1 — Eliminar gateway.py y worker_tia.py
- **Archivos**: `git rm core/infrastructure/gateway.py core/infrastructure/tia/worker_tia.py`.
- **Acción**: borrar los archivos. Imports que queden rotos se arreglan en el mismo commit.
- **Verificación**: `grep -r "from core.infrastructure.gateway" --include="*.py"` → 0. `grep -r "from core.infrastructure.tia.worker_tia"` → 0. Tests pasan.
- **Tiempo estimado**: 0.5 día.

### 4.7 Cleanup legacy post-OB1 (Fase 4 original integrada)

#### [ ] Paso 4.7.1 — Borrar `areas/alimentacion/application/` y `domain/`
- **Archivos**: `git rm -r areas/alimentacion/application/ areas/alimentacion/domain/`.
- **Verificación**: tests pasan.

#### [ ] Paso 4.7.2 — Borrar `core/application/state.py` y `core/models/`
- Idem.

#### [ ] Paso 4.7.3 — Quitar `apiFetch*` redundantes de `api.js` (si no se hizo en 1.3.2)
- Idem.

### 4.8 Tests de integración OB1

#### [ ] Paso 4.8.1 — Suite de tests sin pytest-asyncio
- **Archivos**: tests que actualmente usan `@pytest.mark.asyncio` se reescriben a sync.
- **Verificación**: `pytest tests/ -q` → 1151+ pass, 0 fail nuevos.

### 4.9 Demo + rebuild

#### [ ] Paso 4.9.1 — Demo end-to-end con TIA real
- **Acción**: el operario arranca `python main.py --web`, conecta a TIA, ejecuta un FB, verifica que el SSE emite el snapshot y los `fb_changed`. Compara UX con versión pre-OB1: ¿se ve igual la UI? ¿el click en FB responde igual? ¿hay latencia perceptible?
- **Verificación**: demo pasa todos los pasos manuales.

#### [ ] Paso 4.9.2 — Rebuild del `.exe` con PyInstaller
- **Archivos**: `dist/zc_automation_suite.exe` (NUEVO).
- **Acción**: `python build_exe.py`. Adaptar `.spec` para Flask + threading si hace falta. Verificar que el `.exe` arranca bandeja + web + TIA real funcionan.
- **Verificación**: demo del `.exe` con TIA real funciona end-to-end.

#### [ ] Paso 4.9.3 — Actualizar docs (`.clinerules`, `AGENTS.md`, `README.md`)
- **Archivos**: 3 archivos de docs, ~100 líneas cada uno.
- **Acción**: reflejar la nueva arquitectura OB1, sin asyncio, sin subproceso, Flask en hilo, queue.Queue, etc.

**Total Fase 4 (OB1)**: 16 sub-pasos. ~16 commits. ~7-8 días.

---

## Resumen total

| Fase | Pasos | Commits estimados | Estado |
|---|---|---|---|
| Fase 1 — SSE | 12 | 12 | ✅ |
| Fase 2 — FBs | 24 (incluyendo sub-pasos) | 24 | ✅ |
| Fase 3 — DBs (3.1 + 3.2) | 12 | 12 | ✅ |
| Fase 3 — `store.js` (3.3.1) | 1 | 1 | ✅ (`5f1c82e`) |
| DA-005.5 (wiring Engine + 7 FBs) | 1 | 1 | ✅ (`3a882a0`) |
| DA-011 (snapshot inicial SSE) | 1 | 1 | ✅ (`e70c560`) |
| DA-012 (keepalive SSE, fix real) | 1 | 1 | ✅ (`7b5fd01`) |
| ZC_DEBUG=1 logging infra (DA-012 historia) | 1 | 1 | ✅ (`9d6c208`) |
| **DA-013 (log unificado `zc.log`)** | **3** | **3** | **✅ (`064f153`, `62ae0db`, `2279887`)** |
| **Feature 2 — `ProgressBar` per-instance** | **3** | **3** | **🟡 Pendiente (A creado sin commit, B y C por hacer)** |
| **3.3.3.x (catálogo vía SSE)** | 3 | 3 | 🟡 Pendiente (desbloqueado) |
| **3.3.2 (eliminar `loadCatalog`)** | 1 | 1 | ⏸️ Bloqueado por 3.3.3.x |
| **DA-014 — Fase 4 Refactor OB1** | 16 | 16 | 🟡 En curso (4.0.1+4.1.x ✅; 4.2+4.3+4.4+4.5 ✅; 4.6 soft + 4.8 parcial; 4.7 + full 4.6/4.8 + 4.9 deferred) |
| Demo final + rebuild `.exe` | — | — | Pendiente |
| **Total** | **~78 pasos** | **~78 commits** | **~80 hechos** |

**Commits revertidos** (parte de la historia, no cuentan en el total):
- `e07c33a` — DA-012 `stderr=DEVNULL` (REVERTIDO por `83cf920`, hipótesis descartada).

**Tiempo estimado restante**: ~5 días (~13 commits: Feature 2 × 3 + 3.3.3.x × 3 + 3.3.2 + DA-014 Fase 4 OB1 × 5 restantes — 4.1.2a hecho en 10 commits; 4.1.2b/c pendientes). Validación con operario entre cada paso.

---

## Cómo se EJECUTA cada paso

Para cada paso:
1. **Yo (mavis) escribo un prompt breve** (~1 página) con el scope del paso.
2. **Lanzamos un agente** (o lo hago yo si el paso es trivial).
3. **El agente o yo modificamos el archivo** (1-2 archivos, < 200 líneas).
4. **Validamos** (test manual o automatizado).
5. **Commit** con mensaje descriptivo.
6. **Push a `main`** (con la rama de feature, si la cosa se complica).
7. **Siguiente paso** con tu OK.

Si un paso se complica (alucinaciones, scope creep, regresiones), se subdivide ANTES de seguir.

---

## Lo que NO está en este plan (y por qué)

- **Frontend Vue 3 sin build step** (Fase 5 según el plan greenfield): el operario no lo ha pedido. Si lo pide, se planifica en un documento aparte.
- **Nuevas áreas** (como `tia_conexion`): prohibido.
- **Cambios visuales del frontend** (copy/iconos/colores/tema): prohibido. Las tripas sí cambian; la UI no.
- **Auth, multi-tenant, multi-PLC simultáneo**: fuera de scope.
- **Tests e2e contra TIA real**: se hacen como paso adicional cuando el FB esté listo, en una sesión con el operario.

---

## Desvíos aceptados (changelog de decisiones)

### DA-001 (2026-09-10, operario) — Patrón de testing del SSE

- **Contexto**: el plan original proponía validar el endpoint SSE con `TestClient` o `httpx.AsyncClient`. Estos clientes esperan EOF del stream, pero el generador queda abierto en `await queue.get()` esperando eventos. Se cuelgan.
- **Desvío**: los pasos 1.0.4, 1.1.1, 1.1.2, 1.1.3, 1.1.4 se validan con **test unit del generador `_stream()` con `__anext__()` directamente** (sin HTTP completo).
- **Alcance**: solo el patrón de testing de esos 5 pasos. NO cambia estrategia, arquitectura, frontend, FBs, DBs, nomenclatura, árbol, ni el plan de commits.
- **Lo que se mantiene**: el smoke test HTTP con `curl -N` en el Paso 1.1.5 + la demo end-to-end contra TIA real al cerrar Fase 1.

### DA-002 (2026-09-10, operario) — Lock + assert movido de 2.0.4 a 2.0.2

- **Contexto**: el plan original tenía "clase base sola" en 2.0.2 y "tolerancia best-effort" en 2.0.4. El test del 2.0.3 ("lock no reentrante") necesitaba que el lock existiera.
- **Desvío**: Aketza incluye el `asyncio.Lock` + `assert self._lock.locked()` en 2.0.2 (en `_start_locked` y `_tick_locked`), no en 2.0.4. Razón: el paso 2.0.2 queda commiteable solo (testeable) y el assert cubre ambos métodos.
- **Influencia**: ninguna en la estrategia. La "tolerancia best-effort" (try/except en cada `await` de `_tick_locked`) se mantiene en 2.0.4 como estaba. Solo cambia el contenido de 2.0.4: ahora es "tolerancia best-effort" sin lock (que ya está en 2.0.2).

### DA-003 (2026-09-10, operario) — Subclases overridean `_tick_locked`, no `tick`

- **Contexto**: el plan original decía "subclases overridean `tick()`". Aketza implementa "subclases overridean `_tick_locked()`".
- **Razón**: coherencia con el patrón wrapper / `_locked` (ya usado en `core/sse/stream.py` con `_stream()` y `_publish()`). El wrapper público `tick()` adquiere el lock; las subclases implementan `_tick_locked()` que asume el lock cogido. El assert del greenfield es estructural: la subclase no puede saltarse el lock.
- **Influencia en el plan**: los pasos 2.1.1-2.1.8 (migración de FBs) overridean `_tick_locked`, no `tick`. La guarda de `is_terminal()` queda en la base (la subclase la hereda si llama a `super()._tick_locked()`, o no la tiene si overridea directamente — eso se discute en cada FB).

### DA-005 (2026-09-10, operario) — Decisiones operativas de Fase 2 (transversales a todos los FBs)

Documentadas en cada FB durante la implementación; las recojo aquí para que el siguiente agente las respete:

1. **Wrapper pattern para FBs grandes** (DA-005.1): los use cases de > 200 líneas no se copian inline en el FB. El FB es un wrapper con state machine que delega al use case via `use_case_factory` lazy. La "encapsulación" del FB es la state machine (engine-friendly, observable, progress-tracked, best-effort). El use case legacy sigue ahí hasta Fase 4.
2. **Sin `progress.begin/finish` en los FBs** (DA-005.2): el caller (router) las hace. Los FBs solo emiten `start_stage/finish_stage/error_stage`. Coherente con `.clinerules` §7 (los FBs son transaccionales, no manejan UI).
3. **Sin `HTTPException` en los FBs** (DA-005.3): los FBs son transport-agnostic. Las excepciones de dominio propagan tal cual; el wrapper `tick()` de la base las captura y pone el FB en `n_error`. El router es el responsable de mapear a HTTP.
4. **Tests en `tests/areas/alimentacion/functions/`** (DA-005.4): 1 test por FB, mirroring del source (regla del operario). El test del router va en `tests/test_router_plc.py` (raíz, convención de routers genéricos).
5. **Wiring de `app.py` diferido** (DA-005.5): `core/web/app.py` NO se modifica durante Fase 2 (regla "nada de main cambia sin pedir"). El wiring (crear `Engine`, registrar los 8 FBs, montar el router `plc_router`) se hace al final de Fase 3, no al final de Fase 2. Esto permite terminar Fase 3 con TODOS los DBs y TODOS los FBs activos de una sola vez, no a medias.

### DA-006 (2026-09-10, operario) — DBs y FBs coexisten durante Fase 2 y Fase 3

- **Contexto**: en el plan original, los use cases se eliminan en Fase 4 (Paso 4.0.1). Durante Fase 2 y Fase 3, los use cases y los FBs coexisten. Los routers pueden llamar a uno u otro durante la transición.
- **Implicación**: el orden es `Fase 2 (migrar lógica) → Fase 3 (introducir DBs) → Fase 4 (borrar use cases)`. Los use cases no se borran en Fase 2, solo se FASE 4. Hasta entonces, son el "fallback" si un FB falla.

---

## Cierre del refactor

Cuando todos los ~78 pasos estén hechos y validados:
- 1 EventSource por sesión, 0 polling.
- 1 archivo de log (`zc.log`). ✅ HECHO (DA-013, 3 commits: `064f153`, `62ae0db`, `2279887`).
- Todos los `use_case.py` migrados a `function_*.py` con `nStep`.
- `ProgressTracker` legacy reemplazado por `ProgressBar` per-instance en cada FB. ✅ Coexisten durante la migración (Feature 2 + DA-014).
- `store.js` refactorizado in-place (sigue siendo `reactive`, alimentado por SSE).
- **Arquitectura OB1**: single-threaded cyclic main loop en hilo principal + Flask sync en hilo secundario + TIA wrapper directo sin subproceso. Sin asyncio, sin uvicorn, sin FastAPI, sin worker subprocess.
- Tests pasan (sin `pytest-asyncio` en estos paths).
- `.exe` rebuildeado y validado contra TIA real.
- Documentación actualizada (`.clinerules`, `AGENTS.md`, `README.md`).
- **La UI visual no ha cambiado en ningún momento** (Vue 3 SPA, mismo frontend).

### DA-007 (2026-09-11, operario + mavis) — Orden de cierre del refactor (Opción A, revisado tras DA-011, DA-012 v2 y DA-014)

Aketza eligió **Opción A: Wiring → 3.3.3.x → 3.3.2 → Fase 4 (OB1) → demo final**. Razón: tener demo end-to-end contra TIA real antes de Fase 4 (que es destructiva). Si algo del wiring falla, lo arreglamos antes de borrar legacy.

**Orden exacto (revisado 2026-09-11 tras descubrimiento de DA-011, DA-012 v2 con keepalive, DA-013 y DA-014 OB1)**:
1. **DA-005.5** — Wiring de `app.py` (1 commit). Crea el `Engine`, registra los 7 FBs, monta el `plc_router`. Activa el refactor end-to-end. ✅ HECHO (`3a882a0`).
2. **DA-011** — Fix snapshot inicial SSE (1 commit, ~40 líneas, 3 archivos). `Engine.snapshot()` + `sse_router` modificado + 1 test. ✅ HECHO (`e70c560`).
3. **DA-012** — Fix SSE 0 bytes con TIA real. **Causa real** (quirk uvicorn+Proactor+subprocess PIPE) documentada en DA-014. **Fix aplicado**: keepalive SSE cada 15s (`7b5fd01`, +14 líneas en `core/sse/stream.py`). Historia completa: `e07c33a` (DEVNULL, revertido por `83cf920`) → `9d6c208` (ZC_DEBUG=1 logging) → `7b5fd01` (keepalive, vigente). ✅ HECHO.
4. **Demo contra TIA real** (S7-1500 del operario). Valida el `attach_portal`, el `engine.tick`, el SSE de los `fb_changed`, el snapshot inicial con los 7 FBs, y los keepalives cada 15s.
5. **3.3.3.x** — Catálogo por SSE (3 commits, ~65 líneas). Backend incluye el catálogo en el snapshot SSE. HMI lo consume. **Desbloquea 3.3.2**.
6. **3.3.2** — Eliminar `loadCatalog` (1 commit, ~-15 líneas). Dead code una vez el catálogo llega por SSE.
7. **DA-013** — Log unificado `zc.log` ✅ HECHO (`064f153`, `62ae0db`, `2279887`). Ver detalles en sección DA-013.
8. **Feature 2 — `ProgressBar` per-instance** (3 commits planeados, ~280 líneas; A ya creado sin commit). Pieza nueva pedida por el operario el 2026-09-11: cada FB crea su propio `ProgressBar` en `_start_locked` (no Faceplate, no Singleton); publica al `EventBus` para SSE; shape compatible con `ProgressIndicator.vue` (frontend sin cambios). Coexiste con `ProgressTracker` legacy hasta Fase 4.
   - **A — `core/application/progress_bar.py`** (~280 líneas, YA creado, sin commit). Clase `ProgressBar` con `ProgressBarStage`, métodos `start`/`advance`/`complete`/`error`/`attach_to_bus`/`to_dict`. Idempotente, sin dependencias.
   - **B — `core/plc/engine.py` + integración con `progress_bar.py`** (~50 líneas). Engine tiene `_active_progress_bars: dict[str, ProgressBar]` + `register_progress_bar(pb)`/`unregister_progress_bar(pb)`. `Engine.snapshot()` incluye `"progress_bars": [...]` con los bars activos.
   - **C — Ejemplo de uso en `function_SubirExcel.py`** (~30 líneas). El FB crea un `ProgressBar` en `_start_locked`, llama `attach_to_bus(self._engine._event_bus)`, llama `advance(stage_id, detail=...)` en cada sub-etapa, `complete()` o `error(msg)` al final. **No reemplaza** el `ProgressTracker` legacy que ya usa; es ejemplo de adopción.
9. **DA-014 — Fase 4 Refactor OB1** (16 sub-pasos, ver abajo). Spike (4.0.1) valida approach antes de tocar producción. Si valida, se procede 4.1-4.9 incrementalmente. Si NO valida, se aborta y Fase 4 vuelve al plan original de "limpieza" (borrar use cases, domains, etc.).
10. **Demo final** contra TIA real.
11. **Rebuild del `.exe`** con PyInstaller (adaptado para Flask + threading si OB1 llega al 4.9.2).

**Total commits pendientes**: ~24 (Feature 2 × 3 + 3.3.3.x × 3 + 3.3.2 + DA-014 Fase 4 OB1 × 16). DA-013 ya está hecho y descontado. Sin contar demo + rebuild que no son commits.

**Nota sobre DA-014**: el spike 4.0.1 es **validación previa obligatoria**. Si el spike falla, no se arranca ningún sub-paso de Fase 4. Se vuelve al plan original de limpieza (4.0.x borrado de carpetas) y se documenta el motivo del fallo en DA-014 (post-mortem).

### DA-008 (2026-09-10, operario) — `plc_router` se monta en `create_app`, NO en `register`

- **Contexto**: el plan original ponía `app.include_router(plc_router)` dentro de la función `register(engine, app)` del área. Aketza descubrió un bug: Starlette matchea rutas en orden de inserción, y `app.mount("/", NoCacheStaticFiles(..., html=True))` es un catch-all. Si el router se añade en el lifespan (después del mount), el mount intercepta las requests y devuelve 404.
- **Decisión**: el `plc_router` se monta en `create_app`, entre los routers del área y los mounts (es 1 línea, justo antes del `app.mount("/static/areas", ...)`). El `register` del área solo crea los 7 FBs y los registra en el Engine.
- **Influencia**: separa responsabilidades. `create_app` cablea el shell (routers + mounts); `register` cablea el runtime (engine + FBs). El orden de inserción en `create_app` importa: routers antes de mounts.
- **Corrección de conteo**: el plan decía "8 FBs" en algunos sitios. El número correcto es **7** (SubirExcel, ScanPlcBlocks, GenerarPreview, SincronizarDispositivos, SincronizarDispComentarios, SincronizarProcesosComentarios, DiffConstants). Aketza lo verificó con `grep ^class Function`.

### DA-009 (2026-09-10, operario) — Defensivos en el lifespan con `getattr`

- **Contexto**: el bloque del Engine en el lifespan usa `getattr(app.state, "event_bus", None)` y `getattr(app.state, "engine", None)` para no romper el test preexistente `test_lifespan_no_falla_si_gateway_no_esta_en_app_state` (que crea un `FastAPI()` directo sin pasar por `create_app`).
- **Decisión**: defensivo con `getattr(..., None)`. Consistencia con el patrón que ya existía con `gateway` en el mismo lifespan.
- **Influencia**: 0 scope creep. Es consistencia con el código preexistente.

### DA-010 (2026-09-10, operario) — Inconsistencia de paths entre `sse_router` y `plc_router`

- **Contexto**: durante la demo contra TIA real, Aketza intentó `curl -N /api/v1/plc/events` esperando el SSE del Engine. Dio 404 porque el path correcto es `/api/v1/stream` (sin `plc`). El `sse_router` está en `app.py:273` (`app.include_router(sse_router)`), con `prefix="/api/v1"` y `@router.get("/stream")` en `core/sse/stream.py:42-45`.
- **Decisión**: NO mover el path. La separación es coherente:
  - `/api/v1/stream` (genérico, Fase 1) — estado completo del PLC: `tia_state`, `worker_alive`, `project_name`, `plcs`, `logs`, `progress`, `fb_changed`. No es específico de un área.
  - `/api/v1/plc/fb/{name}/...` (específico, Fase 2) — FBs del Engine, específicos del área de alimentación.
- **Influencia**: 0 código. Documentar para que el siguiente agente o el operario no se confunda con el path.
- **Acción adicional**: añadir un test al wiring (DA-005.5) que verifique que `GET /api/v1/stream` emite el snapshot SSE. El test actual solo verifica `plc_router`, no `sse_router`.

### DA-011 (2026-09-10, mavis) — SSE snapshot inicial vacío: bug descubierto en demo

- **Contexto**: durante la demo contra TIA real posterior a DA-005.5, Aketza hizo `curl -N http://127.0.0.1:8000/api/v1/stream` y el stream se quedó colgado sin emitir contenido visible. El `LogBuffer`, `ProgressTracker` y gateway publican eventos al `EventBus` (1.1.1-1.1.4), pero el `Engine` (Fase 2) está vivo y los 7 FBs registrados (DA-005.5). El snapshot inicial (`_SNAPSHOT_EVENT` en `core/sse/stream.py:22`) tiene `"dbs": {}, "fbs": {}` hardcodeado, vacío.
- **Causa raíz**: Fase 1 (`1.0.3-1.0.4`) emitió un snapshot vacío como placeholder. Fase 2 introdujo el `Engine` con `fb_changed` (eventos, no snapshot). Fase 3 introdujo los DBs sin exponerlos al SSE. Nunca se cableó el `Engine.snapshot()` que rellene el placeholder con el estado real.
- **Síntoma observable**: `curl -N /api/v1/stream` emite 1 línea `data: {"type":"snapshot","dbs":{},"fbs":{}}` y se queda esperando `await queue.get()`. Como los FBs arrancan en `n_idle` y el `LogBuffer` no se toca si nadie loguea, el cliente ve un snapshot inútil y ningún evento siguiente.
- **Fix** (1 commit, 3 archivos, ~40 líneas):
  1. `core/plc/engine.py`: añadir `def snapshot(self) -> dict` que devuelve `{"dbs": {}, "fbs": {name: {"nStep": fb.nStep, "error_msg": fb.error_msg} for name, fb in self._fbs.items()}}` (~15 líneas, con docstring).
  2. `core/sse/stream.py`: cambiar `_SNAPSHOT_EVENT` por una función `_build_snapshot(engine)` que el `sse_router` invoca leyendo `request.app.state.engine`. Si el engine no existe (defensivo, tests sin lifespan), snapshot vacío. (~5 líneas).
  3. `tests/core/test_sse_snapshot.py` (NUEVO, ~20 líneas): mockea `Engine` con `MagicMock`, verifica que `_build_snapshot` devuelve el shape esperado.
- **Verificación**: `curl -N /api/v1/stream` muestra `data: {"type":"snapshot","dbs":{},"fbs":{"SubirExcel":{"nStep":0,...},...}}` con los 7 FBs listados.
- **Riesgo**: bajo. Es un cambio aditivo en el snapshot. Los eventos `fb_changed` y los hooks de log/progress/tia siguen igual. Los tests que ya pasan (Fase 1 + Fase 2 + Fase 3) siguen pasando.
- **Influencia en el plan**: 3.3.3.x (catálogo SSE) depende de DA-011 (sin snapshot inicial, no hay dónde meter el catálogo). DA-007 refleja el orden nuevo.

### DA-012 (2026-09-11, mavis + operario) — SSE 0 bytes con TIA real: causa real y fix definitivo (workaround keepalive)

> **Estado**: ✅ Fix aplicado (`7b5fd01`). Causa raíz arquitectónica documentada en **DA-014 (Refactor OB1)**.

- **Contexto**: tras DA-011 (snapshot inicial), la demo contra TIA real seguía colgada: `curl -N /api/v1/stream` retornaba 0 bytes durante 28s+. El server arrancaba OK (`Application startup complete` salía), el log de uvicorn mostraba `GET /api/v1/stream 200 OK` para los requests, pero el cliente no recibía ni un byte (ni headers ni body). El bug se reproducía en producción con TIA real pero NO en tests con gateway mockeado.
- **Causa raíz** (confirmada con test quirúrgico en mi workspace):
  - En `core/infrastructure/gateway.py:670` (función `_start_persistent_worker`), el subproceso worker se lanza con `stderr=asyncio.subprocess.PIPE`. Esto hace que `stderr` se herede del subproceso al proceso principal (vía el PIPE).
  - El worker escribe logs de timing a `sys.stderr` (línea 1102: `sys.stderr.write(f"[PERSISTENT WORKER TIMING] command={command!r} dispatch_total_ms=...")`).
  - El `reader_task` (línea 853, `_read_worker_stdout_forever`) SOLO lee `stdout`, no `stderr`. Por tanto, el buffer de `stderr` del subproceso se llena, el worker se bloquea en el `write`, y el event loop de asyncio (compartido con uvicorn) queda esperando.
  - Resultado: uvicorn acepta la conexión y entra al handler `get_stream` (que retorna 200), pero el generator `_stream(bus, engine)` no puede ejecutarse porque el event loop está bloqueado. El cliente nunca recibe bytes.
- **Verificación** (test hecho en mi workspace el 2026-09-10 23:58):
  - Con `run_app.bat` (gateway real) → socket raw: 0 bytes, timeout.
  - Con `_run_web_mode_async` y gateway mockeado (`start=fake_start`) → socket raw: 683 bytes con snapshot. ✅
  - Con `_run_web_mode_async` y gateway real PERO `start` parcheado para crear el subproceso con `stderr=asyncio.subprocess.DEVNULL` y `gateway._reader_task = None` → socket raw: 683 bytes con snapshot. ✅
  - Conclusión: el subproceso SÍ bloquea, y basta con redirigir `stderr` a `DEVNULL` y/o no crear la `reader_task` para que el event loop respire. Pero la `reader_task` es necesaria (lee las respuestas JSON del worker); lo que sobra es el PIPE de `stderr`.
- **Fix previsto** (1 commit, 1 archivo, 1-2 líneas): en `core/infrastructure/gateway.py:670`, cambiar `stderr=asyncio.subprocess.PIPE` por `stderr=asyncio.subprocess.DEVNULL`. Los logs de timing del worker se pierden (no se ven en la consola del operario), pero el subproceso ya no bloquea el event loop. Si se quiere preservar la observabilidad, alternativa B: añadir un `reader_task` paralelo que lea `stderr` y lo loggee con `logging.warning`. Pero eso añade 1 task asyncio y ~10 líneas; la opción A (DEVNULL) es más simple y suficiente para DA-012.
- **Tests del fix** (NUEVOS, ~20 líneas en `tests/test_persistent_worker_subprocess_real.py`):
  1. `test_start_persistent_worker_no_hereda_stderr_al_proceso_principal`: verifica que tras `gateway.start()`, `proc.stderr` es `None` o no es un PIPE heredado. Si el subproceso escribe a `sys.stderr` y el proceso principal lo hereda, este test falla con un mensaje claro.
  2. `test_sse_no_queda_bloqueado_con_worker_persistente_vivo`: arranca el server con `_run_web_mode_async` y un gateway con `persistent=True` (subproceso real), hace un GET al SSE con timeout 5s, verifica que recibe el snapshot. Sin este fix, el test da timeout; con el fix, recibe los bytes. Marcado `@pytest.mark.worker_e2e` (slow, skip si no hay TIA real).
- **Cuándo**: ANTES de 3.3.3.x. Sin este fix, la demo SSE contra TIA real no funciona (Aketza lo bloqueó en cuanto intentó `curl -N` post-DA-011). Es 1 commit de 1 línea + 1 test.
- **Influencia en el plan**: DA-007 refleja el orden nuevo (DA-012 antes de 3.3.3.x).

#### DA-012 — Corrección post-mortem (2026-09-11, mavis)

> El contenido de arriba documenta el **diagnóstico inicial** (fallido). La causa real, descubierta con `ZC_DEBUG=1`, está documentada en **DA-014** (causa arquitectónica) y el fix definitivo está en commit `7b5fd01`. El plan conserva esta sección como registro del journey diagnóstico.

- **Por qué el diagnóstico inicial era incorrecto**: el subproceso SÍ escribe a `sys.stderr` (línea 1102 de gateway.py con `[PERSISTENT WORKER TIMING]`), pero **no llena el buffer** — los logs siguen apareciendo en consola después de revertir `stderr=DEVNULL`. El síntoma real (cliente recibe 0 bytes, server loguea 200 OK) no era por buffer lleno, sino por un quirk diferente del transporte HTTP.

- **Diagnóstico correcto (vía `ZC_DEBUG=1`, commit `9d6c208`)**: el log capturado por el operario el 2026-09-11 18:22 mostró que `core/sse/stream.py:95` emitía `_stream: PRIMER yield snapshot enviado al cliente (post-yield)` — el snapshot SÍ se construye y se yield. El cliente no recibe nada porque uvicorn + ProactorEventLoop + 3 PIPE handles del subproceso retienen el primer chunk del streaming response en su buffer 10-30s antes de flushear al socket TCP. Mock gateway no tiene subprocess → quirk no se dispara → test pasa.

- **Fix real aplicado (commit `7b5fd01`, +14 líneas en `core/sse/stream.py`)**: patrón estándar SSE production: `await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)` con `yield b": keepalive\n\n"` en `TimeoutError`. Comentarios SSE fuerzan al transport a flushear al socket TCP, desbloqueando el buffer de uvicorn. Override operativo: `ZC_SSE_KEEPALIVE_SECONDS` (default 15.0).

- **Historia completa del fix (3 commits, todos commiteados en orden)**:
  - `e07c33a` — `stderr=DEVNULL` (hipótesis inicial, **REVERTIDO** por `83cf920`).
  - `9d6c208` — `ZC_DEBUG=1` toggle + logging exhaustivo en 7 archivos (necesario para diagnosticar).
  - `7b5fd01` — SSE keepalive cada 15s (**FIX REAL**, vigente).

- **Limitación reconocida**: el keepalive es workaround defensivo (parche estándar de la industria). La causa arquitectónica (subproceso con PIPE handles en Windows + Proactor) queda sin resolver hasta **DA-014 (Refactor OB1)**.

- **Tests vigentes** (commit `e07c33a` revertido conservó el archivo original con el E2E test preexistente; los 2 tests nuevos de DA-012 fueron revertidos con el commit):
  - `tests/test_persistent_worker_subprocess_real.py::test_worker_persistente_emite_ready_idle_y_responde_ping` (preservado).
  - Los 2 tests DA-012 originales (`test_start_persistent_worker_no_hereda_stderr_al_proceso_principal`, `test_sse_no_queda_bloqueado_con_worker_persistente_vivo`) NO se re-aplicaron porque el fix real es diferente (keepalive, no DEVNULL). Si se necesitan, se crean tests específicos para keepalive en otro paso.

- **Verificación final**: 1151 pass / 1 fail preexistente (logging flaky) / 0 regresiones nuevas.

### DA-013 (2026-09-10 → 2026-09-11, mavis + operario) — Log unificado `zc.log` ✅ APLICADO (con desvíos)

> **Estado**: ✅ HECHO en 3 commits (`064f153`, `62ae0db`, `2279887`). Nombre y ubicación distintos a los previstos originalmente; detalles abajo.

- **Contexto**: el plan original proponía "1 archivo de log (`zc.log`)" en el cierre. En la realidad pre-DA-013, `logs/worker_ot.log` (414 KB) existía pero `zc.log` no. Cada componente (`main.py`, `main_tray.py`, worker TIA) configuraba su logger de forma independiente con `basicConfig` ad-hoc.
- **Síntoma observable**: los logs estaban dispersos (consola de uvicorn + `logs/worker_ot.log` + logs de pystray). Tras DA-012 (quirk de uvicorn+Proactor), la necesidad de un log unificado se volvió más acuciante.
- **Implementación real** (3 commits en lugar del 1 previsto, por "delegar en pasos pequeños"):
  - `064f153` — `core/application/log_paths.py` (NUEVO, +153/-17 líneas): `setup_logging(mode: str)` idempotente. FileHandler único a `<log_dir>/zc.log` (append), formato `%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s] %(message)s`. Override `ZC_LOG_DIR`, fallback a `<exe_dir>/logs` (frozen) o `<cwd>/logs` (dev). Respeta `ZC_DEBUG=1` para subir a DEBUG.
  - `62ae0db` — `main.py` (+9 líneas): `setup_logging("web")` / `setup_logging("mcp")` antes de imports pesados en `--web` y `--mcp`. Logger names `zc.web` / `zc.mcp`.
  - `2279887` — `main_tray.py` (+12/-95 líneas): reemplazado `basicConfig` propio por `setup_logging("tray")`, eliminada la función `_setup_logging_redirect`. Logger name `zc.tray`.
- **Desvíos del plan original**:
  - **3 commits en lugar de 1** (regla "delegar en pasos pequeños" del operario).
  - **Ruta `core/application/` en lugar de `core/infrastructure/`** (sigue convención del operario: código de aplicación/setup vive en `application/`).
  - **Invocado desde `main.py` y `main_tray.py` en lugar de `_tia_lifespan`**. Razón: `setup_logging()` debe correr ANTES de imports pesados (uvicorn, pystray, etc.) para capturar sus logs. El lifespan arranca tarde.
  - **Cubre `--web`, `--mcp`, `tray`** (3 modos de entrada). El worker TIA ya loguea a `zc.log` por append (sin cambios — usa `logging` stdlib).
  - **Nombre `setup_logging(mode)` en lugar de `setup_root_logging()`** (más explícito: mode-aware).
- **Verificación**: 1151 pass / 1 fail preexistente / 0 regresiones. `python -c "from core.application.log_paths import setup_logging; setup_logging('test')"` verificado: idempotente, append mode, formato correcto, ZC_DEBUG=1 → DEBUG.
- **Pendiente para Fase 4 OB1**: el formato y el file handler se mantienen; solo cambia el bootstrap (sin `_tia_lifespan`, lo llama `main.py` directo).

### DA-014 (2026-09-11, operario + mavis) — Refactor OB1: arquitectura single-threaded cyclic

> **Estado**: 🟡 Decisión aprobada en conversación. Detalles de implementación (sub-pasos específicos, line counts, estrategia de tests) se afinan durante el **Paso 4.0.1 (Spike)**. NO se arranca código hasta validar el spike con el operario.

- **Contexto**: tras cerrar DA-012 con workaround keepalive (`7b5fd01`), la causa arquitectónica queda sin resolver: `asyncio + uvicorn + FastAPI + asyncio.subprocess` introduce complejidad que paga el operario sin retorno operacional. El operario preguntó explícitamente: *"puede simplificarse mas? sin tantos subprocesos y tantas cosas? y hacer la app como si fuera ciclica?"* Esto encaja con su preferencia durable de modelo mental PLC (ver memoria de Aketza, "modelo mental PLC" 2026-09-09 + "OB1 single-threaded cyclic" 2026-09-11).

- **Decisión arquitectónica**:
  - **Eliminar** el subproceso worker (`worker_tia.py`, ~2000 líneas) y el `gateway.py` (~700 líneas) que lo orquesta.
  - **Reemplazar** `asyncio` por un loop OB1 single-threaded (PLC-style) en el hilo principal.
  - **Mover** Flask (sync) a un hilo secundario. Comunicación entre hilos vía `queue.Queue` (thread-safe, stdlib).
  - El TIA wrapper se llama **directamente desde el hilo principal** (mismo proceso, sin IPC, sin PIPE). El único motivo del subproceso era evitar problemas de thread-safety con el RCW de .NET, y eso se resuelve con single-threaded: un solo hilo llama al wrapper, no hay race.
  - **Reemplazar** FastAPI por Flask. Mismas rutas, mismo frontend, cero cambios en la UI Vue 3.

- **Trade-offs aceptados**:
  - **Perdido**: paralelismo I/O real. Flask dev server single-threaded = un request HTTP a la vez.
  - **Ganado**: 80% menos código (`gateway.py` 700 → `tia_client.py` ~150 líneas; `worker_tia.py` 2000 → eliminado). Sin subproceso. Sin asyncio. Sin quirks de Proactor. Sin keepalives SSE. Sin reader_task, heartbeat_task, _drain_pending_responses.

- **Estructura del refactor (10 sub-pasos en Fase 4 nueva)**: ver Fase 4 OB1 abajo. Cada sub-paso = 1 commit, 1-2 archivos, <200 líneas, commiteable solo. Regla del plan "nada de main cambia sin pedir" se mantiene: cada paso se valida con el operario antes del siguiente.

- **Cuándo**: DESPUÉS de 3.3.2 + DA-013. La nueva "Fase 4 — Refactor OB1" reemplaza la "Fase 4 — Limpieza" original (los pasos de limpieza legacy se integran como 4.7-4.9 dentro de la nueva fase). Ver DA-007 actualizado.

- **Influencia en el plan**: la Fase 4 se renombra a "Refactor OB1" con sub-pasos 4.0-4.9. DA-007 inserta DA-014 antes del rebuild. Resumen total añade ~10 commits OB1.

- **Detalle finos abiertos** (se deciden durante el spike 4.0.1):
  - ¿Flask con `werkzeug.serving.make_server()` o `gunicorn` para frozen?
  - ¿Patrón de `concurrent.futures.Future` para HTTP requests o `queue.Queue` simple?
  - ¿Engine `run_cycle()` separa "process commands" de "tick FBs" o los entrelaza?
  - ¿Cómo se migran los tests `pytest-asyncio` a sync?

---

## Cierre del refactor (legacy, ver DA-007 para el orden actualizado)
