# zc-plc-suite

Plataforma de integración IT/OT para automatización e inspección de proyectos TIA Portal, construida con arquitectura **PLC-style (IEC 61131-3)**: Function Blocks con `nStep` discreto, Data Blocks como memoria compartida, y un HMI pasivo subscrito por SSE.

## Estado

**Greenfield en rama `greenfield/iec-61131-3`.** El legacy operativo vive en `main` y se mantiene hasta Fase 4 (paridad funcional en alimentación). El legacy completo también está preservado en `legacy_backup/` en esta rama, para referencia.

El plan completo de construcción (Fases 0-5, criterios de cierre, decisiones tomadas) está en [`PLC_IE_61131_GREENFIELD.md`](./PLC_IE_61131_GREENFIELD.md) en la raíz de la rama.

## Stack

- **Backend:** Python 3.12-3.14, FastAPI, asyncio, worker persistente vía subproceso.
- **SDK TIA:** `siemens_tia_scripting` V1.2.1. **Cargado lazy**, único punto de import: `core/worker/worker_tia.py`.
- **Frontend:** Vue 3 ESM sin build step, Tailwind v4 compilado offline, tema "Industrial Claro" con acento `rgb(0, 52, 102)`.
- **Empaquetado:** PyInstaller, `main_tray.py` con icono de bandeja (único entry point).

## Arquitectura

```
SPA (Vue 3, HMI pasivo)
   │  1 EventSource SSE (push) + POST /fb/{name}/start
   ▼
FastAPI (capa IT)
   │  Engine: registro de FBs/DBs, loop 100ms, bus SSE
   │  Routers genéricos (core) + routers específicos (áreas)
   ▼
WorkerBridge (lock-protegido, shutdown incluido)
   │  Fachada con lock desde el primer commit
   ▼
Worker persistente (subproceso aislado)
   │  Único importador de siemens_tia_scripting
   ▼
TIA Portal (COM / .NET CLR)
```

- **Core (trasversal):** Engine + FB_Base + DB_EstadoConexion + WorkerBridge. Lo que TODAS las áreas necesitan.
- **Áreas (Bounded Contexts):** cada una trae sus propios DBs y FBs. Se registran en el Engine al arrancar la app.
- **HMI:** `usePlc()` composable que abre 1 EventSource, expone DBs/FBs como reactivos, `startFb(name, params)` dispara FBs. **Sin polling.**

Ver [`.clinerules`](./.clinerules) (reglas operativas condensadas) y [`AGENTS.md`](./AGENTS.md) (guía de extensión).

## Referencia intelectual (en `legacy_backup/` y en `main`)

- `legacy_backup/PLC_IE_61131_GREENFIELD.md` (copia del plan en raíz) y `legacy_backup/_plan/` — los `_plan/` originales con las auditorías previas.
- `legacy_backup/_plan/14_post_worker_persistent_audit.md` — auditoría del worker persistente que descubrió las 3 lecciones del §0.4 del plan (X1: consumir todos los campos del backend, X2: shutdown handler, X3: race conditions en reconnect).
- `legacy_backup/_plan/17_frontend_simplification_audit.md` — auditoría del frontend que justificó el cambio de polling a SSE.

## Quick start (desarrollo)

```bash
python -m venv .venv
.venv\Scripts\activate              # Windows
pip install -r requirements.txt -r requirements-dev.txt
python main_tray.py                 # único entry point
```

## Tests

```bash
pytest tests/ -v
```

## Licencia

Ver [LICENSE](./LICENSE).
