@echo off
REM run_tray.bat - Lanza main_tray.py SIN ventana de consola.
REM
REM Doble clic sobre este .bat y el tray aparece en la bandeja sin
REM que se abra ninguna terminal negra. Es el equivalente en dev de
REM lo que hara el .exe empaquetado en Fase 2.
REM
REM Implementacion: usa `start /B` de cmd, que lanza pythonw.exe
REM (la version sin consola de Python) en background y devuelve
REM el control inmediatamente, sin anclar una ventana de cmd.

REM Cambiar al directorio del .bat para que las rutas relativas
REM (launcher/icon.ico, etc.) funcionen.
cd /d "%~dp0"

REM Lanzar pythonw.exe en background. /B = no crear ventana nueva.
REM Si pythonw.exe no esta en PATH, intenta la ruta por defecto de
REM Python 3.12 en Windows.
where pythonw.exe >nul 2>nul
if %ERRORLEVEL%==0 (
    start /B pythonw.exe main_tray.py
) else (
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" (
        start /B "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" main_tray.py
    ) else (
        echo No se encontro pythonw.exe en PATH ni en la instalacion por defecto.
        echo Instala Python 3.12 o ajusta este script.
        pause
        exit /b 1
    )
)
