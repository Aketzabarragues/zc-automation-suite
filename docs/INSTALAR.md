# Instalar

## Que hace falta

| Requisito | Version | Para que |
|---|---|---|
| Windows | 10 u 11 | la app es de escritorio |
| Python | 3.12, 3.13 o 3.14 | backend |
| Node.js | 22 o superior | solo para el frontend en desarrollo |
| TIA Portal | V15.1 a V21.1 | operacion contra el PLC |
| Wheel de Siemens `siemens_tia_scripting` | 1.4.3 | SDK oficial de TIA Scripting |

La wheel de Siemens **no esta en PyPI**: es un binario propietario que se
entrega con el SDK de TIA Scripting. Sin ella la app arranca y se puede
usar en modo demo, pero no hay conexion con TIA Portal.

## Instalar la wheel de Siemens

1. Descarga el SDK de TIA Scripting desde el portal de soporte de Siemens
   (tu Cuenta Siemens > "TIA Scripting"). Necesitas el paquete que incluye
   las wheels para Python.
2. Instala la wheel que corresponda a tu version de Python. Los nombres
   llevan el tag de ABI:

   ```
   siemens_tia_scripting-1.4.3-cp312-cp312-win_amd64.whl
   siemens_tia_scripting-1.4.3-cp313-cp313-win_amd64.whl
   siemens_tia_scripting-1.4.3-cp314-cp314-win_amd64.whl
   ```

   El `cpXY` del nombre tiene que coincidir con tu `python -V`.

   ```bash
   pip install vendor/install/siemens_tia_scripting-1.4.3-cp312-cp312-win_amd64.whl
   ```

3. Comprueba que la wheel quedo bien puesta:

   ```bash
   python -c "import siemens_tia_scripting as ts; print(ts.__version__)"
   ```

   Debe imprimir la version de la wheel que has instalado. La app usa la
   **1.4.3**, que es la que lleva el `.exe` y la que soporta TIA Portal
   V21.1. Si imprime otra, actualiza:

   ```bash
   pip install --no-index --no-deps --force-reinstall vendor/install/siemens_tia_scripting-1.4.3-cp312-cp312-win_amd64.whl
   ```

   Para ver tambien de donde se ha cargado:

   ```bash
   python -c "import siemens_tia_scripting as ts; print(ts.__version__, ts.__file__)"
   ```

   En el mismo directorio estan las `.dll` del SDK Openness y el
   `log4net.dll`: la app los stagea sola en un directorio temporal al
   arrancar.

## Sobre pythonnet

**No hace falta.** El `.pyd` de `siemens_tia_scripting` es autonomo: trae su
propia integracion con .NET y carga el CLR sin `pythonnet` instalado. Se ha
verificado en un venv limpio con solo la wheel de Siemens: el import del
wrapper y el acceso a los enums (que inicializa el CLR) funcionan igual.

No lo anadas al proyecto: si lo instalas, es ruido.

## Instalar el proyecto

```bash
git clone https://github.com/Aketzabarragues/zc-automation-suite.git
cd zc-automation-suite

python -m venv .venv
.venv\Scripts\activate

pip install -e ".[dev]"
```

## Instalar el frontend

```bash
cd frontend
npm install
cd ..
```

## Arrancar en desarrollo

```bash
python iniciar.py
```

Levanta el backend (Flask) y el servidor de Vite, y abre el navegador. La
app funciona sin TIA en modo demo: `http://127.0.0.1:5173/?demo=1`.

## Compilar el ejecutable

```bash
python build_exe.py
```

El resultado queda en `dist/`. El `.exe` no necesita Python instalado ni
Node: el frontend va embebido.

## Comprobar la instalacion

```bash
python -m pytest tests/ -v
python -m ruff check .
cd frontend && npm test && cd ..
```
