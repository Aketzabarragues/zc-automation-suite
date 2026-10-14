# ONBOARDING — Guía paso a paso para un técnico nuevo

Esta guía es leíble **sin haber leído `AGENTS.md` antes**. Cubre el
flujo completo desde clonar el repo hasta abrir `?demo=1` en el
navegador. Las reglas arquitectónicas detalladas viven en `AGENTS.md`
(al que se enlaza al final de cada bloque).

> Audiencia: técnico con TIA Portal instalado y experiencia en
> Python 3.12+, Git y PowerShell.

## 1. Requisitos del sistema

| Componente | Versión | Notas |
|---|---|---|
| Windows | 10 / 11 | El worker OT usa COM/.NET; solo Windows. |
| Python | 3.12 / 3.13 / 3.14 | NO 3.11 ni anteriores. TIA Scripting no publica wheel para 3.11. |
| PowerShell | 5.1+ (recomendado 7+) | Para los `.bat` de arranque y compilación. |
| Git para Windows | cualquiera | Para clonar y contribuir. |
| TIA Portal | V15.1+ | El worker OT detecta la versión por las DLLs `OpennessApi{15_1..21_1}.dll` del SDK. |
| Microsoft Visual C++ Redistributable | el que instala TIA Portal | Lo trae TIA; no hace falta instalar aparte. |
| RAM / disco | 8 GB / 500 MB libres | El `.venv` + `dist/.exe` pesan ~200 MB. |

## 2. Clonar el repositorio

```powershell
git clone https://github.com/Aketzabarragues/zc-automation-suite.git
cd zc-automation-suite
```

Tras el `clone`, el directorio raíz contiene `AGENTS.md` (reglas
arquitectónicas), `.clinerules` (reglas críticas cortas) y
`.opencode/` (configuración de sub-agentes y skills si usas OpenCode).

## 3. Preparar el entorno virtual

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-dev.txt
```

Esto instala: PyYAML, Pillow, openpyxl, pyinstaller, pystray,
werkzeug (runtime) y pytest (dev). **NO** incluye la wheel de
Siemens — va en el paso siguiente.

## 4. Instalar la wheel de `siemens_tia_scripting` desde `vendor/`

El SDK 1.4.3 de TIA Scripting viene empaquetado en `vendor/`. Hay
tres wheels, una por cada versión de Python soportada:

- `vendor/install/siemens_tia_scripting-1.4.3-cp312-cp312-win_amd64.whl`
- `vendor/install/siemens_tia_scripting-1.4.3-cp313-cp313-win_amd64.whl`
- `vendor/install/siemens_tia_scripting-1.4.3-cp314-cp314-win_amd64.whl`

Con el venv activado:

```powershell
# Sustituir cp3XX por la versión de tu Python activo
pip install vendor/install/siemens_tia_scripting-1.4.3-cp3XX-cp3XX-win_amd64.whl

# Verificación
python -c "import siemens_tia_scripting"
```

Si `pip install` falla con un error de ABI, tu Python activo no
coincide con la wheel. Averigua tu versión con `python --version`
y elige la wheel `cp3XX` que coincida.

> ⚠️ La wheel es **propietaria de Siemens** (EULA). El repo es
> privado, por lo que commitear los binarios en `vendor/` es
> aceptable para uso interno del equipo. Si el repo pasa a ser
> público, `vendor/` debe ignorarse y cada técnico copia los
> assets manualmente.

## 5. Recompilar Tailwind (solo si tocas CSS)

`tailwindcss-extra.exe` es un binario del operario y **no está en
el repo** (`.gitignore` lo excluye). Si lo necesitas, pídeselo al
equipo y colócalo en la raíz del repo.

```powershell
.\run_tailwind.bat
```

El bat apunta a `core/web_server/static/src/input.css` (verificado
con `ls`; el path `interfaces/web_server/...` quedó obsoleto tras
PR 7).

## 6. Correr los tests

```powershell
python -m pytest tests/ -q
```

**Resultado esperado:** 1114 verde, 3 skipped. Los `skipped` son
intencionales (tests condicionales que no aplican en el entorno
actual).

Si ves fallos, son tests nuevos que no se han estabilizado.
Reporta al equipo antes de tocar nada.

## 7. Primer arranque de la app (sin TIA)

```powershell
python main.py
```

Esto abre la bandeja del sistema. Click derecho → **Iniciar web**.
Se abrirá `http://127.0.0.1:9484/` en tu navegador por defecto.

Para QA sin TIA Portal:

```
http://127.0.0.1:9484/?demo=1
```

`?demo=1` mockea el cliente TIA: ningún `attach_portal` se intenta.
Verás la SPA con datos sintéticos del área de alimentación.

## 8. Primer arranque contra TIA Portal real

1. Abre TIA Portal y carga un proyecto (cualquier PLC, V15.1+).
2. Lanza la app con `python main.py` (paso 7).
3. En la topbar de la SPA, click **Conectar**. Aparece un modal
   pidiendo confirmación; acepta. La app hace `attach_portal` al
   proceso TIA ya abierto.
4. Si TIA no está abierto o ya hay otro attach, el modal muestra
   el error y un hint accionable ("Abre TIA Portal primero", etc.).

## 9. ¿Y ahora qué?

| Quiero... | Ir a |
|---|---|
| Añadir un dispositivo nuevo | `docs/HOWTO_ADD_DEVICE.md` |
| Añadir un área nueva | `docs/HOWTO_CREATE_AREA.md` |
| Añadir un FB (Function Block) | `docs/HOWTO_CREATE_FB.md` |
| Diagnosticar un problema | `docs/TROUBLESHOOTING.md` |
| Reglas para contribuir | `CONTRIBUTING.md` |
| Entender las reglas del proyecto | `AGENTS.md` + `.clinerules` |
| Empaquetar el .exe | `build_exe.py` + sección 7 de `README.md` |
