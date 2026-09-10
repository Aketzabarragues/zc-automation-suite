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
    echo    - PyInstaller no instalado (pip install pyinstaller).
    echo    - Wheel de Siemens no instalada.
    echo    - Falta el icono del exe en launcher\icon.ico.
) else (
    echo =========================================
    echo       BUILD OK
    echo =========================================
)
echo.
pause
