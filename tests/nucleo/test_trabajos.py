"""Tests de los trabajos que lanza la SPA: escanear, preparar y editar.

Ningun test toca TIA de verdad: el modulo ``siemens_tia_scripting`` y el
portal son dobles propios.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from zc_suite import tia, trabajos
from zc_suite.tia import ServicioTIA

CABECERA_SD = """DATA_BLOCK "DB10"
{ S7_BlockTitle := "MLC_t1"
  S7_BlockComment := "MLC_c1" }
"""

RES_S7 = """MultiLingualTexts:
  - id: MLC_t1
    es-ES: "El titulo"
  - id: MLC_c1
    es-ES: "El comentario"
"""


# ── dobles de test ─────────────────────────────────────────────────────────


class BloqueFalso:
    def __init__(self, nombre: str, ruta: str = "") -> None:
        self._nombre = nombre
        self._ruta = ruta
        self.propiedades = {"Number": "10", "ProgrammingLanguage": "DB"}
        self.exportado = False

    def get_name(self) -> str:
        return self._nombre

    def get_path(self) -> str:
        return self._ruta

    def get_properties(self) -> list[str]:
        return list(self.propiedades)

    def get_property(self, name: str) -> Any:
        if name == "Name":
            return self._nombre
        return self.propiedades.get(name)

    def set_property(self, name: str, value: str) -> int:
        if name == "Name":
            self._nombre = value
        else:
            self.propiedades[name] = value
        return 0

    def export(
        self,
        target_directory_path: str,
        export_format: str = "SimaticSD",
        keep_folder_structure: bool = False,
    ) -> None:
        self.exportado = True
        base = Path(target_directory_path) / self._nombre
        base.with_suffix(".s7dcl").write_text(CABECERA_SD, encoding="utf-8")
        base.with_suffix(".s7res").write_text(RES_S7, encoding="utf-8")


class TablaFalsa:
    def __init__(self, nombre: str) -> None:
        self._nombre = nombre

    def get_name(self) -> str:
        return self._nombre

    def get_path(self) -> str:
        return ""


class PlcFalso:
    def __init__(self, bloques: list[BloqueFalso] | None = None) -> None:
        self.bloques = bloques or []
        self.tablas = [TablaFalsa("2000_Disp_ED")]

    def get_name(self) -> str:
        return "ZC_PLC_STD"

    def get_program_blocks(self) -> list[BloqueFalso]:
        return self.bloques

    def get_plc_tag_tables(self) -> list[TablaFalsa]:
        return self.tablas

    def get_user_data_types(self) -> list[Any]:
        return []


class ProyectoFalso:
    def __init__(self, plc: PlcFalso) -> None:
        self.plc = plc
        self.transacciones: list[tuple[str, Any]] = []

    def get_plcs(self) -> list[PlcFalso]:
        return [self.plc]

    def get_property(self, name: str) -> Any:
        if name == "Name":
            return "ZC_PLC_STD"
        if name == "Path":
            return "D:\\Proyectos\\ZC_PLC_STD.ap21"
        return None

    def start_transaction(self, undo_text: str, dialog_text: str) -> None:
        self.transacciones.append(("start", undo_text))

    def end_transaction(self, rollback: bool | None = None) -> None:
        self.transacciones.append(("end", rollback))


class PortalFalso:
    def __init__(self, proyecto: ProyectoFalso) -> None:
        self.proyecto = proyecto

    def get_process_id(self) -> int:
        return 4242

    def get_project(self) -> ProyectoFalso:
        return self.proyecto

    def detach(self) -> None:
        pass


class TsFalso:
    class Enums:
        class PortalMode:
            AnyUserInterface = "cualquier"
            WithGraphicalUserInterface = "con_gui"
            WithoutGraphicalUserInterface = "sin_gui"

    def __init__(self, version: str, plc: PlcFalso) -> None:
        self.version = version
        self.portal = PortalFalso(ProyectoFalso(plc))

    def get_installed_bundles(self) -> list[Any]:
        class _Bundle:
            def __init__(self, titulo: str) -> None:
                self._titulo = titulo

            def get_title(self) -> str:
                return self._titulo

        return [_Bundle(f"Siemens TIA Portal {self.version}")]

    def attach_portal(self, portal_mode: str | None = None) -> PortalFalso:
        return self.portal

    def open_portal(self, portal_mode: str | None = None) -> PortalFalso:
        return self.portal

    def set_logging(self, path: str, console: bool) -> None:
        pass


# ── fixture ────────────────────────────────────────────────────────────────


def _servicio(version: str) -> tuple[Any, Any, list[BloqueFalso], list[Any]]:
    """Servicio con un TIA falso de la version dada, ya conectado."""
    bloques = [BloqueFalso("DB10", "0_Sistema"), BloqueFalso("OB1_MAIN")]
    ts = TsFalso(version, PlcFalso(bloques))
    eventos: list[tuple[str, dict[str, Any]]] = []
    servicio = ServicioTIA(
        publicador=lambda tipo, carga: eventos.append((tipo, carga)),
        cargador=lambda: ts,
    )
    # Los trabajos tocaran el portal: hace falta conectar antes.
    job_id = servicio.lanzar(tia.conectar)
    _esperar_job(eventos, job_id)
    return servicio, ts, bloques, eventos


@pytest.fixture
def entorno() -> Any:
    """Servicio con un TIA V21, con eventos y limpieza."""
    servicio, ts, bloques, eventos = _servicio("V21.0")
    yield servicio, ts, bloques, eventos
    servicio.parar()


@pytest.fixture
def entorno_v18() -> Any:
    """Servicio con un TIA V18: no exporta en SimaticSD."""
    servicio, ts, bloques, eventos = _servicio("V18.0")
    yield servicio, ts, bloques, eventos
    servicio.parar()


def _esperar_job(eventos: list[tuple[str, dict[str, Any]]], job_id: str) -> dict[str, Any]:
    """Espera al evento de fin del trabajo indicado."""
    limite = time.monotonic() + 5.0
    while time.monotonic() < limite:
        for tipo, carga in list(eventos):
            if tipo == "job" and carga["job"] == job_id:
                return carga
        time.sleep(0.005)
    raise AssertionError(f"El trabajo {job_id} no termino.")


def _pasos(eventos: list[tuple[str, dict[str, Any]]]) -> list[str]:
    """Los identificadores de los pasos del ultimo trabajo."""
    for tipo, carga in reversed(eventos):
        if tipo == "progress":
            return [etapa["id"] for etapa in carga["stages"]]
    return []


# ── buscar los PLCs ────────────────────────────────────────────────────────


def test_buscar_plcs_devuelve_los_plcs_y_el_proyecto(entorno: Any) -> None:
    servicio, _ts, _bloques, eventos = entorno

    job_id = servicio.lanzar(trabajos.buscar_plcs)
    evento = _esperar_job(eventos, job_id)

    assert evento["estado"] == "ok"
    assert evento["resultado"]["plcs"] == [{"nombre": "ZC_PLC_STD", "designacion": ""}]
    assert evento["resultado"]["proyecto"]["nombre"] == "ZC_PLC_STD"


# ── escanear el PLC ────────────────────────────────────────────────────────


def test_escanear_plc_devuelve_bloques_tablas_y_tipos(entorno: Any) -> None:
    servicio, _ts, _bloques, eventos = entorno

    job_id = servicio.lanzar(trabajos.escanear_plc, plc="ZC_PLC_STD")
    evento = _esperar_job(eventos, job_id)

    assert evento["estado"] == "ok"
    assert len(evento["resultado"]["bloques"]) == 2
    assert evento["resultado"]["tablas"][0]["nombre"] == "2000_Disp_ED"
    assert evento["resultado"]["tipos"] == []


def test_escanear_plc_declara_sus_pasos(entorno: Any) -> None:
    servicio, _ts, _bloques, eventos = entorno

    job_id = servicio.lanzar(trabajos.escanear_plc, plc="ZC_PLC_STD")
    _esperar_job(eventos, job_id)

    assert _pasos(eventos) == ["bloques", "tablas", "tipos"]


# ── preparar los bloques ───────────────────────────────────────────────────


def test_preparar_en_v21_exporta_y_parsea(entorno: Any) -> None:
    servicio, _ts, bloques, eventos = entorno

    job_id = servicio.lanzar(trabajos.preparar_bloques, plc="ZC_PLC_STD", nombres=["DB10"])
    evento = _esperar_job(eventos, job_id)

    assert evento["estado"] == "ok"
    assert _pasos(eventos) == ["validar", "leer", "exportar", "parsear", "combinar"]
    assert bloques[0].exportado is True
    preparado = evento["resultado"]["bloques"][0]
    assert preparado["extended"]["title"] == "El titulo"
    assert preparado["extended"]["comment"] == "El comentario"


def test_preparar_en_v18_salta_la_exportacion(entorno_v18: Any) -> None:
    servicio, _ts, bloques, eventos = entorno_v18

    job_id = servicio.lanzar(trabajos.preparar_bloques, plc="ZC_PLC_STD", nombres=["DB10"])
    evento = _esperar_job(eventos, job_id)

    assert evento["estado"] == "ok"
    assert _pasos(eventos) == ["validar", "leer", "combinar"]
    assert bloques[0].exportado is False
    preparado = evento["resultado"]["bloques"][0]
    assert preparado["extended"]["comment"] == ""
    assert preparado["extended"]["title"] is None


def test_preparar_sin_bloques_falla(entorno: Any) -> None:
    servicio, _ts, _bloques, eventos = entorno

    job_id = servicio.lanzar(trabajos.preparar_bloques, plc="ZC_PLC_STD", nombres=[])
    evento = _esperar_job(eventos, job_id)

    assert evento["estado"] == "error"
    assert "No hay bloques seleccionados" in evento["error"]


# ── editar los bloques ─────────────────────────────────────────────────────


def test_editar_aplica_los_cambios_y_refresca(entorno: Any) -> None:
    servicio, _ts, bloques, eventos = entorno

    job_id = servicio.lanzar(
        trabajos.editar_bloques,
        plc="ZC_PLC_STD",
        cambios={"DB10": {"Name": "DB10_NUEVO"}},
    )
    evento = _esperar_job(eventos, job_id)

    assert evento["estado"] == "ok"
    assert _pasos(eventos) == [
        "validar",
        "diferencias",
        "aplicar",
        "verificar",
        "refrescar",
    ]
    assert bloques[0].get_name() == "DB10_NUEVO"
    refrescados = evento["resultado"]["bloques"]
    assert [bloque["nombre"] for bloque in refrescados] == ["DB10_NUEVO", "OB1_MAIN"]


def test_editar_sin_cambios_falla(entorno: Any) -> None:
    servicio, _ts, _bloques, eventos = entorno

    job_id = servicio.lanzar(trabajos.editar_bloques, plc="ZC_PLC_STD", cambios={})
    evento = _esperar_job(eventos, job_id)

    assert evento["estado"] == "error"
    assert "No hay cambios" in evento["error"]
