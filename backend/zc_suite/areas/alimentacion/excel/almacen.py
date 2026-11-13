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

from zc_suite.areas.alimentacion.config import ConfigArea, ConfigInvalidoError, n_max_de
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

    def dispositivos_de(self, tipo: str, plc: str) -> list[dict[str, Any]]:
        """Los dispositivos de un tipo, filtrados por PLC.

        Args:
            tipo: la clave del tipo de dispositivo (``"ed"``...).
            plc: el nombre del PLC.

        Returns:
            Las filas del Excel de ese tipo que son de ese PLC.
        """
        for tabla in self.estado()["dispositivos"]:
            if tabla["tipo"] != tipo:
                continue
            return [fila for fila in tabla["filas"] if str(fila.get("plc_name", "")) == plc]
        return []

    def entidades_de(self, plc: str) -> list[dict[str, Any]]:
        """Las entidades del Excel del PLC elegido.

        Args:
            plc: el nombre del PLC.

        Returns:
            Las filas del Excel de entidades que son de ese PLC.
        """
        return [
            fila
            for fila in self.estado()["entidades"]["filas"]
            if str(fila.get("plc_name", "")) == plc
        ]

    def n_max_de_entidades(self, plc: str) -> dict[str, int]:
        """El N_MAX de las entidades del Excel del PLC elegido.

        El N_MAX de las entidades vive en su propia tabla del Excel, no en
        la de los dispositivos: aqui no entra.

        Args:
            plc: el nombre del PLC.

        Returns:
            ``{nombre de la constante: valor}``. Vacio si el PLC no esta en
            el Excel o si la celda esta vacia.
        """
        if self.config is None:
            return {}
        constante = self.config.entidades.nmax.constante
        for fila in self.estado()["configuracion"]["filas"]:
            if str(fila.get("PLC", "")) != plc:
                continue
            valor = fila.get(constante)
            if isinstance(valor, (int, float)):
                return {constante: int(valor)}
            return {}
        return {}

    def valores_n_max_de(self, plc: str) -> dict[str, int]:
        """Los N_MAX de dispositivos del Excel del PLC elegido.

        Los N_MAX de las entidades son otra cosa (van en su propia tabla): aqui
        no entran, igual que en ``main``.

        El orden es el del catalogo de N_MAX, no el de las columnas del Excel:
        las tarjetas de N_MAX se pintan en ese orden.

        Args:
            plc: el nombre del PLC.

        Returns:
            ``{nombre de la constante: valor}``. Vacio si el PLC no esta en
            el Excel.
        """
        if self.config is None:
            return {}
        for fila in self.estado()["configuracion"]["filas"]:
            if str(fila.get("PLC", "")) != plc:
                continue
            valores: dict[str, int] = {}
            for entrada in n_max_de(self.config):
                if not entrada.tipo:
                    continue
                valor = fila.get(entrada.constante)
                if isinstance(valor, (int, float)):
                    valores[entrada.constante] = int(valor)
            return valores
        return {}

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
