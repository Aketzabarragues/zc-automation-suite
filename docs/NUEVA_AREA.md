# Anadir un area

Un area es una unidad de negocio con sus propios datos, sus operaciones
contra TIA y sus vistas. Ejemplos: `alimentacion`, `envasado`.

## 1. Paquete del area

Crea `backend/zc_suite/areas/<id>/__init__.py`. El contrato son siete cosas:

```python
"""<id> — <nombre legible>."""

from __future__ import annotations

from typing import Any

from flask import Blueprint

ID = "mi_area"
NOMBRE = "Mi Area"

rutas = Blueprint("mi_area", __name__, url_prefix="/api/mi_area")


def catalogo(config: Any) -> dict[str, Any]:
    """Datos del area que la SPA consume: columnas, tipos, tablas."""
    return {"dominios": []}


def defaults(config: Any) -> dict[str, Any]:
    """Valores por defecto que el area aporta a su seccion de config."""
    return {}


def al_arrancar(config: Any) -> None:
    """Prepara el area para la sesion. Se llama al montar la app."""
    ...


def estado_sesion() -> dict[str, Any]:
    """Lo que el area tiene en la sesion. Lo sirve GET /api/v1/sesion."""
    return {}


def valida_config(config: Any) -> str | None:
    """El motivo por el que la seccion del area no vale, o None si vale."""
    return None
```

- `ID` va en minusculas y sin acentos. Es la clave en `config.json` y en la
  ruta del frontend.
- `NOMBRE` es lo que ve el operario en el menu.
- `rutas` es un `Blueprint` de Flask. El shell es Flask, no FastAPI.
- `catalogo(config)` y `defaults(config)` reciben la config ya validada.
- `al_arrancar(config)` se llama al montar la app, con la seccion del area.
- `estado_sesion()` devuelve lo que el area tiene en la sesion.
- `valida_config(config)` devuelve el motivo por el que la seccion del area no
  vale, o `None` si vale. El nucleo lo enseña en el banner de config
  incompatible.

## 2. Registro

Anade el area a la lista `AREAS` de `backend/zc_suite/nucleo/app/main.py`:

```python
AREAS = [
    areas_alimentacion,
    areas_mi_area,
]
```

No hay registro automatico, ni ganchos opcionales, ni plugins. Esa lista es
el unico sitio donde el nucleo conoce las areas.

## 3. Modulos del area

Layout recomendado dentro de `areas/<id>/`:

```
__init__.py     ID, NOMBRE, rutas, catalogo(), defaults(), al_arrancar(),
                estado_sesion(), valida_config()
config.py       el modelo del config del area: lo valida y lo describe
rutas.py        el Blueprint del area
funciones/      un FB por fichero: funciones/<dominio>/<verbo>.py
excel/          logica pura del Excel: parser.py, modelo.py, tablas.py, ...
<dominio>/      logica pura del dominio (dispositivos/, procesos/, ...)
```

Lo de `funciones/` es lo que **lanza la web**: recibe el `job`, declara sus
pasos y abre transacciones. Lo de `<dominio>/` es logica pura: no depende de
TIA ni recibe el `job`.

`config.py` es el unico que conoce el formato de la seccion del area: el resto
del area consume ese modelo, no el dict crudo. El formato esta en
[CONFIG.md](CONFIG.md).

Las areas **no se importan entre si** y el nucleo **no importa las areas**
(la unica excepcion es la lista `AREAS`). `tests/test_fronteras.py` lo
comprueba recorriendo los imports, y `tests/test_fronteras_dominio.py` que la
logica pura no depende de TIA.

## 4. Operaciones

Una operacion es UNA funcion con dos modos:

```python
def sincronizar(job: Job, plc: str, aplicar: bool) -> dict[str, Any]:
    """Sincroniza los dispositivos. ``aplicar=False`` es el preview."""
    job.empezar("Sincronizar dispositivos", ["exportar", "comparar", "aplicar"])
    with job.paso("exportar") as paso:
        ...
    if not aplicar:
        return {"cambios": cambios}
    with transaccion(job, "Importar dispositivos"):
        ...
    return {"cambios": cambios, "aplicados": cambios}
```

- No existen pares preview/operar. El preview es la misma funcion con
  `aplicar=False`.
- Toda escritura en TIA va dentro de `with transaccion(job, texto):`.
- Si hay varias transacciones, el resultado dice cuales se confirmaron cuando
  una falla a mitad.
- `job.tia.portal` es la unica forma de llegar al portal.

## 5. Frontend

Crea `frontend/src/areas/<id>/index.js`:

```javascript
export default {
  id: "mi_area",
  nombre: "Mi Area",
  rutas: [
    { path: "/mi-area", vista: () => import("./vistas/MiArea.vue"), menu: "Mi Area" },
  ],
  menu: [{ etiqueta: "Mi Area", ruta: "/mi-area" }],
};
```

El shell las recoge con `import.meta.glob`. El shell no importa vistas de
area de forma directa.

## 6. Tests

En `tests/areas/<id>/test_<que>.py`. Los dobles son propios: un objeto falso
para el portal, nunca el SDK real ni la red.

```bash
python -m pytest tests/areas/ -q
```
