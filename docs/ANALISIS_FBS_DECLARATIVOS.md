# Análisis: simplificar los FBs a una declaración de steps

Documento de analisis (no de implementacion). Todo lo que hay aqui sale de
leer el codigo y de los logs; lo que no esta medido aparece marcado como
INFERIDO.

## 1. Resumen ejecutivo

**Veredicto: el refactor compensa, y de paso arregla un bug que el
operario esta viendo ahora mismo sin saberlo.**

Hoy un FB se declara **dos veces** (la lista `steps=` que ve el HMI y la
tabla `STAGES` que mapea nombre -> metodo), y cada FB reimplementa el
dispatch (730 lineas de `run_step` en 12 FBs). El detalle que se le
muestra al operario sale de un `if/elif` por nombre literal, y en 4 de
los 9 FBs del area **todas las ramas de ese `if/elif` son codigo
muerto**: el operario ve "OK" en vez del resumen real.

| Metrica | Valor |
|---|---|
| FBs | 12 (9 en `areas/alimentacion`, 3 en `core/composition`) |
| Lineas de `run_step` (solo dispatch) | **730** |
| Boilerplate de dispatch en el area (run_step + `_step_summary` + tablas `STAGES`) | **707** (8 % de las 8.801 lineas del area) |
| Andamiaje / logica de negocio | 86 % (FB pequeno) / 49 % (mediano) / 32 % (grande) |
| Steps del area | 65 |
| Steps que muestran el fallback "OK" en vez del resumen real | **37 de 64 (58 %)** |
| Tests del area que dependen de la FORMA del FB | 12 de 147 (8 %) |
| Referencias a metodos privados `_stage_N_*` en tests | 85 (sobreviven si no se renombran) |

**Lo que NO cambia**: la logica de negocio. 415 de las 474 lineas del
`run_step` de los 3 FBs de `core/composition` son logica, no andamiaje. El
refactor no borra trabajo: lo saca de un `switch` y lo deja en metodos
con nombre, que es lo que se puede leer.

## 2. Como se ve hoy

### 2.1 La declaracion esta partida en dos

```python
# function_disp_sincronizar.py
STAGES = (                                    # <- mapa nombre -> metodo
    (0, "Exportar etiquetas", "_stage_1_exportar_tags"),
    ...
)

super().__init__(
    steps=steps if steps is not None else [  # <- lo que ve el HMI
        {"nombre": "Exportar etiquetas"},
        ...
    ],
)
```

Los 65 nombres de las 9 tablas `STAGES` son **identicos** a los 65
nombres de `steps=`. La duplicidad ya tiene un test que la vigila
(`test_function_entidades_generar_preview.py:635-650`), o sea que
cuesta un test de 15 lineas por FB.

Puede divergir de tres maneras, y **dos de ellas son silenciosas**
(MEDIDO):

| Divergencia | Como se manifiesta |
|---|---|
| Nombre que no esta en `STAGES` | `ValueError` en tiempo de ejecucion |
| **Orden distinto** | Se ejecuta el metodo equivocado, en silencio |
| Conteo distinto | Filas de `STAGES` sobrantes se ignoran |

### 2.2 Cada FB reimplementa el dispatch

Los 9 `run_step` del area son **estructuralmente identicos** (MEDIDO):
guard de ctx, buscar el nombre en `steps[idx]`, recorrer `STAGES`
comparando nombres, `getattr(self, attr)()`, devolver el resumen.

```python
def run_step(self, idx: int, **params: Any) -> str:
    if self._ctx is None:
        raise RuntimeError(...)
    step_nombre = self.steps[idx]["nombre"]
    for _s_idx, s_nombre, s_attr in self.STAGES:
        if s_nombre == step_nombre:
            handler = getattr(self, s_attr)
            handler()
            return _step_summary(self._ctx, s_nombre)
    raise ValueError(...)
```

Los 3 FBs de `core/composition` hacen lo mismo con un `match/case`
(237, 176 y 61 lineas). En los 3 de `core` la logica de negocio esta
**dentro** de las ramas del `case`: no hay metodos `_stage_N_*`.

### 2.3 El detalle sale de un `if/elif` por nombre literal

```python
def _step_summary(ctx: Any, step_nombre: str) -> str:
    if step_nombre == "Exportar etiquetas":
        return "Exportar etiquetas: 13 tablas exportadas"
    ...
    return f"{step_nombre}: OK"          # <- fallback
```

El metodo del step **no devuelve nada**: el detail lo pone esta funcion.
Y las claves comparadas son literales escritos a mano.

### 2.4 BUG: en 4 de 9 FBs todas las ramas son codigo muerto

Comparacion automatica de las claves de cada `_step_summary` contra los
nombres reales de `steps=` (MEDIDO, verificado con AST):

| FB | Ramas vivas | Ramas muertas | Steps que caen al fallback |
|---|---|---|---|
| `function_disp_generar_preview.py` | 0 | **4 (100 %)** | 4 de 4 |
| `function_proc_crear_sincronizar.py` | 0 | **9 (100 %)** | 10 de 10 |
| `function_proc_db_sincronizar.py` | 0 | **9 (100 %)** | 9 de 9 |
| `function_proc_crear_generar_preview.py` | 1 | **7** | 7 de 8 |
| `function_entidades_sincronizar.py` | 4 | 0 | 7 de 11 |
| `function_disp_sincronizar.py` | 11 | 0 | 0 de 11 |
| `function_entidades_generar_preview.py` | 5 | 0 | 0 de 5 |
| `function_proc_db_generar_preview.py` | 6 | 0 | 0 de 6 |

Causa: esos FBs comparan contra nombres internos
(`"exportar_tags"`, `"check_state_commit"`, `"done"`) mientras `steps=`
usa nombres humanos ("Exportar etiquetas", "Validar estado de TIA").

**Confirmado en el log del smoke en vivo** (30 oct 2026):

```
Importar proceso: saliendo en 15078ms (Importar proceso: OK)
Abrir transaccion TIA: saliendo en 17031ms (Abrir transaccion TIA: OK)
Construir diccionario: saliendo en 63ms (Construir diccionario: OK)
```

El operario ve "OK" en operaciones que tardaron 15 y 17 segundos contra
TIA. En el mismo log, el sync de dispositivos (que si tiene las ramas
vivas) si muestra "116 adds, 83 removes, 3 renames".

Ninguno de los 4 FBs rota tiene un test que compruebe el texto del
resumen: por eso el bug lleva tiempo vivo.

## 3. Diseno objetivo

### 3.1 Una sola declaracion

El paso se declara **una vez**, encima de su propio codigo, con su
nombre y su descripcion. El orden de los metodos es el orden del flujo:
se lee de arriba abajo, como un SFC.

```python
class FunctionDispSincronizar(FunctionBase):

    @step(
        "Exportar etiquetas",
        descripcion="Exporta del PLC las tablas de tags de dispositivos",
    )
    def _stage_1_exportar_tags(self) -> str:
        """Limpia sync/ y exporta las tablas selectivas al snapshot export."""
        ...
        return f"Exportar etiquetas: {len(self._ctx.selective_tables)} tablas exportadas"

    @step(
        "Calcular diferencias de dispositivos",
        descripcion="Compara los XML exportados con los dispositivos del Excel",
    )
    def _stage_2_compute_diff(self) -> str:
        ...
        return "Calcular diferencias de dispositivos: 116 adds, 83 removes, 3 renames"
```

Y **nada mas**: ni tabla `STAGES`, ni `steps=`, ni `run_step`, ni
`_step_summary`.

El metodo del step **devuelve su detail**, asi que el detalle no puede
quedarse desactualizado ni morir en silencio: lo escribe el mismo codigo
que hace el trabajo.

### 3.2 El motor recoge la declaracion y hace el dispatch

El motor recorre los metodos marcados con `@step` en **orden de
definicion** (`vars(klass)`, no `dir(klass)`, que ordenaria
alfabeticamente) y construye la lista de steps:

```python
    @classmethod
    def pasos_declarados(cls) -> list[StepSpec]:
        specs = []
        for klass in reversed(cls.__mro__):
            for _attr, value in vars(klass).items():
                spec = getattr(value, STEP_ATTR, None)
                if spec is not None:
                    specs.append(spec)
        return specs
```

`FunctionBase` ya normaliza `steps` a `list[dict]` y **tolera keys
extra** (`plc_function_base.py:82-85`), asi que anadir `"handler"` y
`"descripcion"` no rompe nada. El dispatch es una decena de lineas:

```python
    def _invoke_step_sync(self, idx: int) -> str:
        step = self.steps[idx]
        handler = step.get("handler")
        if handler is not None:
            outcome = getattr(self, handler)()
        else:
            outcome = self.run_step(idx, **self._params)   # compat
        if inspect.isawaitable(outcome):
            raise TypeError(...)
        return outcome
```

El fallback a `run_step` permite migrar FB a FB sin cambiar el motor
dos veces. Las dos formas **no se mezclan**: si un FB declara pasos con
`@step` y a la vez pasa `steps=`, el constructor lanza `ValueError`.
Una migracion a medias dejaria pasos sin ejecutar o ejecutados dos
veces, y ese fallo tiene que verse al arrancar, no tres minutos
despues contra el PLC.

### 3.3 Que gana cada parte

| Hoy | Despues |
|---|---|
| 2 declaraciones de los steps (65 + 65 lineas) | 1 declaracion (65 metodos con nombre + descripcion) |
| dispatch en 12 FBs (730 lineas) | dispatch en 1 sitio (el motor) |
| `_step_summary` en 8 FBs (350 lineas, 29 ramas muertas) | el detail lo devuelve el step que lo produce |
| el nombre del step vive en 3 sitios | en 1 sitio (imposible que diverjan) |
| el operario ve "OK" en 37 de 64 steps | ve el resumen real en todos |

### 3.4 El esqueleto unico

Los 12 FBs terminan con **el mismo molde**. Cambia el numero de steps y
el codigo de cada step; el esqueleto es el mismo:

```python
class FunctionX(FunctionBase):
    """Que hace el FB."""

    STEP_TIMEOUT_S: float = 300.0

    # ==================================================================
    # ZONA 0: deps inyectadas
    # ==================================================================
    def __init__(self, nombre=..., titulo=..., ..., tracker=None):
        super().__init__(nombre=nombre, titulo=titulo, tracker=tracker)
        self._config = config_manager
        self._tia_client = tia_client
        self._ctx: XContext | None = None

    # ==================================================================
    # ZONA 1: on_start
    # ==================================================================
    def on_start(self, **params: Any) -> None:
        """Pre-flight: valida los params y crea el ctx."""
        ...

    # ==================================================================
    # ZONA 2: los pasos (un metodo por step, en orden de flujo)
    # ==================================================================
    @step("Nombre visible", descripcion="Que hace este paso")
    def _stage_1_lo_que_sea(self) -> str:
        """Docstring del paso."""
        ...
        return "detail: lo que ve el operario"

    @step("Otro nombre visible", descripcion="...")
    def _stage_2_otro(self) -> str:
        ...

    # ==================================================================
    # ZONA 3: on_finish
    # ==================================================================
    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` con la shape que espera el caller."""
        self.result = {...}
```

Reglas del molde:

- Los hooks son siempre `on_start` / `on_finish`. `run_step` desaparece.
- Un step = un metodo decorado con `@step`, que **devuelve su detail**.
- El nombre del metodo lleva su numero: `_stage_N_<slug>`.
- El estado entre steps vive en el ctx (`self._ctx`), no en atributos
  sueltos.
- Los lazy imports van **dentro** del metodo del step que los usa.

### 3.5 En que se diferencian hoy (MEDIDO)

De los 12 FBs, la mayoria ya coincide en `on_start` / `on_finish` /
`run_step`. Se diferencian en 5 ejes:

| Eje | Como esta hoy | Objetivo |
|---|---|---|
| Metodos de step | 9/12 tienen `_stage_N_*`; los 3 de `core` tienen 0 (la logica vive dentro del `case`) | 12/12 con un metodo por step |
| Detail | 8/12 con `_step_summary`; `excel_cargar` lo devuelve el metodo; 3 de `core` inline en el `case` | 12/12: el detail lo devuelve el step |
| Estado (Zona 3) | 8/12 con dataclass ctx; `excel_cargar` y los 3 de `core` usan atributos sueltos en `self` | 12/12 con ctx (salvo `excel_cargar`, que tiene 1 step) |
| Lazy imports | Dentro del metodo en 7 del area; dentro de `run_step` en `proc_crear_generar_preview` y los 3 de `core` | Dentro del metodo del step, en los 12 |
| Slug del metodo | Mezclado: `_stage_1_exportar_tags` (ingles) junto a `_stage_1_leer_manifest` (espanol) | Ver §6 |

### 3.6 Lo que NO se toca

**El ctx**: 8 dataclasses propios (`DispSyncContext`, `ProcSyncContext`,
...), con `ProcProcessGenContext` **duplicado campo por campo** en 2
ficheros. Se puede unificar el duplicado, pero un ctx comun NO
recomienda: comparten 5-6 campos de deps y luego divergen fuerte
(`nmax_ops`/`rename_ops` vs `slot_map`/`preal_current` vs
`constant_ops`/`comment_ops`). Un ctx comun seria un dataclass con ~40
campos opcionales: el coste de tipado supera el beneficio (INFERIDO).

Lo que si se hace: **cada FB tiene su ctx**, tambien los 3 de `core`
(que hoy guardan el estado en atributos sueltos de `self`). El ctx no
se unifica entre FBs: cada uno tiene el suyo.

**El contrato con el resto del sistema** (MEDIDO, ver §4).

## 4. Contrato intocable

Lo de fuera de los FBs no se toca (MEDIDO):

| Consumidor | Que lee del FB | Donde |
|---|---|---|
| Engine OB1 | `fb.execute(**params)` | `plc_engine.py:307` |
| Engine | `fb.is_terminal()`, `fb.request_cancel()`, `fb.error_msg` | `plc_engine.py:154,203,299,312` |
| Engine / SSE | `fb._on_nstep_change` | `plc_engine.py:105`, `sse_publishers.py:346` |
| Publisher SSE | `fb.nStep`, `fb.result`, `fb.error_msg` | `sse_publishers.py:169-178` |
| Router `/status` | `fb.nStep`, `fb.result`, `fb.error_msg` | `routers/plc.py:102-108` |
| Tracker | `fb.nombre`, `fb.titulo`, los nombres de `fb.steps` | `plc_function_base.py:456-460` |
| SPA | `progress.stages[]` (del tracker) y `fb_state` | `store.js:1293`, `ProgressIndicator.js:84` |

`fb.steps` **no se lee fuera del motor**: es contrato interno
(MEDIDO). Los routers solo hacen `engine.submit("<nombre_fb>", **params)`.

**El timeout** es una constante de clase por FB (`STEP_TIMEOUT_S`), no
por step (MEDIDO). El motor ya resuelve `self._step_timeout_s` y el
dict de `steps`Tolera metadata futura, asi que admitir timeout por
step seria un cambio local al motor. No hace falta ahora.

## 5. Plan

Cada paso es un commit. En los pasos de migracion, **1 commit por FB**
(el area y el core por separado, ficheros disjuntos: se pueden paralelizar).

| Paso | Que | Ficheros | Riesgo |
|---|---|---|---|
| 0 | El motor acepta los pasos declarados con `@step` y hace el dispatch, con fallback a `run_step`. Las dos formas no se mezclan: `@step` + `steps=` a la vez es `ValueError`. Guard: ningun handler es async (sustituye al guard actual que mira `run_step`). | `plc_function_base.py` + su test | Bajo: el fallback deja los 12 FBs igual |
| 1 | Piloto: `subir_excel` (1 step, 332 lineas) migrado al patron nuevo | `function_excel_cargar.py` + tests | Bajo |
| 2 | Migrar los 9 FBs del area. Por cada uno: poner `@step` en cada metodo, borrar `STAGES` y `steps=`, borrar `run_step`, mover el detail al handler, borrar su `_step_summary` | 1 FB + sus tests | Medio: toca tests que dependen de la forma |
| 3 | Migrar los 3 FBs de `core`: extraer la logica de cada `case` a un metodo `_stage_N_*` (conservando los nombres) y declararlos | 3 FBs + sus tests | Medio: la logica se mueve de sitio |
| 4 | Limpieza: unificar el `ProcProcessGenContext` duplicado, borrar los `_step_summary` muertos, actualizar `AGENTS.md` §7, `docs/HOWTO_CREATE_FB.md` y `docs/HOWTO_ADD_DEVICE.md` (cierran metodos privados), anadir el guard "ningun step cae al fallback" | docs + 2 ficheros de codigo | Bajo |

### 5.1 Tests que hay que migrar (MEDIDO)

12 test-funciones en 4 ficheros dependen de la forma:

- `test_function_entidades_generar_preview.py:635-650` — `len(STAGES) == len(steps)` + igualdad nombre a nombre.
- `test_function_entidades_sincronizar.py:37-49,158-197,431-432` — cuenta de `STAGES`, `fb.run_step(0)`, `fb.steps = [...]` esperando `ValueError`.
- `test_function_proc_crear_generar_preview.py:260-274`, `test_function_proc_crear_sincronizar.py:355-365`, `test_function_entidades_sincronizar.py:397-402` — `iscoroutinefunction(FB.run_step)`.
- `test_disp_sync_contadores.py:104,120` y `test_disp_sync_export_estructura.py` — llaman `_step_summary(...)`.

Ademas, 2 asserts de `inspect.iscoroutinefunction(FB.run_step)` en los
tests de `block_edit` (`test_function_block_edit_prepare.py:220-228`,
`test_function_block_edit_apply.py:442-444`) → si `run_step` desaparece
de la clase, `AttributeError`. El guard nuevo (que ningun handler sea
async) es **mas fuerte** que el actual.

Los **85 mocks/invocaciones** de metodos privados `_stage_N_*`
(`test_function_proc_db_sincronizar.py` 23, `test_entidades_sincronizar_d3_to_d6.py`
16, `test_entidades_sincronizar_d2.py` 14, `test_function_entidades_generar_preview.py`
8, `test_function_proc_db_generar_preview.py` 7, `test_disp_sync_contadores.py` 6,
`test_disp_sync_export_estructura.py` 4, `test_function_proc_crear_generar_preview.py` 4,
`test_function_entidades_sincronizar.py` 3) **no se tocan** si los
handlers se llaman igual que hoy.

### 5.2 Que hay que tocar en cada FB (MEDIDO)

Inventario de los 12 FBs: pasos, forma del dispatch, refs de test a los
metodos privados, y si el `_step_summary` tiene la rama viva.

| FB | steps | dispatch hoy | refs `_stage_*` | `_step_summary` | Que hay que hacer |
|---|---|---|---|---|---|
| `function_excel_cargar.py` | 1 | `STAGES` + `run_step` | 0 | no tiene | **Piloto.** Ya devuelve el detail desde el metodo. Solo falta el decorador, borrar `STAGES` y borrar `run_step`. **Overridea `execute()`** (borra el temporal): no se toca. Sin ctx (1 step): se queda con sus atributos |
| `function_disp_generar_preview.py` | 4 | `STAGES` + `run_step` | 1 | 4/4 muertas | El detail pasa al handler: **4 steps dejan de mostrar "OK"** |
| `function_proc_crear_generar_preview.py` | 8 | `STAGES` + `run_step` | 0 | 7/8 muertas | Igual: **7 steps dejan de mostrar "OK"**. El lazy import baja del `run_step` al metodo |
| `function_proc_crear_sincronizar.py` | 10 | `STAGES` + `run_step` | 2 | 9/9 muertas | Igual: **10 steps dejan de mostrar "OK"** |
| `function_proc_db_sincronizar.py` | 9 | `STAGES` + `run_step` | 37 | 9/9 muertas | Igual: **9 steps dejan de mostrar "OK"**. El summary lee `fb._compile_result`: al moverlo al handler pasa a `self._compile_result` |
| `function_proc_db_generar_preview.py` | 6 | `STAGES` + `run_step` | 39 | 6/6 vivas | Mover las 6 ramas al handler |
| `function_entidades_generar_preview.py` | 5 | `STAGES` + `run_step` | 31 | 5/5 vivas | Mover las 5 ramas al handler |
| `function_disp_sincronizar.py` | 11 | `STAGES` + `run_step` | 46 | 11/11 vivas | Mover las 11 ramas al handler |
| `function_entidades_sincronizar.py` | 11 | `STAGES` + `run_step` | 72 | 4/11 vivas | El de mas refs de test. Mover las 4 ramas vivas: **7 steps dejan de mostrar "OK"** |
| `function_scan_plc_blocks.py` | 2 | `match/case` | 0 | - | Extraer 2 metodos y su ctx. Los nombres de step son **internos** (`"check_cache"`, `"escanear"`): se conservan tal cual |
| `function_block_edit_prepare.py` | 5 | `match/case` | 0 | - | Extraer 5 metodos y su ctx (la logica vive dentro del `case`). Los lazy imports pasan al metodo |
| `function_block_edit_apply.py` | 5 | `match/case` | 0 | - | Extraer 5 metodos y su ctx, igual |

Total: **77 steps** (65 en el area, 12 en `core`).

Los metodos **se renombran** al slug unificado (§6.1): cada commit de
migracion renombra los suyos y actualiza las refs de sus propios tests.
Ademas hay que migrar los tests que miran la *forma* (`STAGES`,
`run_step`, `_step_summary`), que son 13 ficheros.

**Ojo: hay tests que tocaban a 2 FBs** (MEDIDO). Seis ficheros de test
tienen refs a metodos de 2 o 3 FBs distintos, y **3 slugs cambian de
nombre en un FB pero no en el otro** (`_stage_2_compute_diff`,
`_stage_6_exportar_post_tx_a`, `_stage_7_editar_xmls_offline`). En
esos ficheros, un reemplazo a pelo de la cadena renombraria la ref del
otro FB y lo dejaria apuntando a un metodo inexistente.

Regla: **el renombrado en un test compartido se hace por destino**, no
por cadena. Cada commit cambia solo las refs que apuntan al FB que
migra en ese commit.

La red de seguridad es la propia suite: un `patch.object` sobre un
metodo que ya no existe revienta con `AttributeError`, asi que un
renombrado mal hecho sale a **test rojo**, nunca a test verde roto.

### 5.3 Orden de los commits

13 commits: 1 de motor + 1 por FB + 1 de limpieza. Cada commit con la
suite completa en verde.

1. **Motor**: el base acepta los pasos declarados con `@step` y hace el
   dispatch por `handler`, con fallback a `run_step`. Los 12 FBs siguen
   como estan (el fallback los deja igual). Guard nuevo: ningun handler
   es async.
2. `excel_cargar` (piloto, 1 step, 0 refs).
3. `disp_generar_preview` (4 steps, 1 ref): arregla 4 "OK".
4. `proc_crear_generar_preview` (8 steps, 0 refs): arregla 7 "OK".
5. `proc_crear_sincronizar` (10 steps, 2 refs): arregla 10 "OK".
6. `proc_db_sincronizar` (9 steps, 37 refs): arregla 9 "OK".
7. `proc_db_generar_preview` (6 steps, 39 refs).
8. `entidades_generar_preview` (5 steps, 31 refs).
9. `disp_sincronizar` (11 steps, 46 refs).
10. `entidades_sincronizar` (11 steps, 72 refs): el de mas refs.
11. `scan_plc_blocks` (2 steps).
12. `block_edit_prepare` (5 steps).
13. `block_edit_apply` (5 steps).
14. **Limpieza**: borrar `run_step` y el parametro `steps=` del base,
    unificar el `ProcProcessGenContext` duplicado, actualizar
    `AGENTS.md` §7 y `docs/HOWTO_CREATE_FB.md`, y anadir los guards
    "ningun step cae al fallback" y "el slug es el snake_case del
    nombre visible".

Los 4 primeros FBs migrados (3-6) arreglan **30 de los 37 "OK"** y son
los de menos refs de test: el patron se asienta donde el riesgo es
menor y donde el operario ve el cambio.

### 5.4 Trampas

- **9 patches de `scan_plc_blocks`** apuntan al **simbolo de modulo**
  (`test_function_block_edit_apply.py` 6 + `test_fbs_reset_run_state.py` 3). Si el
  import pasa a lazy dentro del metodo del step, esos 9 patches se rompen.
- **`subir_excel` overridea `execute()`** (`function_excel_cargar.py:119-132`): si
  cambia la firma o la semantica de `execute`, se rompe.
- **`ProcProcessGenContext` duplicado** en 2 ficheros: al unificar, revisar
  los imports.
- La doc de `AGENTS.md` §7 y `docs/HOWTO_CREATE_FB.md` describen el
  patron actual (tabla `STAGES` + `_step_summary`): hay que actualizarlas.
- `docs/HOWTO_ADD_DEVICE.md:225` y `areas/alimentacion/helpers/proc/proc_db_generar_preview.py:12`
  citan metodos privados: se actualizan al renombrar (ver §6.1).
- **Seis ficheros de test tienen refs a metodos de 2 o 3 FBs** (MEDIDO).
  Tres slugs cambian de nombre en un FB pero no en el otro, asi que un
  reemplazo a pelo de la cadena en un test compartido rompe la ref del
  otro FB. Renombrar **por destino** (ver §5.2).
- `docs/ESTADO_RUNTIME_OB1.md:157-160` afirma que
  `proc_process_crear_router.py` lee `fb.result` en el mismo request: ya
  no es cierto (grep actual: 0 matches). Doc obsoleto.

## 6. Decisiones tomadas

Formato aprobado: **A** (declarador `@step` sobre el metodo del paso,
orden de definicion = orden del flujo, el detail lo devuelve el handler).

1. **El slug del metodo de cada step se unifica**: es el snake_case del
   **nombre visible** del step. Ver §6.1.
2. **Se conservan los nombres visibles de los steps** ("Exportar
   etiquetas", "Abrir transaccion TIA"). Son las etiquetas que ve el
   operario en la barra de progreso; renombrarlos es un cambio de UX,
   no un refactor.
3. **El detail lo devuelve el handler y se borra `_step_summary`.**
   Es lo que hace imposible el bug de las 29 ramas muertas, y devuelve
   el detalle al step que lo produce.
4. **No se unifica el ctx** (salvo el duplicado exacto
   `ProcProcessGenContext`). Pero **cada FB tiene el suyo**: los 3 de
   `core` reciben uno, porque hoy guardan el estado en atributos
   sueltos de `self`.
5. **No hay timeout por step.** El motor ya lo tolera; anadirlo es un
   cambio local si algun dia hace falta.

### 6.1 Regla de nombres de los metodos de step

**El slug es el nombre visible en snake_case.** La regla es mecanica,
para que no haya margen a la interpretacion:

1. nombre visible -> minusculas
2. se quitan los acentos
3. todo lo que no sea `[a-z0-9_]` pasa a `_`
4. se colapsan los `_` repetidos y se quitan los de los extremos
5. los acronimos se quedan como estan (TIA, N_MAX, XML, SD, SCL, DTO,
   Tx, DB)

Ejemplos: "Exportar etiquetas" -> `_stage_1_exportar_etiquetas`,
"Esperar consolidación TIA" -> `_stage_5_esperar_consolidacion_tia`,
"Aplicar N_MAX y renombres" -> `_stage_4_aplicar_n_max_y_renombres`.

Con eso los 12 FBs comparten el mismo criterio y el metodo se lee como
el nombre que ve el operario.

**Coste del renombrado (MEDIDO)**: 52 de los 65 slugs del area cambian.
177 referencias en 9 ficheros de test, 150 dentro de los propios FBs
(la tabla `STAGES`, las definiciones y los docstrings que se citan
entre steps) y 1 en un documento real (`HOWTO_ADD_DEVICE.md:225`).
Todo mecanico: la suite lo verifica.

**9 slugs siguen siendo el mismo nombre en 2 o 3 FBs** tras el
renombrado (mismo nombre visible en los dos FBs), asi que no hay
conflicto: son metodos de clases distintas. Los 3 que **si** se
resuelven (el mismo nombre viejo daba nombres nuevos distintos) son
`_stage_2_compute_diff`, `_stage_6_exportar_post_tx_a` y
`_stage_7_editar_xmls_offline`.

**El guard** que lo fija para siempre: para cada FB, el nombre del
metodo de cada step debe ser `_stage_N_<snake_case(nombre visible)>`.
Es el mismo tipo de guard estructural que ya hay en el repo (AST sobre
los FBs), asi que no necesita ningun dato del runtime: se comprueba
con el AST y la lista de nombres visibles.

### 6.2 Demo en `demo/`

La demo del formato A esta en `demo/` (no toca la aplicacion):

| Fichero | Que es |
|---|---|
| `demo/antes_*.py` | Extractos literales del motor y del FB reales (commit `a5be3d8`) |
| `demo/despues_*.py` | El motor y el FB propuestos |
| `demo/diagrama_sfc.py` | Genera el diagrama SFC (ASCII y mermaid) desde la misma declaracion |
| `demo/demo_disp_sync.py` | Ejecuta el FB propuesto de punta a punta, sin TIA |

```powershell
python demo/diagrama_sfc.py     # el diagrama del FB, de la declaracion
python demo/demo_disp_sync.py   # el FB ejecutandose, con el detail de cada paso
```


## 7. Lo que este refactor NO arregla

- El caso 5a de D4 (nombre colisionado + uid en `removed`): es
  preexistente y esta fuera de este refactor.
- El riesgo abierto de `proc_db_sincronizar` (import de bloques con
  layout plano, no ejercitado con cambios reales).
- El smoke del block edit (`block_edit_prepare` + `block_edit_apply`),
  que sigue sin cobertura en vivo.
