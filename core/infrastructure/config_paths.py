"""Resolucion centralizada del ``config.json`` del usuario.

Patron: "template bundleado + copia writable al lado del .exe".

  - En modo frozen (PyInstaller ``--onefile``), el ``config.json``
    bundleado en ``sys._MEIPASS`` es la plantilla default.
  - En la primera ejecucion se copia a
    ``<exe_dir>/config/config.json`` para que el operario pueda
    editarlo sin recompilar nada.
  - En siguientes ejecuciones, **SIEMPRE gana el del usuario**:
    no sobreescribimos un archivo existente aunque el bundleado
    sea mas nuevo. El operario borra el archivo a mano si quiere
    resetear.
  - Si ``<exe_dir>/config/`` no es escribible (CD-ROM, red
    readonly, permisos), fallback al bundleado directo con
    warning (modo "live demo": los edits no persisten, pero la
    app arranca).

El resolver se llama desde ``ConfigManager.__init__`` cuando el
caller no pasa un ``config_path`` explicito. Los callers que pasan
``config_path=`` (todos los tests, ``app.py``, ``mcp_server.py``)
siguen funcionando identico: compat 100%.

Inspirado en ``core/application/log_paths.py:resolve_log_dir``
(mismo patron de env var + frozen + dev + fallback).
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path


_logger = logging.getLogger(f"{__name__}.resolve_config_path")


# Nombre del archivo de configuracion (siempre este nombre, en
# cualquier carpeta donde vivamos).
_CONFIG_FILENAME: str = "config.json"


def resolve_config_path(
    env_var: str = "ZC_CONFIG_DIR",
    default_subdir: str = "config",
    bundled_relpath: str = "infrastructure/config.json",
) -> Path:
    """Devuelve la ruta al ``config.json`` que debe usar la app.

    Prioridad de localizacion:

      1. ``$ZC_CONFIG_DIR/config.json`` si esta definido y no
         vacio. Si el archivo no existe, se copia el bundleado
         alli (mismo comportamiento que primera ejecucion).
      2. Modo frozen (PyInstaller ``--onefile``):
         ``<exe_dir>/<default_subdir>/config.json``. Si no
         existe, se copia desde
         ``<sys._MEIPASS>/<bundled_relpath>``. Fallback readonly
         al bundleado si no se puede escribir.
      3. Modo dev (``python main_tray.py``):
         ``<cwd>/<bundled_relpath>`` (el del repo, sin copia).
         El developer edita el archivo en su repo directamente.

    Politica: **el usuario gana siempre**. Si el archivo destino
    ya existe, NO se sobreescribe. El operario borra el archivo
    a mano si quiere resetear al bundleado.

    Args:
        env_var: Variable de entorno a respetar como override
            (default ``ZC_CONFIG_DIR``, mismo patron que
            ``ZC_LOG_DIR``).
        default_subdir: Subcarpeta por defecto bajo el ejecutable
            (modo frozen). El archivo siempre se llama
            ``config.json``.
        bundled_relpath: Ruta relativa al bundle (``_MEIPASS`` en
            frozen, ``cwd`` en dev) donde vive el ``config.json``
            plantilla.

    Returns:
        ``Path`` al ``config.json``. La ruta existe en disco
        (recien copiada o preexistente). Si la copia falla por
        permisos, devuelve la ruta bundleada (lectura OK pero
        escritura no; el caller debe estar preparado para eso).

    Raises:
        FileNotFoundError: Si ni la ruta prioritaria ni la
            bundleada se pueden resolver (caso extremo: el
            bundleado no existe en disco).
    """
    # 1. Override explicito por env var (aplica en cualquier modo).
    override = os.environ.get(env_var, "").strip()
    if override:
        candidate = Path(override) / _CONFIG_FILENAME
        bundled = _bundled_path(bundled_relpath)
        if _ensure_user_config(bundled, candidate, source=f"{env_var}={override}"):
            return candidate
        if candidate.is_file():
            return candidate
        # Si tampoco existe, cae al calculo por defecto (no silenciamos).

    # 2. Modo frozen: copiar el bundleado a <exe_dir>/<subdir>/.
    if getattr(sys, "frozen", False):
        candidate = (
            Path(sys.executable).parent / default_subdir / _CONFIG_FILENAME
        )
        bundled = _bundled_path(bundled_relpath)
        if _ensure_user_config(bundled, candidate, source=str(candidate)):
            return candidate
        if candidate.is_file():
            return candidate
        # Fallback readonly: ruta bundleada (lectura OK, escritura no).
        if bundled.is_file():
            _logger.warning(
                "No se pudo escribir config en %s. Usando bundleado "
                "readonly: %s. Los edits del operario no persistiran "
                "hasta que se resuelva el problema de permisos.",
                candidate, bundled,
            )
            return bundled
        raise FileNotFoundError(
            f"No se encontro config.json bundleado en {bundled}. "
            f"Revisa que el .exe este correctamente empaquetado."
        )

    # 3. Modo dev: usar el archivo del repo directamente (sin copia).
    #    El developer edita ``infrastructure/config.json`` en su repo
    #    y los cambios se ven en el siguiente reinicio. No copiamos
    #    a un sitio "del usuario" porque no hay .exe del que hablar.
    return _bundled_path(bundled_relpath)


def _bundled_path(relpath: str) -> Path:
    """Resuelve la ruta al ``config.json`` bundleado (template).

    En frozen: ``<sys._MEIPASS>/<relpath>``.
    En dev: ``<cwd>/<relpath>``.
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / relpath
    return Path.cwd() / relpath


def _ensure_user_config(
    bundled: Path, dst: Path, source: str,
) -> bool:
    """Asegura que ``dst`` existe; si no, copia ``bundled`` a ``dst``.

    Politica: **el usuario gana siempre**. Si ``dst`` ya existe
    (aunque sea un archivo vacio o un JSON malformado), NO se
    sobreescribe. El operario borra el archivo a mano si quiere
    resetear al bundleado.

    Returns:
        True si ``dst`` existe tras la llamada (preexistente o
        recien copiado). False si la copia fallo (permisos, etc.).
    """
    if dst.is_file():
        return True  # el del usuario ya esta; no tocamos
    if not bundled.is_file():
        return False  # no hay template para copiar
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _logger.warning(
            "No se pudo crear la carpeta de config en %s (origen: "
            "%s): %s.", dst.parent, source, exc,
        )
        return False
    try:
        shutil.copy2(bundled, dst)
    except OSError as exc:
        _logger.warning(
            "No se pudo copiar config bundleado a %s (origen: %s): "
            "%s. Se intentara fallback readonly.", dst, source, exc,
        )
        return False
    _logger.info(
        "Se creo %s (primera ejecucion; copia del bundleado %s). "
        "Edita este archivo para personalizar la configuracion del "
        "operario; tus cambios se preservaran entre reinicios del "
        ".exe. Si quieres resetear al estado bundleado, borra este "
        "archivo y reinicia la app.", dst, bundled,
    )
    return True


__all__ = ["resolve_config_path"]
