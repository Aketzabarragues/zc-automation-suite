"""Orquestador de PyInstaller para zc-automation-suite (Fat Binary).

Compila main.py en dist/zc_automation_suite.exe incluyendo el binario nativo
de Siemens (siemens_tia_scripting.pyd) resuelto dinámicamente desde el
intérprete Python actual (3.12 / 3.13 / 3.14).

Restricciones aplicadas:
  - Cero Código Sucio: el .pyd nunca se copia al directorio de trabajo; se
    stagea en un directorio temporal creado con tempfile.mkdtemp().
  - Carga dinámica oficial: el worker resuelve el .pyd desde sys._MEIPASS
    siguiendo la Sección 1.7.1 del manual TIA Scripting V1.2.1.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent
PYD_CANONICAL_NAME = "siemens_tia_scripting.pyd"
EXE_NAME = "zc_automation_suite"


def ensure_pyinstaller() -> None:
    """Falla rápido con mensaje accionable si PyInstaller no está disponible."""
    if importlib.util.find_spec("PyInstaller") is None:
        raise RuntimeError(
            "PyInstaller no está instalado en el intérprete actual. "
            "Ejecuta: pip install pyinstaller"
        )


def resolve_pyd_source() -> Path:
    """Localiza el .pyd de Siemens instalado en el venv actual."""
    spec = importlib.util.find_spec("siemens_tia_scripting")
    if spec is None or not spec.origin:
        raise FileNotFoundError(
            "No se pudo resolver 'siemens_tia_scripting' en el intérprete actual. "
            "¿Está instalado el wheel oficial?"
        )
    pyd_path = Path(spec.origin)
    if not pyd_path.is_file():
        raise FileNotFoundError(f"El binario resuelto no existe en disco: {pyd_path}")
    return pyd_path


def stage_pyd_with_canonical_name(pyd_source: Path) -> tuple[Path, Path]:
    """Copia el .pyd a un staging dir temporal con nombre canónico.

    PyInstaller --add-data conserva el nombre del archivo origen. Si el .pyd
    tiene ABI tag (ej. cp314-win_amd64), lo renombramos a 'siemens_tia_scripting.pyd'
    para que el worker lo encuentre bajo el nombre canónico dentro de _MEIPASS.

    Retorna (staging_dir, staged_pyd_path). El staging dir debe ser ignorado
    por el control de versiones (.gitignore cubre /temp_* y _legacy_reference).
    """
    staging_dir = Path(tempfile.mkdtemp(prefix="zc_tia_pyd_"))
    staged_pyd = staging_dir / PYD_CANONICAL_NAME
    shutil.copy2(pyd_source, staged_pyd)
    return staging_dir, staged_pyd


def build(staged_pyd: Path) -> int:
    """Invoca PyInstaller con los flags requeridos por el ticket."""
    # Separador de rutas nativo del SO: ';' en Windows, ':' en Unix.
    add_data = f"{staged_pyd}{os.pathsep}."

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--onefile",
        "--name", EXE_NAME,
        "--add-data", add_data,
        str(ROOT / "main.py"),
    ]
    print("[BUILD] Ejecutando:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT)
    return result.returncode


def main() -> int:
    staging_dir: Path | None = None
    try:
        ensure_pyinstaller()
        pyd_source = resolve_pyd_source()
        print(f"[BUILD] PYD origen:    {pyd_source}")

        staging_dir, staged_pyd = stage_pyd_with_canonical_name(pyd_source)
        print(f"[BUILD] PYD staged:    {staged_pyd}")
        print(f"[BUILD] Staging dir:   {staging_dir} (temporal, fuera del repo)")

        rc = build(staged_pyd)

        if rc == 0:
            artifact = ROOT / "dist" / f"{EXE_NAME}.exe"
            print(f"\n[BUILD] OK -> {artifact}")
        else:
            print(f"\n[BUILD] FALLÓ con exit code {rc}", file=sys.stderr)
        return rc

    except (FileNotFoundError, RuntimeError) as e:
        print(f"[BUILD] ERROR: {e}", file=sys.stderr)
        return 1
    finally:
        if staging_dir is not None and staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())