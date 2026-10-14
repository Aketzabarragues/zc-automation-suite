# ZC Automation Suite

Capa de integración IT/OT para inspección y automatización de proyectos en **Siemens TIA Portal** mediante el SDK oficial **TIA Scripting Python**.

![Python 3.12+](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-yellow) ![TIA Portal](https://img.shields.io/badge/TIA%20Portal-V15.1%2B-green) ![Plataforma](https://img.shields.io/badge/plataforma-Windows%20%7C%20single--tenant-blue)

---

## 1. Qué hace

- Lee un `.xlsm` maestro con dispositivos, parámetros, `N_MAX` y procesos.
- Extrae los `.s7dcl`/`.s7res` de los DBs del PLC a `exports/` (formato SimaticSD).
- Modifica offline los comentarios de slots `PReal`/`PInt`/`Alarmas` con asignación determinista de IDs MLC (`MLC_<5 hex>`).
- Re-importa los archivos modificados al PLC en su jerarquía original (TIA Portal hace match UPDATE por nombre y ruta).
- Genera previews (diff de cambios) antes de aplicar nada.
- Aplica las operaciones transaccionalmente con `start_transaction`/`end_transaction` (rollback atómico si algo falla).

## 2. Quick start (Windows + PowerShell)

```powershell
git clone https://github.com/Aketzabarragues/zc-automation-suite.git
cd zc-automation-suite
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
pip install vendor/install/siemens_tia_scripting-1.4.3-cp3XX-cp3XX-win_amd64.whl
python main.py
```

Abre `http://127.0.0.1:9484/` (bandeja → Iniciar web). Para QA sin TIA Portal, `?demo=1`.

## 3. Documentación

| Quiero... | Ir a |
|---|---|
| Instalar y arrancar (requisitos, venv, wheel de Siemens, primer test) | [`docs/ONBOARDING.md`](docs/ONBOARDING.md) |
| Añadir un dispositivo nuevo al catálogo | [`docs/HOWTO_ADD_DEVICE.md`](docs/HOWTO_ADD_DEVICE.md) |
| Añadir un área nueva (Bounded Context) | [`docs/HOWTO_CREATE_AREA.md`](docs/HOWTO_CREATE_AREA.md) |
| Añadir un Function Block (state machine con progress) | [`docs/HOWTO_CREATE_FB.md`](docs/HOWTO_CREATE_FB.md) |
| Diagnosticar un problema típico | [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) |
| Reglas para contribuir (commits, scope, smoke en vivo) | [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| Reglas arquitectónicas detalladas (worker OT, FB template, etc.) | [`AGENTS.md`](AGENTS.md) |
| Reglas críticas cortas (siempre cargadas) | [`.clinerules`](.clinerules) |
| Patrón de migración use case → FB | [`docs/MIGRATION_PLAYBOOK.md`](docs/MIGRATION_PLAYBOOK.md) |

## 4. Stack y arquitectura

| Capa | Tecnología | Por qué |
|---|---|---|
| Backend | Python 3.12+, Flask (sync) | Tipado estático, sync encaja con la naturaleza I/O-bound del worker OT |
| Worker OT | Hilo persistente TIA Scripting Python (COM/.NET) + cola FIFO + 6 estados | TIA Openness API no es thread-safe con los RCW; un hilo por sesion evita crashes |
| Excel | `.xlsm` maestro + `excel_cache.py` + parsers por dominio | El Excel es la fuente de verdad de dispositivos, parámetros y `N_MAX` |
| SPA | Vue 3 ESM sin build step, Tailwind v4 offline | Cero CDN = deploy offline = no se rompe sin red |
| Empaquetado | PyInstaller + `tempfile.mkdtemp()` para `.pyd`/`.dll` de Siemens | `.exe` único portable en máquinas Windows con TIA Portal |
| MCP | (planificado, no implementado aún) | Integración con Cline / Claude Desktop |

El `core/` contiene todo transversal sin saber de áreas. Cada `areas/<area>/` es un Bounded Context autocontenido que se autodescribe vía `AreaSpec` (ver `AGENTS.md`).

## 5. Atajos de desarrollo

| Tarea | Comando |
|---|---|
| Tests | `python -m pytest tests/ -q` |
| Servidor dev (web) | `python main.py --web 127.0.0.1:9484` |
| Launcher bandeja | `python main.py` (o `run_app.bat`) |
| Recompilar CSS | `tailwindcss-extra.exe -i core/web_server/static/src/input.css -o core/web_server/static/styles.css --minify` (o `run_tailwind.bat`) |
| Empaquetar `.exe` | `python build_exe.py` |
| Test E2E manual | abrir `http://127.0.0.1:9484/` (demo: `?demo=1`) |

## 6. Licencia

MIT. Copyright (c) 2026 Aketzabarragues. Ver [`LICENSE`](LICENSE).
