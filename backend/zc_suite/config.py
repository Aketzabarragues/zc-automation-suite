"""zc_suite.config — ``config.json`` validado con Pydantic.

El ``config.json`` del usuario vive **junto al ejecutable**, nunca dentro de
``sys._MEIPASS``: en un ``.exe`` de un solo fichero, ``_MEIPASS`` se recrea
en cada arranque y se borra al salir, asi que ahi no se puede guardar nada.

La primera vez se copia la plantilla empaquetada; a partir de ahi **manda
siempre la del usuario**. Si el destino no se puede escribir (permisos,
disco de solo lectura), se usa la plantilla en modo lectura con un aviso.

Prioridad de localizacion:

1. ``$ZC_CONFIG_DIR/config.json`` si la variable esta definida.
2. Empaquetado: ``<carpeta_del_exe>/config/config.json``.
3. Desarrollo: ``<repo>/config/config.json``, sin copia.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)

#: Nombre del fichero de configuracion.
NOMBRE_CONFIG = "config.json"

#: Variable de entorno que apunta a la carpeta del config del usuario.
ENV_CONFIG_DIR = "ZC_CONFIG_DIR"

#: Subcarpeta bajo el ejecutable donde vive el config del usuario.
SUBCARPETA_CONFIG = "config"

#: Carpeta del repo (raiz del proyecto).
RAIZ = Path(__file__).resolve().parents[2]


class ConfigError(Exception):
    """El ``config.json`` no se puede leer o no es valido."""


class ConfigTia(BaseModel):
    """Ajustes de la conexion con TIA Portal."""

    model_config = ConfigDict(extra="allow")

    plc: str = ""
    proyecto: str = ""


class ConfigRutas(BaseModel):
    """Rutas del equipo del operario.

    Solo lo que es de toda la app. Cada area tiene las suyas en su
    seccion de ``areas``.
    """

    model_config = ConfigDict(extra="allow")


class Config(BaseModel):
    """Configuracion completa de la app.

    Las secciones de area se guardan tal cual: cada area valida las suyas.
    """

    model_config = ConfigDict(extra="allow")

    tia: ConfigTia = Field(default_factory=ConfigTia)
    paths: ConfigRutas = Field(default_factory=ConfigRutas)
    areas: dict[str, dict[str, Any]] = Field(default_factory=dict)

    def seccion_area(self, id_area: str, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
        """Seccion final de un area.

        Son los valores por defecto del area con encima lo que haya puesto
        el operario en su ``config.json``.

        Args:
            id_area: identificador del area.
            defaults: valores por defecto que aporta el area.
        """
        seccion = dict(defaults or {})
        seccion.update(self.areas.get(id_area, {}))
        return seccion


# ── rutas ──────────────────────────────────────────────────────────────────


def ruta_plantilla() -> Path:
    """Ruta de la plantilla de ``config.json``.

    Empaquetado: dentro de ``sys._MEIPASS``. Desarrollo: en el repo.
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / SUBCARPETA_CONFIG / NOMBRE_CONFIG
    return RAIZ / SUBCARPETA_CONFIG / NOMBRE_CONFIG


def ruta_config_usuario() -> Path:
    """Ruta donde vive el ``config.json`` del usuario."""
    return Path(sys.executable).resolve().parent / SUBCARPETA_CONFIG / NOMBRE_CONFIG


def _asegurar(destino: Path, plantilla: Path) -> bool:
    """Copia la plantilla si el destino no existe.

    Politica: **el usuario gana siempre**. Si el destino ya existe (aunque
    sea un JSON malformado) no se toca.

    Returns:
        ``True`` si el destino existe tras la llamada.
    """
    if destino.is_file():
        return True
    if not plantilla.is_file():
        return False
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(plantilla, destino)
    except OSError as exc:
        logger.warning("No se pudo copiar la plantilla a %s: %s", destino, exc)
        return False
    logger.info("Configuracion creada en %s", destino)
    return True


def resolve_config_path(
    env_var: str = ENV_CONFIG_DIR,
    subcarpeta: str = SUBCARPETA_CONFIG,
    nombre: str = NOMBRE_CONFIG,
) -> Path:
    """Devuelve la ruta del ``config.json`` que debe usar la app.

    Args:
        env_var: variable de entorno que puede forzar la carpeta.
        subcarpeta: subcarpeta bajo el ejecutable.
        nombre: nombre del fichero.

    Returns:
        La ruta del ``config.json`` del usuario, ya copiado si hacia falta.

    Raises:
        FileNotFoundError: si no hay ni config del usuario ni plantilla.
    """
    plantilla = ruta_plantilla()

    override = os.environ.get(env_var, "").strip()
    if override:
        destino = Path(override) / nombre
        if _asegurar(destino, plantilla):
            return destino
        if destino.is_file():
            return destino

    if getattr(sys, "frozen", False):
        destino = Path(sys.executable).resolve().parent / subcarpeta / nombre
        if _asegurar(destino, plantilla):
            return destino
        if destino.is_file():
            return destino
        if plantilla.is_file():
            logger.warning(
                "No se pudo escribir el config en %s. Se usa la plantilla en solo "
                "lectura: los cambios del operario no persistiran hasta que se "
                "resuelva el problema de permisos.",
                destino,
            )
            return plantilla
        raise FileNotFoundError(
            f"No se encontro {nombre} en {plantilla}. Revisa que el ejecutable "
            "este bien empaquetado."
        )

    return plantilla


# ── carga ──────────────────────────────────────────────────────────────────


def cargar_config(ruta: Path | None = None) -> Config:
    """Carga y valida el ``config.json``.

    Args:
        ruta: fichero a leer. Por defecto, el que resuelve
            ``resolve_config_path()``.

    Returns:
        La configuracion validada.

    Raises:
        ConfigError: si el fichero no existe, no es JSON valido o no cumple
            el esquema.
    """
    destino = ruta or resolve_config_path()
    if not destino.is_file():
        raise ConfigError(f"No se encontro el {NOMBRE_CONFIG} en {destino}.")
    try:
        datos = json.loads(destino.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"El {NOMBRE_CONFIG} de {destino} no es JSON valido: {exc}"
        ) from exc
    try:
        return Config.model_validate(datos)
    except ValidationError as exc:
        raise ConfigError(f"El {NOMBRE_CONFIG} de {destino} no cumple el esquema: {exc}") from exc
