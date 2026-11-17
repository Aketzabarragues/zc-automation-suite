---
description: "Mapa del codigo de zc-automation-suite: backend Python (nucleo, tia_ops, simatic, areas), frontend Vue, tests, scripts y docs."
read_if: "Antes de leer o modificar codigo del proyecto; para saber que modulo existe, donde vive y que area lo posee."
---

# Shared Project Index

## Architecture

- App de escritorio (Windows, un solo operario) que automatiza proyectos de Siemens TIA Portal con el SDK oficial `siemens_tia_scripting`. Se empaqueta en un `.exe` portable con PyInstaller.
- **Un solo hilo** posee el portal de TIA. Todo trabajo se ejecuta **entero** dentro de ese hilo; no hay cola de comandos ni hilos por paso.
- Contrato de trabajo: `job.empezar(titulo, pasos)` + `with job.paso(nombre)` + `with transaccion(job, texto)`. Solo los ficheros en `funciones/` reciben el `job`.
- Preview y aplicacion son la **misma funcion** con `aplicar=False` / `aplicar=True`. No hay pares preview/operar.
- La SPA habla con el backend por SSE (`progress`, `job`, `log`, `tia`); el resultado de un POST nunca vuelve en el body, vuelve por el bus de eventos.
- Capas y dependencias: `nucleo/` (app, web, tia) -> `tia_ops/` (SDK) y `simatic/` (ficheros TIA offline) <- `areas/<id>/` (logica de negocio). El nucleo no importa `areas/` salvo la lista `AREAS` de `main.py`; las areas no se importan entre si.
- La logica de dominio (fuera de `funciones/`) es pura: no importa `zc_suite.nucleo.tia` ni `zc_suite.tia_ops`. Lo verifican `tests/test_fronteras.py` y `tests/test_fronteras_dominio.py`.
- Todo en espanol: ficheros, carpetas, funciones y variables, sin tildes ni anglicismos en los identificadores.
- Frontend: Vue 3 + Pinia + Vite + Tailwind v4. Lo del nucleo vive en `src/nucleo/`, lo del area en `src/areas/<area>/`.

## Project Index

- `CONTRIBUTING.md` — Como se commitea, como se verifica y que se espera de cada cambio.
- `README.md` — Que es el proyecto, estado de la reescritura, requisitos e instalacion.
- `LICENSE` — MIT.
- `pyproject.toml` — Dependencias, config de ruff (line-length 100, py312) y de pytest (`--import-mode=importlib`, `filterwarnings=error`).
- `.gitattributes` — Marca `tests/fixtures/` con `-text`: git no toca sus bytes.
- `.gitignore` — Excluye `vendor/`, caches, `frontend/node_modules/`, `logs/`, `.build_cache/` y las cuarentena `_borrar/`, `_trash_temp/`.
- `iniciar.py` — Arranque de dev: backend Flask + Vite.
- `build_exe.py` — Empaquetado del `.exe` con PyInstaller.
- `run_build.bat` — Atajo de Windows para el empaquetado.
- `config/config.json` — Configuracion de la app y de las areas (formato nuevo; un config en formato de main muestra banner rojo).
- `docs/` — Documentacion de usuario y de mantenimiento.
- `scripts/` — Smokes contra TIA real.
- `backend/` — Paquete Python `zc_suite`.
- `frontend/` — SPA Vue 3.
- `tests/` — Suite de pytest, espeja `backend/zc_suite/`.

### `docs/` — Guias de uso, arquitectura y mantenimiento

- `CONFIG.md` — Formato de la seccion de config de un area.
- `NUEVA_AREA.md` — Como anadir un area.
- `NUEVO_DISPOSITIVO.md` — Como anadir un tipo de dispositivo.
- `FLUJOS_ALIMENTACION.md` — Los flujos de main y los cambios deliberados respecto a main.
- `MAPA_FB.md` — Mapa de los FB por area y fase.
- `PROBLEMAS.md` — Errores de runtime que los tests no pillan, con la receta del fix.
- `INSTALAR.md` — Instalacion, incluida la wheel oficial de Siemens.
- `TIA_OPENNESS.md` — Contrato y trampas del SDK TIA Openness: `import_blocks` sin `target_folder_path`, `compile()` devuelve un `ExecutionResult`, errores .NET pendientes, encoding y CRLF, fixtures byte a byte.
- `REESCRITURA_ESTADO.md` — Estado de la reescritura: fases 4.1-4.6, decisiones aprobadas con el operario, como se revisa una entrega contra main y que queda pendiente.
- `PERFIL_OPERARIO.md` — Preferencias durables del operario y el motivo de cada regla, para proponer disenos y refactors.
- `referencia_ui/REFERENCIA_UI.md` — Referencia visual de la UI.
- `referencia_ui/capturas/` — Capturas de pantalla de la UI, una por vista o estado.

### `backend/` — Paquete Python

- `zc_suite/errores.py` — `ZCError` y `OperacionError`: el contrato de errores.

#### `backend/zc_suite/nucleo/` — Nucleo: arranque, HTTP, hilo de TIA y sesion

- `sesion.py` — Estado de la sesion en memoria (PLCs, seleccion, escaneo con TTL 300 s, datos por area).
- `app/main.py` — Arranque de la app y la lista `AREAS`.
- `app/config.py` — Lectura y validacion de `config.json` con Pydantic.
- `app/logs.py` — Logging al fichero y a la consola.
- `app/bandeja.py`, `app/icono.py` — Icono en la bandeja del sistema via pystray.
- `app/servidor.py` — Servidor de la SPA.
- `web/app.py` — Flask: estaticos, `GET /api/eventos` y `lanzar()`.
- `web/rutas/` — Blueprints de `conexion`, `plc`, `catalogo`, `config`, `sesion`.
- `tia/servicio.py` — El hilo unico dueno del portal: conectar, desconectar, ping y trabajo.
- `tia/job.py` — `Job` y sus pasos.
- `tia/transaccion.py` — `transaccion(job, texto)`: start -> yield -> end, con rollback automatico.
- `tia/errores.py` — `TIAError` y los errores propios de TIA.
- `tia/eventos.py` — Bus SSE y handler de logging.
- `tia/workdir.py` — Carpeta de trabajo `.build_cache/<area>/<contexto>/`.
- `funciones/plc/listar_plcs.py`, `funciones/plc/escanear.py` — Trabajos de listado y escaneo de PLCs.
- `funciones/bloques/preparar.py`, `funciones/bloques/aplicar.py` — Trabajos de preparacion y aplicacion de bloques.

#### `backend/zc_suite/tia_ops/` — Operaciones contra el SDK de Siemens

Ningun objeto .NET sale de aqui: se devuelven `dict`, `list`, `str`, `int` y `bool`.

- `proyecto.py` — Apertura y acceso al proyecto.
- `exportar.py` — Exportacion de bloques y tablas.
- `importar.py` — Importacion. Ojo: `target_folder_path` no se pasa, nunca `""`.
- `compilar.py` — Compilacion. `compile()` devuelve un `ExecutionResult`, nunca un booleano.
- `constantes.py` — Constantes de usuario.
- `bloques.py`, `tablas.py` — Operaciones sobre bloques y sobre tablas de tags.
- `_resolver.py` — Resolucion de nombres y rutas de objetos.

#### `backend/zc_suite/simatic/` — Ficheros TIA manipulados offline

- `ml/constantes_parser.py`, `ml/constantes_modificador.py` — Lectura y modificacion de constantes en SimaticML.
- `ml/rutas_xml.py` — Rutas dentro del XML.
- `sd/cabecera.py`, `sd/comentarios_array.py`, `sd/mlc.py` — Cabecera, array de comentarios y MLC de SimaticSD. Encoding: `.s7res` utf-8-sig, resto utf-8 sin BOM; saltos de linea CRLF fijos.

#### `backend/zc_suite/areas/` — Logica de negocio por area

- `__init__.py` — Base del paquete de areas.

##### `areas/alimentacion/` — El area de alimentacion (la unica registrada hoy)

- `__init__.py` — `ID`, `NOMBRE`, `ALMACEN`, `rutas`, `catalogo()`, `defaults()`, `al_arrancar()`, `estado_sesion()`, `valida_config()`. `ALMACEN` es contrato del area: la recarga de config depende de el.
- `config.py` — Modelo del config del area.
- `rutas.py` — Blueprint del area.
- `excel/` — El Excel maestro: `parser.py` (uno solo, lo usan todas las fases), `modelo.py`, `tablas.py` (campos por dominio), `columnas.py`, `almacen.py` (en memoria, no en disco).
- `dispositivos/` — `catalogo.py`, `diferencias.py`, `sincronizacion.py`.
- `entidades/` — `diferencias.py`, `sincronizacion.py`.
- `procesos/` — `mapa.py`, `plantillas.py`, `clonacion.py`, `diferencias.py`, `sincronizacion.py`.
- `funciones/dispositivos/generar_prevision.py`, `funciones/dispositivos/sincronizar.py` — FB de dispositivos.
- `funciones/entidades/generar_prevision.py`, `funciones/entidades/sincronizar.py` — FB de entidades.
- `funciones/procesos/generar_prevision.py`, `funciones/procesos/sincronizar.py` — FB de procesos.
- `funciones/procesos/generar_prevision_crear.py`, `funciones/procesos/crear.py` — FB de crear un proceso desde plantilla.
- `funciones/excel/cargar.py` — FB de carga del Excel.

### `frontend/` — SPA Vue 3

- `vite.config.js` — Vite + Tailwind v4 + config de Vitest (jsdom, `src/**/*.spec.js`).
- `package.json` — Scripts `dev`, `build`, `preview`, `test` (vitest run).
- `index.html`, `public/logo-zeus-control.png` — Entrada y recurso estatico.
- `src/main.js` — Punto de entrada.
- `src/App.vue` — Shell de la SPA.
- `src/areas/index.js` — Registro de areas del frontend.

#### `frontend/src/nucleo/` — Lo comun a todas las areas

- `api.js` — Cliente HTTP de la API.
- `eventos.js` — Suscripcion SSE y reparto de eventos a los stores.
- `demo.js` — Datos de demo.
- `vistas/Plc.vue` — Vista de PLC (conexion, escaneo, editor de bloques).
- `vistas/EditorBloques.vue` — Editor de bloques y variables.
- `componentes/` — `ShellSidebar.vue`, `ShellTopbar.vue`, `BannerConfig.vue`, `Bienvenida.vue`, `ConsolaLogs.vue`, `DialogoConfirmacion.vue`, `FaceplateProgreso.vue`.
- `stores/` — `areas.js`, `config.js`, `logs.js`, `plc.js`, `sesion.js`, `tia.js`, `trabajos.js`.

#### `frontend/src/areas/alimentacion/` — El area de alimentacion

- `index.js` — Exporta `{id, nombre, rutas, menu}`.
- `vistas/Inicio.vue` — Inicio del area.
- `vistas/Dispositivos.vue`, `vistas/Entidades.vue`, `vistas/Procesos.vue` — Vistas de cada dominio.
- `vistas/CrearProceso.vue` — Crear un proceso desde una plantilla.
- `vistas/DefinicionProgramacion.vue` — Definicion de programacion.
- `stores/` — `excel.js`, `dispositivos.js`, `entidades.js`, `procesos.js`, `crear_proceso.js`.

### `tests/` — Suite de pytest (espeja `backend/zc_suite/`)

- `conftest.py` — Fixtures compartidos (van aqui, no como funciones importadas).
- `_dobles.py` — Dobles de TIA compartidos por los conftest (`PlcSyncFalso`, `ProyectoFalso`, `PortalFalso`, `TsFalso` y variantes). Se importa como `tests._dobles`: `pyproject.toml` lleva `pythonpath = ["backend", "."]` porque `tests/` no es paquete (no lleva `__init__.py`, para no romper la recogida con `--import-mode=importlib`).
- `test_fronteras.py` — El nucleo no importa areas y las areas no se importan entre si.
- `test_fronteras_dominio.py` — La logica de dominio no depende de TIA.
- `test_errores.py` — La jerarquia `ZCError` / `TIAError`.
- `test_vocabulario.py` — El nucleo habla el idioma de TIA, no el del area.
- `test_docs_agente.py` — Los docs de agente citan rutas que existen.
- `test_smoke.py`, `test_smokes.py` — Los smokes de `scripts/smoke/` estan bien formados.
- `nucleo/app/`, `nucleo/web/`, `nucleo/tia/`, `nucleo/funciones/`, `nucleo/test_sesion.py` — Tests del nucleo.
- `tia_ops/` — Tests de las operaciones contra el SDK, con dobles propios.
- `simatic/ml/`, `simatic/sd/`, `simatic/test_paridad_simatic.py` — Tests de los ficheros TIA offline.
- `areas/alimentacion/` — Tests del area, con `<dominio>/` y `funciones/<dominio>/`.
- `fixtures/source/` — Ficheros TIA de partida.
- `fixtures/expected/` — Salida esperada, comparada byte a byte.

### `scripts/smoke/` — Smokes contra TIA real (se lanzan a mano)

- `exportar.py`, `importar.py`, `compilar.py`, `bloques.py`, `constantes.py` — Smokes del nucleo y de `tia_ops`.
- `dispositivos_generar_prevision.py`, `dispositivos_sincronizar.py` — Smokes de dispositivos.
- `entidades_generar_prevision.py`, `entidades_sincronizar.py` — Smokes de entidades.
- `procesos_generar_prevision.py`, `procesos_sincronizar.py`, `procesos_crear.py`, `procesos_crear_prevision.py` — Smokes de procesos.
