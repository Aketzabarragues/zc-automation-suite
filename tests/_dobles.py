"""Dobles de TIA compartidos por los conftest de sync de las areas.

``PlcSyncFalso``, ``ProyectoSyncFalso``, ``PortalSyncFalso`` y
``TsSyncFalso`` estaban copiados en los tres conftest de
``tests/areas/alimentacion/funciones/`` (dispositivos, entidades y
procesos). Aqui viven una unica vez; cada conftest los importa:

    from tests._dobles import (
        PlcSyncFalso,
        PortalSyncFalso,
        ProyectoSyncFalso,
        TsSyncFalso,
    )

El import funciona porque ``pyproject.toml`` lleva
``pythonpath = ["backend", "."]`` (la raiz del repo en el ``sys.path``)
y ``tests/`` **no** es un paquete (no tiene ``__init__.py``): pytest
recoge los test con ``--import-mode=importlib`` sin depender de
paquetes, y este modulo, al no empezar por ``test_``, nunca se recoge
como test.

Las diferencias entre las tres copias antiguas se resolvieron con
parametros de ``PlcSyncFalso``:

- ``nombre`` (por defecto ``"ZC_PLC_STD"``): lo que devuelve
  ``get_name()``. Antes, dispositivos devolvia el literal y entidades y
  procesos la constante ``NOMBRE_PLC`` (mismo valor).
- ``con_importacion_tablas`` (por defecto ``True``): si el area usa la
  importacion de tablas de tags del doble. El metodo ``import_plc_tags``
  y ``importaciones_tablas`` estan siempre presentes; el flag solo
  documenta el uso (procesos lo pasa a ``False``: su doble anterior no
  importaba tablas y sus tests no llaman al metodo).
- ``constante`` (por defecto ``None``): la clase de constante de usuario
  de cada conftest, que el doble necesita para reconstruir las constantes
  de una tabla tras ``import_plc_tags``. Solo se usa si el conftest pasa
  tablas que se importan.

Las tablas y los bloques llegan ya construidos desde cada conftest
(``TablaSyncFalsa``, ``BloqueFalso``/``BloqueSyncFalso`` son clases
propias de cada conftest), asi que este modulo no los conoce: en los
type hints, ``Any``.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from zc_suite.simatic.ml import ModificadorConstantesUsuario

#: La version de TIA del doble: la de los comentarios (SimaticSD) necesita V21.
VERSION_TIA = "Siemens TIA Portal V21.0"

#: El nombre del PLC del fixture: el mismo que el de TIA.
NOMBRE_PLC = "ZC_PLC_STD"


class ProyectoFalso:
    """El proyecto abierto, con un solo PLC."""

    def __init__(self, plc: Any) -> None:
        self.plc = plc

    def get_plcs(self) -> list[Any]:
        return [self.plc]


class PortalFalso:
    """El portal de TIA, con el proyecto ya construido."""

    def __init__(self, plc: Any | None = None) -> None:
        self.proyecto = ProyectoFalso(plc) if plc is not None else None

    def get_project(self) -> ProyectoFalso | None:
        return self.proyecto


class PortalWebFalso:
    """El portal minimo de las rutas web: proyecto cerrado y sin pid real."""

    def get_process_id(self) -> int:
        return 4242

    def get_project(self) -> None:
        return None

    def detach(self) -> None:
        pass


class TsFalso:
    """Doble minimo del modulo ``siemens_tia_scripting``."""

    def __init__(self, modo_usuario: str = "cualquier") -> None:
        class _PortalMode:
            # El literal varia entre los ficheros que lo definian; los tests
            # y el servicio no lo leen, asi que se queda como parametro.
            AnyUserInterface = modo_usuario
            WithGraphicalUserInterface = "con_gui"
            WithoutGraphicalUserInterface = "sin_gui"

        class _Enums:
            PortalMode = _PortalMode

        self.Enums = _Enums

    def set_logging(self, path: str, console: bool) -> None:
        pass


class TsRutasFalso:
    """El modulo del SDK de las rutas web: un portal minimo, ya conectado."""

    class Enums:
        class PortalMode:
            AnyUserInterface = "cualquier"
            WithGraphicalUserInterface = "con_gui"
            WithoutGraphicalUserInterface = "sin_gui"

    def __init__(self) -> None:
        self.portal = PortalWebFalso()

    def attach_portal(self, portal_mode: str | None = None) -> PortalWebFalso:
        return self.portal

    def open_portal(self, portal_mode: str | None = None) -> PortalWebFalso:
        return self.portal

    def set_logging(self, path: str, console: bool) -> None:
        pass


class PlcSyncFalso:
    """El PLC del sync: tablas de tags, bloques y la importacion."""

    def __init__(
        self,
        tablas: list[Any],
        bloques: list[Any],
        nombre: str = NOMBRE_PLC,
        con_importacion_tablas: bool = True,
        constante: Callable[[str, int], Any] | None = None,
    ) -> None:
        self._tablas = tablas
        self._bloques = bloques
        self._nombre = nombre
        #: Las importaciones de tablas que ha hecho el PLC.
        self.importaciones_tablas: list[dict[str, Any]] = []
        #: Las importaciones de bloques que ha hecho el PLC.
        self.importaciones_bloques: list[dict[str, Any]] = []
        self._con_importacion_tablas = con_importacion_tablas
        self._constante = constante

    def get_name(self) -> str:
        return self._nombre

    def get_plc_tag_tables(self) -> list[Any]:
        return self._tablas

    def get_program_blocks(self) -> list[Any]:
        return self._bloques

    def import_plc_tags(
        self,
        import_root_directory: str,
        target_folder_path: str | None = None,
    ) -> None:
        """Importa las tablas de tags del directorio, como hace TIA.

        La clase de la constante es la de cada conftest (``constante``):
        el doble no sabe nada de ``ConstanteFalsa``.
        """
        self.importaciones_tablas.append(
            {
                "directorio": import_root_directory,
                "carpeta_destino": target_folder_path,
            }
        )
        for xml in sorted(Path(import_root_directory).rglob("*.xml")):
            modificador = ModificadorConstantesUsuario(xml)
            valores = modificador.leer_constantes_con_valores()
            for tabla in self._tablas:
                if tabla.get_name() != xml.stem:
                    continue
                tabla.constantes = [
                    self._constante(nombre, int(valor))
                    for valor, nombre in valores.items()
                ]

    def import_blocks(
        self,
        import_root_directory: str,
        target_folder_path: str | None = None,
    ) -> None:
        """Importa los bloques del directorio, como hace TIA."""
        self.importaciones_bloques.append(
            {
                "directorio": import_root_directory,
                "carpeta_destino": target_folder_path,
            }
        )


class ProyectoSyncFalso:
    """El proyecto abierto, con un solo PLC."""

    def __init__(self, plc: PlcSyncFalso) -> None:
        self.plc = plc
        #: Las transacciones que se han abierto y cerrado.
        self.transacciones: list[dict[str, Any]] = []

    def get_plcs(self) -> list[PlcSyncFalso]:
        return [self.plc]

    def start_transaction(self, undo_text: str = "", dialog_text: str = "") -> None:
        self.transacciones.append({"inicio": undo_text})

    def end_transaction(self, rollback: bool = False) -> None:
        self.transacciones.append({"rollback": rollback})


class PortalSyncFalso:
    """El portal de TIA."""

    def __init__(self, proyecto: ProyectoSyncFalso) -> None:
        self.proyecto = proyecto

    def get_process_id(self) -> int:
        return 4242

    def get_project(self) -> ProyectoSyncFalso:
        return self.proyecto

    def detach(self) -> None:
        pass


class TsSyncFalso:
    """El modulo del SDK de Siemens, con un portal ya abierto."""

    class Enums:
        class PortalMode:
            AnyUserInterface = "cualquier"
            WithGraphicalUserInterface = "con_gui"
            WithoutGraphicalUserInterface = "sin_gui"

    def __init__(
        self,
        plc: PlcSyncFalso,
        proyecto: ProyectoSyncFalso,
        version: str = VERSION_TIA,
    ) -> None:
        self._version = version
        self.portal = PortalSyncFalso(proyecto)

    def get_installed_bundles(self) -> list[Any]:
        version = self._version

        class _Bundle:
            def get_title(self) -> str:
                return version

        return [_Bundle()]

    def attach_portal(self, portal_mode: str | None = None) -> PortalSyncFalso:
        return self.portal

    def open_portal(self, portal_mode: str | None = None) -> PortalSyncFalso:
        return self.portal

    def set_logging(self, path: str, console: bool) -> None:
        pass
