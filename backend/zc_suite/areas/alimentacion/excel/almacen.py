"""La cache del Excel maestro del area.

Guarda el volcado parseado **solo en memoria**, mientras la app esta abierta.
No hay copia en disco: al cerrar la app, el Excel cargado se pierde y el
operario vuelve a subirlo.

El almacen es **offline**: no habla con el portal de TIA.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from zc_suite.areas.alimentacion.config import ConfigArea, ConfigInvalidoError
from zc_suite.areas.alimentacion.excel import parser

#: Extensiones admitidas: el Excel maestro del operario es ``.xlsm``.
EXTENSIONES = (".xlsx", ".xlsm")


class AlmacenExcel:
    """El volcado del Excel maestro del area.

    Guarda el parseo, el nombre del fichero y el momento de la carga. Es el
    estado que la vista consulta por HTTP y que el trabajo de parseo rellena.
    """

    def __init__(self) -> None:
        #: El modelo del area, tal y como lo dice el ``config.json``.
        self.config: ConfigArea | None = None
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

    def vaciar(self) -> None:
        """Deja el almacen sin Excel.

        Cada sesion de la app empieza sin Excel: al arrancar, el area vacia
        el almacen.
        """
        self._archivo = None
        self._cargado_en = None
        self._datos = None

    def volcar(self, ruta: Path) -> dict[str, Any]:
        """Parsea el fichero y deja el resultado en la cache.

        Args:
            ruta: el fichero ``.xlsx`` a parsear.

        Returns:
            El volcado parseado.

        Raises:
            OperacionError: si el fichero no existe o si tiene una fila mala.
            ConfigInvalidoError: si el config del area no es valido.
        """
        if self.config is None:
            raise ConfigInvalidoError(
                "El config del area no es valido: no se puede leer el Excel maestro."
            )
        datos = parser.leer_excel(ruta, self.config)
        self._datos = datos
        self._archivo = Path(ruta).name
        self._cargado_en = datetime.now().isoformat(timespec="seconds")
        return datos


# ── el volcado ──────────────────────────────────────────────────────────────


def filas_totales(datos: dict[str, Any]) -> int:
    """Cuantas filas hay en todos los dominios del volcado."""
    total = len(datos.get("configuracion", {}).get("filas", []))
    for tabla in datos.get("dispositivos", []):
        total += len(tabla.get("filas", []))
    for tabla in datos.get("procesos", {}).values():
        total += len(tabla.get("filas", []))
    total += len(datos.get("entidades", {}).get("filas", []))
    return total


def avisos(almacen: AlmacenExcel) -> list[str]:
    """Los avisos del ultimo parseo."""
    return list(almacen.estado().get("avisos") or [])


def detalle_de_avisos(avisos: list[str]) -> str:
    """El detalle del paso de avisos: el primero y cuantos quedan."""
    if not avisos:
        return "sin avisos"
    if len(avisos) == 1:
        return avisos[0]
    return f"{avisos[0]} (+{len(avisos) - 1} más)"
