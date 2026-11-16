---
description: "Estado de la reescritura en rewrite/arquitectura-simple: reglas de seguridad, flujo de entrega y revision, estado de las fases 4.1-4.6, decisiones tomadas con el operario y lista pendiente."
read_if: "Empezar una fase nueva de la reescritura, revisar una entrega contra main, o dudar si una desviacion de main esta ya aprobada."
---

# Estado de la reescritura

Complementa a `.operator-shared/operator.md` (arquitectura y reglas) y a
`docs/FLUJOS_ALIMENTACION.md` (los flujos de main y los cambios deliberados).
Aqui va solo lo que no esta en esos ficheros: el estado, las decisiones de las
revisiones y la forma de trabajar.

## Objetivo

- Reescritura desde cero en `rewrite/arquitectura-simple`. Un solo `.exe`
  portable (PyInstaller onefile), sin base de datos, sin compatibilidad con
  main.

## Reglas de la reescritura (contrato de seguridad)

- **Replicar main fielmente. No inventar nada.** Cada diferencia con main se
  lista en el informe de entrega y la aprueba el operario. Si main tiene un
  fallo, se documenta y se propone el arreglo; no se arregla en silencio.
- El parser del Excel es **identico** al de main (mismos casts, acepta
  `.xlsm`). No se anaden columnas, comentarios ni validaciones que main no
  tenga.
- **Nada contra TIA desde el agente.** Los smokes los lanza el operario en una
  maquina virtual con TIA, sobre una **copia PRUEBA** del proyecto, y el
  proyecto **nunca se guarda** despues. Nunca se prueba un formato o una
  escritura que no este en un smoke commiteado.
- El repo es **publico**: no se commitea el Excel real del operario ni datos
  personales.
- Si `npm install` cambia `frontend/package-lock.json`, no se commitea.
- Commits pequenos, en espanol, en el estilo del repo.

## Forma de trabajo (flujo de entrega)

- Un agente implementa cada fase en su propia rama y **para al final** con un
  informe: hash de cada commit, ficheros tocados, numero de tests de backend y
  frontend, ruff, build y desviaciones de main con su motivo.
- Otro agente revisa la rama contra main (ver "Como se revisa una entrega") y
  devuelve aprobacion, preguntas al operario o un parche.
- Los arreglos pequenos llegan como parche `git format-patch`: se aplican con
  `git am`, se pasan los tests y se hace push. No se reescriben a mano.
- Si una fase se para a preguntar, que sea solo por una contradiccion entre
  main y el prompt, o por algo no cubierto que cambia el comportamiento, con
  fichero y linea de main y la opcion que replica main.

## Fases

| Fase | Estado |
|---|---|
| 4.1 Excel (parser y editor) | Hecha. Paridad del parser con main verificada fichero a fichero |
| 4.2 Prevision de dispositivos | Hecha y validada en V21 |
| 4.3 Sincronizar dispositivos | Hecha y validada en V21 (3 transacciones confirmadas) |
| 4.4 Entidades | Hecha. Paridad con main verificada con TIA simulado. Falta la prueba en V21 |
| 4.5 Procesos: comentarios de DB (proc_db) | Hecha. Paridad con main verificada con TIA simulado. Falta la prueba en V21 |
| 4.6 Crear proceso desde plantilla | Hecha. Paridad con main verificada con TIA simulado. Falta la prueba en V21 |
| 7 Resto (limites de tamano, ConfigError, "ok": False) | Hecha. Sin cambios de comportamiento; suite completa en verde |

Datos de la prueba real de 4.3 en V21: prevision con 116 altas, 83 bajas,
3 renombres y 10 N_MAX; sincronizacion completa en unos 47 s; prevision
posterior toda al dia. El escaneo del PLC tarda unos 100 s (posible mejora
futura).

## Decisiones tomadas con el operario

### Sesion en el servidor

- `backend/zc_suite/nucleo/sesion.py` guarda PLCs, seleccion, escaneo (TTL
  300 s) y datos de cada area (`guardar_dato_area`, `borrar_dato_area`,
  `datos_area`). Sobrevive a un F5 de la web.
- Se vacia al **arrancar y al cerrar** la app. Nada automatico al arrancar: el
  operario sube el Excel, conecta y escanea cada vez. El Excel **no** se
  guarda entre ejecuciones.
- Seleccionar un PLC de la lista lee su cache sin pulsar "Actualizar".
- Perder TIA (`perder_tia()`) vacia todo, como `resetPlcState` de main.
  Cambiar de PLC borra los datos del area.
- El frontend aplica la instantanea de `GET /api/v1/sesion` **una sola vez**
  (hidratar una vez). Volver a aplicarla pisaba previsiones recientes.

### Confirmaciones

- Toda accion que modifica el PLC pide confirmacion, como Dispositivos en
  main. Main no la tenia en Entidades ni en Procesos: era un fallo de main y
  el operario quiere el dialogo en las tres vistas.

### Entidades (4.4)

- **Borrar antes de anadir constantes.** En main, una entidad cuyo numero
  cambia desaparece de TIA: anade primero (se salta el nombre porque ya
  existe) y luego borra. La reescritura borra primero. Aprobado.
- El contador "entidades analizadas" de main siempre marca 0 (lee un
  `entities_block` que el backend no envia). Corregido. Aprobado.
- `backend/zc_suite/simatic/ml/constantes_modificador.py` captura la plantilla
  de constante al cargar el XML (necesario al borrar antes de anadir). La
  salida de Dispositivos sigue identica a main.

### Fase 4: modulo comun de sincronizacion

- El estado de transacciones, el resumen, `compilar_con_aviso`,
  `mensaje_corto` y `localizar_xml` viven en
  `backend/zc_suite/areas/alimentacion/sincronizacion_comun.py`; los FB de
  dispositivos y entidades ya lo usan.
- `resultado["compilacion"]` es un **detalle string** (`compile=OK (...)` /
  `compile=WARN`) en el sync de dispositivos, como en entidades. El frontend
  no lo lee: el aviso con errores va al log.
- **No unificados** (difieren y se dejan):
  - `_aplicar_comentarios`/`_confirmar_comentarios` de dispositivos reexportan
    los bloques, los copian a `modified/` y editan los `.s7dcl`/`.s7res`
    offline antes de importar; en entidades la edicion de los comentarios la
    hace `ent_copiar_y_editar` en el paso previo, y el FB solo importa el DB.
  - `disp_localizar_xml` (dominio de dispositivos) devuelve `Path | None`
    para omitir las tablas ausentes del sync; `localizar_xml` comun devuelve
    siempre un `Path`.
- Por comprobar en V21: el config espera el DB `DB6_ENT`, pero el listado del
  proyecto real mostraba `DB6_ENTIDAD`.

### Procesos (4.5)

- Los contadores de las pestanas de main siempre marcan 0 (leen un
  `summary` por array que el backend no envia). Se corrige.
- **Pendiente de decision:** main escribe "." en las posiciones que sobran, y
  la prevision siguiente las vuelve a marcar como "eliminar" para siempre. Se
  replica tal cual, con un test que lo documente, y se decide tras la
  revision.
- Nombres en el proyecto real: `DB53100_CPR_PARAM`, `DB55100_CPR_ALM`, tabla
  `100_CPR`.

### Compilacion

- `block.compile()` y `compile_software()` devuelven un `ExecutionResult`,
  nunca un booleano (la regla completa esta en `docs/TIA_OPENNESS.md`).
- `backend/zc_suite/tia_ops/compilar.py`: hay errores si `get_errors()` trae
  algo o el estado no es 0; tras compilar un bloque, `is_consistent()` es la
  comprobacion de respaldo.
- La compilacion va **fuera** de las transacciones y no bloquea. El aviso
  lista cada bloque con su mensaje de TIA recortado, p. ej.
  "1 bloque(s) con errores: DB_NO_OK (Interface > Data type Boo is unknown.)".
- Hubo un falso "10 bloques con errores" por tratar el resultado como
  booleano: el operario comprobo en TIA que habia 0 errores.

### Log y consola

- Log en `logs/zc.log` junto al exe, nivel DEBUG. La consola de la SPA solo
  muestra INFO o superior.
- El backend ya registra el fin de cada trabajo; el frontend no lo repite
  (`frontend/src/nucleo/eventos.js`).
- El exe es de ventana, con icono en la bandeja del sistema (pystray).

### Ficheros TIA

- El XML que se genera se escribe con CRLF explicito (ElementTree escribe en
  modo texto y en Linux saldria LF).
- Los ids MLC de SimaticSD son aleatorios, en main y en la reescritura: al
  comparar, se normalizan.

### Config

- `config/config.json` con el formato nuevo (`areas.alimentacion` con
  `carpetas_tia`, `tabla_nmax`, `plantillas_procesos`, `dispositivos`,
  `etiquetas_dispositivos`, `entidades`, `procesos`), validado por
  `backend/zc_suite/areas/alimentacion/config.py`. Un config con el formato de
  main muestra un banner rojo.
- Nunca poner el exe de main y el de la reescritura en la misma carpeta: el
  de la reescritura leeria el `config.json` de main.

## Como se revisa una entrega

1. Traer la rama, pasar los tests de backend y frontend, ruff y build.
2. Leer el diff entero y comparar cada regla con el codigo de main citado en
   `docs/FLUJOS_ALIMENTACION.md`.
3. Ejecutar main y la reescritura con **el mismo Excel** y un **TIA simulado**
   (un `siemens_tia_scripting` falso que exporta bloques y tablas de prueba y
   guarda lo que se importa). Comparar los ficheros de `modified/` byte a
   byte, normalizando CRLF, BOM e ids MLC.
4. Repetir con un escenario de fallo (una importacion que falla) y comprobar
   el estado de cada transaccion.
5. Capturar la vista con Playwright y compararla con la de main: textos,
   contadores, estados y botones.
6. Informe al operario: veredicto, desviaciones de main para que decida, y el
   mensaje o el parche para la siguiente iteracion.

El TIA simulado y los scripts de comparacion no estan en el repo.

## Pendiente

- Decidir el caso "." de proc_db.
- Prueba en V21 de 4.4 (comprobar antes el nombre del DB de entidades) y de
  4.5 y 4.6 (SimaticSD).
- Rendimiento del escaneo: quitadas dos llamadas al SDK por bloque, falta
  medir el tiempo real en el proyecto.

## Fase 7: resto (limites de tamano y errores)

### Los FB de sync se quedaron por debajo de 100 lineas

Cada orquestador se partio en helpers privados por paso; los pasos se
declaran en una constante `PASOS` de modulo. Ninguna funcion de los cuatro
FB sobrepasa las 100 lineas (medidas por AST, incluida la docstring):

- `funciones/dispositivos/sincronizar.py`: `sincronizar` 90 lineas.
- `funciones/entidades/sincronizar.py`: `sincronizar` 92 lineas.
- `funciones/procesos/sincronizar.py`: `sincronizar` 94 lineas.
- `funciones/procesos/crear.py`: `crear` 81 lineas.

Las diferencias que se quedaron **sin unificar** (no son duplicados: la
semantica no es la misma):

- `_transaccion` se repite identico en los tres sync, pero **no** puede
  vivir en `sincronizacion_comun.py`: el modulo comun es puro respecto a TIA
  y no recibe el `job` (lo exigen `test_fronteras_dominio.py` y el contrato
  de que solo `funciones/` recibe el job).
- `_recalcular_prevision` llama a la `generar_prevision` de **su** dominio
  y el detalle del paso no es el mismo ("entradas en la vista unificada"
  contra "cambios en la vista").
- `_armar_resultado` arma shapes distintos por dominio (dispositivos:
  `tablas`/`agregados`/`eliminados`; entidades: `constantes`/`comentarios`;
  procesos: `operaciones`).

### `ConfigError` es un fallo esperado

`ConfigError` (el config.json no se puede leer ni validar) ahora hereda de
`ZCError`: es un fallo esperado, sin traceback. El router de plantillas no
cambia: sigue sirviendo `200` en el OK, `400` por body invalido y `500`
cuando el config no se puede escribir ni recargar (`except ConfigError`).

### El `{"ok": False}` que queda es el shape observable del crear

`rg '"ok": False'` sobre `areas/` y `nucleo/funciones/` solo devuelve las
dos devoluciones de `datos_compilacion` en `sincronizacion_comun.py`: son
los **datos** del shape observable `{ok, error, detalle}` que lee la SPA
(compile=WARN), no un diccionario de control de flujo.

## Ruta de plantillas editable

La ruta de las plantillas se edita desde la SPA (como en main) y se guarda
en el `config.json` del usuario.

- La clave se llama `plantillas_procesos` (no `plantillas_path`: esta en
  `CLAVES_ANTIGUAS` y dispararia el banner de config incompatible). Su
  valor por defecto es la **cadena vacia**, que significa "sin configurar":
  no se resuelve contra `raiz_datos()`.
- `carpeta_plantillas()` devuelve `Path | None`: `None` cuando no esta
  configurada. Los FB de prevision y de creacion lanzan `OperacionError`.
- `PUT /api/v1/areas/alimentacion/procesos/plantillas` con
  `{plantillas_path: str}`: escribe en el `config.json` del usuario de
  forma atomica (`.tmp` + `os.replace`) y recarga el config en memoria
  (`recargar_config_app`), sin reiniciar. La cadena vacia resetea.
- El router NO importa `nucleo.app.main`: el callback de recarga se
  registra en `app.config[CLAVE_RECARGA_CONFIG]` y el router lo lee de ahi.
- `montar_app` se partio en `_secciones_de`, `_estado_completo`,
  `_montar_areas` y `_refrescar_areas`: las blueprints se registran una
  sola vez al arrancar y la recarga no las repite (Flask no lo admite).

## Escaneo del PLC: llamadas al SDK

Por bloque, el escaneo hacía dos lecturas de `ProgrammingLanguage` (en
`_tipo` y en `_extendidas`) y llamaba a `get_path()` y a `get_path_full()`.

- `ProgrammingLanguage` se lee **una vez** por bloque en `_dto()` y se
  comparte con `_tipo()` y `_extendidas()`. UDT incluidos: el DTO de un UDT
  conserva su `extended["programming_language"]`.
- `extended` tiene 5 claves y su unica fuente es `CLAVES_EXTENDIDAS`.
- `get_path_full()` se llama **solo en los UDT**, donde `get_path()` se
  queda corto. En los bloques de programa manda el docstring de `_ruta`:
  `get_path()` basta.
- El DTO no cambia: mismos campos, mismos valores.
- La instrumentacion de tiempos es a nivel **DEBUG** (`logs/zc.log`): la
  consola de la SPA solo muestra INFO o superior.
