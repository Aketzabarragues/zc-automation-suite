---
name: agent-lessons
description: Lecciones operativas criticas del agente para zc-automation-suite — TIA Openness target_folder_path, compile() devuelve un ExecutionResult y no un booleano, silenciado del log nativo de Siemens con set_logging, encoding BOM al restaurar git desde PowerShell, smoke en vivo > tests verdes, auditar imports al mover codigo, encoding y saltos de linea de los ficheros TIA exportados, fixtures byte a byte. Carga esta skill ante bugs de import, de TIA, o refactors grandes.
---

# Lecciones operativas del agente (mavis → zc-automation-suite)

Reglas operativas criticas que el agente raiz (mavis) ha aprendido en este
proyecto. Aplicar como defaults al trabajar sobre `zc-automation-suite`.

Las rutas y los contratos de este repo estan en `AGENTS.md`. Esta skill solo
recoge lo que no se deduce del codigo.

## TIA Openness — no pasar `target_folder_path` en `import_blocks`

Regla critica para `PlcSoftware.import_blocks(import_root_directory,
target_folder_path)` (TIA V21):

- `target_folder_path=None` (default, **no pasar el argumento**) → TIA hace
  match UPDATE recursivo y preserva la ruta relativa. Es el camino feliz.
- `target_folder_path=""` (string vacio explicito) → TIA NO hace match UPDATE
  de bloques pre-existentes. Intenta CREATE y falla con "Import failed
  because an object with the name X already exists".

Aplica a `backend/zc_suite/tia_ops/importar.py` y a cualquier `import_*`
posterior (import_plc_tags, import_data_types...). Si el caller no pasa un
valor no vacio, **omite** el parametro.

## Silenciar el log nativo de Siemens

El SDK escribe en stdout si no se le dice lo contrario. La API documentada es
global, no un logger de Python:

```
ts.set_logging(path = "c:\\ws\\tiascripting.log", console = False)
```

- `console=False` desactiva la salida por consola.
- `path` es la ruta completa del fichero de log del SDK.

Se llama justo despues de cargar el wrapper, dentro del hilo de TIA. Es la
forma documentada; no inventar un `logging.getLogger(...)` para el SDK, que no
lo tiene.

## TIA Openness — errores .NET pendientes que matan el hilo

Peculiaridad de `siemens_tia_scripting`: cuando TIA Portal se cierra, la
llamada a `get_process_id()` puede devolver bien y dejar un error .NET
**pendiente**. Ese error no salta en la llamada: salta en la siguiente
operacion del hilo, que puede ser un `wait()` de Python. El sintoma es un
`SystemError` en `threading.Event.wait` que tumba el hilo `zc-tia` y deja
la app zombi.

Reglas que salen de ahi:

- El hilo que habla con TIA **no puede morir**: cada iteracion va dentro de
  un `try/except BaseException`. Si algo falla, se anota con traceback, se
  da el portal por perdido y el hilo sigue.
- Tras cualquier llamada al SDK, **fuerza una operacion trivial** (leer un
  atributo del resultado, un ``if``) dentro del mismo ``try``. Si hay un
  error pendiente, salta ahi y no en el siguiente sitio RANDOM del hilo.
- El estado de la conexion **no se deduce del portal guardado**: si el hilo
  que lo poseia ha muerto, la conexion no vale.
- Al reabrir, **verifica el portal guardado antes de devolverlo**. Si esta
  muerto, se descarta y se engancha de nuevo.

Aplica a `backend/zc_suite/nucleo/tia/servicio.py` (`pid_del_portal`,
`_bucle`, `_verificar_conexion`, `abrir_portal`).

## `compile()` devuelve un `ExecutionResult`, no un booleano

Comprobado contra TIA (V18 y V21). El manual de Openness no lo documenta:
§2.29.4 no dice nada y §2.2.11 afirma "True si hay errores", que es la
semantica antigua.

- `block.compile()` y `plc.compile_software()` devuelven un `ExecutionResult`
  del SDK. **Un objeto es siempre verdadero**: hacer `bool(resultado)` cuenta
  como "con errores" todo lo que compila. `main` tenia ese bug y en V21 el sync
  avisaba de "10 bloques con errores" con los 10 DBs compilados y sin errores.
- El `ExecutionResult` trae `get_result_state()` (0 sin errores, 20 con
  errores), `get_errors()`, `get_warnings()`, `get_information()` y
  `get_all_messages()`. Los mensajes son textos de TIA, por ejemplo
  `"ZC_PLC_STD > Program blocks > DB_NO_OK (DB5) > Interface > Data type Boo
  is unknown."`. La ultima linea es el resumen
  `"Compiling finished (errors: 1; warnings: 0)"`.

Como se decide si hay errores:

- Si el resultado trae `get_errors()`, hay errores si devuelve alguno.
- En un bloque, ademas, si sigue sin ser consistente tras compilar
  (`is_consistent()`, si documentado). Es el respaldo si el SDK cambia.
- Si TIA devolviera un booleano (SDK antiguo), en el PLC se toma como
  "True = errores" (§2.2.11); en un bloque se ignora y manda `is_consistent()`.

**Nunca `bool()` sobre el resultado de compilar.** Aplica a
`backend/zc_suite/tia_ops/compilar.py` y a cualquier codigo nuevo que
compile.

## `pythonnet` no hace falta

El `.pyd` de `siemens_tia_scripting` es autonomo: trae su propia integracion
con .NET y carga el CLR sin `pythonnet` instalado. Verificado en un venv
limpio con solo la wheel de Siemens. No lo anadir a las dependencias ni a los
hiddenimports de PyInstaller.

## Encoding y saltos de linea de los archivos TIA exportados

- `.s7res`: utf-8-sig (BOM).
- `.s7dcl`, `.scl`, `.xml`: utf-8 puro (sin BOM).
- **Los saltos de linea se fijan, no se heredan del sistema.** TIA exporta con
  CRLF y la paridad byte a byte con `main` depende de eso: los `.s7dcl` y los
  `.s7res` se escriben con `newline=SD_NEWLINE` (`\r\n`) en
  `simatic/sd/comentarios_array.py`. Si metes un `write_text()` nuevo sin
  `newline`, el resultado cambia entre Windows y Linux.
- El XML se serializa con ElementTree, que devuelve los saltos tal cual los
  leyo: el fichero de entrada manda.

## Los fixtures se comparan byte a byte

`tests/fixtures/**` esta marcado con `-text` en `.gitattributes`: git no
convierte sus bytes, ni al añadir ni al sacar. Los fixtures de `expected/`
guardan exactamente lo que produce la app, con CRLF.

- Si cambias un fixture: `git add --renormalize tests/fixtures` y comprueba
  que los tests de paridad siguen verdes.
- Con la regla `-text` en vigor, el indice guarda lo que hay en el disco: si
  el disco tiene LF y el indice CRLF (o al reves), la paridad se rompe en
  cuanto alguien hace checkout en otro sistema.
- Los helpers compartidos entre tests van como **fixtures** de `conftest.py`,
  no como funciones importadas: los modulos hermanos de test no son
  importables de forma fiable en modo importlib de pytest.

## Cero codigo sucio

NUNCA dejar `.pyd` / `.dll` de Siemens en el arbol de trabajo. Se stagean en
`tempfile.mkdtemp()` con el nombre canonico `siemens_tia_scripting.pyd`. Lo
mismo con las DLLs nativas. `vendor/` esta en `.gitignore` a proposito: son
binarios propietarios de Siemens.

## Restaurar archivos desde git en PowerShell — encoding BOM

NUNCA usar `>` de PowerShell para restaurar archivos de un commit git. Usar
siempre:
- La herramienta de write del agente (escribe UTF-8 sin BOM).
- `git show` + Python (lee bytes, decodifica, escribe UTF-8 sin BOM).
- O `git checkout <commit> -- <path>` desde el repo (respeta el encoding
  original).

Si el archivo restaurado se ve como `Bin 12796 -> 27120 bytes` en
`git diff --stat`, esta es la causa.

## PowerShell 5.1 en este host

- No hay `&&` ni `||`: encadena con `;` y comprueba `$LASTEXITCODE`.
- `Remove-Item` esta bloqueado, tambien los borrados recursivos. Para borrar
  de forma recuperable: `rm -- "<ruta absoluta>"` en **una sola invocacion**
  (solo el comando `rm`, sin `;` ni comandos encadenados). Con varios
  comandos o con `cd` en la misma linea, el borrado falla.
- `Get-Content` sin `-Encoding UTF8` muestra mojibake: usa `-Encoding UTF8` o
  la herramienta de read.
- Los commits se hacen con `git commit -F <fichero>`: `-m` con comillas rompe
  el parseo del shell.

## Al mover codigo entre modulos, audita TODOS los imports

Cuando mueves o renombras funciones, TODOS los simbolos que usan tienen que
tener import explicito. Un simbolo sin importar es un bug latente que los
tests con doubles no detectan.

Regla operativa: tras mover codigo, comprobar con `grep "^import|^from "`
sobre el fichero afectado que cada nombre usado en el cuerpo esta importado.

## Diagnostico — escanear TODAS las fuentes de inconsistencia

Cuando el operario reporta un bug tras un rename/import en TIA Portal,
escanear la Plantilla completa en busca de TODAS las inconsistencias, no solo
la que el operario señala.

Aplicacion cross-project: al diagnosticar un bug, hacer un escaneo
exhaustivo de la data del operario y reportar TODAS las inconsistencias, no
solo las relacionadas con el codigo que pregunta. Distinguir claramente "bug
del codigo" vs "inconsistencia pre-existente en tu data".

## Refactors grandes: metodologia worker + verifier con plan de explore

Para refactors cross-file con varios commits:

1. **Plan primero con `explore`:** pedirle:
   - Lista exhaustiva de archivos a tocar con `path:line`.
   - Orden de commits (cada uno commiteable solo, <200 lineas).
   - Ambiguedades que requeririan decision del operario.
   - Estimacion de tiempo y riesgo por commit.
2. **Worker por commit:** cada commit se delega a un `worker` con briefing
   que incluye el patron exacto (basado en un archivo ya migrado como
   referencia), la lista de archivos, y la orden de no tocar archivos fuera de
   scope. NO commitea si la suite falla. Reporta ambiguedades, NO las
   resuelve por su cuenta.
3. **Verifier por commit:** tras cada commit del worker, delegar a un
   `verifier` (read-only) que audite: patron aplicado consistentemente, scope
   respetado, tests verde vs baseline.
4. Smoke en vivo con un proyecto de TIA de PRUEBA.

## Delegar en pasos pequenos

Tarea grande = alucinaciones. Delega en 1-2 ficheros por paso, menos de 200
lineas, commiteable solo. Si un paso se complica, dividelo.

## Tests verdes != codigo correcto — el smoke en vivo es la verdad

Los tests mockean el cliente TIA completo y no ejercitan el path real de
imports / interacciones reales. Regla metodologica durable: tras un refactor
grande, smoke en vivo contra PLC real de prueba. Nunca contra el PLC de
produccion.
