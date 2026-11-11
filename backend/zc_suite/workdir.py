"""zc_suite.workdir — las carpetas de trabajo de cada operacion.

    .build_cache/<area>/<contexto>/
    ├── preview/                        plano (lo que ve el operario)
    │   └── <subcarpetas del contexto>  las declara el area
    └── sincronizar/                    con la estructura de TIA
        ├── variables/{export,modified}
        └── bloques/{export,modified}

Dos carpetas, dos propositos:

- ``preview/``  **plano**: lo que se exporta para leer. Sin la estructura de
  TIA, con los nombres que dice el ``config.json``.
- ``sincronizar/``  **con la estructura de TIA**: lo que se exporta para
  volver a meter. El import recorre la carpeta raiz entera, asi que las
  tablas de variables y los bloques van **siempre** separados: en la misma
  carpeta se mezclarian.

Igual que el ``config.json``, la carpeta va **junto al ejecutable** en el
modo empaquetado: dentro de ``sys._MEIPASS`` no se puede escribir nada que
sobreviva al arranque, y un ``.exe`` de un solo fichero recrea esa carpeta
en cada ejecucion.

Lo generico vive aqui: la raiz, la carpeta de sincronizacion y las
limpiezas. Las subcarpetas de ``preview/`` las declara cada area: el
nucleo no sabe que existe "disp" ni "entidades".

Resolver un workdir **no toca el disco**: solo devuelve rutas. Llama a
``crear()`` cuando vayas a escribir.
"""
from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

#: Carpeta raiz del build cache.
NOMBRE_BUILD_CACHE = ".build_cache"

#: Subcarpetas de la carpeta de sincronizacion. Las variables (tablas de
#: tags) y los bloques nunca se mezclan.
CARPETA_VARIABLES = "variables"
CARPETA_BLOQUES = "bloques"

#: Subcarpetas de cada tipo: lo exportado de TIA y lo modificado offline.
CARPETA_EXPORT = "export"
CARPETA_MODIFIED = "modified"

#: Contexto del editor de bloques, que es del shell y no de un area.
CONTEXTO_EDITOR = "editor_bloques"

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
    """Las carpetas de trabajo de un contexto de un area.

    Attributes:
        base: la carpeta del contexto, ``<build_cache>/<area>/<contexto>``.
        preview_subcarpetas: las subcarpetas de ``preview/``. Las declara
            el area, no el nucleo.
        carpetas_contexto: carpetas propias del contexto, en su raiz. Las
            declara el area cuando su flujo no encaja en el par
            ``preview/`` + ``sincronizar/`` (por ejemplo, el flujo de
            crear procesos, que trabaja con una copia de la plantilla y con
            el proceso generado).
    """

    base: Path
    preview_subcarpetas: tuple[str, ...] = ()
    carpetas_contexto: tuple[str, ...] = ()

    # ── preview ───────────────────────────────────────────────────────────

    @property
    def preview(self) -> Path:
        """La carpeta del preview: plano, para leer."""
        return self.base / "preview"

    def preview_de(self, nombre: str) -> Path:
        """Una subcarpeta del preview. La declara el area."""
        return self.preview / nombre

    # ── carpetas propias del contexto ─────────────────────────────────────

    def carpeta(self, nombre: str) -> Path:
        """Una carpeta propia del contexto, en su raiz."""
        return self.base / nombre

    # ── sincronizar ───────────────────────────────────────────────────────

    @property
    def sincronizar(self) -> Path:
        """La carpeta de sincronizacion: con la estructura de TIA."""
        return self.base / "sincronizar"

    @property
    def variables_export(self) -> Path:
        """Las tablas de tags exportadas de TIA."""
        return self.sincronizar / CARPETA_VARIABLES / CARPETA_EXPORT

    @property
    def variables_modified(self) -> Path:
        """La copia de lo exportado con los cambios offline."""
        return self.sincronizar / CARPETA_VARIABLES / CARPETA_MODIFIED

    @property
    def bloques_export(self) -> Path:
        """Los bloques exportados de TIA."""
        return self.sincronizar / CARPETA_BLOQUES / CARPETA_EXPORT

    @property
    def bloques_modified(self) -> Path:
        """La copia de lo exportado con los cambios offline."""
        return self.sincronizar / CARPETA_BLOQUES / CARPETA_MODIFIED

    # ── creacion ──────────────────────────────────────────────────────────

    def crear(self) -> Workdir:
        """Crea las carpetas. Devuelve el propio workdir."""
        for carpeta in self._carpetas():
            carpeta.mkdir(parents=True, exist_ok=True)
        return self

    def _carpetas(self) -> list[Path]:
        """Todas las carpetas del workdir, en orden."""
        carpetas = [self.preview]
        carpetas.extend(self.preview_de(nombre) for nombre in self.preview_subcarpetas)
        carpetas.extend(self.carpeta(nombre) for nombre in self.carpetas_contexto)
        carpetas.extend(
            [
                self.variables_export,
                self.variables_modified,
                self.bloques_export,
                self.bloques_modified,
            ]
        )
        return carpetas

    # ── limpieza ──────────────────────────────────────────────────────────

    def limpiar_preview(self) -> None:
        """Borra el preview y deja sus carpetas vacias."""
        _borrar(self.preview)
        self.preview.mkdir(parents=True, exist_ok=True)
        for nombre in self.preview_subcarpetas:
            self.preview_de(nombre).mkdir(parents=True, exist_ok=True)

    def limpiar_sincronizar(self) -> None:
        """Borra lo de sincronizar y deja las carpetas vacias."""
        _borrar(self.sincronizar)
        for carpeta in (
            self.variables_export,
            self.variables_modified,
            self.bloques_export,
            self.bloques_modified,
        ):
            carpeta.mkdir(parents=True, exist_ok=True)

    def limpiar_todo(self) -> None:
        """Borra el contexto entero y deja las carpetas vacias."""
        _borrar(self.base)
        self.crear()


@dataclass(frozen=True)
class WorkdirPreview:
    """Un workdir de **solo preview**.

    Lo usa el editor de bloques: exporta en SimaticSD para leer el titulo y
    el comentario del bloque, y no genera artefactos de sincronizacion.
    """

    base: Path

    @property
    def preview(self) -> Path:
        """La carpeta donde se dejan los ficheros exportados."""
        return self.base / "preview"

    def crear(self) -> WorkdirPreview:
        """Crea la carpeta. Devuelve el propio workdir."""
        self.preview.mkdir(parents=True, exist_ok=True)
        return self

    def limpiar_preview(self) -> None:
        """Borra el preview y deja la carpeta vacia.

        Se llama al **empezar** cada preparar: asi los ficheros del
        ultimo prepare son los unicos que hay, y los de un prepare anterior
        no contaminan el siguiente.
        """
        _borrar(self.preview)
        self.preview.mkdir(parents=True, exist_ok=True)


def workdir(
    area: str,
    contexto: str,
    preview: tuple[str, ...] = (),
    carpetas: tuple[str, ...] = (),
) -> Workdir:
    """El workdir de un area y un contexto.

    Args:
        area: identificador del area.
        contexto: contexto de la operacion.
        preview: subcarpetas de ``preview/``. Las declara el area.
        carpetas: carpetas propias del contexto, en su raiz. Las declara el
            area cuando su flujo no encaja en ``preview/`` + ``sincronizar/``.

    Returns:
        El workdir. No crea nada en disco.
    """
    return Workdir(
        base=raiz_build_cache() / area / contexto,
        preview_subcarpetas=preview,
        carpetas_contexto=carpetas,
    )


def workdir_editor_bloques() -> WorkdirPreview:
    """El workdir del editor de bloques: ``.build_cache/editor_bloques/preview``.

    No crea nada en disco.
    """
    return WorkdirPreview(base=raiz_build_cache() / CONTEXTO_EDITOR)


def _borrar(carpeta: Path) -> None:
    """Borra una carpeta entera, si existe."""
    shutil.rmtree(carpeta, ignore_errors=True)
