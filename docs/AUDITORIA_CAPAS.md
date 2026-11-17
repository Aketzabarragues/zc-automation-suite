---
description: "Auditoria de capas y coherencia de nombres del repo: que esta en la capa que le toca y que nombres se leen coherentes."
read_if: "Antes de anadir un area, mover codigo entre capas, o renombrar algo del nucleo, del area o del frontend."
---

# Auditoria de capas y coherencia de nombres

Informe sobre `backend/zc_suite/` (66 ficheros) y `frontend/src/`. La matriz
de imports se ha medido con un recorrido AST de todo el paquete; los hallazgos
van numerados y los lotes propuestos se ordenan de menor a mayor riesgo.

Nota (2026-11-17): el informe recoge el estado tras aplicar los lotes A-K,
segun la revision final; cada hallazgo y cada lote llevan su linea de estado.

## 1. Resumen ejecutivo

- **Pregunta**: ¿El core esta limpio? NO del todo. Un unico punto con codigo real (el log de arranque lee claves de catalogo de area) y el resto son comentarios. Confianza: alta.
- **Pregunta**: ¿El area esta limpia? Las areas no se importan entre si y sus dominios no dependen de TIA. Confianza: alta. (Hallazgo 2 resuelto: los tipos compartidos `DiffNMax`/`DiffTabla` y el calculo de N_MAX viven ahora en `backend/zc_suite/areas/alimentacion/diferencias.py`.)
- **Pregunta**: ¿Las capas estan separadas? `simatic/` no depende de nada; `tia_ops/` solo depende del core por un simbolo (`proyecto_activo`), lo cual esta DECLARADO en el codigo. Confianza: alta.
- **Pregunta**: ¿Una segunda area se podria anadir sin tocar el core? Si, salvo la lista `AREAS` de `main.py` (registro, declarado). Confianza: alta.
- **Pregunta**: ¿Los nombres son coherentes? En general si; hay prefijos de dominio que faltan, sinonimos de verbos y residuos de `preview` en el backend. Confianza: media.
- **Pregunta**: ¿Las reglas declaradas estan vigiladas por tests? 3 de 12 reglas de arquitectura tienen test; las demas no. Confianza: alta.
- **Pregunta**: ¿Hay fugas de dominio en el core? Una, con codigo (log de arranque); el resto son comentarios. Confianza: alta.
- **Pregunta**: ¿Hay logica del core colada en el area? Si: los helpers comunes de sync viven en el area y no se podrian reutilizar tal cual desde otra area. Confianza: alta.
- **Pregunta**: ¿El frontend separa core y area? Si, con una sola excepcion (el store de areas) y una deuda de datos de demo. Confianza: alta.
- **Pregunta**: ¿Hay acoplamientos no documentados? Dos: subdominio-a-subdominio dentro del area, y el core leyendo la forma del catalogo de un area. Confianza: alta.

Ningun hallazgo de este informe rompe el comportamiento observable; son riesgos de mantenibilidad y de extension.

## 2. Matriz de imports

### 2.1 Matriz capa -> capa

`backend/zc_suite`, 66 ficheros, recorrido con AST.

| origen -> destino | imports | ficheros |
|---|---|---|
| areas -> nucleo | 33 | 11 |
| areas -> tia_ops | 19 | 7 |
| areas -> simatic | 14 | 11 |
| areas -> errores | 10 | 10 |
| areas -> areas (internos) | 87 | 24 |
| nucleo -> nucleo (internos) | 42 | 13 |
| nucleo -> errores | 6 | 6 |
| nucleo -> tia_ops | 6 | 4 |
| nucleo -> simatic | 1 | 1 |
| nucleo -> areas | 1 | 1 |
| tia_ops -> errores | 7 | 7 |
| tia_ops -> nucleo | 2 | 2 |
| tia_ops -> tia_ops (internos) | 7 | 7 |
| simatic -> simatic (internos) | 7 | 5 |
| simatic -> nucleo | 0 | 0 |
| simatic -> tia_ops | 0 | 0 |
| simatic -> areas | 0 | 0 |
| tia_ops -> areas | 0 | 0 |
| tia_ops -> simatic | 0 | 0 |

Nota: "imports" cuenta pares (fichero, modulo); un fichero que importa 3
modulos de la misma capa cuenta 3.

### 2.2 Direccion de las flechas permitidas

Segun las reglas declaradas (`.operator-shared/operator.md`, reglas 4 y 5):
el nucleo no importa areas (salvo `AREAS` de `main.py`); las areas no se
importan entre si; la logica pura de los dominios (fuera de `funciones/`) no
depende de TIA.

### 2.3 Cada flecha, como se lee

| flecha | veredicto | nota |
|---|---|---|
| areas -> nucleo | correcta | El area usa `job.tia.portal`, `transaccion` y los stores de sesion: es el sentido permitido. |
| areas -> tia_ops | correcta | El area orchestra operaciones TIA. |
| areas -> simatic | correcta | El area edita ficheros SimaticML/SimaticSD. |
| areas -> errores | correcta | — |
| areas -> areas (internos) | ATENCION | Ver hallazgo 2. |
| nucleo -> tia_ops | correcta | El core llama al SDK. |
| nucleo -> simatic | correcta | El core lee cabeceras SimaticSD. |
| nucleo -> areas | la UNICA excepcion declarada | `backend/zc_suite/nucleo/app/main.py:27` importa `zc_suite.areas` (el paquete raiz, no un submodulo) y `backend/zc_suite/nucleo/app/main.py:62` lo usa en la lista `AREAS`. Esta en `EXCEPCIONES` de `tests/test_fronteras.py:22`. |
| tia_ops -> nucleo | correcta, documentada | 2 imports, ambos del MISMO simbolo `proyecto_activo` (`backend/zc_suite/tia_ops/proyecto.py:19`, `backend/zc_suite/tia_ops/_resolver.py:15`; definicion en `backend/zc_suite/nucleo/tia/transaccion.py:25`). Ver hallazgo 9. |
| tia_ops -> areas | correcta | 0. |
| tia_ops -> simatic | correcta | 0. |
| simatic -> (nada) | correcta | 0. `simatic/` no depende de nadie. |

## 3. Hallazgos

### Hallazgo 1 — El core lee la forma del catalogo de un area

- **Severidad**: Media
- **Evidencia**: `backend/zc_suite/nucleo/app/main.py:104` (`catalogo.get("device_tabs")`), `backend/zc_suite/nucleo/app/main.py:105` (`catalogo.get("nmax")`), `backend/zc_suite/nucleo/app/main.py:107` (log "Area '%s': %d tipos de dispositivo, %d N_MAX"), `backend/zc_suite/nucleo/app/main.py:112-119` y `backend/zc_suite/nucleo/app/main.py:120-126` (avisos sobre dispositivos y N_MAX).
- **Por que importa**: es la unica fuga de dominio CON CODIGO del core. El core asume que toda area devuelve un catalogo con `device_tabs` y `nmax` (claves de alimentacion). Una segunda area con otra forma de catalogo recibira avisos que no le corresponden. No lo vigila ningun test: `tests/test_vocabulario.py` solo busca literales en el texto, no claves de JSON.
- **Propuesta**: que el area exponga en su `catalogo()` un bloque generico (por ejemplo `"resumen": {"tarjetas": N, "grupos": N}`) y que el core lea ese bloque generico; o que el aviso se derive de las claves que el area declare. **DECISION** (cambia la forma del JSON del catalogo, que es contrato con la SPA).
- **Estado**: HECHO (`8b73514`).

### Hallazgo 2 — `dispositivos/diferencias.py` es un modulo fundacional del area y no lo parece

- **Severidad**: Media
- **Evidencia** (anterior): `backend/zc_suite/areas/alimentacion/entidades/diferencias.py`, `backend/zc_suite/areas/alimentacion/procesos/diferencias.py` y `backend/zc_suite/areas/alimentacion/sincronizacion_comun.py` importaban de `backend/zc_suite/areas/alimentacion/dispositivos/diferencias.py` (tipos `DiffNMax`, `DiffTabla`).
- **Por que importa**: `dispositivos/` es el dominio de dispositivos, pero sus tipos los usan `entidades/`, `procesos/` y el helper comun. Quien lea el arbol creera que `entidades/` depende de dispositivos, que no es cierto: depende de un tipo compartido mal ubicado. `tests/test_fronteras.py:117` solo vigila area-contra-area, asi que este acoplamiento entre subdominios del MISMO area no lo detecta nada.
- **Propuesta**: **HECHO** (opcion (a)): los tipos compartidos se movieron a `backend/zc_suite/areas/alimentacion/diferencias.py`, con el calculo de N_MAX (`disp_calcular_diff_n_max`) y su helper, y todos los importadores apuntan al modulo comun.
  - (a) Extraer `DiffNMax`/`DiffTabla` a un modulo comun del area (por ejemplo `backend/zc_suite/areas/alimentacion/diferencias.py`), moviendo tambien el calculo de N_MAX que los usa.
  - (b) Dejarlo y documentar que `dispositivos/diferencias.py` es el modulo de tipos compartidos del area.
  - (c) Anadir un test de frontera que prohiva el cruce entre subdominios, obligando a decidir.
- **Estado**: HECHO (`0530e5e`). Los tipos y el calculo de N_MAX viven ahora en `backend/zc_suite/areas/alimentacion/diferencias.py`.

### Hallazgo 3 — El core asume el numero de areas

- **Severidad**: Baja
- **DECISION**
- **Evidencia**: `tests/nucleo/web/test_rutas_config.py:120` (`assert len(AREAS) == 1`). Con una segunda area, ese test falla aunque el codigo sea correcto.
- **Por que importa**: un test que se rompe al hacer lo correcto desincentiva anadir areas. No es un fallo del producto: es una fragilidad del test.
- **Propuesta**: parametrizar el test sobre `AREAS` en vez de fijar el numero, o quitar la asercion y comprobar que las areas registradas aparecen.
- **Estado**: HECHO (`9577e2a`).

### Hallazgo 4 — Los helpers comunes de sync no se pueden reutilizar desde otra area

- **Severidad**: Media
- **DECISION**
- **Evidencia**: `backend/zc_suite/areas/alimentacion/sincronizacion_comun.py` esta en la raiz del area; sus funciones genericas son `estados_iniciales` (`backend/zc_suite/areas/alimentacion/sincronizacion_comun.py:56`), `resumen_transacciones` (`backend/zc_suite/areas/alimentacion/sincronizacion_comun.py:74`), `estado_confirmada`/`estado_revertida`/`estado_no_ejecutada` (`backend/zc_suite/areas/alimentacion/sincronizacion_comun.py:82`/`:88`/`:94`), `compilar_con_aviso` (`backend/zc_suite/areas/alimentacion/sincronizacion_comun.py:134`), `datos_compilacion` (`backend/zc_suite/areas/alimentacion/sincronizacion_comun.py:153`), `texto_errores_compilacion` (`backend/zc_suite/areas/alimentacion/sincronizacion_comun.py:199`), `mensaje_corto` (`backend/zc_suite/areas/alimentacion/sincronizacion_comun.py:236`), `localizar_xml` (`backend/zc_suite/areas/alimentacion/sincronizacion_comun.py:250`); y `backend/zc_suite/areas/alimentacion/funciones/_transaccion.py:25` (`_transaccion`).
- **Por que importa**: una segunda area ("envasado") que quisiera el mismo flujo de sync tendria que COPIAR estos helpers: importarlos viola la regla "las areas no se importan entre si" (`tests/test_fronteras.py:117`). Es decir, el repo no ofrece todavia un sitio donde vivir el "comun de sync" reutilizable. Que el modulo sea generico en su contenido no ayuda si su ubicacion lo hace inaccesible.
- **Nota importante**: NO es una violacion de la regla actual (la regla dice "un FB por fichero en `funciones/<dominio>/<verbo>.py`" y `sincronizacion_comun.py` no es un FB). Es una limitacion de la regla, no un fallo.
- **Propuesta**: **DECISION**.
  - (a) Crear un paquete `zc_suite/nucleo/sync/` (o similar) para lo que sea reutilizable, con la parte que recibe el `job` en `funciones/` segun la regla. Coste: mover codigo y revisar que el test de "solo `funciones/` recibe el `job`" siga verde.
  - (b) Declarar en el contrato que cada area trae su propio modulo comun y que la duplicacion es aceptada.
  - (c) Dejarlo hasta que exista una segunda area.

  NO mover nada sin orden del operario.
- **Estado**: APLAZADO por decision del operario (era el Lote H): pendiente de que exista una segunda area.

### Hallazgo 5 — Prefijos de dominio que faltan

- **Severidad**: Baja
- **Evidencia**: `backend/zc_suite/areas/alimentacion/dispositivos/catalogo.py` expone `etiqueta_de_n_max`, `construir_pestanas` y `construir_n_max` sin el prefijo `disp_`, mientras los otros nueve modulos de dominio si lo llevan (`dispositivos/diferencias.py`, `dispositivos/sincronizacion.py`, `entidades/diferencias.py`, `entidades/sincronizacion.py`, `procesos/clonacion.py`, `procesos/diferencias.py`, `procesos/mapa.py`, `procesos/plantillas.py`, `procesos/sincronizacion.py`).
- **Por que importa**: la regla de `.operator-shared/operator.md` ("prefijo de dominio primero") no tiene excepciones declaradas, y este modulo es el unico que se aparta. Matiz: el modulo se usa siempre como MODULO (`backend/zc_suite/areas/alimentacion/__init__.py:32` y `tests/areas/alimentacion/dispositivos/test_catalogo.py:11` lo importan como `dispositivos_catalogo` y llaman `dispositivos_catalogo.construir_pestanas`), no importando nombres sueltos: por eso el prefijo no es necesario para evitar colisiones, y por eso la excepcion es defendible si se DECLARA.
- **Propuesta**: o renombrar las tres funciones con `disp_`, o (recomendado, barato) declarar la excepcion en la regla: "un modulo de dominio que se usa como modulo no necesita prefijo en sus funciones".
- **Estado**: HECHO por la via de DECLARAR la excepcion (`fa8a266`, regla; `d7327de`, glosario de verbos).

### Hallazgo 6 — Sinonimos de verbos para la misma idea

- **Severidad**: Baja
- **Evidencia**:
  - `generar_prevision` (FB, `backend/zc_suite/areas/alimentacion/funciones/*/generar_prevision.py`) frente a `calcular_*` (dominio: `disp_calcular_diff_tabla`, `ent_calcular_diff_constantes`, `proc_calcular_diff_n_max`) frente a `construir_*` (`proc_construir_diccionarios`, `proc_construir_mapa`).
  - `backend/zc_suite/tia_ops/constantes.py:55` `cambiar_valor` y `backend/zc_suite/tia_ops/constantes.py:99` `renombrar` frente a `backend/zc_suite/tia_ops/bloques.py:199` `cambiar_propiedad` y `backend/zc_suite/tia_ops/bloques.py:248` `aplicar_cambios`.
- **Por que importa**: `cambiar_valor` y `cambiar_propiedad` son el mismo verbo con objetos distintos, y `cambiar`/`renombrar`/`aplicar_cambios` conviven en el mismo modulo `tia_ops/constantes.py` frente a `tia_ops/bloques.py`. Dificulta buscar "quien cambia algo".
- **Propuesta**: fijar un mini-glosario de verbos en `CONTRIBUTING.md` (calcular = diff; generar = prevision; construir = estructura; aplicar = escribir en TIA) y renombrar lo que no encaje. No hace falta renombrar de golpe: basta con que la regla exista y se aplique a lo nuevo.
- **Estado**: HECHO por la via del glosario de verbos, sin renombrar nada existente (`d7327de`).

### Hallazgo 7 — `preview` sigue en el backend

- **Severidad**: Baja
- **Evidencia**: `backend/zc_suite/areas/alimentacion/rutas.py:118` `preview_dispositivos`, `backend/zc_suite/areas/alimentacion/rutas.py:162` `preview_entidades`, `backend/zc_suite/areas/alimentacion/rutas.py:206` `preview_procesos`, `backend/zc_suite/areas/alimentacion/rutas.py:328` `preview_crear_proceso` (nombres de las funciones de ruta; las URLs ya son `/preview` y no se tocan en este informe). Y `backend/zc_suite/nucleo/tia/workdir.py:107` `preview` y `backend/zc_suite/nucleo/tia/workdir.py:111` `preview_de` (la carpeta en disco `preview/`).
- **Por que importa**: el Lote 10 renombro el frontend de `preview` a `prevision`; el backend se quedo a medias. Ahora el mismo concepto se llama `prevision` en la SPA y `preview` en las rutas y en el workdir.
- **Matiz importante**: `preview/` es el NOMBRE DE UNA CARPETA EN DISCO (`.build_cache/<area>/<contexto>/preview/`): cambiarlo es tocar el disco y no es solo renombrar. Y las URLs `/preview` son contrato con la SPA.
- **Propuesta**: renombrar solo los NOMBRES INTERNOS de las funciones de ruta (`preview_dispositivos` -> `prevision_dispositivos`), que no son contrato. La carpeta en disco y las URLs quedan como estan, con un comentario que lo explique. **HECHO**: se renombraron las cuatro funciones de ruta y se anadio el comentario en `workdir.py` junto a la propiedad `preview`.
- **Estado**: HECHO (parcial) (`6d2b944`): los nombres de las funciones de ruta pasan a `prevision_*`; las URLs `/preview` y la carpeta en disco `preview/` se mantienen a proposito.

### Hallazgo 8 — Ingles residual en `simatic/`

- **Severidad**: Baja
- **Evidencia**: `backend/zc_suite/simatic/ml/constantes_parser.py:63` metodo privado `_extract_constants`; `backend/zc_suite/simatic/ml/constantes_modificador.py:47` parametro `xml_path`; `backend/zc_suite/simatic/ml/constantes_modificador.py:241` y `:304` variable `start`; `backend/zc_suite/simatic/ml/constantes_modificador.py:304` y `:419` parametro `elem`; `backend/zc_suite/simatic/ml/constantes_parser.py:59` y `:63` parametro `root`; `backend/zc_suite/simatic/sd/mlc.py:141` parametro `out`.
- **Por que importa**: el Lote 5 renombro los parametros publicos de `simatic/` a espanol, pero dejo estos. `root`/`elem`/`start`/`out` son nombres de la API de `xml.etree.ElementTree`, que en Python son `Element`; `xml_path` es una ruta de fichero.
- **Propuesta**: renombrar lo que no toque la API: `root`->`raiz`, `elem`->`elemento`, `start`->`inicio`, `out`->`salida`, `xml_path`->`ruta_xml`, `_extract_constants`->`_extraer_constantes`. Son cambios locales, sin contrato.
- **Estado**: HECHO (parcial) (`960c979` y el commit que renombra las variables locales que quedaban en ingles): quedan solo las locales que reflejan tags XML o APIs externas (`name_el`, `value_el`, `mlti`, `mlt`, `buffer`, `tree`, `match`, `pattern`).

### Hallazgo 9 — El core publica un helper que consume `tia_ops`

- **Severidad**: Baja
- **DECISION**
- **Evidencia**: `backend/zc_suite/nucleo/tia/transaccion.py:25` define `proyecto_activo`; `backend/zc_suite/tia_ops/proyecto.py:19` y `backend/zc_suite/tia_ops/_resolver.py:15` lo importan; el docstring de `backend/zc_suite/nucleo/tia/transaccion.py:28-29` dice "Es el unico sitio donde se resuelve el proyecto: las operaciones de ``tia_ops`` lo reutilizan."
- **Por que importa**: la dependencia `tia_ops -> nucleo` es INTENCIONADA y documentada (no es un fallo). Lo que si confunde es el NOMBRE del modulo: `transaccion.py` sugiere que solo gestiona transacciones, y esconde que tambien es el punto de resolucion del proyecto para la capa de operaciones. Quien lea `tia_ops/proyecto.py` ve un import al modulo de transacciones y no entiende el motivo.
- **Propuesta**: **DECISION**.
  - (a) Dejarlo y anadir una linea al indice del repo (`docs/AUDITORIA_CAPAS.md` o el mapa) que explique que `transaccion.py` es tambien el punto de resolucion del proyecto. Coste: cero.
  - (b) Mover `proyecto_activo` a `tia_ops/_resolver.py` (donde ya vive `nombre_plc`) y dejar en el nucleo solo el uso de la transaccion. Coste: mueve un simbolo entre capas y toca `scripts/smoke/exportar.py:47`.
- **Estado**: APLAZADO por decision del operario (era el Lote H).

### Hallazgo 10 — Datos de demo de alimentacion en el shell del frontend

- **Severidad**: Baja
- **Evidencia**: `frontend/src/nucleo/demo.js:39`, `frontend/src/nucleo/demo.js:59`, `frontend/src/nucleo/demo.js:101`, `frontend/src/nucleo/demo.js:131` (`label: "Sincronizar dispositivos"`), `frontend/src/nucleo/demo.js:158` (PLC de demo), `frontend/src/nucleo/demo.js:161` (ruta de demo), `frontend/src/nucleo/demo.js:188` (`BLOQUES_DEMO` con nombres reales del proyecto de prueba), `frontend/src/nucleo/demo.js:219` (`TABLAS_DEMO`), `frontend/src/nucleo/demo.js:226` (`TIPOS_DEMO`).
- **Por que importa**: el shell (que deberia servir a cualquier area) lleva vocabulario y datos de alimentacion. No rompe nada y no hay ninguna regla declarada que lo prohiba: es deuda de mantenibilidad, visible solo cuando exista una segunda area. No es una violacion de frontera.
- **Propuesta**: **DECISION**.
  - (a) No tocar hasta que haya una segunda area.
  - (b) Mover los datos de demo al area y que el shell los pida al store de areas.
  - (c) Dejar los datos genericos en el shell y sacar solo los especificos.
- **Estado**: APLAZADO por decision del operario (era el Lote J).

### Hallazgo 11 — Reglas de arquitectura sin test

- **Severidad**: Media
- **Evidencia** (de `.operator-shared/operator.md`, 12 reglas): tienen test la 4 (`tests/test_fronteras.py:94` y `tests/test_fronteras.py:117`) y la 5 (`tests/test_fronteras_dominio.py:180` y `tests/test_fronteras_dominio.py:190`). NO tienen test: la 1 (solo el job toca TIA), la 2 (toda escritura en TIA va en `with transaccion(...)`), la 3 (la prevision no escribe), la 6 (ningun objeto .NET sale de `tia_ops/`), la 7 (sin asyncio, sin CDN), la 8 (fuera de alcance), la 9 (`vendor/` no versionado), la 10 (cero `.pyd`/`.dll`), la 11 (`target_folder_path` no se pasa), la 12 (encoding `.s7res` en `utf-8-sig`).
- Ademas de `CONTRIBUTING.md`: "solo el hilo de `tia.py` importa `siemens_tia_scripting`" sin test, y "ninguna funcion supera las 100 lineas" sin test.
- **Por que importa**: las reglas que no se vigilan se degradan sin que nadie lo note. Varias se cumplen hoy (verificado: `siemens_tia_scripting` solo se importa en `backend/zc_suite/nucleo/tia/servicio.py:176`; no hay `.pyd`/`.dll`; no hay asyncio; `target_folder_path` no se pasa nunca con `""` en el codigo), pero nada impide que se rompan.
- **Propuesta**: la seccion 6 de este informe lista las reglas nuevas candidatas, todas comprobables con AST.
- **Estado**: HECHO (parcial) (`49e90c7` anade 4 reglas vigiladas). `test_ninguna_funcion_supera_las_100_lineas` NO se anade por decision del operario: quedan 5 funciones por encima de 100 lineas.

### Hallazgo 12 — No hay glosario de siglas

- **Severidad**: Baja
- **Evidencia**: en `backend/zc_suite/` se usan `TIA` (522 ocurrencias), `plc`/`PLC` (369+270), `N_MAX` (176), `DB` (114), `proc_uid` (94), `s7res`/`s7dcl` (54+50, extensiones de fichero), `uid` (45), `MLC` (37), `n_max` (28), `dcl`/`res` (26+22), `sd`/`ml` (17+12). No existe ningun glosario en `docs/` ni en `.operator-shared/`.
- **Por que importa**: la mayoria son terminos del dominio de TIA o del Excel maestro (contrato, intocables). Pero `n_max`, `dcl`, `res`, `sd`, `ml` y `uid` son abreviaturas internas sin significado evidente para quien llega. `docs/TIA_OPENNESS.md` explica parte del vocabulario de TIA, pero no hay una lista unica.
- **Propuesta**: anadir a `docs/AUDITORIA_CAPAS.md` (o a `docs/NUEVA_AREA.md`) un glosario corto con las siglas que NO son de TIA ni del Excel, y marcar explicitamente cuales son contrato y no se tocan.
- **Estado**: HECHO (`7066d18`), con `docs/GLOSARIO.md`.

## 4. Lo que esta bien

- `simatic/` no depende de nada: ni del core, ni de `tia_ops`, ni de las areas. Cero imports hacia fuera (verificado con AST). Es la capa mas limpia.
- `tia_ops/` no importa areas ni `simatic`. Y la regla "tia_ops no importa areas" YA esta cubierta: `tests/test_fronteras.py:94` recorre `_modulos(PAQUETE_DIR)` (todo el paquete salvo las areas) y `tia_ops/` esta ahi dentro, asi que lo vigila aunque el nombre del test (`test_el_nucleo_no_importa_areas`) no lo diga.
- La excepcion `nucleo -> areas` esta acotada a UN import del paquete raiz, en el fichero que la regla declara como excepcion, y su uso es la lista `AREAS` (registro, no logica).
- La regla "un FB por fichero con la funcion homonima" se cumple en el 100%: los 13 FB (`backend/zc_suite/nucleo/funciones/`: `aplicar`, `preparar`, `escanear`, `listar_plcs`; `backend/zc_suite/areas/alimentacion/funciones/`: `generar_prevision` x3, `sincronizar` x3, `crear`, `generar_prevision_crear`, `cargar`) mas `backend/zc_suite/areas/alimentacion/funciones/_transaccion.py` tienen su funcion homonima.
- La regla "solo `funciones/` recibe el `job`" se cumple y esta vigilada por `tests/test_fronteras_dominio.py:209` (que recorre TODO `PAQUETE_DIR`, no solo los dominios).
- Los `__init__.py` de los subdominios del area no reexportan nada: todos los imports van al submodulo concreto. No hay accesos a atributos privados entre modulos (cero ocurrencias de `modulo._atributo` en backend y frontend).
- El contrato del area (`backend/zc_suite/areas/alimentacion/__init__.py:38-49`, 10 simbolos en `__all__`) coincide EXACTAMENTE con lo que dice `docs/NUEVA_AREA.md:8` ("El contrato son diez cosas").
- El frontend separa bien: el unico import de `areas/` en `nucleo/` es `frontend/src/nucleo/stores/areas.js:10` (registro); el shell recoge las vistas con `import.meta.glob` (`frontend/src/areas/index.js:8,21`), asi que anadir un area NO obliga a editar ningun fichero del shell. Ningun componente de `frontend/src/nucleo/componentes/` importa un store de area. Ningun `data-testid` de un componente comun contiene palabras de area.
- Los tests de frontera existentes son solidos: `tests/test_fronteras.py` (7 tests) y `tests/test_fronteras_dominio.py` (9 tests) recorren el arbol con AST, resuelven imports relativos y tienen autocomprobaciones del propio comprobador.

## 5. Lotes propuestos

| Lote | Que toca | Riesgo | Toca contrato externo | Requiere V21 |
|---|---|---|---|---|
| A | Acoplamiento subdominio-a-subdominio del area (hallazgo 2) | medio | NO | NO |
| B | El core no debe conocer la forma del catalogo de un area (hallazgo 1) | medio | SI | NO |
| C | Reglas de arquitectura vigiladas por test (hallazgo 11 y seccion 6) | bajo | NO | NO |
| D | Nombres de dominio en `dispositivos/catalogo.py` (hallazgo 5) | bajo | NO | NO |
| E | Verbos: glosario minimo (hallazgo 6) | bajo | NO | NO |
| F | `preview` -> `prevision` en el backend (hallazgo 7) | bajo | NO | NO |
| G | Ingles residual en `simatic/` (hallazgo 8) | bajo | NO | NO |
| H | El helper comun de sync, reusable (hallazgos 4 y 9) | medio | NO | NO |
| I | Tests fragiles frente a una segunda area (hallazgo 3) | bajo | NO | NO |
| J | Datos de demo del shell (hallazgo 10) | bajo | NO | NO |
| K | Glosario de siglas (hallazgo 12) | bajo | NO | NO |

- **Lote A — Acoplamiento subdominio-a-subdominio del area** (hallazgo 2). Riesgo medio. Toca contrato: NO (los tipos `DiffNMax`/`DiffTabla` son internos; si se mueven, cambian los imports de 4 ficheros y sus tests). V21: NO. **HECHO** con la opcion (a) del hallazgo 2: los tipos y el calculo de N_MAX se movieron a `backend/zc_suite/areas/alimentacion/diferencias.py` y se actualizo `sincronizacion_comun.py`. **Estado**: HECHO (`0530e5e`).
- **Lote B — El core no debe conocer la forma del catalogo de un area** (hallazgo 1). Riesgo medio. Toca contrato: SI (la forma del JSON del catalogo que consume la SPA). V21: NO. El area expone un bloque generico en su `catalogo()` y el core lee ese bloque; hay que actualizar `backend/zc_suite/areas/alimentacion/__init__.py` (el `catalogo()`) y `backend/zc_suite/nucleo/app/main.py:103-126`. La SPA no deberia notar nada si el bloque nuevo es adicional. **Estado**: HECHO (`8b73514`).
- **Lote C — Reglas de arquitectura vigiladas por test** (hallazgo 11 y seccion 6). Riesgo bajo. Toca contrato: NO. V21: NO. Anadir los tests de la seccion 6 (AST puro). Ojo: las reglas de encoding y `target_folder_path` necesitan fixtures byte a byte: NO las metas en este lote. **Estado**: HECHO (`49e90c7`).
- **Lote D — Nombres de dominio en `dispositivos/catalogo.py`** (hallazgo 5). Riesgo bajo. Toca contrato: NO. V21: NO. Renombrar las tres funciones con `disp_`, o declarar la excepcion (recomendado: mas barato y deja la regla escrita). **Estado**: HECHO (`fa8a266`).
- **Lote E — Verbos: glosario minimo** (hallazgo 6). Riesgo bajo. Toca contrato: NO. V21: NO. Anadir el mini-glosario a `CONTRIBUTING.md` y renombrar solo lo que mas estorbe (`cambiar_valor`/`cambiar_propiedad`). **Estado**: HECHO (`d7327de`).
- **Lote F — `preview` -> `prevision` en el backend** (hallazgo 7). Riesgo bajo. Toca contrato: NO si solo se renombran los nombres de las funciones de ruta; SI si se toca la carpeta en disco `preview/` o las URLs `/preview` (NO se tocan). V21: NO. **HECHO**: se renombraron las cuatro funciones de ruta en `backend/zc_suite/areas/alimentacion/rutas.py` y se anadio el comentario en `workdir.py`; la carpeta en disco y las URLs quedan. **Estado**: HECHO (`6d2b944`).
- **Lote G — Ingles residual en `simatic/`** (hallazgo 8). Riesgo bajo. Toca contrato: NO. V21: NO. Renombrar `root`, `elem`, `start`, `out`, `xml_path` y `_extract_constants`. El test de paridad byte a byte (`tests/simatic/test_paridad_simatic.py`) sale verde solo si no se toca el contenido del XML. **Estado**: HECHO (`960c979` y el commit que renombra las variables locales que quedaban en ingles).
- **Lote H — El helper comun de sync, reusable** (hallazgos 4 y 9). Riesgo medio. Toca contrato: NO. V21: NO. DECISION del operario. Si se mueve `backend/zc_suite/areas/alimentacion/sincronizacion_comun.py` a un sitio compartido, hay que revisar el test "solo `funciones/` recibe el job" y el caso de `DiffNMax`. **Estado**: APLAZADO por decision del operario (hallazgos 4 y 9).
- **Lote I — Tests fragiles frente a una segunda area** (hallazgo 3). Riesgo bajo. Toca contrato: NO. V21: NO. Parametrizar `tests/nucleo/web/test_rutas_config.py:120` sobre `AREAS`; revisar `tests/nucleo/web/test_rutas_catalogo.py:49-51`, `tests/nucleo/app/test_main.py:34,42` y `tests/nucleo/web/test_rutas_sesion.py:26,108-109`. **Estado**: HECHO (`9577e2a`).
- **Lote J — Datos de demo del shell** (hallazgo 10). Riesgo bajo. Toca contrato: NO. V21: NO. DECISION del operario; no tocar hasta que haya segunda area. **Estado**: APLAZADO por decision del operario (hallazgo 10).
- **Lote K — Glosario de siglas** (hallazgo 12). Riesgo bajo. Toca contrato: NO. V21: NO. Anadir la lista de siglas al final de este mismo documento. **Estado**: HECHO (`7066d18`), con `docs/GLOSARIO.md`.

El Lote 14 de la auditoria previa (fusionar las parejas previsualizar/aplicar) sigue cerrado sin tocar codigo: la norma ya se reescribio en el Lote 11 y el codigo ya usa parejas de FBs.

## 6. Reglas nuevas candidatas para test_fronteras

Todas se pueden comprobar con el recorrido AST que ya existe en
`tests/test_fronteras.py` (helper `_importaciones` y `_modulo_de`): no hace
falta escribir logica nueva.

| Test | Que comprobaria | Prioridad |
|---|---|---|
| `test_simatic_no_importa_nucleo_ni_tia_ops` | Que ningun fichero de `simatic/` importe `zc_suite.nucleo.tia` ni `zc_suite.tia_ops`. Hoy la condicion ya se cumple; el test protege contra regresion. | Media |
| `test_dominio_no_importa_subdominio_ajeno` | Que, dentro de un area, ningun modulo de `<subdominio>/` (fuera de `funciones/`) importe otro `<subdominio>/` distinto. Es el unico acoplamiento real que hoy escapa a todos los tests (`entidades/` y `procesos/` -> `dispositivos/diferencias.py`). Obliga a decidir el hallazgo 2. | Alta |
| `test_tia_ops_no_importa_areas` | Que ningun fichero de `tia_ops/` importe `zc_suite.areas.*`. Hoy lo cubre `test_el_nucleo_no_importa_areas` de forma implicita (recorre todo `PAQUETE_DIR` menos las areas); el test explicito hace el contrato visible. | Media |
| `test_cada_fb_es_el_unico_de_su_fichero` | Que cada fichero de `funciones/` tenga exactamente UNA funcion de nivel superior cuyo nombre sea el del fichero. Extiende `test_cada_fb_vive_en_su_propio_fichero` (que hoy solo exige que exista). | Baja |
| `test_solo_el_hilo_de_tia_importa_el_sdk` | Que `siemens_tia_scripting` solo se importe en `backend/zc_suite/nucleo/tia/servicio.py`. Hoy se cumple (unico import en `backend/zc_suite/nucleo/tia/servicio.py:176`). | Media |
| `test_nadie_importa_el_sdk_de_siemens_fuera_del_hilo` | Que ningun modulo importe `siemens_tia_scripting` salvo `backend/zc_suite/nucleo/tia/servicio.py` y `backend/zc_suite/nucleo/tia/transaccion.py` (si procede). Mismo criterio, otro angulo. | Baja |
| `test_ninguna_funcion_supera_las_100_lineas` | Que ninguna funcion de `backend/` pase de 100 lineas (AST, `end_lineno - lineno + 1`). Hoy NO se cumple: quedan 5 (`generar_prevision` de procesos 202, `ent_calcular_diff_constantes` 188, `generar_prevision` de entidades 146, `generar_prevision` de dispositivos 119, `proc_construir_diccionarios` 102). El test solo puede activarse cuando esas 5 esten partidas. | Media (bloqueado por las 5 funciones) |
| `test_el_nucleo_no_escribe_fuera_del_workdir` | Que el core no escriba ficheros fuera de `.build_cache/`. Regla 12 de la arquitectura, hoy sin vigilar. | Baja |

Nota: la regla 12 (encoding: `.s7res` en `utf-8-sig`) y la regla 11
(`target_folder_path` no se pasa) NO se proponen aqui: necesitan fixtures byte
a byte y una prueba en V21, respectivamente.
