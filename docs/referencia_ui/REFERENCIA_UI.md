# Referencia de la interfaz original (rama `main`)

Capturas y especificación de cada pantalla de la app original, para replicarlas en
`rewrite/arquitectura-simple`. El objetivo es que el operario vea **las mismas pantallas, con el
mismo flujo y el mismo aspecto**. Lo que cambia es solo lo de debajo (endpoints, jobs, stores).

## Cómo se obtuvieron

- Se arrancó el backend Flask de `main` tal cual (`MainServiceSupervisor`), sin bandeja.
- `siemens_tia_scripting` se sustituyó por un **doble** que simula el proyecto `ZC_PLC_STD` con la
  lista real de bloques y UDT que dio el smoke (168 bloques, 101 UDT). Los ficheros exportados se
  generan a partir de los fixtures de `main` (`tests/fixtures/source/Bloques/*.s7dcl`) y de XML
  SimaticML sintéticos.
- El Excel maestro es sintético, generado con los helpers de los tests de `main`
  (`test_excel_loader._build_full_xlsx`), con `Tabla_PLC`, `Tabla_Entidades` y más filas.
- Navegador: Chrome sin cabeza, 1440×900.

**Los datos de las capturas son de prueba.** En particular:

- `no value` (subtítulo del PLC, Author/Version en el editor) es lo que devuelve el doble. El SDK
  real devuelve ese mismo literal en algunos campos: **en la reescritura se normaliza a vacío**.
- Los números del preview (renombrar, agregar…) salen de comparar el Excel sintético con el doble.
- La pestaña Variables del PLC muestra 2 tablas porque se capturó con una versión anterior del doble.

El código fuente de cada pantalla está en `main`; para leerlo:
`git show origin/main:<ruta>`. Las rutas se indican en cada sección.

---

## 1. Shell común

Presente en todas las pantallas dentro de un área. Fuente:
`core/web_server/static/js/main.js`, `components/ShellSidebar.js`, `components/ShellTopbar.js`,
`components/ProgressIndicator.js`, `components/ConsolaLogs.js`.

### Barra lateral (izquierda, 288 px, navy `#00205B`)

De arriba abajo:

1. **Cabecera**: etiqueta `ÁREA` (pequeña, mayúsculas, tenue) y el nombre del área en grande
   (`Alimentacion`).
2. **Sección `PLC`**: dos botones fijos del shell, que no dependen del área:
   - 🔌 **PLC** → vista PLC (sección 4).
   - 🔧 **Editor de bloques** → editor (sección 5).
3. **Sección `NAVEGACIÓN`**: los items que aporta el área, en este orden:
   🏠 Inicio · 📊 Definición programación · ⚡ Dispositivos · ⚙️ Procesos · 🗂️ Entidades.
4. **Faceplate de progreso** (pegado al pie, solo cuando hay o hubo un trabajo). Ver 1.4.
5. **Botón `← Volver al inicio`** (pie): vuelve al selector de áreas (sección 2).

Item activo: fondo blanco al 10 %, borde izquierdo azul claro (`#4d8fd1`), texto en negrita.

### Barra superior (blanca, 56 px)

- **Migas**: `ÁREA DE ALIMENTACIÓN • <VISTA>`, en mayúsculas espaciadas; la vista actual en
  negrita y color de acento.
- **Pastilla de PLC** a la derecha: `PLC: —` sin PLC seleccionado; `PLC: ZC_PLC_STD` (en negrita)
  cuando hay uno seleccionado en la vista PLC.

No hay botón de conectar en la topbar: **la conexión se hace en la vista PLC**.

### Faceplate de progreso (pie de la barra lateral)

Capturas: `20_dispositivos_aplicando_faceplate.png` (en curso), `21_dispositivos_aplicado.png`
(completado), y el pie de casi todas las demás.

- Cabecera: icono de estado + **`En curso`** / **`Completado`** (y error), y debajo el título del
  trabajo y `n/N completados` (p. ej. `Sincronizar dispositivos contra PLC — 4/11`).
- Botón `×` para cerrarlo.
- Barra de progreso fina (verde al completar, azul en curso).
- Lista de pasos numerados en fuente monoespaciada: `✓` hecho, `○` pendiente, el paso en curso
  resaltado con fondo. Tras el nombre, en cursiva y tenue, el detalle del paso
  (p. ej. `— exportados 18/18 bloques SD a …`), truncado con `…`.

Los pasos de cada operación (para que el faceplate nuevo muestre los mismos):

| Operación | Pasos |
|---|---|
| Escanear PLC | Check cache · Escanear |
| Cargar Excel | Parsear y volcar Excel |
| Preview dispositivos | Exportar etiquetas · Calcular diferencias de dispositivos · Calcular diferencias de N_MAX · Componer respuesta |
| Sync dispositivos | Exportar etiquetas · Calcular diferencias de dispositivos · Preparar operaciones · Aplicar N_MAX y renombres · Esperar consolidación TIA · Re-exportar etiquetas · Editar archivos XML · Aplicar dispositivos · Compilar bloques · Aplicar comentarios · Generar preview post-sincronización |
| Preview entidades | Exportar etiquetas y DB · Calcular diferencias de N_MAX entidad · Calcular diferencias de constantes · Calcular diferencias de comentarios · Componer respuesta |
| Sync entidades | Exportar etiquetas y DB · Calcular diferencias · Preparar operaciones · Aplicar N_MAX (Tx A) · Esperar consolidación TIA · Re-exportar etiquetas y DB · Editar XMLs offline · Aplicar constantes (Tx B) · Compilar bloques · Aplicar comentarios (Tx C) · Generar preview post-sincronización |
| Preview crear proceso | Leer manifiesto · Validar mínimos · Copiar a vista previa · Construir diccionarios · Detectar colisiones · Validar dependencias · Generar previstos · Componer respuesta |
| Crear proceso | Leer manifiesto · Validar mínimos · Copiar a vista previa · Construir diccionarios · Generar proceso nuevo · Escribir manifiesto modificado · Importar proceso · Compilar bloques · Refrescar caché de bloques · Componer respuesta |
| Preview comentarios DB | Validar estado de TIA · Validar bloques · Construir mapa de slots · Calcular diferencias de N_MAX · Exportar y calcular diferencias · Componer respuesta |
| Sync comentarios DB | Validar estado de TIA · Validar bloques · Construir mapa de slots · Aplicar N_MAX · Esperar consolidación TIA · Compilar bloques · Abrir transacción TIA · Generar preview post-sincronización · Componer respuesta |
| Editor: preparar | Validar selección · Leer bloques desde caché · Exportar bloques SD · Parsear cabeceras SCL · Combinar datos |
| Editor: aplicar | Validar cambios · Calcular diff · Aplicar transacción · Verificar resultado · Refrescar caché |

En la reescritura no hace falta copiar los pasos internos que ya no existan; sí conviene que los
nombres que ve el operario sean estos o equivalentes.

### Consola de trazabilidad (franja inferior del área de contenido)

- Cabecera gris: `CONSOLA DE TRAZABILIDAD`, a la derecha `(N msgs)` y botón `🧹 Limpiar`.
- Cuerpo en monoespaciada; vacía muestra `Esperando eventos...` en cursiva.
- En `main` la consola apenas recibía líneas (todas las capturas muestran `0 msgs`). En la
  reescritura debe mostrar de verdad el evento `log`, con el traceback desplegable.

### Paleta (de `core/web_server/static/src/input.css` en `main`)

| Token | Valor | Uso |
|---|---|---|
| `shell` | `#00205B` | barra lateral, pantalla de inicio |
| `shell-deep` | `#001540` | separadores, botón "Volver al inicio" |
| `on-shell-muted` | `#93b5e3` | texto secundario sobre navy |
| `on-shell-faint` | `#5a7fbb` | etiquetas de sección |
| `accent-bright` | `#4d8fd1` | borde del item activo |
| `surface` | `#f3f4f6` | fondo del contenido |
| `surface-raised` | `#ffffff` | tarjetas, tablas |
| `surface-sunken` | `#e5e7eb` | inputs, cabeceras de tabla, botones secundarios |
| `line` | `#d1d5db` | bordes |
| `ink` / `ink-muted` | `#1f2937` / `#6b7280` | texto |
| `accent` | `rgb(0 52 102)` | botones primarios, enlaces, migas |

Tipografía: sans (Inter) para la interfaz; monoespaciada para nombres de bloques, rutas, tablas
de datos y el faceplate. Bordes redondeados suaves, sombras mínimas.

Copiar `input.css` de `main` es el camino más corto para que la reescritura sea idéntica.

---

## 2. Inicio: selector de área

Captura: `01_inicio_selector_area.png`. Fuente: `components/Welcome.js`.

- Fondo navy a pantalla completa, sin barra lateral.
- Tarjeta blanca centrada con el **logo de Zeus Control** (`core/web_server/static/Logos Zeus Control.png`).
- Título `Zeus Control` y subtítulo `Plataforma de Ingeniería, Sincronización y Generación de Código TIA Portal.`
- Separador con texto `SELECCIONA UN ÁREA PARA COMENZAR`.
- Una tarjeta blanca por área (icono 📁, nombre, descripción). Clic → entra en el área en su
  vista "Inicio".
- Pie: `v1.0.0 • Zeus Control` en monoespaciada tenue.

---

## 3. Área: Inicio

Captura: `02_area_inicio.png`. Fuente: `areas/alimentacion/frontend/components/AreaLanding.js`.

- Icono 📁 en cuadrado navy, título `Área de alimentación`, subtítulo `¿Qué quieres hacer?`.
- Lista de tarjetas-acción (icono, título, descripción, botón `Abrir →`):
  - 📊 **Definición programación** — Carga el maestro Excel y consulta la AppState del PLC.
  - ⚡ **Dispositivos** — Previsualiza y aplica cambios en TIA Portal.
  - ⚙️ **Procesos** — Genera procesos en TIA Portal (crear / actualizar comentarios).

(Entidades no tiene tarjeta aquí, solo item en la barra lateral.)

---

## 4. PLC

Capturas: `03_plc_desconectado.png`, `04_plc_conectado.png`, `05_plc_bloques.png`,
`06_plc_variables.png`, `07_plc_udt.png`. Fuente: `core/web_server/static/js/components/plcpanelview.js`.

### Tarjeta superior

Dos columnas:

- **ESTADO DEL SISTEMA**, lista con puntos de color:
  - `Worker: inactivo` (rojo) / `activo` (verde).
  - `TIA: idle` / `connected` (verde).
  - Conectado, además: `Proyecto: ZC_PLC_STD` y `Ruta: D:\…\ZC_PLC_STD.ap21` (monoespaciada).
- **CONTROLES**: `🔌 Conectar` y `⏏ Desconectar`, en la misma fila; el que no aplica sale
  deshabilitado.

Debajo, separado por una línea:

- **PLC DISPONIBLES** con botón `↻ Actualizar` a la derecha.
- Sin conectar: caja punteada `No se han encontrado PLCs disponibles.`
- Conectado: una tarjeta por PLC (icono 💻, nombre en negrita, subtítulo con la designación
  corta de la CPU) y botón `Seleccionar`. Seleccionado: tarjeta con borde y fondo verdes, icono
  verde y botón `Seleccionado`. La pastilla de la topbar pasa a `PLC: <nombre>`.

### Tarjeta inferior: contenido del PLC

- Sin PLC seleccionado: 📦 `Selecciona un PLC primero.` / `Pulsa "↻ Actualizar" para escanear el PLC.`
- Tras `Actualizar` (lanza el escaneo; faceplate "Check cache · Escanear"): pestañas
  **Bloques (168)** · **Variables (2)** · **UDT (101)**.
  - **Bloques**: tabla `NOMBRE | TIPO | NÚMERO | RUTA`, **agrupada por tipo** con filas-cabecera
    (`OB  10 bloques`, `DB  40 bloques`, `FC …`, `FB …`). Nombres en monoespaciada.
  - **Variables**: tabla `NOMBRE | RUTA` con las tablas de variables.
  - **UDT**: tabla `NOMBRE | TIPO | NÚMERO | RUTA`.

Notas para la reescritura: el UDT sale con tipo `OTHER` y número `0`, y la ruta incompleta;
`bloques.py` nuevo ya lo corrige (número vacío y ruta completa). El subtítulo `no value` del PLC
debe salir vacío.

---

## 5. Editor de bloques

Capturas: `08_editor_sin_conexion.png`, `09_editor_seleccion.png`,
`10_editor_tabla_edicion.png`, `11_editor_cambio_pendiente.png`, `12_editor_aplicado.png`.
Fuente: `core/web_server/static/js/components/BlockPropertiesEditor.js`.

- Sin PLC escaneado: tarjeta vacía con 🔌 `Conecta a TIA Portal` / `Desde la pestaña PLC pulsa 'Conectar' para empezar.`
- Dos tarjetas lado a lado:

**Izquierda — Selección de bloques** (≈ 1/3 del ancho)

- Título y subtítulo `Selección read-only.`; a la derecha `N seleccionados` y enlace `Limpiar`.
- Casilla `Seleccionar todos (168 bloques)`, enlaces `Expandir todo` / `Colapsar todo`.
- Árbol con scroll: primero los bloques sueltos de la raíz, después las carpetas con `▶`, casilla,
  📁, nombre en negrita y `(N bloques)`. Cada bloque: casilla, insignia de color por tipo (OB
  morado, FC verde, DB azul, FB…) y nombre en monoespaciada. Marcar una carpeta marca todos sus
  bloques (estado indeterminado en "Seleccionar todos").
- Pie: botón primario **Editar** (deshabilitado sin selección).

**Derecha — Edición de propiedades**

- Sin preparar: zona gris con 🛠️ `Selecciona bloques en el árbol para empezar.` o
  `N bloques seleccionados. Pulsa "Editar" para preparar los datos contra TIA.`
- Tras **Editar** (faceplate de 5 pasos; exporta los bloques en SimaticSD): texto
  `Name y Number son editables y se aplican contra TIA Portal. Title, Comment, Author y Version son solo lectura por ahora…`
  y tabla `Tipo | Name* | Number* | Title | Comment | Author | Version`: Name y Number son inputs
  editables; el resto, inputs deshabilitados (Comment es un textarea).
- Con cambios: pie con enlace `Cancelar` y botón primario **`Aplicar (N)`**, con N = número de
  bloques cambiados. Mientras se prepara o aplica, el árbol se atenúa.
- Tras aplicar (faceplate de 5 pasos): el árbol se refresca con los nombres nuevos y la tabla se
  vacía.

Notas: la preparación exige V21 (SimaticSD). En V18, el editor nuevo puede editar Name/Number
sin exportar (lo hace `tia_ops/bloques.py`), y Title/Comment/Author/Version quedan en blanco.

---

## 6. Definición programación

Capturas: `13_definicion_vacia.png`, `14_definicion_configuracion.png`,
`15_definicion_dispositivos.png`, `16_definicion_procesos.png`, `17_definicion_entidades.png`.
Fuente: `areas/alimentacion/frontend/components/DefinicionProgramacion.js`, `MainTabs.js`,
`ConfiguracionPanel.js`, `DispositivosPanel.js`, `ProcesosPanel.js`, `EntidadesPanel.js`.

**Tarjeta CARGA EXCEL**

- Selector de fichero nativo y, a la derecha, botón `🔄 Volver a seleccionar`.
- **Al elegir el fichero se sube y se carga solo** (sin botón "Actualizar"; faceplate
  "Parsear y volcar Excel").
- Cargado: `✅ Excel cargado` y `📎 Último archivo: <nombre>`.

**Tarjeta de contenido**

- Vacía: 📊 `La cache del excel está vacía.` / `Sube un Excel y pulsa "Actualizar".`
- Cargada: pestañas grandes con icono y contador:
  `⚙️ Configuracion (1)` · `📟 Dispositivos (68)` · `📋 Procesos (4)` · `🗂️ Entidades (6)`.
  - **Configuración**: tabla de N_MAX por PLC: `PLC | N_MAX_DISP_EA | N_MAX_DISP_ED | … | N_MAX_ENTIDAD`.
  - **Dispositivos**: sub-pestañas por tipo con contador: `ED · EA · SA · SD · V · M · MVF · MSINA · TQ · TQAE · TOT · PID`.
    Cada una, tabla con las columnas del Excel (ED: `PLC_NAME | NÚMERO | TAG | DESCRIPCIÓN | FAT | E.BYTE | E.BIT | GR.ALARMA | CUADRO | OBSERVACIONES`).
  - **Procesos**: sub-pestañas `Procesos (1) · Parámetros Enteros (1) · Parámetros Reales (1) · Alarmas (1)`;
    la de procesos: `PLC | CÓDIGO | NOMBRE | PREAL | PINT | ALARMAS | ALARMAS HMI`.
  - **Entidades**: `PLC | NÚMERO | DESCRIPCIÓN | PLC.TAG | PLC.TIPO | PLC.INDEX | PLC.COMENTARIO`.
- Tablas: cabecera gris en mayúsculas pequeñas; celdas vacías como `—`.

Es una vista **solo de consulta** del Excel cargado; no toca TIA.

---

## 7. Dispositivos

Capturas: `18_dispositivos_vacio.png`, `19_dispositivos_preview.png`,
`20_dispositivos_aplicando_faceplate.png`, `21_dispositivos_aplicado.png`.
Fuente: `areas/alimentacion/frontend/components/Dispositivos.js`.

- **Barra superior**: a la izquierda, el resumen (tras generar):
  `75 dispositivos analizados — 25 a agregar · 43 a renombrar · 7 a eliminar · 0 sin cambios`
  (agregar en azul, renombrar en naranja, eliminar en rojo). A la derecha, `🔍 Generar Previsión`
  (deshabilitado si TIA no está conectado o no hay Excel).
- **Sin preview**: ⚡ `Sin prevision generada.` / `Pulsa "🔍 Generar Previsión" para ver el diff completo.`
- **Con preview**:
  - **Tarjetas de N_MAX** en rejilla (6 por fila): nombre (`NUM_DISP_EA`) y valor grande;
    si cambia, `10 → 20` con el nuevo en naranja; si no, solo el valor.
  - **Pestañas por tipo** con contador: `ED (12) · EA (12) · SA (4) · …`.
  - **Tabla de diff**: `# | ACTUAL (TIA) | DESEADO (EXCEL) | ESTADO`. Estados:
    `✏️ RENOMBRAR` (naranja; el valor deseado también en naranja), `➕ AGREGAR` (azul; actual `—`),
    `ELIMINAR` (rojo), `✓ OK` (gris).
- **Botón ancho** al pie: `✅ Aplicar Cambios en TIA Portal (83 cambios)`, deshabilitado sin preview.
- **Confirmación** (en `main` es un `window.confirm`):

  ```
  ¿Aplicar 83 cambios en TIA Portal?

  Devices:
    Agregar: 25
    Renombrar: 43
    Eliminar: 7

  N_MAX (dimensiones):
    Actualizar: 8

  Los "sin cambios" no se tocan.
  Esta operacion modifica el PLC.
  ```

- **Aplicando**: botones deshabilitados y faceplate con los 11 pasos. Al terminar, la vista se
  rellena con el preview posterior (los aplicados pasan a `✓ OK`, los N_MAX sin flecha).
- **Errores**: en `main` salen en un `window.alert` (p. ej. `Error generando prevision: ValueError: PLC 'ZC_PLC_STD' no esta en el Excel cargado…`).
  En la reescritura conviene mostrarlos en la propia vista (aviso rojo) y en el faceplate, no en
  un `alert`.

---

## 8. Procesos

Capturas: `22_procesos_sin_excel.png`, `23_procesos_seleccionado.png`,
`24_procesos_crear_ruta_plantillas.png`, `25_procesos_crear_plantilla.png`,
`26_procesos_crear_preview.png`, `27_procesos_crear_preview_completa.png`,
`28_procesos_comentarios_preconditions.png`.
Fuente: `areas/alimentacion/frontend/components/Procesos.js`, `ProcesosCrearView.js`,
`ProcesosSyncView.js`.

- **Sin Excel**: aviso amarillo `⚠️ No hay Excel cargado. Sube un Excel y pulsa "Actualizar" en "Definición programación".`
- **Tarjeta PROCESO**: desplegable `Selecciona un proceso…` / `PR1 — Proceso 1` (código — nombre,
  monoespaciada).
- **Tarjeta ¿Qué quieres hacer?**: dos tarjetas-botón (deshabilitadas sin proceso):
  - 🏗️ **Crear proceso completo** — Genera el DB + bloques + UDTs del proceso.
  - 💬 **Actualizar comentarios de DB** — Sincroniza los comentarios de los DBs existentes.
- Cada acción abre un **panel debajo** (no es otra vista), con botón `Cerrar`.

### 8.1 Crear proceso completo desde plantilla

- Subtítulo `Proceso seleccionado: PR1 - Proceso 1 (uid 1)`.
- Botón `Configurar ruta de plantillas` y la ruta actual entre paréntesis. Al pulsarlo se abre un
  recuadro gris `Ruta base de plantillas` con un input y `Guardar` / `Cancelar`. Si la carpeta no
  existe: `Aviso: Directorio no existe: <ruta>` en naranja.
- **PLANTILLA**: desplegable `CPR - Compacto (base 50100)` y su descripción en cursiva debajo.
  Cada plantilla es una subcarpeta con `manifest.json` (`base`, `codigo`, `nombre`, `descripcion`,
  `dependencias`, `minimos`), `Bloques de programa/` y `Variables PLC/…`.
- Tabla `DATO | PLANTILLA | PROCESO NUEVO`: PREAL, PINT, ALM, ALM_HMI, UID, CÓDIGO.
- Botón `🔍 Generar Previsión`.
- **Preview**:
  - `Bloques a generar (3)`; si hay colisiones, aviso rojo
    `Aviso: 2 colision(es) detectada(s) con bloques ya existentes en el PLC.` con la lista y
    `Cambia el proceso o plantilla para evitar pisar bloques existentes.`
  - Tabla `BLOQUE ORIGINAL | BLOQUE NUEVO | ESTADO` (`OK`, o `DUPLICADO - <bloque existente>`).
  - `Dependencias (1)`: tabla `DEPENDENCIA PLC | ESTADO`.
  - Botón `✅ Aplicar Cambios en TIA Portal`.

### 8.2 Actualizar comentarios de DB

- Título `💬 Actualizar comentarios de DB`, subtítulo `Proceso Proceso 1 (PR1, uid 1)`,
  botones `Cerrar` y `🔍 Generar Previsión`.
- Sin preview: ⚙️ `Sin prevision generada.`
- Si faltan bloques: aviso amarillo `⚠️ Precondiciones no cumplidas: Tabla de variables: 1_PR1 · DB de parametros: DB3001_PR1_PARAM · DB de alarmas: DB5001_PR1_ALM`
  y caja `Bloques TIA objetivo` con cada bloque y `(no existe en PLC)` en rojo.
- Con preview (no capturado: el doble no tiene esos DB): diff de comentarios por slot y botón de
  aplicar, con la misma estructura que dispositivos. Ver `ProcesosSyncView.js`.

---

## 9. Entidades

Capturas: `29_entidades_vacio.png`, `30_entidades_preview.png`.
Fuente: `areas/alimentacion/frontend/components/Entidades.js`.

Misma estructura que Dispositivos:

- Resumen `0 entidades analizadas — 6 a agregar · 0 a renombrar · 0 a eliminar · 0 sin cambios`
  y `🔍 Generar Prevision`.
- Tarjeta de N_MAX: `N_MAX_ENTIDAD 10 → 0`.
- Tabla sin pestañas: `# | TAG ACTUAL (TIA) | COMENTARIO ACTUAL (TIA) | TAG DESEADO (EXCEL) | COMENTARIO DESEADO (EXCEL) | ESTADO`.
- `✅ Aplicar Cambios en TIA Portal (7 cambios)`, con confirmación como en dispositivos.

---

## 10. Endpoints de `main` (referencia)

La reescritura no tiene que copiarlos: cada vista usa las rutas nuevas (`/api/v1/tia/...` y las
del área). Sirven para localizar en `main` qué hace cada botón.

| Pantalla | Endpoints en `main` |
|---|---|
| Shell | `GET /api/v1/areas`, `GET /api/v1/catalog`, SSE `GET /stream`, `POST /api/v1/progress/clear`, `GET/POST /api/v1/logs`, `/api/v1/logs/clear` |
| PLC | `POST /api/v1/tia/connect`, `/api/v1/tia/disconnect`, `/api/v1/portal/attach`, `/api/v1/portal/open-new`, `GET /api/v1/portal/project-info`, `GET /api/v1/plcs`, `GET /api/v1/plcs/<plc>/blocks`, `POST /api/v1/plcs/<plc>/blocks/refresh` |
| Editor | `POST /api/v1/blocks/edit/prepare`, `GET /api/v1/blocks/edit/<plc>/prepared`, `POST /api/v1/blocks/edit/apply` |
| Definición | `POST /api/v1/excel/upload` |
| Dispositivos | `POST /api/v1/sync/preview`, `POST /api/v1/sync/commit` |
| Procesos | `GET/POST /api/v1/procesos/plantillas`, `POST /api/v1/procesos/crear/preview`, `/api/v1/procesos/crear/aplicar`, `POST /api/v1/procesos/sync/preview`, `/api/v1/procesos/sync/commit` |
| Entidades | `POST /api/v1/entidades/preview`, `/api/v1/entidades/sincronizar` |

---

## 11. Qué replicar igual y qué mejorar

**Igual** (es lo que conoce el operario):

- Estructura del shell: barra lateral navy con las dos secciones, topbar con migas y pastilla de
  PLC, faceplate al pie de la barra lateral, consola abajo.
- Paleta, tipografía e iconos (los emojis incluidos).
- Flujos: conectar y seleccionar PLC en la vista PLC; el Excel se carga al elegirlo; cada
  operación es "Generar previsión → revisar → Aplicar" con confirmación.
- Textos de botones, estados vacíos y avisos.

**Mejorar** sin cambiar el aspecto:

1. Errores en la vista y en el faceplate, no con `window.alert`; la confirmación puede ser un
   diálogo propio con el mismo texto.
2. La consola debe mostrar de verdad los eventos `log`.
3. No mostrar `no value` del SDK: vacío.
4. UDT con número vacío y ruta completa.
5. Si una sincronización falla a mitad, el resultado debe decir qué transacciones se confirmaron.
6. En V18, avisar en el editor y en los pasos con SimaticSD de que requieren V21, en lugar de
   fallar.
