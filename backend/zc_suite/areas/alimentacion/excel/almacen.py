"""La cache del Excel maestro del area.

Guarda el volcado parseado y una copia del ultimo ``.xlsx``, para que la vista
tenga datos al arrancar sin que el operario vuelva a subir el fichero.

Persistencia **sin base de datos**: una copia del Excel junto al ejecutable.
Empaquetado va a ``<carpeta_del_exe>/excel/ultimo.xlsx``; en desarrollo, a
``<repo>/excel/ultimo.xlsx``.

El almacen es **offline**: no habla con el portal de TIA.
"""
from __future__ import annotations

import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from zc_suite.areas.alimentacion.excel import parser

logger = logging.getLogger(__name__)

#: Carpeta donde viven las copias del Excel.
SUBCARPETA_EXCEL = "excel"

#: Extension de las copias.
EXTENSION = ".xlsx"

#: Extensiones de las copias: el Excel maestro del operario es ``.xlsm``.
EXTENSIONES = (".xlsx", ".xlsm")

#: Raiz del repo.
RAIZ = Path(__file__).resolve().parents[5]


def carpeta_persistida() -> Path:
    """La carpeta de las copias del Excel.

    Empaquetado: junto al ejecutable. Desarrollo: en el repo.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / SUBCARPETA_EXCEL
    return RAIZ / SUBCARPETA_EXCEL


def ruta_persistida() -> Path | None:
    """La copia guardada del Excel, si la hay.

    La copia se llama como el fichero que subio el operario, para que el
    nombre que ve en la vista siga siendo el del Excel original.
    """
    carpeta = carpeta_persistida()
    if not carpeta.is_dir():
        return None
    ficheros = sorted(
        fichero
        for extension in EXTENSIONES
        for fichero in carpeta.glob(f"*{extension}")
    )
    return ficheros[-1] if ficheros else None


class AlmacenExcel:
    """El volcado del Excel maestro del area.

    Guarda el parseo, el nombre del fichero y el momento de la carga. Es el
    estado que la vista consulta por HTTP y que el trabajo de parseo rellena.
    """

    def __init__(self) -> None:
        #: La seccion del area en el ``config.json``.
        self.config: dict[str, Any] = {}
        self._archivo: str | None = None
        self._cargado_en: str | None = None
        self._datos: dict[str, Any] | None = None

    # ── consultas ───────────────────────────────────────────────────────

    @property
    def cargado(self) -> bool:
        """``True`` si hay un Excel parseado."""
        return self._datos is not None

    @property
    def archivo(self) -> str | None:
        """El nombre del fichero cargado."""
        return self._archivo

    @property
    def cargado_en(self) -> str | None:
        """El momento de la carga, en ISO."""
        return self._cargado_en

    def estado(self) -> dict[str, Any]:
        """Lo que ve la SPA: el volcado y cuando se cargo.

        Returns:
            Un dict con ``cargado``, ``archivo``, ``cargado_en``, ``plcs``,
            ``configuracion``, ``dispositivos``, ``procesos``, ``entidades``
            y ``avisos``. Sin Excel cargado, los dominios salen vacios: la
            vista enseña el estado vacio, no un error.
        """
        datos = self._datos or {}
        return {
            "cargado": self.cargado,
            "archivo": self._archivo,
            "cargado_en": self._cargado_en,
            "plcs": list(datos.get("plcs") or []),
            "configuracion": datos.get("configuracion") or {"columnas": [], "filas": []},
            "dispositivos": list(datos.get("dispositivos") or []),
            "procesos": dict(datos.get("procesos") or {}),
            "entidades": datos.get("entidades") or {"columnas": [], "filas": []},
            "avisos": list(datos.get("avisos") or []),
        }

    # ── escritura ───────────────────────────────────────────────────────

    def volcar(self, ruta: Path) -> dict[str, Any]:
        """Parsea el fichero y deja el resultado en la cache.

        Args:
            ruta: el fichero ``.xlsx`` a parsear.

        Returns:
            El volcado parseado.

        Raises:
            OperacionError: si el fichero no existe o si tiene una fila mala.
        """
        datos = parser.leer_excel(ruta, self.config)
        self._datos = datos
        self._archivo = Path(ruta).name
        self._cargado_en = datetime.now().isoformat(timespec="seconds")
        return datos

    def persistir(self, ruta: Path) -> Path:
        """Copia el fichero a la carpeta de persistencia.

        La copia se llama como el original y es la unica que queda: al
        guardar una nueva, se borran las anteriores.

        Args:
            ruta: el fichero a copiar.

        Returns:
            La ruta de la copia.
        """
        carpeta = carpeta_persistida()
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = carpeta / Path(ruta).name
        for anterior in carpeta.iterdir():
            if anterior.suffix.lower() in EXTENSIONES and anterior != destino:
                anterior.unlink(missing_ok=True)
        shutil.copy2(ruta, destino)
        logger.info("Excel maestro guardado en %s", destino)
        return destino

    def recargar(self) -> bool:
        """Parsea la copia guardada del Excel, si la hay.

        Returns:
            ``True`` si habia una copia y se ha parseado.
        """
        ruta = ruta_persistida()
        if ruta is None:
            return False
        self.volcar(ruta)
        return True
