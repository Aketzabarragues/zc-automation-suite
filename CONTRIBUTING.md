# CONTRIBUTING — Guía para contribuidores

> Las reglas del proyecto viven en `AGENTS.md`. Si hay conflicto, manda
> `AGENTS.md`. Este documento explica el cómo: cómo se commitea, cómo se
> verifica y qué se espera de cada cambio.

## 1. Reglas de commits

- **1-2 archivos por commit.** Excepción: refactors coordinados que tocan
  1 archivo en N puntos; en ese caso 1 commit con scope claro.
- **Mensaje en archivo, no en `-m`** (PowerShell con `-m` multilínea falla con
  caracteres especiales):

  ```powershell
  $msg = "fix(tia): corregir target_folder_path en import_blocks"
  # escribir mas detalle a un archivo, luego:
  git commit -F .commit-msg.txt
  rm -- .commit-msg.txt  # papelera, nunca rm directo
  ```

- **Scope entre paréntesis**: `fix(<scope>)`, `feat(<scope>)`,
  `docs(<scope>)`, `chore(<scope>)`, `refactor(<scope>)`, `test(<scope>)`.
  El scope es el area o modulo afectado (`tia`, `nucleo`, `alimentacion`,
  `frontend`, `vendor`, `readme`).
- **Descripción imperativa, en español.** Verbo en presente, sin sujeto
  ("añadir", "corregir", "portar"). NO "añadido por ...", NO "esto añade ...".
- **NO en el cuerpo**: planes (Fase X, Paso Y), fechas explicitas, estilo IA
  ("absorbe lógica de", "Migrado de", "ahora X antes Y"), narrador refactor.
  El diff ya cuenta la historia.
- **Borrar el archivo temp** con papelera de reciclaje (Windows) o `rm --`
  (que el runtime de mavis enruta a `mavis-trash` si está disponible).

## 2. Convenciones de código

- **PEP 8 + type hints** en Python, en todas las firmas.
  `from __future__ import annotations` al principio de cada módulo.
- **PowerShell estricto**: no `&&` (PowerShell 5.1 no lo soporta), usar `;`.
- **Prefijos de dominio primero** en archivos, clases y funciones:
  `disp_*` (dispositivos), `proc_*` (procesos), `ent_*` (entidades). Patron
  `<prefijo>_<verbo>_<concepto>`, NO al revés. No mezclar `disp_*` con `proc_*`
  en el mismo archivo.
- **Sin singletons dentro de la logica.** Las funciones de dominio son puras y
  reciben kwargs explicitos.

## 3. Reglas arquitectónicas críticas

| Regla | Detalle | Doc |
|---|---|---|
| Solo el hilo de `tia.py` importa `siemens_tia_scripting` | El wrapper se carga dentro del hilo; en ningun otro punto del proceso. | `AGENTS.md` |
| Toda escritura en TIA dentro de `with transaccion(...)` | Con rollback automatico si salta una excepcion. | `AGENTS.md` |
| Preview y aplicacion son la MISMA funcion | `aplicar=False` es el preview. No hay pares de funciones. | `AGENTS.md` |
| TIA: `target_folder_path` no se pasa (ni `""`) | Pasar `""` rompe el match UPDATE en V21. | `tia_ops/importar.py` |
| Encoding: `.s7res` utf-8-sig, resto utf-8 sin BOM | Siemens firma el YAML con BOM. | `AGENTS.md` |
| Cero codigo sucio: no dejar `.pyd`/`.dll` en el arbol | Se stagean en `tempfile.mkdtemp()`. | `AGENTS.md` |
| El nucleo no importa `areas` | Salvo la lista `AREAS` de `main.py`. Lo verifica `tests/test_fronteras.py`. | `AGENTS.md` |

## 4. `vendor/` (binarios propietarios de terceros)

- `vendor/` **no se versiona**. Es ignorado por git a proposito: los binarios
  del SDK Openness son de Siemens y tienen su licencia.
- Se poblara en local con la wheel oficial y los ficheros que trae. Ver
  [docs/INSTALAR.md](docs/INSTALAR.md).
- NO subas DLLs sueltas, fuentes ni documentacion de terceros al repo.
- La app no debe leer de `vendor/` en runtime: los binarios se resuelven desde
  `site-packages` y se stagean en un temporal.

## 5. Tests antes de commit

```powershell
python -m pytest tests/ -q
python -m ruff check .
```

En el frontend:

```powershell
cd frontend; npm test; cd ..
```

Cualquier fallo es regresion tuya: arréglalo antes de commitear. Si el fallo es
preexistente y no es tuyo, no lo toques, pero tu commit no debe anadir ninguno
nuevo.

Si anadiste una operacion contra TIA o tocaste el nucleo:

1. Smoke en vivo contra TIA Portal (los tests mockean todo y no pillan el path
   real de imports). **Siempre contra un proyecto de PRUEBA.**
2. Documenta el cambio en `AGENTS.md` o en la guia correspondiente de `docs/`.

## 6. Push y PRs

- **1-2 commits ahead de main** antes de push. Mega-commits prohibidos.
- **Mensaje de PR**: 2-3 frases explicando el "qué" y el "por qué". El "qué"
  se ve en los commits; el "por qué" no.
- **CI local** (no hay CI en el repo todavia): corre la suite completa antes
  de push.

## 7. Comunicacion

- Si un cambio cruza el nucleo y un area, abre hilo en el chat del equipo
  antes de empezar.
- Si encuentras un bug en runtime que los tests no pilla, escribelo en
  [docs/PROBLEMAS.md](docs/PROBLEMAS.md) con la receta del fix.
- Si modificas el contrato del nucleo (Job, transaccion, eventos SSE),
  actualiza `AGENTS.md` en el mismo commit.

## Resumen

| Regla | Dónde | Severidad |
|---|---|---|
| 1-2 archivos por commit | este doc | bloqueante |
| Mensaje en archivo (no `-m`) | este doc | bloqueante |
| Scope entre paréntesis | este doc | bloqueante |
| Sin planes ni "Migrado de" en el cuerpo | este doc | bloqueante |
| Dobles de test propios, nunca el SDK real | este doc + `AGENTS.md` | bloqueante |
| Smoke en vivo contra TIA real antes de mergear | este doc + `AGENTS.md` | bloqueante |
| Prefijos de dominio primero | este doc | bloqueante |
| `target_folder_path` no se pasa, nunca `""` | `tia_ops/importar.py` | bloqueante |
| Preview y aplicacion en la misma funcion | `AGENTS.md` | bloqueante |
