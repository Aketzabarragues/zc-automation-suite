# Anadir un tipo de dispositivo

Un dispositivo es un tipo de equipo (una entrada digital, una valvula, un
motor) con su DB en el PLC, su tabla de tags y sus columnas en el Excel
maestro. Anadir uno no obliga a tocar la SPA: el catalogo es data-driven.

La clave de la entrada es el **unico identificador** del tipo: no hay un
segundo nombre para el mismo tipo.

## 1. Configuracion

Anade la entrada en `config.json`, dentro de `areas.<area>.dispositivos`:

```json
"dispositivos": {
  "mi_tipo": {
    "etiqueta": "MI",
    "db": "DB2050_MI",
    "array": "MI",
    "tabla_tags": "2000_Disp_MI",
    "excel": {
      "hoja": "DISP_MI",
      "tabla": "Tabla_Disp_MI"
    },
    "nmax": {
      "constante": "N_MAX_DISP_MI",
      "columna_excel": "N_Max_MI",
      "comentario": "Numero max. de mi tipo"
    },
    "columnas": ["plc_name", "numero", "tag", "descripcion"]
  }
}
```

- `etiqueta`: lo que se ensena en la pestana del tipo.
- `db`: nombre del DB en TIA.
- `array`: nombre del array dentro del DB.
- `tabla_tags`: tabla de tags donde viven las entradas del tipo.
- `excel`: la hoja y la tabla nombrada del Excel maestro donde vive el tipo.
- `nmax`: la constante de usuario en TIA, la columna del Excel que la alimenta
  y el comentario que lleva.
- `columnas`: las columnas que ve el operario, en orden.

El formato entero esta en [CONFIG.md](CONFIG.md).

## 2. Columnas del Excel

Anade la definicion de columnas en `areas/<area>/excel/tablas.py`. El lector
generico recorre la tabla del Excel y proyecta las columnas declaradas. La
hoja y la tabla **no** se ponen aqui: las dice el config.

Si la tabla no encaja en el modelo generico (estructura irregular, celdas
combinadas, varias tablas en una hoja), su parser va a
`areas/<area>/excel/especiales.py`.

## 3. Titulos de las columnas

Los titulos de las columnas de los dispositivos van en
`areas.<area>.etiquetas_dispositivos`: `{campo: titulo}`. Donde no haya
titulo, se ensena el nombre del campo tal cual.

Las etiquetas van **por seccion**: las de los dispositivos no se pisan con las
del software ni con las de las entidades.

## 4. Comprobacion

```bash
python -m pytest tests/areas/ -q
```

Si el config no cumple el formato, la app lo dice al arrancar (log + banner)
con la clave que falta. Y en vivo: abrir el area, comprobar que la tabla
aparece con el numero de filas esperado y que el preview no propone cambios
inventados.
