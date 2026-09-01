"""Resolucion centralizada de la carpeta de logs.

Antes de este modulo, la logica de donde escribir los logs vivia
duplicada (y desalineada) en dos sitios:

  - ``main_tray.py`` -> ``<exe_dir>/logs/zc_tray.log``            (correcto)
  - ``worker_tia.py`` -> ``<exe_dir>/worker_openness.log``         (junto al .exe)

La inconsistencia rompia la convencion "todos los artefactos del
operario en ``<exe_dir>/logs/``" y hacia que ``worker_openness.log``
escapara del lugar esperado. Ademas, el worker no respetaba
``ZC_LOG_DIR`` ni tenia fallback a AppData.

Unificando aqui conseguimos que ambos logs vayan a la misma
carpeta, con el mismo override por env var y el mismo fallback,
independientemente de quien los escriba.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


_logger = logging.getLogger(f"{__name__}.resolve_log_dir")


def resolve_log_dir(
    env_var: str = "ZC_LOG_DIR",
    default_subdir: str = "logs",
) -> Path:
    """Devuelve la carpeta donde escribir los logs del programa.

    Prioridad de localizacion:

      1. ``env_var`` (default ``ZC_LOG_DIR``) si esta definida y no vacia.
      2. Modo frozen (PyInstaller ``--onefile``): ``<exe_dir>/<default_subdir>``.
      3. Modo dev (``python main_tray.py``): ``<cwd>/<default_subdir>``.
      4. Fallback legacy a ``%LocalAppData%\\zc-automation-suite\\<default_subdir>``
         si la ruta prioritaria no se puede crear (permisos, etc.).

    La ruta devuelta SIEMPRE existe en disco (``mkdir(parents=True,
    exist_ok=True)``). Esto es importante para los consumidores que
    escriben directamente (e.g. ``ts.set_logging(path=...)`` de Siemens
    no crea el directorio padre, solo escribe).

    Args:
        env_var: Nombre de la variable de entorno a respetar.
        default_subdir: Subcarpeta por defecto bajo el ejecutable o el CWD.

    Returns:
        ``Path`` a una carpeta existente. Nunca ``None``.
    """
    # 1. Override explicito por env var.
    override = os.environ.get(env_var, "").strip()
    if override:
        candidate = Path(override)
        if _try_mkdir(candidate, source=f"{env_var}={override}"):
            return candidate
        # Si el override fallo, cae al calculo por defecto (no silenciamos).

    # 2. Calcular ruta por defecto segun el modo de ejecucion.
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path.cwd()
    candidate = base / default_subdir
    if _try_mkdir(candidate, source=str(candidate)):
        return candidate

    # 3. Fallback al AppData legacy (clasico en Windows para apps internas).
    fallback = (
        Path.home() / "AppData" / "Local" / "zc-automation-suite" / default_subdir
    )
    fallback.mkdir(parents=True, exist_ok=True)
    _logger.warning(
        "No se pudo usar la ruta de logs por defecto; usando fallback AppData: %s",
        fallback,
    )
    return fallback


def _try_mkdir(path: Path, source: str) -> bool:
    """Intenta crear ``path``. Retorna True si existe tras la llamada."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except OSError as exc:
        _logger.warning(
            "No se pudo crear la carpeta de logs en %s (origen: %s): %s",
            path, source, exc,
        )
        return False


__all__ = ["resolve_log_dir"]
