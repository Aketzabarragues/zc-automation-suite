# El config.json

Donde vive el `config.json`, como se llama y que formato tiene cada seccion.

## Donde vive

| Entorno | Ruta |
|---|---|
| Empaquetado | `<carpeta del .exe>/config/config.json` |
| Desarrollo | `<repo>/config/config.json` |

La primera vez que se arranca el `.exe`, la plantilla del paquete se copia ahi.
A partir de ese momento **manda siempre el del operario**: la app nunca lo
sustituye ni lo pisa, ni siquiera cuando no vale.

La variable de entorno `ZC_CONFIG_DIR` fuerza otra carpeta.

## Cuando el config no vale

Si el `config.json` no cumple el formato, la app **arranca igual** y lo dice:

- El log escribe el motivo como error.
- La SPA enseña un banner rojo con el motivo.
- El area que no vale se queda sin catalogo: sus vistas salen vacias.

Un config sin la seccion `areas`, o sin la seccion de un area registrada, es de
otra version de la app: tambien es incompatible.

El formato esta validado por el modelo de cada area
(`backend/zc_suite/areas/<id>/config.py`). El nucleo no sabe que es valido en el
config de un area: se lo pregunta al area y enseña lo que contesta.

## El formato

La raiz solo tiene `areas`. Cada area tiene su seccion, con su propio formato.

### areas.alimentacion

```json
{
  "areas": {
    "alimentacion": {
      "carpetas_tia": { "...": "..." },
      "tabla_nmax": "0_Config_Dispositivos",
      "plantillas_procesos": "plantillas",
      "dispositivos": { "ed": { "...": "..." } },
      "etiquetas_dispositivos": { "numero": "Numero" },
      "entidades": { "...": "..." },
      "procesos": { "...": "..." }
    }
  }
}
```

#### carpetas_tia

Las carpetas del proyecto de TIA, donde viven los bloques y las tablas.

| Clave | Que es |
|---|---|
| `dispositivos` | la carpeta de las tablas de tags de los dispositivos |
| `sistema` | la carpeta de las tablas de sistema (los N_MAX) |
| `entidades` | la carpeta de las tablas de tags de las entidades |
| `procesos` | la carpeta de los bloques de los procesos |

#### tabla_nmax

La tabla de TIA donde viven las constantes de los N_MAX de los dispositivos
(`0_Config_Dispositivos`).

#### plantillas_procesos

La carpeta con las plantillas TIA para generar procesos. Es **relativa** a la
carpeta de datos de la app (la del `.exe`), no una ruta absoluta: asi el
config es portable entre maquinas. Por defecto, `plantillas`.

#### dispositivos

Un tipo de dispositivo por clave. **La clave es su unico identificador**: no
hay un segundo nombre para el mismo tipo. El orden de las claves es el orden de
las pestanas.

```json
"ed": {
  "etiqueta": "ED",
  "db": "DB2000_ED",
  "array": "ED",
  "tabla_tags": "2000_Disp_ED",
  "excel": { "hoja": "DISP_ED", "tabla": "Tabla_Disp_ED" },
  "nmax": {
    "constante": "N_MAX_DISP_ED",
    "columna_excel": "N_Max_ED",
    "comentario": "Numero max. entrada digital"
  },
  "columnas": ["plc_name", "numero", "tag", "..."]
}
```

| Clave | Que es |
|---|---|
| `etiqueta` | lo que se ensena en la pestaña del tipo |
| `db` | el DB del tipo en TIA |
| `array` | el nombre del array dentro del DB |
| `tabla_tags` | la tabla de tags del tipo en TIA |
| `excel.hoja` | la hoja del Excel maestro donde vive el tipo |
| `excel.tabla` | la tabla nombrada dentro de esa hoja |
| `nmax.constante` | el nombre de la constante de usuario en TIA |
| `nmax.columna_excel` | la columna del Excel que la alimenta |
| `nmax.comentario` | el comentario que lleva la constante en TIA |
| `columnas` | las columnas que se ven, en orden |

Un tipo al que le falte `db`, `tabla_tags`, `excel` o `nmax` no vale: el error
dice que clave falta y donde.

#### etiquetas_dispositivos

Los titulos de las columnas de los dispositivos (`{campo: titulo}`). Donde no
haya titulo, se ensena el nombre del campo tal cual.

#### entidades

Las entidades: su DB, su array, su tabla de tags, la tabla donde vive su N_MAX,
sus columnas y sus titulos.

```json
"entidades": {
  "db": "DB6_ENT",
  "array": "ENT",
  "tabla_tags": "6_Entidades",
  "tabla_config": "0_Config_Generales",
  "nmax": {
    "constante": "N_MAX_ENTIDAD",
    "columna_excel": "N_Max_ENT",
    "comentario": "Numero max. entidades (dimension del array ENT de DB6_ENT)"
  },
  "columnas": ["plc_name", "numero", "..."],
  "etiquetas": { "numero": "Numero" }
}
```

#### procesos

El software: los procesos, sus parametros y sus alarmas.

```json
"procesos": {
  "sufijos_nmax": { "preal": "PREAL", "pint": "PINT", "alm": "ALM", "alm_hmi": "ALM_HMI" },
  "columnas": {
    "procesos": ["plc_name", "codigo", "..."],
    "preal": ["plc_name", "numero", "..."],
    "pint": ["plc_name", "numero", "..."],
    "alarmas": ["plc_name", "numero", "..."]
  },
  "etiquetas": { "numero": "No" }
}
```

| Clave | Que es |
|---|---|
| `sufijos_nmax` | el sufijo de cada N_MAX de proceso (`100_N_MAX_PREAL`) |
| `columnas.procesos` | las columnas de la sub-pestana Procesos |
| `columnas.preal` | las de los parametros reales |
| `columnas.pint` | las de los parametros enteros |
| `columnas.alarmas` | las de las alarmas |
| `etiquetas` | los titulos de las columnas del software |

## Reglas

- **Un identificador por tipo.** La clave de `dispositivos` es el nombre del
  tipo en toda la app: en las pestañas, en el diff de la prevision y en las
  filas del Excel.
- **Las etiquetas van por seccion.** `numero` se titula `Número` en los
  dispositivos, `No` en el software y `Numero` en las entidades. No se pisan
  porque cada seccion tiene las suyas.
- **El orden de los N_MAX** es el de sus constantes (alfabetico), con el de las
  entidades el ultimo. Asi las tarjetas de N_MAX se pintan siempre igual.
- **Las claves que no son del formato no se admiten.** Un `config.json` de una
  version anterior se rechaza con un mensaje claro, no se ignora en silencio.
- **Sin rutas absolutas.** El config es portable: las rutas van relativas a la
  carpeta de datos de la app.
- **El PLC no esta en el config.** Se elige en la web, en la sesion.
- **Los tipos legacy** (`agrup`, `ff`, `media`, `ton`, ...) no estan: sus N_MAX
  no se usan.
