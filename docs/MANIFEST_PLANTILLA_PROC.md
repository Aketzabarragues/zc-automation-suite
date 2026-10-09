# Manifest de plantilla (procesos)

Cada subcarpeta de `plantillas_path` que quiera aparecer como
plantilla clonable debe contener un `manifest.json` valido.

Este documento describe el shape completo. Para una nueva
plantilla, copia el bloque JSON de "Ejemplo" abajo en un fichero
`manifest.json` dentro de la subcarpeta y adapta los valores.

## Campos obligatorios

| Campo          | Tipo            | Notas                                                                                            |
| -------------- | --------------- | ------------------------------------------------------------------------------------------------ |
| `base`         | int             | Numero base del bloque TIA (e.g. 50010). Cada bloque se calcula a partir de este numero.         |
| `codigo`       | str no vacio    | Codigo del proceso (e.g. "EXP", "CPR"). Prefijo corto que aparece en nombres de bloque.           |
| `nombre`       | str no vacio    | Nombre humano del proceso (e.g. "Expedicion"). Aparece en menus.                                  |
| `descripcion`  | str no vacio    | Descripcion larga (1-2 frases, lenguaje humano). Se muestra en el selector de la SPA.            |
| `dependencias` | list[str]       | Bloques del PLC que la plantilla REQUIERE que ya existan. Match exacto por nombre TIA canonico.  |
| `minimos`      | dict[str, int]  | 4 N_MAX que el proceso destino debe cubrir: `N_MAX_PREAL`, `N_MAX_PINT`, `N_MAX_ALM`, `N_MAX_ALM_HMI`. |

## Campo opcional

| Campo          | Tipo | Notas                                                                                       |
| -------------- | ---- | ------------------------------------------------------------------------------------------- |
| (sin extras)   |      | El manifest es minimalista: no hay campos opcionales hoy. Anadir solo si es estrictamente necesario. |

## Restricciones operativas

### Dependencias

Cada entrada de `dependencias` debe coincidir EXACTAMENTE con el
nombre de un bloque ya existente en el PLC destino (match case-
sensitive). Los nombres validos son los nombres TIA canonicos con
prefijo + numero + sufijo (e.g. `DB1_SYS`, `FC15151_ZC_MARCHA_PARO_SEC`).

Si una dependencia declarada NO existe en el PLC, la SPA pinta
la fila en rojo y bloquea el boton "Aplicar". Si el PLC todavia
no esta escaneado, todas las dependencias se reportan como
faltantes (mismo bloqueo) hasta que el operario escanee.

Para saber que nombres existen en tu PLC, ve a "Escanear bloques
PLC" en la SPA y mira la cache (`plcBlocksCache`).

### Minimos

Los `minimos` describen el piso que el proceso destino debe
cubrir. Si los valores del proceso (del Excel maestro) son
menores que los de la plantilla, la SPA no permite aplicar.

Las 4 claves son canonicas: deben aparecer las 4. Valores en
`0` no son validos (interpretar como "sin minimo" dejaria huecos
en TIA; siempre poner un entero positivo razonable).

## Ejemplo

Copia este bloque tal cual en `manifest.json`, adapta los
valores a tu caso y listo.

```json
{
  "base": 50010,
  "codigo": "NUEVO",
  "nombre": "Proceso Nuevo Estandar",
  "descripcion": "Proceso estandar para X. Requiere el bloque de sistema DB1_SYS y la FC de marcha/paro de la zona Z.",
  "dependencias": [
    "DB1_SYS",
    "FC15151_ZC_MARCHA_PARO_SEC"
  ],
  "minimos": {
    "N_MAX_PREAL": 5,
    "N_MAX_PINT": 20,
    "N_MAX_ALM": 16,
    "N_MAX_ALM_HMI": 4
  }
}
```

## Errores comunes

- `"base": "50010"` (string en vez de int): lanza `ManifestInvalido: manifest.json debe contener 'base' (int).`
- `"dependencias": [""]`: las entradas vacias o solo-whitespace se rechazan (`manifest.json 'dependencias' debe ser una lista de strings no vacios.`).
- `"dependencias": "DB1_SYS"` (string en vez de list): lanza `ManifestInvalido: manifest.json debe contener 'dependencias' (list[str]).`
- `"dependencias": []`: lista vacia NO es valido (`manifest.json debe contener 'dependencias' (list[str]).`). El helper exige al menos 1 para validar contra la cache. Si tu plantilla no referencia bloques externos reales, declara un bloque que SIEMPRE exista en el PLC (ej. `DB1_SYS`).
- Falta `descripcion`: lanza `ManifestInvalido: manifest.json debe contener 'descripcion' (str no vacio).`
