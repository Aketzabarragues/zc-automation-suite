"""El doble de TIA del sync de dispositivos.

El sync escribe en TIA (constantes, tablas de tags y bloques), asi que el
doble de la prevision no sirve: aqui hace falta un PLC con constantes
editables, bloques que se exportan en SimaticSD y transacciones que se puedan
contar.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from tests._dobles import (
    PlcSyncFalso,
    ProyectoSyncFalso,
    TsSyncFalso,
)

from zc_suite.areas.alimentacion.config import ConfigArea
from zc_suite.areas.alimentacion.excel.almacen import AlmacenExcel
from zc_suite.areas.alimentacion.funciones.dispositivos import (
    generar_prevision as modulo_prevision,
)
from zc_suite.areas.alimentacion.funciones.dispositivos import (
    sincronizar as modulo_sync,
)
from zc_suite.nucleo.tia import servicio as tia
from zc_suite.nucleo.tia.servicio import ServicioTIA
from zc_suite.nucleo.tia.workdir import Workdir

#: La version de TIA del doble: la de los comentarios (SimaticSD) necesita V21.
VERSION_TIA = "Siemens TIA Portal V21.0"

#: La carpeta de TIA donde viven los DBs de dispositivos.
CARPETA_DISPOSITIVOS = "2000_Dispositivos"

#: Los bloques de prueba: el DB de las entradas digitales.
ORIGEN_BLOQUES = Path(__file__).resolve().parents[4] / "fixtures" / "source" / "Bloques"


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
            plc="ZC_PLC_STD",
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


@pytest.fixture
def entorno_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    modelo: ConfigArea,
    excel_dispositivos: Path,
    constantes_tia: dict[str, tuple[tuple[str, int], ...]],
    xml_tabla: Callable[[str, tuple[tuple[str, int], ...]], str],
) -> Any:
    """El almacen con el Excel del fixture y un TIA falso con transacciones."""
    yield from _enterno(
        tmp_path,
        monkeypatch,
        modelo,
        excel_dispositivos,
        constantes_tia,
        xml_tabla,
        VERSION_TIA,
    )


@pytest.fixture
def entorno_sync_v18(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    modelo: ConfigArea,
    excel_dispositivos: Path,
    constantes_tia: dict[str, tuple[tuple[str, int], ...]],
    xml_tabla: Callable[[str, tuple[tuple[str, int], ...]], str],
) -> Any:
    """Lo mismo, pero con un TIA Portal V18: sin SimaticSD."""
    yield from _enterno(
        tmp_path,
        monkeypatch,
        modelo,
        excel_dispositivos,
        constantes_tia,
        xml_tabla,
        "Siemens TIA Portal V18.0",
    )


def _enterno(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    modelo: ConfigArea,
    excel_dispositivos: Path,
    constantes_tia: dict[str, tuple[tuple[str, int], ...]],
    xml_tabla: Callable[[str, tuple[tuple[str, int], ...]], str],
    version: str,
) -> Any:
    """Monta el almacen, el Excel y el TIA falso de la version indicada."""
    almacen = AlmacenExcel()
    almacen.config = modelo
    almacen.volcar(excel_dispositivos)

    workdir = Workdir(base=tmp_path / "disp", preview_subcarpetas=("config", "disp"))
    monkeypatch.setattr(modulo_sync, "workdir", lambda *args, **kwargs: workdir)
    monkeypatch.setattr(
        modulo_prevision,
        "workdir_dispositivos",
        lambda: workdir,
    )
    # La espera de consolidacion de TIA no aporta nada en un test.
    monkeypatch.setattr(modulo_sync, "PAUSA_CONSOLIDACION_S", 0.0)

    tablas = [
        TablaSyncFalsa(
            nombre,
            valores,
            xml_tabla,
            CARPETA_DISPOSITIVOS if nombre.startswith("2000_Disp_") else "",
        )
        for nombre, valores in constantes_tia.items()
    ]
    plc = PlcSyncFalso(
        tablas,
        [BloqueFalso("DB2000_ED", CARPETA_DISPOSITIVOS)],
        constante=ConstanteFalsa,
    )
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
