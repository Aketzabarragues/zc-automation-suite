# ZC Automation Suite

> Capa de integración IT/OT para automatización e inspección de proyectos en **Siemens TIA Portal** mediante el SDK oficial **TIA Scripting Python (SIOS 109742322)**.

![Python 3.12+](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-yellow) ![TIA Portal](https://img.shields.io/badge/TIA%20Portal-V15.1%2B-green) ![Plataforma](https://img.shields.io/badge/plataforma-Windows%20%7C%20single--tenant-blue) ![Licencia](https://img.shields.io/badge/licencia-MIT-lightgrey)

---

## Tabla de contenidos

**Operario**
1. [Qué es y qué hace](#1-qué-es-y-qué-hace)
2. [Requisitos e instalación](#2-requisitos-e-instalación)
3. [Cómo se arranca](#3-cómo-se-arranca)
4. [Cómo se usa (topbar y paneles)](#4-cómo-se-usa-topbar-y-paneles)
5. [Solución de problemas](#5-solución-de-problemas)

**Desarrollador**
6. [Build y despliegue](#6-build-y-despliegue)
7. [Tests](#7-tests)
8. [Arquitectura](#8-arquitectura)
9. [Cómo contribuir](#9-cómo-contribuir)
10. [Licencia](#10-licencia)

---

## 1. Qué es y qué hace

Una capa de integración que conecta Python (servidor web FastAPI + cliente MCP/LLM) con **TIA Portal Openness** a través del SDK oficial `siemens_tia_scripting`. Pensada para un único operario por puesto (single-tenant).

Lo que hace por ti:

- Lee el Excel corporativo, calcula diffs contra el PLC y aplica los cambios en **una sola transacción TIA atómica**. Si algo falla a mitad, todo se revierte.
- Mantiene TIA Portal conectado a un **subproceso persistente**: el operario decide cuándo conectar y cuándo desconectar desde el topbar; no se paga el coste de arranque del wrapper nativo en cada operación.
- Sirve los mismos flujos desde dos adaptadores paralelos: **SPA web** (navegador, para el operario) y **FastMCP** (Cline / Claude Desktop, para un LLM).
- Aplica **rollback atómico** en lotes transaccionales (`start_transaction` / `end_transaction(rollback=True)`).
- Modificadores offline XML/SD **idempotentes** — aplicar dos veces el mismo cambio no duplica instancias.

---

## 2. Requisitos e instalación

| Componente | Requisito |
|---|---|
| Sistema operativo | Windows 10 / 11 / Server (64-bit). Solo Windows: TIA Openness requiere COM. |
| Python | **3.12.x, 3.13.x o 3.14.x** (64-bit). Sin soporte para 3.11 ni anteriores. |
| TIA Portal | V15.1 o superior con Openness instalado. |
| Permisos Windows | Tu usuario debe pertenecer al grupo `Siemens TIA Openness` (gestionado por el `Openness Security Dialog` de Siemens). |
| Librería TIA Scripting | Wheel oficial de Siemens: `siemens_tia_scripting-*.whl`. |

Instalación rápida:

```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install siemens_tia_scripting-*.whl

python -c "import siemens_tia_scripting; print('OK')"
```

Las dependencias de bandeja (`pystray`, `Pillow`) vienen en `requirements.txt` y solo son necesarias si vas a usar `main_tray.py` o el ejecutable empaquetado.

---

## 3. Cómo se arranca

Cuatro formas, según el flujo de trabajo:

### 3.1 Bandeja del sistema + web (operario en producción)

```cmd
run_tray.bat
```

Doble clic sobre `run_tray.bat` o `pythonw main_tray.py`. Aparece un icono en la bandeja con menú: **Iniciar web**, **Parar web**, **Abrir panel web**, **Estado**, **Salir**.

### 3.2 Web directo (sin bandeja, dev)

```cmd
python main.py --web
:: por defecto http://127.0.0.1:8000
:: opcional: python main.py --web 0.0.0.0:5000
```

Levanta FastAPI + Uvicorn y sirve la SPA. Útil en desarrollo para tener logs en consola.

### 3.3 Servidor MCP para clientes LLM (Cline, Claude Desktop)

```cmd
python main.py --mcp
:: o sin flag, es el default
```

Arranca FastMCP sobre STDIN/STDOUT. Backend headless puro (sin TUI). El cliente MCP (Cline, Claude Desktop, etc.) envía invocaciones de tools contra este proceso.

### 3.4 Ejecutable empaquetado (producción, sin Python instalado)

Doble clic sobre `dist\zc_automation_suite.exe` (ver [Build y despliegue](#6-build-y-despliegue)). Icono en la bandeja, mismo menú que 3.1.

### 3.5 Worker OT directo (solo debug)

```cmd
echo {"command":"list_plcs","args":{}} | python main.py --worker
```

Este modo lanza un subproceso OT **1-shot** (un solo comando, el subproceso muere). **No se usa en producción** — el gateway en modo web usa el modo persistente (`--worker-persistent`) que se invoca internamente. Útil para depurar el motor OT directamente.

---

## 4. Cómo se usa (topbar y paneles)

Al abrir el panel web en `http://127.0.0.1:8000` ves:

- **Topbar** — Indicador del estado del worker TIA (gris = idle, ámbar = connecting, verde = connected) y dos botones:
  - **Conectar**: lanza un `attach_portal` contra el TIA Portal que ya tienes abierto. Solo funciona si TIA Portal está ejecutándose con un proyecto cargado. Devuelve el PID del proceso TIA al que se ha conectado (visible en el endpoint `GET /api/v1/tia/connection`).
  - **Desconectar**: hace `detach_portal`. **El worker OT sigue vivo** en estado `idle`, listo para un próximo Conectar sin pagar el coste de arrancar de nuevo el subproceso.
- **Sidebar** — Lista de áreas operativas. Hoy: **Alimentación** (departamento con N_MAX + dispositivos + procesos). Al entrar en un área, sus componentes Vue se cargan dinámicamente.
- **Panel principal** — Depende del área. Para Alimentación: panel de Dispositivos, panel de Procesos, tabs de Sync (preview / commit), vista de Excel, etc.
- **Panel de progreso** — Aparece en operaciones >500 ms. Stages con `pending` / `running` / `done` / `error`.
- **Panel de logs** — Consola con los logs del backend. Polling a 1s.

### Flujo típico (sync de dispositivos desde Excel)

1. Operario carga el Excel corporativo desde la SPA (`POST /api/v1/excel/upload`).
2. Pulsa **Conectar** en el topbar. El indicador pasa a verde.
3. Selecciona el PLC en la SPA.
4. Entra al panel de Dispositivos → Sync → **Preview**: la suite calcula el diff (N_MAX + renombres + devices add/remove) **sin tocar TIA**. Muestra `agregados`, `eliminados`, `renombrados` y los `N_MAX` que cambiarán.
5. Si el preview le encaja, pulsa **Commit**: la suite aplica N_MAX + renombres + devices en **una sola transacción TIA**. Si algo falla, todo se revierte automáticamente.
6. Pulsa **Desconectar** cuando termine la sesión.

---

## 5. Solución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| El botón Conectar se queda en ámbar más de 60s | TIA Portal no responde, no está abierto, o no tiene proyecto cargado. | Abre TIA Portal con un proyecto, vuelve a pulsar Conectar. |
| `attach_portal retorno None. ¿Está TIA Portal abierto?` | TIA Portal no está abierto, o tu usuario no pertenece al grupo `Siemens TIA Openness`. | Abre TIA Portal con un proyecto. Verifica permisos en `Administración de equipos → Usuarios → Siemens TIA Openness`. |
| `Timeout tras Ns ejecutando el comando 'X'` | El worker OT no responde (diálogo modal abierto en TIA, o TIA colgado). | Cierra cualquier diálogo modal en TIA Portal. El subproceso se cierra automáticamente. Si el timeout es muy corto, súbelo con la env var `ZC_GATEWAY_TIMEOUT` (default 300s). |
| La SPA no carga | El web server no está arrancado, o la URL es otra. | Lanza el web server con `python main.py --web` o desde el menú de la bandeja. Verifica `http://127.0.0.1:8000`. |
| Tests fallan con `ImportError: cannot import name 'X' from 'core.X'` | Algún módulo quedó con un import legacy. | Busca el import roto y actualízalo a la ruta actual (`core.application.X`, `core.infrastructure.X`, `areas.<área>.X`). |

Diagnóstico avanzado:

- **Logs del worker** (`worker_openness.log`): trazas C++/COM del wrapper nativo de Siemens. Está junto al ejecutable en modo frozen, o en la raíz del repo en dev.
- **Logs del launcher** (`zc_tray.log`): actividad del tray + arranque del web server. En `%LocalAppData%\zc-automation-suite\logs\` por defecto.
- **Logs del web server**: aparecen en la consola donde lanzaste `python main.py --web`, o en `zc_tray.log` si arrancaste desde la bandeja.
- **Panel de logs en la SPA**: vista rápida de lo que está pasando en el backend (polling 1s, no para diagnóstico fino).

Para arquitectura, Bounded Contexts, IPC, AreaSpec, COMMAND_REGISTRY, configuración y decisiones de diseño, consulta **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

---

## 6. Build y despliegue

```cmd
.venv\Scripts\activate
python build_exe.py
```

El script:

1. Verifica PyInstaller.
2. Localiza el `.pyd` de Siemens en el venv (`importlib.util.find_spec`).
3. Lo copia a un `tempfile.mkdtemp()` con nombre canónico (`siemens_tia_scripting.pyd`).
4. Invoca `PyInstaller --onefile --add-data <pyd>`.
5. Limpia el staging en `finally`.

**Artefacto**: `dist\zc_automation_suite.exe` (un único binario, modo windowed sin consola). Doble clic → bandeja.

**Restricciones del build**:

- El `.pyd` y todas las `.dll` se stagean en un `tempfile.mkdtemp()`, **nunca** en la raíz del repo. Tras el build no queda ningún `.pyd`/`.dll`/`.xml` en el working tree.
- UPX excluido para `*.dll` y `*.pyd` (UPX corrompe los ensamblados .NET nativos de Siemens).
- Modo FastMCP STDIO (`--mcp`) **no se incluye** en el `.exe` — queda como modo dev (`python main.py --mcp`). El `.exe` es para la UX de operario (bandeja + web).

---

## 7. Tests

```cmd
pip install pytest
python -m pytest tests/ -q
```

**Estado actual: 840 tests** (837 ok + 3 skipped). Deben pasar todos antes de commitear.

Convenciones:

- **Backend**: mockear el gateway con `MagicMock(spec=TIAProcessGateway)`. Para `ProgressTracker`, instanciar uno limpio (`ProgressTracker()`) y pasarlo al use case (no se mockea).
- **Frontend**: sin tests automatizados (SPA ESM sin build step). QA manual con el servidor de pruebas.
- **Naming**: `tests/test_<modulo>.py` o `tests/test_area_<área>_<feature>.py`.

---

## 8. Arquitectura

> A partir de aquí el documento asume público desarrollador.
> Para arquitectura, Bounded Contexts, IPC, AreaSpec, COMMAND_REGISTRY, configuración y decisiones de diseño, consulta **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

Reglas de oro (resumen de `.clinerules`; documento completo en el archivo):

- `siemens_tia_scripting` SOLO se importa en `core/infrastructure/tia/worker_tia.py`. Cualquier intento de importarlo en otra capa es un bug crítico.
- Las áreas **no importan entre sí**; comparten vía `core/`. El core no conoce las áreas concretas (la única excepción es `core/application/area_registry.py` que itera el paquete `areas/` por convención).
- Modificadores offline (XML/SD) son **idempotentes** — aplicar dos veces no duplica instancias.
- **Singleton + single-tenant**: `ProgressTracker`, `LogBuffer`, `AppState` no se persisten entre reinicios. Si llega un nuevo `begin()` con uno activo, OVERWRITE + warning.
- Tras añadir clases Tailwind nuevas, **recompilar CSS**: `run_tailwind.bat` (o `tailwindcss-extra.exe -i interfaces/web_server/static/src/input.css -o interfaces/web_server/static/styles.css --minify`).
- **Sin CDN**: la SPA se sirve en local para funcionar en redes industriales aisladas (OT). Sin daisyUI, sin CSS externo. Tema "Industrial Claro" con tokens semánticos (`bg-surface*`, `text-ink*`, `bg-accent`, `border-line`).

---

## 9. Cómo contribuir

1. Lee **`.clinerules`** (reglas arquitectónicas críticas) y **`AGENTS.md`** (guía de extensión paso a paso: cómo añadir una operación OT, un endpoint REST, una vista SPA, una nueva área, un nuevo tipo de dispositivo, un comando MCP).
2. **Operación OT genérica** → edita `core/infrastructure/tia/worker_tia.py` y `COMMAND_REGISTRY`. **Específica de un área** → edita `areas/<área>/infrastructure/tia/extra_commands.py` con su `register(registry)` (el `command_loader` lo descubre al arrancar).
3. Si modificas un **caso de uso** (`core/application/` o `areas/<área>/application/`), respeta el contrato de DI: el use case recibe gateway, config_manager y (si aplica) state/progress por constructor. No usa Singleton/global.
4. Si modificas el **dominio**, respeta las restricciones: sin `siemens_tia_scripting`, sin `Any` en atributos, sin openpyxl.
5. Tras añadir **clases Tailwind nuevas** en cualquier `.js` de `static/js/`, recompila CSS (`.clinerules §9`).
6. Ejecuta `python -m pytest tests/ -q` antes de commitear — 840 tests deben pasar.
7. Una sola rama (`main`). No reintroducir la rama `Main` huérfana.

---

## 10. Licencia

MIT. Ver [LICENSE](LICENSE).

```
MIT License
Copyright (c) 2026 Aketzabarragues
```
