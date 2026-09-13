# zc-automation-suite

Suite de automatizacion para proyectos TIA Portal. Une la IT (Excel
corporativo, N_MAX, dispositivos, procesos) con la OT (TIA Portal
v17+ via Openness).

## Estado actual

App OB1 — sin TIA obligatorios para arrancar. Sin FBs legacy
registrados; solo FunctionBlock Template (dummy 10 pasos x 1s).

## Arrancar la app

```cmd
python main.py
```

Aparece icono en la bandeja del sistema. Click derecho → **Iniciar
web** → Flask daemon + main loop en `http://127.0.0.1:9484`.

Si TIA Portal esta abierto y quieres engancharte, pulsa **Conectar**
desde la topbar de la SPA (o `POST /api/v1/tia/connect`).

### Smoke test (sin bandeja, sin GUI)

```cmd
python _local_demo/smoke_main_lifecycle.py
```

Verifica el flujo base: setup_logging + ConfigManager + tia-loop
+carga wrapper + engine + Flask + stop limpio. Imprime
`SMOKE MAIN: PASS` si todo va bien.

## Arquitectura OB1

```
main.py                          # entry point unico (bandeja, puerto 9484)
└─ launcher/main_supervisor.py   # 3 hilos daemon
   ├─ tia-loop                   # drena cola, unico dueno del wrapper .NET
   ├─ flask-daemon               # werkzeug serve_forever (threaded=False)
   └─ main-loop                  # engine.run_cycle() cada 100 ms
```

### Subsistema TIA (`core/infrastructure/tia_loop.py`)

State machine de 6 estados:

```
IDLE -> ATTACHING -> CONNECTED <-> BUSY
                    CONNECTED -> DETACHING -> IDLE
                                  o ERROR (irrecuperable)
```

API publica:

```python
from core.infrastructure.tia_loop import SyncTIAClient, register_core_commands
from areas.alimentacion.infrastructure.tia.extra_commands import register_main

tc = SyncTIAClient()
register_core_commands(tc)   # 24 commands core (lifecycle, inspection, mutation)
register_main(tc)             # 13 commands del area alimentacion
tc.start_tia_loop()           # arranca hilo + carga wrapper .pyd

# Request/response (bloquea con timeout):
result = tc.submit_and_wait("attach_portal", {}, timeout=10.0)

# Fire-and-forget:
tc.submit("list_plcs", {})

# Lote atomico:
results = tc.submit_batch([("attach_portal", {}), ("get_project_info", {})], timeout=30.0)

# Estado actual:
print(tc.state)  # "idle" | "attaching" | "connected" | "busy" | "detaching" | "error"
```

## FuncionBlock Template

`areas/alimentacion/functions/function_Template.py` — FB con 10
pasos discretos (1s cada uno). Patron para migrar los FBs legacy
del area. Se registra automaticamente en el engine al arrancar.

```
nStep=10   arrancar
nStep=20..90   pasos 1..8 (sleep 1s cada uno)
nStep=95   finalizar
nStep=99   done (terminal)
```

Tiempo total: ~10 segundos.

## Endpoints HTTP

| Metodo | Path | Descripcion |
|---|---|---|
| GET | `/api/v1/tia/connection` | Estado del subsistema TIA (state, project, plcs). |
| POST | `/api/v1/tia/connect` | attach_portal (timeout 10s). |
| POST | `/api/v1/tia/disconnect` | detach_portal (timeout 10s). |
| GET | `/api/v1/ping` | `{"pong": true}`. |
| GET | `/api/v1/cycle_count` | Numero de ciclos del main loop. |
| GET | `/api/v1/stream` | SSE keepalive. |
| GET | `/api/v1/catalog` | Catalogo de areas. |
| GET | `/api/v1/areas` | Lista de areas configuradas. |
| GET | `/api/v1/areas/<id>/manifest` | Manifest del area. |

Los 7 blueprints Flask viven en `interfaces/web_server/routers/`.
La SPA (Vue 3 ESM, sin build step) vive en
`interfaces/web_server/static/`.

## Configuracion del usuario

`config/config.json` (eager-loaded al arrancar). El path del
config se resuelve por:

1. `$ZC_CONFIG_DIR/config.json` (override)
2. Modo frozen: `<exe_dir>/config/config.json`
3. Modo dev: `<cwd>/config/config.json`
4. Fallback readonly al bundleado

Politica: **el usuario gana siempre** — no sobreescribimos un
`config.json` existente.

## Estructura del proyecto

```
zc-automation-suite/
├── main.py                       # entry point unico
├── run_app.bat                   # python main.py
├── build_exe.py                  # PyInstaller
├── config/config.json
├── launcher/
│   ├── main_supervisor.py        # 3 hilos daemon
│   ├── tray_app.py               # bandeja pystray
│   └── icon.ico
├── core/
│   ├── application/              # area_registry, log_paths, state
│   ├── infrastructure/
│   │   ├── tia_loop.py           # SyncTIAClient + state machine
│   │   ├── tia_loader.py         # carga .pyd/.dll/.xml
│   │   ├── build_cache.py, config_manager.py, config_paths.py
│   │   └── cache/bloque_cache_manager.py
│   ├── plc/                      # engine, function_base
│   ├── sse/                      # event_bus_sync + 3 subscribers
│   └── models/                   # bloque_cache, bloque_plc
├── interfaces/web_server/
│   ├── app_flask.py
│   ├── routers/                  # 7 blueprints
│   └── static/                   # SPA Vue 3
├── areas/alimentacion/
│   ├── __init__.py               # AREA_SPEC + register(engine)
│   ├── functions/
│   │   └── function_Template.py  # FB 10 pasos x 1s
│   ├── infrastructure/tia/extra_commands.py
│   ├── domain/, application/, data/, frontend/
│   └── ...
├── tests/
└── _local_demo/
    └── smoke_main_lifecycle.py
```

## Convenciones

- Sin build step para la SPA: modulos ESM directos.
- Comandos TIA: handler signature `(args: dict, tia_client: SyncTIAClient) -> dict`.
- Estado: `{"ok": True, "result": <dict>}` o `{"ok": False, "error": <str>}`.
- Wrapper .NET: single-threaded; solo el tia-loop lo toca.
- Logger jerarquico: `zc` (raiz), `zc.main`, `zc.web`, etc.

## Build del .exe

```cmd
python build_exe.py
```

Salida: `dist/zc_automation_suite.exe`. Bundlea `config/`,
`interfaces/web_server/static/`, `areas/alimentacion/frontend/` y
`launcher/icon.ico`.
