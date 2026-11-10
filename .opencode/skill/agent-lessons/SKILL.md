---
name: agent-lessons
description: Lecciones operativas criticas del agente para zc-automation-suite — TIA Openness target_folder_path, silenciado del log nativo de Siemens con set_logging, encoding BOM al restaurar git desde PowerShell, smoke en vivo > tests verdes, auditar imports al mover codigo, encoding de archivos TIA exportados. Carga esta skill ante bugs de import, de TIA, o refactors grandes.
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

## `pythonnet` no hace falta

El `.pyd` de `siemens_tia_scripting` es autonomo: trae su propia integracion
con .NET y carga el CLR sin `pythonnet` instalado. Verificado en un venv
limpio con solo la wheel de Siemens. No lo anadir a las dependencias ni a los
hiddenimports de PyInstaller.

## Encoding de archivos TIA exportados

- `.s7res`: utf-8-sig (BOM).
- `.s7dcl`, `.scl`, `.xml`: utf-8 puro (sin BOM).
- `open()` siempre con `newline=''` para preservar los retornos de carro
  originales de TIA Portal.

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

## Tests verdes != codigo correcto — el smoke en vivo es la verdad

Los tests mockean el cliente TIA completo y no ejercitan el path real de
imports / interacciones reales. Regla metodologica durable: tras un refactor
grande, smoke en vivo contra PLC real de prueba. Nunca contra el PLC de
produccion.
