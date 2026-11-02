# HOWTO — Crear un Function Block (FB) nuevo

> Audiencia: tecnico que ha leido `core/composition/plc_function_base.py`
> y conoce el patron `nStep` con zonas 0/1/2/3. Esta guia es una
> **replica standalone** con un ejemplo end-to-end; no reemplaza
> la lectura del base ni de `MIGRATION_PLAYBOOK.md`.

## 0. Modelo de ejecucion

```
HMI --> pulsador --> OB1 --> FB --> WORKER (TIA)
```

- **OB1** = el dispatcher = `Engine` (`core/composition/plc_engine.py`):
  cola de trabajos + hilo dedicado (`plc-ob1`) que ejecuta cada FB
  completo con `fb.execute(**params)` (sync, sin event loop).
- **WORKER** = `core/infrastructure/tia/tia_loop.py`: hilo dedicado de TIA.
  El FB le habla con `tia_client.submit_and_wait(comando, args, timeout=T)`,
  que es **bloqueante a proposito**: el FB corre en el hilo del OB1, sin
  event loop, asi que puede esperar al worker TIA sin bloquear nada mas.

API del dispatcher (`core/composition/plc_engine.py`):

| Metodo | Que hace |
|---|---|
| `engine.submit(nombre_fb, **params) -> str` | Encola el trabajo y devuelve el `job_id`. Lanza `FBBusyError` si el FB no existe o ya tiene un trabajo en curso. |
| `engine.cancel_job(job_id, reason)` | Pide la cancelacion cooperativa del trabajo en curso. |
| `engine.get_job(job_id)` | Job por id (`None` si no existe). |
| `engine.list_jobs()` | Todos los jobs conocidos. |
| `engine.current_job_for(nombre_fb)` | Job en curso de un FB (`None` si no hay). |
| `engine.start_ob1()` / `engine.stop_ob1()` / `engine.ob1_running()` | Ciclo de vida del hilo dispatcher. |

El router **no bloquea**: responde `202` con `{"ok": true, "job_id": "<hex>"}`.
El resultado vuelve al HMI por **push** (SSE), no en el body del response:

- evento SSE `fb_state`, payload
  `{name, nStep, is_terminal, job_id, result, error_msg}`;
- slots del `AppCache` que el FB publica en su `on_finish`.

En la SPA: `store.fbStates` guarda el estado por FB y
`waitForFbJob(jobId, fbName, timeoutMs)` (`/js/store.js`) espera al estado
terminal correlacionando el `job_id` con el `fb_state` recibido.

## 1. Cuando necesitas un FB

Si tu operacion:

- Tarda > 500 ms (el operario necesita ver progreso).
- Tiene varios pasos discretos que quieres reportar al HMI.
- Necesita cancelacion cooperativa.
- Necesita lockeo contra re-entradas concurrentes: un FB admite un
  trabajo en curso y el siguiente `submit` recibe `409`.

Un FB **no** es para operaciones instantaneas (esas van en un
endpoint Flask sincrono).

## 2. Pre-requisitos

- Leer `core/composition/plc_function_base.py` (la `FunctionBase`).
- Leer `core/composition/plc_engine.py` (el `Engine` = OB1).
- Conocer el FB de referencia: `areas/alimentacion/functions/function_excel_cargar.py`.
- Conocer el router de referencia: `areas/alimentacion/frontend/excel_router.py`.

## 3. Estructura del FB

Cada step se declara encima de su propio codigo con el decorador
`@step`. El motor (`FunctionBase`) recoge los pasos **en orden de
definicion** (que es el orden del flujo) y hace el dispatch. No hay
`run_step`, ni tabla `STAGES`, ni lista `steps=`.

```python
# Zona 0: imports + declaracion
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Any

from core.composition.fb_step import step
from core.composition.plc_function_base import FunctionBase

logger = logging.getLogger(__name__)


@dataclass
class MiCtx:
    """Estado compartido entre los steps del FB."""
    tia_client: Any
    plc_name: str


# Zona 1: declaracion estatica
class FunctionMiFB(FunctionBase):
    STEP_TIMEOUT_S = 600.0  # 10 min por step

    def __init__(self, tracker=None, tia_client=None):
        super().__init__(
            nombre="mi_fb",
            titulo="Mi operacion",
            tracker=tracker,
        )
        # Zona 0: deps inyectadas
        self._tia_client = tia_client
        # Zona 3: estado entre steps
        self._ctx: MiCtx | None = None

    # Zona 2: hooks (on_start, on_finish)
    def on_start(self, **params) -> None:
        """Validar params, abrir recursos."""
        plc_name = params.get("plc_name")
        if not plc_name:
            raise ValueError("Se requiere 'plc_name'.")
        if self._tia_client is None:
            raise RuntimeError("FunctionMiFB requiere tia_client explicito.")
        self._ctx = MiCtx(tia_client=self._tia_client, plc_name=plc_name)

    def on_finish(self, **params) -> None:
        """Vuelca self.result: lo publica el SSE fb_state y el AppCache."""
        self.result = {"status": "ok"}

    # Zona 3: los steps (uno por metodo, en orden de flujo)
    @step("Listar bloques", descripcion="Lee los bloques del PLC")
    def _stage_1_listar_bloques(self) -> str:
        """Logica del step 1. Devuelve detail (string) para el HMI.

        Es sync: el FB corre en el hilo del dispatcher del OB1, sin
        event loop. Para hablar con TIA se usa ``submit_and_wait()``,
        que es bloqueante a proposito.
        """
        resp = self._ctx.tia_client.submit_and_wait(
            "list_blocks",
            {"plc_name": self._ctx.plc_name},
            timeout=60.0,
        )
        if not resp.get("ok"):
            raise RuntimeError(resp.get("error", "list_blocks fallo"))
        bloques = resp.get("result", {}).get("blocks", [])
        self._stats["bloques"] = len(bloques)
        return f"{len(bloques)} bloques"
```

### 3.1 Regla de nombres

El **nombre visible** (el primer argumento de `@step`) es la etiqueta que
ve el operario en la barra de progreso: es texto de UI, se escribe como
una frase ("Listar bloques", "Esperar consolidación TIA") y **no se
cambia** aunque cambie la implementacion.

El **slug** (el nombre del metodo) es el `snake_case` del nombre visible:
minusculas, sin acentos, cada caracter que no sea `[a-z0-9_]` se
convierte en `_`, y los `_` repetidos se colapsan en uno. Los acronimos
van en minusculas (`DB` -> `db`, `N_MAX` -> `n_max`, `SD` -> `sd`).

El metodo se llama `_stage_<n>_<slug>`, con `<n>` correlativo 1-based:

| Nombre visible | Metodo |
|---|---|
| `Listar bloques` | `_stage_1_listar_bloques` |
| `Esperar consolidación TIA` | `_stage_2_esperar_consolidacion_tia` |
| `Componer respuesta` | `_stage_3_componer_respuesta` |

El nombre visible **no** puede repetirse dentro del mismo FB: el motor
lanza `ValueError` (el tracker seria ambiguo).

### 3.2 Que devuelve cada step

El `return` del metodo es el **detail** del step: el texto que el
operario ve en la barra de progreso y en el log. Devuelve el dato real
del step, no un "OK" generico:

```python
    @step("Validar bloques", descripcion="Comprueba el cache de bloques")
    def _stage_1_validar_bloques(self) -> str:
        if not self._ctx.bloques_cache:
            raise RuntimeError("Cache de bloques no disponible.")
        return f"Validar bloques: {len(self._ctx.bloques_cache)} bloques"
```

Si el step tiene varias salidas (por ejemplo, un caso "nada que
hacer"), cada una devuelve su propio detail: el operario tiene que
poder distinguir "no havia nada" de "fallo".

Contrato de `submit_and_wait`:
`submit_and_wait(command: str, args: dict | None = None, timeout: float = 30.0) -> dict`.
La respuesta es `{"ok": True, "result": <dict>}` o `{"ok": False, "error": "<msg>"}`.
El keyword del timeout es `timeout`.

## 4. Hooks: contrato, errores tipicos

| Hook | Cuando se llama | Errores tipicos |
|---|---|---|
| `on_start(**params)` | Una vez, antes del primer step. **Sincrono.** | Lanzar `ValueError` por params invalidos: el base lo captura y transita a `n_error`. |
| `@step(...)` handler | Una vez por step, en orden de definicion. **Sincrono.** | Lanzar `NotImplementedError` por olvidos: propaga al dev. Lanzar `Exception` operacional: el base lo silencia y transita a `n_error`. Devolver una corrutina es un error de programacion: el base lo dice explicitamente. |
| `on_finish(**params)` | Una vez, al pasar de `n_finalizar` a `n_done`. **Sincrono.** | Asignar `self.result` con el dict que se publicara por SSE `fb_state` y en los slots del AppCache. |

El entry point del dispatcher es `FunctionBase.execute(**params)`: ejecuta
el FB completo (`on_start` -> steps -> `on_finish`) y devuelve `self.result`.

## 5. Progreso: `ProgressTracker`

El base invoca el tracker automaticamente:

- `tracker.begin(operation, label, stages)` en `on_start` (via
  `_step_arrancar`).
- `tracker.start_stage(stage_id)` antes de cada `run_step`.
- `tracker.finish_stage(stage_id, detail)` despues.
- `tracker.error_stage(stage_id, detail)` si hay error.
- `tracker.finish(success=True|False)` en `n_done` o `n_error`.

Los IDs de stage vienen de los metodos marcados con `@step`: el base los
recoge en orden de definicion y usa el nombre visible como ID. El HMI los
muestra con ese `nombre`.

**Reglas operativas**:

- Emite `begin` en `on_start` (lo hace el base).
- Emite `start_stage` / `finish_stage` solo si el step tiene
  progreso INTERNO que merece ser visible. Para un step trivial
  (e.g. parsear un JSON de 50 lineas), el start/finish del stage
  ya basta.
- NO emitas `begin` / `start_stage` / `finish` en el router Flask.
  Eso es responsabilidad del FB y su `execute()`.

## 6. Router Flask que encola el FB

`areas/<area>/frontend/<mi_fb>_router.py`:

```python
from flask import Blueprint, current_app, jsonify, request

from core.composition.plc_engine import FBBusyError

bp = Blueprint("<area>_<mi_fb>", __name__, url_prefix="/api/v1/<area>/<mi_fb>")


@bp.post("/start")
def start():
    body = request.get_json(silent=True) or {}
    if not body.get("plc_name"):
        return jsonify({
            "ok": False,
            "error": "plc_name (str) es obligatorio en el body",
        }), 400

    engine = current_app.config["ENGINE"]
    if engine is None:
        return jsonify({"ok": False, "error": "Engine no disponible"}), 500
    if engine.get_fb("mi_fb") is None:
        return jsonify({
            "ok": False,
            "error": "FB 'mi_fb' no registrado en el engine",
        }), 500

    try:
        job_id = engine.submit("mi_fb", plc_name=body["plc_name"])
    except FBBusyError as exc:
        return jsonify({
            "ok": False,
            "error": (
                f"FB 'mi_fb' ya tiene un trabajo en curso. "
                f"Espera a que termine y reintenta. ({exc})"
            ),
        }), 409
    except Exception as exc:  # noqa: BLE001
        return jsonify({
            "ok": False,
            "error": f"no se pudo encolar el trabajo: {exc}",
        }), 500

    return jsonify({"ok": True, "job_id": job_id}), 202
```

Reglas:

- Lee el engine de `current_app.config["ENGINE"]`. NUNCA importes
  Singletons globales.
- Devuelve `dict` (Flask lo serializa con `jsonify`).
- Contrato HTTP: `202` encolado, `400` validacion, `409` FB ocupado,
  `500` FB no registrado / fallo al encolar.
- NO hagas poll del resultado ni lo devuelvas en el body: el resultado
  llega al HMI por SSE (`fb_state`) y por los slots del AppCache.

## 7. Tests

`tests/areas/<area>/functions/test_<mi_fb>.py`:

```python
from unittest.mock import MagicMock

from core.infrastructure.tia.tia_loop import SyncTIAClient
from areas.<area>.functions.function_<mi_fb> import FunctionMiFB


def test_<mi_fb>_happy_path():
    tia_client = MagicMock(spec=SyncTIAClient)
    fb = FunctionMiFB(tia_client=tia_client)
    result = fb.execute(plc_name="PLC_1")
    assert result == {"status": "ok"}
```

Convenciones:

- Mockear el cliente TIA con `MagicMock(spec=SyncTIAClient)`. Nunca
  mockear el worker directamente.
- `ProgressTracker()` limpio instanciado y pasado al FB (no
  mockear el tracker).
- El FB se ejecuta con `fb.execute(**params)` (sync, igual que hace el
  OB1). `execute()` devuelve `self.result`.
- 1 test por path: happy, error, timeout, cancelacion, etc.

## 8. Smoke en vivo (no solo tests)

Antes de mergear, el operario verifica contra TIA Portal real:

1. Abrir TIA Portal y cargar un proyecto.
2. Lanzar la app con `python main.py`.
3. Conectar desde la topbar.
4. Ejecutar el FB desde la SPA.
5. Verificar el progreso en la UI y los logs.
6. Verificar que `self.result` es lo esperado.

**Regla durable**: los tests pytest mockean el cliente TIA
completo y no ejercitan el path real de imports / interacciones.
El smoke en vivo es la verdad.

## Convenciones (resumen)

- Zona 0: imports + declaracion.
- Zona 1: `__init__` con `nombre`, `titulo`, `tracker=...`.
- Zona 2: hooks `on_start` / `on_finish`, todos sync.
- Zona 3: los steps, uno por metodo, con `@step` encima.
- El slug del metodo es el `snake_case` del nombre visible:
  `_stage_<n>_<slug>`.
- El `return` del step es su detail: el texto que ve el operario.
- TIA: `tia_client.submit_and_wait(comando, args, timeout=T)`.
- Router: `engine.submit(...)` + `202 {"ok": True, "job_id": ...}`.
- Resultado al HMI: push SSE `fb_state` + slots del AppCache.
- Tests con `MagicMock(spec=SyncTIAClient)`.
- Smoke en vivo obligatorio contra TIA real antes de mergear.
