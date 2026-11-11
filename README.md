# zc-automation-suite

Automatizacion IT/OT para proyectos de Siemens TIA Portal. Lee el Excel
maestro, exporta del PLC los bloques y tablas afectados, calcula las
diferencias y las muestra. Si el operario lo aprueba, modifica los ficheros
exportados offline y los reimporta en TIA dentro de una transaccion con
rollback.

App de escritorio: Windows, un solo operario, se empaqueta en un `.exe` con
PyInstaller.

## Estado

La aplicacion se esta reescribiendo con una arquitectura simple: un unico
hilo dueño de TIA Portal, trabajos que se ejecutan enteros, eventos SSE y
areas registradas en una lista explicita.

El detalle de la arquitectura, los contratos y las reglas esta en
[AGENTS.md](AGENTS.md).

## Requisitos

- Python 3.12-3.14
- Node.js 22+ (solo para el frontend)
- La wheel oficial de Siemens `siemens_tia_scripting` (no esta en PyPI). Ver
  [docs/INSTALAR.md](docs/INSTALAR.md).

## Instalacion

```bash
pip install -e ".[dev]"
cd frontend && npm install && cd ..
```

## Comandos

| Tarea | Comando |
|---|---|
| Tests backend | `python -m pytest tests/ -v` |
| Lint | `python -m ruff check .` |
| Dev | `python iniciar.py` |
| Tests frontend | `npm test` (en `frontend/`) |
| Build frontend | `npm run build` (en `frontend/`) |
| Empaquetar .exe | `python build_exe.py` |

## Arrancar la app

### Desarrollo: backend + Vite

```bash
python iniciar.py
```

Abre `http://localhost:5173/`. Vite sirve la SPA y redirige `/api` al backend
(`127.0.0.1:9484`). El backend se levanta en modo desarrollo, que es lo que
permite el origen de Vite en las peticiones `POST`.

### Build servido por Flask (como ira en el `.exe`)

```bash
cd frontend && npm run build && cd ..
python iniciar.py --build
```

Abre `http://127.0.0.1:9484/`. Flask sirve `frontend/dist` y el stream de
eventos. Es exactamente lo que hace el `.exe` empaquetado.

### Modo demo

Anade `?demo=1` a la URL: `http://localhost:5173/?demo=1` o
`http://127.0.0.1:9484/?demo=1`. No se abre el stream de eventos, se
simulan: sirve para ver el shell (barra superior, faceplate de progreso y
consola de trazabilidad) sin TIA Portal ni backend.

## Estructura

```
backend/zc_suite/   nucleo, operaciones TIA, areas
frontend/           SPA Vue 3 + Vite + Tailwind v4
tests/              pytest
docs/               instalacion y guias
config/config.json  plantilla de configuracion
```

## Documentacion

- [docs/INSTALAR.md](docs/INSTALAR.md) — que hace falta y como se instala.
- [docs/NUEVA_AREA.md](docs/NUEVA_AREA.md) — como se anade un area.
- [docs/NUEVO_DISPOSITIVO.md](docs/NUEVO_DISPOSITIVO.md) — como se anade un tipo
  de dispositivo.
- [docs/PROBLEMAS.md](docs/PROBLEMAS.md) — problemas frecuentes.

## Licencia

Ver [LICENSE](LICENSE).
