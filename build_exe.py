"""Orquestador PyInstaller para ``zc-automation-suite``.

Compila ``backend/zc_suite/main.py`` en ``dist/zc_automation_suite.exe`` con
TODO lo necesario para ejecutar la app en produccion, incluyendo el binario
nativo de Siemens (``.pyd``) y sus dependencias (``.dll`` / ``.xml``)
resueltos dinamicamente desde el interprete Python actual (3.12 / 3.13 /
3.14).

Restricciones aplicadas (decisiones arquitectónicas del proyecto):

  - **Cero Codigo Sucio**: ni el ``.pyd`` ni las ``.dll``/``.xml`` se copian
    al directorio de trabajo. Se stagean en un directorio temporal creado con
    ``tempfile.mkdtemp(prefix="zc_build_")``.

  - **Carga dinamica oficial**: ``zc_suite.tia.cargar_modulo_tia()`` importa
    ``siemens_tia_scripting``. En un ejecutable congelado, el import solo
    encuentra el modulo si el ``.pyd`` esta en la **raiz de** ``sys._MEIPASS``.
    Por eso **el ``.pyd`` y TODAS las ``.dll`` van a la raiz de
    ``_MEIPASS``** (no en subcarpetas ``vendor/``). Las ``.xml`` (log4net)
    tambien.

  - **De donde salen los binarios de Siemens**: de la **wheel instalada**.
    ``importlib.util.find_spec("siemens_tia_scripting")`` da el ``.pyd`` que
    pip descomprimio en ``site-packages``; las ``.dll`` y los ``.xml`` que
    lo acompanan son los que estan **en la misma carpeta**. No hay carpeta
    ``vendor/`` en este repo: los binarios proprietarios de Siemens no se
    versionan (ver ``.gitignore``). La regla queda escrita aqui y en
    ``collect_vendor_assets()``.

  - **UPX excluido para ``*.dll`` y ``*.pyd``**: UPX corrompe los ensamblados
    .NET nativos. Critico; sin esto, el import de ``siemens_tia_scripting``
    muere con ``ImportError``.

  - **Entry = ``backend/zc_suite/main.py``**: el ``.exe`` arranca con la
    bandeja (pystray) y el web server. ``console=False``, ``windowed``.

  - **Auto-generacion del ``.spec``**: el spec se genera programaticamente
    en el mismo tempdir de staging y se borra en ``finally``. No es un
    archivo tracked.

  - **Los datos van junto al ``.exe``, nunca en ``_MEIPASS``**: el
    ``config.json`` del operario, la copia del Excel maestro
    (``excel/``) y el ``.build_cache`` se escriben en la carpeta del
    ejecutable. ``_MEIPASS`` se recrea en cada arranque: ahi no se puede
    guardar nada. Lo resuelven ``zc_suite.nucleo.app.config``, ``zc_suite.nucleo.tia.workdir`` y
    ``zc_suite.areas.alimentacion.excel.almacen``, que miran
    ``sys.frozen``.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from textwrap import dedent
from typing import Any

try:
    import psutil  # type: ignore[import-not-found]
    _HAS_PSUTIL = True
except ImportError:
    psutil = None  # type: ignore[assignment]
    _HAS_PSUTIL = False


# ── Forzar UTF-8 en stdout/stderr (mismo patron que el nucleo) ─────────────
# Sin esto, Windows imprime por cp1252 y revienta con caracteres
# acentuados, flechas, etc. que usamos en los mensajes del report.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, Exception):
        sys.stdout = io.TextIOWrapper(  # type: ignore[assignment]
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )
        sys.stderr = io.TextIOWrapper(  # type: ignore[assignment]
            sys.stderr.buffer, encoding="utf-8", errors="replace"
        )


# ── Constantes ──────────────────────────────────────────────────────────────

#: Raiz del repo.
ROOT = Path(__file__).resolve().parent

#: El paquete del nucleo, para poder importar sus modulos.
BACKEND_DIR = "backend"

if str(ROOT / BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT / BACKEND_DIR))

from zc_suite.nucleo.app.icono import generar_ico  # noqa: E402

#: Nombre del ejecutable, sin extension.
EXE_NAME = "zc_automation_suite"

#: Nombre canonico del binario de Siemens dentro del bundle.
PYD_CANONICAL_NAME = "siemens_tia_scripting.pyd"

#: Prefijo del tempdir de staging.
STAGING_PREFIX = "zc_build_"

#: Versiones de Python con las que hay wheel oficial de Siemens.
SUPPORTED_PYTHONS: list[tuple[int, int]] = [(3, 12), (3, 13), (3, 14)]

#: Entry del ``.exe``: el modulo ``main`` del paquete.
ENTRY_SCRIPT = "backend/zc_suite/main.py"

#: Carpeta del frontend, con su ``package.json``.
FRONTEND_DIR = "frontend"

#: La SPA compilada. ``zc_suite.nucleo.web.app.ruta_dist_frontend()`` la busca en
#: ``_MEIPASS/frontend/dist`` cuando la app esta congelada.
DIST_FRONTEND = "frontend/dist"

#: La plantilla del ``config.json``. ``zc_suite.nucleo.app.config.ruta_plantilla()`` la
#: busca en ``_MEIPASS/config/config.json`` cuando la app esta congelada.
CONFIG_PLANTILLA = "config/config.json"

#: Datos del proyecto que se bundlean dentro de _MEIPASS, conservando la
#: MISMA ruta relativa que el codigo espera en runtime.
#
# Convencion de PyInstaller ``--add-data``:
#   ``(ruta_origen_absoluta, directorio_destino_en_bundle)``
# El segundo elemento es el DIRECTORIO dentro de ``_MEIPASS`` donde se
# deposita el archivo, NO la ruta completa del archivo. Si se pusiera la
# ruta completa del archivo, PyInstaller crearia un directorio anidado
# ``_MEIPASS\frontend\dist\frontend\dist`` con un ``\dist`` extra al
# final.
PROJECT_DATA_FILES: list[tuple[str, str]] = [
    (DIST_FRONTEND, DIST_FRONTEND),
    (CONFIG_PLANTILLA, "config"),
]


# ── El icono del ejecutable ────────────────────────────────────────────────
#
#: No hay un ``.ico`` en el repo: el icono se dibuja en el momento de
#: empaquetar (el mismo "ZC" que lleva la bandeja). Ver
#: ``zc_suite.nucleo.app.icono``.


# ── Hiddenimports ───────────────────────────────────────────────────────────

#: Modulos que PyInstaller no detecta de forma estatica.
#:
#: - Los de Siemens: el ``.pyd`` se importa en runtime, no en analisis.
#: - Los de las areas: se registran en la lista ``AREAS`` de
#:   ``zc_suite.nucleo.app.main`` y sus modulos se importan desde ahi.
HIDDEN_IMPORTS_BASE: list[str] = [
    # ── Siemens / Pythonnet (hilo de TIA) ──────────────────────────────
    "siemens_tia_scripting",
    "pythonnet",
    "clr",
    # ── Excel (parser del maestro) ──────────────────────────────────────
    "openpyxl",
    "openpyxl.cell._writer",
    # ── Bandeja (pystray + Pillow) ──────────────────────────────────────
    "pystray",
    "pystray._win32",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageFont",
    "PIL._imaging",
    # ── Estandar de la app ──────────────────────────────────────────────
    "asyncio",
    "asyncio.windows_utils",
    "webbrowser",
]


def ids_de_areas() -> list[str]:
    """Los identificadores de las areas registradas en ``AREAS``.

    Returns:
        La lista de ids, en el orden de la lista ``AREAS``.

    Raises:
        RuntimeError: si el paquete del nucleo no se puede importar.
    """
    if str(ROOT / BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT / BACKEND_DIR))
    try:
        from zc_suite.nucleo.app.main import AREAS
    except Exception as exc:
        raise RuntimeError(
            f"No se pudo importar 'zc_suite.nucleo.app.main' para leer la lista AREAS: {exc}. "
            "Instala el backend con: pip install -e \".[dev]\""
        ) from exc
    return [str(area.ID) for area in AREAS]

def _scan_hiddenimports() -> list[str]:
    """Escanea las areas registradas y devuelve los modulos a bundlear.

    Genera entradas como ``"zc_suite.areas.alimentacion"`` y
    ``"zc_suite.areas.alimentacion.excel.parser"`` (sin la extension
    ``.py``). Excluye ``__pycache__/``.

    Por que hay que escanear: la lista ``AREAS`` de ``zc_suite.nucleo.app.main``
    importa los areas, pero PyInstaller solo ve lo que se importa de forma
    estatica en el entry. Declarar los modulos de cada area aqui
    garantiza que el ``.exe`` los lleva aunque el area se registre por
    codigo.

    Returns:
        Lista de nombres de modulos Python ordenados y deduplicados.
    """
    vistos: set[str] = set()
    lista: list[str] = []

    def _add(modulo: str) -> None:
        if modulo and modulo not in vistos:
            vistos.add(modulo)
            lista.append(modulo)

    _add("zc_suite")
    _add("zc_suite.areas")

    for id_area in ids_de_areas():
        raiz = ROOT / BACKEND_DIR / "zc_suite" / "areas" / id_area
        if not raiz.is_dir():
            continue
        for fichero in sorted(raiz.rglob("*.py")):
            if "__pycache__" in fichero.parts:
                continue
            relativo = fichero.relative_to(ROOT / BACKEND_DIR).with_suffix("")
            if relativo.name == "__init__":
                _add(".".join(relativo.parent.parts))
            else:
                _add(".".join(relativo.parts))

    return lista


def _py_repr_hiddenimports(modulos: list[str]) -> str:
    """Literal Python para la lista de ``hiddenimports``.

    Shape: ``'a', 'b', 'c'``.
    """
    return ",\n            ".join(f"'{modulo}'" for modulo in modulos)


# ── La plantilla del .spec ──────────────────────────────────────────────────

SPEC_TEMPLATE = dedent(
    '''\
    # -*- mode: python ; coding: utf-8 -*-
    # AUTO-GENERATED por build_exe.py — NO EDITAR A MANO.
    # Vive en el tempdir de staging y se borra tras el build.

    import sys as _sys
    from pathlib import Path as _P
    block_cipher = None

    # Rutas resueltas por build_exe.py antes de invocar PyInstaller
    _STAGING = r"{staging_dir}"
    _VENDOR  = r"{vendor_dir}"
    _ROOT    = r"{project_root}"

    # ── Binarios nativos de Siemens (.pyd + .dll) ─────────────────
    # TODOS a la raiz de _MEIPASS: el import de
    # ``siemens_tia_scripting`` solo encuentra el modulo si esta en la
    # raiz del bundle. En subcarpetas falla con ModuleNotFoundError.
    _siemens_binaries = [
        (str(_P(_VENDOR) / "siemens_tia_scripting.pyd"), "."),
    ]
    for _dll in {dll_list_py}:
        _siemens_binaries.append((_dll, "."))

    # Datos (XMLs de log4net, esquemas Siemens): tambien a la raiz por
    # convencion del loader nativo.
    _siemens_datas = []
    for _xml in {xml_list_py}:
        _siemens_datas.append((_xml, "."))

    # Datos del proyecto (SPA, plantilla de config). Se preserva la
    # ruta relativa para que el codigo la resuelva igual en frozen.
    _project_datas = {project_datas_py}

    a = Analysis(
        [str(_P(_ROOT) / {entry_script_py!r})],
        pathex=[str(_P(_ROOT) / {backend_dir_py!r})],
        binaries=_siemens_binaries,
        datas=_siemens_datas + _project_datas,
        hiddenimports=[
            # ── Siemens / Pythonnet (hilo de TIA) ──────────────────────
            'siemens_tia_scripting', 'pythonnet', 'clr',
            # ── Excel (parsers) ─────────────────────────────────────────
            'openpyxl', 'openpyxl.cell._writer',
            # ── Bandeja ─────────────────────────────────────────────────
            'pystray', 'pystray._win32', 'PIL', 'PIL.Image',
            'PIL.ImageDraw', 'PIL.ImageFont', 'PIL._imaging',
            # ── Estandar ────────────────────────────────────────────────
            'asyncio', 'asyncio.windows_utils', 'webbrowser',
            # ── Areas registradas en AREAS ──────────────────────────────
            {hiddenimports_areas_py}
        ],
        excludes=[
            # El entry se incluye via ENTRY_SCRIPT (entry del .exe);
            # PyInstaller lo empaqueta automaticamente. No excluir.
            # Dev/test/tamano
            'pytest', 'unittest', 'matplotlib', 'numpy.tests',
            'pandas.tests', 'tkinter', 'test', 'tests',
            'scipy', 'IPython', 'jupyter', 'notebook',
        ],
        cipher=block_cipher,
        noarchive=False,
    )
    pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name={exe_name_py!r},
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[
            # CRITICO: UPX corrompe DLLs nativas .NET y el .pyd de Siemens
            'siemens_tia_scripting.pyd',
            'python312.dll', 'python313.dll', 'python314.dll',
            'vcruntime140*.dll', 'msvcp140*.dll',
            '*.dll',  # wildcard defensivo
            '*.pyd',
        ],
        runtime_tmpdir=None,
        console=False,  # WINDOWED: el entry arranca la bandeja y el web
        disable_windowed_traceback=False,
        icon={exe_icon_py!r},
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    # Modo --onefile: NO hay bloque COLLECT(...)
    '''
)


def _py_repr_path(path: Path) -> str:
    r"""Devuelve un literal Python raw-string (sin comillas) para una ruta.

    El caller es responsable de envolver el resultado en ``r"..."``. Esta
    funcion solo escapa comillas dobles (imposibles en nombres de fichero
    Windows) para que el caller pueda usarlas con seguridad.
    """
    texto = str(path)
    if '"' in texto:
        texto = texto.replace('"', '\\"')
    return texto


def _py_repr_path_list(paths: list[Path]) -> str:
    """Literal Python para una lista de rutas (``[r"a", r"b"]``)."""
    if not paths:
        return "[]"
    return "[" + ", ".join(f'r"{_py_repr_path(path)}"' for path in paths) + "]"


def _py_repr_project_datas(files: list[tuple[str, str]]) -> str:
    """Literal Python para la lista de ``--add-data`` del proyecto.

    Shape: ``[(r"<src>", "<dst>"), ...]``.
    """
    if not files:
        return "[]"
    items = []
    for origen_rel, destino_rel in files:
        origen = (ROOT / origen_rel).resolve()
        items.append(f'(r"{_py_repr_path(origen)}", {destino_rel!r})')
    return "[" + ", ".join(items) + "]"


def write_generated_spec_file(
    staging_root: Path,
    vendor_dir: Path,
    dlls: list[Path],
    xmls: list[Path],
    exe_icon: Path,
) -> Path:
    """Vuelca la plantilla del ``.spec`` con las rutas resueltas.

    Returns:
        Ruta absoluta al ``.spec`` recien creado (dentro de
        ``staging_root``, se borra en ``finally``).
    """
    spec_path = staging_root / f"{EXE_NAME}.spec"

    dlls_en_vendor = [vendor_dir / dll.name for dll in dlls]
    xmls_en_vendor = [vendor_dir / xml.name for xml in xmls]

    content = SPEC_TEMPLATE.format(
        staging_dir=_py_repr_path(staging_root),
        vendor_dir=_py_repr_path(vendor_dir),
        project_root=_py_repr_path(ROOT),
        backend_dir_py=BACKEND_DIR,
        dll_list_py=_py_repr_path_list(dlls_en_vendor),
        xml_list_py=_py_repr_path_list(xmls_en_vendor),
        project_datas_py=_py_repr_project_datas(PROJECT_DATA_FILES),
        hiddenimports_areas_py=_py_repr_hiddenimports(_scan_hiddenimports()),
        entry_script_py=ENTRY_SCRIPT,
        exe_name_py=EXE_NAME,
        exe_icon_py=_py_repr_path(exe_icon),
    )

    spec_path.write_text(content, encoding="utf-8")
    print(f"[OK] .spec auto-generado: {spec_path.name}")
    return spec_path


# ── Etapa 0: validacion ─────────────────────────────────────────────────────


def check_python_version() -> None:
    """Valida que el interprete actual sea 3.12, 3.13 o 3.14.

    TIA Scripting requiere estas versiones (la wheel oficial no se publica
    para 3.11 ni anteriores).
    """
    major, minor = sys.version_info[:2]
    if (major, minor) not in SUPPORTED_PYTHONS:
        print(
            f"[ERROR] Python {major}.{minor} no soportado. "
            f"Requerido: {', '.join(f'{a}.{b}' for a, b in SUPPORTED_PYTHONS)}."
        )
        sys.exit(1)
    print(f"[OK] Python {major}.{minor} detectado (compatible)")


def ensure_pyinstaller() -> None:
    """Falla rapido con mensaje accionable si PyInstaller no esta disponible."""
    if importlib.util.find_spec("PyInstaller") is None:
        raise RuntimeError(
            "PyInstaller no esta instalado en el interprete actual. "
            "Ejecuta: pip install -e \".[build]\""
        )
    print("[OK] PyInstaller disponible")


def ensure_node() -> None:
    """Falla rapido con mensaje accionable si node o npm no estan.

    El frontend se compila antes de empaquetar: el ``.exe`` lleva la SPA
    dentro, no la compila al arrancar.
    """
    if shutil.which("npm") is None and shutil.which("npm.cmd") is None:
        raise RuntimeError(
            "No se encontro 'npm' en el PATH. Instala Node.js 22+ "
            "y vuelve a ejecutar el build."
        )
    print("[OK] npm disponible")


def ensure_siemens_wheel() -> Path:
    """Comprueba que la wheel de Siemens este y devuelve el ``.pyd``.

    Returns:
        La ruta del ``.pyd`` instalado.

    Raises:
        FileNotFoundError: si la wheel no esta instalada.
    """
    try:
        return resolve_siemens_pyd()
    except FileNotFoundError as exc:
        raise RuntimeError(str(exc)) from exc


# ── Etapa 1: el frontend ────────────────────────────────────────────────────


def build_frontend() -> Path:
    """Compila la SPA: ``npm ci`` y ``npm run build``.

    Returns:
        La carpeta ``frontend/dist``.

    Raises:
        RuntimeError: si npm falla o si la build no deja el ``index.html``.
    """
    carpeta = ROOT / FRONTEND_DIR
    if not (carpeta / "package.json").is_file():
        raise RuntimeError(f"No se encontro {carpeta / 'package.json'}.")

    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if npm is None:
        raise RuntimeError("No se encontro 'npm' en el PATH.")

    tiene_lock = (carpeta / "package-lock.json").is_file()
    instalacion = ["ci"] if tiene_lock else ["install"]
    print(f"[BUILD] Frontend: npm {instalacion[0]}")
    resultado = subprocess.run([npm, *instalacion], cwd=carpeta, check=False)
    if resultado.returncode != 0:
        raise RuntimeError(
            f"'npm {instalacion[0]}' fallo con codigo {resultado.returncode}. "
            "Revisa la salida de npm."
        )

    print("[BUILD] Frontend: npm run build")
    resultado = subprocess.run(
        [npm, "run", "build"],
        cwd=carpeta,
        check=False,
    )
    if resultado.returncode != 0:
        raise RuntimeError(
            f"'npm run build' fallo con codigo {resultado.returncode}. "
            "Revisa la salida de npm."
        )

    dist = ROOT / DIST_FRONTEND
    if not (dist / "index.html").is_file():
        raise RuntimeError(
            f"La build del frontend no dejo {dist / 'index.html'}. "
            "El .exe no se puede generar sin la SPA."
        )
    print(f"[OK] SPA compilada en {dist}")
    return dist


# ── Etapa 2: los assets de Siemens ──────────────────────────────────────────


def resolve_siemens_pyd() -> Path:
    """Localiza el ``.pyd`` de ``siemens_tia_scripting`` en el venv actual.

    Returns:
        Ruta absoluta al archivo ``.pyd`` (puede tener ABI tag, ej.
        ``siemens_tia_scripting.cp314-win_amd64.pyd``).

    Raises:
        FileNotFoundError: Si la wheel no esta instalada.
    """
    spec = importlib.util.find_spec("siemens_tia_scripting")
    if spec is None or not spec.origin:
        raise FileNotFoundError(
            "No se pudo resolver 'siemens_tia_scripting' en el interprete "
            "actual. Esta instalada la wheel oficial?\n"
            "  pip install vendor/install/siemens_tia_scripting-<version>"
            "-cp3XX-cp3XX-win_amd64.whl\n"
            "  Ver docs/INSTALAR.md"
        )
    pyd_path = Path(spec.origin)
    if not pyd_path.is_file():
        raise FileNotFoundError(f"El binario resuelto no existe en disco: {pyd_path}")
    return pyd_path


def collect_vendor_assets(pyd_path: Path) -> tuple[Path, list[Path], list[Path]]:
    """Separa los assets de la wheel en (``.pyd``, ``.dll``, ``.xml``).

    **La regla**: los binarios de Siemens son los que estan **en la misma
    carpeta que el ``.pyd`` que instala pip**. La wheel descomprime el
    ``.pyd``, las ``.dll`` de Openness y el ``.xml`` de log4net en
    ``site-packages``. No hay carpeta ``vendor/`` en este repo: los binarios
    proprietarios de Siemens no se versionan.

    Args:
        pyd_path: Ruta al ``.pyd`` resuelta por ``resolve_siemens_pyd``.

    Returns:
        Tupla ``(pyd_path, dlls, xmls)`` con rutas absolutas.
    """
    base_dir = pyd_path.parent
    dlls = sorted(p for p in base_dir.glob("*.dll") if p.is_file())
    xmls = sorted(p for p in base_dir.glob("*.xml") if p.is_file())
    return pyd_path, dlls, xmls


def stage_vendor_assets(
    pyd_path: Path,
    dlls: list[Path],
    xmls: list[Path],
) -> tuple[Path, Path]:
    """Copia el ``.pyd`` (renombrado a canonico) + ``.dll`` + ``.xml``
    a un directorio temporal dentro de un staging raiz.

    El staging raiz es un subdirectorio del tempdir del sistema, NO del
    repo. Cumple "Cero Codigo Sucio": la raiz del repo queda intacta tras
    el build.

    Returns:
        Tupla ``(staging_root, vendor_dir)``.
    """
    staging_root = Path(tempfile.mkdtemp(prefix=STAGING_PREFIX))
    vendor_dir = staging_root / "vendor"
    vendor_dir.mkdir(parents=True, exist_ok=True)

    staged_pyd = vendor_dir / PYD_CANONICAL_NAME
    shutil.copy2(pyd_path, staged_pyd)
    print(f"[OK] .pyd stageado: {staged_pyd.name}")

    for dll in dlls:
        shutil.copy2(dll, vendor_dir / dll.name)
        print(f"[OK] .dll stageada: {dll.name}")

    for xml in xmls:
        shutil.copy2(xml, vendor_dir / xml.name)
        print(f"[OK] .xml stageado: {xml.name}")

    if not dlls:
        print(
            "[WARN] La wheel no trae .dll acompañantes; el hilo de TIA "
            "puede fallar al cargar CLR/Pythonnet."
        )
    if not xmls:
        print(
            "[WARN] La wheel no trae .xml acompañantes; log4net puede "
            "quejarse en el log."
        )

    return staging_root, vendor_dir


# ── Etapa 3: build ──────────────────────────────────────────────────────────


def clean_build_dirs() -> None:
    """Elimina carpetas de builds anteriores (idempotente)."""
    for carpeta in ["build", "dist"]:
        ruta = ROOT / carpeta
        if ruta.exists():
            print(f"[CLEAN] Limpiando {carpeta}/...")
            shutil.rmtree(ruta, ignore_errors=True)


# ── Deteccion de procesos bloqueantes (Windows-friendly) ───────────────────
#
# Patrones de nombre de proceso que pueden tener locks sobre los assets de
# Siemens (``.pyd``/``.dll``/``.xml``) o sobre el ``.exe`` de la build
# anterior en ``dist/``. Si PyInstaller intenta leer o escribir uno de
# esos ficheros mientras estan en uso, Windows le niega el acceso con
# ``PermissionError`` y el build cae con un mensaje cryptic.
_BLOCKING_PROCESS_PATTERNS: list[str] = [
    # La app, corriendo en la bandeja.
    "zc_automation_suite",
    # Otra instancia de PyInstaller (p. ej. en CI concurrente).
    "pyinstaller",
]

#: Procesos que se pueden matar sin que el operario lo pida: los de
#: PyInstaller. La app en ejecucion se deja en paz: matarla seria dejar al
#: operario sin su sesion de TIA a mitad de trabajo.
_PATRONES_AUTOMATICOS: list[str] = ["pyinstaller"]


def _find_blocking_processes() -> list[dict[str, Any]]:
    """Devuelve la lista de procesos que pueden bloquear el build.

    Usa ``psutil`` si esta disponible; si no, cae al comando nativo
    ``tasklist`` de Windows.

    Returns:
        Una lista de dicts con ``name``, ``pid`` y ``exe``.
    """
    found: list[dict[str, Any]] = []
    if _HAS_PSUTIL:
        for proc in psutil.process_iter(["name", "pid", "exe"]):
            try:
                name = (proc.info.get("name") or "").lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if not name:
                continue
            for patron in _BLOCKING_PROCESS_PATTERNS:
                if patron in name:
                    found.append(
                        {
                            "name": name,
                            "pid": proc.info.get("pid"),
                            "exe": proc.info.get("exe"),
                        }
                    )
                    break
        return found

    if sys.platform != "win32":
        return found
    try:
        salida = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return found
    for linea in salida.stdout.splitlines():
        partes = [p.strip().strip('"') for p in linea.split(",")]
        if len(partes) < 2:
            continue
        name_lc = partes[0].lower()
        for patron in _BLOCKING_PROCESS_PATTERNS:
            if patron in name_lc:
                with contextlib.suppress(ValueError):
                    found.append({"name": name_lc, "pid": int(partes[1]), "exe": None})
                break
    return found


def _bloquea_este_build(proceso: dict[str, Any]) -> bool:
    """Si el proceso bloquea **este** build.

    Solo bloquea el ejecutable que va a estar en ``dist/``: otra copia de
    la app, en otra carpeta, no bloquea nada. Sin ruta conocida (el
    fallback de ``tasklist`` no la da) se es conservador y se bloquea.
    """
    exe = proceso.get("exe")
    if not exe:
        return True
    return Path(exe).resolve() == (ROOT / "dist" / f"{EXE_NAME}.exe").resolve()


def check_blocking_processes(
    force_kill: bool = False,
    patrones: list[str] | None = None,
) -> bool:
    """Detecta procesos bloqueantes. Si los hay:

      * ``force_kill=False`` (default): imprime los PIDs y aborta con
        ``sys.exit(1)``. Mensaje accionable.
      * ``force_kill=True``: los mata y continua.

    Args:
        force_kill: si es ``True``, mata los procesos encontrados.
        patrones: los patrones de nombre a mirar. Por defecto, todos.

    Returns:
        ``True`` si no habia procesos bloqueantes (o si se mataron).
    """
    encontrados = _find_blocking_processes()
    if patrones is None:
        candidatos = encontrados
    else:
        candidatos = [
            p for p in encontrados if any(pat in p["name"] for pat in patrones)
        ]
    procs = [p for p in candidatos if _bloquea_este_build(p)]
    if not procs:
        return True
    print(
        "[ERROR] Hay procesos que pueden bloquear el build (tienen locks "
        "sobre los assets de Siemens o el .exe de builds anteriores en "
        "dist/):",
        file=sys.stderr,
    )
    for p in procs:
        print(f"  - {p['name']} (pid {p['pid']})", file=sys.stderr)
    if not force_kill:
        print(
            "\n        Soluciones:\n"
            "          1. Cierra el icono de la bandeja de la app.\n"
            "          2. Vuelve a ejecutar build_exe.py con --force-kill\n"
            "             para que mate los procesos automaticamente.\n"
            "          3. Si el proceso es otro pyinstaller, espera a que\n"
            "             termine o cancelalo a mano.",
            file=sys.stderr,
        )
        return False

    print("[KILL] Matando procesos bloqueantes (--force-kill)...")
    for p in procs:
        pid = p["pid"]
        if not pid:
            continue
        if sys.platform == "win32":
            if _HAS_PSUTIL:
                try:
                    psutil.Process(pid).kill()
                    print(f"  [KILL] {p['name']} (pid {pid}) OK")
                    continue
                except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
                    print(
                        f"  [WARN] psutil fallo con {p['name']} (pid {pid}): {exc}; "
                        "intento con taskkill"
                    )
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                check=False,
            )
            print(f"  [KILL] {p['name']} (pid {pid}) taskkill enviado")

    import time

    time.sleep(1.0)
    return True


def clean_pyinstaller_cache() -> None:
    """Limpia el cache de PyInstaller y el ``build/`` local.

    PyInstaller deja artefactos entre builds. Si uno de ellos esta
    lockeado por un proceso zombie, el siguiente build falla con
    ``PermissionError`` al escribir ``base_library.zip``.
    """
    cache = Path(tempfile.gettempdir()).parent / "pyinstaller"
    if cache.is_dir():
        print(f"[CLEAN] Borrando cache de PyInstaller: {cache}")
        shutil.rmtree(cache, ignore_errors=True)
    local = ROOT / "build"
    if local.is_dir():
        print(f"[CLEAN] Borrando build/ local: {local}")
        shutil.rmtree(local, ignore_errors=True)


def run_pyinstaller(spec_path: Path) -> int:
    """Invoca PyInstaller con el ``.spec`` generado.

    Usa ``sys.executable -m PyInstaller`` para garantizar que se ejecuta
    en el mismo interprete donde esta instalado PyInstaller.

    Si falla con ``PermissionError``, limpia el cache, mata los procesos
    bloqueantes si los hay y reintenta UNA vez.
    """
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        str(spec_path),
    ]

    def _run_once(label: str) -> tuple[int, str]:
        print(f"[BUILD] Ejecutando ({label}):", " ".join(cmd))
        resultado = subprocess.run(
            cmd,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        return resultado.returncode, (resultado.stdout or "") + (resultado.stderr or "")

    exit_code, output = _run_once("1/2")
    if exit_code != 0 and "PermissionError" in output:
        print(
            "[WARN] PyInstaller fallo con PermissionError. Probable lock de "
            "un proceso sobre los assets o sobre el cache de PyInstaller. "
            "Limpio el cache y mato los procesos de PyInstaller que esten "
            "corriendo, y reintento.",
            file=sys.stderr,
        )
        clean_pyinstaller_cache()
        check_blocking_processes(force_kill=True, patrones=_PATRONES_AUTOMATICOS)
        exit_code, output = _run_once("2/2")

    if output:
        print(output, end="")
    return exit_code


# ── Etapa 4: report ─────────────────────────────────────────────────────────


def report_artifact(exit_code: int) -> int:
    """Imprime el resumen del build. Retorna el ``exit_code``."""
    artefacto = ROOT / "dist" / f"{EXE_NAME}.exe"
    if exit_code == 0 and artefacto.is_file():
        size_mb = artefacto.stat().st_size / (1024 * 1024)
        print()
        print("[SUCCESS] COMPILACION EXITOSA")
        print(f"          Ejecutable: {artefacto}")
        print(f"          Tamano:     {size_mb:.1f} MB")
        print()
        print("[NEXT STEPS]")
        print("  1. Doble-clic sobre el .exe -> aparece el icono de bandeja.")
        print("  2. La app sirve la SPA en http://127.0.0.1:9484/.")
        print("  3. Conectar TIA desde la SPA: boton 'Conectar' del panel PLC.")
        print("  4. Los datos del operario (config/, excel/, .build_cache/)")
        print("     se crean junto al .exe, no dentro de _MEIPASS.")
        return 0

    print()
    print(f"[ERROR] Build fallo con exit code {exit_code}.", file=sys.stderr)
    print(f"        Artefacto esperado: {artefacto}", file=sys.stderr)
    return exit_code or 1


# ── Orquestacion ────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    """Compila el ejecutable. Devuelve el codigo de salida."""
    print("=" * 60)
    print(f"{EXE_NAME} - PyInstaller Build Script")
    print("=" * 60)

    force_kill = False
    for arg in (argv if argv is not None else sys.argv[1:]):
        if arg in ("--force-kill", "--kill"):
            force_kill = True
        elif arg in ("-h", "--help"):
            print(
                "Uso: python build_exe.py [--force-kill]\n"
                "\n"
                "  --force-kill   Mata automaticamente procesos que puedan\n"
                "                 bloquear el build (instancia previa de la\n"
                "                 app, otro pyinstaller, etc.) y reintenta la\n"
                "                 build limpiando el cache."
            )
            return 0

    if force_kill:
        print("[OK] --force-kill activado: se mataran procesos bloqueantes automaticamente.")

    if not check_blocking_processes(force_kill=force_kill):
        return 1

    check_python_version()

    try:
        ensure_pyinstaller()
        ensure_node()
        pyd_source = ensure_siemens_wheel()
        build_frontend()
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    print(f"[OK] .pyd origen: {pyd_source}")

    pyd_path, dlls, xmls = collect_vendor_assets(pyd_source)
    print(f"[OK] Assets de Siemens: {len(dlls)} .dll, {len(xmls)} .xml")

    staging_root: Path | None = None
    try:
        staging_root, vendor_dir = stage_vendor_assets(pyd_path, dlls, xmls)
        exe_icon = generar_ico(staging_root / "icon.ico")
        print(f"[OK] Icono generado: {exe_icon.name}")
        spec_path = write_generated_spec_file(
            staging_root,
            vendor_dir,
            dlls,
            xmls,
            exe_icon,
        )

        clean_build_dirs()
        exit_code = run_pyinstaller(spec_path)

        return report_artifact(exit_code)

    finally:
        if staging_root is not None and staging_root.exists():
            shutil.rmtree(staging_root, ignore_errors=True)
            print(f"[CLEAN] Staging temporal borrado: {staging_root}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
