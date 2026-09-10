# Plan greenfield: arquitectura PLC-style (IEC 61131-3)

> **Estado:** propuesta, pendiente de aprobación.
> **Tipo:** greenfield en **rama** del repo actual (`greenfield/iec-61131-3`), no repo nuevo. El repo actual `zc-automation-suite` se mantiene operativo en `main` hasta Fase 4 (ver §4 y §7).
> **Operario:** Aketza
> **HEAD base:** el actual de `main` antes del wipe.
> **Auditorías previas (referencia intelectual):** `_plan/14_post_worker_persistent_audit.md`, `_plan/17_frontend_simplification_audit.md`.

---

## §0. Principio rector: greenfield de código, no de conocimiento

Empezar de cero en el código no significa empezar de cero en el dominio. El repo actual costó muchas rondas de auditoría contra la API real de TIA Portal y contra fallos reales en producción. Esa parte del trabajo **no se repite** — se traslada como conocimiento verificado, documentado aquí explícitamente para que nadie lo re-derive por las malas.

### 0.1 Conocimiento de la API de TIA Portal ya verificado contra el manual Openness (V1.2.1)

No volver a comprobar estas firmas desde cero — ya están confirmadas línea por línea contra el manual:

| Método | Firma verificada | Notas |
|---|---|---|
| `ts.attach_portal(portal_mode)` | Requiere una instancia **ya en ejecución**. No lanza TIA Portal. | §2.4.2 |
| `ts.open_portal(portal_mode, version=None)` | Lanza una instancia **nueva**. Hay que llamar a `portal.open_project(project_file_path)` después para abrir el proyecto. | §2.4.1 |
| `portal.detach()` | Libera el RCW. No cierra TIA Portal. | §2.5.16 |
| `project.start_transaction(undo_text, dialog_text)` | Ambos argumentos obligatorios. | §2.37.27 |
| `project.end_transaction(rollback: bool)` | — | §2.37.28 |
| `project.update_transaction(dialog_text)` | Sirve para dar feedback en vivo durante un lote largo. Existe y no se usó en el repo actual — aprovecharlo desde el principio esta vez. | §2.37.29 |
| `table.get_user_constants()` / `table.get_plc_tags()` | Colecciones distintas dentro de una `PlcTagTable`. | §2.28.4/5 |
| `obj.get_property(name=...)` / `obj.set_property(name=..., value=...)` | Siempre por keyword — el repo actual tuvo una función que rompía esta convención por usar posicionales; no repetir eso. | §2.27.2/6 |
| Carga del `.pyd` en frozen (PyInstaller) | Inyección manual en `sys.path` + `os.environ["PATH"]` + `os.add_dll_directory` desde `sys._MEIPASS`, **nunca** `importlib.util` para la carga en tiempo de ejecución. | Empírico, confirmado en producción |

### 0.2 Decisiones arquitectónicas ya pagadas — no relitigar

- **Los dispositivos se modelan como `PlcUserConstant`, no como `PlcTag`.** El repo actual empezó modelándolos como `PlcTag` con dirección física, chocó con incertidumbre real sobre el anidamiento `AttributeList` del XML exportado, y pivotó a constantes — mismo primitivo que ya funciona de forma fiable para N_MAX. Empezar directamente desde ahí.
- **Aislamiento de proceso: solo un módulo importa `siemens_tia_scripting`, y de forma perezosa (dentro de una función, nunca a nivel de módulo).** El proceso IT (FastAPI) no lo toca nunca.
- **Conexión persistente, no proceso-por-llamada.** Un único worker en subproceso, vivo durante toda la sesión, con `attach`/`detach` explícitos controlados por el operario. Proceso-por-llamada (relanzar el intérprete + reinicializar el CLR en cada operación) se probó primero y se descartó por coste de latencia real.
- **El acceso al worker se serializa con un lock.** El worker habla por un único stdin/stdout; dos comandos concurrentes corromperían el stream. Esta vez el lock se diseña como parte del contrato desde el primer commit, no se añade después de encontrar el bug.
- **Configuración multi-departamento dirigida por datos, no por código.** Un `config.json` con la forma `departments.<área>.dispositivos.<tipo> → {db_name, tag_table, config_constant}` permite añadir un departamento sin tocar el motor genérico.
- **Excel con cabeceras tolerantes a acentos/mayúsculas** vía `unicodedata.normalize("NFKD", ...)`, no comparación de string literal.
- **Tailwind + daisyUI compilados una vez offline** (`tailwind-cli-extra`, binario standalone sin Node/npm) a un `.css` estático — la máquina de destino puede no tener internet.
- **Tema claro industrial**: fondo blanco/gris, texto oscuro, acento único `rgb(0, 52, 102)`. Token semánticos (`--color-surface`, `--color-ink`, `--color-accent`), nunca nombres de la paleta de Tailwind reutilizados con otro significado.
- **El operario piensa en `nStep`/SFC, no en promesas encadenadas.** SSE con estado explícito por Function Block, no polling. Esta era la conclusión del plan de refactor anterior — aquí no es una capa añadida encima de lo existente, es la arquitectura de partida.

### 0.3 Lo que sí se descarta de verdad

- La forma actual de `core/infrastructure/gateway.py`, `core/application/use_cases/*`, `store.js` y el modelo de polling — se reescriben desde cero, informados por el punto 0.2, no adaptados.
- La suite de tests actual no se porta literal — se reescribe contra la arquitectura nueva. Pero sirve como **checklist de casos a cubrir** (qué escenarios de reconexión, qué race conditions, qué errores de TIA ya se sabe que hay que probar) — no hay que redescubrir qué probar, solo reescribir cómo se prueba. Se mantiene viva en `zc-automation-suite` (rama `main`) como documentación de dominio hasta Fase 4, no se borra antes.

### 0.4 Lecciones aprendidas de auditorías previas (NO relitigar)

Tres bugs críticos del audit `_plan/14_post_worker_persistent_audit.md` que ya costaron iteraciones. Documentados aquí para que el greenfield no los repita:

- **X1 — Consumir TODOS los campos que el backend expone, no solo los obvios.** En el bug original, `GET /api/v1/tia/connection` devolvía `worker_alive` y `project_changed` pero el `Object.assign` del frontend solo escribía `state, project, plcs, last_ping_ok_unix, last_error`. Resultado: el `WorkerStatusIndicator` del topbar NUNCA se ponía verde en producción. **Lección:** el `Engine._apply_snapshot` debe mergear TODOS los campos estables de la respuesta, con merge defensivo (conservar valor previo si el campo falta, no pisar con `false` por defecto). Cubierto en §3 con un test explícito.

- **X2 — El shutdown handler del worker persistente es obligatorio.** Sin él, al pulsar "Detener web" el subproceso queda zombi con `siemens_tia_scripting.pyd` cargado (~200 MB) hasta que se cierra TIA o se mata el proceso a mano. **Lección:** `WorkerBridge` debe tener un método `shutdown()` que se llame desde el `lifespan` de FastAPI al apagado, que envíe `detach_portal` + cierre del subproceso. Cubierto en §3 con un test explícito (el shutdown libera el .pyd, no queda zombi).

- **X3 — El lock del worker no protege `reconnect()`.** Doble clic rápido en Conectar + Desconectar puede dejar procs huérfanos si el operario hace doble-click rápido. **Lección:** el lock debe cubrir TODA la operación de cambio de estado (connect, disconnect, reconnect), no solo el envío. `WorkerBridge` debe tener double-checked locking desde el primer commit, no añadirlo después de encontrar el bug. Cubierto en §3 con un test explícito.

---

## §1. Arquitectura objetivo

```
┌──────────────────────────────────────────────────────────┐
│  SPA Vue 3 (sin build step)                               │
│  usePlc(): 1 EventSource, DBs/FBs reactivos, startFb()    │
└───────────────────────────┬────────────────────────────────┘
                             │ SSE (push) + POST /fb/{name}/start
┌───────────────────────────▼────────────────────────────────┐
│  FastAPI — capa IT                                          │
│  Engine: registro de FBs/DBs, loop 100ms, bus de eventos    │
│  Routers genéricos (core) + routers específicos (áreas)     │
└───────────────────────────┬────────────────────────────────┘
                             │ WorkerBridge (lock-protegido desde el diseño, con shutdown)
┌───────────────────────────▼────────────────────────────────┐
│  Worker persistente — subproceso aislado                    │
│  Único punto de import de siemens_tia_scripting              │
└───────────────────────────┬────────────────────────────────┘
                             │ COM / .NET CLR
┌───────────────────────────▼────────────────────────────────┐
│  Siemens TIA Portal                                          │
└──────────────────────────────────────────────────────────┘
```

Diferencia clave con el plan de refactor anterior: ahí el Engine se montaba **encima** de un `gateway.py` ya existente cuya lógica de concurrencia había que preservar sin verla del todo. Aquí, `WorkerBridge` es la primera pieza que se diseña, con el lock, la reconexión y la heurística de desconexión como parte de su contrato desde el primer test, no como una capa de compatibilidad hacia algo heredado.

---

## §2. Estructura de carpetas (repo actual, rama greenfield/iec-61131-3, todo borrado)

```
zc-automation-suite/                          ← repo único, dos ramas
├── main                                       ← LEGACY operativo (no se toca)
│
└── greenfield/iec-61131-3                    ← esta rama: empieza vacía, se reconstruye
    ├── .clinerules                            # escrito ANTES del primer commit
    ├── AGENTS.md                              # idem
    ├── README.md                              # enlaza a _plan/14 y _plan/17 como referencia
    ├── pyproject.toml
    ├── requirements.txt
    ├── pytest.ini
    ├── ruff.toml
    ├── main_tray.py                           # único entry point
    ├── build_exe.py
    │
    ├── core/                                  # motor genérico — todo lo que TODAS las áreas necesitan
    │   ├── worker/
    │   │   ├── worker_tia.py                  # subproceso persistente, único import de siemens_tia_scripting
    │   │   └── worker_bridge.py               # fachada con lock, reconexión y shutdown
    │   ├── plc/
    │   │   └── plc.py                         # Engine + FB_Base + DB_EstadoConexion + FB_ConexionTIA, agrupado
    │   │                                       # (partir en engine.py/fb_base.py/db_estado_conexion.py si supera ~500 líneas)
    │   ├── config/
    │   │   ├── config_manager.py
    │   │   └── config.json
    │   ├── excel/
    │   │   └── excel_parser.py                # base genérica, normalización de cabeceras
    │   └── web/
    │       ├── app.py                         # composition root de FastAPI (incluye shutdown del worker)
    │       └── routers/
    │           ├── plc.py                     # POST /fb/{name}/start, GET /events — genérico
    │           ├── areas.py
    │           └── health.py
    │
    ├── areas/
    │   ├── _registry.py                        # descubrimiento de áreas (AreaSpec)
    │   └── alimentacion/
    │       ├── __init__.py                     # register(engine, app)
    │       ├── plc/
    │       │   ├── data.py                     # DBs específicas del área
    │       │   └── functions.py                # FBs específicos del área
    │       ├── domain/
    │       │   └── dispositivos.py             # dataclasses de dominio
    │       ├── excel/
    │       │   └── parser.py                   # mapeo Excel → dominio de esta área
    │       ├── routers.py
    │       └── frontend/
    │           ├── manifest.js
    │           └── components/                 # los 11 componentes existentes, clonados (ver Fase 3)
    │
    ├── interfaces/
    │   └── web_server/static/
    │       ├── index.html                      # shell mínimo
    │       ├── styles.css                      # compilado, commiteado
    │       ├── src/input.css                   # fuente Tailwind + daisyUI
    │       └── js/
    │           ├── main.js
    │           ├── composables/usePlc.js
    │           └── components/                 # shell: topbar, sidebar, consola de logs
    │
    └── tests/
        ├── core/
        └── areas/alimentacion/
```

---

## §3. Estrategia de tests (global, no por fase)

Tres capas, cada una con un propósito distinto — no se sustituyen entre sí:

- **Unit**: `WorkerBridge` mockeado, sin TIA real. Cubren la lógica de cada FB de forma aislada y rápida.
- **Integration**: `TestClient` de FastAPI + `Engine` real (worker todavía mockeado). Cubren routers, el ciclo de vida completo de un FB a través del Engine, y el bus SSE.
- **Smoke E2E**: contra un S7-1500 real. Uno por fase, no automatizado — es la validación de hardware que cierra cada fase (ver §4).

No se fija un porcentaje de cobertura como objetivo — un número alto con los casos que importan sin cubrir es peor que uno más bajo que sí los cubre. Lo que **tiene** que estar probado explícitamente, sin excepción, antes de cerrar Fase 1:

1. **El lock de `WorkerBridge` no es reentrante** — ninguna cadena de llamadas interna vuelve a cogerlo.
2. **Doble clic en "Conectar" no deja dos `attach` colgando** (double-checked locking).
3. **Dos suscriptores SSE reciben el mismo evento**; desconectar uno no afecta al otro.
4. **El Engine no tickea FBs en estado terminal** (`nStep == 0`, `n_done`, `n_error`).
5. **El shutdown handler del worker persistente existe y libera el `.pyd` de Siemens** (no queda zombi con ~200 MB). *(Lección X2, §0.4.)*
6. **Doble clic en Conectar + Desconectar no deja el worker en estado inconsistente** (race conditions en reconnect). *(Lección X3, §0.4.)*

La suite de tests del repo actual (630+ tests) no se porta literal — se reescribe contra la arquitectura nueva, pero se usa como checklist de qué escenarios de reconexión y errores de TIA ya se sabe que hay que cubrir. Se mantiene viva en la rama `main` de `zc-automation-suite` hasta Fase 4, no se borra antes.

---

## §4. Fases de construcción — walking skeleton primero, ampliar después

La regla: **nada se replica a una segunda área hasta que el patrón completo está demostrado una vez, de punta a punta, contra hardware real.**

Cada fase cierra con dos criterios, no solo uno: **validación técnica** (tests + hardware real) y **demo de 30 min al operario con confirmación explícita**. Si el operario dice "no es esto", se itera antes de avanzar a la siguiente fase — evita llegar a Fase 4 y descubrir que el rumbo se torció en Fase 1.

### Pre-Fase 0 — Crear la rama greenfield (15 min)

Antes de escribir la primera línea de código, crear la rama y dejarla en blanco.

```bash
cd "D:/Zeus Control/Proyectos/GitHub/zc-automation-suite"
git checkout -b greenfield/iec-61131-3
git rm -r .
git commit -m "wipe: punto de partida greenfield IEC 61131-3"
git push -u origin greenfield/iec-61131-3

# Verificar que main sigue intacta
git checkout main && pytest tests/ -v
git checkout greenfield/iec-61131-3
```

**Cierre:** `git log` en la rama muestra un solo commit (wipe). `git checkout main && pytest tests/ -v` sigue verde.

### Fase 0 — Esqueleto del repo (0.5 días)

- Estructura de carpetas vacía, `pyproject.toml`, `requirements.txt`, `pytest.ini`, `ruff.toml`.
- `.clinerules` y `AGENTS.md` escritos ya con la arquitectura objetivo del §1-§2 — así el primer commit ya tiene la referencia correcta.
- CI local mínimo: `pytest` corriendo (aunque sea sobre cero tests) y `ruff check` en verde.
- `README.md` inicial que enlaza a `_plan/14_post_worker_persistent_audit.md`, `_plan/17_frontend_simplification_audit.md` y este documento como referencia intelectual.

**Cierre:** `python -m pytest` no falla por ausencia de config, `ruff check .` limpio.

### Fase 0.5 — "Hola mundo" extremo a extremo, empaquetado (1 día)

Antes de invertir 3-4 días en el Engine, comprobar que la pieza de la que depende todo lo demás (SSE dentro de un `.exe` de PyInstaller, en el Windows real del operario) funciona. Si esto falla, falla todo lo que viene después — mejor enterarse en 1 día que al final de la Fase 1.

- `main_tray.py` arranca.
- FastAPI sirve `GET /api/v1/ping` y `GET /api/v1/events` (con `StreamingResponse` nativo, sin `sse-starlette`).
- `main.js` abre 1 `EventSource`, recibe `{ping: "pong"}`, lo pinta en pantalla.
- Empaquetar a `.exe` con PyInstaller.

**Cierre:** el `.exe` arranca, la conexión SSE aguanta más de 30 segundos sin cerrarse, sobrevive a un refresco de página. Si falla: evaluar `sse-starlette` como fallback antes de seguir a Fase 1, no después.

### Fase 1 — Worker + WorkerBridge + Engine mínimo (3-4 días)

El único objetivo: **conectar con TIA Portal real y listar sus PLCs, de punta a punta, con la disciplina de concurrencia ya incorporada.**

- `core/worker/worker_tia.py`: bucle persistente, arranca en `idle`, comandos `attach_portal`, `list_plcs`, `detach_portal`, `ping`. Carga perezosa del wrapper (§0.1).
- `core/worker/worker_bridge.py`: la fachada. **El lock se diseña aquí desde la primera línea** — método `_send()` privado que asume el lock cogido, con `assert self._lock.locked()` al principio (no solo un comentario). `connect()`/`disconnect()` con double-checked locking contra doble clic desde el primer test que se escribe. `shutdown()` que libera el `.pyd` (lección X2).
- `core/plc/plc.py`: Engine (tickea FBs activos cada 100ms, bus de eventos por `asyncio.Queue` por suscriptor), `FB_Base`, `DB_EstadoConexion`, `FB_ConexionTIA` (`10 conectar → 20 listar PLCs → 30 done → 99 error`).
- `core/web/routers/plc.py`: `POST /api/v1/plc/fb/{name}/start`, `GET /api/v1/plc/events` (SSE con snapshot inicial + stream).
- `core/web/app.py`: en el `lifespan` de FastAPI, llamar a `worker_bridge.shutdown()` al apagado (lección X2).

**Cierre técnico:**

- Los 6 tests obligatorios del §3 (incluyendo shutdown y race conditions en reconnect).
- `curl -N .../plc/events` mantiene la conexión y emite snapshot inicial.
- `curl -X POST .../plc/fb/ConexionTIA/start` contra un TIA Portal real abierto → `nStep` avanza `10 → 20 → 30`, la lista de PLCs es la real del proyecto abierto.
- Cerrar TIA Portal a media sesión y arrancar `ConexionTIA` de nuevo → error claro, no traceback.
- Dos conexiones `curl -N` simultáneas reciben los mismos eventos ante un mismo `start`; cerrar una no interrumpe la otra. El reconector automático de `EventSource` funciona tras matar el servidor y reiniciarlo.

**Cierre con el operario:** demo de 30 min — conectar, ver la lista de PLCs real, desconectar. Confirmación explícita antes de pasar a Fase 2.

### Fase 2 — Una sola área, un solo flujo vertical completo (4-5 días)

No "toda alimentación" — **un flujo, de Excel a PLC, completo.** El candidato natural es sincronización de dispositivos (§0.2).

- `areas/alimentacion/domain/dispositivos.py`: las dataclasses de dispositivo (tipos correctos desde el principio — campos tipo código como `str`, campos tipo contador como `int`).
- `areas/alimentacion/excel/parser.py`: lectura de Excel con normalización de cabecera (§0.2).
- `areas/alimentacion/plc/data.py` + `functions.py`: `FB_LeerExcel`, `FB_SincronizarDispositivos` con sus `nStep` propios.
- `config.json`: mapeo `alimentacion.dispositivos.<tipo> → {tabla, constante}` para los seis tipos, en formato de datos desde el primer commit.
- Tests unit con `WorkerBridge` mockeado (§3).

**Cierre técnico:** subir un Excel real, generar la previsión, aplicar el commit transaccional contra un S7-1500 real, confirmar en TIA Portal que los cambios son correctos y que un renombrado no rompe referencias cruzadas.

**Cierre con el operario:** demo de 30 min con su Excel real. Confirmación explícita.

### Fase 3 — Frontend real: clonar la UI actual, no rediseñarla (2-3 días)

El operario ya confirmó que la parte gráfica actual le gusta. Esta fase **no es un rediseño** — es cambiar la fuente de datos de los componentes existentes.

Los 11 componentes actuales (`Welcome`, `ShellTopbar`, `ShellSidebar`, `TiaConnectionIndicator`, `WorkerStatusIndicator`, `MainTabs`, `DispositivosPanel`, `ProcesosPanel`, `AreaLanding`, el `Sidebar` del área, `Procesos`) se copian tal cual al nuevo repo. Solo cambia:

- `import { store } from "/js/store.js"` → `import { usePlc } from "/js/composables/usePlc.js"`
- `store.tiaConnection.state` → `plc.DBs.estado_conexion.tia_state`
- Referencias a datos cacheados (`store.previewData` y equivalentes) → la DB del área correspondiente expuesta por `usePlc`.

Los 2-3 componentes que sí dependen de flujos multi-paso (`Dispositivos.js`, `ProcesosSyncView.js`) se migran de verdad al patrón `startFb` + `nStep`, no solo cambian el import — son los únicos con lógica real que reescribir en esta fase.

Errores estructurados desde el backend (`error_type` en el evento SSE), nunca `string.includes()` en el frontend para decidir comportamiento. Tema claro industrial (§0.2) desde el primer estilo que se escribe.

**Cierre técnico:** flujo completo end-to-end en el navegador contra hardware real — conectar, subir Excel, previsualizar, aplicar, ver el resultado — sin ningún `setInterval` en la consola de red del navegador. La UI se ve igual que la actual (no es una comparación subjetiva: mismos componentes, mismo `styles.css`).

**Cierre con el operario:** demo de 30 min. Si "se ve distinto" es la queja, es señal de que esta fase se salió de su alcance (clonar, no rediseñar) — revisar antes de seguir.

### Fase 4 — Ampliar: segundo flujo del mismo área (2-3 días)

Con el patrón demostrado una vez, replicarlo para "procesos" (sincronización de comentarios) debería ser mecánico: mismo `WorkerBridge`, mismo `Engine`, un `FB` nuevo, un panel nuevo.

**Validación explícita del patrón, no solo "funciona":** medir cuánto código nuevo hizo falta para el segundo FB frente al primero. Si el segundo FB necesitó más del 50% del código del primero (más allá de lo específico del dominio), el patrón de Fase 2-3 no quedó lo bastante genérico — parar y revisar antes de firmar esta fase como "patrón listo para réplica en otras áreas".

**Cierre técnico:** sync de comentarios de procesos funcionando contra hardware real, con la métrica de reutilización de código evaluada explícitamente.

**Cierre con el operario:** demo de 30 min de los dos flujos juntos (dispositivos + procesos). Confirmación explícita — este es el punto de paridad con el repo legacy en el área de alimentación.

### Fase 5 — Validación final y release (2-3 días)

- Demo end-to-end completa al operario: subir Excel, generar previsión, aplicar, sync comentarios, escanear bloques, conectar/desconectar — todo contra un S7-1500 real, en una sola sesión.
- Regresión: comparar explícitamente el comportamiento del nuevo repo contra el legacy en los flujos clave — mismos datos de entrada, mismo resultado esperado.
- Empaquetar a `.exe` con PyInstaller, validar que el binario arranca y todo funciona igual que en modo desarrollo.
- `README.md` y `AGENTS.md`: revisión final de que siguen siendo ciertos (se actualizaron en cada fase anterior, no de golpe aquí).
- Firma explícita del operario: "esto sustituye a la versión anterior". Solo entonces:
  - Merge de `greenfield/iec-61131-3` sobre `main` (squash-merge o rebase, decisión del operario).
  - La rama `main` (legacy operativo) se archiva como `legacy/2026` y se deja de usar.

### Fase 6+ (futuro, fuera de este plan)

Nuevas áreas/departamentos, con el patrón ya demostrado dos veces (alimentación: dispositivos + procesos) como plantilla.

---

## §5. Riesgos específicos de ir greenfield

- **Tiempo total mayor y "nada funciona hasta que algo funciona" durante más tiempo** que un refactor incremental. Se mitiga con la Fase 0.5 y la Fase 1 como hitos mínimos demostrables cuanto antes.
- **Riesgo de repetir errores ya resueltos si el §0 no se respeta de verdad.** Este documento existe precisamente para eso. Las 3 lecciones del §0.4 ya costaron iteraciones; releerlas antes de tocar código.
- **Mantener dos codebases vivas en paralelo (legacy en `main` + greenfield en la rama) hasta Fase 4 tiene coste de mantenimiento real** — si aparece un bug urgente en producción durante la construcción, hay que decidir si se arregla solo en el legacy (probable) o también se replica en la rama nueva. No es gratis, es el precio de que el operario no se quede sin herramienta.

---

## §6. Routing de trabajo por fase

Confirmado por el orquestador: los 4 agentes `tia-ot-worker`, `backend-api`, `frontend-spa`, `build-and-tests` están disponibles en el entorno de Aketza.

| Fase | Routing propuesto |
|---|---|
| Pre-Fase 0 + 0 + 0.5 | `build-and-tests`: estructura del repo, CI local, `.clinerules`/`AGENTS.md`, spike de empaquetado |
| 1 | `tia-ot-worker` (worker_tia.py, worker_bridge.py, app.py con shutdown) + `backend-api` (plc.py, routers, tests) |
| 2 | `backend-api` (functions.py del área, parser Excel, config.json) + `tia-ot-worker` (validación con S7-1500) |
| 3 | `frontend-spa` (composable, migración de los 11 componentes) + `tia-ot-worker` (validación HMI con S7-1500) |
| 4 | `backend-api` (segundo FB) + `frontend-spa` (segundo panel) |
| 5 | `build-and-tests` (PyInstaller, regresión) — demo y firma las llevas tú directamente con el operario |

---

## §7. Antes de escribir la primera línea

**Decisiones ya tomadas** (confirmadas en esta conversación):

1. **El greenfield vive en una rama del repo actual, no en un repo nuevo.** Rama elegida: `greenfield/iec-61131-3`. El legacy `zc-automation-suite` se mantiene operativo en `main` hasta Fase 4. Razón: el operario no se queda sin herramienta durante la construcción; la historia de git del legacy queda accesible vía `git checkout main`; no se duplican los `_plan/`, los tests, ni la config de CI. Implicación: cuando la rama mergea a `main` en Fase 5, la suite legacy se archiva como `legacy/2026` y se deja de usar.

2. **Fase 2 = dispositivos** (sincronización N_MAX + devices). Es el dominio mejor conocido, el que más bugs ha tenido (más se ha aprendido), y el que más valor da al operario.

**Decisión pendiente del operario** (no del plan):

3. **Estrategia de merge en Fase 5**: ¿`squash-merge` (un solo commit en `main` con todo el greenfield) o `rebase` (historia del greenfield preservada commit por commit en `main`)? Recomiendo `rebase` para mantener la trazabilidad de las 5 fases, pero es decisión tuya.

---

*Plan generado el 2026-09-10. Pendiente de aprobación. NO se ha modificado código todavía — la rama `greenfield/iec-61131-3` aún no se ha creado.*
