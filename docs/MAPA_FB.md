# Mapa de FBs: de `main` a la reescritura

En `main`, un **FB** (*Function Block*) era cada operacion con pasos que se
registraba en el motor:

```python
engine.register_fb("disp_generar_preview", FunctionDispGenerarPreview(...))
```

Los registraba el nucleo (`core/composition/register_core_fbs.py`) y cada area
(`areas/alimentacion/__init__.py::register`). Los doce estan listados abajo.

En la reescritura **no hay FBs**. Cada operacion es una **funcion de trabajo**
que recibe el `job`, declara sus pasos y devuelve un dict de primitivos. El
motor (el hilo de TIA) la ejecuta entera y el resultado llega a la SPA por el
evento `job` del stream SSE.

## Las dos diferencias de fondo

| En `main` | En la reescritura |
|---|---|
| Un unico motor con la cola de FBs, un worker OT y el dispatcher del OB1 | Un unico hilo de TIA que ejecuta el trabajo **entero** |
| Una ruta generica para todos: `POST /api/v1/plc/fb/<nombre>/start` | Una ruta por operacion, con sus parametros y sus precondiciones |
| El resultado se publica en el `AppCache` y la SPA lo lee por sondeo | El resultado llega en el evento `job` del stream SSE |

El nombre del FB **no** se conserva tal cual: el trabajo se identifica por el
nombre de su funcion (`escanear_plc`, `cargar_excel`, `disp_generar_preview`),
que es lo que sale en el log y en el faceplate. Solo `disp_generar_preview`
coincide con el nombre que tenia en `main`.

## Los doce FBs de `main`

### Nucleo

| FB en `main` | Donde vive ahora | Ruta HTTP | Store / vista | Pasos del faceplate | Estado |
|---|---|---|---|---|---|
| `scan_plc_blocks`<br>`core/composition/function_scan_plc_blocks.py` | `zc_suite/nucleo/trabajos/plc.py::escanear_plc` | `POST /api/v1/tia/plcs/<plc>/escanear` | `nucleo/stores/plc.js` -> `nucleo/vistas/Plc.vue` | main: `check_cache`, `escanear`<br>ahora: `bloques`, `tablas`, `tipos` | **portado** |
| `block_edit_prepare`<br>`core/composition/function_block_edit_prepare.py` | `zc_suite/nucleo/trabajos/bloques.py::preparar_bloques` | `POST /api/v1/tia/plcs/<plc>/bloques/preparar` | `nucleo/vistas/EditorBloques.vue` | main: Validar seleccion, Leer bloques desde cache, Exportar bloques SD, Parsear headers SCL, Combinar DTOs en cache<br>ahora: `validar`, `leer`, `exportar`, `parsear`, `combinar` (los dos del SimaticSD solo en V21+) | **portado** |
| `block_edit_apply`<br>`core/composition/function_block_edit_apply.py` | `zc_suite/nucleo/trabajos/bloques.py::editar_bloques` | `POST /api/v1/tia/plcs/<plc>/bloques/editar` | `nucleo/vistas/EditorBloques.vue` | main: Validar edits, Calcular diff, Aplicar transaccion, Verificar resultado, Refrescar cache<br>ahora: `validar`, `diferencias`, `aplicar`, `verificar`, `refrescar` | **portado** |

### Area de alimentacion

| FB en `main` | Donde vive ahora | Ruta HTTP | Store / vista | Pasos del faceplate | Estado |
|---|---|---|---|---|---|
| `subir_excel`<br>`areas/alimentacion/functions/function_excel_cargar.py` | `zc_suite/areas/alimentacion/excel/trabajo.py::cargar_excel` | `POST /api/v1/areas/alimentacion/excel` | `areas/alimentacion/stores/excel.js` -> `areas/alimentacion/vistas/DefinicionProgramacion.vue` | main: Parsear y volcar Excel<br>ahora: `validar`, `parsear`, `guardar`, `avisos` | **portado** |
| `disp_generar_preview`<br>`areas/alimentacion/functions/function_disp_generar_preview.py` | `zc_suite/areas/alimentacion/dispositivos/trabajo.py::disp_generar_preview` | `POST /api/v1/areas/alimentacion/dispositivos/preview` | `areas/alimentacion/stores/dispositivos.js` -> `areas/alimentacion/vistas/Dispositivos.vue` | main: Exportar etiquetas, Calcular diferencias de dispositivos, Calcular diferencias de N_MAX, Componer respuesta<br>ahora: `exportar`, `dispositivos`, `n_max`, `componer` | **portado** |
| `disp_sincronizar`<br>`areas/alimentacion/functions/function_disp_sincronizar.py` | (a escribir) | (a escribir) | `areas/alimentacion/stores/dispositivos.js` -> `areas/alimentacion/vistas/Dispositivos.vue` | main: Exportar etiquetas, Calcular diferencias de dispositivos, Preparar operaciones, Aplicar N_MAX y renombres, Esperar consolidacion TIA, Re-exportar etiquetas, Editar archivos XML, Aplicar dispositivos, Compilar bloques, Aplicar comentarios, Generar preview post-sincronizacion<br>ahora: (a definir en la 4.3) | **pendiente** (fase 4.3) |
| `entidades_generar_preview`<br>`areas/alimentacion/functions/function_entidades_generar_preview.py` | (a escribir) | (a escribir) | (a escribir) | main: Exportar etiquetas y DB, Calcular diferencias de N_MAX_ENTIDAD, Calcular diferencias de constantes, Calcular diferencias de comentarios, Componer respuesta<br>ahora: (a definir) | **pendiente** (fase 4.4) |
| `entidades_sincronizar`<br>`areas/alimentacion/functions/function_entidades_sincronizar.py` | (a escribir) | (a escribir) | (a escribir) | main: Exportar etiquetas y DB, Calcular diferencias, Preparar operaciones, Aplicar NMAX online (Tx A), Esperar consolidacion TIA, Re-exportar etiquetas y DB, Editar XMLs offline, Aplicar constantes offline (Tx B), Compilar bloques, Aplicar comentarios offline (Tx C), Generar preview post-sincronizacion<br>ahora: (a definir) | **pendiente** (fase 4.4) |
| `proc_db_generar_preview`<br>`areas/alimentacion/functions/function_proc_db_generar_preview.py` | (a escribir) | (a escribir) | (a escribir) | main: Validar estado de TIA, Validar bloques, Construir mapa de slots, Calcular diferencias de N_MAX, Exportar y calcular diferencias, Componer respuesta<br>ahora: (a definir) | **pendiente** (fase 4.5) |
| `proc_db_sincronizar`<br>`areas/alimentacion/functions/function_proc_db_sincronizar.py` | (a escribir) | (a escribir) | (a escribir) | main: Validar estado de TIA, Validar bloques, Construir mapa de slots, Aplicar N_MAX, Esperar consolidacion TIA, Compilar bloques, Abrir transaccion TIA, Generar preview post-sincronizacion, Componer respuesta<br>ahora: (a definir) | **pendiente** (fase 4.5) |
| `proc_process_crear_preview`<br>`areas/alimentacion/functions/function_proc_crear_generar_preview.py` | (a escribir) | (a escribir) | (a escribir) | main: Leer manifiesto, Validar minimos, Copiar a vista previa, Construir diccionarios, Detectar colisiones, Validar dependencias, Generar previstos, Componer respuesta<br>ahora: (a definir) | **pendiente** (fase 4.6) |
| `proc_process_crear_aplicar`<br>`areas/alimentacion/functions/function_proc_crear_sincronizar.py` | (a escribir) | (a escribir) | (a escribir) | main: Leer manifiesto, Validar minimos, Copiar a vista previa, Construir diccionarios, Generar proceso nuevo, Escribir manifiesto modificado, Importar proceso, Compilar bloques, Refrescar BloqueCache, Componer respuesta<br>ahora: (a definir) | **pendiente** (fase 4.6) |

El numero de fase sale del orden de los flujos de
[`FLUJOS_ALIMENTACION.md`](FLUJOS_ALIMENTACION.md): primero los dispositivos
(4.2 y 4.3), luego las entidades (4.4), los procesos ya existentes (4.5) y
por ultimo la creacion de procesos (4.6). Si ese orden cambia, cambia aqui
tambien.

### Eliminados

Ninguno. Los doce FBs de `main` tienen sitio en la reescritura: cinco ya
estan portados y siete estan pendientes de fase. Lo que **no** se porta es el
motor que los sostenia (`PlcEngine`, el dispatcher del OB1 y el `AppCache`),
que en la reescritura son el hilo de TIA, el stream SSE y el almacen del area.

## Trabajos que en `main` no eran FB

En `main` esto eran *comandos* del cliente de TIA o rutas sueltas, no FBs. En
la reescritura son trabajos, pero sin pasos:

| En `main` | Donde vive ahora | Ruta HTTP ahora | Store / vista |
|---|---|---|---|
| Conectar: `POST /api/v1/portal/attach` | `zc_suite/nucleo/tia/servicio.py::conectar` | `POST /api/v1/tia/conectar` | `nucleo/stores/tia.js` -> `nucleo/vistas/Plc.vue` |
| Desconectar: el `disconnect` del FB | `zc_suite/nucleo/tia/servicio.py::desconectar` | `POST /api/v1/tia/desconectar` | `nucleo/stores/tia.js` -> `nucleo/vistas/Plc.vue` |
| Listar PLCs: `GET /api/v1/plcs` | `zc_suite/nucleo/trabajos/plc.py::buscar_plcs` | `POST /api/v1/tia/plcs/listar` | `nucleo/stores/plc.js` -> `nucleo/vistas/Plc.vue` |
| Recargar el Excel guardado | `zc_suite/areas/alimentacion/excel/trabajo.py::recargar_excel` | `POST /api/v1/areas/alimentacion/excel/recargar` | `areas/alimentacion/stores/excel.js` (la SPA recarga con un GET al subir) |

El catalogo de la SPA (`GET /api/v1/catalog`) y el estado de la conexion
(`GET /api/v1/tia/estado`) no son trabajos: son lecturas.

## Como se crea un trabajo nuevo

### 1. Donde va la funcion

La funcion va en el modulo que le corresponde por dominio:

- **Nucleo** (no depende de un area): `backend/zc_suite/nucleo/trabajos/`.
- **De un area**: dentro del area, en el modulo de su dominio. Por ejemplo,
  los dispositivos viven en
  `backend/zc_suite/areas/alimentacion/dispositivos/trabajo.py`.

Las operaciones puras contra TIA (leer, exportar, importar, compilar) van en
`backend/zc_suite/tia_ops/`. La funcion de trabajo solo las **orquesta**.

La funcion recibe el `job` y sus parametros, y **devuelve un dict de
primitivos** (`dict`, `list`, `str`, `int`, `bool`): nada de objetos .NET
salen de `tia_ops/`.

### 2. Como se declaran los pasos

```python
def mi_trabajo(job: Job, plc: str) -> dict[str, Any]:
    job.empezar(
        "Lo que ve el operario",
        [
            ("primer_paso", "Lo que ve el operario"),
            ("segundo_paso", "Lo que ve el operario"),
        ],
    )
    with job.paso("primer_paso") as paso:
        resultado = hacer_algo(job.tia.portal, plc)
        paso["detail"] = f"{len(resultado)} cosas"
    with job.paso("segundo_paso") as paso:
        paso["detail"] = "hecho"
    return {"resultado": resultado}
```

- `job.empezar(titulo, pasos)` declara **todos** los pasos al inicio. Cada
  paso es un identificador o una pareja `(identificador, etiqueta)`.
- `with job.paso("identificador") as paso:` marca el paso como en curso y lo
  cierra al salir. Si dentro salta una excepcion, el paso queda como `error`
  y la excepcion se vuelve a lanzar.
- `paso["detail"]` escribe una linea de detalle: es lo que sale en el
  faceplate y en el log.

El `job` tambien tiene `job.log(mensaje, nivel=...)`, que publica una linea
en la consola de la SPA.

### 3. Las transacciones

Las escrituras en TIA van **siempre** dentro de `transaccion(job, texto)`:

```python
from zc_suite.nucleo.tia.transaccion import transaccion

with job.paso("aplicar") as paso:
    with transaccion(job, "Editar bloques"):
        for nombre, propiedades in cambios.items():
            aplicados.append(
                aplicar_cambios(job.tia.portal, plc, nombre, dict(propiedades))
            )
    paso["detail"] = f"{len(aplicados)} bloques"
```

`transaccion` hace `start_transaction` -> yield -> `end_transaction(rollback=False)`.
Si salta cualquier excepcion, hace `end_transaction(rollback=True)` y vuelve a
lanzarla. Si el commit falla, tambien intenta el rollback y lanza
`TransaccionError` diciendo que fallo el commit.

Con **varias** transacciones en el mismo trabajo (el de sincronizar
dispositivos tiene tres), cada una comprueba su resultado y el trabajo dice
cual se confirmo, cual se revirtio y cual no se ejecuto.

Las compilaciones van **fuera** de la transaccion: no bloquean y solo avisan.

### 4. Como se registra la ruta

Una ruta por operacion, en el `Blueprint` que le toca:

- **Del nucleo**: `backend/zc_suite/rutas/<recurso>.py`. Se monta en
  `zc_suite/main.py::montar_app` con `rutas.<recurso>.registrar(app)`.
- **De un area**: `backend/zc_suite/areas/<id>/rutas.py`. Se monta sola: el
  area se registra en la lista `AREAS` de `zc_suite/main.py` y su `Blueprint`
  va con el.

La ruta **no toca el portal**: encola el trabajo en el hilo de TIA y responde
`202` con el `job_id`.

```python
@rutas.post("/plcs/<plc>/escanear")
def escanear(plc: str) -> tuple[Response, int]:
    """Encola el escaneo del PLC: bloques, tablas de tags y tipos de usuario."""
    return lanzar(trabajos.escanear_plc, plc=plc)
```

`lanzar()` es el de `zc_suite.nucleo.web.app`: mira el hilo de TIA, encola y responde
`202` con el `job_id` (o `409` si ya hay un trabajo en curso).

Las dependencias se leen de `current_app.config`, nunca de singletons.

### 5. Como se recoge el resultado en la SPA

La respuesta del POST no lleva el resultado: lleva el `job_id`. El resultado
llega despues por el stream de eventos.

En la SPA, el store espera al trabajo y lee su resultado:

```javascript
// frontend/src/nucleo/stores/plc.js
async escanear() {
  const respuesta = await escanearPlc(this.seleccionado);
  const job = await useTrabajosStore().esperar(respuesta.job_id);
  if (job.estado !== "ok") {
    this.error = job.error || "No se pudo escanear el PLC.";
    return;
  }
  const resultado = job.resultado || {};
  this.bloques = resultado.bloques || [];
  // ...
}
```

`trabajos.esperar(job_id)` devuelve el resultado tanto si el evento `job` ya
llego como si llega despues: el store guarda los trabajos terminados por id.

### Ejemplo real y minimo

El trabajo de escanear el PLC, tal y como esta en
`backend/zc_suite/nucleo/trabajos/plc.py`:

```python
def escanear_plc(job: Job, plc: str) -> dict[str, Any]:
    """Escanea el PLC: bloques, tablas de tags y tipos de usuario."""
    job.empezar(
        f"Escanear {plc}",
        [
            ("bloques", "Escanear bloques"),
            ("tablas", "Escanear tablas de tags"),
            ("tipos", "Escanear tipos de usuario"),
        ],
    )
    with job.paso("bloques") as paso:
        bloques = escanear_bloques(job.tia.portal, plc)
        paso["detail"] = f"{len(bloques)} bloques"
    with job.paso("tablas") as paso:
        tablas = escanear_tablas_tags(job.tia.portal, plc)
        paso["detail"] = f"{len(tablas)} tablas de tags"
    with job.paso("tipos") as paso:
        tipos = escanear_tipos_de_usuario(job.tia.portal, plc)
        paso["detail"] = f"{len(tipos)} tipos de usuario"
    return {"plc": plc, "bloques": bloques, "tablas": tablas, "tipos": tipos}
```

Y su ruta, en `backend/zc_suite/nucleo/web/rutas/plc.py`:

```python
@rutas.post("/plcs/<plc>/escanear")
def escanear(plc: str) -> tuple[Response, int]:
    """Encola el escaneo del PLC: bloques, tablas de tags y tipos de usuario."""
    return lanzar(trabajos.escanear_plc, plc=plc)
```

Y su uso en la SPA, en `frontend/src/nucleo/stores/plc.js`:

```javascript
async escanear() {
  if (!this.seleccionado) return;
  this.error = null;
  this.ocupado = true;
  const tia = useTiaStore();
  if (tia.demo) {
    const datos = datosDemo();
    this.bloques = datos.bloques;
    this.tablas = datos.tablas;
    this.tipos = datos.tipos;
    this.ocupado = false;
    return;
  }
  try {
    const respuesta = await escanearPlc(this.seleccionado);
    const job = await useTrabajosStore().esperar(respuesta.job_id);
    this.ocupado = false;
    if (job.estado !== "ok") {
      this.error = job.error || "No se pudo escanear el PLC.";
      return;
    }
    const resultado = job.resultado || {};
    this.bloques = resultado.bloques || [];
    this.tablas = resultado.tablas || [];
    this.tipos = resultado.tipos || [];
  } catch (error) {
    this.error = error.message;
    this.ocupado = false;
  }
},
```

## Las reglas que no se negocian

- Solo el codigo que corre dentro de un trabajo toca TIA, y siempre via
  `job.tia.portal`.
- Toda escritura en TIA va dentro de `with transaccion(job, texto):`.
- El resultado de un trabajo es un dict de primitivos, serializable a JSON.
- Un fallo es una **excepcion**, nunca un `{"ok": False}` que alguien tenga
  que comprobar.
