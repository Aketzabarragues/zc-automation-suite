# Flujos de alimentacion

Como funcionaba cada operacion en la version original (rama `main`) y como hay
que rehacerla en la reescritura. Esto es **documentacion**: no hay aqui ni una
linea de codigo del area.

Cada flujo dice, en orden:

- **a) Exporta**: que saca de TIA, con que nombres, de que carpeta, con o sin
  estructura, y a que carpeta del workdir.
- **b) Modifica offline**: que se edita en disco, y donde.
- **c) Importa**: que vuelve a meter en TIA, desde que carpeta raiz.
- **d) Transacciones y compilaciones**: en que orden, y que queda confirmado si
  algo falla a mitad.
- **e) SimaticSD**: que pasos dependen de la exportacion en SimaticSD (que
  solo existe desde TIA V21).

Las citas son `ruta:linea` de `main`. Para leerlas:
`git show origin/main:<ruta>`.

---

## Las carpetas de trabajo

El workdir vive **junto al ejecutable** (en el repo, en desarrollo):

```
.build_cache/<area>/<contexto>/
├── preview/                        plano: lo que se exporta para LEER
│   └── <subcarpetas del contexto>  las declara el area
└── sincronizar/                    con la estructura de TIA
    ├── variables/{export,modified}
    └── bloques/{export,modified}
```

Tres reglas que explican casi todos los Export/Import de `main`:

1. **Preview es plano.** Se exporta con `keep_folder_structure=False` y se lee
   por el nombre que dice el `config.json`. Sirve para ensenar al operario lo
   que hay en TIA sin meterse con la estructura.

2. **Sincronizar conserva la estructura de TIA.** Se exporta con
   `keep_folder_structure=True`. El import recorre la carpeta raiz entera, y
   necesita la ruta relativa para detectar **UPDATE** en vez de **CREATE**.

3. **Variables y bloques, siempre separados.** El import recorre la carpeta
   raiz: si las tablas de tags y los bloques estan juntos, se mezclan. Por eso
   `variables/` y `bloques/` son dos carpetas hermanas, cada una con su
   `export/` (lo que salio de TIA) y su `modified/` (la copia con los cambios
   offline).

Y una cuarta, la que mas caro sale: **al importar nunca se pasa
`target_folder_path=""`**. Con la carpeta destino vacia, TIA intenta **CREATE**
en vez de **UPDATE** y falla con *"an object with the name X already exists"*.
El parametro se omite: es TIA el que actualiza donde esta.

### Las subcarpetas de preview de cada contexto

| contexto | preview | sincronizar |
|---|---|---|
| `disp` | `config/` (N_MAX), `disp/` (las 6+ tablas de tags) | `variables/`, `bloques/` |
| `entidades` | `config/` (N_MAX entidad), `disp/` (constantes), `bloques/` (DB6_ENT) | `variables/`, `bloques/` |
| `proc_db` | `bloques/` (los DB del proceso), `variables/` (tablas del proceso) | `variables/`, `bloques/` |

Las declara el area, no el nucleo: `zc_suite.nucleo.tia.workdir` solo sabe resolver
`<area>/<contexto>` y las carpetas de sincronizacion.

### Los nombres salen del `config.json`

| Que | De donde |
|---|---|
| Tabla global de N_MAX | `areas.alimentacion.global_config_table_name` |
| Tabla de N_MAX de cada tipo | `areas.alimentacion.n_max_catalog[].plc_tag_table` |
| DB de cada tipo de dispositivo | `areas.alimentacion.Dispositivos.<tipo>.db_name` |
| Tabla de tags de cada tipo | `areas.alimentacion.Dispositivos.<tipo>.tag_table` |
| DB de entidades | `areas.alimentacion.entidades.db_name` (`DB6_ENT`) |
| Tabla de tags de entidades | `areas.alimentacion.entidades.tag_table` (`6_Entidades`) |
| Carpetas de TIA | `areas.alimentacion.tia_folders` (`nmax`, `dispositivos`, `proceso`, `entidades_config`, `entidades_tags`) |
| Sufijos de N_MAX de procesos | `areas.alimentacion.procesos.n_max_suffixes` |

---

## Los ocho flujos

### function_disp_generar_preview
`areas/alimentacion/functions/function_disp_generar_preview.py`

**Que hace.** Exporta del PLC la tabla N_MAX y las tablas de tags de dispositivos en plano y calcula el diff de cada tabla contra el Excel (agregados / eliminados / renombrados), sin escribir nada en TIA. Publica el resultado en el AppCache (slot `preview_disp`) para que lo reciba la SPA.

**Pasos, en orden.**
1. Exportar etiquetas — borra `preview/` y exporta la N_MAX a `preview/config/` y las 12 tablas de tags a `preview/disp/`, ambas en plano (`keep_folder_structure=False`). (`areas/alimentacion/functions/function_disp_generar_preview.py:231`)
2. Calcular diferencias de dispositivos — por cada tipo de hw activo lee su XML plano y calcula el diff contra los dispositivos del Excel. (`areas/alimentacion/functions/function_disp_generar_preview.py:309`)
3. Calcular diferencias de N_MAX — lee el XML plano de la N_MAX y calcula el diff de valores contra el Excel del PLC activo. (`areas/alimentacion/functions/function_disp_generar_preview.py:388`)
4. Componer respuesta — arma el shape legacy `{agregados, eliminados, renombrados, todos, nmax, summary}` que consume la SPA. (`areas/alimentacion/functions/function_disp_generar_preview.py:438`)

Antes del paso 1, `on_start` valida `plc_name`, comprueba que el PLC existe en TIA (`validate_plc_in_tia`) y que existe en el Excel (`validate_plc_in_excel`), y fija el PLC activo en el AppCache (`with_plc`). (`areas/alimentacion/functions/function_disp_generar_preview.py:140`)

**a) Exporta.**
- La N_MAX se exporta con `export_tables` hacia `preview/config/` con `keep_folder_structure=False`. El nombre de la tabla sale de `global_config_table_name` = `0_Config_Dispositivos`. (`areas/alimentacion/functions/function_disp_generar_preview.py:273`)
- Las tablas de tags de dispositivos se exportan en un segundo dispatch a `preview/disp/`, también con `keep_folder_structure=False`. Los nombres salen de `Dispositivos.<hw>.tag_table` (`2000_Disp_ED`, `2000_Disp_EA`, `2000_Disp_SA`, `2000_Disp_SD`, `2000_Disp_V`, `2000_Disp_M`, `2000_Disp_M_VF`, `2000_Disp_M_SINA`, `2000_Disp_TQ`, `2000_Disp_TQ_AE`, `2000_Disp_TOT`, `2000_Disp_PID`), resueltos con `get_tag_table_name(hw)` sobre `list_hw_types_active()`. (`areas/alimentacion/functions/function_disp_generar_preview.py:289`; `core/infrastructure/config/config_manager.py:455`)
- Las carpetas las crea `DispLayout.preview_config` y `DispLayout.preview_disp` bajo `.build_cache/alimentacion/disp/preview/`, y `clean_preview()` las borra y recrea antes de exportar. (`areas/alimentacion/helpers/disp/_workdir_layout.py:62`, `:69`, `:109`)
- La carpeta TIA de origen no se consulta para el preview: `export_tables` exporta por nombre de tabla, sin carpeta destino. (`core/infrastructure/tia/tia_cmd_export.py:216`)

**b) Modifica offline.**
- El preview NO modifica nada offline: es read-only de punta a punta. Solo lee los XML exportados (`compute_diff_table` y `compute_nmax_diff` son funciones puras que devuelven dataclasses `DiffTable` / `NmaxDiff`). No hay copia a `modified/` ni carpeta `modified/` en el layout del preview. (`areas/alimentacion/helpers/disp/disp_generate_preview.py:126`, `:178`; `areas/alimentacion/helpers/disp/_workdir_layout.py:85`)

**c) Importa.**
- El preview NO importa nada en TIA. No hay ninguna llamada a `import_plc_tags_xml`, `import_block` ni `import_blocks_sd` en este flujo. (`areas/alimentacion/functions/function_disp_generar_preview.py:231`)

**d) Transacciones y compilaciones.**
- El preview NO abre transacciones ni compila. Es solo lectura: export + diff en local. Ninguno de los 4 pasos llama a `execute_transactional_batch` ni a `compile_blocks`. (`areas/alimentacion/functions/function_disp_generar_preview.py:273`, `:349`)
- Los dos `export_tables` van en dispatchs sueltos (`submit_and_wait` directo), no en batch, y con timeout de 60 s (`STEP_TIMEOUT_S = 60.0`). (`areas/alimentacion/functions/function_disp_generar_preview.py:273`, `:75`)
- Si un XML no está en el export, el diff de esa tabla se marca como ausente y se avisa por log en vez de inventar el estado de TIA; para N_MAX, `missing_xml` deja `nmax_error` informational y todos los N_MAX como `sin_cambios`. (`areas/alimentacion/helpers/disp/disp_generate_preview.py:149`, `:197`; `areas/alimentacion/functions/function_disp_generar_preview.py:424`)

**e) SimaticSD.**
- El preview NO depende de SimaticSD. Solo exporta tablas de tags en XML (SimaticML); no toca `.s7dcl` ni `.s7res`. El único parser implicado es `PlcUserConstantParser` / `PlcUserConstantModifier` sobre XML. (`core/helpers/simatic_ml/simatic_ml_user_constant_modifier.py:92`; `areas/alimentacion/helpers/disp/disp_generate_preview.py:9`)
- Sobre V18: **no está en main**. En `main` no hay ninguna detección de versión de TIA Portal en `core/infrastructure/tia/` ni en este flujo; las referencias a V21 del código son reglas de comportamiento asumidas, no ramificaciones por versión. (`core/infrastructure/tia/tia_cmd_import_.py:16`; `core/infrastructure/tia/tia_cmd_export.py:172`)

### function_disp_sincronizar
`areas/alimentacion/functions/function_disp_sincronizar.py`

**Que hace.** Exporta las tablas de tags de dispositivos con la estructura de TIA, calcula el diff contra el Excel, aplica los N_MAX y renombres online (Tx A), re-exporta y edita los XML offline para añadir/quitar tags (Tx B), compila los DBs afectados, aplica los comentarios por instancia (Tx C) y genera el preview post-sync.

**Pasos, en orden.**
1. Exportar etiquetas — borra `sincronizar/` y exporta todas las tablas selectivas (12 de dispositivos + N_MAX) a `sincronizar/variables/export/` con `keep_folder_structure=True`. (`areas/alimentacion/functions/function_disp_sincronizar.py:282`)
2. Calcular diferencias de dispositivos — localiza cada XML en el export tolerando layout plano o con jerarquía, y calcula el diff contra el Excel. (`areas/alimentacion/functions/function_disp_sincronizar.py:340`)
3. Preparar operaciones — calcula `nmax_ops`, `rename_ops` y `device_changes` (adds/removes por tabla). (`areas/alimentacion/functions/function_disp_sincronizar.py:424`)
4. Aplicar N_MAX y renombres — Tx A online: un lote transaccional con `update_user_constant_value` y `update_user_constant_name`. (`areas/alimentacion/functions/function_disp_sincronizar.py:480`)
5. Esperar consolidación TIA — sleep de 2 s para que TIA consolide internamente tras Tx A. (`areas/alimentacion/functions/function_disp_sincronizar.py:548`)
6. Re-exportar etiquetas — re-exporta solo las tablas de dispositivos con cambios (no la N_MAX) a `sincronizar/variables/export/`, con `keep_folder_structure=True`. (`areas/alimentacion/functions/function_disp_sincronizar.py:557`)
7. Editar archivos XML — copia `export/` a `modified/` filtrando la N_MAX, y edita offline cada XML de dispositivo (adds y removes). (`areas/alimentacion/functions/function_disp_sincronizar.py:604`)
8. Aplicar dispositivos — Tx B offline: importa los XML modificados con `import_plc_tags_xml` desde la raíz de `modified/`. (`areas/alimentacion/functions/function_disp_sincronizar.py:618`)
9. Compilar bloques — compila los DBs de dispositivos afectados, fuera de transacción. (`areas/alimentacion/functions/function_disp_sincronizar.py:681`)
10. Aplicar comentarios — exporta los DBs a `sincronizar/bloques/export/`, edita los `.s7dcl`/`.s7res` offline y los importa con un único `import_block` transaccional. (`areas/alimentacion/functions/function_disp_sincronizar.py:739`)
11. Generar preview post-sincronización — limpia `preview/`, re-exporta en plano y recalcula el diff para que la SPA vea "todo en sync". (`areas/alimentacion/functions/function_disp_sincronizar.py:962`)

**a) Exporta.**
- Paso 1: un `execute_batch` con un `export_tables` que exporta `self._ctx.selective_tables` a `sincronizar/variables/export/` con `keep_folder_structure=True`. La lista es data-driven: las 12 `tag_table` de `Dispositivos.<hw>.tag_table` más la N_MAX `0_Config_Dispositivos` de `global_config_table_name`. (`areas/alimentacion/functions/function_disp_sincronizar.py:311`, `:321`, `:1231`)
- La razón de `keep_folder_structure=True` está documentada en el propio código: con export plano la tabla se crearía de nuevo en vez de actualizarse, el objeto ya existe y la transacción muere con `CommitOnDispose`. (`areas/alimentacion/functions/function_disp_sincronizar.py:316`)
- Paso 6: re-exporta solo las tablas con cambios (`device_changes`), al mismo destino `sincronizar/variables/export/`, con `keep_folder_structure=True` por el mismo motivo. (`areas/alimentacion/functions/function_disp_sincronizar.py:584`, `:588`)
- Paso 10: un `execute_batch` con `export_blocks` de los DBs (`db_name` de cada hw: `DB2000_ED`, `DB2001_EA`, `DB2006_SA`, `DB2005_SD`, `DB2010_V`, `DB2015_M`, `DB2016_M_VF`, `DB2017_M_SINA`, `DB2040_TQ`, `DB2041_TQ_AE`, `DB2025_TOT`, `DB2035_PID`) a `sincronizar/bloques/export/`, con `keep_folder_structure=True` para preservar la subcarpeta TIA (`2000_Dispositivos`). (`areas/alimentacion/functions/function_disp_sincronizar.py:835`, `:840`)
- Paso 11: el preview post-sync vuelve a exportar en plano (`keep_folder_structure=False`), la N_MAX a `preview/config/` y las 12 de dispositivos a `preview/disp/`. (`areas/alimentacion/functions/function_disp_sincronizar.py:1018`, `:1027`)
- Las carpetas las crea `DispLayout`: `sync_variables_export`, `sync_variables_modified`, `sync_bloques_export`, `sync_bloques_modified`, y `clean_sincronizar()` borra y recrea `sincronizar/{variables,bloques}/{export,modified}` conservando `preview/`. (`areas/alimentacion/helpers/disp/_workdir_layout.py:78`, `:85`, `:94`, `:101`, `:117`)

**b) Modifica offline.**
- Paso 7: `_copy_and_edit_offline` hace `shutil.copytree` de `sincronizar/variables/export/` a `sincronizar/variables/modified/` con un `ignore` que EXCLUYE todo `.xml` cuyo stem no sea una tabla de dispositivo. Eso deja fuera `0_Config_Dispositivos.xml` a propósito: si se copiara, Tx B la re-importaría con sus valores pre-commit y anularía los N_MAX ya aplicados online en Tx A. (`areas/alimentacion/functions/function_disp_sincronizar.py:1374`, `:1328`)
- La edición usa `PlcUserConstantModifier`: `add_user_constants_by_table(table_name, adds)` para los adds y `remove_user_constants(removes)` para los removes; solo se guarda el XML si `was_modified()`. `adds` son dicts `{uid, plc_tag}` y `removes` son uids sueltos (`set[str]`), no dicts. (`areas/alimentacion/functions/function_disp_sincronizar.py:1403`, `:1404`, `:1406`, `:463`)
- Paso 10: los bloques van por separado. `copytree` de `sincronizar/bloques/export/` a `sincronizar/bloques/modified/`, y sobre cada `.s7dcl`/`.s7res` se llama a `commit_array_comments` con `write_to_original=True` y `array_type="Simple"` para inyectar los comentarios por instancia. La ruta del par de archivos se resuelve con `SdPair(modified_bloques / target_folder, db_name)`, donde `target_folder` es `tia_folders.dispositivos` = `2000_Dispositivos`. (`areas/alimentacion/functions/function_disp_sincronizar.py:856`, `:886`, `:892`)
- Las variables y los bloques nunca se mezclan: `variables/` y `bloques/` son subdirectorios hermanos del mismo nivel en `sincronizar/`. (`areas/alimentacion/helpers/disp/_workdir_layout.py:36`)

**c) Importa.**
- Paso 8 (Tx B): un `execute_transactional_batch` con una sola operación `import_plc_tags_xml`, `import_dir` = raíz de `sincronizar/variables/modified/`, `target_folder` = `""`. El handler hace `target_folder_raw = args.get("target_folder") or ""` y, al ser vacío, llama a `import_plc_tags(import_root_directory=import_dir)` SIN `target_folder_path`: es el camino de escaneo recursivo que hace match UPDATE preservando el subpath. (`areas/alimentacion/functions/function_disp_sincronizar.py:651`, `:655`; `core/infrastructure/tia/tia_cmd_import_.py:134`, `:140`)
- El motivo está documentado en el handler: pasar `target_folder_path=""` (string vacío) hace que TIA NO haga match UPDATE de objetos pre-existentes, intente CREATE y falle con "Import failed because an object with the name X already exists". La regla es "si el caller no pasa un `target_folder` no vacío, NO pasamos el argumento". (`core/infrastructure/tia/tia_cmd_import_.py:19`, `:57`, `:105`)
- Paso 10: un único `import_block` (no `import_blocks_sd`) con `import_dir` = raíz de `sincronizar/bloques/modified/` y `target_folder` = `""`, también envuelto en `execute_transactional_batch`. El handler `_h_import_block` aplica la misma regla de omitir `target_folder_path` cuando viene vacío. (`areas/alimentacion/functions/function_disp_sincronizar.py:932`, `:936`; `core/infrastructure/tia/tia_cmd_import_.py:208`, `:214`)
- La lectura del export previo es tolerante a ambos layouts: `_locate_table_xml` usa `XmlTarget`, que prueba la ruta plana y, si no existe, hace `rglob` en subdirectorios. (`areas/alimentacion/functions/function_disp_sincronizar.py:1317`; `core/infrastructure/tia/tia_export_paths.py:96`, `:100`)

**d) Transacciones y compilaciones.**
- Orden: Tx A (N_MAX + renombres, online) → sleep 2 s → re-export → edición offline → Tx B (import de tags, offline) → compilación → Tx C (import de bloques con comentarios) → preview post-sync. (`areas/alimentacion/functions/function_disp_sincronizar.py:484`, `:552`, `:618`, `:685`, `:739`)
- Tx A: un único `execute_transactional_batch` con todas las ops `update_user_constant_value` y `update_user_constant_name`. El lote hace `start_transaction` al principio y `end_transaction(rollback=False)` al final; si cualquier sub-comando falla, hace `end_transaction(rollback=True)` y relanza distinguiendo si lo que falló fue la operación o el commit. (`areas/alimentacion/functions/function_disp_sincronizar.py:519`; `core/infrastructure/tia/tia_cmd_batch.py:85`, `:140`, `:153`, `:172`)
- Tx B: un `execute_transactional_batch` con un solo `import_plc_tags_xml`. Si `ok` es falso, el FB lanza `RuntimeError` y el trabajo muere ahí. (`areas/alimentacion/functions/function_disp_sincronizar.py:646`, `:661`)
- Compilación: `compile_blocks` sobre los DBs afectados, FUERA de toda transacción (el commit de Tx B ya está aplicado). Los errores de compilación NO abortan el flujo: se capturan en `compile_ok=False` y `compile_error`, con un warning explícito de "commit ya aplicado". (`areas/alimentacion/functions/function_disp_sincronizar.py:689`, `:704`, `:733`)
- Tx C: el `import_block` de comentarios va envuelto en `execute_transactional_batch` para atomicidad. Ojo: a diferencia de Tx A y Tx B, aquí el FB NO comprueba el `ok` del resultado del lote; el `submit_and_wait` se descarta. (`areas/alimentacion/functions/function_disp_sincronizar.py:926`, `:921`)
- **Qué queda confirmado si algo falla a mitad**: si Tx A falla, no se aplica N_MAX ni renombres. Si Tx B falla, Tx A ya está confirmado (N_MAX y renombres aplicados en TIA) y los dispositivos no; la compilación no llega a ejecutarse. Si la compilación falla, Tx A y Tx B ya están confirmados. Si el preview post-sync falla, todo lo anterior está confirmado y solo se pierde el preview (se avisa por log y `post_sync_preview` queda a `None`). (`areas/alimentacion/functions/function_disp_sincronizar.py:527`, `:661`, `:719`, `:1141`)
- `compile_blocks` está en la lista de comandos prohibidos dentro de un lote transaccional (`_TRANSACTION_FORBIDDEN_COMMANDS`), junto con lifecycle, listados y el propio `execute_transactional_batch` (no se admite nesting). (`core/infrastructure/tia/tia_cmd_batch.py:49`, `:55`)
- `STEP_TIMEOUT_S = 600.0` (10 min) y `TIA_CONSOLIDATION_SLEEP_S = 2.0`. (`areas/alimentacion/functions/function_disp_sincronizar.py:91`, `:78`)

**e) SimaticSD.**
- El paso 10 ("Aplicar comentarios") es el que depende de SimaticSD: `export_blocks` con `export_format="SimaticSD"` genera los `.s7dcl`/`.s7res` de cada DB, y `commit_array_comments` los edita offline (inyecta, elimina, actualiza o añade bloques `{ S7_MLC := ... }` según los 4 casos del helper). (`core/infrastructure/tia/tia_cmd_export.py:87`; `core/helpers/simatic_sd/simatic_sd_db_array_comment_updater.py:241`, `:300`)
- El resto del flujo (pasos 1-9 y 11) NO depende de SimaticSD: es todo XML de tablas de tags.
- Sobre V18: **no está en main**. En `main` no hay ramificación por versión de TIA en estos flujos, ni detección de versión en `core/infrastructure/tia/`. El formato esperado por el helper SimaticSD está documentado como "TIA V21 export" y la lectura se hace con `utf-8-sig` porque "TIA V21 exporta los archivos en UTF-8 con BOM", pero el código asume ese formato sin comprobar la versión. (`core/helpers/simatic_sd/simatic_sd_db_array_comment_updater.py:20`, `:80`, `:82`)
- La regla de `keep_folder_structure` está anotada como "V21+": al exportar con `keep_folder_structure=True`, TIA deposita el `.xml` en un subdirectorio (`Tags/` o similar), y el helper `XmlTarget` existe justo para tolerarlo. (`core/infrastructure/tia/tia_export_paths.py:72`, `:99`)

### function_entidades_generar_preview
`areas/alimentacion/functions/function_entidades_generar_preview.py`

**Que hace.** Exporta del PLC las dos tablas de etiquetas y el DB de entidades, calcula el diff contra el Excel (N_MAX_ENTIDAD, constantes `PlcUserConstant` y comentarios del array `ENT[]`) y publica la previsión en el AppCache. Es read-only: no escribe nunca en TIA.

**Pasos, en orden.**
1. Exportar etiquetas y DB — limpia `preview/` y exporta las 2 tablas (plano) más el `DB6_ENT`. (`areas/alimentacion/functions/function_entidades_generar_preview.py:225`)
2. Calcular diferencias de N_MAX_ENTIDAD — lee `0_Config_Generales.xml` del export y compara `N_MAX_ENTIDAD` con el Excel. (`areas/alimentacion/functions/function_entidades_generar_preview.py:326`)
3. Calcular diferencias de constantes — lee `6_Entidades.xml` y compara las `PlcUserConstant` con el Excel. (`areas/alimentacion/functions/function_entidades_generar_preview.py:375`)
4. Calcular diferencias de comentarios — lee `DB6_ENT.s7dcl`/`.s7res` y compara los comentarios de los slots del array `ENT[]`. (`areas/alimentacion/functions/function_entidades_generar_preview.py:421`)
5. Componer respuesta — une los tres diffs en la shape que consume la SPA. (`areas/alimentacion/functions/function_entidades_generar_preview.py:479`)

**a) Exporta.**
- Los nombres salen del bloque `entidades` de `config.json`: `db_name` (`DB6_ENT`), `db_array_name` (`ENT`), `tag_table` (`6_Entidades`), `config_table` (`0_Config_Generales`). Se leen vía `ConfigManager.get_entidades_config()`, que devuelve esas 4 claves. (`core/infrastructure/config/config_manager.py:569`, `:586`; `areas/alimentacion/functions/function_entidades_generar_preview.py:262`). Si el bloque viene vacío el FB aborta (`areas/alimentacion/functions/function_entidades_generar_preview.py:257`).
- Las dos tablas de tags salen del PLC con **un solo** `export_tables` a `preview/disp/`, **PLANO** (`keep_folder_structure=False` explícito). La lista de tablas es `[config_table, tag_table]`, o sea `0_Config_Generales` y `6_Entidades`. (`areas/alimentacion/functions/function_entidades_generar_preview.py:277`)
- El DB `DB6_ENT` sale con `export_blocks` a `preview/bloques/`. **No** se pasa `keep_folder_structure`, así que el handler aplica su default `False` → **PLANO**: `.s7dcl` + `.s7res` en la raíz de la carpeta. (`areas/alimentacion/functions/function_entidades_generar_preview.py:302`; `core/infrastructure/tia/tia_cmd_export.py:58`, `:88`)
- Aviso para la reescritura: en `main` **las dos tablas van juntas a `preview/disp/`**. La carpeta `preview/config/` la crea el layout pero el FB de entidades **no la usa**; el FB de dispositivos sí separa el N_MAX en `preview/config/`. El reparto `preview/config/` = N_MAX y `preview/disp/` = constantes es un cambio del diseño nuevo, no el comportamiento de `main`. (`areas/alimentacion/helpers/entidades/_workdir_layout.py:60`; `areas/alimentacion/functions/function_disp_generar_preview.py:277`)
- Formatos: el bloque se exporta en SimaticSD (`core/infrastructure/tia/tia_cmd_export.py:87`); las PlcTagTables no aceptan `export_format` y el wrapper TIA escribe el XML directamente (`core/infrastructure/tia/tia_cmd_export.py:169`).
- Antes de exportar se llama a `clean_preview()`, que borra y recrea `preview/{config,disp,bloques}`. (`areas/alimentacion/functions/function_entidades_generar_preview.py:251`; `areas/alimentacion/helpers/entidades/_workdir_layout.py:116`)
- Si el worker TIA devuelve `None` (tabla o bloque que no existen en TIA) el FB **no aborta**: mete warning, marca `missing_xml` y sigue; el diff de esa parte sale vacío. (`areas/alimentacion/functions/function_entidades_generar_preview.py:287`, `:311`)

**b) Modifica offline.**
- El preview **no modifica nada**: no hay copia a `modified/` ni escritura en disco. Todo el diff se calcula en memoria sobre los ficheros recién exportados.
- Lecturas: `preview/disp/0_Config_Generales.xml`, `preview/disp/6_Entidades.xml` y `preview/bloques/DB6_ENT.s7dcl` + `.s7res` vía `SdPair`. (`areas/alimentacion/functions/function_entidades_generar_preview.py:346`, `:387`, `:435`; `core/infrastructure/tia/tia_export_paths.py:63`)
- El "lado Excel" (desired) sale del caché de Excel ya filtrado por PLC: `get_nmax_entidades()` para el N_MAX y `get_entidades()` para las constantes. (`core/helpers/tia/active_cache.py:89`, `:129`)

**c) Importa.**
- No importa nada. El preview no escribe en TIA en ningún punto; su único efecto es de lectura.

**d) Transacciones y compilaciones.**
- Ninguna transacción y ninguna compilación: todo es lectura.
- El resultado se publica en el AppCache en `on_finish`, en el slot `preview_disp`, que es el canal SSE hacia la SPA. (`areas/alimentacion/functions/function_entidades_generar_preview.py:211`, `:215`)
- Si un stage previo no completó, el stage 5 devuelve una shape vacía pero válida con `precondiciones_ok=False`. (`areas/alimentacion/functions/function_entidades_generar_preview.py:496`)

**e) SimaticSD.**
- **Sí depende de SimaticSD**, en el paso 4 (comentarios): el diff de los slots del array `ENT[]` se calcula leyendo el par `.s7dcl` + `.s7res` que TIA exportó en SimaticSD. (`areas/alimentacion/functions/function_entidades_generar_preview.py:435`; `core/infrastructure/tia/tia_cmd_export.py:87`)
- El parser es `find_array_slots` + `read_current_comments` del helper de SimaticSD, reutilizado por `compute_comments_diff`. (`areas/alimentacion/helpers/entidades/entidades_generate_preview.py:522`, `:523`)
- Slots presentes en el Excel pero no en TIA → `added`; slots presentes en TIA pero no en el Excel **no** se marcan para eliminar (`removed = []`, preservación defensiva). (`areas/alimentacion/helpers/entidades/entidades_generate_preview.py:537`, `:538`)
- V18: **no está en main**. En `main` no hay ninguna rama, constante ni comentario sobre V18 en el código de SimaticSD; el formato documentado es el de export de **TIA V21** y el encoding es UTF-8 con BOM leído con `utf-8-sig`. (`core/helpers/simatic_sd/simatic_sd_db_array_comment_updater.py:20`, `:78`, `:82`)

### function_entidades_sincronizar
`areas/alimentacion/functions/function_entidades_sincronizar.py`

**Que hace.** Aplica contra TIA el diff de entidades del preview: tres transacciones (NMAX online, constantes offline, comentarios del DB offline), compilación del `DB6_ENT` y un preview post-sincronización. No hace `save_project`: el operario guarda a mano en TIA Portal.

**Pasos, en orden.**
1. Exportar etiquetas y DB — limpia `sincronizar/` y exporta las 2 tablas y el `DB6_ENT` **con estructura TIA**. (`areas/alimentacion/functions/function_entidades_sincronizar.py:255`)
2. Calcular diferencias — diff de constantes, NMAX y comentarios sobre los ficheros exportados. (`areas/alimentacion/functions/function_entidades_sincronizar.py:361`)
3. Preparar operaciones — reparte las ops en NMAX (Tx A), constantes (Tx B) y comentarios de slot (Tx C). (`areas/alimentacion/functions/function_entidades_sincronizar.py:482`)
4. Aplicar NMAX online (Tx A) — transacción online que cambia el valor de `N_MAX_ENTIDAD` y redimensiona el array `ENT[]`. (`areas/alimentacion/functions/function_entidades_sincronizar.py:606`)
5. Esperar consolidacion TIA — sleep de 2 s para que TIA internalice el redimensionado. (`areas/alimentacion/functions/function_entidades_sincronizar.py:689`)
6. Re-exportar etiquetas y DB — re-exporta tablas y bloque con el tamaño ya actualizado. (`areas/alimentacion/functions/function_entidades_sincronizar.py:716`)
7. Editar XMLs offline — copia `export/` a `modified/` y edita el XML de constantes y el par SD del DB. (`areas/alimentacion/functions/function_entidades_sincronizar.py:785`)
8. Aplicar constantes offline (Tx B) — importa `6_Entidades.xml` desde `variables/modified/`. (`areas/alimentacion/functions/function_entidades_sincronizar.py:953`)
9. Compilar bloques — compila `DB6_ENT` para consolidar estructuras. (`areas/alimentacion/functions/function_entidades_sincronizar.py:1024`)
10. Aplicar comentarios offline (Tx C) — importa el `DB6_ENT` modificado desde `bloques/modified/`. (`areas/alimentacion/functions/function_entidades_sincronizar.py:1087`)
11. Generar preview post-sincronizacion — re-export plano y recalcula el diff para que la SPA vea "todo en sync". (`areas/alimentacion/functions/function_entidades_sincronizar.py:1162`)

**a) Exporta.**
- Los nombres salen del bloque `entidades` de `config.json`, leídos con `get_entidades_config()` en el stage 1. (`areas/alimentacion/functions/function_entidades_sincronizar.py:282`; `core/infrastructure/config/config_manager.py:569`)
- `sincronizar/variables/export/`: las dos tablas (`0_Config_Generales` y `6_Entidades`) con **un solo** `export_tables` y `keep_folder_structure=True` → **CON estructura TIA**: cada `.xml` queda en su subcarpeta de TIA (`0_Sistema` para la de config y `6_Entidades` para la de tags, según `tia_folders`). La razón está documentada en el propio código: TIA V21 hace match UPDATE recursivo por subpath; sin la subcarpeta el `.xml` queda plano y TIA no encuentra la ruta esperada al reimportar. (`areas/alimentacion/functions/function_entidades_sincronizar.py:299`; `core/infrastructure/config/config_manager.py:540`, `:554`)
- `sincronizar/bloques/export/`: el `DB6_ENT` con `export_blocks` y `keep_folder_structure=True` → **CON estructura TIA**. Sin esto, el `import_block` de la Tx C falla con "Import failed because an object with the name 'DB6_ENT' already exists" porque TIA no puede determinar la subcarpeta destino del UPDATE. (`areas/alimentacion/functions/function_entidades_sincronizar.py:328`)
- Variables y bloques van **siempre a carpetas separadas**, porque son comandos de import distintos (`import_plc_tags_xml` vs `import_block`) y no pueden mezclarse. (`areas/alimentacion/helpers/entidades/_workdir_layout.py:34`, `:35`)
- `clean_sincronizar()` borra y recrea `sincronizar/{variables,bloques}/{export,modified}` antes de exportar. (`areas/alimentacion/functions/function_entidades_sincronizar.py:275`; `areas/alimentacion/helpers/entidades/_workdir_layout.py:124`)
- Las rutas de lectura de los XML respetan la subcarpeta TIA: `variables/export/<tia_folder_tags>/6_Entidades.xml` y `variables/export/<tia_folder_config>/0_Config_Generales.xml`. (`areas/alimentacion/functions/function_entidades_sincronizar.py:391`, `:396`)
- Re-export del paso 6 (solo si hubo NMAX op): repite los mismos dos exports con `keep_folder_structure=True` sobre las **mismas** carpetas `export/`, sobrescribiendo con el estado ya redimensionado. (`areas/alimentacion/functions/function_entidades_sincronizar.py:737`, `:743`, `:759`, `:765`)

**b) Modifica offline.**
- El `export/` se copia a `modified/` y **ahí** se edita. Cuatro sub-pasos:
  1. `copytree` **filtrado** de `variables/export/` a `variables/modified/`: se excluye `0_Config_Generales.xml` (la tabla del NMAX) porque el NMAX ya se aplicó online en la Tx A y la Tx B reimportaría los valores pre-commit, anulando la Tx A. (`areas/alimentacion/functions/function_entidades_sincronizar.py:826`, `:831`, `:797`)
  2. Edición offline de `variables/modified/<tia_folder_tags>/6_Entidades.xml` con `PlcUserConstantModifier`: adds, removes y cambios de comentario; solo se guarda si `was_modified()`. El modificador es offline puro (XML con `ElementTree`, sin `siemens_tia_scripting`). (`areas/alimentacion/functions/function_entidades_sincronizar.py:848`, `:854`, `:867`, `:873`, `:875`, `:878`; `core/helpers/simatic_ml/simatic_ml_user_constant_modifier.py:12`)
  3. `copytree` simple de `bloques/export/` a `bloques/modified/`, conservando la estructura TIA. (`areas/alimentacion/functions/function_entidades_sincronizar.py:893`, `:896`)
  4. Edición offline de `bloques/modified/<tia_folder>/DB6_ENT.s7dcl` + `.s7res` con `commit_array_comments(..., array_type="UDT", write_to_original=True)`. Con `write_to_original=True` escribe in-place sobre los archivos de `modified/`. (`areas/alimentacion/functions/function_entidades_sincronizar.py:911`, `:916`, `:925`; `core/helpers/simatic_sd/simatic_sd_db_array_comment_updater.py:248`, `:414`, `:418`)
- Los comentarios de slot del DB se aplican **siempre** (política "manda el Excel"): una op `update_comment` por entidad del Excel con comentario no vacío, sin diff. (`areas/alimentacion/functions/function_entidades_sincronizar.py:585`, `:592`)
- El rename de una `PlcUserConstant` se materializa como remove + add con el mismo value, porque en TIA la constante se identifica por `Name`. (`areas/alimentacion/functions/function_entidades_sincronizar.py:552`, `:558`, `:562`)

**c) Importa.**
- Tx B: `import_plc_tags_xml` con `import_dir = sincronizar/variables/modified/` y `target_folder: ""`. (`areas/alimentacion/functions/function_entidades_sincronizar.py:993`, `:1006`, `:1007`)
- Tx C: `import_block` con `import_dir = sincronizar/bloques/modified/` y `target_folder: ""`. (`areas/alimentacion/functions/function_entidades_sincronizar.py:1126`, `:1135`, `:1136`)
- `target_folder=""` es la forma de que el handler **omite** el argumento y deje que TIA use su default `None` = escaneo recursivo con match UPDATE por nombre preservando el subpath. Pasar `target_folder_path=""` a TIA hace que NO haga match UPDATE de los objetos preexistentes: intenta CREATE y falla con "Import failed because an object with the name X already exists". En la reescritura el parámetro **se omite**, nunca se pasa `""`. (`core/infrastructure/tia/tia_cmd_import_.py:19`, `:22`, `:134`, `:140`, `:208`, `:214`)
- El import recorre la carpeta raíz **entera**: de ahí la necesidad de exportar con estructura y de que variables y bloques estén en carpetas separadas — el `import_root_directory` que se pasa a TIA es la raíz de `modified/`, y el subpath relativo es lo que permite el UPDATE. (`core/infrastructure/tia/tia_cmd_import_.py:140`)

**d) Transacciones y compilaciones.**
- Tres transacciones TIA, cada una en su propio `execute_transactional_batch`:
  1. **Tx A (paso 4) — online puro**: `update_user_constant_value` sobre `N_MAX_ENTIDAD` en la tabla `0_Config_Generales`; redimensiona el array `ENT[]` del `DB6_ENT` en la sesión de TIA. El handler hace doble validación: `set_property` debe devolver 0 y el valor releído debe coincidir, por el fallo silencioso de Pythonnet en TIA V21. (`areas/alimentacion/functions/function_entidades_sincronizar.py:639`, `:523`; `core/infrastructure/tia/tia_cmd_user_consts.py:127`, `:135`)
  2. **Tx B (paso 8) — offline puro**: importa el `6_Entidades.xml` modificado. (`areas/alimentacion/functions/function_entidades_sincronizar.py:993`)
  3. **Tx C (paso 10) — offline puro**: importa el `DB6_ENT` modificado. (`areas/alimentacion/functions/function_entidades_sincronizar.py:1126`)
- `execute_transactional_batch` hace `start_transaction` → ejecuta las ops → `end_transaction(rollback=False)`; si cualquier sub-comando falla hace `end_transaction(rollback=True)` y relanza, y el mensaje distingue si falló la operación o el commit. (`core/infrastructure/tia/tia_cmd_batch.py:85`, `:140`, `:153`, `:168`, `:177`)
- `compile_blocks` está **prohibido dentro de un lote transaccional**, así que las compilaciones van fuera de las transacciones. Hay dos: (`core/infrastructure/tia/tia_cmd_batch.py:49`, `:56`)
  1. Compilación **defensiva** del `DB6_ENT` justo después de la Tx A, para forzar a TIA a regenerar la estructura del array redimensionado; si falla, solo warning y el sync sigue. (`areas/alimentacion/functions/function_entidades_sincronizar.py:658`, `:667`, `:676`)
  2. Compilación normal del `DB6_ENT` en el paso 9, entre Tx B y Tx C; **no aborta**: marca `compile_ok=False` y `compile_error` y continúa. (`areas/alimentacion/functions/function_entidades_sincronizar.py:1048`, `:1057`, `:1075`)
- Orden completo: Tx A → sleep 2 s → re-export → edición offline → Tx B → compile → Tx C → preview post-sync. El sleep es `TIA_CONSOLIDATION_SLEEP_S = 2.0`. (`areas/alimentacion/functions/function_entidades_sincronizar.py:85`, `:710`)
- **Qué queda confirmado si algo falla a mitad**: cada transacción es atómica por separado, no hay transacción global. Si falla la Tx B, se hace rollback de la Tx B (las constantes **no** quedan confirmadas) pero la **Tx A ya está confirmada** (el NMAX queda aplicado en TIA). Si falla la Tx C, quedan confirmadas la Tx A y la Tx B y solo se pierden los comentarios del array. Un fallo de la Tx A aborta el flujo. (`core/infrastructure/tia/tia_cmd_batch.py:169`, `:172`; `areas/alimentacion/functions/function_entidades_sincronizar.py:648`)
- El paso 11 (preview post-sync) re-exporta **plano** a `preview/` y recalcula el diff; si el re-export falla, emite warning y deja `post_sync_preview=None` sin abortar. (`areas/alimentacion/functions/function_entidades_sincronizar.py:1182`, `:1191`, `:1205`)
- No hay `save_project`: los cambios quedan en memoria de TIA Portal y el operario pulsa Save manual. (`areas/alimentacion/functions/function_entidades_sincronizar.py:504`, `:627`)

**e) SimaticSD.**
- **Sí depende de SimaticSD**, en dos puntos:
  - Lectura para el diff: el `DB6_ENT` se exporta en SimaticSD (`.s7dcl` + `.s7res`) y el paso 2 lee ese par desde `bloques/export/` para calcular los comentarios actuales de los slots. (`areas/alimentacion/functions/function_entidades_sincronizar.py:443`, `:444`, `:522`)
  - Edición offline: `commit_array_comments` reescribe el `.s7dcl` (inyección/actualización/borrado de MLC) y el `.s7res` (YAML con `MultiLingualTexts`) del `DB6_ENT` en `bloques/modified/`. (`core/helpers/simatic_sd/simatic_sd_db_array_comment_updater.py:241`, `:404`, `:420`)
- La reimportación del DB usa `import_block`, que acaba llamando a `import_blocks` de TIA. (`core/infrastructure/tia/tia_cmd_import_.py:208`, `:214`)
- V18: **no está en main**. En `main` no hay ninguna mención, constante ni rama para V18 en el código de SimaticSD ni en el de import.

### function_proc_db_generar_preview
`areas/alimentacion/functions/function_proc_db_generar_preview.py`

**Que hace.** Calcula, en solo lectura, el diff entre los comentarios que hay ahora en TIA y los que quiere el Excel para los DB de parámetros y de alarmas de un proceso, más el diff de sus N_MAX. No escribe nada en TIA.

**Pasos, en orden.**
1. Validar estado de TIA — comprueba que el Excel del área está cargado en el AppCache; si no, marca `excel_loaded=False` y sigue (no aborta). (`areas/alimentacion/functions/function_proc_db_generar_preview.py:283`, `:296-305`)
2. Validar bloques — comprueba que hay caché de bloques del PLC; marca `bloques_loaded`. (`areas/alimentacion/functions/function_proc_db_generar_preview.py:309`, `:323`)
3. Construir mapa de slots — `proc_build_slot_maps` cruza Excel + caché de bloques y devuelve los nombres canónicos de DB_PARAM, DB_ALM y de la tabla, los slot maps por array y los N_MAX; si revienta, el error se guarda y no se propaga. (`areas/alimentacion/functions/function_proc_db_generar_preview.py:330`, `:352-358`)
4. Calcular diferencias de N_MAX — exporta la tabla de tags del proceso y compara sus PlcUserConstant con los valores del Excel. (`areas/alimentacion/functions/function_proc_db_generar_preview.py:381`, `:429-450`)
5. Exportar y calcular diferencias — exporta DB_PARAM + DB_ALM en SimaticSD y lee los comentarios `es-ES` actuales. (`areas/alimentacion/functions/function_proc_db_generar_preview.py:477`, `:546-616`)
6. Componer respuesta — arma el `result` legacy que consume la SPA y lo publica en el AppCache. (`areas/alimentacion/functions/function_proc_db_generar_preview.py:623`, `:644-742`, `:237`, `:272`)

**a) Exporta.**
- Dos exports, ambos **planos**, a dos carpetas hermanas del workdir:
  - **Tabla de tags del proceso** (donde viven los N_MAX): `export_tables` con `table_names=[<uid>_<codigo>]` y `keep_folder_structure=False` explícito → `preview/variables/`. (`areas/alimentacion/functions/function_proc_db_generar_preview.py:425`, `:430-441`)
  - **DBs del proceso**: `export_blocks` con `block_names=[<db_param_name>, <db_alm_name>]` → `preview/bloques/`, en SimaticSD (`.s7dcl` + `.s7res`). No se pasa `keep_folder_structure`, así que hereda el default `False` del handler: plano. (`areas/alimentacion/functions/function_proc_db_generar_preview.py:520`, `:546-554`; `core/infrastructure/tia/tia_cmd_export.py:51-58`, `:85-89`)
- **Los nombres no salen del `config.json` en este flujo**: se computan del Excel. `db_param_name = DB<num_db>_<codigo>_PARAM`, `db_alm_name = DB<num_db>_<codigo>_ALM` (el `num_db` sale de la primera fila del Excel que casa con el proceso; si no hay filas, fallback `num_db = uid` con warning) y `table_name = <uid>_<codigo>`. (`areas/alimentacion/data/data_proc_slot_map.py:277`, `:288`, `:290`, `:130-163`)
- Del `config.json` solo sale el nombre de las constantes N_MAX: los sufijos `preal/pint/alm/alm_hmi` de `procesos.n_max_suffixes`, con los que se compone `<uid>_N_MAX_<SUFIJO>`. (`areas/alimentacion/data/data_proc_slot_map.py:354`, `:369-370`)
- La carpeta TIA de cada DB tampoco sale del config: sale del `ruta` cacheado en el escaneo (`ProgramBlock.get_path()`, jerarquía de grupos con separador `/`, sin el nombre del bloque). Ese `ruta` es el `param_subpath`/`alm_subpath` del slot map. (`core/data/data_block_plc.py:11-14`; `areas/alimentacion/data/data_proc_slot_map.py:312-319`)
- El `.xml` de la tabla se localiza con `XmlTarget`, que tolera los dos layouts (directo o en subcarpeta). (`core/infrastructure/tia/tia_export_paths.py:94-108`; `areas/alimentacion/functions/function_proc_db_generar_preview.py:444`)

**b) Modifica offline.**
- El preview **no modifica nada**: solo lee. Los `.s7dcl`/`.s7res` se parsean en memoria (`read_current_comments` busca el MLC del `.s7dcl` y resuelve su texto `es-ES` en el `.s7res`) y el `.xml` se parsea para sacar los N_MAX. (`areas/alimentacion/helpers/proc/proc_db_generar_preview.py:345-377`; `core/helpers/simatic_sd/simatic_sd_db_array_comment_updater.py:204-238`)
- El diff se monta con helpers puros: `compute_proc_slot_diff`, `compute_nmax_diff_for_proc`, `compose_arrays` y `compute_summary`. (`areas/alimentacion/helpers/proc/proc_db_generar_preview.py:312`, `:212`, `:45`, `:138`)
- No hay carpeta `modified/`: en el layout de `proc_db` el `modified/` es solo del `sincronizar/`. (`areas/alimentacion/helpers/proc/_workdir_layout.py:60-72`, `:84-88`)

**c) Importa.**
- **No importa nada.** El preview es de solo lectura: sus dos únicos despachos al worker son `export_tables` y `export_blocks`. (`areas/alimentacion/functions/function_proc_db_generar_preview.py:430`, `:546`; `core/infrastructure/tia/tia_cmd_export.py:21`)
- Lo que deja es el workdir (`preview/bloques/`, `preview/variables/`) y el resultado publicado en el AppCache (`area_set_preview_proc`) para que la SPA lo reciba por SSE. (`areas/alimentacion/functions/function_proc_db_generar_preview.py:272`)

**d) Transacciones y compilaciones.**
- Ninguna: el preview no abre transacción de TIA ni compila; solo despacha dos comandos de lectura con `submit_and_wait`. (`areas/alimentacion/functions/function_proc_db_generar_preview.py:430`, `:546`; `core/infrastructure/tia/tia_cmd_export.py:21`)
- Modo degradado: si falla el export de uno solo de los dos DBs, el preview sigue y avisa por warning; si fallan los dos, los tres `current` quedan a `None` y el preview sale con warning, no con error. (`areas/alimentacion/functions/function_proc_db_generar_preview.py:576-586`, `:588-602`)

**e) SimaticSD.**
- El paso 5 depende de SimaticSD: `export_blocks` exporta con `export_format="SimaticSD"` y produce el par `.s7dcl` + `.s7res` que luego se lee. (`core/infrastructure/tia/tia_cmd_export.py:6`, `:85-89`; `core/infrastructure/tia/tia_export_paths.py:21-22`)
- El paso 4 (N_MAX) **no** depende de SimaticSD: es una tabla de tags en XML SimaticML. (`core/infrastructure/tia/tia_cmd_export.py:8`)
- En V18: la exportación de bloques en SimaticSD no existe, así que el paso 5 no tiene salida y el preview solo puede dar el diff de N_MAX. Ese dato **no está en main**: la regla "SimaticSD solo desde V21" viene de la rama de reescritura (`docs/INSTALAR.md:20`; `docs/PROBLEMAS.md:102-107`), no de `main`.

### function_proc_db_sincronizar
`areas/alimentacion/functions/function_proc_db_sincronizar.py`

**Que hace.** Aplica contra TIA los comentarios de los DB de un proceso (PARAM y ALM) y sus N_MAX: primero cambia los N_MAX en línea y compila, y después reexporta, edita offline e importa los bloques con los comentarios nuevos.

**Pasos, en orden.**
1. Validar estado de TIA — exige el Excel del área cargado; si no, aborta con `RuntimeError`. (`areas/alimentacion/functions/function_proc_db_sincronizar.py:285`, `:293-303`)
2. Validar bloques — exige caché de bloques del PLC; si no, aborta. (`areas/alimentacion/functions/function_proc_db_sincronizar.py:308`, `:312-318`)
3. Construir mapa de slots — recalcula el slot map y aborta si la tabla del proceso no existe en TIA o si faltan los dos DBs; si falta uno solo, avisa y sigue. De paso calcula las ops de N_MAX. (`areas/alimentacion/functions/function_proc_db_sincronizar.py:323`, `:344-383`)
4. Aplicar N_MAX — Tx A online: un `execute_transactional_batch` con un `update_user_constant_value` por cada N_MAX cambiado. (`areas/alimentacion/functions/function_proc_db_sincronizar.py:420`, `:460-476`)
5. Esperar consolidación TIA — sleep de 2 s para que TIA consolide el cambio de N_MAX. (`areas/alimentacion/functions/function_proc_db_sincronizar.py:483`, `:487`, `:67`)
6. Compilar bloques — `compile_blocks` con DB_PARAM + DB_ALM (los que no estén en `db_missing`), para validar el resize del array. (`areas/alimentacion/functions/function_proc_db_sincronizar.py:495`, `:505-561`)
7. Abrir transacción TIA — Tx B: limpia `sincronizar/`, reexporta los DBs, edita los comentarios offline e importa. (`areas/alimentacion/functions/function_proc_db_sincronizar.py:582`, `:606-786`)
8. Generar preview post-sincronización — vuelve a exportar y recomponer el diff para que la SPA vea "todo en sync". (`areas/alimentacion/functions/function_proc_db_sincronizar.py:796`, `:829-963`)
9. Componer respuesta — vuelca `ctx.result` y lo publica en el AppCache. (`areas/alimentacion/functions/function_proc_db_sincronizar.py:977`, `:986-1003`, `:268-274`)

**a) Exporta.**
- **N_MAX: no se exporta para editar.** El sync lee el `.xml` de la tabla del proceso que dejó el preview anterior (`preview/variables/`) y de ahí calcula las ops. Si el XML no está, aborta con un mensaje que pide lanzar el preview antes del commit. (`areas/alimentacion/functions/function_proc_db_sincronizar.py:410-412`, `:414-416`, `:1067-1075`)
- **DBs del proceso (Tx B)**: un `export_blocks` por cada DB presente en TIA, cada uno a `sincronizar/bloques/export/<subpath>/`, donde `<subpath>` es el `param_subpath`/`alm_subpath` del bloque (su ruta dentro del PLC). El export es **plano** y la jerarquía de TIA se replica a mano: el destino del export es ya la subcarpeta que le toca a cada bloque. (`areas/alimentacion/functions/function_proc_db_sincronizar.py:1234-1241`, `:1246-1265`; `core/infrastructure/tia/tia_cmd_export.py:51-58`)
  - Esto es lo que evita el problema "S1" (import que hace CREATE en vez de UPDATE): el bloque se importa desde la misma ruta relativa en la que estaba en TIA. En `main` está escrito explícitamente que el sync de proc_db exporta plano y replica la jerarquía por su cuenta, y que esa rama de import no se ha ejercitado contra TIA en el smoke. (`docs/ESTADO_RUNTIME_OB1.md:189-214`, `:615-618`)
- **Post-preview (paso 8)**: vuelve a exportar los 2 DBs a `preview/bloques/` y la tabla a `preview/variables/` con `keep_folder_structure=False` explícito, porque es solo lectura. (`areas/alimentacion/functions/function_proc_db_sincronizar.py:838-874`)
- Los nombres de DB y de tabla se computan igual que en el preview, a partir del Excel y no del `config.json` (`areas/alimentacion/data/data_proc_slot_map.py:277`, `:288`, `:290`); del config solo salen los sufijos N_MAX.

**b) Modifica offline.**
- El export de Tx B se edita **en el sitio**: `commit_array_comments(..., write_to_original=True)` escribe sobre los `.s7dcl`/`.s7res` de `sincronizar/bloques/export/<subpath>/`, acumulando cambios de varios arrays en el mismo archivo. (`areas/alimentacion/functions/function_proc_db_sincronizar.py:664-677`, `:699-712`; `core/helpers/simatic_sd/simatic_sd_db_array_comment_updater.py:241-249`, `:271-275`)
- 6 arrays en DB_PARAM (`PReal`, `PReal_Vis`, `Aux.PReal_ValorAnterior`, `PInt`, `PInt_Vis`, `Aux.PInt_ValorAnterior`) y 1 en DB_ALM (`ALM`). (`areas/alimentacion/functions/function_proc_db_sincronizar.py:646-653`, `:708`)
- Lo que se escribe es el mapa "Excel + eliminar": los slots que existen en TIA y no en el Excel se resetean a `"."`. (`areas/alimentacion/functions/function_proc_db_sincronizar.py:627-629`, `:1371-1395`)
- Después se copia el árbol exportado a `sincronizar/bloques/modified/<subpath>/` con `copytree`; **lo que se importa es la copia modificada, no el export**. (`areas/alimentacion/functions/function_proc_db_sincronizar.py:735-763`)
- El paso 4 lee los comentarios actuales para poder detectar los "eliminar"; si el parseo falla, se sigue en modo degradado (solo se aplican los slots del Excel). (`areas/alimentacion/functions/function_proc_db_sincronizar.py:1309-1368`)
- `sincronizar/variables/{export,modified}` existe en el layout pero **el sync de proc_db no lo usa**: las tablas de tags no se editan offline en este flujo, los N_MAX se cambian en línea. (`areas/alimentacion/helpers/proc/_workdir_layout.py:77-88`)

**c) Importa.**
- Importa desde `sincronizar/bloques/modified/` (raíz completa, recursivo) con un único comando `import_block` dentro del lote transaccional. (`areas/alimentacion/functions/function_proc_db_sincronizar.py:768-786`; `core/infrastructure/tia/tia_cmd_import_.py:171-215`)
- El caller pasa la carpeta destino **vacía** (`"target_folder": ""`), y el handler la interpreta como "no la pasa": si `target_folder` llega vacío llama a `import_blocks(import_root_directory=...)` **sin** `target_folder_path`, que es lo que hace que TIA haga UPDATE por nombre conservando la ruta relativa. (`areas/alimentacion/functions/function_proc_db_sincronizar.py:780`; `core/infrastructure/tia/tia_cmd_import_.py:208-214`, `:92-98`)
- Regla para la reescritura: **nunca pasar `target_folder_path=""` a TIA**. Con la carpeta destino vacía, TIA intenta CREATE en vez de UPDATE y falla con *"Import failed because an object with the name X already exists"*; validado en VM. El parámetro se omite y es TIA el que actualiza donde está. (`core/infrastructure/tia/tia_cmd_import_.py:47-60`, `:176-187`)
- El import recorre la carpeta raíz entera, así que las tablas de tags no pueden estar mezcladas con los bloques: de ahí que `variables/` y `bloques/` sean carpetas hermanas. En `main` este flujo solo importa bloques (las tags del proceso no se reimportan). (`areas/alimentacion/helpers/proc/_workdir_layout.py:14-21`)
- Antes de importar, `sincronizar/` se borra y se recrea, para que no queden archivos stale de una ejecución anterior (un stale es justamente un "object with the name X already exists"). (`areas/alimentacion/functions/function_proc_db_sincronizar.py:1195-1207`; `areas/alimentacion/helpers/proc/_workdir_layout.py:116-123`)

**d) Transacciones y compilaciones.**
- Dos transacciones, en este orden:
  1. **Tx A (online, N_MAX)**: `execute_transactional_batch` con un `update_user_constant_value` por constante. Si falla, el handler hace rollback de toda la cadena y el error sube como excepción; los N_MAX quedan sin aplicar. (`areas/alimentacion/functions/function_proc_db_sincronizar.py:460-475`; `core/infrastructure/tia/tia_cmd_batch.py:85`, `:140`, `:148-184`)
  2. **Compilación** entre Tx A y Tx B: 2 s de sleep + `compile_blocks` de DB_PARAM y DB_ALM. No es bloqueante: si TIA reporta errores parciales, marca `compile_ok=False` y guarda el mensaje, pero el flujo sigue hacia Tx B. (`areas/alimentacion/functions/function_proc_db_sincronizar.py:487`, `:515-561`; `core/infrastructure/tia/tia_cmd_compile.py:56-72`)
  3. **Tx B (comentarios)**: `execute_transactional_batch` con el `import_block` de `sincronizar/bloques/modified/`. (`areas/alimentacion/functions/function_proc_db_sincronizar.py:768-786`)
- **Qué queda confirmado si algo falla a mitad**: lo confirmado en una transacción anterior se queda confirmado. Si la Tx B falla, los N_MAX de la Tx A ya están aplicados y confirmados (son una transacción aparte), y el propio código lo dice en el log del post-preview: *"Post-sync preview fallo (commit ya aplicado)"*. (`areas/alimentacion/functions/function_proc_db_sincronizar.py:956-963`)
- El rollback del lote lo hace el handler: `end_transaction(rollback=True)`, y si el rollback también falla, el mensaje lo dice ("el proyecto puede haber quedado a medias"). (`core/infrastructure/tia/tia_cmd_batch.py:148-163`)
- La Tx B solo se lanza si se ha modificado algo (`param_modified or alm_modified`) y hay `plc_name`; si no hay cambios, no hay import. (`areas/alimentacion/functions/function_proc_db_sincronizar.py:735`)
- Las ops de N_MAX se calculan **antes** de abrir la Tx A, contra el XML que dejó el preview; si falta ese XML, el flujo aborta antes de tocar TIA. (`areas/alimentacion/functions/function_proc_db_sincronizar.py:383`, `:1067-1075`)

**e) SimaticSD.**
- La Tx B depende de SimaticSD de punta a punta: export de bloques en `export_format="SimaticSD"` (`.s7dcl` + `.s7res`), edición offline de los comentarios en esos archivos e import de esos mismos archivos. (`core/infrastructure/tia/tia_cmd_export.py:85-89`; `core/infrastructure/tia/tia_export_paths.py:21-22`)
- La Tx A (N_MAX) **no** depende de SimaticSD: es una tabla de tags en XML SimaticML y se cambia online con `update_user_constant_value`, que además relee el valor para confirmar que TIA lo aplicó. (`core/infrastructure/tia/tia_cmd_user_consts.py:99-146`; `core/infrastructure/tia/tia_cmd_export.py:8`)
- En V18: la exportación de bloques en SimaticSD no existe, así que en V18 no se puede ni exportar, ni editar, ni importar los DBs: el sync solo podría aplicar los N_MAX (Tx A) y se quedaría en el paso 3/4. Ese dato **no está en main**: viene de la rama de reescritura (`docs/INSTALAR.md:20`; `docs/PROBLEMAS.md:102-107`).

---

### function_proc_crear_generar_preview
`areas/alimentacion/functions/function_proc_crear_generar_preview.py`

**Que hace.** Monta en local el proceso nuevo a partir de una plantilla TIA y dice qué bloques se crearian al aplicarlo, con las colisiones y las dependencias. No toca TIA: solo trabaja sobre la plantilla copiada y la cache de bloques del PLC.

**Pasos, en orden.**
1. Leer manifiesto — lee el `manifest.json` de la plantilla TIA. (`areas/alimentacion/functions/function_proc_crear_generar_preview.py:311`)
2. Validar mínimos — comprueba que los N_MAX del operario cubren los de la plantilla. (`areas/alimentacion/functions/function_proc_crear_generar_preview.py:325`)
3. Copiar a vista previa — copia la plantilla al workdir de la vista previa. (`areas/alimentacion/functions/function_proc_crear_generar_preview.py:338`)
4. Construir diccionarios — parsea bloques y XMLs de la plantilla y arma los diccionarios base. (`areas/alimentacion/functions/function_proc_crear_generar_preview.py:350`)
5. Detectar colisiones — cruza los bloques nuevos contra los del PLC destino. (`areas/alimentacion/functions/function_proc_crear_generar_preview.py:362`)
6. Validar dependencias — comprueba que las dependencias declaradas existen en el PLC. (`areas/alimentacion/functions/function_proc_crear_generar_preview.py:371`)
7. Generar previstos — genera la lista de bloques que se crearian al aplicar. (`areas/alimentacion/functions/function_proc_crear_generar_preview.py:389`)
8. Componer respuesta — compone la respuesta final del preview. (`areas/alimentacion/functions/function_proc_crear_generar_preview.py:398`)

**a) Exporta.**
- **Este preview no exporta de TIA.** Toma la plantilla de disco (`plantillas_path` + `dir_plantilla_nombre`, de `config.json`) y los bloques del PLC de la **cache** (`plc_blocks_cache`), no de una exportación en vivo. (`areas/alimentacion/functions/function_proc_crear_generar_preview.py:232`, `:249`)
- Las carpetas del workdir son propias de este flujo, y **no** son las de `preview/` y `sincronizar/`:
  - `dir_plantilla` = `<plantillas_path>/<dir_plantilla_nombre>`: la plantilla original, de solo lectura.
  - `dir_plantilla_copia` = `.build_cache/alimentacion/ProcesoNuevo/Plantilla`: la copia de la plantilla.
  - `dir_nuevo` = `.build_cache/alimentacion/ProcesoNuevo/Nuevo`: el proceso nuevo generado. (`areas/alimentacion/functions/function_proc_crear_generar_preview.py:239-244`)
- En el workdir nuevo esto **no cabe** en `preview/` + `sincronizar/`: hacen falta dos carpetas sisters (`Plantilla/` y `Nuevo/`) con la plantilla entera y el proceso generado. Lo mas proximo al layout nuevo seria un contexto `proc_crear` con `preview/Plantilla/` y `preview/Nuevo/`.

**b) Modifica offline.**
- La copia de la plantilla se edita con los diccionarios: `proc_process_construir_diccionarios` recorre `dir_plantilla_copia/Bloques de programa` y arma el mapa de renombrado. (`areas/alimentacion/helpers/proc/proc_process_construir_diccionarios.py:79`, `:80`)
- El preview **no materializa** el proceso nuevo: solo dice que se crearia. La materializacion (`proc_process_aplicar_clonacion`) es del flujo de sincronizar. (`areas/alimentacion/helpers/proc/proc_process_aplicar_clonacion.py:115`)

**c) Importa.**
- No importa nada. El preview es de solo lectura sobre disco.

**d) Transacciones y compilaciones.**
- Ninguna: el preview no abre transacción ni compila. Todo es local (copytree + regex). (`areas/alimentacion/functions/function_proc_crear_generar_preview.py:120`)

**e) SimaticSD.**
- El preview **no depende de SimaticSD**: trabaja con los ficheros de la plantilla en disco (`.s7dcl`/`.s7res` ya exportados y guardados en la plantilla), no con una exportación en vivo.
- Sobre V18: **no está en main**. No hay ninguna detección de versión en este flujo.

### function_proc_crear_sincronizar
`areas/alimentacion/functions/function_proc_crear_sincronizar.py`

**Que hace.** Materializa el proceso nuevo a partir de la plantilla, lo importa en TIA (tags y bloques en una sola transaccion), compila el PLC y refresca la cache de bloques.

**Pasos, en orden.**
1. Leer manifiesto — lee el `manifest.json` de la plantilla TIA. (`areas/alimentacion/functions/function_proc_crear_sincronizar.py:382`)
2. Validar mínimos — comprueba que los N_MAX cubren los minimos de la plantilla. (`areas/alimentacion/functions/function_proc_crear_sincronizar.py:396`)
3. Copiar a vista previa — copia la plantilla al workdir de la vista previa. (`areas/alimentacion/functions/function_proc_crear_sincronizar.py:405`)
4. Construir diccionarios — parsea bloques y XMLs y arma los diccionarios base. (`areas/alimentacion/functions/function_proc_crear_sincronizar.py:417`)
5. Generar proceso nuevo — aplica las reglas y materializa los archivos del proceso nuevo. (`areas/alimentacion/functions/function_proc_crear_sincronizar.py:429`)
6. Escribir manifiesto modificado — escribe el `manifest.json` del proceso nuevo en `modified/`. (`areas/alimentacion/functions/function_proc_crear_sincronizar.py:441`)
7. Importar proceso — importa tags y bloques bajo una transaccion TIA unica. (`areas/alimentacion/functions/function_proc_crear_sincronizar.py:450`)
8. Compilar bloques — compila el PLC con los cambios del proceso nuevo. (`areas/alimentacion/functions/function_proc_crear_sincronizar.py:531`)
9. Refrescar BloqueCache — reescanea el PLC y repuebla el cache de bloques. (`areas/alimentacion/functions/function_proc_crear_sincronizar.py:549`)
10. Componer respuesta — compone el resultado final del apply. (`areas/alimentacion/functions/function_proc_crear_sincronizar.py:588`)

**a) Exporta.**
- **Tampoco exporta de TIA.** Toma la plantilla de disco y la cache de bloques del PLC. (`areas/alimentacion/functions/function_proc_crear_sincronizar.py:297-302`)
- Las carpetas son las mismas del preview: `Plantilla/` (la copia) y `Nuevo/` (el proceso generado), bajo `.build_cache/alimentacion/ProcesoNuevo/`. (`areas/alimentacion/functions/function_proc_crear_sincronizar.py:297-302`)

**b) Modifica offline.**
- `proc_process_aplicar_clonacion` borra `dir_nuevo/` si existe, hace `copytree` de la copia de la plantilla, renombra las rutas y reescribe los contenidos. (`areas/alimentacion/helpers/proc/proc_process_aplicar_clonacion.py:122`, `:123`, `:128`, `:134`, `:159`)
- La reescritura es por tipo de fichero: los `.s7dcl` se reescriben con el diccionario de bloques y los `.s7res` con `dicc_bloques` en `utf-8-sig`; el resto (binarios) se queda como venia de la copia. (`areas/alimentacion/helpers/proc/proc_process_aplicar_clonacion.py:165`, `:24`, `:30`)
- El `manifest.json` del proceso nuevo se escribe aparte, en el workdir `modified/`. (`areas/alimentacion/functions/function_proc_crear_sincronizar.py:441`, `:445`)

**c) Importa.**
- **Una sola transaccion** con tres ops, en este orden: (`areas/alimentacion/functions/function_proc_crear_sincronizar.py:477`, `:481`, `:486`, `:490`, `:494`)
  1. `import_plc_tags_xml` sobre `dir_nuevo/Variables PLC`.
  2. `_wait` de 2 s (sub-comando del handler, para que TIA consolide).
  3. `import_blocks_sd` sobre `dir_nuevo/Bloques de programa`.
- **En este flujo NUNCA se pasa `target_folder`**: los dos imports se invocan SIN el argumento, para que TIA haga match UPDATE por nombre conservando la ruta relativa. El propio codigo avisa de que `target_folder_path=""` (string vacio) NO es lo mismo que omitirlo. (`areas/alimentacion/functions/function_proc_crear_sincronizar.py:21`, `:27`, `:470`, `:471`)

**d) Transacciones y compilaciones.**
- Una unica transaccion TIA (la del paso 7) con las tres ops. `execute_transactional_batch` hace `start_transaction` → ops → `end_transaction(rollback=False)`, y si cualquier op falla hace `end_transaction(rollback=True)` y relanza, distinguiendo si fallo la operacion o el commit. (`core/infrastructure/tia/tia_cmd_batch.py:85`, `:140`, `:153`, `:168`)
- La compilacion (`compile_plc`, paso 8) va **fuera** de la transaccion: `compile_plc` esta en la lista de comandos prohibidos dentro de un lote transaccional. (`core/infrastructure/tia/tia_cmd_batch.py:49`; `areas/alimentacion/functions/function_proc_crear_sincronizar.py:535`)
- **Qué queda confirmado si algo falla a mitad**: al haber una sola transaccion, o se aplica todo el proceso (tags y bloques) o no se aplica nada. Si falla la transaccion, el rollback deshace el proceso entero. Si falla la compilacion, el proceso **ya esta confirmado** (la transaccion se cerro antes) y solo se pierde la certeza de que compile. Si falla el refresco de la cache (paso 9), el proceso sigue aplicado y solo el cache se queda viejo; el paso es tolerante a fallos. (`areas/alimentacion/functions/function_proc_crear_sincronizar.py:584`)
- El paso 9 (`Refrescar BloqueCache`) reescanea el PLC y repuebla la cache; si el scan no esta disponible, avisa y sigue. (`areas/alimentacion/functions/function_proc_crear_sincronizar.py:549`, `:584`)

**e) SimaticSD.**
- **Sí depende de SimaticSD**, en el paso 7: `import_blocks_sd` importa los `.s7dcl`/`.s7res` del proceso generado, que son ficheros en formato SimaticSD. (`areas/alimentacion/functions/function_proc_crear_sincronizar.py:490`)
- Los ficheros vienen de la **plantilla en disco**, no de una exportación en vivo: en este flujo no hay export de bloques.
- Sobre V18: **no está en main**. Sin la exportacion en SimaticSD no se podria ni regenerar la plantilla ni importar el proceso nuevo.

---

## Que cambia en la reescritura

Los ocho flujos de arriba son el comportamiento de `main`. En la reescritura cambia **donde** vive cada cosa, no que se hace:

| En `main` | En la reescritura |
|---|---|
| Cada area tiene sus FBs y su worker | El nucleo tiene `tia_ops` (operaciones puras) y `funciones/` (la orquestacion), con un FB por fichero |
| El resultado se publica en el AppCache | El resultado llega por el evento `job` del stream SSE |
| `execute_transactional_batch` envuelve las transacciones | `transaccion(job, ...)` de `zc_suite.nucleo.tia.transaccion`, una por operacion |
| `compile_blocks` fuera de toda transaccion | `tia_ops.compilar`, siempre fuera |
| Sin deteccion de version de TIA | `job.tia.version_tia`: en V18 los pasos de SimaticSD se saltan con un aviso |
| `target_folder=""` pasado al handler | El parametro **se omite**: nunca se pasa `""` a TIA |
| Los errores salen en un `window.alert` | Salen en la vista y en el faceplate |
| El export del editor va a `.build_cache/blocks_edit/preview/` | Va a `.build_cache/editor_bloques/preview/`, y se vacia al empezar |
| El workdir del area vive en `areas/.../helpers/*_workdir_layout.py` | El layout generico vive en `zc_suite/workdir.py`; el area declara sus subcarpetas de preview |

### Lo que el nucleo ya tiene

| Modulo | Que da |
|---|---|
| `tia_ops/exportar.py` | `exportar_bloques` (SimaticSD) y `exportar_tablas` (SimaticML) |
| `tia_ops/importar.py` | `importar_bloques` y `importar_tablas`, **sin** `target_folder_path` vacio |
| `tia_ops/constantes.py` | `leer_constantes`, `cambiar_valor`, `renombrar` (con la doble validacion) |
| `tia_ops/bloques.py` | `escanear_bloques`, `escanear_tipos_de_usuario`, `leer_bloques`, `cambiar_propiedad`, `aplicar_cambios` |
| `tia_ops/tablas.py` | `escanear_tablas_tags` |
| `tia_ops/compilar.py` | `compilar_plc` y `compilar_bloques` |
| `simatic/cabecera.py` | La cabecera del `.s7dcl` (titulo y comentario) y los MLC del `.s7res` |

### Lo que falta

- **El modificador de comentarios de arrays** (`commit_array_comments` de `main`): es lo que escribe los comentarios por instancia dentro del `.s7dcl`/`.s7res`. En `main` esta en `core/helpers/simatic_sd/`. Sin el, el paso 10 del sync de dispositivos y el paso 7 del de proc_db no se pueden hacer.
- **El modificador de constantes de usuario** (`PlcUserConstantModifier` de `main`, en `core/helpers/simatic_ml/`): adds, removes y cambios de comentario sobre el XML de una tabla de tags. Es el paso 7 del sync de dispositivos y el paso 7 del de entidades.
- **El paquete de Python del area** (`areas/alimentacion/`): con su `ID`, `NOMBRE`, `rutas`, `catalogo()` y `defaults()`, y la declaracion de las subcarpetas de preview de cada contexto.
- **Un contexto de workdir para crear procesos**: el flujo de `proc_crear` necesita dos carpetas sisters (`Plantilla/` con la copia de la plantilla y `Nuevo/` con el proceso generado) que no encajan en `preview/` + `sincronizar/`. Lo mas simple es un contexto `proc_crear` con `preview/Plantilla/` y `preview/Nuevo/`.

---

## Fallos de main que NO se portan

Son fallos reales de `main`. En la reescritura no se repiten, porque el trabajo
comprueba lo que hace.

### El resultado de la Tx C de dispositivos se descarta

En `main`, el paso 10 de `function_disp_sincronizar` envuelve el `import_block`
de los comentarios en un lote transaccional, pero **no mira el resultado**: el
`submit_and_wait` se descarta y el flujo sigue como si hubiera ido bien. Si el
import fallaba, el paso se marcaba como correcto. (`areas/alimentacion/functions/function_disp_sincronizar.py:921`, `:926`)

En la reescritura, **toda transaccion comprueba su resultado**: si el lote no
vuelve `ok`, el trabajo falla y se dice que transaccion se quedo a medias.

### La prevision post-sincronizacion de entidades lee mal el bloque

En `main`, el paso 11 de `function_entidades_sincronizar` exporta el `DB6_ENT`
con `keep_folder_structure=True` (el bloque queda en su subcarpeta de TIA), pero
despues lo lee **plano** con `SdPair(preview_bloques, ...)`: busca el fichero
en la raiz del preview, donde no esta. (`areas/alimentacion/functions/function_entidades_sincronizar.py:1201`)

En la reescritura, la prevision post-sincronizacion **reutiliza el flujo de
prevision** (la misma funcion, con el mismo codigo de lectura), en vez de
duplicarlo. Una sola ruta para leer un bloque: la que locate el fichero por
nombre.

---

## Cambios deliberados

Decisiones que se apartan de `main` a proposito. Cada una esta tomada porque
`main` fallo con la otra opcion, o porque la reescritura tiene una pieza que
`main` no tenia.

### a) proc_db exporta los DB con estructura

`main` exporta los DB de proc_db **planos** y replica la jerarquia de TIA a
mano: cada bloque va a `sincronizar/bloques/export/<subpath>/`, con `<subpath>`
calculado a mano. (`areas/alimentacion/functions/function_proc_db_sincronizar.py:1234-1241`)

En la reescritura, proc_db exporta los DB **con `mantener_estructura=True`**, como
dispositivos y entidades: es el camino validado. Los ficheros se localizan
**buscando por nombre** (`rglob`), no construyendo la ruta a mano.

### b) Ningun sincronizar depende de una prevision anterior

En `main`, el sync de proc_db lee el `.xml` de la tabla de tags que dejo el
preview anterior para calcular las ops de N_MAX, y aborta si no esta. El preview
tenia que haberse ejecutado antes, en el mismo momento. (`areas/alimentacion/functions/function_proc_db_sincronizar.py:410-416`)

En la reescritura, **cada sincronizar exporta lo que necesita**. No hay
dependencia del estado que dejo otra operacion: el preview y el sync son
independientes.

### c) Crear proceso: contexto de workdir `proc_crear`

Contexto de workdir `proc_crear`, con las carpetas `plantilla/` y `nuevo/`
**declaradas por el area**: el workdir del nucleo tiene que permitir que el area
declare carpetas propias de su contexto.

`nuevo/Variables PLC` y `nuevo/Bloques de programa` se importan **cada una
desde su raiz**, sin carpeta destino. (`areas/alimentacion/functions/function_proc_crear_sincronizar.py:477`, `:481`, `:490`, `:494`)

### d) Con varias transacciones, el resultado dice cual se confirmo

Cuando un trabajo tiene varias transacciones, el resultado **lista cada una con
su estado**: `confirmada`, `revertida` o `no ejecutada`. El faceplate y el
mensaje final lo dicen claro.

Es lo que hace falta con lo que se ha visto en `main`: si la Tx B falla, la Tx A
ya esta confirmada y el operario tiene que saberlo.

### e) En V18, cada flujo se para donde puede

| Flujo | En V18 |
|---|---|
| Dispositivos | Sin comentarios: el resto (N_MAX, renombres, altas y bajas de tags) funciona igual |
| Entidades | Sin comentarios: N_MAX y constantes funcionan igual |
| proc_db | Solo N_MAX. Ni export de bloques, ni edicion, ni import de comentarios |
| Crear proceso | **Bloqueado al validar**, antes de tocar nada, con un mensaje claro: importa SimaticSD |

El aviso va en la vista y en el faceplate. En ningun caso se falla con un
`NotSupportedException` a medias.

### f) De main se mantiene tal cual

- El **sleep de 2 s** despues de cambiar los N_MAX online, para que TIA
  consolide antes de reexportar. (`areas/alimentacion/functions/function_disp_sincronizar.py:548`)
- La **compilacion defensiva** del `DB6_ENT` justo despues de la Tx A: si
  falla, es solo un warning y el sync sigue. (`areas/alimentacion/functions/function_entidades_sincronizar.py:658`)
- Las **compilaciones van fuera de la transaccion** y **no bloquean**: avisan y
  el flujo sigue. (`core/infrastructure/tia/tia_cmd_batch.py:49`; `areas/alimentacion/functions/function_disp_sincronizar.py:689`)
- El **filtro que excluye la tabla de N_MAX** al copiar a `modified/`: si se
  copiara, la Tx B reimportaria los valores pre-commit y anularia los N_MAX ya
  aplicados online. (`areas/alimentacion/functions/function_disp_sincronizar.py:1374`)
- **No se guarda el proyecto**: los cambios quedan en la sesion de TIA y lo
  guarda el operario. (`areas/alimentacion/functions/function_entidades_sincronizar.py:21`, `:504`, `:627`)


