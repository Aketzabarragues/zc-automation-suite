# Estado del runtime tras el refactor de tres pilares

Analisis del repo en `main` (commit `f877a70`). Metodo: cuatro exploraciones
read-only por carpeta (`core/composition/`, `core/web_server/` + `core/launcher/`
+ `core/runtime/`, `core/infrastructure/tia/` + `core/helpers/`,
`areas/alimentacion/`) mas una comprobacion propia de `tests/` y de las
referencias a ficheros inexistentes.

Toda afirmacion lleva `ruta:linea`. Se distingue lo MEDIDO (leido o
grepado) de lo INFERIDO.

---

## 0. Estado actual

| Grupo | Estado |
|---|---|
| **G0** - bugs del modelo nuevo | **Hecho.** B1 (reserva atomica del FB), B2 (flag de ocupado por SSE), B3 (log de cierre en el FB), B4 (banner de precondiciones), B5 (400 en vez de 500) |
| **G1** - retirada del legacy de runtime | **Hecho.** El Engine y el FunctionBase ya no tienen camino async; los 38 tests que lo cubrian se migraron al camino `execute()` o se borraron con el codigo |
| **G2** - higiene de docs y codigo muerto | En curso |
| **G3** - fuera de alcance | Pendiente de decision |

Estado medido tras G1:

- **0** funciones `async def` en codigo de produccion (las 40 que quedan
  estan en `tests/`: 38 testean helpers sync, 1 verifica que un
  `run_step` corrutina se rechaza y 1 es un resto en un test del router).
- El repo no tiene ningun `asyncio` en `core/`, `areas/` ni `main.py`.
- La suite completa: **1453 passed, 3 skipped**.

---

## 1. Veredicto

El runtime tiene **un solo camino de ejecucion**: el dispatcher OB1. El
camino async ("tick legacy") **no tenia un solo llamador en produccion**
(grep exhaustivo sobre `core/`, `areas/`, `main.py`), y ya se ha
retirado: el Engine y el FunctionBase no exponen `start_loop` /
`stop_loop` / `tick_once` / `run_cycle` ni `start()` / `tick()` /
`cancel()`.

El empuje de resultados al HMI esta **completo de extremo a extremo**: los
17 eslabones del push estan cableados y verificados.

Lo que el refactor **no** toco y sigue pendiente es otra cosa: ~30
referencias a ficheros que ya no existen (`core/infrastructure/gateway.py`,
`core/web_server/dependencies.py`, `_pendiente/`, `_legacy_reference/`,
`mcp_server.py`, `tia_handlers.py`), ~40 docstrings que describen un modelo
que ya no existe (incluido el que motivo esta revision) y 11 endpoints sin
consumidor.

Ademas, la auditoria destapo **4 bugs del modelo nuevo** (no legacy),
todos corregidos en G0. El mas grave: dos ``submit()`` del mismo FB lo
ejecutaban dos veces (doble sincronizacion contra TIA desde un doble clic).

---

## 2. Las cuatro acepciones de "legacy" (la raiz de la confusion)

La palabra "legacy" se usa en el repo para cuatro cosas distintas. No
confundirlas es el punto de partida de este documento.

| # | Acepcion | Que es | Que implica | Alcance |
|---|---|---|---|---|
| **L1** | **Legacy de runtime** | El camino async: `Engine.start_loop/stop_loop/tick_once/run_cycle` y `FunctionBase.start/tick/cancel/_tick_locked/_step_ejecutar` | Codigo muerto: sin llamador en produccion, pero con 38 tests que lo prueban | ~260 lineas en `core/composition/` + 38 tests |
| **L2** | **Legacy de datos** | "shape legacy", "N_MAX legacy", "Excel legacy": la **forma del payload** que la SPA espera | **NO es deuda de este refactor.** Cambiarlo es cambiar el contrato con la SPA y con el Excel del operario | 118 de las 127 ocurrencias en `areas/alimentacion/` |
| **L3** | **Legacy de archivo** | Carpetas y modulos archivados: `_pendiente/`, `_legacy_reference/`, `core/infrastructure/gateway.py`, `core/web_server/dependencies.py`, `mcp_server.py`, `tia_handlers.py`, `tia_bloque_cache.py` | **No existen en disco.** Solo sobreviven las menciones textuales | ~30 referencias en codigo y docs |
| **L4** | **Legacy de build** | `build_exe.py`: el "gateway legacy" que re-invocaba el `.exe` como subproceso OT efimero via `main.py --worker` | `main.py` **no tiene** `--worker` (solo `--web`). El `.exe` ya no se re-invoca | `build_exe.py:30-33`, `:290-291` |

Regla para leer el repo: **L1 es deuda de este refactor. L2 es otro
proyecto. L3 y L4 son basura que hay que limpiar.**

---

## 3. Estado por capa

| Capa | Estado | Nota |
|---|---|---|
| `core/composition/plc_engine.py` | **VIVO con residuo** | El OB1 completo (`submit`, `start_ob1`, `stop_ob1`, `_ob1_loop`, `_run_job`, `Job`, `FBBusyError`). Ademas, muerto: `start_loop`, `stop_loop`, `run_cycle`, `tick_once`, `_run`, `snapshot()`, `cycle_count`, `_task`, `_tick_period_s`, `tick_period_s` |
| `core/composition/plc_function_base.py` | **VIVO con residuo** | `execute()` sync + `_step_ejecutar_sync` + `_invoke_step_sync` + `request_cancel` + tracker. Ademas, muerto: `start`, `tick`, `cancel`, `_tick_locked`, `_step_ejecutar` (async), `_ensure_loop_objects`, `_lock` (asyncio.Lock), `_loop` |
| `core/infrastructure/tia/` | **INTACTO** | 0 trazas de asyncio. 27 comandos en 9 modulos `tia_cmd_*.py`, todos sync y con retornos primitivos. La cifra **coincide** con lo documentado |
| `core/helpers/` | **INTACTO** | 100% sync, todos los helpers en uso por FBs del OB1 |
| `core/web_server/` + `core/launcher/` + `core/runtime/` | **LIMPIO del async** | 0 imports de asyncio, 0 `tick_once`, 0 event loop propio. El hilo `main-loop` ya no existe |
| `areas/alimentacion/` | **MIGRADO** | 9 FBs sync, 9 routers a 202, 0 `async def`, 0 polling |
| `tests/` | **MIXTO** | 157 ficheros: 19 con camino OB1, 6 con camino legacy (38 tests), 1 solo-legacy |

### Lo que cambio (el antes/después)

| Antes | Ahora |
|---|---|
| Router ejecutaba el FB y bloqueaba hasta responder (hasta 600 s) | Router encola con `engine.submit()` y responde `202 {"ok":true,"job_id":"<hex>"}` |
| El resultado volvia en el body del HTTP | El resultado llega por push: SSE `fb_state` + slots del `AppCache` que el FB publica en su `on_finish` |
| El engine tickeaba los FBs cada 100 ms (hilo `main-loop`, event loop efimero por ciclo) | El engine es un dispatcher con cola FIFO y un hilo `plc-ob1` que ejecuta cada FB completo con `fb.execute()` |
| FBs `async`, con `await dispatch_async(...)` hacia TIA | FBs sync, con `tia_client.submit_and_wait(cmd, args, timeout=T)` (bloqueante a proposito: el hilo del OB1 es su sitio) |
| El wrapper `core/helpers/tia/tia_dispatch_async.py` envuelve `submit_and_wait` en `asyncio.to_thread` | Borrado. El wrapper no hacia falta: el FB ya corre en un hilo dedicado |
| El progreso y los logs llegaban por polling (`GET /api/v1/progress/current` cada 500 ms, `GET /api/v1/logs` cada 1 s) | Llegan por SSE (`progress`, `log`) |
| `cancel()` async, `asyncio.Lock` por FB | `request_cancel()` sync y thread-safe |
| El supervisor arrancaba el `main-loop` | Arranca el dispatcher OB1; el OB1 se para antes que el worker TIA |

---

## 4. Bugs reales (todos del modelo nuevo, ninguno legacy)

**Estado: los cinco de G0 y los ocho del smoke en vivo contra TIA
Portal, corregidos.** La descripcion de cada uno se conserva como
registro de que estaban y de por que se detectaron.

### B1 — CRITICO: dos `submit()` del mismo FB lo ejecutan DOS veces

**Corregido.** `submit()` decide ahora la ocupacion sobre los trabajos
(`queued` + `running`) y comprueba + encola en la misma seccion critica
(`Engine._submit_lock`). Guard de regresion:
`tests/core/test_engine_submit_reserva.py`.

`Engine.submit()` decide la ocupacion con `fb.is_terminal()`
(`core/composition/plc_engine.py:272`). Ese estado **no cambia hasta que el
OB1 empieza a ejecutar**, asi que entre el `submit()` y el `_run_job()` el
FB sigue apareciendo como terminal y admite un segundo trabajo.

**Reproduccion (MEDIDO, `tools/_probe_double_submit.py`)**:

```
submit 1: 0cd58f696e4d4640bb53dd2087cb02fc
submit 2: ACEPTADO (cb830c7cf26447f4848357d7b4168cea)
ejecuciones reales del FB: 2
  job 0cd58f69 status=done result={'ejecuciones': 1}
  job cb830c7c status=done result={'ejecuciones': 2}
```

**Escenario real**: doble clic del operario con el OB1 ocupado en otro
trabajo. El primer `submit` encola; el segundo tambien (el FB sigue
terminal). Cuando el OB1 los alcanza, ejecuta el mismo FB dos veces: dos
sincronizaciones completas contra TIA (import + compile).

`_run_job()` vuelve a comprobar `is_terminal()` (`:403`), pero para entonces
el primer trabajo ya termino y el FB vuelve a estar terminal: la segunda
comprobacion no salva.

Causa raiz: la reserva del FB no es atomica. `submit()` deberia decidir la
ocupacion sobre los **jobs** (los estados `queued` y `running`), no sobre el
estado del FB, y hacerlo bajo un lock que cubra comprobar + encolar.

### B2 — `store.busy` se libera cuando responde el POST, no cuando el FB termina

`areas/alimentacion/frontend/components/Dispositivos.js:169` pone
`store.busy = true` y `:189` lo pone a `false` en el `finally` del fetch.
Como el router responde `202` de inmediato, **el boton se rehabilita con el
trabajo en vuelo**. El operario puede relanzar el mismo FB. Igual en
`Entidades.js:223/236` y `ProcesosSyncView.js:318/351`.

Encadenado con B1: B2 produce el segundo `submit()` y B1 lo acepta. El
flag `busy` deberia принадener al FB (via el `fb_state` terminal del SSE),
no al `finally` del POST.

### B3 — el log de cierre de "crear proceso" miente

`areas/alimentacion/frontend/proc_process_crear_router.py:305` y `:408`
leen `fb.result` en el **mismo request** que hace `engine.submit()` (`:285`,
`:388`). El FB aun no ha corrido, luego `fb.result` siempre esta vacio: el
`logger.ok` de `:314` reporta siempre "0 archivos previstos, 0 colisiones" y
el de `:424` siempre "0 archivos generados, compile=FAIL". Es residuo del
modelo en el que el router recibia el resultado. El log de cierre debe
emitirlo el FB al final de `execute()`, como ya hacen el resto.

### B4 — `ProcesosSyncView.js:330` lee una clave que ya no existe

`if (r.data && r.data.precondiciones_ok)` lee del body de un endpoint que
responde `202 {"ok":true,"job_id":"<hex>"}`. La clave no existe: la rama
nunca se cumple y el banner ambar que anuncia ese docstring
(`ProcesosSyncView.js:13-14`) no se muestra nunca. El dato real llega por
SSE `cache_changed` al slot `preview_proc` (`:104-106`).

### B5 (menor) — `proc_process_crear_router.py:380` responde 500 a un error de validacion

`except ValueError` de `validate_plc_in_excel` (el PLC no esta en el Excel
cargado) se traduce a **500**. Por el contrato de `AGENTS.md` §2.6 es un
**400**.

**Estado de los cinco**: corregidos en G0. B2 y B3, ademas, se
resolvieron moviendo la responsabilidad al sitio correcto (el FB y el
estado terminal del SSE), no con un parche.

### Bugs del smoke en vivo contra TIA Portal

El smoke ejecuto 12 trabajos contra TIA Portal: 11 correctos y 1 fallo
(el sync de dispositivos, en Tx B). Los ocho de abajo son los que se
detectaron con ese log y con la revision del codigo; todos corregidos.

### S1 — el sync de dispositivos importa en TIA con el layout equivocado

**Corregido.** El sync de dispositivos reimporta las tablas de tags
dentro de una transaccion (Tx B). Para que TIA haga UPDATE y no CREATE,
el export tiene que conservar la jerarquia de carpetas del PLC: con el
export plano la tabla se crea de nuevo, el objeto ya existe y la
transaccion muere con `CommitOnDispose`.

Causa raiz: el handler unificado `export_tables` tiene
`keep_folder_structure=False` por defecto, mientras que el handler que
usaba antes el sync (`export_plc_tags_xml`) lo tenia en `True`. Los dos
call sites del sync no pasaban el flag, asi que pasaron a exportar plano
sin que nadie lo notase. El `export_tables` de los 4 previews y el de
`entidades` si lo declaraban, por eso solo el sync de dispositivos fallo.

Los 2 exports del sync (stage 1 y stage 6) pasan ahora
`keep_folder_structure=True` de forma explicita, y el diff de
dispositivos y el lector de N_MAX localizan el XML por tabla con
`XmlTarget`, que tolera los dos layouts (plano y con jerarquia). Si el
XML no aparece, la tabla se omite con un warning en vez de proponer
cambios contra una base inventada.

Guard de regresion:
`tests/areas/alimentacion/functions/test_disp_sync_export_estructura.py`
(guard estructural: ningun `export_tables` puede heredar el default del
handler, y los 2 exports del sync tienen que llevar la jerarquia).

### S2 — el N_MAX de dispositivos no se leia y no se aplicaba

**Corregido.** El lector de N_MAX buscaba el XML en una subcarpeta
concreta, sin fallback. Con el export plano el XML vive en la raiz del
workdir: no se encontraba, el estado actual se quedaba vacio y el sync
proponia 0 cambios de N_MAX **en silencio**. Con `XmlTarget` el XML se
localiza en cualquiera de los dos layouts.

Consecuencia a tener en cuenta: antes el N_MAX de dispositivos nunca se
aplicaba. Ahora si. Si el Excel trae un valor distinto del que hay en
TIA, ese cambio llega al PLC (redimensiona el array del bloque de
dispositivos).

### S3 — el error del lote transaccional no decia donde habia fallado

**Corregido.** `execute_transactional_batch` distinguia entre un
sub-comando fallido y el commit de la transaccion solo por el numero de
paso. Cuando todos los sub-comandos pasaban y el commit era rechazado
por TIA, el mensaje apuntaba a un paso que no existia y no decia que el
detalle real esta en el log de TIA Portal. Ademas, el fallo del rollback
se tragaba con `except Exception: pass`: el proyecto puede haber quedado
a medias y el operador no se enteraba.

Ahora el error dice si el fallo esta en un paso concreto o en el commit,
apunta al log de TIA Portal y reporta el fallo del rollback como dato
adicional, sin sustituir a la causa raiz.

### S4 — el sync no decia cuantos tags habia escrito de verdad

**Corregido.** El diff de dispositivos razona por `uid` (el `Value` del
PlcUserConstant) y el modificador razona por `nombre` (el `Name`): un
add cuyo nombre ya existe en la tabla, con otro uid, no se puede
escribir. El modificador lo descartaba en silencio, de modo que el
preview (que cuenta por uid) prometia mas tags de los que acababan en
TIA.

Ahora el modificador avisa de cada omision con su motivo, y el sync
informa de cuantos tags ha escrito de los pedidos y en que tabla se han
quedado fuera.

Pendiente de decision: cuando el nombre colisiona y el `uid` antiguo
esta en `removed`, el modificador borra el constante viejo y no escribe
el nuevo (el tag desaparece del PLC). El sync no puede resolver ese
caso por su cuenta: es una decision de negocio (si el Excel reenumeró
los dispositivos, hay que decidir si se renombra el tag existente o si
se rechaza el sync).

### S5 — los defaults del area usaban nombres de tabla que no existen

**Corregido.** La tabla global N_MAX se llama `0_Config_Dispositivos` y
vive en la carpeta `0_Sistema` (nombres del config que se instala y del
PLC del operario). Los defaults del area seguian con
`000_Config_Dispositivos`, `000_Sistema` y `003_Procesos`: una
instalacion sin esas claves en su JSON buscaba una tabla inexistente y
se quedaba sin N_MAX que aplicar.

Los defaults quedan atados al config empaquetado por un guard:
`tests/areas/alimentacion/helpers/config/test_config_defaults.py`.

### S6 — el sync de dispositivos reportaba 0 operaciones

**Corregido.** El worker responde al batch con el envelope
`{"ok":…, "result":{…}}` y los contadores viven en `result`. El FB
guardaba el envelope entero, asi que los contadores se leian en el nivel
equivocado: el resumen decia "0 N_MAX aplicados en TIA" y "0 tablas
importadas a TIA" tras un sync que habia escrito 116 tags y borrado 83,
y el `result` que ve el operario decia "0 ops" con los detalles vacios.

El ctx guarda ahora el `result` del batch, el resumen distingue las ops
de N_MAX de las de renombreo y dice cuantas tablas se han importado, y
el `result` lleva el detalle de cada operacion en su propia clave.

Guard de regresion:
`tests/areas/alimentacion/functions/test_disp_sync_contadores.py` (los
tests pasan por los stages de verdad con el envelope real del worker:
un mock del ctx con el shape interior no detectaba el fallo).

### S7 — el guard del layout de export no cubria un formato de llamada

**Corregido.** Hay dos formas de pedir un export: dentro de un
`execute_batch` (el FB pasa una lista de operaciones) y en directo
(`submit_and_wait("export_tables", {…})`). El guard solo miraba el
primer formato: el preview de proc_db exportaba sin declarar el layout
y el aviso del handler saltia en una operacion que era correcta (el
preview no importa nada en TIA).

El preview declara ahora el layout que usa, y el guard mira los 2
formatos. Ademas avisa si dejara de ver alguno, que es como el fallo se
escondia.

Guard de regresion:
`tests/areas/alimentacion/functions/test_disp_sync_export_estructura.py`.

### S8 — el listado de plantillas devolvia 500 si la share no respondia

**Corregido.** `proc_plantillas_router` preguntaba por el directorio de
plantillas con `Path.is_dir()` sin capturar `OSError`. Una share de red
caida (credenciales, mount caido) devolvia `WinError 1326` y el
operario se comia un 500 con traceback, cuando el propio router promete
200 con `warning` para los casos degradados.

Ahora la share inaccesible es un caso degradado: 200 con la lista vacia
y el aviso explicando que no se puede leer la ruta.

Guard de regresion:
`tests/areas/alimentacion/frontend/test_proc_plantillas_router.py`.

---

## 5. L1 - Legacy de runtime: RETIRADO

**Estado: retirado en G1.** El Engine y el FunctionBase ya no exponen el
camino async, y los 38 tests que lo cubrian se migraron al camino
`execute()` o se borraron con el codigo. El inventario siguiente se
conserva como registro de lo que habia y de lo que costaba.

### En `core/composition/plc_engine.py` (425 lineas)

| Simbolo | Ubicacion | Coste | Quien lo usa |
|---|---|---|---|
| `async start_loop()` | `:182-191` | 10 lineas | solo tests |
| `async stop_loop()` | `:193-203` | 11 lineas | solo tests |
| `run_cycle()` | `:205-217` | 13 lineas | solo tests |
| `async tick_once()` | `:219-234` | 16 lineas | solo `run_cycle` |
| `async _run()` | `:240-257` | 18 lineas | solo `start_loop` |
| `snapshot()` | `:151` | 26 lineas | **nadie** (ni produccion ni tests) |
| `self.cycle_count` | `:81` | - | siempre 0 en produccion |
| `self._task` | `:79` | - | siempre `None` en produccion |
| `self._tick_period_s` + parametro `tick_period_s` | `:76`, `:80` | - | propagado desde `main.py:174` y `main_supervisor.py:333`, no lo consume nadie |
| `DEFAULT_TICK_PERIOD_S` | `:41` | - | solo el loop legacy |
| `import asyncio` | `:26` | - | 7 usos, todos legacy |

### En `core/composition/plc_function_base.py` (674 lineas)

| Simbolo | Ubicacion | Coste | Quien lo usa |
|---|---|---|---|
| `async start()` | `:452-507` | 56 lineas | ~38 tests |
| `async tick()` | `:509-539` | 31 lineas | `tick_once` + tests |
| `async cancel()` | `:541-559` | 19 lineas | 1 test |
| `async _tick_locked()` | `:565-575` | 10 lineas | `tick()` |
| `async _step_ejecutar()` | `:592-642` | 51 lineas | `_tick_locked` (duplica `_step_ejecutar_sync` con otra semantica de timeout) |
| `_ensure_loop_objects()` | `:179-197` | 19 lineas | `start`/`tick`/`cancel` |
| `self._lock` (asyncio.Lock) | `:121` | - | solo el camino async |
| `self._loop` | `:105` | - | solo `_ensure_loop_objects` |
| `import asyncio` + `import inspect` | `:44`, `:45` | - | 9 + 2 usos, todos legacy |

Ademas, rama **muerta**: `if inspect.iscoroutinefunction(self.run_step)`
(`:609-613`). Ningun `function_*.py` del repo declara hooks async (por el
guard `tests/core/composition/test_fbs_sync_contract.py:84`).

### Diferencia de semantica entre los dos caminos (motivo para tirar el legacy)

`_step_ejecutar()` (legacy, `:592`) comprueba `_cancelled` **antes** del
step pero **no despues**. `_step_ejecutar_sync()` (OB1, `:319`) lo comprueba
**despues** (`:354-355`). Es decir: en el camino legacy, una cancelacion
llegada durante un step se pierde y el FB cierra como `n_done`. El camino
OB1 lo hace bien.

### Tests que dependen del camino legacy (38)

| Fichero | Tests legacy | Tests OB1 | Nota |
|---|---|---|---|
| `tests/core/test_function_base.py` | 9 | 14 | 6 legacy puros + 2 mixtos (`test_execute_y_tick_no_se_solapan`, `test_execute_cancelado_durante_un_step`) |
| `tests/core/test_engine_ob1_run_cycle.py` | 6 | 15 | `test_engine_exposes_both_sync_and_async_apis` blinda hoy la coexistencia: hay que invertirlo |
| `tests/core/composition/test_function_block_edit_prepare.py` | **10 (todos)** | 0 | **100% legacy**: por eso no detecto el FB async que rompio el smoke en vivo |
| `tests/core/composition/test_function_block_edit_apply.py` | 7 | 2 | |
| `tests/areas/.../test_function_proc_crear_generar_preview.py` | 3 | 4 | los equivalentes OB1 ya existen (`:336`, `:374`) |
| `tests/areas/.../test_function_proc_crear_sincronizar.py` | 2 | 2 | el equivalente OB1 ya existe (`:418`) |

Al migrar a `execute()` cambia la semantica de los errores: en OB1 las
excepciones de `on_start`/`run_step` **no se propagan**, quedan en
`fb.error_msg` con `nStep == n_error`. Los tests que hoy esperan
`ValueError`/`RuntimeError` propagados deben pasar a assertar `error_msg`.

---

## 6. L2 - Legacy de datos: NO es deuda de este refactor

118 de las 127 ocurrencias de "legacy" en `areas/alimentacion/**` son
**forma de datos**, no runtime:

- **Shape del `self.result`** que la SPA espera: `function_excel_cargar.py:212`,
  `function_disp_generar_preview.py:228`, `function_disp_sincronizar.py:263`,
  `function_entidades_generar_preview.py:247`, `function_entidades_sincronizar.py:247`,
  `function_proc_db_generar_preview.py:262`, `function_proc_db_sincronizar.py:273`,
  `function_proc_crear_generar_preview.py:388`, `function_proc_crear_sincronizar.py:428`.
- **Formato del Excel corporativo y N_MAX**: los 18 `helpers/excel/excel_parser_*.py`,
  `helpers/config/config_defaults.py:43`.
- **Compat de entrada**: `list[str]` legacy que los FBs convierten en
  `[{nombre, numero}]` (`function_proc_crear_generar_preview.py:317`).

Retirarlo es cambiar el contrato con la SPA y con el fichero del operario:
otro proyecto, otro momento.

**Riesgo registrado**: `entidades_generar_preview` publica en `preview_disp`
(`function_entidades_generar_preview.py:263`), el **mismo** slot que
`disp_generar_preview` (`:284`); y `entidades_sincronizar` en
`last_disp_commit_summary` (`:302`), el mismo que `disp_sincronizar` (`:338`).
Un preview de entidades borra el de dispositivos en la SPA. Esta decision
esta documentada (`function_entidades_generar_preview.py:256-257`) y es
intencional, pero conviene tenerla presente.

---

## 7. L3/L4 - Documentacion que ya no corresponde al codigo

**Estado: resuelto en G2.** El inventario se conserva como registro de lo
que habia. Las correcciones se hicieron por capas: el nucleo, el area y
las guias en `docs/` y `.opencode/agent/`, y el shell JS por separado.

### Los docstrings que motivan esta revision

| Ubicacion | Afirmacion | Realidad |
|---|---|---|
| `plc_engine.py:3` | "Expone dos caminos **independientes**" | **FALSO**: los dos comparten `FunctionBase._exec_lock` (`plc_function_base.py:127`), que existe para que no se pisen |
| `plc_engine.py:5-8` | El tick va listado primero, sin aviso | El unico con llamador es el dispatcher. `.clinerules:42` si dice "no es el camino de ejecucion"; el docstring no |
| `plc_engine.py:66-72` | "Dos caminos de ejecucion independientes" (docstring de la clase) | El que cita el operario. Repite el falsehood anterior |
| `plc_function_base.py:23-25` | "``execute()`` ... **Es el camino que usa el worker TIA**" | **FALSO**: el worker TIA (`tia_loop.py`) es un hilo **distinto** que consume comandos. Quien llama a `execute()` es el hilo `plc-ob1` (`plc_engine.py:411`). Funde dos de los tres pilares |
| `plc_function_base.py:26-28` | El legacy "desaparece cuando el engine pasa a ser un OB1 con cola de trabajos" | **La condicion ya se cumplio** (`submit()` en `:263`, `start_ob1()` en `:333`). El docstring anuncia un futuro que ya es presente |
| `plc_function_base.py:35-40` | `cancel(reason)` es la API de cancelacion y `request_cancel` "la variante sync" | **INVERTIDO**: `cancel()` es legacy sin llamador; `request_cancel()` es la de produccion (`plc_engine.py:307`) |
| `plc_function_base.py:12-19` | "nStep=99 done (terminal OK, **el engine NO tickea mas**)" | En OB1 el engine no tickea nunca. Es residuo del modelo tick |
| `plc_function_base.py:448-450` | "API publica legacy (async, engine) -- **se retira con el OB1**" | El OB1 ya esta y el bloque sigue aqui |
| `plc_function_base.py:375-386` | Justifica el riesgo del OB1 comparandolo con "el camino legacy" | Referencia a un camino que se va a borrar |
| `core/composition/__init__.py:3` | "el engine (ciclo principal que **tickea los FBs cada 50ms**)" | Doble error: no tickea nada desde `3d4ab3d`, y el periodo era 100 ms (`plc_engine.py:41`) |

### Comentarios que describen un polling inexistente

`core/runtime/log_buffer.py:3` y `:66`, `core/runtime/progress_buffer.py:3`
y `:9`, `core/web_server/static/js/main.js:339-342` y `:351-352`,
`core/web_server/static/js/api.js:181-182`, `core/runtime/sse/sse_event_bus_sync.py:3-5`,
`core/runtime/sse/sse_publishers.py:127-128` ("tras cada tick"),
`core/web_server/app_flask.py:128` ("eventos del main loop").

### Referencias a ficheros que no existen

| Referencia | Donde | Estado |
|---|---|---|
| `core/infrastructure/gateway.py`, `TIAProcessGateway` | `api.js:66`, `store.js:667`, `function_proc_db_generar_preview.py:134`, `.opencode/agent/build-and-tests.md:55` | **no existe** |
| `core/web_server/dependencies.py`, `get_gateway` | `.opencode/agent/backend-api.md:16-18`, `docs/HOWTO_CREATE_AREA.md:115-123` | **no existe** |
| `_pendiente/` | `core/__init__.py:9`, `core/infrastructure/__init__.py:9`, `app_area_registry.py:65`, `tests/_tia_openness_mock.py:37` | **no existe** |
| `_legacy_reference/` | 10 menciones en 7 ficheros (parsers del Excel, tests) | **no existe** |
| `mcp_server.py` | `AGENTS.md` §5, `.opencode/agent/backend-api.md`, `config_manager.py` | **no existe** |
| `tia_handlers.py` | `core/infrastructure/tia/__init__.py:3`, `tia_loop.py:8` | **no existe** (los comandos estan en 9 modulos `tia_cmd_*.py`) |
| `main.py --worker` | `build_exe.py:30-33` | `main.py` solo define `--web` |
| `areas/alimentacion/application/use_cases/`, `core/plc/engine.py`, `core/plc/function_base.py` | `areas/alimentacion/functions/__init__.py:3-10` | **no existen** |
| `helpers/proc/proc_sincronizar` | `function_proc_db_sincronizar.py:211-213` | **no existe** |
| `tests/_tia_openness_mock.py` | su propio docstring | **el modulo no lo importa nadie** |
| `test_store_tia_methods.py` | `store.js:737-739` | **no existe** |

### Recuentos que mienten

| Ubicacion | Dice | Real |
|---|---|---|
| `core/infrastructure/tia/__init__.py:3`, `tia_loop.py:8` | "26 comandos en `tia_handlers.py`" | **27 comandos en 9 modulos** `tia_cmd_*.py` (MEDIDO ejecutando el catalogo) |
| `tia_commands_catalog.py:16` | "1 batch: execute_transactional_batch" | **2** (`execute_batch` + `execute_transactional_batch`) |
| `tia_commands_catalog.py:49` | "# 5" sobre `EXPORT_COMMANDS` | **3** |
| `tia_commands_catalog.py:52` | "# 1" sobre `BATCH_COMMANDS` | **2** |
| `core/web_server/__init__.py:7-9`, `build_exe.py:170-178` | "7 blueprints" | **8** (falta `blocks_edit`) |
| `helpers/excel/excel_loader.py:3-4`, `:14-26`, `:115` | 15 y 17 parsers | **19** (12 disp + 4 software + 1 N_MAX + 1 PLC + 1 entidades) |
| `AGENTS.md` (seccion del dispatcher) | "El supervisor arranca Flask, luego el dispatcher, luego el worker TIA" | El codigo real es `start_tia_loop()` (`main_supervisor.py:390`) -> `start_ob1()` (`:109`) -> hilo Flask (`:110`) |

### Docstrings de shell que no corresponden

- `areas/alimentacion/__init__.py:11-12`: "Los routers web ... siguen existiendo en el area pero **no se montan**". Falso: se montan via `contributes_routers` (`:109`).
- `helpers/excel/excel_loader.py:8-12`: "Los callers (router FastAPI, MCP tool) lo invocan con `asyncio.to_thread(loader.load, path)`". El codigo es sync y su unico caller es `excel_upload.py:63`, invocado desde el hilo del OB1.
- `areas/alimentacion/frontend/manifest.py:28`: "Prefijo HTTP desde el que el **FastAPI** sirve los .js". El shell es Flask.
- `api.js:106`, `api.js:377`, `api.js:411`: "devuelve el resumen/result". Los endpoints responden `202 {job_id}`; el resultado llega por SSE.
- `store.js:719-740`: docstring huerfano de una funcion borrada (`refreshTiaConnection`), y `:737-739` apunta a un test inexistente. `:745` la nombra mientras `:738` y `:1216` dicen que ya no se exporta.
- `store.js:757-778` (`_logTiaStateTransition`): rama `else {}` vacia y un `const err` asignado y nunca usado.
- `disp_sync_router.py:1`, `:18`, `disp_preview_router.py:1`, `:20`: documentan rutas `POST /api/v1/plcs/<name>/...`; las reales son `POST /api/v1/sync/...`.
- `areas/alimentacion/functions/__init__.py:1-16`: el docstring entero describe el runtime anterior (state machine `nStep=10->20->30->99/98`, `_tick_locked()`, `await`, `core/plc/engine.py`).

---

## 8. Codigo muerto (L1 y transversales)

**Estado: resuelto en G2** (salvo lo indicado en cada fila).

| Simbolo | Ubicacion | Seguro de borrar | Quien lo usa |
|---|---|---|---|
| `Engine.snapshot()` | `plc_engine.py:151` | si | **nadie** (ni produccion ni tests) |
| `SyncTIAClient.submit_batch` | `tia_loop.py:148` | si | **nadie** |
| `_sanitize_args` | `tia_helpers.py:430` | si | **nadie** |
| `_summarize_result` | `tia_helpers.py:450` | si | **nadie** |
| `import WEB_LEVEL` | `tia_helpers.py:27` | si | importado y nunca usado |
| Bloque "Decorador de trazabilidad para handlers OT" | `tia_helpers.py:418-426` | si | comentario de 9 lines sin decorador |
| `SD_ENCODING`, `SD_RES_ENCODING`, `MAX_COMMENT_LEN` | `tia_export_paths.py:38-43` | si | **nadie** (y `SD_ENCODING` duplica la de `simatic_sd_db_array_comment_updater.py:82` con **valor distinto**: `utf-8` vs `utf-8-sig`) |
| `SLOW_TIMEOUT_MS` | `static/js/api.js:40` | si | **0 usos**; `AGENTS.md` lo documenta como el bucket de los commits, pero el commit usa MEDIUM (`api.js:171`) |
| `case "plcs"`, `case "project_info"` | `main.js:387`, `:395` | si | ningun publisher emite esos tipos |
| `make_tia_loop_status_publisher` | `sse_publishers.py:186` | revisar | emite `tia_loop_status` y la SPA no tiene `case` para el |
| `tests/_tia_openness_mock.py` (modulo entero) | `tests/` | si | **nadie** lo importa |
| `tia_dispatch_async.cpython-312.pyc` | `core/helpers/tia/__pycache__/` | si | bytecode de un modulo borrado |

### Endpoints sin consumidor

`/ping` y `/cycle_count` (`app_flask.py:109`, `:114`),
`/api/v1/plc/fb/<name>/start|disconnect|status` (`plc.py:39`, `:78`, `:92`),
`/api/v1/blocks/edit/<name>/status` (`blocks_edit.py:213`),
`GET /api/v1/logs` (`diagnostics.py:32`),
`GET /api/v1/progress/current` (`diagnostics.py:73`),
`GET /api/v1/tia/connection` (`tia_connection.py:41`),
`GET /api/v1/sync/preview/status`, `GET /api/v1/sync/commit/status`,
`GET /api/v1/entidades/preview/status` (los tres son *placeholders* que
devuelven siempre `200 ok=True`; sus unicos consumidores son tests).

Los tres placeholders del area son restos del modelo en el que se
consultaba el estado por polling.

---

## 9. Lo que NO hay que tocar (suena antiguo pero es vigente)

| Elemento | Por que |
|---|---|
| `core/infrastructure/tia/tia_loop.py` completo | El nombre "loop" engaña: es un `threading.Thread` + `queue.Queue` (`:62`, `:181`, `:271`). Cero asyncio. Es el WORKER |
| `core/infrastructure/tia/tia_helpers.py:38-405` | 14 utilidades privadas que importan explicitamente los 9 modulos de comandos. El prefijo `_` es convencion, no exclusividad |
| `core/helpers/` completo | 100% sync, todo en uso por FBs del OB1 |
| `core/infrastructure/tia/tia_state_cache.py`, `tia_cache.py`, `tia_loader.py`, `tia_export_paths.py`, `sd_block_parser.py` | Capa OT vigente |
| `core/web_server/routers/tia_connection.py` | Llama `submit_and_wait` **desde el hilo de Flask**, no desde un FB. Es intencionado: `attach_portal`/`detach_portal` son el pulsador Conectar/Desconectar y el worker debe quedar attached entre comandos. **No lo conviertas en FB** |
| Los "shape legacy" de los FBs | Contrato con la SPA (L2) |
| `core/composition/plc_function_base.py:577` (`_step_arrancar`) y `:644` (`_step_finalizar`) | **Compartidos** por los dos caminos: no se van con el legacy |

---

## 10. Plan propuesto (por grupos, cada uno con su suite verde)

**Estado: G0 y G1 hechos; G2 en curso; G3 pendiente de decision.** Los
detalles de cada grupo se conservan como registro de lo ejecutado.

### G0 - Bugs del modelo nuevo (prioridad maxima) — HECHO

1. `Engine.submit()`: reserva atomica del FB. Decidir la ocupacion sobre los
   jobs (`queued` + `running`) y proteger comprobar + encolar con un lock.
   Anadir el test de regresion que reproduce B1.
2. `store.busy`/`applying`: que lo liberen el `fb_state` terminal del SSE, no
   el `finally` del POST (B2). Ficheros: `Dispositivos.js`, `Entidades.js`,
   `ProcesosSyncView.js`.
3. Mover el log de cierre de "crear proceso" al FB (B3).
4. `ProcesosSyncView.js:330`: leer `precondiciones_ok` del `preview_proc` del
   AppCache (B4).
5. `proc_process_crear_router.py:380`: `ValueError` -> 400 (B5).

### G1 - Retirada del legacy de runtime (L1) — HECHO

Orden ejecutado (el propuesto por el agente de `core/composition/`, con
un ajuste: los tests legacy puros del `FunctionBase` se borraron en el
mismo commit que el codigo, no antes).

1. Congelar el contrato sync antes de tocar nada: guard que verifique que
   `FunctionBase` **no** expone `start`/`tick`/`cancel`.
2. Reescribir `tests/core/composition/test_function_block_edit_prepare.py` y
   `test_function_block_edit_apply.py` al camino `execute()` (17 tests). Es
   el paso mas grande: cambia la semantica de los errores (a `error_msg`).
3. Borrar los 5 tests legacy del area (los equivalentes OB1 ya existen).
4. `tests/core/test_function_base.py`: borrar 6 legacy puros, reescribir 2
   mixtos.
5. Borrar el legacy del `Engine` (`start_loop`, `stop_loop`, `run_cycle`,
   `tick_once`, `_run`, `snapshot`, `cycle_count`, `_task`, `_tick_period_s`,
   `tick_period_s`, `DEFAULT_TICK_PERIOD_S`, `import asyncio`) y de paso
   `main.py:174,177` y `main_supervisor.py:62,69,333`.
   Antes: reescribir los 8 tests legacy de `test_engine_ob1_run_cycle.py` e
   **invertir** `test_engine_exposes_both_sync_and_async_apis`.
6. Borrar el legacy del `FunctionBase` (`start`, `tick`, `cancel`,
   `_tick_locked`, `_step_ejecutar`, `_ensure_loop_objects`, `_lock`, `_loop`,
   `import asyncio`, `import inspect`).
7. Reescribir los docstrings (seccion 7).
8. `requirements-dev.txt` no declara `pytest-asyncio`, que 13 tests usan
   hoy. Al migrar, esa dependencia puede desaparecer del entorno.

### G2 - Higiene (barato, bajo riesgo)

- Docstrings que no corresponden al codigo (seccion 7): nucleo, runtime,
  shell, area, OT.
- Referencias a ficheros inexistentes (seccion 7).
- Recuentos que mienten (tabla de la seccion 7).
- Codigo muerto (seccion 8).
- Endpoints sin consumidor (seccion 8): **verificar antes** si los
  `/api/v1/plc/fb/<name>/*` los consume alguna integracion externa. Contra
  el historico de git: esos paths existen desde antes del refactor.
- `store.js:719-740` (docstring huerfano) y `store.js:757-778` (ramas
  vacias).
- `build_exe.py:30-33` y `:290-291` (gateway legacy).

### G3 - Fuera del alcance de este refactor

- Los shapes de datos (L2).
- El endpoint `/cycle_count` sin consumidor: decidir si se borra o se
  renombra a algo que describa lo que mide (`jobs_processed`).
- `SD_ENCODING` duplicado con valores distintos: centralizar o borrar la
  central. **Nunca dejar las dos.**

### Pendiente de smoke en vivo (no automatizable)

- `_h_get_project_info` (`tia_cmd_inspect.py:109-131`): normaliza solo lo que
  tiene `isoformat`. Si `Version` devolviera un tipo .NET no-ISO, el payload
  no seria JSON-serializable (INFERIDO: no medido contra TIA).
- `_h_import_tag_table` (`tia_cmd_import_.py:149`): cae en `target_folder=""`,
  que el propio modulo advierte que rompe el match UPDATE en TIA V21
  (INFERIDO: depende de si `import_plc_tags` comparte esa semantica).
- `proc_db_sincronizar`: exporta los bloques plano y replica la jerarquia
  del PLC por su cuenta (`param_subpath`), asi que no tiene el problema de
  S1. En el smoke no hubo import (0 cambios), asi que la rama de import con
  bloques existentes no se ha ejercitado contra TIA (INFERIDO: no medido).

---

## 11. Cobertura: el hueco que dejo el bug async

`tests/core/composition/test_function_block_edit_prepare.py` era **100%
legacy**: sus 10 tests usaban `asyncio.run(fb.start(...))` + `asyncio.run(fb.tick())`.
El camino `execute()` (el que usa el OB1) no estaba probado en ese FB, asi que
su `run_step` async paso la suite y revento en el smoke en vivo.

Cubierto ya por `tests/core/composition/test_fbs_sync_contract.py`
(commit `c4ba1bd`): ningun FB registrado puede tener hooks async, ningun
`function_*.py` del repo los declara, y `execute()` no muere con el error de
corrutina. El guard se valido en negativo.

**Hueco cerrado**: `tests/core/launcher/test_main_supervisor_ob1.py`
(commit `01658ec`) verifica que el supervisor **no** arranca ningun loop
async (`start_loop`, `run_cycle`, `tick_once`). Si alguien reintrodujera
el `main-loop`, la suite lo detecta.

Ademas, con la retirada del legacy en G1, los 38 tests que cubrian el
camino async se migraron al camino `execute()`. Ese camino esta ahora
cubierto en su totalidad: no queda ningun test que dependa de un metodo
retirado.

---

## 12. Arranque real verificado (sin TIA)

Medido arrancando la app de verdad (`python main.py --web 127.0.0.1:9499`)
sobre el codigo de `main` tras G0, G1 y G2:

| Comprobacion | Resultado |
|---|---|
| Comandos TIA registrados | 27 (los 9 modulos `tia_cmd_*`) |
| FBs registrados en el engine | 12 (3 core + 9 del area) |
| Blueprints montados | 9 (8 modulos; `plc.py` expone dos) |
| `engine.on_fb_change` cableado | si, tras registrar los FBs (el fix de `8279bc0`) |
| Worker TIA (hilo) | arrancado, estado `idle`, sin portal attached |
| Dispatcher OB1 (hilo `plc-ob1`) | arrancado |
| Hilo de tick | **ninguno** |
| `GET /api/v1/catalog` | 200 |
| `GET /cycle_count` | `{"cycles":0}` |
| `GET /api/v1/plc/fb/subir_excel/status` | 200 con el estado del FB |
| `POST /api/v1/plc/fb/scan_plc_blocks/start` | **202** `{"ok":true,"job_id":"..."}` |
| Ejecucion del FB encolado | el OB1 lo recoge y ejecuta los steps (`check_cache` -> `escanear`) |
| Error sin TIA conectado | el FB lo captura en `error_msg` y queda en `n_error`; el dispatcher sigue vivo |
| Reconexion SSE de la SPA | `EventBusSync.subscribe` al cargar la pagina |

El unico punto que quedo sin verificar contra TIA real: el scan de bloques
contra un portal abierto, y el attach (`attach_portal` falla con "no TIA
instances found" porque no hay ninguna instancia abierta, que es el
comportamiento esperado).

### Hallazgo lateral

`core/web_server/static/js/components/TiaConnectionIndicator.js` existe pero
**no lo importa ni `main.js` ni `ShellTopbar.js`**: el componente no se
monta. Los docstrings de `store.js` lo citan como el consumidor de
`store.tiaConnection.state`. Queda pendiente decidir si se monta o se
retira.
