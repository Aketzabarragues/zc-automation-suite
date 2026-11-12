"""zc_suite.areas.alimentacion.config — el formato del config del area.

La seccion ``areas.alimentacion`` del ``config.json`` sigue este formato. El
modelo de aqui es el unico que lo conoce: el resto del area (el parser, el
catalogo de las pestanas, la prevision) consume **este modelo**, no el dict
crudo. Asi el formato se cambia en un solo sitio.

Reglas del formato:

- Un tipo de dispositivo se identifica **solo** por su clave en
  ``dispositivos`` (``"ed"``, ``"m_vf"``...). No hay un segundo nombre.
- Todo lo que un tipo necesita esta en su entrada: la etiqueta, el DB, el
  array, la tabla de tags, donde vive en el Excel, su N_MAX y las columnas
  que se ven.
- Las claves que no son del formato no se admiten: un ``config.json`` de una
  version anterior se rechaza con un mensaje claro, no se ignora en silencio.

El formato esta explicado en ``docs/CONFIG.md``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from zc_suite.errores import OperacionError

#: Las claves del formato anterior del area. Si alguna esta, el config es viejo.
CLAVES_ANTIGUAS: tuple[str, ...] = (
    "Dispositivos",
    "n_max_catalog",
    "disp_catalog",
    "proc_catalog",
    "entidades_catalog",
    "tia_folders",
    "global_config_table_name",
    "plantillas_path",
    "pending_nmax",
    "pending_dispositivos",
)


class ConfigInvalidoError(OperacionError):
    """La seccion del config del area no cumple el formato."""


class ConfigExcel(BaseModel):
    """Donde vive un dominio del Excel maestro."""

    model_config = ConfigDict(extra="forbid")

    #: La hoja del libro maestro.
    hoja: str

    #: El nombre de la tabla nombrada dentro de la hoja.
    tabla: str


class ConfigNMax(BaseModel):
    """El N_MAX de un tipo: la constante en TIA y la columna del Excel."""

    model_config = ConfigDict(extra="forbid")

    #: El nombre de la constante de usuario en TIA.
    constante: str

    #: La columna del Excel que la alimenta.
    columna_excel: str

    #: El comentario que lleva la constante en TIA.
    comentario: str = ""


class ConfigDispositivo(BaseModel):
    """Un tipo de dispositivo."""

    model_config = ConfigDict(extra="forbid")

    #: Lo que se ensena en la pestaña del tipo.
    etiqueta: str

    #: El DB del tipo en TIA.
    db: str

    #: El nombre del array dentro del DB.
    array: str

    #: La tabla de tags del tipo en TIA.
    tabla_tags: str

    #: Donde vive el tipo en el Excel maestro.
    excel: ConfigExcel

    #: El N_MAX del tipo.
    nmax: ConfigNMax

    #: Las columnas que se ven, en orden.
    columnas: list[str]


class ConfigCarpetas(BaseModel):
    """Las carpetas del proyecto de TIA."""

    model_config = ConfigDict(extra="forbid")

    #: La carpeta de las tablas de tags de los dispositivos.
    dispositivos: str

    #: La carpeta de las tablas de sistema.
    sistema: str

    #: La carpeta de las tablas de tags de las entidades.
    entidades: str

    #: La carpeta de los bloques de los procesos.
    procesos: str


class ConfigEntidades(BaseModel):
    """Las entidades: su DB, su tabla de tags y su N_MAX."""

    model_config = ConfigDict(extra="forbid")

    #: El DB de las entidades en TIA.
    db: str

    #: El nombre del array dentro del DB.
    array: str

    #: La tabla de tags de las entidades en TIA.
    tabla_tags: str

    #: La tabla donde vive la constante del N_MAX de las entidades.
    tabla_config: str

    #: El N_MAX de las entidades.
    nmax: ConfigNMax

    #: Las columnas que se ven, en orden.
    columnas: list[str]

    #: Los titulos de las columnas.
    etiquetas: dict[str, str]


class ConfigProcesos(BaseModel):
    """El software: los procesos, sus parametros y sus alarmas."""

    model_config = ConfigDict(extra="forbid")

    #: Los sufijos de los N_MAX de cada proceso.
    sufijos_nmax: dict[str, str]

    #: Las columnas que se ven, por subdominio.
    columnas: dict[str, list[str]]

    #: Los titulos de las columnas.
    etiquetas: dict[str, str]


class ConfigArea(BaseModel):
    """La seccion del area de alimentacion en el ``config.json``."""

    model_config = ConfigDict(extra="forbid")

    #: Las carpetas del proyecto de TIA.
    carpetas_tia: ConfigCarpetas

    #: La tabla donde viven las constantes de los N_MAX de los dispositivos.
    tabla_nmax: str

    #: La carpeta de las plantillas de los procesos, relativa a los datos.
    plantillas_procesos: str = "plantillas"

    #: Los tipos de dispositivo, por clave. El orden es el de las pestanas.
    dispositivos: dict[str, ConfigDispositivo]

    #: Los titulos de las columnas de los dispositivos.
    etiquetas_dispositivos: dict[str, str]

    #: Las entidades.
    entidades: ConfigEntidades

    #: El software.
    procesos: ConfigProcesos


@dataclass(frozen=True)
class NMaxTipo:
    """Un N_MAX del area: el de un tipo de dispositivo o el de las entidades.

    Attributes:
        tipo: la clave del tipo de dispositivo. Vacia en el N_MAX de las
            entidades.
        constante: el nombre de la constante de usuario en TIA.
        columna_excel: la columna del Excel que la alimenta.
        comentario: el comentario que lleva la constante en TIA.
        tabla: la tabla de TIA donde vive la constante.
    """

    tipo: str
    constante: str
    columna_excel: str
    comentario: str
    tabla: str


def n_max_de(config: ConfigArea) -> list[NMaxTipo]:
    """Los N_MAX del area, en el orden en que se pintan.

    Los de los dispositivos van por nombre de constante, que es como se
    ordenan las tarjetas de N_MAX; el de las entidades, el ultimo.

    Args:
        config: el modelo del area.

    Returns:
        La lista de N_MAX, con el de las entidades al final.
    """
    n_max = [
        NMaxTipo(
            tipo=tipo,
            constante=dispositivo.nmax.constante,
            columna_excel=dispositivo.nmax.columna_excel,
            comentario=dispositivo.nmax.comentario,
            tabla=config.tabla_nmax,
        )
        for tipo, dispositivo in config.dispositivos.items()
    ]
    n_max.sort(key=lambda entrada: entrada.constante)
    entidades = config.entidades.nmax
    n_max.append(
        NMaxTipo(
            tipo="",
            constante=entidades.constante,
            columna_excel=entidades.columna_excel,
            comentario=entidades.comentario,
            tabla=config.entidades.tabla_config,
        )
    )
    return n_max


def cargar(seccion: dict[str, Any]) -> ConfigArea:
    """Valida la seccion del area y devuelve el modelo.

    Args:
        seccion: la seccion ``areas.<id>`` del ``config.json``.

    Returns:
        El modelo del area.

    Raises:
        ConfigInvalidoError: si la seccion no cumple el formato.
    """
    try:
        return ConfigArea.model_validate(seccion)
    except ValidationError as exc:
        raise ConfigInvalidoError(_mensaje(exc, seccion)) from exc


def problema(seccion: dict[str, Any]) -> str | None:
    """El motivo por el que la seccion no vale, o ``None`` si vale.

    Args:
        seccion: la seccion ``areas.<id>`` del ``config.json``.

    Returns:
        El mensaje para el operario, o ``None`` si la seccion es valida.
    """
    try:
        ConfigArea.model_validate(seccion)
    except ValidationError as exc:
        return _mensaje(exc, seccion)
    return None


def _mensaje(exc: ValidationError, seccion: dict[str, Any]) -> str:
    """El motivo del rechazo, dicho para el operario."""
    antiguas = [clave for clave in CLAVES_ANTIGUAS if clave in seccion]
    if antiguas:
        return (
            "El config.json del area 'alimentacion' usa el formato anterior "
            f"(claves: {', '.join(antiguas)}). Copia el config de la plantilla: "
            "el formato esta en docs/CONFIG.md."
        )
    detalles = [_detalle(error) for error in exc.errors()]
    return (
        "El config.json del area 'alimentacion' no cumple el formato: "
        + "; ".join(detalles)
        + ". El formato esta en docs/CONFIG.md."
    )


def _detalle(error: dict[str, Any]) -> str:
    """Un error de validacion, dicho en Castellano."""
    ubicacion = ".".join(str(parte) for parte in error.get("loc", ()))
    tipo = str(error.get("type", ""))
    if tipo == "missing":
        return f"falta '{ubicacion}'"
    if tipo == "extra_forbidden":
        return f"'{ubicacion}' no es una clave admitida"
    return f"'{ubicacion}': {error.get('msg', '')}"
