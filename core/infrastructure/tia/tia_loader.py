"""core.infrastructure.tia.tia_loader - carga el wrapper siemens_tia_scripting.pyd.

Stage del .pyd en tempdir con nombre canonico e import via importlib.
Si la wheel no esta instalada o el staging falla, levanta excepciones
con mensajes accionables para el operario.

Tres pasos:
  1. resolve_siemens_pyd()  - localiza el .pyd en el venv actual.
  2. stage_vendor_assets()  - copia a tempdir con nombre canonico.
  3. load_siemenstia()      - carga el modulo via importlib.

Usado por core.infrastructure.tia.tia_loop.start_tia_loop() cuando arranca
el hilo dedicado TIA (no en main.py).
"""
from __future__ import annotations

import importlib.util
import logging
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Nombre canonico del .pyd (sin ABI tag). El wrapper se carga siempre con
# este nombre, independientemente del nombre real de la wheel instalada.
PYD_CANONICAL_NAME = "siemens_tia_scripting.pyd"


def resolve_siemens_pyd() -> Path:
    """Localiza el .pyd de ``siemens_tia_scripting`` en el venv actual.

    Returns:
        Ruta absoluta al archivo ``.pyd`` (puede tener ABI tag, ej.
        ``siemens_tia_scripting.cp314-win_amd64.pyd``).

    Raises:
        FileNotFoundError: Si la wheel no esta instalada en el venv.
    """
    spec = importlib.util.find_spec("siemens_tia_scripting")
    if spec is None or not spec.origin:
        raise FileNotFoundError(
            "No se pudo resolver 'siemens_tia_scripting' en el "
            "interprete actual. La wheel oficial no esta instalada.\n"
            "Para instalar: pip install siemens_tia_scripting-<version>-cp3XX-cp3XX-win_amd64.whl"
        )
    pyd_path = Path(spec.origin)
    if not pyd_path.is_file():
        raise FileNotFoundError(
            f"El binario resuelto no existe en disco: {pyd_path}"
        )
    return pyd_path


def _collect_vendor_assets(pyd_path: Path) -> tuple[list[Path], list[Path]]:
    """Separa .dll y .xml acompanantes de la wheel (mismo directorio)."""
    base_dir = pyd_path.parent
    dlls = sorted(p for p in base_dir.glob("*.dll") if p.is_file())
    xmls = sorted(p for p in base_dir.glob("*.xml") if p.is_file())
    return dlls, xmls


def stage_vendor_assets(pyd_path: Path) -> Path:
    """Copia el .pyd (renombrado a canonico) + .dll + .xml a un tempdir.

    El staging es dentro de un subdirectorio del tempdir del sistema,
    NO del repo. Cumple "Cero Codigo Sucio": el repo queda intacto.

    Returns:
        Path al directorio vendor (contiene el .pyd canonico + dlls + xmls).

    Raises:
        OSError: Si no se puede crear el tempdir o copiar los archivos.
    """
    staging_root = Path(tempfile.mkdtemp(prefix="zc_vendor_"))
    vendor_dir = staging_root / "vendor"
    vendor_dir.mkdir(parents=True, exist_ok=True)

    staged_pyd = vendor_dir / PYD_CANONICAL_NAME
    shutil.copy2(pyd_path, staged_pyd)
    logger.info(".pyd stageado: %s", staged_pyd.name)

    dlls, xmls = _collect_vendor_assets(pyd_path)
    for dll in dlls:
        shutil.copy2(dll, vendor_dir / dll.name)
        logger.info(".dll stageada: %s", dll.name)
    for xml in xmls:
        shutil.copy2(xml, vendor_dir / xml.name)
        logger.info(".xml stageado: %s", xml.name)

    return vendor_dir


def _import_module_from_path(module_name: str, file_path: Path) -> Any:
    """Carga un modulo Python desde una ruta absoluta via importlib.

    Args:
        module_name: nombre que tendra el modulo (ej. 'siemens_tia_scripting').
        file_path: ruta al archivo .pyd / .so / .py.

    Returns:
        El modulo cargado.
    """
    spec = importlib.util.spec_from_file_location(module_name, str(file_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"No se pudo crear un spec para {module_name} desde {file_path}"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_siemenstia() -> tuple[Any, Any]:
    """Carga el wrapper .NET y lo deja listo para usar.

    Pasos:
      1. Resolver el .pyd en el venv actual.
      2. Stagear el .pyd (+ .dll + .xml) en un tempdir.
      3. Importar el modulo desde el .pyd stageado.

    Returns:
        Tupla ``(ts_module, vendor_dir)`` donde ``ts_module`` es el
        modulo ``siemens_tia_scripting`` listo para ``ts.open_portal(...)``.

    Raises:
        FileNotFoundError: Si la wheel no esta instalada.
        RuntimeError: Si falla el staging o el import.
    """
    pyd_path = resolve_siemens_pyd()
    vendor_dir = stage_vendor_assets(pyd_path)
    staged_pyd = vendor_dir / PYD_CANONICAL_NAME
    try:
        ts_module = _import_module_from_path(
            "siemens_tia_scripting", staged_pyd,
        )
    except Exception as exc:
        raise RuntimeError(
            f"Fallo al importar {staged_pyd}: {type(exc).__name__}: {exc}"
        ) from exc
    logger.info("Wrapper TIA cargado: %s", staged_pyd)
    return ts_module, vendor_dir


__all__ = ["load_siemenstia", "PYD_CANONICAL_NAME"]
