# Anadir un area

Un area es una unidad de negocio con sus propios datos, sus operaciones
contra TIA y sus vistas. Ejemplos: `alimentacion`, `envasado`.

## 1. Paquete del area

Crea `backend/zc_suite/areas/<id>/__init__.py`. El contrato son cinco cosas:

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
```

- `ID` va en minusculas y sin acentos. Es la clave en `config.json` y en la
  ruta del frontend.
- `NOMBRE` es lo que ve el operario en el menu.
- `rutas` es un `Blueprint` de Flask. El shell es Flask, no FastAPI.
- `catalogo(config)` y `defaults(config)` reciben la config ya validada.

## 2. Registro

Anade el area a la lista `AREAS` de `backend/zc_suite/main.py`:

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
__init__.py     ID, NOMBRE, rutas, catalogo(), defaults()
excel/          lector.py, tablas.py, especiales.py
datos/          catalogos y slot maps
<dominio>.py    logica de negocio pura (dispositivos.py, procesos.py, ...)
diff.py         calculo de diferencias
```

Las areas **no se importan entre si** y el nucleo **no importa las areas**
(la unica excepcion es la lista `AREAS`). `tests/test_fronteras.py` lo
comprueba recorriendo los imports.

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
