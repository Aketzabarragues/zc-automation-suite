# Migración de use cases legacy a FBs (playbook)

> Checklist operacional para pasar un use case de
> `areas/<area>/application/use_cases/` a un FB del area usando
> `function_template.py` como base. Aplica a los 5 use cases
> restantes de alimentacion (A.2-A.6) y a futuras areas.

## Referencia canonica: subir_excel

Antes de empezar, lee estos 4 archivos en este orden:

1. `areas/alimentacion/functions/function_template.py` — plantilla con Zona 0.
2. `areas/alimentacion/functions/function_SubirExcel.py` — FB migrado.
3. `areas/alimentacion/helpers/sync/upload_excel.py` — helper puro.
4. `areas/alimentacion/frontend/excel_router.py` — endpoint POST.

El FB `subir_excel` cubre los 5 gotchas conocidos. Replica su estructura.

## 6 pasos por migracion

### 1. Identificar el use case origen

`areas/<area>/application/use_cases/<use_case>.py` (legacy). Anotar:
- Funciones puras que contiene (que hace, que datos produce).
- Side effects (I/O, subprocess, red).
- Deps que necesita (config_manager, tia_client, cache, etc.).

### 2. Extraer la logica pura al helper

Crear `areas/<area>/helpers/sync/<use_case>.py` con funciones puras
que reciben las deps como kwargs explicitos. NO usar Singletons
globales dentro del helper. Devuelven dataclasses del area o dicts.

```python
async def do_thing(config_manager, tia_client, **kwargs) -> Result:
    ...
```

Si la logica es CPU/IO-bound, envolver con `asyncio.to_thread(...)`
para no bloquear el event loop.

### 3. Crear el FB desde la plantilla

Copiar `function_SubirExcel.py` a `function_<UseCase>.py` y editar:

- **Zona 1** (`STEP_TIMEOUT_S`): elegir timeout razonable por step.
- **Zona 0** (`__init__`): quitar deps no usadas, anadir las
  especificas (cache_cls, factory, etc.).
- **Zona 3** (estado entre ticks): atributos persistentes entre
  `run_step` y `on_finish` (ej. `_xlsx_path`, `_pending_cache`).
- **`on_start(**params)`**: validar params obligatorios, fallar con
  `ValueError` si falta alguno (el base transita a `n_error`).
- **`run_step(idx, **params)`**: lazy import del helper (ver
  gotcha 4). Cada `case` = una etapa del FB.
- **`on_finish(**params)`**: volcar `self.result` con la shape que
  el endpoint espera (consultar el use case legacy para mantener
  compatibilidad si el caller lo consume).

Renombrar la clase a `Function<UseCase>` y el kwarg `nombre` por
defecto a `"<use_case>"` (canonico: debe coincidir con la key del
registro en el engine).

### 4. Registrar el FB en el engine

En `areas/<area>/__init__.py::register_<area>(engine, *,
config_manager, tia_client, build_cache, log, app_state)` anadir:

```python
engine.register_fb(
    "<use_case>",
    Function<UseCase>(
        config_manager=config_manager,
        tia_client=tia_client,
        build_cache=build_cache,
        log=log,
        app_state=app_state,
        # ... deps especificas si las hay
    ),
)
```

### 5. Crear el endpoint web

`areas/<area>/frontend/<use_case>_router.py` con un blueprint
Flask. Patron multipart + poll bloqueante de `excel_router.py`
para casos con input del operario. Para casos sin input, un GET
basta.

El endpoint debe propagar `started=False` como `409`:

```python
started = asyncio.run(fb.start(**params))
if not started:
    return jsonify({"ok": False, "error": "FB ya activo."}), 409
```

Montar el blueprint en
`areas/<area>/__init__.py::_build_all_routers(app)` anadiendo la
llamada al `build_routers(app)` del nuevo modulo.

### 6. Smoke y borrado del legacy

- Smoke en vivo: `POST /api/v1/<use_case>` (con input real si
  aplica) + verificar `ConsolaLogs` + `self.result` correcto.
- Si OK, `git rm areas/<area>/application/use_cases/<use_case>.py`.

## Gotchas (5)

1. **`LogBuffer.info(message)` solo acepta 1 argumento.** NUNCA
   `info("fmt %s", arg1)` estilo `logging`. Usar f-strings:
   `info(f"[{nombre}] {x}")`. El template y los FBs ya lo respetan
   (commits `cb24d40`, `85cfb62`).

2. **`_stats` lo inicializa `FunctionBase.__init__`.** No
   redeclararlo en el FB a menos que heredes de `FunctionTemplate`
   (que lo hace en su Zona 3).

3. **El FB es reusable.** `start()` acepta re-arranque desde
   `n_done`/`n_error` (commit `8c30ed0`). El operario puede
   disparar el endpoint N veces sin reiniciar la app. El router
   no necesita cambios para esto; basta propagar 409 si
   `start()` devuelve False.

4. **Lazy import del helper dentro de `run_step`** para evitar
   ciclos entre el FB y `helpers/sync/<x>.py`. Patron en
   `function_SubirExcel.py:116-119`.

5. **No devolver objetos nativos TIA (.NET) al proceso IT.**
   Mapear a `dict`/`list`/`str`/`bool`/`int` antes de `self.result`
   o cualquier serializacion JSON. Aplica a todo lo que el helper
   exponga hacia arriba.
