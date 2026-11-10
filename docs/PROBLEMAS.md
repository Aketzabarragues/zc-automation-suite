# Problemas

## TIA Portal

### El trabajo se queda colgado y hay que esperar mas de un minuto

TIA Portal tiene dialogos modales que bloquean la API: al compilar, al abrir
una transaccion o al importar bloques, TIA puede abrir una ventana de
confirmacion que espera una respuesta que la API no puede dar.

Cierra cualquier ventana de TIA que haya quedado abierta y repite la
operacion.

### El portal se cae a mitad de una operacion

Si TIA Portal se cierra o se reinicia, el handle COM queda invalido. La
app detecta la conexion caida y la marca como desconectada; no hay que
reiniciar la app, solo volver a conectar desde la topbar.

### El import crea un bloque en vez de actualizarlo

`import_blocks` con `target_folder_path=""` hace que TIA intente CREATE en
vez de UPDATE, y falla con "an object with the name X already exists". El
parametro no se pasa: es el camino que TIA entiende como "actualiza donde
este".

### El formato de export falla

El formato de export depende del objeto y de la version de TIA. Se consulta
con `get_supported_export_format()` en vez de suponerlo.

## Backend

### "No se pudo resolver 'siemens_tia_scripting'"

La wheel de Siemens no esta instalada en este interprete. Ver
[INSTALAR.md](INSTALAR.md). Ojo: el nombre de la wheel lleva el tag de ABI
(`cp312`, `cp313`, `cp314`) y tiene que coincidir con tu `python -V`.

### El hilo de TIA no arranca

El import del wrapper ocurre dentro del hilo. Si falla, el mensaje va al log
(`logs/zc.log`) con la excepcion original. Comprueba primero que la wheel
esta bien instalada.

### La app escribe en stdout cosas que no son del log

El SDK de Siemens escribe en stdout por su cuenta. La API documentada para
callarlo es global, del modulo `siemens_tia_scripting`, no un logger de
Python:

```
ts.set_logging(path = "c:\\logs\\tia.log", console = False)
```

- `console=False` desactiva la salida por consola.
- `path` es la ruta completa del log del SDK.

Se llama justo despues de cargar el wrapper, dentro del hilo de TIA. Si ves
ruido de Siemens en la consola, la llamada no se esta aplicando: mira
`zc_suite/tia.py`.

El `log4net.xml` que acompaña a la wheel **no** es su configuracion: es el
fichero de documentacion de la API de log4net. No hay nada que configurar a
mano.

### El hilo de TIA se muere al cerrar TIA Portal a mano

Peculiaridad de `siemens_tia_scripting`: cuando TIA Portal se cierra, la
llamada a `get_process_id()` puede devolver bien y dejar un error .NET
**pendiente**. Ese error no salta en la llamada: salta en la siguiente
operacion del hilo, que puede ser un `wait()` de Python y no parece tener
nada que ver. El sintoma es un `SystemError` dentro de
`threading.Event.wait` que tumba el hilo `zc-tia` y deja la app zombi: cree
que esta conectada, pero el portal esta muerto y ya nadie lo mira.

**Confirmado en las dos versiones del SDK**: la 1.2.1 y la 1.4.3 lo hacen
igual ("`<class 'int'> returned a result with an exception set`"). No es un
fallo de la 1.2.1.

La app lo cubre por tres vias:

- Cada iteracion del hilo va dentro de un `try/except BaseException`. Si
  algo falla, se anota con traceback, se da el portal por perdido y **el
  hilo sigue**.
- Tras `get_process_id()` se hace una comprobacion trivial
  (`pid_del_portal`). Si hay un error pendiente, salta ahi, dentro del
  `try` de quien llama, y no mas tarde en un sitio inexplicable.
- `estado()` da `conectado: false` si el hilo no esta vivo, y `lanzar()`
  reinicia el hilo avisando por log y por el evento `tia` con
  `ultimo_error: "El hilo de TIA se reinició tras un fallo"`.

Si aparece en el log, no es un fallo de la app: es el SDK. Lo que hay que
comprobar es que el hilo siga vivo y que la app se desconecte sola.

### "No se pudo exportar el bloque 'X': NotSupportedException"

El SDK no admite exportar ese bloque en SimaticSD con **esta** version de TIA
Portal. El error lo dice claro: *"The method is not supported in this API
version"*. Es la version de la API de TIA, no la del SDK.

Comprobado con las dos versiones del SDK (1.2.1 y 1.4.3) contra **TIA V18**:
las dos devuelven `get_supported_export_format() == ['SimaticML',
'ExternalSource']` y las dos rechazan `SimaticSD`. Con **TIA V21**, que es el
entorno de produccion, SimaticSD si funciona: por eso los bloques siguen
exportandose en SimaticSD (`.s7dcl`), que es lo que necesita la edicion
offline.

Si aparece, mira el proyecto abierto: puede que sea una version de TIA
distinta de la de produccion. Las tablas de tags no tienen ese problema: se
exportan en XML SimaticML en cualquier version.

### "No hay ningún TIA Portal abierto (o su versión no es compatible)"

Lo que ve el operario cuando el enganche falla. El texto original de
Siemens ("OpennessAccessException: No matching TIA Portal version could be
found") queda solo en el log.

Suele significar una de dos cosas: TIA Portal no esta abierto, o la version
de TIA que hay instalada no es la que soporta el SDK. La solucion es abrir
TIA Portal con el proyecto y volver a conectar.

### Sale un aviso de que falta pythonnet

No hace falta. El `.pyd` de `siemens_tia_scripting` es autonomo y carga el
CLR sin `pythonnet`. Si algo lo pide, es una dependencia que se colaron sin
necesidad: no la anadas al proyecto.

## Frontend

### Los estilos no se aplican

Tailwind v4 purga las clases que no encuentra en el codigo. Con el plugin de
Vite no hay que configurar nada: si una clase no existe, casi siempre es que
la clase no existe en el token set del tema. Los tokens estan en
`frontend/src/style.css`.

### La pagina no carga datos

Mira la consola del navegador y la pestaña Network. Si la peticion va a
`/api/...` y falla con un 404, el router no esta montado. Si falla con
`409`, hay un trabajo en curso: espera a que termine.

### La vista pide datos que no llegan

Los resultados llegan por SSE, no en el body del POST. Si la vista espera el
resultado de un `POST`, se queda esperando: el resultado esta en el evento
`job`.

## Empaquetado

### El `.exe` muere con ImportError al cargar Siemens

UPX corrompe los ensamblados .NET nativos. Las `.dll` y el `.pyd` tienen que
quedar **excluidos de UPX**.

### El `.exe` no encuentra el wrapper

En el bundle, el `.pyd` y todas las `.dll` tienen que estar en la **raiz** de
`_MEIPASS`, no en una subcarpeta.

### Build falla con PermissionError

Windows no deja escribir un `.exe` que esta en uso, ni un `.dll` que TIA
Portal tiene mapeada. Cierra TIA Portal y el `.exe` anterior, y repite.
