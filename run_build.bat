@echo off
python build_exe.py
set BUILD_RC=%ERRORLEVEL%
echo.
if %BUILD_RC% NEQ 0 (
    echo =========================================
    echo       BUILD FALLO (codigo %BUILD_RC%)
    echo =========================================
    echo  Revisa el output de arriba. Causas habituales:
    echo    - Python 3.12/3.13/3.14 no esta instalado.
    echo    - PyInstaller no instalado (pip install -e ".[build]").
    echo    - Wheel de Siemens no instalada (ver docs\INSTALAR.md).
    echo    - Node.js no instalado o npm no esta en el PATH.
    echo    - npm ci / npm run build han fallado.
) else (
    echo =========================================
    echo       BUILD OK
    echo =========================================
    echo  El ejecutable esta en dist\zc_automation_suite.exe
)
echo.
pause
