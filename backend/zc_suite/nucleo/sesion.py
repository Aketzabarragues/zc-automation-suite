"""zc_suite.nucleo.sesion — el estado de la sesion viva.

La sesion vive **en la memoria del backend**, no en disco: los PLCs, el PLC
seleccionado y los escaneos por PLC. Sobrevive a un F5 de la web (la SPA se
hidrata con un ``GET``) y se pierde al cerrar la app.

Lo que cada area tenga en su sesion lo aporta el area: el nucleo no sabe que
guarda cada una.

El estado lo escriben los trabajos (que corren en el hilo de TIA) y lo leen
las rutas (que corren en el hilo web). Por eso lleva un cerrojo.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

#: Segundos que un escaneo sirve antes de darse por caducado.
TTL_ESCANEO = 300

#: Clave de la sesion en la configuracion de la app.
CLAVE_SESION = "ZC_SESION"

#: Clave del estado de sesion de las areas en la configuracion de la app.
#: Cada valor es un ``callable`` que devuelve el estado del area, para que
#: la respuesta de la sesion lo lea siempre fresco.
CLAVE_SESION_AREAS = "ZC_SESION_AREAS"


@dataclass
class Escaneo:
    """Lo que se escaneo de un PLC.

    El momento del escaneo es lo que dice si el escaneo sigue valiendo: a
    partir de ``TTL_ESCANEO`` segundos hay que volver a escanear.
    """

    #: Nombre del PLC escaneado.
    plc: str
    #: Los bloques del PLC.
    bloques: list[dict[str, Any]] = field(default_factory=list)
    #: Las tablas de tags del PLC.
    tablas: list[dict[str, Any]] = field(default_factory=list)
    #: Los tipos de datos de usuario del PLC.
    tipos: list[dict[str, Any]] = field(default_factory=list)
    #: Cuando se hizo el escaneo.
    momento: datetime = field(default_factory=datetime.now)

    def caducado(self, ttl: int = TTL_ESCANEO) -> bool:
        """``True`` si el escaneo ya no sirve.

        Args:
            ttl: los segundos que un escaneo aguanta.
        """
        return (datetime.now() - self.momento).total_seconds() > ttl

    def estado(self) -> dict[str, Any]:
        """El escaneo, como lo ve la SPA."""
        return {
            "plc": self.plc,
            "bloques": list(self.bloques),
            "tablas": list(self.tablas),
            "tipos": list(self.tipos),
            "momento": self.momento.isoformat(timespec="seconds"),
            "caducado": self.caducado(),
        }


class Sesion:
    """El estado de la sesion: los PLCs, la seleccion y los escaneos.

    La sesion empieza vacia y se vacia al cerrar la app. Al desconectar de
    TIA (o al perder el portal) se vacia todo lo que dependia de la conexion:
    PLCs, seleccion, escaneos y los datos de las areas (como main:
    ``resetPlcState`` y ``area_clear_disp_preview``).

    Los datos de un area (por ejemplo su ultima prevision) van ligados al PLC
    seleccionado: al cambiar de PLC se borran.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._plcs: list[dict[str, Any]] = []
        self._proyecto: dict[str, Any] | None = None
        self._seleccionado: str = ""
        self._escaneos: dict[str, Escaneo] = {}
        self._datos_area: dict[str, dict[str, Any]] = {}

    # ── PLCs ─────────────────────────────────────────────────────────────

    def guardar_plcs(
        self,
        plcs: list[dict[str, Any]],
        proyecto: dict[str, Any] | None = None,
    ) -> None:
        """Guarda la lista de PLCs del proyecto abierto.

        Args:
            plcs: los PLCs encontrados.
            proyecto: nombre y ruta del proyecto.
        """
        with self._lock:
            self._plcs = list(plcs)
            self._proyecto = dict(proyecto) if proyecto else None

    @property
    def plcs(self) -> list[dict[str, Any]]:
        """Los PLCs del proyecto abierto."""
        with self._lock:
            return list(self._plcs)

    @property
    def proyecto(self) -> dict[str, Any] | None:
        """El proyecto abierto."""
        with self._lock:
            return dict(self._proyecto) if self._proyecto else None

    # ── seleccion ────────────────────────────────────────────────────────

    def seleccionar(self, plc: str) -> None:
        """Guarda el PLC seleccionado.

        Cambiar de PLC (o deseleccionar) borra los datos de las areas: eran
        del PLC anterior.

        Args:
            plc: el nombre del PLC. Vacio para deseleccionar.
        """
        with self._lock:
            if plc != self._seleccionado:
                self._datos_area.clear()
            self._seleccionado = plc

    @property
    def seleccionado(self) -> str:
        """El PLC seleccionado."""
        with self._lock:
            return self._seleccionado

    # ── escaneos ─────────────────────────────────────────────────────────

    def guardar_escaneo(
        self,
        plc: str,
        bloques: list[dict[str, Any]],
        tablas: list[dict[str, Any]],
        tipos: list[dict[str, Any]],
    ) -> Escaneo:
        """Guarda el escaneo de un PLC.

        Args:
            plc: el PLC escaneado.
            bloques: los bloques.
            tablas: las tablas de tags.
            tipos: los tipos de datos de usuario.

        Returns:
            El escaneo guardado.
        """
        escaneo = Escaneo(
            plc=plc,
            bloques=list(bloques),
            tablas=list(tablas),
            tipos=list(tipos),
        )
        with self._lock:
            self._escaneos[plc] = escaneo
        return escaneo

    def escaneo(self, plc: str) -> Escaneo | None:
        """El escaneo de un PLC, aunque esté caducado."""
        with self._lock:
            return self._escaneos.get(plc)

    def actualizar_bloques(self, plc: str, bloques: list[dict[str, Any]]) -> None:
        """Actualiza los bloques de un escaneo ya hecho.

        Lo usa el editor de bloques: al renombrar un bloque, el escaneo del
        PLC tiene que reflejar el nombre nuevo. Las tablas de tags y los
        tipos de usuario no cambian, asi que se conservan.

        Si el PLC no tiene escaneo, no se crea uno: un escaneo con solo
        bloques no vale.

        Args:
            plc: el PLC.
            bloques: los bloques recien escaneados.
        """
        with self._lock:
            escaneo = self._escaneos.get(plc)
            if escaneo is None:
                return
            escaneo.bloques = list(bloques)
            escaneo.momento = datetime.now()

    def escaneo_fresco(self, plc: str, ttl: int = TTL_ESCANEO) -> Escaneo | None:
        """El escaneo de un PLC, si sigue valiendo.

        Args:
            plc: el PLC.
            ttl: los segundos que un escaneo aguanta.
        """
        escaneo = self.escaneo(plc)
        if escaneo is None or escaneo.caducado(ttl):
            return None
        return escaneo

    def perder_tia(self) -> None:
        """Vacia lo que dependia de la conexion con TIA.

        Se llama al desconectar y al perder el portal: los PLCs, la
        seleccion, los escaneos y los datos de las areas ya no son de fiar.
        Lo que cada area guarda por su cuenta (lo que no depende de TIA)
        no se toca.
        """
        with self._lock:
            self._plcs = []
            self._proyecto = None
            self._seleccionado = ""
            self._escaneos.clear()
            self._datos_area.clear()

    # ── datos de las areas ───────────────────────────────────────────────

    def guardar_dato_area(self, area: str, clave: str, valor: Any) -> None:
        """Guarda un dato de un area en la sesion (por ejemplo su prevision).

        Args:
            area: identificador del area.
            clave: nombre del dato.
            valor: el dato, en tipos primitivos.
        """
        with self._lock:
            self._datos_area.setdefault(area, {})[clave] = valor

    def borrar_dato_area(self, area: str, clave: str) -> None:
        """Borra un dato de un area, si lo tiene."""
        with self._lock:
            self._datos_area.get(area, {}).pop(clave, None)

    def datos_area(self, area: str) -> dict[str, Any]:
        """Los datos que un area tiene en la sesion."""
        with self._lock:
            return dict(self._datos_area.get(area, {}))

    # ── ciclo de vida ────────────────────────────────────────────────────

    def vaciar(self) -> None:
        """Vacia la sesion entera.

        Se llama al arrancar y al cerrar la app.
        """
        with self._lock:
            self._plcs = []
            self._proyecto = None
            self._seleccionado = ""
            self._escaneos.clear()
            self._datos_area.clear()

    # ── lo que ve la SPA ─────────────────────────────────────────────────

    def estado(self) -> dict[str, Any]:
        """El estado de la sesion, como lo ve la SPA.

        Returns:
            Un dict con ``plcs``, ``proyecto``, ``plc_seleccionado`` y
            ``escaneo`` (el del PLC seleccionado, o ``None``).
        """
        with self._lock:
            seleccionado = self._seleccionado
            escaneo = self._escaneos.get(seleccionado)
            return {
                "plcs": list(self._plcs),
                "proyecto": dict(self._proyecto) if self._proyecto else None,
                "plc_seleccionado": seleccionado,
                "escaneo": escaneo.estado() if escaneo else None,
            }
