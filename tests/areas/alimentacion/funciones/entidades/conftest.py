"""El doble de TIA del sync de entidades.

El sync escribe en TIA (el N_MAX, la tabla de tags y el DB), asi que el doble
de la prevision no sirve: aqui hace falta un PLC con constantes editables,
bloques que se exportan en SimaticSD y transacciones que se puedan contar.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from zc_suite.areas.alimentacion.config import ConfigArea
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel
from zc_suite.areas.alimentacion.funciones.entidades import (
    generar_prevision as modulo_prevision,
)
from zc_suite.areas.alimentacion.funciones.entidades import (
    sincronizar as modulo_sync,
)
from zc_suite.nucleo.tia import servicio as tia
from zc_suite.nucleo.tia.servicio import ServicioTIA
from zc_suite.nucleo.tia.workdir import Workdir
from zc_suite.simatic.ml import ModificadorConstantesUsuario

#: La version de TIA del doble: la de los comentarios (SimaticSD) necesita V21.
VERSION_TIA = "Siemens TIA Portal V21.0"

#: La carpeta de TIA donde viven la tabla de tags y el DB de las entidades.
CARPETA_ENTIDADES = "6_Entidades"

#: Los bloques de prueba: el DB de las entidades.
ORIGEN_BLOQUES = Path(__file__).resolve().parents[4] / "fixtures" / "source" / "Bloques"

#: El PLC del fixture: el mismo nombre que el PLC de TIA.
NOMBRE_PLC = "ZC_PLC_STD"


class ConstanteFalsa:
    """Una constante de usuario de TIA, con su nombre y su valor."""

    def __init__(self, nombre: str, valor: int) -> None:
        self._nombre = nombre
        self._valor = valor

    def get_property(self, name: str) -> str:
        if name == "Name":
            return self._nombre
        if name == "Value":
            return str(self._valor)
        raise KeyError(name)

    def set_property(self, name: str, value: str) -> int:
        if name == "Name":
            self._nombre = str(value)
        elif name == "Value":
            self._valor = int(value)
        else:
            raise KeyError(name)
        return 0


class TablaSyncFalsa:
    """Una tabla de tags: exporta su XML y deja editar sus constantes."""

    def __init__(
        self,
        nombre: str,
        constantes: tuple[tuple[str, int], ...],
        xml: Callable[[str, tuple[tuple[str, int], ...]], str],
        jerarquia: str = "",
    ) -> None:
        self._nombre = nombre
        self._constantes = constantes
        self._xml = xml
        self._jerarquia = jerarquia
        self.constantes: list[ConstanteFalsa] = [
            ConstanteFalsa(nombre_constante, valor)
            for nombre_constante, valor in constantes
        ]

    def get_name(self) -> str:
        return self._nombre

    def get_user_constants(self) -> list[ConstanteFalsa]:
        return self.constantes

    def export(
        self,
        target_directory_path: str,
        keep_folder_structure: bool = False,
    ) -> None:
        carpeta = Path(target_directory_path)
        if keep_folder_structure and self._jerarquia:
            carpeta = carpeta / self._jerarquia
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / f"{self._nombre}.xml").write_text(
            self._xml(self._nombre, self._constantes_actuales()),
            encoding="utf-8",
        )

    def _constantes_actuales(self) -> tuple[tuple[str, int], ...]:
        """Las constantes como estan **ahora**: el export ve lo ya cambiado."""
        return tuple(
            (constante.get_property("Name"), int(constante.get_property("Value")))
            for constante in self.constantes
        )


class BloqueFalso:
    """Un bloque de datos que se exporta en SimaticSD."""

    def __init__(self, nombre: str, jerarquia: str = "") -> None:
        self._nombre = nombre
        self._jerarquia = jerarquia

    def get_name(self) -> str:
        return self._nombre

    def export(
        self,
        target_directory_path: str,
        export_format: str = "SimaticSD",
        keep_folder_structure: bool = False,
    ) -> None:
        carpeta = Path(target_directory_path)
        if keep_folder_structure and self._jerarquia:
            carpeta = carpeta / self._jerarquia
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / f"{self._nombre}.s7dcl").write_bytes(
            (ORIGEN_BLOQUES / f"{self._nombre}.s7dcl").read_bytes()
        )
        (carpeta / f"{self._nombre}.s7res").write_bytes(
            (ORIGEN_BLOQUES / f"{self._nombre}.s7res").read_bytes()
        )

    def is_consistent(self) -> bool:
        return True

    def compile(self) -> bool:
        return False


class PlcSyncFalso:
    """El PLC del sync: tablas de tags, bloques y la importacion."""

    def __init__(
        self,
        tablas: list[TablaSyncFalsa],
        bloques: list[BloqueFalso],
    ) -> None:
        self._tablas = tablas
        self._bloques = bloques
        #: Las importaciones de tablas que ha hecho el PLC.
        self.importaciones_tablas: list[dict[str, Any]] = []
        #: Las importaciones de bloques que ha hecho el PLC.
        self.importaciones_bloques: list[dict[str, Any]] = []

    def get_name(self) -> str:
        return NOMBRE_PLC

    def get_plc_tag_tables(self) -> list[TablaSyncFalsa]:
        return self._tablas

    def get_program_blocks(self) -> list[BloqueFalso]:
        return self._bloques

    def import_plc_tags(
        self,
        import_root_directory: str,
        target_folder_path: str | None = None,
    ) -> None:
        """Importa las tablas de tags del directorio, como hace TIA."""
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
                    ConstanteFalsa(nombre, int(valor))
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


class EntornoSync:
    """El almacen con el Excel del fixture y un TIA falso conectado."""

    def __init__(
        self,
        servicio: ServicioTIA,
        almacen: AlmacenExcel,
        modelo: ConfigArea,
        plc: PlcSyncFalso,
        proyecto: ProyectoSyncFalso,
        eventos: list[tuple[str, dict[str, Any]]],
    ) -> None:
        self.servicio = servicio
        self.almacen = almacen
        self.modelo = modelo
        self.plc = plc
        self.proyecto = proyecto
        self.eventos = eventos

    def sincronizar(self, sesion: Any = None) -> dict[str, Any]:
        """Lanza el sync y devuelve su resultado."""
        job_id = self.servicio.lanzar(
            modulo_sync.sincronizar,
            plc=NOMBRE_PLC,
            almacen=self.almacen,
            config=self.modelo,
            sesion=sesion,
        )
        return self._esperar(job_id)

    def _esperar(self, job_id: str) -> dict[str, Any]:
        """Espera al evento de fin del trabajo."""
        limite = time.monotonic() + 10.0
        while time.monotonic() < limite:
            for tipo, carga in list(self.eventos):
                if tipo == "job" and carga["job"] == job_id:
                    return carga
            time.sleep(0.005)
        raise AssertionError(f"El trabajo {job_id} no termino.")


# ── el Excel de prueba ──────────────────────────────────────────────────────

#: Las filas de la tabla de entidades del Excel de prueba.
FILAS_ENTIDADES: tuple[tuple[Any, ...], ...] = (
    (NOMBRE_PLC, 1, "ENT_001", "Entidad 1", "Comentario uno", 1, 1),
    (NOMBRE_PLC, 2, "ENT_002_NUEVO", "Entidad 2", "Comentario dos", 1, 2),
    (NOMBRE_PLC, 4, "ENT_004", "Entidad 4", "", 1, 4),
    (NOMBRE_PLC, 99, "ENT_099", "Entidad 99", "", 1, 99),
)


def _anadir_tabla(
    libro: Workbook,
    hoja: str,
    nombre: str,
    cabeceras: list[str],
    filas: list[list[Any]],
) -> None:
    """Escribe una tabla nombrada en la hoja."""
    if hoja not in libro.sheetnames:
        libro.create_sheet(hoja)
    hoja_obj = libro[hoja]
    hoja_obj.append(list(cabeceras))
    inicio = hoja_obj.max_row
    for fila in filas:
        hoja_obj.append(list(fila))
    ref = f"A{inicio}:{get_column_letter(len(cabeceras))}{hoja_obj.max_row}"
    tabla = Table(displayName=nombre, ref=ref)
    tabla.tableStyleInfo = TableStyleInfo(name="TableStyleMedium9", showRowStripes=True)
    hoja_obj.add_table(tabla)


def escribir_excel_entidades(ruta: Path) -> Path:
    """Escribe el Excel de prueba: las entidades y su N_MAX."""
    libro = Workbook()
    libro.remove(libro.active)
    _anadir_tabla(
        libro,
        "CONFIG",
        "Tabla_Dimensiones",
        ["PLC", "N_Max_ENT"],
        [[NOMBRE_PLC, 6]],
    )
    _anadir_tabla(
        libro,
        "ENTIDADES",
        "Tabla_Entidades",
        ["PLC", "Numero", "PLC.Tag", "Descripcion", "PLC.Comentario", "PLC.Tipo", "PLC.Index"],
        [list(fila) for fila in FILAS_ENTIDADES],
    )
    libro.save(ruta)
    return ruta


#: Lo que hay en el PLC: las constantes de usuario de cada tabla.
CONSTANTES_TIA: dict[str, tuple[tuple[str, int], ...]] = {
    "0_Config_Generales": (
        ("N_MAX_ENTIDAD", 3),
    ),
    "6_Entidades": (
        ("ENT_001", 1),
        ("ENT_002", 2),
        ("Constant_1", 99),
        ("ENT_050", 50),
    ),
}


@pytest.fixture
def excel_entidades(tmp_path: Path) -> Path:
    """El Excel del fixture de entidades."""
    return escribir_excel_entidades(tmp_path / "maestro.xlsx")


@pytest.fixture
def constantes_tia_entidades() -> dict[str, tuple[tuple[str, int], ...]]:
    """Lo que hay en el PLC de entidades: las constantes de cada tabla."""
    return CONSTANTES_TIA


@pytest.fixture
def entorno_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    modelo: ConfigArea,
    excel_entidades: Path,
    constantes_tia_entidades: dict[str, tuple[tuple[str, int], ...]],
    xml_tabla: Callable[[str, tuple[tuple[str, int], ...]], str],
) -> Any:
    """El almacen con el Excel del fixture y un TIA falso con transacciones."""
    yield from _entorno(
        tmp_path,
        monkeypatch,
        modelo,
        excel_entidades,
        constantes_tia_entidades,
        xml_tabla,
        VERSION_TIA,
    )


@pytest.fixture
def entorno_sync_v18(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    modelo: ConfigArea,
    excel_entidades: Path,
    constantes_tia_entidades: dict[str, tuple[tuple[str, int], ...]],
    xml_tabla: Callable[[str, tuple[tuple[str, int], ...]], str],
) -> Any:
    """Lo mismo, pero con un TIA Portal V18: sin SimaticSD."""
    yield from _entorno(
        tmp_path,
        monkeypatch,
        modelo,
        excel_entidades,
        constantes_tia_entidades,
        xml_tabla,
        "Siemens TIA Portal V18.0",
    )


def _entorno(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    modelo: ConfigArea,
    excel_entidades: Path,
    constantes_tia: dict[str, tuple[tuple[str, int], ...]],
    xml_tabla: Callable[[str, tuple[tuple[str, int], ...]], str],
    version: str,
) -> Any:
    """Monta el almacen, el Excel y el TIA falso de la version indicada."""
    almacen = AlmacenExcel()
    almacen.config = modelo
    almacen.volcar(excel_entidades)

    workdir = Workdir(base=tmp_path / "entidades", preview_subcarpetas=("disp", "bloques"))
    monkeypatch.setattr(modulo_sync, "workdir", lambda *args, **kwargs: workdir)
    monkeypatch.setattr(modulo_prevision, "workdir_entidades", lambda: workdir)
    # La espera de consolidacion de TIA no aporta nada en un test.
    monkeypatch.setattr(modulo_sync, "PAUSA_CONSOLIDACION_S", 0.0)

    tablas = [
        TablaSyncFalsa(nombre, valores, xml_tabla, CARPETA_ENTIDADES)
        for nombre, valores in constantes_tia.items()
    ]
    plc = PlcSyncFalso(tablas, [BloqueFalso("DB6_ENT", CARPETA_ENTIDADES)])
    proyecto = ProyectoSyncFalso(plc)

    eventos: list[tuple[str, dict[str, Any]]] = []
    servicio = ServicioTIA(
        publicador=lambda tipo, carga: eventos.append((tipo, carga)),
        cargador=lambda: TsSyncFalso(plc, proyecto, version),
    )
    conectar = servicio.lanzar(tia.conectar)
    _esperar_job(eventos, conectar)
    yield EntornoSync(servicio, almacen, modelo, plc, proyecto, eventos)
    servicio.parar()


def _esperar_job(
    eventos: list[tuple[str, dict[str, Any]]],
    job_id: str,
) -> dict[str, Any]:
    """Espera al evento de fin del trabajo indicado."""
    limite = time.monotonic() + 5.0
    while time.monotonic() < limite:
        for tipo, carga in list(eventos):
            if tipo == "job" and carga["job"] == job_id:
                return carga
        time.sleep(0.005)
    raise AssertionError(f"El trabajo {job_id} no termino.")
