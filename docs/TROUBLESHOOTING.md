# TROUBLESHOOTING — Problemas típicos con fix

> 10 problemas típicos al desarrollar o ejecutar `zc-automation-suite`,
> con causa y fix accionable. Si tu problema no está aquí, abre un
> issue con el log completo (especialmente el `tail -100 logs/zc.log`).

## 1. Worker OT falla con timeout 45s

**Síntoma:** el endpoint que toca TIA devuelve 504 tras ~45s.

**Causa típica:** hay un diálogo modal abierto en TIA Portal
(`Save project?`, `Compiler progress`, etc.) que bloquea el
`attach_portal` o cualquier llamada `import_*` / `compile_*`.

**Diagnóstico:**

```powershell
# Ver si TIA está bloqueado
Get-Process -Name "Siemens.TiaPortal" -ErrorAction SilentlyContinue
```

**Fix:**

1. Click en TIA Portal y cierra cualquier diálogo modal.
2. Si está en `compile_plc` u `open_transaction`, espera a que
   termine (puede tardar minutos).
3. Reintenta el endpoint.

## 2. "Otra instancia está corriendo (lock file ocupado)"

**Síntoma:** la app no arranca; log dice que el lock file está
ocupado.

**Causa típica:** la bandeja anterior no se cerró limpiamente
(sigterm, crash, etc.) y dejó `~/.zc_automation_suite.lock`.

**Diagnóstico:**

```powershell
Test-Path ~/.zc_automation_suite.lock
```

**Fix:**

1. Si no hay otra instancia visible, borrar el lock:
   ```powershell
   Remove-Item ~/.zc_automation_suite.lock -Force
   ```
2. Si hay otra instancia, cerrarla desde la bandeja (click derecho
   → Salir).

## 3. `ImportError: siemens_tia_scripting`

**Síntoma:** la app no arranca; el worker OT loga
`ImportError: No module named 'siemens_tia_scripting'`.

**Causa típica:** la wheel de `vendor/` no está instalada, o la
versión del Python activo no coincide con la wheel.

**Diagnóstico:**

```powershell
python --version
ls vendor/install/
python -c "import siemens_tia_scripting; print(siemens_tia_scripting.__file__)"
```

**Fix:**

```powershell
# Sustituir cp3XX por la versión de tu Python activo
pip install vendor/install/siemens_tia_scripting-1.4.3-cp3XX-cp3XX-win_amd64.whl
```

Si no hay wheel para tu versión, pedir al equipo (ver
`docs/ONBOARDING.md` §4).

## 4. "Excel no se carga"

**Síntoma:** la SPA muestra "Excel no cargado" al abrir el área de
alimentación.

**Causa típica:** el `plantillas_path` en `config/config.json` apunta
a una ruta que no existe en tu máquina, o el path tiene espacios
mal escapados.

**Diagnóstico:**

```powershell
# Ver el config actual
Get-Content config/config.json | Select-String "plantillas_path"

# Verificar que la ruta existe
Test-Path "D:\ruta\del\operario\_plan\Generar_Proceso"
```

**Fix:**

Edita `config/config.json` y reemplaza `plantillas_path` con la
ruta real de tu máquina. Usa `\\` en lugar de `\` para los
separadores de Windows dentro del JSON:

```json
"plantillas_path": "C:\\Users\\TU_USUARIO\\...\\plantillas"
```

## 5. "Tests fallan con 4 legacy"

**Síntoma:** `python -m pytest tests/ -q` falla con 4 errores que
parecen no tener relación con tus cambios.

**Causa típica:** 4 tests legacy pre-existentes (NO son regresión
tuya). Están documentados en `AGENTS.md §"Convenciones operativas"`
como no-bloqueantes.

**Diagnóstico:**

```powershell
python -m pytest tests/ -q 2>&1 | Select-String "FAILED"
```

**Fix:**

Compara con la baseline de tu rama antes de empezar a tocar:

```powershell
git stash
python -m pytest tests/ -q  # baseline
git stash pop
```

Si los 4 fallos son los mismos, no son tuyos. Si hay fallos
nuevos, esos sí son tuyos.

## 6. "TypeError: Cannot read properties of undefined" en la consola del browser

**Síntoma:** la SPA carga pero un componente explota con
`Cannot read properties of undefined (reading 'xxx')`.

**Causa típica:** Vue 3 sin build step no expone los `import` a
nivel de módulo al scope del template. Si el template lee
`store.memoryState` directamente, ve `undefined`.

**Diagnóstico:** abrir la consola del browser (F12) y leer la traza.
El componente problemático aparece en la primera línea del stack.

**Fix:**

Encapsular el acceso a `store` en un `computed` y retornarlo del
`setup()`:

```javascript
const data = computed(() => store.memoryState?.datos || null);
return { data };
```

Ver `AGENTS.md §"Vue 3 sin build step"` para más detalles.

## 7. "CSS no se aplica"

**Síntoma:** añades una clase nueva a un componente pero no se ve
en el navegador.

**Causa típica:** Tailwind no se recompiló tras el cambio. Los
componentes usan `bg-accent` (clase del tema "Industrial Claro") y
Tailwind solo incluye en `styles.css` las clases que ve en los
archivos.

**Fix:**

```powershell
.\run_tailwind.bat
```

Si el bat apunta a un path obsoleto (síntoma adicional: el bat
falla con "file not found"), ver Bloque 1 del plan (commit
`fix(build): corregir path de Tailwind en run_tailwind.bat`).

## 8. "Compilación falla con error 33007"

**Síntoma:** `compile_blocks` o `compile_plc` devuelve error
`33007` (TiaPortal.OpennessApi).

**Causa típica:** un bloque del PLC está siendo usado por otro
programa (TIA Portal mismo, un export en curso, etc.) y no se
puede re-compilar.

**Diagnóstico:** el error va con el nombre del bloque problemático
en `result.errors[].name`.

**Fix:**

1. Cerrar TIA Portal temporalmente.
2. Reintentar la compilación.
3. Si persiste, abrir TIA, ir al bloque en cuestión, hacer "Compile"
    manual y leer el error de Siemens.

## 9. "El worker OT entra en estado `error`"

**Síntoma:** la SPA muestra "Worker OT en error. Reconectar.".

**Causa típica:** RCW de .NET quedó inválido (TIA Portal se cerró
de golpe, o el worker quedó atado a un TIA que ya no responde).

**Diagnóstico:** ver `logs/zc.log` para el traceback.

**Fix:**

1. En la topbar, click **Desconectar**.
2. Verificar que TIA Portal sigue abierto y el proyecto está
   cargado.
3. Click **Conectar** de nuevo.

## 10. "Tests fallan con `expected str, bytes or os.PathLike object, not NoneType`"

**Síntoma:** pytest falla con `TypeError: expected str, bytes or
os.PathLike object, not NoneType` en tests que tocan
`ConfigManager` o paths.

**Causa típica:** `ConfigManager()` se instancia sin argumentos y
asume que el `cwd` es la raíz del repo. Si corres pytest desde
otra carpeta, los paths resuelven a `None`.

**Fix:**

```powershell
# Asegurarse de correr pytest desde la raíz del repo
cd "D:\ruta\a\zc-automation-suite"
python -m pytest tests/ -q
```

Si lo corres desde otra carpeta (e.g. `tests/`), los tests fallan.
