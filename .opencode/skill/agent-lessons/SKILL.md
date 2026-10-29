---
name: agent-lessons
description: Lecciones operativas críticas del agente para zc-automation-suite — TIA Openness target_folder_path, Vue3 sin build step (CERO backticks en template), encoding BOM al restaurar git desde PowerShell, smoke en vivo > tests verdes, mover module-level a class methods audita imports, encoding de archivos TIA exportados. Carga esta skill ante bugs de import, templates Vue que rompen, o refactors grandes.
---

# Lecciones operativas del agente (mavis → zc-automation-suite)

Resumen de las reglas operativas críticas que el agente raíz (mavis)
ha aprendido en este proyecto. Aplicar como defaults al trabajar
sobre `zc-automation-suite` con OpenCode.

## TIA Openness — `None` vs string vacío en `target_folder_path`

Regla crítica (`.clinerules` §4) para
`PlcSoftware.import_blocks(import_root_directory, target_folder_path)`
(TIA V21):

- `target_folder_path=None` (default, NO pasar el argumento) → TIA
  hace match UPDATE recursivo, preserva la ruta relativa. **Es el
  camino feliz.**
- `target_folder_path=""` (string vacío explícito) → TIA NO hace match
  UPDATE de bloques pre-existentes. Intenta CREATE y falla con
  "Import failed because an object with the name X already exists".

Fix: si el caller no pasa un valor no vacío, omitir el parámetro
`target_folder_path` en la llamada a TIA. Aplica a
`core/infrastructure/tia/tia_cmd_import_.py::_h_import_block` y futuros
`import_*` (import_plc_tags, import_data_types, etc.).

## Vue 3 sin build step — CUALQUIER baktill dentro de `template:` rompe

PROHIBIDO usar baktilts literales (ni dobles ni simples) dentro de
comentarios HTML del template string Vue 3 sin build step.

El template es un JS string delimitado por baktilts:
`` template: /* html */ `...` ``. Si pones ``openSyncView`` dentro de
un ``<!-- comentario -->``, los baktilts cierran prematuramente el
string. El motor JS ve el resto del template como código, Vue monta
el componente con `"X is not a function"` y nada renderiza.

Síntomas típicos:
```
area-loader.js: [area-loader] loader "/static/.../Entidades.js" fallo:
TypeError: "... is not a function at Entidades.js:206:47
```
o:
```
SyntaxError: Unexpected identifier 'ENT'
```

Fix:
- En comentarios HTML del template, omitir baktilts. Escribir los
  identificadores sin formato o con comillas rectas.
- Si quieres delimitar nombres de código, usa `"ENT"` (comillas
  rectas), `ENT` (sin delimitadores) o `&quot;ENT&quot;` (entidad
  HTML).
- El JSDoc FUERA del template (``/** ... */`` arriba del export) sí
  puede tener baktilts dobles libremente.

Check pre-commit: auditar todos los archivos Vue ESM con regex
buscando baktilts dentro del rango del template. Hay un test
regression en `tests/areas/alimentacion/frontend/test_template_baktilts.py`
que rompe si CUALQUIER archivo tiene UN baktill dentro del template.

## Restaurar archivos desde git en PowerShell — encoding BOM

NUNCA usar `>` de PowerShell para restaurar archivos de un commit
git. Usar siempre:
- La herramienta de write del agente (escribe UTF-8 sin BOM).
- `git show` + Python (lee bytes, decodifica, escribe UTF-8 sin BOM).
- O `git checkout <commit> -- <path>` desde el repo (respeta el
  encoding original).

Si el archivo restaurado se ve como `Bin 12796 -> 27120 bytes` en
`git diff --stat`, esta es la causa.

## Diagnóstico — escanear TODAS las fuentes de inconsistencia

Cuando el operario reporta un bug tras un rename/import en TIA
Portal, escanear la Plantilla completa en busca de TODAS las
inconsistencias, no solo la que el operario señala.

Aplicación cross-project: al diagnosticar un bug, hacer un escaneo
exhaustivo de la data del operario y reportar TODAS las
inconsistencias, no solo las relacionadas con el código que pregunta.
Distinguir claramente "bug del código" vs "inconsistencia
pre-existente en tu data".

## Refactors grandes: metodología worker + verifier con plan de explore

Para refactors cross-file con varios commits:

1. **Plan primero con `explore`:** pedirle:
   - Lista exhaustiva de archivos a tocar con `path:line`.
   - Orden de commits (cada uno commiteable solo, <200 líneas).
   - Ambigüedades que requerirían decisión del operario.
   - Estimación de tiempo y riesgo por commit.
2. **Worker por commit:** cada commit se delega a un `worker` con
   briefing que incluye el patrón exacto (basado en un archivo ya
   migrado como referencia), la lista de archivos, y la orden de no
   tocar archivos fuera de scope. NO commitea si la suite falla.
   Reporta ambigüedades, NO las resuelve por su cuenta.
3. **Verifier por commit:** tras cada commit del worker, delegar a
   un `verifier` (read-only) que audite: patrón aplicado
   consistentemente, scope respetado, tests verde vs baseline.
4. Smoke E2E con `MainServiceSupervisor` directo (no por bandeja):
   instanciar `ConfigManager(department=...)`,
   `MainServiceSupervisor(host=..., port=..., config_manager=cfg)`,
   `sup.start()`, esperar `/api/v1/catalog`, hacer requests HTTP,
   `sup.stop(timeout=3)`.

## Tests verdes != código correcto — smoke en vivo es la verdad

El operario hizo smoke en vivo contra TIA V21 y el log pilló DOS bugs
críticos que todos los tests verdes NO detectaban (compute_diff path
bug + commit_user_constants_online perdido).

Regla metodológica durable: tras un refactor grande, smoke en vivo
contra PLC real. Los tests pytest mockean el cliente TIA completo y
no ejercitan el path de imports / interacciones reales.

## Cuando mueves funciones module-level a class methods — audita TODOS los imports

Cuando absorbes funciones a nivel de módulo (`def proc_X(self)`) dentro
de una clase como métodos reales (`def _stage_N_X(self)`), TODOS los
símbolos que esas funciones usan deben estar importados a nivel de
módulo.

Smoke en vivo del operario contra TIA V21 pilló 5 de
estos: `function_disp_sincronizar.py`,
`function_disp_generar_preview.py`,
`function_proc_crear_sincronizar.py`,
`function_proc_db_generar_preview.py`,
`function_proc_db_sincronizar.py`.

Regla operativa: tras mover module-level functions a class methods,
ejecutar SIEMPRE en vivo (no solo tests). Verificar con
`grep "^import|^from " <file>` que TODOS los símbolos usados en el
cuerpo del archivo tienen import explícito arriba. Cualquier
referencia a un nombre que no esté importado es un bug latente.

## Encoding de archivos TIA exportados

- `.s7res`: utf-8-sig (BOM).
- `.s7dcl`, `.scl`, `.xml`: utf-8 puro (sin BOM).
- `open()` siempre con `newline=''` para preservar retornos de
  carro originales de TIA Portal.

## Cero código sucio

NUNCA dejar `.pyd` / `.dll` de Siemens en el working tree. Stagea
siempre en `tempfile.mkdtemp()` con nombre canónico
(`siemens_tia_scripting.pyd`). Lo mismo con DLLs nativas (.NET
runtime, VCRuntime, etc.).