# Guía para integrar un nuevo dispositivo en el área de alimentación

> Checklist operacional para añadir un nuevo tipo de dispositivo
> (motor, válvula, sensor, ...) al área de alimentación. Aplica al
> patrón actual y a futuras áreas que sigan el mismo data-driven.
>
> El sistema es 100% data-driven sobre `ConfigManager.list_hw_types_active()`
> y `list_nmax_active()`. Los FB de preview/sync iteran estas listas y
> no requieren cambios. Lo único que hay que tocar es la capa de
> configuración, los DTOs, los parsers del Excel, el catalog data-driven
> y los tests. La SPA lo recoge solo vía `GET /api/v1/catalog`.

## Referencia canónica: m_sina (motor sinamics)

Antes de empezar, lee estos 6 archivos en este orden. Son el ejemplo
completo de un dispositivo activado de la forma que describe esta guía.

1. Commit: `7230d14 feat(alimentacion): añadir dispositivo m_sina (motor sinamics)`.
2. `config/config.json` — el bloque `Dispositivos` y `n_max_catalog`.
3. `areas/alimentacion/data/data_dispositivos.py` — la dataclass `DispMSINA`.
4. `areas/alimentacion/helpers/excel/excel_parser_disp_m_sina.py` — parser.
5. `areas/alimentacion/helpers/excel/excel_loader.py` — integración 7º parser.
6. `areas/alimentacion/data/data_disp_catalog.py` — entry en `_CANONICAL_TO_CLASS`.

Replica su estructura. Cubre los gotchas conocidos al final.

## Convenciones

- **hw_type**: identificador corto en minúsculas con `_` como separador
  (`ed`, `ea`, `m_vf`, `m_sina`). Se usa como key en `state.dispositivos`.
- **canonical**: nombre de la clase Python sin guión bajo (`DispED`,
  `DispM_VF`, `DispM_SINA`). Lo deriva `ConfigManager._canonical_default()`
  con la regla `"Disp" + mayúsculas de cada parte`.
- **DB / tag_table**: convención `DB<num>_<HW>` / `2000_Disp_<HW>`.
  El número se reserva en el PLC; consulta con el operario si tienes duda.
- **Hoja Excel**: `DISP_<HW>` (uppercase) y `Tabla_Disp_<HW>`. Lo deriva
  `ConfigManager.get_excel_target_for()` automáticamente si no hay override.
- **cfg\_\***: campos `str` con SCL de configuración. La SPA los filtra
  en `model_columns` (ver `get_columns_for` en `data_disp_catalog.py`).
  No los expongas al operario en columnas de tabla.

## Pre-requisitos

Antes de empezar necesitas tener claro:

1. **El nombre del hw_type** (ej. `m_sina`) y su **canonical** derivado
   (`DispM_SINA`).
2. **El DB y tag_table del PLC** para este dispositivo (consultar con el
   operario si el PLC ya tiene el array).
3. **El N_MAX canónico** (`N_MAX_DISP_<HW>`) y su `excel_named_range`
   corporativo (`Num_Disp_<HW>`).
4. **Las columnas del Excel** que el operario quiere en este dispositivo
   (cabeceras exactas, una por columna).
5. **Qué campos son required** vs defaults razonables (`str=""`, `int=0`,
   `float=0.0`).

## 9 pasos por integración

### 1. `config/config.json`

Mueve la entry de `pending_dispositivos` → `Dispositivos` y de
`pending_nmax` → `n_max_catalog`.

```json
"Dispositivos": {
  "ed": { ... },
  "...": { ... },
  "<hw_type>": {
    "db_name":         "DB<num>_<HW>",
    "db_array_name":   "<HW>",
    "tag_table":       "2000_Disp_<HW>",
    "config_table":    "000_Config_Dispositivos"
  }
}

"n_max_catalog": [
  ...,
  {
    "name":              "N_MAX_DISP_<HW>",
    "excel_named_range": "Num_Disp_<HW>",
    "hw_type":           "<hw_type>",
    "plc_tag_table":     "2000_Disp_<HW>",
    "comment":           "Numero max. <descripcion humana>"
  }
]
```

Borra el hw_type de `pending_dispositivos` y el N_MAX de `pending_nmax`.
Actualiza el `_todo_legacy_types` del header del JSON para reflejar
que este tipo ya no está pendiente.

### 2. Defaults defensivos

`areas/alimentacion/helpers/config/config_defaults.py::install`:

- Añade `N_MAX_DISP_<HW>` a `_DEFAULT_NMAX_CATALOG` (entrada fallback
  para setups sin `n_max_catalog` en el JSON).

`areas/alimentacion/helpers/excel/excel_parser_disp_dimensiones.py`:

- Añade `"<hw_type>": "N_MAX_DISP_<HW>"` al `_FALLBACK_HW_TO_CANONICAL`.
- Actualiza el docstring que menciona el conteo de hw_types fallback.

### 3. Dataclass `DispXxx`

`areas/alimentacion/data/data_dispositivos.py`:

Crea una dataclass nueva con `@dataclass(frozen=True)`. Decide
previamente si debe heredar de otra o ser independiente:

- **Hereda de `DispM`** si comparte la mayoría de los campos digitales
  (S/RM/RT) y solo añade específicos (caso típico: `DispM_VF` añade
  SA.Byte + cfg_byteanalogica).
- **Independiente** si el dispositivo es conceptualmente distinto
  (caso típico: `DispMSINA` no tiene activación digital ni confirmación
  de marcha, solo RT + parámetros analógicos).

Reglas:
- Los 5 campos del `Protocol Dispositivo` van primero (positional):
  `numero, plc_tag, plc_comentario, descripcion, uid`.
- Defaults: `str=""`, `int=0`, `float=0.0`.
- Añade la clase a `__all__`.

### 4. Parser `excel_parser_disp_<hw>.py`

Copia `excel_parser_disp_m_vf.py` (o el más parecido) como base y edita:

- Renombra la clase a `<Disp><Hw>Parser`.
- Cambia `SHEET = "DISP_<HW>"` y `TABLE = "Tabla_Disp_<HW>"`.
- En `__init__`, el override via `config_manager.get_excel_target_for("<hw_type>")`
  funciona idéntico — solo cambia el argumento.
- En `extraer`, instancia la dataclass del paso 3 con todos los campos
  del Excel. Usa `_safe_str`, `_safe_int`, `_safe_float` (este último
  para columnas numéricas no enteras).
- Si un Excel del operario puede tener coma decimal (`"1,5"`), `_safe_float`
  ya lo soporta.

### 5. Integrar el parser en el loader

`areas/alimentacion/helpers/excel/excel_loader.py`:

- Importa la nueva clase del parser.
- En `__init__`: instancia `self._disp_<hw> = <Disp><Hw>Parser(config_manager=config_manager)`.
- En `load`: `disp_<hw> = self._disp_<hw>.extraer(wb)`.
- En el dict `dispositivos_dict`: añade `"<hw_type>": tuple(disp_<hw>),`.
- Actualiza los docstrings que dicen "6 disp" → "7 disp" (o el conteo nuevo).

### 6. Catalog data-driven

`areas/alimentacion/data/data_disp_catalog.py`:

- Importa la nueva dataclass del paso 3.
- En `_CANONICAL_TO_CLASS`: añade `"Disp<HW>": Disp<HW>,`.
- En `COLUMN_LABELS`: añade entradas para cualquier columna nueva que
  no exista (ej. `vel_min: "Vel.Min"`, `vel_max: "Vel.Max"`). Las
  columnas que ya tienen label (uid, plc_tag, etc.) no necesitan tocarse.
- Actualiza el docstring del módulo si menciona el conteo de tipos.

A partir de aquí, `GET /api/v1/catalog` ya devuelve:

- `device_tabs`: incluye el nuevo tab con su `hw_type`, `canonical`, `label`.
- `nmax`: incluye el nuevo N_MAX con su label derivado.
- `model_columns["Disp<HW>"]`: lista de campos (los `cfg_*` filtrados).
- `col_labels`: incluye los labels nuevos.

### 7. Tests

Hay 5 archivos a tocar + 1 nuevo. Sigue el patrón de `m_sina` (commit
`7230d14`) como referencia.

**a) `tests/areas/alimentacion/data/test_data_dispositivos.py`:**

- Importa la nueva dataclass.
- Añade 3–5 tests: construcción básica, isinstance, frozen, defaults,
  y (si aplica) "no tiene campos digitales" u otro invariante del tipo.
- Actualiza los tests `test_disp_defaults_*` para incluir el nuevo tipo.

**b) `tests/areas/alimentacion/helpers/excel/test_disp_<hw>_parser.py`** (nuevo):

Réplica de `test_disp_m_vf_parser.py`:

- `test_extrae_disp_<hw>_basico`: 1 fila con campos específicos populados.
- `test_hoja_inexistente_devuelve_lista_vacia`.
- `test_tabla_inexistente_devuelve_lista_vacia`.
- `test_fila_sin_uid_se_descarta`.
- `test_defaults_when_only_uid_and_numero`: defaults tolerantes.
- Opcional: `test_parser_respeta_config_manager_override` si el
  dispositivo tiene sheet/table no estándar.

**c) `tests/_disp_parser_test_helpers.py`:**

- Añade `"<HW>": [...]` a `_FULL_DISP_HEADERS` con las cabeceras del
  Excel del operario en orden.
- Añade defaults específicos en `build_full_row` (campos float, etc.).

**d) `tests/areas/alimentacion/helpers/excel/test_excel_loader.py`:**

- En `_build_full_xlsx`: añade 1 tabla `DISP_<HW>` con 1 fila + 1
  defined name `N_MAX_DISP_<HW>`.
- En `test_load_basico`: assert `len(cache.dispositivos["<hw_type>"]) == 1`
  y `cache.n_max.extras["N_MAX_DISP_<HW>"] == N`.

**e) `tests/areas/alimentacion/helpers/excel/test_excel_cache_manager.py`:**

- En `_make_cache`: añade `"<hw_type>": ()` al dict.

**f) `tests/areas/alimentacion/helpers/excel/test_dimensiones_parser.py`:**

- Si tenías un test que asumía que el hw_type se descartaba (estaba en
  `pending_*`), inviértelo: ahora SÍ entra. Renómbralo a
  `test_<algo>_tipo_pendiente_se_descarta` y usa otro tipo pendiente real
  (ej. `Num_Disp_AGRUP`).

### 8. Docstrings cosméticos

Hay docstrings en el código que dicen "6 disp / 6 hw / 6 DBs" o números
hardcoded. Actualízalos a:

- El conteo correcto (ej. "7 disp"), **o**
- "los del área" / "data-driven vía config.json" (preferible si no quieres
  volver a actualizar).

Sitios habituales a revisar:

- `areas/alimentacion/data/data_disp_slot_map.py` — "los N tipos de dispositivos".
- `areas/alimentacion/data/data_dimensiones.py` — "los N principales + cualquier extra".
- `areas/alimentacion/data/data_proc_slot_map.py` — "los N DBs de dispositivos".
- `areas/alimentacion/helpers/layout/build_cache.py` — "los N DBs de dispositivos".
- `areas/alimentacion/functions/function_disp_sincronizar.py::stage_10` — "los N DBs de disp".
- `areas/alimentacion/helpers/excel/excel_upload.py` — "los N mini parsers".
- `areas/alimentacion/helpers/excel/excel_loader.py` — docstrings + comentarios.
- `core/infrastructure/config/config_manager.py` — algunos docstrings.
- `core/runtime/app_state.py` — set_devices docstring.
- `config/config.json` — `_comment_folders` (suele decir "las N tablas").
- `tests/_disp_parser_test_helpers.py` — docstring del módulo.

### 9. Smoke en vivo + commit

Antes de commitear:

1. **Tests**: `python -m pytest tests/areas/alimentacion/ -v` → verde.
2. **Backend smoke**: arranca Flask test client y verifica
   `/api/v1/catalog` (ver el smoke del commit `7230d14` para patrón).
   Comprueba que:
   - `device_tabs` tiene el nuevo entry.
   - `nmax` tiene el nuevo entry.
   - `model_columns["Disp<HW>"]` tiene las columnas esperadas.
   - `ConfigManager.list_hw_types_active()` y `list_nmax_active()` lo incluyen.
3. **Commit**: un commit atómico con mensaje
   `feat(alimentacion): añadir dispositivo <hw_type> (<descripcion>)`.
   Lista en el body qué cambia (config, DTO, parser, catalog, tests).

El smoke visual con `?demo=1` + PLC real lo hace el operario en su
entorno, fuera de esta guía.

## Lista de verificación final

Marca cada item cuando lo completes:

- [ ] Pre-requisitos recopilados (hw_type, DB, N_MAX, columnas Excel).
- [ ] `config/config.json` actualizado (Dispositivos + n_max_catalog).
- [ ] Defaults defensivos actualizados (config_defaults + dimensiones parser).
- [ ] Dataclass creada (con __all__ actualizado).
- [ ] Parser creado y exporta `__all__`.
- [ ] Parser integrado en `excel_loader.py`.
- [ ] Catalog actualizado (_CANONICAL_TO_CLASS + COLUMN_LABELS).
- [ ] Tests del dataclass añadidos.
- [ ] Test del parser nuevo creado.
- [ ] `_disp_parser_test_helpers.py` actualizado.
- [ ] `_build_full_xlsx` y `_make_cache` actualizados.
- [ ] `test_dimensiones_parser.py` actualizado si era necesario.
- [ ] Docstrings cosméticos revisados.
- [ ] `pytest -v` verde.
- [ ] Smoke backend verificado (catalog + ConfigManager).
- [ ] Commit creado.

## Gotchas (lecciones aprendidas)

**1. Herencia vs independencia en dataclasses.**
`DispM_VF` hereda de `DispM` (comparten S/RM/RT, solo añade SA.Byte +
cfg_byteanalogica). `DispMSINA` es independiente porque no comparte
activación digital. Decide por concepto, no por DRY: si comparten
campos pero conceptualmente son distintos, mejor clase nueva (como
`DispEA`/`DispSA` que tampoco heredan pese a ser casi idénticos).

**2. El campo `cfg_*` filtra la SPA.**
La SPA muestra solo columnas que NO empiezan por `cfg_` (ver
`get_columns_for` en `data_disp_catalog.py`). Esto es por diseño:
los `cfg_*` son SCL de configuración del PLC, no datos del dispositivo
que el operario quiera ver en una tabla.

**3. Tests legacy que asumían "pendiente".**
Cuando un dispositivo estaba en `pending_*`, había tests que
aseveraban "se descarta". Al activarlo, esos tests fallan. Hay que
**invertir la aserción** (ahora SÍ entra) y mover el caso "se descarta"
a otro tipo que siga pendiente realmente.

**4. `m_sina` hereda la convención canonical del config_manager.**
`_canonical_default("m_sina")` ya devolvía `"DispM_SINA"` antes del
commit `7230d14`. El sistema estaba diseñado para que esto funcionara
sin tocar el config_manager. Si añades un hw_type con una forma
exótica, verifica primero que `_canonical_default` produce el canonical
que esperas.

**5. El backend ya era data-driven, pero los tests no.**
Antes del commit `7230d14`, los tests del cache manager y del loader
tenían listas hardcoded de 6 hw_types (literalmente `"ed", "ea", "sa",
"v", "m", "m_vf"`). Hay que actualizarlos para incluir el nuevo. Lo
mismo aplica al `_build_full_xlsx` del test del loader.

**6. SPA y FB no se tocan.**
La SPA renderiza tabs/nmax/columnas/labels desde `/api/v1/catalog`. Si
los datos están bien en el backend, aparecen solos. Los FBs de preview
y sync iteran `list_hw_types_active()` y `list_nmax_active()`. Si el
dispositivo está en el config, lo recogen automáticamente. **Cero
código que tocar en la SPA o en los FB** para añadir un dispositivo
nuevo.
