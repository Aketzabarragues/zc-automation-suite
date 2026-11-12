"""zc_suite.nucleo.app.config — ``config.json`` validado con Pydantic.

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
from collections.abc import Iterable
from dataclasses import dataclass
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
RAIZ = Path(__file__).resolve().parents[4]

#: El config vino de la variable de entorno.
ORIGEN_ENTORNO = "entorno"

#: El config es el que ya tenia el operario: **manda siempre**.
ORIGEN_USUARIO = "usuario"

#: El config se copio ahora de la plantilla.
ORIGEN_COPIA = "copia"

#: El config es la plantilla empaquetada, en solo lectura.
ORIGEN_PLANTILLA = "plantilla"


class ConfigError(Exception):
    """El ``config.json`` no se puede leer o no es valido."""


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
        ``ORIGEN_USUARIO`` si el destino ya estaba, ``ORIGEN_COPIA`` si se
    acaba de copiar, o ``None`` si no se pudo dejar el destino listo.
    """
    if destino.is_file():
        return ORIGEN_USUARIO
    if not plantilla.is_file():
        return None
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(plantilla, destino)
    except OSError as exc:
        logger.warning("No se pudo copiar la plantilla a %s: %s", destino, exc)
        return None
    logger.info("Configuracion creada en %s", destino)
    return ORIGEN_COPIA


@dataclass(frozen=True)
class ConfigEnUso:
    """De donde sale el ``config.json`` que usa la app.

    Attributes:
        ruta: el fichero que se lee.
        origen: de donde sale: ``entorno``, ``usuario``, ``copia`` o
            ``plantilla``.
    """

    ruta: Path
    origen: str


def resolver_config(
    env_var: str = ENV_CONFIG_DIR,
    subcarpeta: str = SUBCARPETA_CONFIG,
    nombre: str = NOMBRE_CONFIG,
) -> ConfigEnUso:
    """Resuelve el ``config.json`` que debe usar la app, y de donde sale.

    Es ``resolve_config_path()`` pero ademas dice el origen: sin eso no se
    puede explicar por que un ``config.json`` dejo de tener los tipos de
    dispositivo.

    Returns:
        La ruta y el origen.

    Raises:
        FileNotFoundError: si no hay ni config del usuario ni plantilla.
    """
    plantilla = ruta_plantilla()

    override = os.environ.get(env_var, "").strip()
    if override:
        destino = Path(override) / nombre
        origen = _asegurar(destino, plantilla)
        if origen is not None:
            return ConfigEnUso(destino, ORIGEN_ENTORNO)
        if destino.is_file():
            return ConfigEnUso(destino, ORIGEN_ENTORNO)

    if getattr(sys, "frozen", False):
        destino = Path(sys.executable).resolve().parent / subcarpeta / nombre
        origen = _asegurar(destino, plantilla)
        if origen is not None:
            return ConfigEnUso(destino, origen)
        if destino.is_file():
            return ConfigEnUso(destino, ORIGEN_USUARIO)
        if plantilla.is_file():
            logger.warning(
                "No se pudo escribir el config en %s. Se usa la plantilla en solo "
                "lectura: los cambios del operario no persistiran hasta que se "
                "resuelva el problema de permisos.",
                destino,
            )
            return ConfigEnUso(plantilla, ORIGEN_PLANTILLA)
        raise FileNotFoundError(
            f"No se encontro {nombre} en {plantilla}. Revisa que el ejecutable "
            "este bien empaquetado."
        )

    return ConfigEnUso(plantilla, ORIGEN_PLANTILLA)


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
    return resolver_config(env_var, subcarpeta, nombre).ruta


# ── carga ──────────────────────────────────────────────────────────────────


def areas_registradas_faltantes(config: Config, ids_areas: Iterable[str]) -> list[str]:
    """Las areas registradas que no tienen seccion en el ``config.json``.

    Args:
        config: la configuracion cargada.
        ids_areas: los identificadores de las areas registradas.

    Returns:
        Los identificadores de las areas que no estan en el config.
    """
    return [id_area for id_area in ids_areas if id_area not in config.areas]


def config_incompatible(config: Config, ids_areas: Iterable[str]) -> str | None:
    """El motivo por el que el ``config.json`` no sirve, o ``None`` si vale.

    Un ``config.json`` sin la seccion ``areas`` (o sin la seccion de un area
    registrada) es de otra version de la app. **No se sustituye**: el config
    del operario manda siempre. La app avisa y sigue.

    Args:
        config: la configuracion cargada.
        ids_areas: los identificadores de las areas registradas.

    Returns:
        El mensaje para el operario, o ``None`` si el config sirve.
    """
    if not config.areas:
        return (
            "El config.json no tiene la seccion 'areas': es de otra version de la "
            "app. No se sustituye (el config del operario manda siempre): anadele "
            "la seccion 'areas' o copie el config de la plantilla."
        )
    faltan = areas_registradas_faltantes(config, ids_areas)
    if faltan:
        return (
            f"El config.json no tiene la seccion de las areas '{', '.join(faltan)}'. "
            "No se sustituye (el config del operario manda siempre): copie el "
            "config de la plantilla."
        )
    return None


def estado_config(
    config: Config,
    config_en_uso: ConfigEnUso,
    ids_areas: Iterable[str],
) -> dict[str, Any]:
    """El estado de la configuracion, tal y como lo ve la SPA.

    Args:
        config: la configuracion cargada.
        config_en_uso: de donde sale el ``config.json``.
        ids_areas: los identificadores de las areas registradas.

    Returns:
        Un dict con la ruta, el origen, si el config sirve y por que no.
    """
    motivo = config_incompatible(config, ids_areas)
    return {
        "ruta": str(config_en_uso.ruta),
        "origen": config_en_uso.origen,
        "incompatible": motivo is not None,
        "motivo": motivo,
        "areas_faltantes": areas_registradas_faltantes(config, ids_areas),
    }


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
        # ``utf-8-sig`` lee igual un fichero con BOM que sin el: hay
        # editores que lo guardan con BOM y el app no deberia caer por eso.
        datos = json.loads(destino.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"El {NOMBRE_CONFIG} de {destino} no es JSON valido: {exc}"
        ) from exc
    try:
        return Config.model_validate(datos)
    except ValidationError as exc:
        raise ConfigError(f"El {NOMBRE_CONFIG} de {destino} no cumple el esquema: {exc}") from exc
