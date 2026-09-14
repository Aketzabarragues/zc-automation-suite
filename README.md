# zc-automation-suite

Capa de integración IT/OT para automatización e inspección de proyectos
en **Siemens TIA Portal** mediante el SDK oficial **TIA Scripting Python**.

Une la IT (Excel corporativo, N_MAX, dispositivos, procesos) con la OT
(TIA Portal v17+ via Openness) a través de un subproceso persistente y
una SPA Vue 3 servida en local. Pensada para un único operario por
puesto (single-tenant).

---

## Tabla de contenidos

**Operario**
1. [Qué hace por ti](#1-qué-hace-por-ti)
2. [Requisitos e instalación](#2-requisitos-e-instalación)
3. [Cómo se arranca](#3-cómo-se-arranca)
4. [Cómo se usa (topbar y paneles)](#4-cómo-se-usa-topbar-y-paneles)
5. [Solución de problemas](#5-solución-de-problemas)

**Desarrollador**
6. [Estructura del repositorio](#6-estructura-del-repositorio)
7. [Cómo añadir un área nueva](#7-cómo-añadir-un-área-nueva)
8. [Smokes y validación](#8-smokes-y-validación)
9. [Build del .exe](#9-build-del-exe)
10. [Convenciones operativas](#10-convenciones-operativas)

---

## 1. Qué hace por ti

- **Sube el Excel corporativo** y aplica los cambios contra TIA Portal
  en **una sola transacción atómica**. Si algo falla a mitad, todo se
  revierte (`start_transaction` / `end_transaction(rollback=True)`).
- **Mantiene TIA Portal conectado a un subproceso persistente**: el
  operario decide cuándo conectar y cuándo desconectar desde el topbar;
  no se paga el coste de arranque del wrapper nativo en cada operación.
- **Sirve los flujos desde una SPA web** (bandeja del sistema + navegador)
  para el operario.
- **Modificadores offline XML/SD idempotentes** — aplicar dos veces el
  mismo cambio no duplica instancias.
- **ProgressTracker con HMI integrado**: cada FunctionBlock reporta sus
  pasos (`pending` / `running` / `done` / `error`) a un panel visible
  durante operaciones largas.

---

## 2. Requisitos e instalación

| Componente | Requisito |
|---|---|
| Sistema operativo | Windows 10 / 11 / Server (64-bit). Solo Windows: TIA Openness requiere COM. |
| Python | **3.12.x, 3.13.x o 3.14.x** (64-bit). |
| TIA Portal | V15.1 o superior con Openness instalado. |
| Permisos Windows | Tu usuario debe pertenecer al grupo `Siemens TIA Openness`. |
| Librería TIA Scripting | Wheel oficial de Siemens: `siemens_tia_scripting-*.whl`. |

Instalación rápida:

```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install siemens_tia_scripting-*.whl

python -c "import siemens_tia_scripting; print('OK')"
```

Las dependencias de bandeja (`pystray`, `Pillow`) vienen en
`requirements.txt` y solo son necesarias si vas a usar la bandeja o el
ejecutable empaquetado.

---

## 3. Cómo se arranca

### 3.1 Bandeja del sistema + web (operario en producción)

```cmd
run_app.bat
```

Doble clic sobre `run_app.bat` o `python main.py`. Aparece un icono en
la bandeja con menú: **Iniciar web**, **Parar web**, **Abrir panel web**,
**Estado**, **Salir**.

### 3.2 Web directo (sin bandeja, dev)

```cmd
python main.py --web
:: por defecto http://127.0.0.1:9484
:: opcional: python main.py --web 0.0.0.0:5000
```

Levanta Flask (threaded) + el main loop. Útil en desarrollo para tener
logs en consola.

### 3.3 Ejecutable empaquetado (producción, sin Python instalado)

Doble clic sobre `dist\zc_automation_suite.exe` (ver [Build del .exe](#9-build-del-exe)).
Icono en la bandeja, mismo menú que 3.1.

---

## 4. Cómo se usa (topbar y paneles)

Al abrir el panel web en `http://127.0.0.1:9484` ves:

- **Topbar** — Indicador del estado del subproceso TIA (gris = idle,
  ámbar = connecting, verde = connected) y dos botones:
  - **Conectar**: lanza `attach_portal` contra el TIA Portal que ya
    tienes abierto. Solo funciona si TIA Portal está ejecutándose con
    un proyecto cargado.
  - **Desconectar**: hace `detach_portal`. **El subproceso sigue vivo**
    en estado `idle`, listo para un próximo Conectar sin pagar el coste
    de arrancar de nuevo.
- **Sidebar** — Chrome corporativo transversal:
  - Cabecera con el área activa (label derivado de la key del área).
  - Botón **🔌 PLC** (siempre visible, vista común a todas las áreas).
  - Navegación del área activa (cargada del manifest del área).
  - **ProgressIndicator** (variant dark) al final.
  - Botón **← Volver al inicio** para volver al selector de áreas.
- **Panel principal** — Depende del área. Para Alimentación: tabs de
  Definición programación / Dispositivos / Inicio / Procesos / Sync.
- **Panel de progreso** — Aparece en operaciones >500 ms. Stages con
  `pending` / `running` / `done` / `error`.
- **Panel de logs** — Consola con los logs del backend. Polling a 1s.

### Flujo típico (sync de dispositivos desde Excel)

1. Operario carga el Excel corporativo desde la SPA.
2. Pulsa **Conectar** en el topbar. El indicador pasa a verde.
3. Selecciona el PLC en la SPA.
4. Entra al panel de Dispositivos → Sync → **Preview**: la suite
   calcula el diff **sin tocar TIA**. Muestra `agregados`,
   `eliminados`, `renombrados` y los `N_MAX` que cambiarán.
5. Si el preview le encaja, pulsa **Commit**: la suite aplica los
   cambios en **una sola transacción TIA**. Si algo falla, todo se
   revierte automáticamente.
6. Pulsa **Desconectar** cuando termine la sesión.

---

## 5. Solución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| El botón Conectar se queda en ámbar más de 60s | TIA Portal no responde o no tiene proyecto cargado. | Abre TIA Portal con un proyecto, vuelve a pulsar Conectar. |
| `attach_portal retorno None. ¿Está TIA Portal abierto?` | TIA Portal no está abierto, o tu usuario no pertenece al grupo `Siemens TIA Openness`. | Abre TIA Portal con un proyecto. Verifica permisos en `Administración de equipos → Usuarios → Siemens TIA Openness`. |
| `Timeout tras Ns ejecutando el comando 'X'` | El subproceso OT no responde (diálogo modal abierto en TIA, o TIA colgado). | Cierra cualquier diálogo modal en TIA Portal. Si el timeout es muy corto, súbelo con la env var `ZC_GATEWAY_TIMEOUT` (default 300s). |
| La SPA no carga | El web server no está arrancado, o la URL es otra. | Lanza el web server con `python main.py --web` o desde el menú de la bandeja. Verifica `http://127.0.0.1:9484`. |

Diagnóstico avanzado:

- **Logs del worker** (`worker_openness.log`): trazas C++/COM del
  wrapper nativo de Siemens. Está junto al ejecutable en modo frozen,
  o en la raíz del repo en dev.
- **Logs del launcher** (`zc.log`): actividad del main loop, web server
  y bandeja. En `%LocalAppData%\zc-automation-suite\logs\` por defecto.
- **Panel de logs en la SPA**: vista rápida de lo que está pasando en
  el backend (polling 1s, no para diagnóstico fino).

---

## 6. Estructura del repositorio

```
zc-automation-suite/
├── main.py                          # entry point unico (bandeja + --web HOST:PORT)
├── run_app.bat                      # python main.py
├── run_build.bat                    # python build_exe.py
├── run_tailwind.bat                 # recompilar CSS
├── build_exe.py                     # PyInstaller (--onefile, mode windowed)
├── tailwind.config.js               # config Tailwind v4 offline
├── AGENTS.md                        # guia de extension para agentes
├── requirements.txt
├── config/config.json               # departamentos + TIA paths
│
├── core/                            # transversal, NO sabe de areas
│   ├── web_server/                  # Flask + SPA Vue 3
│   │   ├── app_flask.py             # threaded=True
│   │   ├── routers/                 # 7 blueprints (areas, plc, portal, ...)
│   │   └── static/                  # SPA (index.html + js/ + styles.css)
│   │       └── js/components/       # ShellSidebar, ShellTopbar, plcpanelview,
│   │                                #   Welcome, ProgressIndicator, ConsolaLogs
│   ├── launcher/                    # main_supervisor (3 hilos daemon) + tray
│   ├── composition/                 # AreaSpec, engine wiring
│   ├── data/                        # modelos compartidos
│   ├── infrastructure/              # tia_loop (state machine), config, ...
│   └── runtime/                     # event bus, progress tracker
│
├── areas/                           # cada area autocontenida
│   └── alimentacion/                # unica area hoy
│       ├── __init__.py              # AREA_SPEC + register(engine)
│       ├── frontend/
│       │   ├── manifest.py          # espejo Python del .js
│       │   ├── manifest.js          # SPA: componentes + viewLabels
│       │   └── components/          # vistas especificas del area
│       ├── functions/               # FBs (FunctionBase con HMI)
│       │   ├── function_template.py # patron para migrar FBs reales
│       │   └── function_<nombre>.py # SubirExcel, ScanPlcBlocks, ...
│       ├── application/             # use cases
│       ├── domain/                  # modelos puros
│       ├── data/                    # data_Dispositivos, data_Procesos, ...
│       └── infrastructure/          # parsers Excel, sd, xml, tia, cache
│
├── tests/                           # tests pytest
├── _local_demo/                     # smokes sin navegador
└── _review/                         # paginas de revision (no se commitea)
```

### Capas y reglas

- `core/` contiene TODO lo transversal sin saber de áreas. Cada
  `areas/<area>/` es un paquete autocontenido que se autodescribe vía
  `AreaSpec`.
- `siemens_tia_scripting` SOLO se importa en el worker OT
  (`core/infrastructure/tia/worker_tia.py`). Cualquier intento de
  importarlo en otra capa es un bug crítico.
- Las áreas **no importan entre sí**; comparten vía `core/`. El core
  no conoce las áreas concretas (la única excepción es
  `core/composition/app_area_registry.py` que itera el paquete
  `areas/` por convención).
- Modificadores offline (XML/SD) son **idempotentes** — aplicar dos
  veces no duplica instancias.
- **Singleton + single-tenant**: `ProgressTracker`, `LogBuffer`,
  `AppState` no se persisten entre reinicios.

---

## 7. Cómo añadir un área nueva

El shell SPA y el core **no se tocan** al añadir un área. Solo se
crea la carpeta `areas/<area_id>/` y se registra en config.

### Paso 1 — Crear la estructura

```text
areas/<area_id>/
├── __init__.py          # AREA_SPEC + register(engine)
├── frontend/
│   ├── manifest.py      # mismo shape que el .js
│   ├── manifest.js      # componentes + viewLabels
│   └── components/      # vistas Vue 3 ESM (sin build step)
├── functions/           # FunctionBase con HMI
├── application/         # use cases
├── domain/              # modelos puros
├── data/                # data_<entidad>.py
└── infrastructure/      # parsers, sd, xml, tia, cache
```

### Paso 2 — Definir el `AREA_SPEC`

En `areas/<area>/__init__.py`, dataclass frozen declarada en
`core/composition/app_area_registry.py`. Aquí se conectan los hooks:

- `contributes_frontend_manifest=build_manifest`
- `contributes_routers=build_routers`
- `contributes_mcp_tools=build_tools`
- `contributes_tia_commands=register_extra_commands`

La función `register(engine)` se invoca al arrancar y crea los FBs del
área en el engine.

### Paso 3 — Crear el manifest

`frontend/manifest.py` y `frontend/manifest.js` deben tener el mismo
shape. Lista de vistas del área:

```python
{
  "components": {
    "views": {
      "landing": "AreaLanding",
      "definicion": "DefinicionProgramacion",
      "dispositivos": "Dispositivos",
      ...
    },
    "viewLabels": {                  # opcional, fallback a capitalize(key)
      "landing": "Inicio",
      "definicion": "Definición programación",
      ...
    }
  }
}
```

El shell lee este manifest automáticamente vía `area-loader.js` al
entrar al área y monta sus vistas en `ShellSidebar`.

### Paso 4 — Implementar los componentes específicos

Una vista por cada key del manifest. Vue 3 ESM, sin build step:

- Estado global en `store.js` (singleton `reactive`).
- Fetch puro en `api.js` (devuelve `{ ok, status, data }`).
- Estilos: solo tokens semánticos del tema (recompilar Tailwind tras
  añadir clases nuevas: `run_tailwind.bat`).

### Paso 5 — Registrar el área

Bloque declarativo bajo `departments.<id>` en `config/config.json`.
El engine lo descubre al arrancar.

### Paso 6 — Validar

- El shell lee `/api/v1/areas`, `Welcome` muestra la card del nuevo
  área automáticamente.
- Al pulsarla, `area-loader.js` carga su manifest y monta sus vistas.
- Smoke `_local_demo/smoke_ui_nav.py` valida la estructura sin
  navegador.

---

## 8. Smokes y validación

Smokes en `_local_demo/` (sin navegador, sin TIA Portal):

| Smoke | Qué valida |
|---|---|
| `smoke_main_lifecycle.py` | Flujo base: setup_logging + ConfigManager + tia-loop + wrapper + engine + Flask + stop limpio. |
| `smoke_main_loop_fb.py` | Main loop ejecuta FunctionBlocks reales del área. |
| `smoke_progress_dynamic.py` | ProgressTracker con 3 FBs dummy (4 / 6 / 10 pasos) emite eventos al bus SSE. |
| `smoke_e2e_full.py` | End-to-end: engine + bus + FB + endpoints REST + SSE. |
| `smoke_ui_nav.py` | Estructura del shell SPA sin navegador: manifest shape, plcpanelview en core, sin archivos obsoletos. |

Cómo correrlos:

```cmd
python _local_demo/smoke_main_lifecycle.py
python _local_demo/smoke_progress_dynamic.py
python _local_demo/smoke_ui_nav.py
```

Cada uno imprime `SMOKE <name>: PASS` si todo va bien.

> **Nota**: los tests pytest en `tests/` no están alineados con el
> estado actual del refactor de áreas. Pendiente de migración
> (Fase 2). Para validar la app hoy, usa los smokes.

---

## 9. Build del .exe

```cmd
python build_exe.py
```

El script:

1. Verifica PyInstaller.
2. Localiza el `.pyd` de Siemens en el venv (`importlib.util.find_spec`).
3. Lo copia a un `tempfile.mkdtemp()` con nombre canónico
   (`siemens_tia_scripting.pyd`).
4. Invoca `PyInstaller --onefile --add-data <pyd>`.
5. Limpia el staging en `finally`.

**Artefacto**: `dist\zc_automation_suite.exe` (un único binario, modo
windowed sin consola). Doble clic → bandeja.

**Restricciones del build**:

- El `.pyd` y todas las `.dll` se stagean en un `tempfile.mkdtemp()`,
  **nunca** en la raíz del repo. Tras el build no queda ningún
  `.pyd`/`.dll`/`.xml` en el working tree.
- UPX excluido para `*.dll` y `*.pyd` (UPX corrompe los ensamblados
  .NET nativos de Siemens).
- El binario es para la UX de operario (bandeja + web). El modo dev
  (`python main.py --web`) se usa para desarrollo local.

---

## 10. Convenciones operativas

### Paths del proyecto

- **Config del usuario**: `config/config.json` (eager-loaded al
  arrancar). Resolución:
  1. `$ZC_CONFIG_DIR/config.json` (override)
  2. Modo frozen: `<exe_dir>/config/config.json`
  3. Modo dev: `<cwd>/config/config.json`
  4. Fallback readonly al bundleado

  Política: **el usuario gana siempre** — no sobreescribimos un
  `config.json` existente. El operario borra el archivo a mano si
  quiere resetear al bundleado.

- **Workdirs de export/modificación**: `.build_cache/<área>/<contexto>/{exports,modified,preview}`.
  Convención de la app, no config del proyecto.

- **CSS**: `tailwind.config.js` escanea `./areas/**/frontend/**/*.js`
  en `content`. Tras añadir clases nuevas en cualquier `.js` de la
  SPA, **recompilar CSS**:

  ```cmd
  run_tailwind.bat
  ```

### SPA Vue 3 sin build step

- **Sin build step**: el navegador carga módulos ESM directamente
  desde `/js/`. No usar `import.meta`, no usar TypeScript.
- **Estado global** en `store.js` con `reactive({...})`.
- **Fetch puro** en `api.js`: cada función devuelve `{ ok, status, data }`.
- **Polling** vía `setInterval` en `main.js` (no en componentes).
- **ProgressIndicator** es el ÚNICO componente de feedback de
  operaciones largas. Va anclado al final del sidebar.

**Regla firme**: nunca usar markdown style `` `X` `` (backticks
dobles) dentro de comentarios HTML de un template literal de JS.
Usar `'X'` o nada — los backticks cierran el string prematuramente.

### Tema "Industrial Claro"

- Superficies: `bg-surface` / `bg-surface-raised` / `bg-surface-sunken`.
- Bordes: `border-line` / `border-line-strong` (gris oscuro para focus).
- Texto: `text-ink` / `text-ink-muted` / `text-ink-inverse`.
- Acento: `bg-accent` (azul marino Siemens `rgb(0 52 102)`) /
  `bg-accent-hover` / `bg-accent-subtle`.
- Status: `text-green-600` (ok), `text-red-600` (error),
  `text-amber-600` (warning).

### Logger

- Logger jerárquico: `zc` (raíz), `zc.main`, `zc.web`, etc.
- Un solo archivo `zc.log` para toda la aplicación.
- En `%LocalAppData%\zc-automation-suite\logs\` por defecto.

---

## Licencia

MIT. Ver [LICENSE](LICENSE).
