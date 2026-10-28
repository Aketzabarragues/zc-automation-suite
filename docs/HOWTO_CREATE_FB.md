# HOWTO — Crear un Function Block (FB) nuevo

> Audiencia: técnico que ha leído `core/composition/plc_function_base.py`
> y conoce el patrón `nStep` con zonas 0/1/2/3. Esta guía es una
> **réplica standalone** con un ejemplo end-to-end; no reemplaza
> la lectura del base ni de `MIGRATION_PLAYBOOK.md`.

## 1. Cuándo necesitas un FB

Si tu operación:

- Tarda > 500 ms (el operario necesita ver progreso).
- Tiene varios pasos discretos que quieres reportar al HMI.
- Necesita cancelación cooperativa.
- Necesita lockeo contra re-entradas concurrentes.

Un FB **no** es para operaciones instantáneas (esas van en un
endpoint Flask síncrono).

## 2. Pre-requisitos

- Leer `core/composition/plc_function_base.py` (la `FunctionBase`).
- Conocer el FB de referencia: `areas/alimentacion/functions/function_excel_cargar.py`.

## 3. Estructura de 4 zonas

```python
# Zona 0: imports + declaracion
from __future__ import annotations
import logging
from typing import Any
from core.composition.plc_function_base import FunctionBase
from core.helpers.tia.tia_dispatch_async import dispatch_async

logger = logging.getLogger(__name__)


# Zona 1: declaracion estatica
class FunctionMiFB(FunctionBase):
    STEP_TIMEOUT_S = 600  # 10 min por step

    def __init__(self, tracker=None):
        super().__init__(
            nombre="mi_fb",
            titulo="Mi operación",
            steps=["paso_1", "paso_2", "paso_3"],
            tracker=tracker,
        )

    # Zona 2: hooks (on_start, run_step, on_finish)
    def on_start(self, **params) -> None:
        """Validar params, abrir recursos."""
        # los params vienen del fb._params (seteado por start(**kwargs))
        if not params.get("path"):
            raise ValueError("Se requiere 'path'.")

    async def run_step(self, idx, **params) -> str:
        """Logica del step N. Devuelve detail (string) para el HMI."""
        if idx == 0:
            # paso 1
            return await self._step_1(params)
        if idx == 1:
            return await self._step_2(params)
        if idx == 2:
            return await self._step_3(params)
        raise NotImplementedError(f"step {idx} no implementado")

    def on_finish(self, **params) -> None:
        """Vuelca self.result para que el router lo devuelva al cliente."""
        self.result = {"status": "ok"}

    # Zona 3: helpers privados
    async def _step_1(self, params):
        # ...
        return "ok"
```

## 4. Hooks: contrato, errores típicos

| Hook | Cuándo se llama | Errores típicos |
|---|---|---|
| `on_start(**params)` | Una vez, antes del primer `run_step`. **Síncrono.** | Lanzar `ValueError` por params inválidos: el base lo captura y transita a `n_error`. |
| `run_step(idx, **params)` | Una vez por step. **Async.** | Lanzar `NotImplementedError` por olvidos: propaga al dev. Lanzar `Exception` operacional: el base lo silencia y transita a `n_error`. |
| `on_finish(**params)` | Una vez, al pasar de `n_finalizar` a `n_done`. **Síncrono.** | Asignar `self.result` con el dict que el router devolverá al cliente. |

## 5. Progreso: `ProgressTracker`

El base invoca el tracker automáticamente:

- `tracker.begin(operation, label, stages)` en `on_start` (vía
  `_step_arrancar`).
- `tracker.start_stage(stage_id)` antes de cada `run_step`.
- `tracker.finish_stage(stage_id, detail)` después.
- `tracker.error_stage(stage_id, detail)` si hay error.
- `tracker.finish(success=True|False)` en `n_done` o `n_error`.

Los IDs de stage vienen de `self.steps` (la lista de dicts que
pasaste en `__init__`). El HMI los muestra con su `nombre`.

**Reglas operativas**:

- Emite `begin` en `on_start` (lo hace el base).
- Emite `start_stage` / `finish_stage` solo si el step tiene
  progreso INTERNO que merece ser visible. Para un step trivial
  (e.g. parsear un JSON de 50 líneas), el start/finish del stage
  ya basta.
- NO emitas `begin` / `start_stage` / `finish` en el router Flask.
  Eso es responsabilidad del FB y su `tick()`.

## 6. Router Flask que llama al FB

`areas/<area>/frontend/<mi_fb>_router.py`:

```python
from flask import Blueprint, jsonify, request
import asyncio
from core.web_server.dependencies import get_gateway, get_progress_tracker

bp = Blueprint("<area>_<mi_fb>", __name__, url_prefix="/api/v1/<area>/<mi_fb>")


@bp.post("/start")
def start():
    gateway = get_gateway()
    tracker = get_progress_tracker()
    fb = gateway.get_fb("mi_fb")
    if fb is None or not fb.is_terminal():
        return jsonify({"ok": False, "error": "FB ya activo"}), 409
    try:
        asyncio.run(fb.start(**request.json or {}))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "fb": "mi_fb", "result": fb.result})
```

Reglas:

- Inyecta dependencias explícitamente con `get_gateway()` /
  `get_progress_tracker()`. NUNCA importes Singletons globales.
- Devuelve `dict` (Flask lo serializa con `jsonify`).
- Para errores, devuelve tuplas `(dict, status_code)` con HTTP
  sensato (400, 404, 409, 500).
- Si `fb.is_terminal() is False` (FB ya activo), devuelve 409.

## 7. Tests

`tests/areas/<area>/functions/test_<mi_fb>.py`:

```python
from unittest.mock import MagicMock
from core.infrastructure.tia.tia_client import SyncTIAClient
from areas.<area>.functions.function_<mi_fb> import FunctionMiFB


def test_<mi_fb>_happy_path():
    tia_client = MagicMock(spec=SyncTIAClient)
    fb = FunctionMiFB()
    # ... drive el FB a n_done
    assert fb.nStep == fb.n_done
    assert fb.result == {"status": "ok"}
```

Convenciones:

- Mockear el cliente TIA con `MagicMock(spec=SyncTIAClient)`. Nunca
  mockear el worker directamente.
- `ProgressTracker()` limpio instanciado y pasado al FB (no
  mockear el tracker).
- 1 test por path: happy, error, timeout, cancelación, etc.

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

- Zona 0: imports + declaración.
- Zona 1: `__init__` con `nombre`, `titulo`, `steps`, `tracker=...`.
- Zona 2: hooks `on_start` / `run_step` / `on_finish`.
- Zona 3: helpers privados.
- Tests con `MagicMock(spec=SyncTIAClient)`.
- Smoke en vivo obligatorio contra TIA real antes de mergear.
