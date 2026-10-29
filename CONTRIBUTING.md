# CONTRIBUTING — Guía para contribuidores

> Esta guía consolida las reglas dispersas en `AGENTS.md` y en la
> memoria del agente raíz. Si hay conflicto, manda `AGENTS.md`.

## 1. Reglas de commits

- **1-2 archivos por commit.** Excepción: refactors coordinados
  que tocan 1 archivo en N puntos; en ese caso 1 commit con
  scope claro.
- **Mensaje en archivo, no en `-m`** (PowerShell con `-m`
  multilínea falla con caracteres especiales):

  ```powershell
  $msg = "fix(tia): corregir target_folder_path en import_blocks"
  # escribir mas detalle a un archivo, luego:
  git commit -F .commit-msg.txt
  rm -- .commit-msg.txt  # papelera, nunca rm directo
  ```

- **Scope entre paréntesis**: `fix(<scope>)`, `feat(<scope>)`,
  `docs(<scope>)`, `chore(<scope>)`, `refactor(<scope>)`,
  `test(<scope>)`. El scope suele ser el área o submódulo
  afectado (`tia`, `engine`, `vendor`, `readme`, etc.).
- **Descripción imperativa, en español.** Verbo en presente, sin
  sujeto ("añadir", "corregir", "migrar"). NO "añadido por ...",
  NO "esto añade ...".
- **NO en el cuerpo**: planes (Fase X, Paso Y), fechas explícitas,
  estilo IA ("absorbe lógica de", "Migrado de", "ahora X antes
  Y"), narrador refactor. El diff ya cuenta la historia.
- **Borrar el archivo temp** con papelera de reciclaje (Windows)
  o `rm --` (que el runtime de mavis enruta a `mavis-trash` si
  está disponible).

## 2. Convenciones de código

- **PEP 8 + type hints** en Python. `from __future__ import
  annotations` al principio de cada módulo.
- **PowerShell estricto**: no `&&` (PowerShell 5.1 no lo soporta),
  usar `;`.
- **Prefijos `disp_*` / `proc_*` primero** en archivos, clases y
  funciones del área de alimentación. Patrón
  `<prefijo>_<verbo>_<concepto>`, NO al revés. Excepciones:
  `mlc_registry.py`, `excel_cache.py`, cross-cutting,
  `mcp/tools.py`.
- **No mezclar** `disp_*` con `proc_*` en el mismo archivo (regla
  del operario).

## 3. Reglas arquitectónicas críticas

| Regla | Detalle | Doc |
|---|---|---|
| Worker OT no importa `siemens_tia_scripting` fuera de `core/infrastructure/tia/` | El wrapper solo se carga en el hilo persistente del worker. | `.clinerules §1` |
| TIA: `target_folder_path=None` (NO `""`) | Pasar `""` rompe el match UPDATE en V21. | `.clinerules §4` |
| Vue 3: CERO backticks en `template:` | Cualquier backtick cierra prematuramente el template string. | `.clinerules §9` |
| Encoding: `.s7res` utf-8-sig, resto utf-8 sin BOM | Siemens firma el YAML con BOM. | `AGENTS.md` |
| Cero código sucio: no dejar `.pyd`/`.dll` en el working tree | Stagea siempre en `tempfile.mkdtemp()`. | `.clinerules §6` |

## 4. `vendor/` (wheels de terceros propietarios)

- Las wheels y binarios propietarios viven en `vendor/` y se
  trackean en git. NO están en `requirements.txt` (licensing).
- Cada wheel nueva va con su commit propio:
  `chore(vendor): añadir wheel de <nombre>-<version>`.
- NO subir DLLs sueltas, fuentes, ni docs de terceros a `vendor/`.
  Solo wheels y archivos binarios autocontenidos que el proyecto
  necesita en runtime o build.
- `vendor/README.md` documenta qué hay en cada subcarpeta;
  mantenerlo al día.

## 5. Tests antes de commit

```powershell
python -m pytest tests/ -q
```

**Resultado esperado:** 1114 verde, 3 skipped (intencionales).
Cualquier fallo NO documentado en `TROUBLESHOOTING.md §5` es
regresión tuya: arréglalo antes de commitear.

Si añadiste un FB, helper o comando nuevo:
1. Smoke en vivo contra TIA Portal (los tests mockean todo, no
   pillan el path real de imports).
2. Documenta el cambio en `AGENTS.md` o en el howto
   correspondiente.

## 6. Push y PRs

- **1-2 commits ahead de main** antes de push. Mega-commits
  prohibidos.
- **Mensaje de PR**: 2-3 frases explicando el "qué" y el "por qué".
  El "qué" se ve en los commits; el "por qué" no.
- **CI local** (no hay CI en el repo todavía): corre la suite
  completa antes de push. Si la suite tiene fallos preexistentes
  que no son tuyos, no los toques; pero tu commit no debe añadir
  ninguno nuevo.

## 7. Comunicación

- Si un cambio cruza varios bounded contexts (core + area), abre
  hilo en el chat del equipo antes de empezar.
- Si encuentras un bug en runtime que los tests no pilla, escríbelo
  en `TROUBLESHOOTING.md` con la receta del fix.
- Si modificas el contrato de un comando TIA, actualiza el
  catálogo en `AGENTS.md` en el mismo commit.

## Resumen

| Regla | Dónde | Severidad |
|---|---|---|
| 1-2 archivos por commit | este doc | bloqueante |
| Mensaje en archivo (no `-m`) | este doc | bloqueante |
| Scope entre paréntesis | este doc | bloqueante |
| Sin planes ni "Migrado de" en el cuerpo | este doc | bloqueante |
| `MagicMock(spec=SyncTIAClient)` en tests | este doc + AGENTS.md | bloqueante |
| Smoke en vivo contra TIA real antes de mergear | este doc + AGENTS.md | bloqueante |
| Prefijos `disp_*` / `proc_*` primero | este doc | bloqueante |
| `target_folder_path=None`, nunca `""` | `.clinerules §4` | bloqueante |
| CERO backticks en `template:` Vue 3 | `.clinerules §9` | bloqueante |
