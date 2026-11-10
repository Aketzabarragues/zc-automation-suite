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

El logger nativo de Siemens escribe en stdout al cargar el wrapper. Se
silencia al cargar la libreria. Si ves ruido de Siemens en la consola, el
silenciamiento no se ha aplicado: mira `zc_suite/tia.py`.

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
