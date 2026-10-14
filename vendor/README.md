# vendor/ — assets propietarios de terceros

Esta carpeta contiene binarios y wheels **propietarios** que el
proyecto necesita en runtime o build, pero que **no se distribuyen
vía `requirements.txt`** (por licensing o tamaño).

## Contenido

| Subcarpeta / archivo | Qué contiene | Tamaño | Notas |
|---|---|---|---|
| `siemens_tia_scripting.pyd` | Binario nativo Python (wrapper del SDK de TIA Openness) | 900 KB | Nombre canónico; el loader OT lo busca así en runtime. |
| `siemens_tia_scripting-1.4.3-cp3XX-...whl` (3) | Wheels para Python 3.12 / 3.13 / 3.14 | 4.5 MB | `pip install vendor/install/<wheel>.whl` durante setup. |
| `Siemens.TiaPortal.OpennessApi{15_1..21_1}.dll` (9) | Wrappers .NET del SDK Openness de Siemens, uno por cada TIA Portal soportado (V15.1 a V21.1) | 3.0 MB | Stageados por `build_exe.py` desde `site-packages/` tras `pip install`. |
| `Siemens.TiaPortal.OpennessAdapter.dll` | Adaptador Openness (.NET) | 35 KB | Stageado por `build_exe.py`. |
| `Siemens.TiaPortal.OpennessContracts.dll` | Contratos Openness (.NET) | 52 KB | Stageado por `build_exe.py`. |
| `log4net.dll` + `log4net.xml` | Implementación de logging y su config | 1.7 MB | Necesarios para el logging del worker OT. |
| `oss/ReadMe_OSS.html` | Disclosure de componentes OSS usados por el SDK de Siemens (compliance) | 47 KB | Conservar para auditoría de licencias. |
| `example_workflows/*.py` (6) | Ejemplos oficiales de uso del SDK de Siemens (export PLC, export HMI, etc.) | 17 KB | **Referencia.** El proyecto no los importa; están aquí para que un técnico nuevo vea patrones de uso del SDK. |
| `docs/*.pdf` (2) | Manual oficial del SDK (V1.4.3, EN + DE) | 7.1 MB | **NO commiteados.** Descargar de Siemens si se necesitan. |

## Cómo se usa

1. **Setup del técnico nuevo** (ver `docs/ONBOARDING.md` §4):

   ```powershell
   .\.venv\Scripts\Activate.ps1
   pip install vendor/install/siemens_tia_scripting-1.4.3-cp3XX-cp3XX-win_amd64.whl
   python -c "import siemens_tia_scripting"   # debe funcionar sin ImportError
   ```

2. **Build del `.exe`** (ver `docs/ONBOARDING.md` §6):

   ```powershell
   python build_exe.py
   ```

   `build_exe.py` resuelve los binarios desde `site-packages/` (donde
   `pip install` los dejó) y los stagea en un tempdir para PyInstaller.
   `vendor/` actúa como **fuente de las wheels** durante el setup;
   no es la fuente directa de `build_exe.py`.

## Mantenimiento

- **Actualizar el SDK**: descargar la nueva versión del SDK desde
  Siemens, reemplazar wheels en `vendor/install/`, reemplazar
  binarios en `vendor/`, actualizar versión en este README.
- **Licencia**: el repo es MIT propio. Los assets de Siemens son
  propietarios (EULA de Siemens). **No publicar el repo en abierto**;
  la redistribución pública de estos binarios viola la EULA.
- **Debug symbols (`*.pdb`)** y artefactos de linkado (`*.exp`,
  `*.lib`) NO se commitean (están excluidos por `.gitignore`).
