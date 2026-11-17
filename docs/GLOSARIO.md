---
description: "Significado de las siglas y abreviaturas del repo, y cuales son contrato (no se tocan) y cuales son internas."
read_if: "Antes de renombrar un identificador, tocar una clave de JSON o de config, o escribir un nombre nuevo con siglas."
---

# Glosario de siglas

| Sigla | Significado | Donde se usa | Contrato / interno |
|---|---|---|---|
| `TIA` | TIA Portal, el producto de Siemens con el que se trabaja | Todo el backend (hilo de TIA, SDK `siemens_tia_scripting`) | Contrato |
| `PLC` | Controlador logico programable | Todo el proyecto | Contrato |
| `DB` | Data Block: bloque de datos de un PLC | Nombres de bloque en TIA (`DB53100_CPR_PARAM`), clave `db` del config | Contrato |
| `FB` | Function Block | Nombres de bloque en TIA | Contrato |
| `FC` | Function Call | Nombres de bloque en TIA (`FC101_CPR_ORDENES`) | Contrato |
| `UDT` | User Data Type | Nombres de bloque en TIA | Contrato |
| `OB` | Organization Block | Solo en la documentacion de familias de bloque | Contrato |
| `N_MAX` | Numero maximo de elementos de un array o tabla, por tipo de dispositivo | Clave `constante` del `config.json` (`N_MAX_DISP_ED`), nombres de constante TIA `<uid>_N_MAX_<SUFIJO>`, columna del Excel | Contrato |
| `n_max` | La misma idea, en minuscula, dentro del nombre de la constante TIA | `areas/alimentacion/procesos/mapa.py`, `sincronizacion_comun.py` | Contrato |
| `MLC` | Identificador de texto multilingue (`MLC_a1b2`) | Ficheros `.s7res` y cabeceras `.s7dcl` | Contrato |
| `SimaticSD` | Formato de exportacion de bloques de TIA V21 (`.s7dcl` + `.s7res`) | `backend/zc_suite/simatic/sd/` | Contrato |
| `SimaticML` | Formato XML de las tablas de tags | `backend/zc_suite/simatic/ml/` | Contrato |
| `sd` | Sufijo de carpeta: SimaticSD | `backend/zc_suite/simatic/sd/` | Interno |
| `ml` | Sufijo de carpeta: SimaticML | `backend/zc_suite/simatic/ml/` | Interno |
| `dcl` | Sufijo `.s7dcl`, la declaracion del bloque | `simatic/sd/cabecera.py:26` | Contrato |
| `res` | Sufijo `.s7res`, los textos multilingues | `simatic/sd/cabecera.py:29` | Contrato |
| `s7dcl` | Fichero SimaticSD de declaracion | En disco, exportado por TIA | Contrato |
| `s7res` | Fichero SimaticSD de textos (encoding `utf-8-sig`) | En disco, exportado por TIA | Contrato |
| `uid` | Identificador numerico unico de una fila del Excel maestro | Columna `uid` del Excel, campo del modelo | Contrato |
| `proc_uid` | El `uid` de un proceso concreto | Parametros de las funciones de procesos | Interno |
| `CPR` | Codigo del proceso de ejemplo con `uid` 100 (no es una sigla) | Fixtures de test, ejemplos en la documentacion | Contrato (los tests lo asumen) |
| `faceplate` | El panel de progreso del trabajo en la SPA | `frontend/src/nucleo/componentes/FaceplateProgreso.vue` | Interno |
| `device_tabs` | Clave del catalogo: las pestanas de dispositivos | Respuesta de `GET /api/v1/catalogo` | Contrato |
| `slot_map` | Mapa de slot de array a comentario del Excel | `areas/alimentacion/procesos/mapa.py` y `diferencias.py` | Interno |
| `ap21` | Extension del fichero de proyecto de TIA Portal | Selector de proyecto de la SPA | Contrato |

## Siglas sin definicion confirmada

- `xcpt`: no aparece en el repo (busqueda exhaustiva vacia).
- `fbd`: no aparece en el repo (busqueda exhaustiva vacia).
- `ts`: solo aparece en un ejemplo del SDK en `docs/TIA_OPENNESS.md:32`
  (`ts.set_logging`); no es un identificador del repo.
