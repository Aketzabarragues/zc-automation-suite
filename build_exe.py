"""Orquestador PyInstaller para ``zc-automation-suite`` (Fat Binary).

Compila ``main_tray.py`` en ``dist/zc_automation_suite.exe`` con TODO lo
necesario para ejecutar la app en producción, incluyendo el binario
nativo de Siemens (``.pyd``) y sus dependencias (``.dll`` / ``.xml``)
resueltos dinámicamente desde el intérprete Python actual (3.12 / 3.13
/ 3.14).

Restricciones aplicadas (heredadas del legacy
``_legacy_reference/ZC_ALM_TOOLS/build_exe.py`` + decisiones
arquitectónicas del proyecto):

  - **Cero Código Sucio**: ni el ``.pyd`` ni las ``.dll``/``.xml`` se
    copian al directorio de trabajo. Se stagean en un directorio
    temporal creado con ``tempfile.mkdtemp(prefix="zc_build_")``.

  - **Carga dinámica oficial**: el worker OT (``worker_tia.py``)
    resuelve el ``.pyd`` desde ``sys._MEIPASS`` siguiendo la
    Sección 1.7.1 del manual TIA Scripting V1.2.1. Para que esto
    funcione, **el ``.pyd`` y TODAS las ``.dll`` deben vivir en la
    raíz de ``_MEIPASS``** (no en subcarpetas ``vendor/``). Las
    ``.xml`` (log4net) también.

  - **UPX excluido para ``*.dll`` y ``*.pyd``**: UPX corrompe los
    ensamblados .NET nativos. Crítico; sin esto, el worker muere
    con ``ImportError`` al cargar ``siemens_tia_scripting``.

  - **Entry = ``main_tray.py``**: el ``.exe`` arranca como bandeja
    + web supervisor (``console=False``, windowed). MCP queda
    dev-only y se invoca con ``python main.py`` en el repo.
    ``main_tray.py`` despacha ``--worker`` internamente para que el
    gateway pueda re-invocar el ``.exe`` como subproceso OT efímero.

  - **Auto-generación del ``.spec``**: el spec se genera
    programáticamente en el mismo tempdir de staging y se borra en
    ``finally``. No es un archivo tracked.
"""
from __future__ import annotations

import importlib.util
import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from textwrap import dedent


# ── Forzar UTF-8 en stdout/stderr (mismo patrón que main.py / worker_tia.py) ─
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


# ── Constantes ─────────────────────────────────────────────────────
ROOT = Path(__file__).parent
EXE_NAME = "zc_automation_suite"
PYD_CANONICAL_NAME = "siemens_tia_scripting.pyd"
STAGING_PREFIX = "zc_build_"
SUPPORTED_PYTHONS: list[tuple[int, int]] = [(3, 12), (3, 13), (3, 14)]
ENTRY_SCRIPT = "main_tray.py"  # entry del .exe (UX: bandeja + web supervisor)

# Datos del proyecto que se bundlean dentro de _MEIPASS, conservando
# la MISMA ruta relativa que el código espera en runtime.
#
# Convención de PyInstaller ``--add-data``:
#   ``(ruta_origen_absoluta, directorio_destino_en_bundle)``
# El segundo elemento es el DIRECTORIO dentro de ``_MEIPASS`` donde
# se deposita el archivo, NO la ruta completa del archivo. Si
# pusiera la ruta completa del archivo (``"infrastructure/config.json"``),
# PyInstaller crearía un directorio anidado
# ``_MEIPASS\infrastructure\config.json\config.json`` con un
# ``\config.json`` extra al final. Bug real visto en
# ``dist\zc_automation_suite.exe``: el web crasheaba con
# ``FileNotFoundError: 'infrastructure\config.json'`` porque
# ``ConfigManager`` busca en ``_MEIPASS\infrastructure\config.json``
# (sin el sufijo).
#
# - ``static/`` → directorio, mapping a sí mismo (entero).
#   El código hace ``Path(__file__).parent / "static"`` y debe
#   encontrar la SPA en ``_MEIPASS\interfaces\web_server\static\``.
# - ``areas/alimentacion/frontend/`` → directorio, mapping a la
#   ruta que el ``area-loader.js`` espera en runtime:
#   ``_MEIPASS\interfaces\web_server\static\areas\alimentacion\``.
#   Añadido en PR 7 (estaba en PR 5 pero no se había añadido al
#   bundle del .exe; el código en runtime lo busca en la ruta
#   estática del shell, no bajo ``_MEIPASS/areas/``).
# - ``icon.ico`` → fichero suelto, mapping a su carpeta padre.
#   El código hace ``_MEIPASS\launcher\icon.ico``.
# - ``config.json`` → fichero suelto, mapping a su carpeta padre.
#   El código hace ``_MEIPASS\infrastructure\config.json``.
PROJECT_DATA_FILES: list[tuple[str, str]] = [
    ("interfaces/web_server/static", "interfaces/web_server/static"),
    ("areas/alimentacion/frontend", "interfaces/web_server/static/areas/alimentacion"),
    ("launcher/icon.ico", "launcher"),
    ("infrastructure/config.json", "infrastructure"),
]

# Icono embebido en el .exe (lo que se ve en el Explorador de Windows,
# en Alt+Tab, en el .lnk si se crea un acceso directo, etc.).
# PyInstaller solo acepta .ico multi-resolución (16/32/48/64/128/256).
# Por defecto usamos el mismo ``launcher/icon.ico`` que se bundlea
# como data file para la bandeja en runtime, pero puedes cambiarlo
# apuntando ``EXE_ICON`` a otro .ico sin tocar el resto del script.
# Si el fichero no existe, ``run_pyinstaller()`` falla con mensaje
# accionable (``ejecuta launcher/make_icon.py`` o coloca tu icono).
EXE_ICON: Path = ROOT / "launcher" / "icon.ico"

# Plantilla del .spec auto-generado. Usa placeholders ``{...}`` que
# se sustituyen en ``write_generated_spec_file()`` con rutas reales.
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
    # TODOS a la raíz de _MEIPASS: ``worker_tia._load_siemens_wrapper``
    # hace ``add_dll_directory(_MEIPASS)`` + ``sys.path.insert(_MEIPASS)``
    # y luego ``import siemens_tia_scripting``. Si el .pyd NO está
    # en la raíz, el import falla con ModuleNotFoundError.
    _siemens_binaries = [
        (str(_P(_VENDOR) / "siemens_tia_scripting.pyd"), "."),
    ]
    for _dll in {dll_list_py}:
        _siemens_binaries.append((_dll, "."))

    # Datos (XMLs de log4net, esquemas Siemens): también a la raíz
    # por convención del loader nativo.
    _siemens_datas = []
    for _xml in {xml_list_py}:
        _siemens_datas.append((_xml, "."))

    # Datos del proyecto (SPA, icono, config.json). Se preserva la
    # ruta relativa para que ``Path(__file__).parent / "static"``
    # siga funcionando en frozen.
    _project_datas = {project_datas_py}

    a = Analysis(
        [str(_P(_ROOT) / {entry_script_py!r})],
        binaries=_siemens_binaries,
        datas=_siemens_datas + _project_datas,
        hiddenimports=[
            # ── Siemens / Pythonnet (worker OT, llamado por --worker) ──
            'siemens_tia_scripting', 'pythonnet', 'clr',
            # ── Web server (interfaces/web_server/) ──
            'fastapi', 'fastapi.staticfiles', 'starlette',
            'starlette.staticfiles', 'uvicorn', 'uvicorn.lifespan',
            'uvicorn.lifespan.on', 'uvicorn.loops', 'uvicorn.loops.auto',
            'uvicorn.protocols', 'uvicorn.protocols.http',
            'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets',
            'uvicorn.protocols.websockets.auto', 'uvicorn.server',
            'uvicorn.main', 'uvicorn.config', 'uvicorn.importer',
            # ── Excel (parsers + use cases) ──
            'openpyxl', 'openpyxl.cell._writer',
            # ── Tray (launcher/) ──
            'pystray', 'pystray._win32', 'PIL', 'PIL.Image',
            'PIL.ImageDraw', 'PIL.ImageFont', 'PIL._tkinter_finder',
            'PIL._imaging',
            # ── Async (gateway) ──
            'asyncio', 'asyncio.windows_utils',
            # ── Webbrowser (launcher/tray_app: "Abrir panel web") ──
            'webbrowser',
        ],
        excludes=[
            # MCP/FastMCP NO entran en el .exe (es dev-only);
            # excluidos explícitamente para no inflar el bundle.
            'mcp', 'fastmcp', 'fastmcp.server', 'fastmcp.tools',
            'mcp.server', 'mcp.server.stdio',
            # main.py NO se usa en frozen (entry = main_tray.py)
            'main',
            # Dev/test/tamaño
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
            # CRÍTICO: UPX corrompe DLLs nativas .NET y el .pyd de Siemens
            'siemens_tia_scripting.pyd',
            'python312.dll', 'python313.dll', 'python314.dll',
            'vcruntime140*.dll', 'msvcp140*.dll',
            '*.dll',  # wildcard defensivo (heredado del legacy)
        ],
        runtime_tmpdir=None,
        console=False,  # WINDOWED: entry = main_tray.py, no abre consola
        disable_windowed_traceback=False,
        icon={exe_icon_py!r},  # ruta absoluta al .ico (ver build_exe.EXE_ICON)
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    # Modo --onefile: NO hay bloque COLLECT(...)
    '''
)


# ── Etapa 0: validación ────────────────────────────────────────────
def check_python_version() -> None:
    """Valida que el intérprete actual sea 3.12, 3.13 o 3.14.

    TIA Scripting requiere estas versiones (la wheel oficial no se
    publica para 3.11 ni anteriores).
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
    """Falla rápido con mensaje accionable si PyInstaller no está disponible."""
    if importlib.util.find_spec("PyInstaller") is None:
        raise RuntimeError(
            "PyInstaller no está instalado en el intérprete actual. "
            "Ejecuta: pip install pyinstaller"
        )


# ── Etapa 1: resolver assets vendor de Siemens ────────────────────
def resolve_siemens_pyd() -> Path:
    """Localiza el .pyd de ``siemens_tia_scripting`` en el venv actual.

    Returns:
        Ruta absoluta al archivo ``.pyd`` (puede tener ABI tag, ej.
        ``siemens_tia_scripting.cp314-win_amd64.pyd``).

    Raises:
        FileNotFoundError: Si la wheel no está instalada.
    """
    spec = importlib.util.find_spec("siemens_tia_scripting")
    if spec is None or not spec.origin:
        raise FileNotFoundError(
            "No se pudo resolver 'siemens_tia_scripting' en el "
            "intérprete actual. ¿Está instalada la wheel oficial?\n"
            "  pip install siemens_tia_scripting-<version>-cp3XX-cp3XX-win_amd64.whl"
        )
    pyd_path = Path(spec.origin)
    if not pyd_path.is_file():
        raise FileNotFoundError(f"El binario resuelto no existe en disco: {pyd_path}")
    return pyd_path


def collect_vendor_assets(pyd_path: Path) -> tuple[Path, list[Path], list[Path]]:
    """Separa los assets de la wheel en (.pyd, .dll, .xml).

    Las ``.dll`` y ``.xml`` viven en el mismo directorio de instalación
    de la wheel (donde pip descomprime los archivos de datos de la
    ``.whl``). Si la wheel no las trae (versiones antiguas), las
    listas correspondientes quedan vacías y se loggea un warning.

    Args:
        pyd_path: Ruta al ``.pyd`` resuelta por ``resolve_siemens_pyd``.

    Returns:
        Tupla ``(pyd_path, dlls, xmls)`` con rutas absolutas.
    """
    base_dir = pyd_path.parent
    dlls = sorted(p for p in base_dir.glob("*.dll") if p.is_file())
    xmls = sorted(p for p in base_dir.glob("*.xml") if p.is_file())
    return pyd_path, dlls, xmls


# ── Etapa 2: staging en tempdir ───────────────────────────────────
def stage_vendor_assets(
    pyd_path: Path, dlls: list[Path], xmls: list[Path]
) -> tuple[Path, Path]:
    """Copia el ``.pyd`` (renombrado a canónico) + ``.dll`` + ``.xml``
    a un directorio temporal dentro de un staging raíz.

    El staging raíz es un subdirectorio del tempdir del sistema, NO
    del repo. Cumple "Cero Código Sucio": la raíz del repo queda
    intacta tras el build.

    Args:
        pyd_path: Ruta al .pyd original (puede tener ABI tag).
        dlls:    Rutas a los .dll acompañantes de la wheel.
        xmls:    Rutas a los .xml acompañantes de la wheel.

    Returns:
        Tupla ``(staging_root, vendor_dir)``:
          - ``staging_root``: el tempdir completo (para limpieza
            en ``finally``).
          - ``vendor_dir``: subdirectorio dentro de ``staging_root``
            que contiene el ``.pyd`` canónico, las ``.dll`` y los
            ``.xml``.
    """
    staging_root = Path(tempfile.mkdtemp(prefix=STAGING_PREFIX))
    vendor_dir = staging_root / "vendor"
    vendor_dir.mkdir(parents=True, exist_ok=True)

    # 1) .pyd con nombre canónico
    staged_pyd = vendor_dir / PYD_CANONICAL_NAME
    shutil.copy2(pyd_path, staged_pyd)
    print(f"[OK] .pyd stageado: {staged_pyd.name}")

    # 2) .dll acompañantes
    for dll in dlls:
        shutil.copy2(dll, vendor_dir / dll.name)
        print(f"[OK] .dll stageada: {dll.name}")

    # 3) .xml acompañantes
    for xml in xmls:
        shutil.copy2(xml, vendor_dir / xml.name)
        print(f"[OK] .xml stageado: {xml.name}")

    if not dlls:
        print(
            "[WARN] La wheel no trae .dll acompañantes; el worker OT "
            "puede fallar al cargar CLR/Pythonnet."
        )
    if not xmls:
        print(
            "[WARN] La wheel no trae .xml acompañantes; log4net puede "
            "quejarse en el log file del worker."
        )

    return staging_root, vendor_dir


def _py_repr_path(path: Path) -> str:
    r"""Devuelve un literal Python raw-string (sin comillas) para una
    ruta Windows.

    El caller es responsable de envolver el resultado en ``r"..."``
    si quiere un literal raw. Esta función solo escapa comillas
    dobles (imposibles en nombres de archivo Windows) para que el
    caller pueda usarlas con seguridad.
    """
    s = str(path)
    if '"' in s:
        s = s.replace('"', '\\"')
    return s


def _py_repr_path_list(paths: list[Path]) -> str:
    """Literal Python para una lista de rutas (``[r"a", r"b"]``)."""
    if not paths:
        return "[]"
    return "[" + ", ".join(f'r"{_py_repr_path(p)}"' for p in paths) + "]"


def _py_repr_project_datas(files: list[tuple[str, str]]) -> str:
    """Literal Python para la lista de ``--add-data`` del proyecto.

    Shape: ``[(r"<src>", "<dst>"), ...]``.
    """
    if not files:
        return "[]"
    items = []
    for src_rel, dst_rel in files:
        src = (ROOT / src_rel).resolve()
        items.append(f'(r"{_py_repr_path(src)}", {dst_rel!r})')
    return "[" + ", ".join(items) + "]"


def write_generated_spec_file(
    staging_root: Path,
    vendor_dir: Path,
    dlls: list[Path],
    xmls: list[Path],
) -> Path:
    """Vuelca la plantilla del ``.spec`` con las rutas resueltas.

    Returns:
        Ruta absoluta al ``.spec`` recién creado (dentro de
        ``staging_root``, se borra en ``finally``).
    """
    spec_path = staging_root / f"{EXE_NAME}.spec"

    # Paths a inyectar, normalizados para que el .spec los
    # interprete correctamente en Windows.
    dlls_in_vendor = [vendor_dir / dll.name for dll in dlls]
    xmls_in_vendor = [vendor_dir / xml.name for xml in xmls]

    content = SPEC_TEMPLATE.format(
        staging_dir=_py_repr_path(staging_root),
        vendor_dir=_py_repr_path(vendor_dir),
        project_root=_py_repr_path(ROOT),
        dll_list_py=_py_repr_path_list(dlls_in_vendor),
        xml_list_py=_py_repr_path_list(xmls_in_vendor),
        project_datas_py=_py_repr_project_datas(PROJECT_DATA_FILES),
        entry_script_py=ENTRY_SCRIPT,
        exe_name_py=EXE_NAME,
        exe_icon_py=_py_repr_path(EXE_ICON),
    )

    spec_path.write_text(content, encoding="utf-8")
    print(f"[OK] .spec auto-generado: {spec_path.name}")
    return spec_path


# ── Etapa 3: build ────────────────────────────────────────────────
def clean_build_dirs() -> None:
    """Elimina carpetas de builds anteriores (idempotente)."""
    for folder in ["build", "dist"]:
        path = ROOT / folder
        if path.exists():
            print(f"[CLEAN] Limpiando {folder}/...")
            shutil.rmtree(path, ignore_errors=True)


def run_pyinstaller(spec_path: Path) -> int:
    """Invoca PyInstaller con el ``.spec`` generado.

    Usa ``sys.executable -m PyInstaller`` para garantizar que se
    ejecuta en el mismo intérprete donde está instalado PyInstaller.
    Pasa ``--clean`` para purgar el cache de PyInstaller entre
    builds (evita arrastrar artefactos de configuraciones
    anteriores).

    Pre-condición: ``EXE_ICON`` debe existir en disco (es un .ico
    multi-resolución). Si falta, se aborta con mensaje accionable.
    """
    if not EXE_ICON.is_file():
        print(
            f"[ERROR] No se encontró el icono del .exe: {EXE_ICON}\n"
            f"        Opciones:\n"
            f"          - Coloca tu .ico en {EXE_ICON} (multi-resolución 16/32/48/64/128/256).\n"
            f"          - O ejecuta: python launcher/make_icon.py  (genera un placeholder).\n"
            f"          - O cambia la constante EXE_ICON en build_exe.py.",
            file=sys.stderr,
        )
        return 1

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        str(spec_path),
    ]
    print("[BUILD] Ejecutando:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT, check=False)
    return result.returncode


# ── Etapa 4: report ───────────────────────────────────────────────
def report_artifact(exit_code: int) -> int:
    """Imprime el resumen del build. Retorna el ``exit_code``."""
    artifact = ROOT / "dist" / f"{EXE_NAME}.exe"
    if exit_code == 0 and artifact.is_file():
        size_mb = artifact.stat().st_size / (1024 * 1024)
        print()
        print("[SUCCESS] COMPILACIÓN EXITOSA")
        print(f"          Ejecutable: {artifact}")
        print(f"          Tamaño:     {size_mb:.1f} MB")
        print()
        print("[NEXT STEPS]")
        print("  1. Doble-clic sobre el .exe → aparece icono de bandeja.")
        print("  2. Click-derecho → Iniciar web → uvicorn en :8000.")
        print("  3. Probar worker: "
              f"echo {{\"command\":\"list_plcs\",\"args\":{{}}}} | {artifact.name} --worker")
        return 0

    print()
    print(f"[ERROR] Build falló con exit code {exit_code}.", file=sys.stderr)
    print(f"        Artefacto esperado: {artifact}", file=sys.stderr)
    return exit_code or 1


# ── Orquestación ──────────────────────────────────────────────────
def main() -> int:
    print("=" * 60)
    print(f"{EXE_NAME} - PyInstaller Build Script")
    print("=" * 60)

    check_python_version()
    try:
        ensure_pyinstaller()
    except RuntimeError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    # Resolver los assets vendor de Siemens.
    try:
        pyd_source = resolve_siemens_pyd()
    except FileNotFoundError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1
    print(f"[OK] .pyd origen: {pyd_source}")

    pyd_path, dlls, xmls = collect_vendor_assets(pyd_source)
    print(f"[OK] Assets vendor: {len(dlls)} .dll, {len(xmls)} .xml")

    # Stagear y generar spec en tempdir. Limpiar SIEMPRE al final.
    staging_root: Path | None = None
    try:
        staging_root, vendor_dir = stage_vendor_assets(pyd_path, dlls, xmls)
        spec_path = write_generated_spec_file(staging_root, vendor_dir, dlls, xmls)

        clean_build_dirs()
        exit_code = run_pyinstaller(spec_path)

        return report_artifact(exit_code)

    finally:
        if staging_root is not None and staging_root.exists():
            shutil.rmtree(staging_root, ignore_errors=True)
            print(f"[CLEAN] Staging temporal borrado: {staging_root}")


if __name__ == "__main__":
    sys.exit(main())
