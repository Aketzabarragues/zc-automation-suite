"""El doble de TIA de la prevision de procesos.

La prevision solo lee (exporta la tabla de variables y los dos DBs del
proceso y los compara con el Excel), asi que el doble es mas fino que el del
sync: el PLC tiene su tabla de tags con las constantes de N_MAX y sus dos DBs,
que se exportan en SimaticSD desde el fixture.
"""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo
from tests._dobles import (
    PlcSyncFalso,
    ProyectoSyncFalso,
    TsSyncFalso,
)

from zc_suite.areas.alimentacion.config import ConfigArea
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel
from zc_suite.areas.alimentacion.funciones.procesos import (
    crear as modulo_crear,
)
from zc_suite.areas.alimentacion.funciones.procesos import (
    generar_prevision as modulo_prevision,
)
from zc_suite.areas.alimentacion.funciones.procesos import (
    sincronizar as modulo_sync,
)
from zc_suite.nucleo.sesion import Sesion
from zc_suite.nucleo.tia import servicio as tia
from zc_suite.nucleo.tia.servicio import ServicioTIA
from zc_suite.nucleo.tia.workdir import Workdir
from zc_suite.simatic.sd.cabecera import soporta_simaticsd

#: La carpeta de TIA donde viven la tabla de variables y los DBs del proceso.
CARPETA_PROCESOS = "0_Procesos"

#: La version de TIA del doble del sync: la de los comentarios (SimaticSD)
#: necesita V21.
VERSION_TIA = "Siemens TIA Portal V21.0"

#: La carpeta de los bloques del fixture.
ORIGEN_BLOQUES = Path(__file__).resolve().parents[4] / "fixtures" / "source" / "Bloques"

#: El PLC del fixture: el mismo nombre que el PLC de TIA.
NOMBRE_PLC = "ZC_PLC_STD"

#: El uid del proceso de prueba.
PROC_UID = 100

#: Los nombres canonicos TIA del proceso de prueba.
DB_PARAM = "DB53100_CPR_PARAM"
DB_ALM = "DB55100_CPR_ALM"
TABLA_PROCESO = "100_CPR"


class TablaFalsa:
    """Una tabla de tags: exporta su XML plano al destino."""

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

    def get_name(self) -> str:
        return self._nombre

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
            self._xml(self._nombre, self._constantes),
            encoding="utf-8",
        )


class BloqueFalso:
    """Un bloque de datos que se exporta en SimaticSD."""

    def __init__(
        self,
        nombre: str,
        jerarquia: str = "",
        soporta_simaticsd: bool = True,
    ) -> None:
        self._nombre = nombre
        self._jerarquia = jerarquia
        self._soporta_simaticsd = soporta_simaticsd

    def get_name(self) -> str:
        return self._nombre

    def export(
        self,
        target_directory_path: str,
        export_format: str = "SimaticSD",
        keep_folder_structure: bool = False,
    ) -> None:
        if not self._soporta_simaticsd:
            raise RuntimeError(
                "The method is not supported in this API version"
            )
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


class PlcFalso:
    """El PLC de la prevision: su tabla de tags y sus dos DBs."""

    def __init__(
        self,
        tablas: list[TablaFalsa],
        bloques: list[BloqueFalso],
    ) -> None:
        self._tablas = tablas
        self._bloques = bloques

    def get_name(self) -> str:
        return NOMBRE_PLC

    def get_plc_tag_tables(self) -> list[TablaFalsa]:
        return self._tablas

    def get_program_blocks(self) -> list[BloqueFalso]:
        return self._bloques


class ProyectoFalso:
    """El proyecto abierto, con un solo PLC."""

    def __init__(self, plc: PlcFalso) -> None:
        self.plc = plc

    def get_plcs(self) -> list[PlcFalso]:
        return [self.plc]


class PortalFalso:
    """El portal de TIA."""

    def __init__(self, proyecto: ProyectoFalso) -> None:
        self.proyecto = proyecto

    def get_process_id(self) -> int:
        return 4242

    def get_project(self) -> ProyectoFalso:
        return self.proyecto

    def detach(self) -> None:
        pass


class TsFalso:
    """El modulo del SDK de Siemens, con un portal ya abierto."""

    class Enums:
        class PortalMode:
            AnyUserInterface = "cualquier"
            WithGraphicalUserInterface = "con_gui"
            WithoutGraphicalUserInterface = "sin_gui"

    def __init__(self, plc: PlcFalso, version: str = VERSION_TIA) -> None:
        self._version = version
        self.portal = PortalFalso(ProyectoFalso(plc))

    def get_installed_bundles(self) -> list[Any]:
        version = self._version

        class _Bundle:
            def get_title(self) -> str:
                return version

        return [_Bundle()]

    def attach_portal(self, portal_mode: str | None = None) -> PortalFalso:
        return self.portal

    def open_portal(self, portal_mode: str | None = None) -> PortalFalso:
        return self.portal

    def set_logging(self, path: str, console: bool) -> None:
        pass


class Entorno:
    """El almacen con el Excel del fixture y un TIA falso conectado."""

    def __init__(
        self,
        servicio: ServicioTIA,
        almacen: AlmacenExcel,
        modelo: ConfigArea,
        eventos: list[tuple[str, dict[str, Any]]],
    ) -> None:
        self.servicio = servicio
        self.almacen = almacen
        self.modelo = modelo
        self.eventos = eventos

    def prevision(self, proc_uid: int, sesion: Any = None) -> dict[str, Any]:
        """Lanza la prevision de un proceso y devuelve el evento de fin."""
        job_id = self.servicio.lanzar(
            modulo_prevision.generar_prevision,
            proc_uid=proc_uid,
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


def escribir_excel_procesos(ruta: Path) -> Path:
    """Escribe el Excel de prueba: un proceso y sus tres dominios.

    El proceso CPR (uid 100) tiene dos PReals, un PInt y dos alarmas en el
    Excel; TIA lleva tres PReals (uno de mas), dos PInts y tres alarmas.
    """
    libro = Workbook()
    libro.remove(libro.active)
    _anadir_tabla(
        libro,
        "CONFIG",
        "Tabla_Procesos",
        [
            "UID",
            "Nombre",
            "Codigo",
            "PReal",
            "Index_Preal",
            "PInt",
            "Index_Pint",
            "Alarmas",
            "Alarmas_Hmi",
            "PLC",
        ],
        [[PROC_UID, "CPR", "CPR", 2, 1, 1, 1, 2, 2, NOMBRE_PLC]],
    )
    _anadir_tabla(
        libro,
        "P_REAL",
        "Tabla_PReal",
        ["UID", "Numero", "Proceso", "Codigo", "Num.DB", "Descripcion", "ComentarioDB", "PLC"],
        [
            [
                "PR_100_001", 1, "CPR", "CPR", 53100,
                "Parametro real uno", "PARAMETRO UNO", NOMBRE_PLC,
            ],
            [
                "PR_100_002", 2, "CPR", "CPR", 53100,
                "Parametro real dos", "", NOMBRE_PLC,
            ],
        ],
    )
    _anadir_tabla(
        libro,
        "P_INT",
        "Tabla_PInt",
        ["UID", "Numero", "Proceso", "Codigo", "Num.DB", "Descripcion", "ComentarioDB", "PLC"],
        [
            [
                "PI_100_001", 1, "CPR", "CPR", 53100,
                "Parametro entero uno", "PARAMETRO ENTERO UNO", NOMBRE_PLC,
            ],
        ],
    )
    _anadir_tabla(
        libro,
        "ALARMAS",
        "Tabla_Alarmas",
        ["UID", "Numero", "Proceso", "Num.DB", "Descripcion", "ComentarioDB", "PLC"],
        [
            ["AL_100_001", 1, "CPR", 55100, "Alarma uno", "ALARMA UNO", NOMBRE_PLC],
            ["AL_100_002", 2, "CPR", 55100, "Alarma dos", "ALARMA DOS", NOMBRE_PLC],
        ],
    )
    libro.save(ruta)
    return ruta


@pytest.fixture
def excel_procesos(tmp_path: Path) -> Path:
    """El Excel del fixture de procesos."""
    return escribir_excel_procesos(tmp_path / "maestro.xlsx")


def _entorno_prevision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    modelo: ConfigArea,
    excel_procesos: Path,
    xml_tabla: Callable[[str, tuple[tuple[str, int], ...]], str],
    version: str,
) -> Any:
    """Monta el fixture de la prevision para la version de TIA indicada."""
    almacen = AlmacenExcel()
    almacen.config = modelo
    almacen.volcar(excel_procesos)

    workdir = Workdir(base=tmp_path / "procesos", preview_subcarpetas=("disp", "bloques"))
    monkeypatch.setattr(modulo_prevision, "workdir_procesos", lambda: workdir)

    tablas = [
        TablaFalsa(
            TABLA_PROCESO,
            (
                (f"{PROC_UID}_N_MAX_PREAL", 3),
                (f"{PROC_UID}_N_MAX_PINT", 1),
                (f"{PROC_UID}_N_MAX_ALM", 2),
                (f"{PROC_UID}_N_MAX_ALM_HMI", 1),
            ),
            xml_tabla,
            CARPETA_PROCESOS,
        )
    ]
    con_simaticsd = soporta_simaticsd(version)
    bloques = [
        BloqueFalso(DB_PARAM, CARPETA_PROCESOS, con_simaticsd),
        BloqueFalso(DB_ALM, CARPETA_PROCESOS, con_simaticsd),
    ]
    plc = PlcFalso(tablas, bloques)

    eventos: list[tuple[str, dict[str, Any]]] = []
    servicio = ServicioTIA(
        publicador=lambda tipo, carga: eventos.append((tipo, carga)),
        cargador=lambda: TsFalso(plc, version),
    )
    conectar = servicio.lanzar(tia.conectar)
    _esperar_job(eventos, conectar)
    yield Entorno(servicio, almacen, modelo, eventos)
    servicio.parar()


@pytest.fixture
def entorno_prevision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    modelo: ConfigArea,
    excel_procesos: Path,
    xml_tabla: Callable[[str, tuple[tuple[str, int], ...]], str],
) -> Any:
    """El almacen con el Excel del fixture y un TIA falso conectado."""
    yield from _entorno_prevision(
        tmp_path, monkeypatch, modelo, excel_procesos, xml_tabla, VERSION_TIA
    )


@pytest.fixture
def entorno_prevision_v18(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    modelo: ConfigArea,
    excel_procesos: Path,
    xml_tabla: Callable[[str, tuple[tuple[str, int], ...]], str],
) -> Any:
    """La prevision sobre un TIA Portal V18: sin exportacion SimaticSD."""
    yield from _entorno_prevision(
        tmp_path,
        monkeypatch,
        modelo,
        excel_procesos,
        xml_tabla,
        "Siemens TIA Portal V18.0",
    )


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
        orden: list[str] | None = None,
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


class BloqueSyncFalso:
    """Un bloque de datos que se exporta en SimaticSD y se puede compilar."""

    def __init__(
        self,
        nombre: str,
        jerarquia: str = "",
        orden: list[str] | None = None,
        soporta_simaticsd: bool = True,
    ) -> None:
        self._nombre = nombre
        self._jerarquia = jerarquia
        #: La lista compartida de orden de llamadas (export/compile).
        self._orden = orden
        #: Cuantas veces se ha compilado el bloque.
        self.n_compilaciones = 0
        #: Las versiones sin SimaticSD (V18) no dejan exportar bloques.
        self._soporta_simaticsd = soporta_simaticsd

    def get_name(self) -> str:
        return self._nombre

    def export(
        self,
        target_directory_path: str,
        export_format: str = "SimaticSD",
        keep_folder_structure: bool = False,
    ) -> None:
        if not self._soporta_simaticsd:
            raise RuntimeError(
                "The method is not supported in this API version"
            )
        if self._orden is not None:
            self._orden.append(f"export:{self._nombre}")
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
        self.n_compilaciones += 1
        if self._orden is not None:
            self._orden.append(f"compile:{self._nombre}")
        return False


class EntornoSync:
    """El almacen con el Excel del fixture, un escaneo y un TIA conectado."""

    def __init__(
        self,
        servicio: ServicioTIA,
        almacen: AlmacenExcel,
        modelo: ConfigArea,
        plc: PlcSyncFalso,
        proyecto: ProyectoSyncFalso,
        sesion: Sesion,
        eventos: list[tuple[str, dict[str, Any]]],
    ) -> None:
        self.servicio = servicio
        self.almacen = almacen
        self.modelo = modelo
        self.plc = plc
        self.proyecto = proyecto
        self.sesion = sesion
        self.eventos = eventos

    def sincronizar(self, proc_uid: int, sesion: Sesion | None = None) -> dict[str, Any]:
        """Lanza el sync de un proceso y devuelve su evento de fin."""
        if sesion is None:
            sesion = self.sesion
        job_id = self.servicio.lanzar(
            modulo_sync.sincronizar,
            proc_uid=proc_uid,
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


#: Lo que hay en la tabla del proceso en TIA: los N_MAX. El PREAL y el ALM
#: discrepan con el Excel (2 y 1), para que el sync tenga dos N_MAX que aplicar.
CONSTANTES_TIA: tuple[tuple[str, int], ...] = (
    (f"{PROC_UID}_N_MAX_PREAL", 3),
    (f"{PROC_UID}_N_MAX_PINT", 1),
    (f"{PROC_UID}_N_MAX_ALM", 2),
    (f"{PROC_UID}_N_MAX_ALM_HMI", 1),
)


def _escaneo_de(plc: PlcSyncFalso) -> Sesion:
    """Una sesion con un escaneo fresco del PLC del fixture."""
    sesion = Sesion()
    sesion.guardar_escaneo(
        NOMBRE_PLC,
        bloques=[{"nombre": b.get_name()} for b in plc.get_program_blocks()],
        tablas=[{"nombre": t.get_name()} for t in plc.get_plc_tag_tables()],
        tipos=[],
    )
    return sesion


@pytest.fixture
def entorno_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    modelo: ConfigArea,
    excel_procesos: Path,
    xml_tabla: Callable[[str, tuple[tuple[str, int], ...]], str],
) -> Any:
    """El almacen, un escaneo fresco y un TIA falso con transacciones."""
    yield from _entorno(
        tmp_path,
        monkeypatch,
        modelo,
        excel_procesos,
        xml_tabla,
        VERSION_TIA,
    )


@pytest.fixture
def entorno_sync_v18(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    modelo: ConfigArea,
    excel_procesos: Path,
    xml_tabla: Callable[[str, tuple[tuple[str, int], ...]], str],
) -> Any:
    """Lo mismo, pero con un TIA Portal V18: sin SimaticSD."""
    yield from _entorno(
        tmp_path,
        monkeypatch,
        modelo,
        excel_procesos,
        xml_tabla,
        "Siemens TIA Portal V18.0",
    )


def _entorno(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    modelo: ConfigArea,
    excel_procesos: Path,
    xml_tabla: Callable[[str, tuple[tuple[str, int], ...]], str],
    version: str,
) -> Any:
    """Monta el almacen, el Excel y el TIA falso de la version indicada."""
    almacen = AlmacenExcel()
    almacen.config = modelo
    almacen.volcar(excel_procesos)

    workdir = Workdir(base=tmp_path / "procesos", preview_subcarpetas=("disp", "bloques"))
    monkeypatch.setattr(modulo_sync, "workdir", lambda *args, **kwargs: workdir)
    # La prevision post-sync usa su propio workdir: el mismo, para que vea lo
    # que el sync acaba de dejar en disco.
    monkeypatch.setattr(modulo_prevision, "workdir_procesos", lambda: workdir)
    # La espera de consolidacion de TIA no aporta nada en un test.
    monkeypatch.setattr(modulo_sync, "PAUSA_CONSOLIDACION_S", 0.0)

    orden: list[str] = []
    tablas = [TablaSyncFalsa(TABLA_PROCESO, CONSTANTES_TIA, xml_tabla)]
    con_simaticsd = soporta_simaticsd(version)
    bloques = [
        BloqueSyncFalso(DB_PARAM, orden=orden, soporta_simaticsd=con_simaticsd),
        BloqueSyncFalso(DB_ALM, orden=orden, soporta_simaticsd=con_simaticsd),
    ]
    # El doble de sync de procesos no importa tablas de tags: su
    # importacion es solo la de bloques.
    plc = PlcSyncFalso(tablas, bloques, con_importacion_tablas=False)
    plc.orden = orden
    proyecto = ProyectoSyncFalso(plc)

    eventos: list[tuple[str, dict[str, Any]]] = []
    servicio = ServicioTIA(
        publicador=lambda tipo, carga: eventos.append((tipo, carga)),
        cargador=lambda: TsSyncFalso(plc, proyecto, version),
    )
    conectar = servicio.lanzar(tia.conectar)
    _esperar_job(eventos, conectar)
    yield EntornoSync(
        servicio,
        almacen,
        modelo,
        plc,
        proyecto,
        _escaneo_de(plc),
        eventos,
    )
    servicio.parar()


# ── el doble de la aplicacion (crear.py) ───────────────────────────────────
#
# El doble del apply es mas grueso que el del sync: el PLC importa tablas y
# bloques (sin carpeta destino), registra el orden de las llamadas, deja
# fallar cada import de forma programable y expone sus bloques a
# ``escanear_bloques`` (``get_program_blocks``) y a ``compilar_bloques``
# (``is_consistent``/``compile`` por bloque).
#
# El ``modulo_crear`` (importado arriba) es el FB de apply (``crear.py``),
# no la prevision.

#: El nombre de la subcarpeta de la plantilla de prueba del apply.
PLANTILLA_NOMBRE = "50500_CIP1"

#: La carpeta de los bloques dentro de la exportacion de TIA (la plantilla).
CARPETA_BLOQUES_APPLY = "Bloques de programa"

#: La carpeta de las tablas de variables dentro de la exportacion de TIA.
CARPETA_VARIABLES_APPLY = "Variables PLC"


class BloqueCompilableFalso:
    """Un bloque que se puede compilar (``compilar_bloques``)."""

    def __init__(self, nombre: str, error: str | None = None) -> None:
        self._nombre = nombre
        self._error = error
        self.n_compilaciones = 0

    def get_name(self) -> str:
        return self._nombre

    def get_property(self, name: str) -> Any:
        if name == "Name":
            return self._nombre
        return None

    def get_properties(self) -> list[str]:
        return ["Name"]

    def is_consistent(self) -> bool:
        return False

    def compile(self) -> Any:
        self.n_compilaciones += 1
        if self._error is not None:
            raise RuntimeError(self._error)
        return False


class TablaCrearFalso:
    """Una tabla de tags del PLC, lo minimo que ``escanear_tablas_tags``
    necesita."""

    def __init__(self, nombre: str) -> None:
        self._nombre = nombre

    def get_name(self) -> str:
        return self._nombre


class PlcCrearFalso:
    """El PLC del apply: tablas, bloques y las importaciones."""

    def __init__(
        self,
        orden: list[str],
        bloques: list[Any] | None = None,
        fallo_import_tablas: str | None = None,
        fallo_import_bloques: str | None = None,
    ) -> None:
        self._orden = orden
        self._bloques = bloques if bloques is not None else []
        self._fallo_import_tablas = fallo_import_tablas
        self._fallo_import_bloques = fallo_import_bloques
        self.importaciones_tablas: list[dict[str, Any]] = []
        self.importaciones_bloques: list[dict[str, Any]] = []
        #: Las tablas de tags del PLC (``escanear_tablas_tags``).
        self.tablas: list[TablaCrearFalso] = []
        #: Falla ``escanear_bloques`` en el paso "escaneo" del apply (el
        #: import ya esta confirmado; el test comprueba que el refresco no
        #: tumba el trabajo).
        self.fallo_escaneo_bloques: str | None = None
        #: Puerta para bloquear un import y soltarlo desde el test: simula un
        #: TIA lento para que la cancelacion caiga mientras el import esta en
        #: curso (la cancelacion se respeta entre pasos, no dentro de un
        #: import que ya arranco).
        self.bloquea_import = False
        self.esperando_import = threading.Event()
        self.libera_import = threading.Event()

    def _esperar_libre(self) -> None:
        if self.bloquea_import:
            self.esperando_import.set()
            self.libera_import.wait(timeout=30.0)

    def get_name(self) -> str:
        return NOMBRE_PLC

    def get_plc_tag_tables(self) -> list[Any]:
        return self.tablas

    def get_program_blocks(self) -> list[Any]:
        if self.fallo_escaneo_bloques is not None:
            raise RuntimeError(self.fallo_escaneo_bloques)
        return self._bloques

    def import_plc_tags(
        self,
        import_root_directory: str,
        target_folder_path: str | None = None,
    ) -> None:
        self._orden.append("import_tablas")
        self.importaciones_tablas.append(
            {
                "directorio": import_root_directory,
                "carpeta_destino": target_folder_path,
            }
        )
        self._esperar_libre()
        if self._fallo_import_tablas is not None:
            raise RuntimeError(self._fallo_import_tablas)

    def import_blocks(
        self,
        import_root_directory: str,
        target_folder_path: str | None = None,
    ) -> None:
        self._orden.append("import_bloques")
        self.importaciones_bloques.append(
            {
                "directorio": import_root_directory,
                "carpeta_destino": target_folder_path,
            }
        )
        self._esperar_libre()
        if self._fallo_import_bloques is not None:
            raise RuntimeError(self._fallo_import_bloques)


class ProyectoCrearFalso:
    """El proyecto del apply, con transacciones."""

    def __init__(self, plc: PlcCrearFalso) -> None:
        self.plc = plc
        self.transacciones: list[dict[str, Any]] = []

    def get_plcs(self) -> list[PlcCrearFalso]:
        return [self.plc]

    def start_transaction(self, undo_text: str = "", dialog_text: str = "") -> None:
        self.transacciones.append({"inicio": undo_text})

    def end_transaction(self, rollback: bool = False) -> None:
        self.transacciones.append({"rollback": rollback})


class PortalCrearFalso:
    """El portal del apply."""

    def __init__(self, proyecto: ProyectoCrearFalso) -> None:
        self.proyecto = proyecto

    def get_process_id(self) -> int:
        return 4242

    def get_project(self) -> ProyectoCrearFalso:
        return self.proyecto

    def detach(self) -> None:
        pass


class TsCrearFalso:
    """El modulo del SDK del apply, con un portal ya abierto."""

    class Enums:
        class PortalMode:
            AnyUserInterface = "cualquier"
            WithGraphicalUserInterface = "con_gui"
            WithoutGraphicalUserInterface = "sin_gui"

    def __init__(
        self,
        plc: PlcCrearFalso,
        proyecto: ProyectoCrearFalso,
        version: str = VERSION_TIA,
    ) -> None:
        self._version = version
        self.portal = PortalCrearFalso(proyecto)

    def get_installed_bundles(self) -> list[Any]:
        version = self._version

        class _Bundle:
            def get_title(self) -> str:
                return version

        return [_Bundle()]

    def attach_portal(self, portal_mode: str | None = None) -> PortalCrearFalso:
        return self.portal

    def open_portal(self, portal_mode: str | None = None) -> PortalCrearFalso:
        return self.portal

    def set_logging(self, path: str, console: bool) -> None:
        pass


class EntornoCrear:
    """El almacen, un escaneo y un TIA falso que acepta el apply."""

    def __init__(
        self,
        servicio: ServicioTIA,
        almacen: AlmacenExcel,
        modelo: ConfigArea,
        plc: PlcCrearFalso,
        proyecto: ProyectoCrearFalso,
        sesion: Sesion,
        eventos: list[tuple[str, dict[str, Any]]],
        orden: list[str],
        plantillas: Path,
    ) -> None:
        self.servicio = servicio
        self.almacen = almacen
        self.modelo = modelo
        self.plc = plc
        self.proyecto = proyecto
        self.sesion = sesion
        self.eventos = eventos
        self.orden = orden
        self.plantillas = plantillas

    def lanzar(self, **params: Any) -> str:
        """Encola el apply de crear y devuelve su ``job_id`` (sin esperar)."""
        sesion = params.pop("sesion", None)
        if sesion is None:
            sesion = self.sesion
        plantillas_dir = params.pop("plantillas_dir", None)
        return self.servicio.lanzar(
            modulo_crear.crear,
            almacen=self.almacen,
            config=self.modelo,
            sesion=sesion,
            plantillas_dir=plantillas_dir
            if plantillas_dir is not None
            else self.plantillas,
            **params,
        )

    def crear(
        self,
        proc_uid: int,
        sesion: Sesion | None = None,
        plantillas_dir: Path | None = None,
        dir_plantilla: str = PLANTILLA_NOMBRE,
    ) -> dict[str, Any]:
        """Lanza el apply de crear y devuelve su evento de fin."""
        job_id = self.lanzar(
            proc_uid=proc_uid,
            plc=NOMBRE_PLC,
            dir_plantilla_nombre=dir_plantilla,
            sesion=sesion,
            plantillas_dir=plantillas_dir,
        )
        return self._esperar(job_id)

    def _esperar(self, job_id: str) -> dict[str, Any]:
        """Espera al evento de fin del trabajo."""
        limite = time.monotonic() + 15.0
        while time.monotonic() < limite:
            for tipo, carga in list(self.eventos):
                if tipo == "job" and carga["job"] == job_id:
                    return carga
            time.sleep(0.005)
        raise AssertionError(f"El trabajo {job_id} no termino.")


def _plantilla_apply(raiz: Path) -> Path:
    """La plantilla 50500 con su XML de variables (N_MAX) para el apply."""
    dir_plantilla = raiz / PLANTILLA_NOMBRE
    (dir_plantilla / CARPETA_BLOQUES_APPLY).mkdir(parents=True)
    for bloque in ("DB50500_CIP1_INTERFAZ", "FC50501_CIP1_ORDENES"):
        (dir_plantilla / CARPETA_BLOQUES_APPLY / f"{bloque}.s7dcl").write_bytes(
            b"END_DATA_BLOCK\r\n"
        )
        (dir_plantilla / CARPETA_BLOQUES_APPLY / f"{bloque}.s7res").write_bytes(
            b"es-ES\r\n"
        )
    (dir_plantilla / CARPETA_VARIABLES_APPLY).mkdir()
    (dir_plantilla / CARPETA_VARIABLES_APPLY / "50500_CIP1.xml").write_text(
        _xml_tabla_plantilla(),
        encoding="utf-8",
    )
    manifest = {
        "base": 50500,
        "codigo": "CIP1",
        "nombre": "Principal",
        "descripcion": "Plantilla de proceso de alimentacion.",
        "dependencias": ["DB1_SYS"],
        "minimos": {"N_MAX_PREAL": 1, "N_MAX_PINT": 1},
    }
    (dir_plantilla / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return dir_plantilla


def _xml_tabla_plantilla() -> str:
    """El XML de la tabla de variables de la plantilla, con los N_MAX.

    Mismo formato que ``xml_de_tabla`` del conftest del area: cada constante
    es un ``SW.Tags.PlcUserConstant`` con su ``<Name>`` y su ``<Value>``.
    El nombre ya lleva la base nueva (``100_``), porque el XML de la
    plantilla pasa por ``dicc_xml`` y ahi se fija la base del proceso nuevo.
    """
    constantes = [
        ("100_N_MAX_PREAL", 1),
        ("100_N_MAX_PINT", 1),
        ("100_N_MAX_ALM", 2),
        ("100_N_MAX_ALM_HMI", 2),
    ]
    partes = [
        '<?xml version="1.0" encoding="utf-8"?>',
        "<Document>",
        '  <SW.Tags.PlcTagTable ID="0">',
        "    <ObjectList>",
    ]
    for indice, (nombre_constante, valor) in enumerate(constantes, start=1):
        partes.append(
            f'      <SW.Tags.PlcUserConstant ID="{indice}">\n'
            f"        <AttributeList><Name>{nombre_constante}</Name>"
            f"<Value>{valor}</Value></AttributeList>\n"
            "      </SW.Tags.PlcUserConstant>"
        )
    partes += ["    </ObjectList>", "  </SW.Tags.PlcTagTable>", "</Document>", ""]
    return "\n".join(partes)


def _entorno_crear(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    modelo: ConfigArea,
    excel_procesos: Path,
    version: str,
    plantillas: Path,
    fallo_import_tablas: str | None = None,
    fallo_import_bloques: str | None = None,
    bloques: list[Any] | None = None,
) -> Any:
    """Monta el fixture del apply para la version de TIA indicada."""
    almacen = AlmacenExcel()
    almacen.config = modelo
    almacen.volcar(excel_procesos)

    workdir = Workdir(
        base=tmp_path / "procesos_crear",
        carpetas_contexto=("Plantilla", "Nuevo"),
    )
    monkeypatch.setattr(modulo_crear, "workdir_crear", lambda: workdir)
    # La pausa de consolidacion de TIA no aporta nada en un test.
    monkeypatch.setattr(modulo_crear, "TIA_CONSOLIDATION_SLEEP_S", 0.0)

    orden: list[str] = []
    plc = PlcCrearFalso(
        orden,
        bloques=bloques,
        fallo_import_tablas=fallo_import_tablas,
        fallo_import_bloques=fallo_import_bloques,
    )
    proyecto = ProyectoCrearFalso(plc)

    eventos: list[tuple[str, dict[str, Any]]] = []
    servicio = ServicioTIA(
        publicador=lambda tipo, carga: eventos.append((tipo, carga)),
        cargador=lambda: TsCrearFalso(plc, proyecto, version),
    )
    conectar = servicio.lanzar(tia.conectar)
    _esperar_job(eventos, conectar)
    yield EntornoCrear(
        servicio,
        almacen,
        modelo,
        plc,
        proyecto,
        _sesion_apply(),
        eventos,
        orden,
        plantillas,
    )
    servicio.parar()


def _sesion_con_escaneo(bloques: list[dict[str, str]]) -> Sesion:
    """Una sesion con un escaneo fresco del PLC y los bloques dados."""
    sesion = Sesion()
    sesion.guardar_escaneo(
        NOMBRE_PLC,
        bloques=bloques,
        tablas=[{"nombre": TABLA_PROCESO}],
        tipos=[],
    )
    return sesion


def _sesion_apply() -> Sesion:
    """Una sesion con un escaneo fresco que incluye la dependencia."""
    return _sesion_con_escaneo(
        bloques=[{"nombre": "DB1_SYS"}, {"nombre": "DB999_OTRO"}]
    )


@pytest.fixture
def entorno_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    modelo: ConfigArea,
    excel_procesos: Path,
) -> Any:
    """El almacen, un escaneo fresco y un TIA falso que acepta el apply."""
    plantillas = tmp_path / "plantillas_apply"
    _plantilla_apply(plantillas)
    yield from _entorno_crear(
        tmp_path,
        monkeypatch,
        modelo,
        excel_procesos,
        VERSION_TIA,
        plantillas,
    )


@pytest.fixture
def entorno_apply_v18(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    modelo: ConfigArea,
    excel_procesos: Path,
) -> Any:
    """Lo mismo, pero con un TIA Portal V18: no soporta SimaticSD."""
    plantillas = tmp_path / "plantillas_apply"
    _plantilla_apply(plantillas)
    yield from _entorno_crear(
        tmp_path,
        monkeypatch,
        modelo,
        excel_procesos,
        "Siemens TIA Portal V18.0",
        plantillas,
    )

