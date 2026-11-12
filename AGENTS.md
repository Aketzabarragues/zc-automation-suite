# AGENTS.md — zc-automation-suite

App de escritorio (Windows, un solo operario) que automatiza proyectos de
Siemens TIA Portal mediante el SDK oficial `siemens_tia_scripting`.

Lee este fichero antes de tocar codigo. Sus reglas son obligatorias.

## Reglas no negociables

1. Solo el codigo que corre dentro de un job toca TIA, siempre via
   `job.tia.portal`.
2. Toda escritura en TIA va dentro de `with transaccion(...)`.
3. Cada operacion tiene modo `aplicar=False`, que es el preview.
4. El nucleo no importa areas (salvo la lista `AREAS` de `main.py`) y las areas
   no se importan entre si. Lo verifica `tests/test_fronteras.py`.
5. La logica pura de los dominios (fuera de `funciones/`) no depende de TIA.
   Lo verifica `tests/test_fronteras_dominio.py`.
6. Ningun objeto .NET sale de `tia_ops/`: se devuelven `dict`, `list`, `str`,
   `int` y `bool`.
7. Python 3.12-3.14, type hints en todas las firmas, ruff limpio.
8. Sin asyncio. Sin CDN: todo funciona offline.
9. Fuera de alcance: base de datos, MCP, autenticacion, sistemas de plugins.

## Modelo de ejecucion

```
SPA --POST /api/...--> tia.lanzar(funcion, **params) --> job_id (202)
                             |
                             v
                   hilo unico de TIA
                   ejecuta el trabajo ENTERO
                             |
                             v
                   eventos SSE: progress, job, log, tia
```

- El resultado **no** vuelve en el body del POST. Vuelve por SSE.
- `202` = encolado (con `job_id`). `409` = hay un trabajo en curso.
- Un fallo en un trabajo no cambia el estado de la conexion.
- Conectar y desconectar del portal tambien son trabajos.

## Estructura

```
backend/zc_suite/
  errores.py          ZCError y OperacionError: el contrato de errores
  nucleo/app/        main.py (arranque + lista AREAS), config.py, logs.py,
                     bandeja.py, icono.py, servidor.py
  nucleo/web/        app.py (Flask, estaticos, /api/eventos, lanzar())
                     rutas/{conexion,plc,catalogo}.py
  nucleo/tia/        servicio.py (hilo unico, conectar/desconectar),
                     job.py (Job y sus pasos), transaccion.py, errores.py
                     (TIAError y los suyos), eventos.py (bus SSE + handler
                     de logging), workdir.py (.build_cache/<area>/<contexto>/)
  nucleo/funciones/  plc/buscar_plcs.py, plc/escanear.py,
                     bloques/preparar.py, bloques/aplicar.py
  tia_ops/           proyecto.py, exportar.py, importar.py, compilar.py,
                     constantes.py, bloques.py, tablas.py
  simatic/ml/        constantes_parser.py, constantes_modificador.py,
                     rutas_xml.py
  simatic/sd/        cabecera.py, comentarios_array.py, mlc.py
  areas/<id>/        ID, NOMBRE, rutas, catalogo(), defaults(), al_arrancar()
                     <id>/rutas.py con el Blueprint del area
                     <id>/funciones/    un FB por fichero
                     <id>/excel/        parser.py, modelo.py, tablas.py,
                                       columnas.py, almacen.py
                     <id>/dispositivos/ diferencias.py, catalogo.py
frontend/src/
  nucleo/            api.js, eventos.js, demo.js, componentes/, vistas/,
                     stores/
  areas/<area>/      index.js, vistas/, stores/
  App.vue  main.js  style.css
tests/               misma estructura que backend/zc_suite:
                     nucleo/{app,web,tia,funciones}/, tia_ops/,
                     simatic/{ml,sd}/, areas/<id>/{<dominio>,funciones}/,
                     fixtures/
scripts/smoke/       smokes contra TIA real (se lanzan a mano)
```

## Estructura y nombres

- **Todo en espanol**: ficheros, carpetas, funciones y variables. Sin
  tildes ni anglicismos en los identificadores.
- **Las carpetas de dominio van en plural**: `dispositivos/`, `excel/`,
  `entidades/`, `procesos/`.
- **Un fichero no repite el nombre de su carpeta**: `dispositivos/diferencias.py`
  y no `dispositivos/disp_diferencias.py`; `simatic/sd/mlc.py` y no
  `simatic/sd/generador_mlc.py`.
- **Un FB por fichero, en `funciones/<dominio>/<verbo>.py`**: la funcion de
  dentro se llama como el fichero (`def generar_prevision(job, ...)`). Son los
  **unicos** modulos que reciben el `job`, declaran pasos y abren
  `transaccion()`. Lo que solo usa el FB se queda como funcion privada de su
  fichero.
- **`<dominio>/` (fuera de `funciones/`) es logica pura**: no importa
  `zc_suite.nucleo.tia` ni `zc_suite.tia_ops`, ni recibe el `job`. Para lanzar
  un fallo esperado usa `zc_suite.errores`. Lo vigila
  `tests/test_fronteras_dominio.py`.
- **Los fallos esperados cuelgan de `ZCError`** (`zc_suite/errores.py`): se
  registran como warning y sin traceback. Lo inesperado, con traceback. Los
  errores propios de TIA cuelgan de `TIAError`, que a su vez cuelga de
  `ZCError`. Lo fija `tests/test_errores.py`.
- **En el frontend, lo del nucleo va en `src/nucleo/` y lo del area en
  `src/areas/<area>/`**. Un store del area nunca esta en `nucleo/stores/`.
- **`tests/` refleja `backend/zc_suite/` carpeta a carpeta**: un test vive
  junto al modulo que prueba.

## Como se ejecuta un trabajo

```python
def sincronizar(job: Job, plc: str, aplicar: bool) -> dict:
    job.empezar("Sincronizar dispositivos", ["exportar", "comparar", "aplicar"])
    with job.paso("exportar") as paso:
        exportado = exportar_bloques(job.tia.portal, plc)
        paso["detail"] = f"{len(exportado)} bloques"
    ...
    return {"cambios": n}
```

- `job.empezar(titulo, pasos)` declara **todos** los pasos al inicio.
- `with job.paso(nombre) as paso:` marca el paso `running` -> `done`, o `error`
  si salta una excepcion (y la re-lanza). Antes de empezar comprueba la
  cancelacion. `paso["detail"]` escribe una linea de detalle.
- `job.tia.portal` es la unica forma de llegar al portal. El portal es un
  objeto COM afin a hilo: leerlo desde un hilo que no sea el de TIA lanza
  `FueraDelHiloError`.
- El estado del trabajo son variables locales de la funcion. Nada de estado en
  instancias que sobreviva entre ejecuciones.
- `with transaccion(job, texto):` hace `start_transaction` -> yield ->
  `end_transaction(rollback=False)`. Si salta cualquier excepcion, hace
  `end_transaction(rollback=True)` y re-lanza, indicando en el mensaje si el
  rollback tambien fallo. Si el commit falla, tambien intenta el rollback y
  lanza `TransaccionError` diciendo que fallo el commit. El mensaje distingue
  siempre el fallo de la operacion del fallo del commit.
- Los fallos son **excepciones**, nunca un `{"ok": False}` que alguien tenga
  que comprobar.

### Cancelacion

La cancelacion es cooperativa y se respeta entre pasos: `tia.cancelar(job_id)`
marca el trabajo, y el siguiente `job.paso()` aborta con `CanceladoError`. El
trabajo termina con estado `cancelado`.

### Vida de la conexion

El hilo de TIA comprueba el portal al terminar cada trabajo y, cuando esta
ocioso, cada `INTERVALO_PING` segundos. Si el portal no responde, la conexion
pasa a desconectada y se publica el evento `tia`. Un fallo de trabajo, en
cambio, no cambia el estado de la conexion.

## Eventos SSE

`GET /api/eventos` emite cuatro tipos:

| tipo | cuando | carga |
|---|---|---|
| `progress` | cambia el avance | `active, operation, label, current, total, percent, stages[], started_at, finished_at, error` |
| `job` | termina un trabajo | `job, estado (ok\|error\|cancelado), resultado, error` |
| `log` | linea de log | `nivel, mensaje` |
| `tia` | cambia la conexion | `conectado, trabajo_actual, ultimo_error` |

Cada `stage` es `{id, label, status (pending\|running\|done\|error), detail,
started_at, finished_at}`. Al conectarse, un cliente recibe de inmediato el
ultimo `progress` y el ultimo `tia`.

## Anadir una operacion contra TIA

1. Si es generica, pon la funcion en `tia_ops/<modulo>.py`. Si es especifica de
   un area, ponla en el area. La funcion recibe el portal y devuelve
   primitivos.
2. Si escribe, envuelvela en `with transaccion(job, texto):`.
3. La operacion completa es UNA funcion con modo `aplicar=False` (preview) y
   `aplicar=True`. No existen pares preview/operar: el preview es la misma
   funcion con `aplicar=False`, y el post-preview tras aplicar es volver a
   llamarla con `aplicar=False`.
4. Si la operacion tiene varias transacciones (por ejemplo el sync de
   dispositivos), el resultado debe decir con claridad cuales se confirmaron si
   una falla a mitad.

## Anadir un endpoint

1. Ruta generica: `rutas/<recurso>.py` con un `Blueprint` de Flask. Ruta de
   area: `areas/<id>/rutas.py`. (El shell es Flask, no FastAPI.)
2. El router lee las dependencias de `current_app.config`. Nunca importes
   singletons globales en el router.
3. Si la operacion es larga, encola el trabajo con `tia.lanzar(...)` y responde
   `202` con el `job_id`. No esperes al resultado.
4. Codigos: `202` encolado, `400` entrada invalida, `404` no encontrado,
   `409` ocupado, `500` error interno.
5. Las POST comprueban la cabecera `Origin`: rechaza las que no vengan de la
   propia app.

## Anadir un area

1. Crea `backend/zc_suite/areas/<id>/__init__.py` con `ID`, `NOMBRE`, `rutas`
   (Blueprint), `catalogo(config)`, `defaults(config)` y `al_arrancar(seccion)`.
   `al_arrancar` se llama al montar la app, con la seccion de configuracion
   del area: ahi es donde el area recarga lo que tenga guardado (el Excel
   maestro, por ejemplo). No es opcional: todas las areas lo implementan.
2. Las rutas van en `backend/zc_suite/areas/<id>/rutas.py`, con el `Blueprint`
   del area. El `__init__.py` lo expone como `rutas`.
3. Registra el area en la lista `AREAS` de `backend/zc_suite/nucleo/app/main.py`. No hay
   registro automatico ni ganchos opcionales.
4. Frontend: `frontend/src/areas/<id>/index.js` exporta `{id, nombre, rutas,
   menu}`. El shell las recoge con `import.meta.glob`.
5. Tests en `tests/areas/<id>/`.

## Anadir un tipo de dispositivo

1. Anade el dataclass del catalogo en `areas/<id>/datos/`.
2. Anade la entrada en `config.json` (`areas.<id>.Dispositivos`).
3. Anade el dominio del tipo en `areas/<id>/excel/tablas.py`: sus campos, con
   los nombres y los tipos que usan las fases siguientes.
4. El `GET /api/v1/catalogo` lo recoge automaticamente (data-driven). No hay
   que tocar la SPA.

## El Excel maestro de un area

- El **modelo** (los campos de cada dominio) vive en `excel/tablas.py` y
  `excel/modelo.py`. El parser es **uno solo** y lo usan tal cual todas las
  fases: no se escribe un parser por operacion.
- El **almacen** guarda el modelo completo de cada fila. El `display_order`
  del `config.json` decide solo que columnas se ensenan; el `col_labels`
  del mismo catalogo decide como se titulan.
- Una hoja o una tabla que no esta **no es un error**: el dominio sale
  vacio y el trabajo lleva un aviso.

## Convenciones

- Nombre de archivo, clase y funcion: `<prefijo>_<verbo>_<concepto>`. Los
  prefijos de dominio van primero: `disp_*` (dispositivos), `proc_*`
  (procesos), `ent_*` (entidades). No inventes sufijos.
- Las funciones de dominio son puras y reciben kwargs explicitos. Sin
  singletons dentro de la logica.
- Los modulos nativos de TIA no se importan nunca en el proceso principal: el
  hilo de `tia.py` es su unico dueno.
- Comentarios: contrato, restricciones y nombres no obvios. Nada de planes,
  fechas ni narrativas de refactor.
- Nada de shims, re-exports ni alias "legacy". Si algo se llama distinto, se
  llama distinto.

## Tests

- Backend: `pytest tests/`. Nombra el fichero como el modulo que prueba
  (`tests/nucleo/test_tia.py`).
- Frontend: `npm test` en `frontend/` (Vitest). Nombra el spec como la vista
  (`vistas/Bloques.spec.js`).
- Mockea el portal con un doble de test propio (un objeto falso con
  `get_process_id`, `projects`, ...), nunca con el SDK real.
- Los tests verdes no sustituyen al smoke en vivo contra un proyecto de
  PRUEBA de TIA.

## Comandos

| Tarea | Comando |
|---|---|
| Instalar backend | `pip install -e ".[dev]"` |
| Tests backend | `python -m pytest tests/ -v` |
| Lint | `python -m ruff check .` |
| Dev (backend + vite) | `python iniciar.py` |
| Tests frontend | `npm test` (en `frontend/`) |
| Build frontend | `npm run build` (en `frontend/`) |
| Empaquetar .exe | `python build_exe.py` |
