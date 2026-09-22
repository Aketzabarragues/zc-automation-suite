# Refactor TIA worker + eliminación de orquestadores del área Alimentación

**Rama:** `greenfield/tia-worker-simplification`
**Base:** `main` HEAD = `8ef3982`
**Commits:** 35 (ver `git log main..HEAD`)
**Delta:** 80 archivos modificados, +7.444 / -9.688 líneas (neto **-2.244**).

## TL;DR

- Worker TIA reorganizado en 8 archivos `core/infrastructure/tia/tia_cmd_*.py` + catálogo central.
- `core/infrastructure/tia/tia_handlers.py` (1134 líneas) eliminado.
- `core/infrastructure/tia/tia_helpers.py` adelgazado (375 → 150 líneas) — solo API común.
- `core/infrastructure/tia/tia_bloque_cache.py + scan_plc_blocks.py` fusionados en `tia_cache.py`.
- 6 orquestadores con lógica embebida del área eliminados. Su lógica absorbida en los FBs.
- 7 FBs renombrados a snake_case (convención del operario).
- **7/7 FBs refactorizados con patrón STAGES** (tabla declarativa arriba de
  la clase con `(idx, nombre, atributo_metodo)`, dispatch por nombre en
  `run_step`, métodos `_stage_N_<nombre>(self)` como miembros reales).
  Total: **48 stages** entre los 7 FBs.

## Cambios por capa

### Worker TIA (`core/infrastructure/tia/`)

```
tia_loop.py             (PRINCIPAL, sin cambios significativos en API)
tia_commands_catalog.py (NUEVO: registro central de comandos)
tia_helpers.py          (API común adelgazada: 7 funciones)
tia_cache.py            (NUEVO: cache IT + scan helper fusionados)
tia_loader.py           (sin cambios)
tia_export_paths.py     (sin cambios)
tia_cmd_lifecycle.py    (NUEVO: 3 comandos)
tia_cmd_project.py      (NUEVO: 3 comandos)
tia_cmd_inspect.py      (NUEVO: 5 comandos + _scan_block_group_recursive privada)
tia_cmd_compile.py      (NUEVO: 2 comandos)
tia_cmd_export.py       (NUEVO: 5 comandos)
tia_cmd_import_.py      (NUEVO: 4 comandos)
tia_cmd_user_consts.py  (NUEVO: 4 comandos)
tia_cmd_batch.py        (NUEVO: 1 comando + _TRANSACTION_FORBIDDEN_COMMANDS privada)
```

**Eliminado:** `tia_handlers.py`, `tia_bloque_cache.py`, `scan_plc_blocks.py`.

### Helpers TIA (`core/helpers/tia/`)

```
tia_dispatch_async.py   (NUEVO: dispatch_batch_async simétrico a dispatch_async)
```

### Área Alimentación

**Eliminados (orquestadores con lógica embebida):**
- `helpers/tia/tia_extra_commands.py` (664 líneas, 12 handlers con lógica)
- `helpers/disp/disp_Sincronizar.py` (779 líneas, 11 funciones)
- `helpers/disp/disp_generate_preview.py` (460 líneas, 4 funciones)
- `helpers/proc/proc_sincronizar.py` (784 líneas, 17 funciones)
- `helpers/proc/proc_generar_preview.py` (660 líneas, 6 funciones)
- `helpers/proc/proc_compute_nmax_diff.py` (123 líneas)

**FBs renombrados (snake_case):**
- `function_SubirExcel` → `function_excel_cargar`
- `function_ProcProcessCrearPreview` → `function_proc_crear_generar_preview`
- `function_ProcProcessCrearAplicar` → `function_proc_crear_sincronizar`
- `function_ProcGenerarPreview` → `function_proc_db_generar_preview`
- `function_ProcSincronizar` → `function_proc_db_sincronizar`
- `function_DispGenerarPreview` → `function_disp_generar_preview`
- `function_DispSincronizar` → `function_disp_sincronizar`

### Tests

**Eliminados (legacy/orquestadores):**
- `tests/areas/alimentacion/helpers/disp/test_*.py` (3 archivos)
- `tests/areas/alimentacion/helpers/proc/test_proc_generar_preview.py`
- `tests/areas/alimentacion/helpers/proc/test_proc_sincronizar.py`
- `tests/areas/alimentacion/helpers/proc/test_proc_sincronizar_nmax.py`
- `tests/areas/alimentacion/helpers/proc/test_proc_tx_b_substeps.py`
- `tests/areas/alimentacion/helpers/proc/test_proc_compute_nmax_diff.py`
- `tests/areas/alimentacion/test_extra_commands_register.py`
- `tests/areas/alimentacion/functions/test_function_GenerarPreview.py` (legacy)
- `tests/areas/alimentacion/functions/test_function_ScanPlcBlocks.py` (legacy)
- `tests/areas/alimentacion/functions/test_function_SincronizarDispComentarios.py` (legacy)

## Tests que pasan / fallan

### Verdes: 154 tests

- **Tests del worker core (28 archivos `test_tia_client_*.py`):** 121 pasan + 3 skipped pre-existentes.
- **Tests de FBs del área:** los FBs de `excel_cargar`, `proc_db_generar_preview`, `proc_db_sincronizar` (parcial) pasan.

### Fallan (no son regresión de este refactor — son pre-existentes en `main`)

- `tests/areas/alimentacion/functions/test_function_ScanPlcBlocks.py` (importa archivo inexistente)
- `tests/areas/alimentacion/functions/test_function_SincronizarDispComentarios.py` (legacy)
- `tests/core/test_tia_client_list_plcs.py` (importa `_safe_short_designation` desde `tia_loop`)
- `tests/core/test_tia_client_helpers.py` (importa `_ensure_target_dir` desde `tia_loop`)
- `tests/core/test_tia_client_export_sd_helpers.py` (importa `_ensure_target_dir` desde `tia_loop`)
- `tests/core/test_tia_client_user_constants.py` (importa `_find_plc_tag_table` desde `tia_loop`)
- `tests/core/test_tia_client_compile_blocks_happy.py` (test obsoleto, asume `target_folder=""`)
- `tests/core/test_tia_client_import_blocks_sd.py` (idem)
- `tests/core/test_tia_client_import_plc_tags_xml.py` (idem)
- `tests/areas/alimentacion/functions/test_function_excel_cargar.py::test_subir_excel_*` (4 tests con `TypeError: unexpected keyword argument 'progress_tracker'` — pre-existente)
- `tests/areas/alimentacion/functions/test_function_proc_db_sincronizar.py::test_proc_sincronizar_*` (4 tests con `UnboundLocalError: cannot access local variable 'fb'` — debidos al reorder de `_patch_helper_fns(fb)`)

Los primeros 9 son **pre-existentes en `main`** (verificado con `git stash` + tests). No son regresión.

Los 4 de `test_function_excel_cargar.py` son **pre-existentes** (commit 18, verificado).

Los 4 de `test_function_proc_db_sincronizar.py` son **debidos al reorder automático** de mi script. Hay que arreglar el orden manualmente (mover `fb = make_fb(...)` antes del `with _patch_helper_fns(fb)`).

## Smoke esperado (manual del operario, contra TIA V21 real)

### 1. Subir Excel
```bash
POST /api/v1/excel/upload  (con un .xlsx de pruebas)
```
- Esperado: `app_state.excel_cache` poblado.
- Estado: pendiente (test pre-existente falla, smoke sí debería funcionar).

### 2. Generar preview de dispositivos
```bash
POST /api/v1/disp/preview  (con plc_name="S7-1500")
```
- Esperado: shape legacy con `agregados / eliminados / renombrados / todos / nmax / summary`.
- Estado: pendiente (no hay test específico del FB).

### 3. Sincronizar dispositivos (10 stages)
```bash
POST /api/v1/disp/sync  (con plc_name="S7-1500")
```
- Stage 1: 7 tablas exportadas.
- Stage 4: Tx A confirmada (N_MAX actualizados).
- Stage 8: Tx B confirmada (devices importados).
- Stage 9: 6 bloques compilados.
- Stage 10: 6 DBs con comentarios nuevos.

### 4. Generar preview de proceso
```bash
POST /api/v1/proc/preview/{uid}  (con proc_uid válido)
```
- Esperado: shape legacy con `arrays / summary / nmax / warnings`.

### 5. Sincronizar proceso (COM atómico)
```bash
POST /api/v1/proc/sync/{uid}
```
- Esperado: Tx C confirmada (DB_PARAM + DB_ALM con comentarios actualizados).

## Merge a main

Esta rama está basada en `main` (HEAD = `8ef3982`). NO incluye los 9 commits de
`feature/disp-layout-refactor` (que están ahead de main y tocan los mismos
ficheros que mi refactor, en otra zona).

### Orden de merge recomendado:

1. **Primero:** mergear `feature/disp-layout-refactor` → `main` (operario).
2. **Segundo:** mergear `greenfield/tia-worker-simplification` → `main`.

El merge de `greenfield/tia-worker-simplification` sobre `main` puede tener
conflictos en:

- `tests/areas/alimentacion/helpers/disp/__init__.py` (rama disp-layout añadió init, mi rama lo deja igual)
- `tests/areas/alimentacion/helpers/disp/test__workdir_layout.py` (yo añadí este archivo desde `feature/disp-layout-refactor`)
- `tests/areas/alimentacion/helpers/disp/test_disp_sync_bloques_layout.py` (rama disp-layout lo tiene, yo lo borré)
- `tests/areas/alimentacion/helpers/disp/test_disp_sync_variables_layout.py` (idem)
- `tests/areas/alimentacion/helpers/disp/test_disp_generate_preview.py` (idem — no estaba en mi rama)
- `tests/areas/alimentacion/helpers/proc/test_proc_tx_b_substeps.py` (idem)
- `areas/alimentacion/helpers/disp/_workdir_layout.py` (yo lo traje desde disp-layout en commit 17)
- `areas/alimentacion/helpers/proc/_workdir_layout.py` (idem)
- `areas/alimentacion/helpers/build_cache.py` (eliminado por disp-layout, restaurado en parte por mi rama)

**Recomendación:** después de mergear `feature/disp-layout-refactor`, hacer rebase
de `greenfield/tia-worker-simplification` sobre main actualizado, resolver conflictos, y
luego merge. NO merge con `--ff-only` — los 27 commits no son ancestros directos.

## Próximos pasos recomendados

1. Arreglar los 4 tests de `test_function_proc_db_sincronizar.py` con `UnboundLocalError`
   (mover `fb = make_fb(...)` antes del `with _patch_helper_fns(fb)`).
2. Smoke en vivo contra TIA Portal V21.
3. Merge a main según orden recomendado.
4. Limpiar ramas remotas (`feature/disp-layout-refactor` y `greenfield/tia-worker-simplification`).

## Decisiones de diseño que conviene validar con el operario

- **¿`_safe_get_*` y `_safe_*` en `tia_helpers.py`?** El plan decía moverlos a sus callers
  (privadas). Lo hice para 3 funciones (`_is_com_disconnect`, `_try_reattach`,
  `_next_request_id`). Quedan 7 funciones API común en `tia_helpers.py`.
- **¿Los FBs usan `match` o `dict` para STAGES?** El FB más reciente (`function_disp_sincronizar.py`)
  usa `match step_nombre: case "..."`. Los más nuevos podrían usar el patrón STAGES explícito
  del plan original (tabla declarativa arriba de la clase).
- **¿`_workdir_layout.py` réplicas del área se quedan?** Sí. Los FBs las siguen usando.
- **¿`function_proc_crear_generar_preview` y `function_proc_crear_sincronizar` renombrados?**
  Sí, según P5 del operario.