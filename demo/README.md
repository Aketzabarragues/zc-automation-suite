# Demo: como quedaria un FB declarativo

**Esto es una demo de codigo. No toca la aplicacion.** Ninguno de estos
ficheros se importa desde `core/` ni desde `areas/`, y no hay ningun
cambio en el repo fuera de esta carpeta.

Material de analisis para decidir si merece la pena refactorizar los 12
FBs del runtime para que sean "una declaracion de steps y que hace cada
step".

## Los 6 ficheros

| Fichero | Que es |
|---|---|
| `antes_function_base.py` | Extracto **literal** del motor real (`core/composition/plc_function_base.py`) |
| `antes_fb_disp_sincronizar.py` | Extracto **literal** del FB real del sync de dispositivos |
| `despues_function_base.py` | El motor propuesto: el dispatch se muda al motor |
| `despues_fb_disp_sincronizar.py` | El FB propuesto: una sola declaracion, sin `run_step` ni `_step_summary` |
| `diagrama_sfc.py` | Generador de diagramas SFC (ASCII y mermaid) desde la misma declaracion |
| `demo_disp_sync.py` | Ejecuta el FB propuesto de punta a punta, sin TIA |

Los "antes" son copia literal del repo (commit `a5be3d8`), con las
referencias de linea en los comentarios. Los "despues" son la propuesta:
la logica de negocio esta resumida (`# ... logica actual ...`) porque lo
que se analiza aqui es la **forma**, no el contenido.

## Que se ve, en dos minutos

### El FB declara sus steps DOS veces

```python
# 1a. el mapa nombre -> metodo (dentro de la clase)
STAGES = [
    (1, "Exportar etiquetas", "_stage_1_exportar_tags"),
    (2, "Calcular diferencias de dispositivos", "_stage_2_compute_diff"),
    ...
]

# 1b. los nombres que ve el HMI (en el constructor)
super().__init__(steps=steps if steps is not None else [
    {"nombre": "Exportar etiquetas"},
    {"nombre": "Calcular diferencias de dispositivos"},
    ...
])
```

Los 65 nombres del area son identicos en las dos listas. Y pueden
diverger **en silencio**: si el orden de `STAGES` no coincide con el de
`steps=`, se ejecuta el metodo equivocado sin error.

### Cada FB reimplementa el dispatch

```python
def run_step(self, idx, **params):
    step_nombre = self.steps[idx]["nombre"]
    for _s_idx, s_nombre, s_attr in self.STAGES:
        if s_nombre == step_nombre:
            getattr(self, s_attr)()
            return _step_summary(self._ctx, s_nombre)
    raise ValueError(...)
```

730 lineas de esto en los 12 FBs (286 en el area con tabla `STAGES`, 474
en `core/composition` con `match/case`).

### El detail sale de un `if/elif` por nombre literal

```python
def _step_summary(ctx, step_nombre):
    if step_nombre == "Exportar etiquetas":
        return f"Exportar etiquetas: {len(ctx.selective_tables)} tablas exportadas"
    ...
    return f"{step_nombre}: OK"     # <- fallback
```

**En 4 de los 9 FBs del area, el 100 % de esas ramas es codigo muerto**:
comparan contra nombres internos (`"check_state_commit"`, `"done"`)
mientras los steps se llaman `"Validar estado de TIA"`, `"Componer
respuesta"`. El operario ve "OK" en **37 de los 64 steps que pasan por
`_step_summary`** (58 %).

En el log del smoke del 30 oct 2026:

```
Importar proceso: saliendo en 15078ms (Importar proceso: OK)
Abrir transaccion TIA: saliendo en 17031ms (Abrir transaccion TIA: OK)
```

El sync de dispositivos (que si tiene las ramas vivas) si dice
"116 adds, 83 removes, 3 renames".

## El "despues" (formato A)

### El FB: cada paso se declara UNA vez

```python
class FunctionDispSincronizar(FunctionBase):

    @step(
        "Exportar etiquetas",
        descripcion="Exporta del PLC las tablas de tags de dispositivos",
    )
    def _stage_1_exportar_tags(self) -> str:
        """Limpia sync/ y exporta las tablas selectivas al snapshot export."""
        ...
        return f"Exportar etiquetas: {len(self._ctx.selective_tables)} tablas exportadas"
```

El nombre del paso, su descripcion y su codigo estan **juntos**. El
orden de los metodos es el orden del flujo: se lee de arriba abajo,
como un SFC.

Sin tabla `STAGES`, sin `steps=`, sin `run_step`, sin `_step_summary`. Y
**cada paso devuelve su detail**, que es lo que ve el operario: no hay
un segundo sitio donde decir que ha hecho el paso.

### El motor: recoge la declaracion y hace el dispatch

```python
@classmethod
def pasos_declarados(cls) -> list[StepSpec]:
    specs = []
    for klass in reversed(cls.__mro__):
        for _attr, value in vars(klass).items():
            spec = getattr(value, STEP_ATTR, None)
            if spec is not None:
                specs.append(spec)
    return specs
```

```python
def _invoke_step_sync(self, idx: int) -> str:
    step = self.steps[idx]
    handler = step.get("handler")
    if handler is not None:
        outcome = getattr(self, handler)()
    else:
        outcome = self.run_step(idx, **self._params)   # compat
    ...
```

`FunctionBase` ya normaliza `steps` a `list[dict]` y tolera keys extra,
asi que anadir `"handler"` no rompe nada.

## El diagrama sale de la misma declaracion

`demo/diagrama_sfc.py` dibuja el FB como un SFC, leyendo los mismos
`@step` que ejecuta el motor. No hay una tercera lista que mantener.

```powershell
python demo/diagrama_sfc.py            # ASCII + mermaid
python demo/diagrama_sfc.py --todos    # el de antes y el de despues
python demo/diagrama_sfc.py --mermaid  # solo mermaid
```

El de despues:

```
╔════════════════════════════════════════════════════════════════════════════╗
║ FunctionDispSincronizar                                                    ║
║ Sincroniza las tablas de tags de dispositivos contra el PLC.               ║
╚════════════════════════════════════════════════════════════════════════════╝

  ┌─ S1 ─ Exportar etiquetas ──────────────────────────────────────────────────┐
  │ Exporta del PLC las tablas de tags de dispositivos                         │
  │ -> _stage_1_exportar_etiquetas                                                  │
  └────────────────────────────────────────────────────────────────────────────┘
      │
      ▼
  ┌─ S2 ─ Calcular diferencias de dispositivos ────────────────────────────────┐
  │ Compara los XML exportados con los dispositivos del Excel                  │
  │ -> _stage_2_calcular_diferencias_de_dispositivos                                                   │
  └────────────────────────────────────────────────────────────────────────────┘
      │
      ▼
  ...
```

El de antes, con la misma caja pero sin descripcion y con el detail
salido de un sitio aparte:

```
  ┌─ S1 ─ Exportar etiquetas ──────────────────────────────────────────────────┐
  │ (sin descripcion)                                                          │
  │ -> _stage_1_exportar_etiquetas                                                  │
  │ detail: _step_summary(ctx, "Exportar etiquetas")                           │
  └────────────────────────────────────────────────────────────────────────────┘
```

## Verlo en marcha

```powershell
python demo/demo_disp_sync.py
```

Ejecuta el FB propuesto de punta a punta (sin TIA) y muestra lo que
veria el operario:

```
FB: disp_sincronizar -- Sincronizar dispositivos contra PLC
steps declarados: 11

[disp_sincronizar] Sincronizar dispositivos contra PLC
  flujo: Exportar etiquetas -> Calcular diferencias de dispositivos -> ...
  [ok] Exportar etiquetas -- Exportar etiquetas: 0 tablas exportadas
  [ok] Calcular diferencias de dispositivos -- Calcular diferencias de dispositivos: 0 adds, 0 removes, 0 renames
  ...
  [fin] ok

nStep=99  error=None
result={'success': True, 'message': 'Inyeccion completada: 0 N_MAX aplicados en TIA', ...}
```

Cada `[ok]` lleva el detail del paso. Es exactamente lo que hoy sale del
`_step_summary`: la diferencia es que ahora lo escribe el propio paso,
asi que no puede quedar desactualizado ni morir en silencio.

## El flujo, antes y despues (modo SFC)

```
ANTES: el flujo esta en 3 sitios                      DESPUES: esta en 1
  steps=[...]      -> lo ve el HMI                      @step(...)   -> lo ve el HMI
  STAGES=[...]     -> busca el metodo                      y el motor busca el metodo
  run_step()       -> hace el dispatch
  _step_summary()  -> pone el detail

  Si un nombre cambia en un sitio y no en otro: error o silencio.
```

## Numeros

| | |
|---|---|
| FBs | 12 (9 area + 3 core) |
| `run_step` solo de dispatch | 730 lineas |
| Boilerplate de dispatch en el area (`run_step` + `_step_summary` + `STAGES`) | 707 lineas (8 % del area) |
| Lineas que el FB de disp pierde | 13 (STAGES) + 13 (steps=) + 36 (run_step) + 57 (`_step_summary`) = **119** |
| Andamiaje / logica de negocio | 86 % (FB pequeno) / 49 % (mediano) / 32 % (grande) |
| Steps que muestran "OK" en vez del resumen | **37 de 64 (58 %)** |
| Tests del area que dependen de la forma | 12 de 147 |
| Referencias a metodos privados `_stage_N_*` | 85 (no se tocan si no se renombran) |

Ojo con el matiz: de las 474 lineas de `run_step` de los 3 FBs de
`core/composition`, **415 son logica de negocio** (el `match/case` de
`block_edit_prepare` tiene la logica dentro de las ramas). El refactor
no borra trabajo: lo saca de un `switch` y lo deja en metodos con
nombre, que es lo que se puede leer.

## Lo que no se toca

- El ctx: 8 dataclasses propios (el `ProcProcessGenContext` duplicado se
  unifico en `areas/alimentacion/state/proc_process_gen_context.py`)
  campo por campo en 2 ficheros. Se unifica el duplicado, no el resto.
- El contrato con el exterior: `execute`, `nStep`, `result`,
  `error_msg`, `is_terminal`, `request_cancel`, el shape de `fb_state` y
  de `progress`, y los routers. `fb.steps` no lo lee nadie fuera del
  motor: es contrato interno.
- Los nombres visibles de los steps: son las etiquetas que ve el
  operario en la barra de progreso.
- Los nombres de los metodos (`_stage_N_*`): 85 refs de test y 2 docs.
- El timeout: hoy es uno por FB. No se cambia en este paso.

## Como se migra un FB

1. Poner `@step(nombre, descripcion=...)` encima de cada metodo `_stage_N_*`.
2. Borrar la tabla `STAGES` y el `steps=` del constructor.
3. Borrar `run_step`.
4. Que cada paso devuelva su detail y borrar `_step_summary`.
5. Cambiar el guard `test_fbs_sync_contract` para que verifique los
   handlers en vez de `run_step`.

El motor acepta las dos formas, pero **no se mezclan**: si un FB declara
pasos con `@step` y a la vez pasa `steps=`, el constructor lanza
`ValueError`. Es deliberado: una migracion a medias dejaria pasos sin
ejecutar o ejecutados dos veces, y ese fallo tiene que verse al
arrancar, no tres minutos despues contra el PLC.

Por eso la migracion va FB a FB, y el motor va detras: mientras un FB
no tenga ningun `@step`, sigue funcionando con `steps=` + `run_step`.
