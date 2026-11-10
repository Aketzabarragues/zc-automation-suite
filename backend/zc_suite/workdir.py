"""zc_suite.workdir — carpetas de trabajo de cada operacion.

    .build_cache/<area>/<contexto>/{exports,modified,preview}

- ``exports``  lo que se ha exportado de TIA (los originales).
- ``modified`` lo que se ha modificado offline.
- ``preview``  lo que ve el operario antes de aplicar.

Igual que el ``config.json``, la carpeta va **junto al ejecutable** en el
modo empaquetado: dentro de ``sys._MEIPASS`` no se puede escribir nada que
sobreviva al arranque, y un ``.exe`` de un solo fichero recrea esa carpeta
en cada ejecucion.
"""
from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

#: Carpeta raiz del build cache.
NOMBRE_BUILD_CACHE = ".build_cache"

#: Raiz del repo (raiz del proyecto).
RAIZ = Path(__file__).resolve().parents[2]


def raiz_build_cache() -> Path:
    """Carpeta raiz del build cache.

    Empaquetado: junto al ejecutable. Desarrollo: en el repo.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / NOMBRE_BUILD_CACHE
    return RAIZ / NOMBRE_BUILD_CACHE


@dataclass(frozen=True)
class Workdir:
    """Las carpetas de una operacion.

    Resolver un workdir no toca el disco: solo devuelve las rutas. Llama a
    ``crear()`` cuando vayas a escribir.
    """

    base: Path

    @property
    def exports(self) -> Path:
        """Ficheros exportados de TIA."""
        return self.base / "exports"

    @property
    def modified(self) -> Path:
        """Ficheros modificados offline."""
        return self.base / "modified"

    @property
    def preview(self) -> Path:
        """Preview que ve el operario."""
        return self.base / "preview"

    def crear(self) -> Workdir:
        """Crea las tres carpetas. Devuelve el propio workdir."""
        for carpeta in (self.exports, self.modified, self.preview):
            carpeta.mkdir(parents=True, exist_ok=True)
        return self

    def limpiar_preview(self) -> None:
        """Borra el contenido del preview y deja la carpeta."""
        _vaciar(self.preview)

    def limpiar(self) -> None:
        """Borra el contenido de las tres carpetas y las deja vacias."""
        for carpeta in (self.exports, self.modified, self.preview):
            _vaciar(carpeta)


def workdir(area: str, contexto: str) -> Workdir:
    """Workdir de un area y un contexto.

    Args:
        area: identificador del area.
        contexto: contexto de la operacion (``disp``, ``entidades``, ...).

    Returns:
        El workdir. No crea nada en disco.
    """
    return Workdir(base=raiz_build_cache() / area / contexto)


def _vaciar(carpeta: Path) -> None:
    """Borra el contenido de una carpeta sin borrarla."""
    if not carpeta.is_dir():
        return
    for hijo in carpeta.iterdir():
        if hijo.is_dir():
            shutil.rmtree(hijo, ignore_errors=True)
        else:
            hijo.unlink(missing_ok=True)
