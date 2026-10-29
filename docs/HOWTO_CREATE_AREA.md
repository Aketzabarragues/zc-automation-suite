# HOWTO — Crear un área nueva

> Audiencia: técnico que conoce Bounded Contexts y ha leído
> `AGENTS.md §1` (núcleo de la arquitectura) y `§6` (cómo añadir un
> área). Esta guía es una **réplica standalone** con un ejemplo
> end-to-end; no reemplaza la lectura de `AGENTS.md`.

## 1. Pre-requisitos

- Leer `AGENTS.md §1` (capas transversal `core/` vs `areas/<area>/`).
- Tener claras las decisiones de diseño (siguiente sección).
- Conocer el layout de un área real: `areas/alimentacion/` es la
  referencia canónica.

## 2. Decisiones de diseño (input del operario)

Antes de tocar código, confirma con el operario:

- **`area_id` canónico.** Snake_case, sin prefijos. Ejemplos:
  `alimentacion`, `envasado`, `paletizado`.
- **Departamento y permisos.** Cada área aparece bajo un
  departamento en `config/config.json`. Los permisos TIA (qué PLC
  puede tocar) se configuran a nivel de departamento.
- **¿Aporta comandos TIA extra?** Si tu área necesita comandos que
  no están en los 27 del catálogo genérico (ver `AGENTS.md §`),
  crea `areas/<area>/infrastructure/tia/extra_commands.py` y
  registra en `AreaSpec.contributes_tia_commands(tia_client)`.

## 3. Layout mínimo del área

```
areas/<area_id>/
├── __init__.py                  # AREA_SPEC + register(engine, ...)
├── _area_id.py                  # constante AREA_ID = "<area_id>" (convenio)
├── data/                        # DTOs puros del dominio
│   └── disp_catalog.py         # catalogos de dispositivos
├── helpers/
│   └── excel/                  # parsers Excel del area
│       └── excel_parser_<tipo>.py
├── functions/                  # Function Blocks (state machines)
│   └── function_<fb>.py
├── state/                       # estado runtime del area (opcional)
├── frontend/                    # SPA + routers Flask del area
│   ├── components/             # componentes Vue 3 ESM
│   ├── manifest.js              # build() que devuelve { components, routes, ... }
│   └── <fb>_router.py           # Blueprint Flask del FB
└── tests/                       # tests del area (NO en tests/areas/<area>/)
```

`tests/areas/<area_id>/` también existe en la raíz (es lo que
descubre pytest). Convención: tests unitarios del área en
`tests/areas/<area>/`, además de los `tests/` locales si los hay.

## 4. Definir `AREA_SPEC`

Edita `areas/<area_id>/__init__.py`:

```python
from core.composition.app_area_registry import AreaSpec, AreaResources

AREA_SPEC = AreaSpec(
    area_id="<area_id>",
    title="<Titulo visible en el sidebar>",
    icon="<icon-key>",  # ver core/web_server/static/manifest/icons.js
    contributes_catalog=lambda: [...],  # catalogos de dispositivos/procesos
    contributes_tia_commands=lambda tia_client: None,  # ver AGENTS.md §6.4
    contributes_routers=lambda app: _build_all_routers(app),  # ver punto 7
    contributes_components=lambda: [...],  # ver punto 8
)
```

## 5. Catálogo del área

En `areas/<area_id>/data/disp_catalog.py` (o `proc_catalog.py`):

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class DispCatalogEntry:
    plc_name: str
    block_name: str
    n_max: int
    # ...

CATALOG: list[DispCatalogEntry] = [
    DispCatalogEntry(plc_name="PLC_1", block_name="DB100", n_max=10),
    # ...
]
```

Este catálogo lo recoge automáticamente el `GET /api/v1/catalog` del
web. No hace falta cablearlo en otro sitio.

## 6. Registrar FBs

En `areas/<area_id>/__init__.py`:

```python
def register(engine, *, config_manager=None, tia_client=None,
             build_cache=None, app_cache=None) -> None:
    from .functions.function_<fb> import Function<FB>
    engine.register_fb("<fb>", Function<FB>(...))
    # ... mas FBs
```

`log` no se inyecta; usa `logging.getLogger(__name__)`.

## 7. Routers Flask del área

En `areas/<area_id>/frontend/<fb>_router.py`:

```python
from flask import Blueprint, current_app, jsonify

bp = Blueprint("<area>_<fb>", __name__, url_prefix="/api/v1/<area>/<fb>")

@bp.post("/start")
def start():
    engine = current_app.config["ENGINE"]
    job_id = engine.submit("<fb>", <param>)
    return jsonify({"ok": True, "job_id": job_id}), 202
```

Las dependencias del runtime se leen de `current_app.config` (`ENGINE`,
`EVENT_BUS`, `APP_CACHE`, ...), nunca de un singleton importado en el
módulo: los tests rompen con imports globales.

El router **encola y responde `202`**: no espera al resultado. El
trabajo lo ejecuta el hilo `plc-ob1` del `Engine` y el estado del FB
llega al HMI por SSE (`fb_state`), con los datos del resultado en los
slots del `AppCache` (`cache_changed`). El `ProgressTracker` lo
gestiona el FB (`begin` en `on_start`, `start_stage`/`finish_stage` en
cada step, `finish` en `on_finish`): el router no lo escribe.

Y en `areas/<area_id>/frontend/__init__.py`:

```python
def _build_all_routers(app):
    from .<fb>_router import bp as <fb>_bp
    app.register_blueprint(<fb>_bp)
    # ... mas blueprints
```

## 8. Manifest del área (SPA)

En `areas/<area_id>/frontend/manifest.js`:

```javascript
export function build() {
  return {
    components: {
      MiVista: () => import("./components/MiVista.js"),
    },
    routes: {
      "mi-vista": "MiVista",
    },
    sidebar: [
      { key: "mi-vista", title: "Mi Vista", icon: "<icon>" },
    ],
    landing: "mi-vista",
    loaders: [],
  };
}
```

El shell SPA (`core/web_server/static/main.js`) lo carga
dinámicamente vía `area-loader.js` al entrar al área.

## 9. Entrada en `config/config.json`

```json
{
  "departments": {
    "<area_id>": {
      "title": "<Titulo>",
      "permissions": {
        "plcs": ["PLC_1", "PLC_2"]
      }
    }
  }
}
```

## 10. Tests mínimos + smoke E2E

- Test unitario por FB en `tests/areas/<area>/functions/test_<fb>.py`
  con `MagicMock(spec=SyncTIAClient)`.
- Smoke E2E: arrancar la app con `?demo=1` y verificar que el
  área aparece en el sidebar.

## Convenciones

- Prefijos `disp_*` / `proc_*` primero en archivos y clases del
  área. NO mezclar.
- No importar `siemens_tia_scripting` directamente; pasar siempre
  por `tia_client.dispatch("comando", args)`.
- `log = logging.getLogger(__name__)` (no inyectado).
- Tests con `MagicMock(spec=SyncTIAClient)`, nunca mockear el
  worker directamente.
