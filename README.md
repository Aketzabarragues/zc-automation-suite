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

## Empaquetar el ejecutable

```bash
pip install -e ".[build]"
python build_exe.py
```

El script hace todo el trabajo: comprueba que estan Python, PyInstaller, la
wheel de Siemens y node; compila el frontend (`npm ci` y `npm run build`); y
genera `dist/zc_automation_suite.exe`, un unico fichero.

Si falta algo, el build para con un mensaje que dice que. En Windows tambien
se puede lanzar con `run_build.bat`.

El `.exe` no necesita Python ni Node: la SPA va dentro. Los binarios de
Siemens (el `.pyd` y las `.dll` del SDK de Openness) tambien van dentro, en
la raiz del bundle: salen de la wheel instalada, de la misma carpeta donde
pip deja el `.pyd`.

El `.exe` se abre con doble click: arranca con la bandeja y sirve la SPA en
`http://127.0.0.1:9484/`. El navegador no se abre solo: se usa "Abrir panel
web" del menu de la bandeja.

El log va a `logs/zc.log`, junto al ejecutable (rota a los 10 MB y guarda 3
copias). Ahi queda la trazabilidad completa: el arranque, cada trabajo con
sus pasos y como acaba, y las excepciones no controladas.

## Llevar el ejecutable a otra maquina

El `.exe` es un fichero: se copia a donde sea y se ejecuta. No hay
instalador.

La maquina destino necesita:

| Requisito | Para que |
|---|---|
| Windows 10 u 11 | la app es de escritorio |
| TIA Portal instalado | sin TIA no hay nada que automatizar |
| TIA Portal Openness instalado | el API con el que la app habla con TIA |
| El usuario en el grupo **Siemens TIA Portal Openness** | TIA rechaza la conexion si el usuario no esta en el |

Python y Node **no** hacen falta: van dentro del `.exe`.

Sin TIA abierto, la app arranca igual: se ve la SPA, se puede subir el
Excel maestro y se trabaja con la app en modo desconectado.

Junto al `.exe` la app va creando sus datos: `config/` con el
`config.json` del operario, `excel/` con la copia del Excel maestro,
`logs/` con el log y `.build_cache/` con lo que va exportando de TIA. Nada
de eso se guarda dentro del `.exe`: los datos del operario se pueden copiar
de una maquina a otra sin tocar el ejecutable.

Para llevar los datos a otra maquina, copia la carpeta del `.exe` entera
(o solo `config/` y `excel/`).

## Estructura

```
backend/zc_suite/
  errores.py  el contrato de errores de la app
  nucleo/       app/ (arranque, config, log, bandeja), web/ (Flask y rutas),
                tia/ (hilo, Job, transaccion), funciones/ (un trabajo por fichero)
  tia_ops/      operaciones contra TIA Portal
  simatic/      ml/ (SimaticML), sd/ (SimaticSD)
  areas/        areas de negocio; el nucleo no las importa
frontend/src/
  nucleo/       el shell: api, eventos, componentes, vistas y stores
  areas/        un area por carpeta: sus vistas y sus stores
tests/          misma estructura que backend/zc_suite
scripts/smoke/  smokes contra TIA real (se lanzan a mano)
config/config.json  plantilla de configuracion
```

## Documentacion

- [docs/INSTALAR.md](docs/INSTALAR.md) — que hace falta y como se instala.
- [docs/NUEVA_AREA.md](docs/NUEVA_AREA.md) — como se anade un area.
- [docs/NUEVO_DISPOSITIVO.md](docs/NUEVO_DISPOSITIVO.md) — como se anade un tipo
  de dispositivo.
- [docs/MAPA_FB.md](docs/MAPA_FB.md) — donde vive ahora cada FB de la app
  anterior, y como se crea un trabajo nuevo.
- [docs/PROBLEMAS.md](docs/PROBLEMAS.md) — problemas frecuentes.
- [docs/FLUJOS_ALIMENTACION.md](docs/FLUJOS_ALIMENTACION.md) — los ocho flujos de
  la app original, paso a paso, y como hay que rehacerlos.
- [docs/referencia_ui/REFERENCIA_UI.md](docs/referencia_ui/REFERENCIA_UI.md) — las
  capturas y la especificacion de la app original: la reescritura replica esas
  pantallas.

## Licencia

Ver [LICENSE](LICENSE).
