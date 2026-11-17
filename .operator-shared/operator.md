# Shared Operator Instructions

Instrucciones publicadas para el repo `zc-automation-suite`. Doctrina del
proyecto: reglas de arquitectura, estructura, codigo, commits y verificacion.
Es una version condensada de las instrucciones privadas del proyecto; si hay
conflicto con el codigo, manda el codigo.

## Que es este proyecto

App de escritorio (Windows, un solo operario) que automatiza proyectos de
Siemens TIA Portal con el SDK oficial `siemens_tia_scripting`: lee el Excel
maestro, exporta de los PLC los bloques y tablas afectados, calcula y muestra
las diferencias y, tras aprobacion, modifica los ficheros exportados offline y
los reimporta en TIA dentro de una transaccion con rollback. .exe portable
con PyInstaller.

## Reglas de arquitectura no negociables

1. Solo el codigo que corre dentro de un job toca TIA, siempre via
   `job.tia.portal`.
2. Toda escritura en TIA va dentro de `with transaccion(...)`.
3. Prevision y aplicacion son FBs distintos: la prevision no escribe (ni en
   TIA ni en el disco de salida) y la que aplica escribe dentro de
   `with transaccion(job, texto):`.
4. El nucleo no importa areas (salvo la lista `AREAS` de `main.py`) y las
   areas no se importan entre si. Lo verifica `tests/test_fronteras.py`.
5. La logica pura de los dominios (fuera de `funciones/`) no depende de TIA.
   Lo verifica `tests/test_fronteras_dominio.py`.
6. Ningun objeto .NET sale de `tia_ops/`: se devuelven `dict`, `list`, `str`,
   `int`, `bool`.
7. Python 3.12-3.14, type hints en todas las firmas, ruff limpio. Sin
   asyncio. Sin CDN: todo funciona offline.
8. Fuera de alcance: base de datos, MCP, autenticacion, sistemas de plugins.
9. `vendor/` no se versiona (binarios propietarios de Siemens, wheel oficial)
   y la app nunca lee de `vendor/` en runtime.
10. Cero `.pyd`/`.dll` en el arbol: se stagean en un temporal.
11. TIA: `target_folder_path` no se pasa (ni `""`).
12. Encoding: `.s7res` en `utf-8-sig` (BOM), el resto `utf-8` sin BOM.

## Contrato de ejecucion

- Flujo: `SPA --POST /api/...--> tia.lanzar(funcion, **params) --> 202 con
  job_id`. Un hilo unico de TIA ejecuta el trabajo entero; el resultado vuelve
  por SSE, **nunca** en el body del POST. `202` = encolado, `409` = ocupado.
- `job.empezar(titulo, pasos)` declara todos los pasos al inicio;
  `with job.paso(nombre) as paso:` gestiona `running` -> `done`/`error` y
  comprueba la cancelacion antes de empezar.
- `with transaccion(job, texto):` hace `start_transaction` -> yield ->
  `end_transaction(rollback=False)`; ante excepcion hace rollback y re-lanza.
  El mensaje distingue siempre el fallo de la operacion del fallo del commit.
- La cancelacion es cooperativa: `tia.cancelar(job_id)` y el siguiente
  `job.paso()` aborta con `CanceladoError`.
- El estado del trabajo son variables locales: nada de estado que sobreviva
  entre ejecuciones.
- Eventos SSE (`GET /api/eventos`): `progress` (avance y `stages[]`), `job`
  (fin de trabajo), `log` (linea de log), `tia` (estado de la conexion).
  Al conectarse el cliente recibe de inmediato el ultimo `progress` y el
  ultimo `tia`.

## Estructura y nombres

- **Todo en espanol**: ficheros, carpetas, funciones y variables. Sin tildes
  ni anglicismos en los identificadores.
- Carpeta de dominio en plural; un fichero no repite el nombre de su carpeta.
- Un FB por fichero, en `funciones/<dominio>/<verbo>.py`; la funcion se llama
  como el fichero. Son los unicos modulos que reciben el `job`.
- `<dominio>/` fuera de `funciones/` es logica pura: no importa el nucleo TIA
  ni `tia_ops`, ni recibe el `job`.
- Fallos esperados: subclases de `ZCError` (warning, sin traceback); errores
  de TIA cuelgan de `TIAError` (que cuelga de `ZCError`).
- Frontend: lo del nucleo en `src/nucleo/`, lo del area en `src/areas/<area>/`.
- `tests/` refleja `backend/zc_suite/` carpeta a carpeta.

## Convenciones de codigo

- PEP 8 + type hints en todas las firmas;
  `from __future__ import annotations` al principio de cada modulo.
- Nombre: `<prefijo>_<verbo>_<concepto>`, prefijo de dominio primero
  (`disp_*`, `proc_*`, `ent_*`). No mezclar prefijos en un mismo archivo.
  Excepcion: un modulo de dominio que se usa siempre como MODULO no necesita
  el prefijo en sus funciones, porque el prefijo lo da el modulo. Ejemplo:
  `backend/zc_suite/areas/alimentacion/dispositivos/catalogo.py`, que se
  importa como `dispositivos_catalogo` (ver
  `backend/zc_suite/areas/alimentacion/__init__.py:33`) y se llama
  `dispositivos_catalogo.construir_pestanas`.
- Funciones de dominio puras con kwargs explicitos; sin singletons en la
  logica.
- Los modulos nativos de TIA solo los importa el hilo de
  `nucleo/tia/servicio.py`.
- Comentarios: contrato, restricciones, nombres no obvios. Nada de planes,
  fechas ni narrativas de refactor.
- Nada de shims, re-exports ni alias "legacy".

## Normas Estrictas de Implementacion y Control de Calidad

1. **Prohibicion de Git destructivo o merges.** Ningun agente puede ejecutar
   `git merge`, `git push`, `git reset --hard` ni cambiar de rama sin orden
   explicita del operario. Si estan permitidos los comandos de solo lectura
   (`git status`, `git diff`, `git log`) y los commits locales en la rama de
   trabajo activa, que sirven de checkpoint para dejar el trabajo a medias sin
   perderlo. Un commit local nunca reescribe historia: no se amendan commits
   ya publicados ni se hace `rebase` de lo ya hecho.
2. **Fidelidad estricta a la UI de referencia.** En vistas frontend Vue esta
   prohibido improvisar el diseno: hay que clonar y adaptar la estructura
   exacta de la vista de referencia indicada (por ejemplo `ProcesosSyncView`) y
   verificar el diff contra `main` antes de dar la vista por terminada.
3. **Limite de tamano y principio DRY.** Ninguna funcion nueva puede superar
   las 80-100 lineas, ni copiar/pegar logica ya existente (`_compilar`, control
   de transacciones, avisos). Si algo ya existe en otro modulo, se extrae a un
   helper comun y se reutiliza desde ahi.
4. **Excepciones de dominio frente a diccionarios de estado.** Los fallos de
   compilacion o de sincronizacion lanzan excepciones tipadas
   (subclases de `ZCError`), nunca devuelven `{"ok": False}`. Siempre se
   validan las versiones de TIA Portal involucradas (por ejemplo V18 / V21)
   antes de operar.

## Reglas de commits

- 1-2 archivos por commit (excepcion: refactor coordinado de 1 archivo en N
  puntos).
- Mensaje en archivo, no en `-m`: `git commit -F <fichero>`.
- Scope entre paréntesis: `fix|feat|docs|chore|refactor|test(<scope>)`;
  scopes habituales: `tia`, `nucleo`, `alimentacion`, `frontend`, `vendor`,
  `readme`.
- Descripción imperativa en español, sin sujeto.
- NO en el cuerpo: planes, fechas, estilo IA ("absorbe lógica de", "Migrado
  de", "ahora X antes Y"), narrador refactor.
- Borrar el archivo temporal con la papelera (o `rm --`).
- 1-2 commits ahead de main; mega-commits prohibidos; PR con 2-3 frases de
  "qué" y "por qué"; suite completa antes de push (no hay CI).

## Tests y verificacion

- Backend: `pytest tests/`; el fichero del test se llama como el modulo que
  prueba. Frontend: Vitest (`npm test` en `frontend/`); el spec va en
  `__tests__/` y se llama como la vista.
- El portal se mockea con un doble de test propio, nunca el SDK real.
- Fixtures byte a byte; `.gitattributes` los deja intactos (`-text`); si
  cambias uno, `git add --renormalize tests/fixtures`.
- Antes de commit: `python -m pytest tests/ -q`, `python -m ruff check .`,
  y en `frontend/`: `npm test`. Un fallo nuevo es una regresion a arreglar;
  los fallos preexistentes no se tocan, pero no se anaden nuevos.
- Los tests verdes no sustituyen al smoke en vivo contra un proyecto de
  PRUEBA de TIA (solo el operario lo corre; nunca contra produccion).

## Delegacion a subagentes

El repo tiene sus propios especialistas de dominio en `.opencode/agent/`, y el
harness tiene los workers genericos. Son ejes distintos, no compiten:

| Agente | Que es | Que sabe |
|---|---|---|
| `nucleo` | `backend/zc_suite/nucleo/` y `errores.py` | El hilo unico de TIA, `Job`, `transaccion`, el bus SSE, el workdir |
| `tia-ops` | `backend/zc_suite/tia_ops/` y `simatic/` | El SDK de Siemens y los ficheros SimaticML / SimaticSD |
| `areas` | `backend/zc_suite/areas/` y sus tests | Excel maestro, dispositivos, entidades, procesos |
| `frontend` | `frontend/` | Vistas, componentes, stores, SSE y Vitest |
| `build-y-tests` | `build_exe.py`, `pyproject.toml`, `tests/`, `scripts/smoke/`, `docs/` | Empaquetado, suite de pruebas y documentacion |
| `explorer` | Worker generico | Localiza ficheros, rutas y lineas exactas. Sin contexto de dominio |
| `fixer` | Worker generico | Edita ficheros y ejecuta tests. Sin contexto de dominio |
| `oracle` | Asesor | Decisiones de arquitectura y bugs criticos |
| `librarian` | Asesor | Documentacion externa y APIs de terceros |
| `designer` | UI/UX | Layout, jerarquia, espaciado y movimiento |

Reglas de reparto:

- **Localizar** con `explorer`: pide ficheros, rutas y numeros de linea
  exactos, no el contenido entero. Si la busqueda es de un area concreta, el
  especialista de esa area (`nucleo`, `tia-ops`, `areas`, `frontend`) conoce
  los contratos y la respuesta es mas fiable que una busqueda generica.
- **Implementar** con `fixer`: implementa y ejecuta los tests. Si el cambio
  pertenece a un area, delega al especialista de esa area, que conoce los
  contratos del modulo.
- **Revisa** el diff o la salida de tests de `fixer` antes de darlo por
  bueno. Si falta algo, vuelve a invocar a `fixer` con instrucciones
  precisas.
- `oracle` es una escalada, no un paso por defecto: decisiones de
  arquitectura complejas, o un bug que `fixer` no resolvio tras dos intentos.
- `designer` es el unico que decide sobre UI: no se tocan vistas sin el.

### Restriccion critica de hardware (GPU local unica)

`explorer` y `fixer` corren en el **mismo modelo local** (`llama-local/qwen3.8-27b`)
sobre una **unica GPU (RTX 5070 Ti)**. Por eso:

- **PROHIBIDO lanzar subagentes locales en paralelo.** Nunca `explorer` y
  `fixer` a la vez, ni dos `explorer` simultaneos. Espera a que termine uno
  antes de lanzar el siguiente.
- Los subagentes de modelo remoto (`oracle`, `librarian`, `designer`) si se
  pueden lanzar en paralelo entre si.
- En un prompt a `fixer` o `explorer`, nombra la herramienta `edit` (no
  `mcp_TZWRpdA`).

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
