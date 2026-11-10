# Anadir un tipo de dispositivo

Un dispositivo es un tipo de equipo (una entrada digital, una valvula, un
motor) con su DB en el PLC, su tabla de tags y sus columnas en el Excel
maestro. Anadir uno no obliga a tocar la SPA: el catalogo es data-driven.

## 1. Configuracion

Anade la entrada en `config.json`, dentro de `areas.<area>.Dispositivos`:

```json
"Dispositivos": {
  "mi_tipo": {
    "db_name": "DB2050_MI",
    "db_array_name": "MI",
    "tag_table": "2000_Disp_MI",
    "config_table": "0_Config_Dispositivos",
    "excel_target": {
      "sheet": "DISP_MI",
      "table": "Tabla_Disp_MI",
      "canonical": "DispMI"
    }
  }
}
```

- `db_name`: nombre del DB en TIA.
- `db_array_name`: nombre del array dentro del DB.
- `tag_table`: tabla de tags donde viven las entradas del tipo.
- `config_table`: tabla de configuracion global.
- `excel_target`: solo si el tipo tiene su propia tabla en el Excel. Dice que
  hoja y que tabla leer, y que clave canonica usa.

## 2. N_MAX

Si el tipo tiene contador propio, anade su entrada a
`areas.<area>.n_max_catalog`:

```json
{
  "name": "N_MAX_DISP_MI",
  "hw_type": "mi",
  "plc_tag_table": "2000_Disp_MI",
  "comment": "Numero max. de mi tipo",
  "excel_column": "N_Max_MI"
}
```

`hw_type` es la clave que enlaza el catalogo de N_MAX con el tipo de
dispositivo. Sin entrada en `n_max_catalog`, el tipo no aparece en el
preview de N_MAX.

## 3. Columnas del Excel

Anade la definicion de columnas en `areas/<area>/excel/tablas.py`. El lector
generico recorre la tabla del Excel y proyecta las columnas declaradas.

Si la tabla no encaja en el modelo generico (estructura irregular, celdas
combinadas, varias tablas en una hoja), su parser va a
`areas/<area>/excel/especiales.py`.

## 4. Dataclass del catalogo

Si el tipo necesita un DTO propio (no solo columnas), anade su dataclass en
`areas/<area>/datos/`.

## 5. Columnas visibles

El orden y el subconjunto de columnas que ve el operario se controla por
`canonical` (por ejemplo `DispMI`) en `areas.<area>.disp_catalog.display_order`
de `config.json`. El override es total: si el canonical no esta, se muestran
todos los campos del DTO.

## 6. Comprobacion

```bash
python -m pytest tests/areas/ -q
```

Y en vivo: abrir el area, comprobar que la tabla aparece con el numero de
filas esperado y que el preview no propone cambios inventados.
