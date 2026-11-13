"""La prevision de las entidades.

Exporta del PLC las dos tablas y el DB, y los compara con el Excel. No
escribe nada en TIA.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from zc_suite.areas.alimentacion.funciones.entidades.generar_prevision import (
    generar_prevision,
)
from zc_suite.nucleo.sesion import Sesion


def _lanzar(entorno: Any, sesion: Sesion | None = None) -> dict[str, Any]:
    """Lanza la prevision y devuelve el evento de fin del trabajo."""
    job_id = entorno.servicio.lanzar(
        generar_prevision,
        plc="ZC_PLC_STD",
        almacen=entorno.almacen,
        config=entorno.modelo,
        sesion=sesion,
    )
    return entorno._esperar(job_id)


def test_la_prevision_exporta_las_tablas_y_el_db(
    entorno_sync: Any,
    tmp_path: Path,
) -> None:
    """El preview deja las dos tablas y el DB exportados."""
    evento = _lanzar(entorno_sync)

    assert evento["estado"] == "ok", evento.get("error")
    preview = tmp_path / "entidades" / "preview"
    assert (preview / "disp" / "0_Config_Generales.xml").is_file()
    assert (preview / "disp" / "6_Entidades.xml").is_file()
    assert (preview / "bloques" / "DB6_ENT.s7dcl").is_file()
    assert (preview / "bloques" / "DB6_ENT.s7res").is_file()


def test_la_prevision_devuelve_el_diff_de_las_entidades(entorno_sync: Any) -> None:
    """La prevision trae el shape que consume la SPA."""
    evento = _lanzar(entorno_sync)

    assert evento["estado"] == "ok", evento.get("error")
    resultado = evento["resultado"]
    assert resultado["precondiciones_ok"] is True
    assert resultado["db_name"] == "DB6_ENT"
    assert resultado["db_array_name"] == "ENT"
    assert resultado["tag_table"] == "6_Entidades"
    assert resultado["config_table"] == "0_Config_Generales"
    assert resultado["table_present"] is True
    assert resultado["db_present"] is True


def test_la_prevision_detecta_las_altas_y_las_bajas(entorno_sync: Any) -> None:
    """Las operaciones del diff: un alta, una baja y un renombre."""
    evento = _lanzar(entorno_sync)

    operaciones = evento["resultado"]["ops"]
    kinds = [operacion["kind"] for operacion in operaciones]
    assert "delete" in kinds
    assert "rename" in kinds
    assert "add" in kinds


def test_la_prevision_detecta_el_n_max(entorno_sync: Any) -> None:
    """El N_MAX de las entidades sale del Excel contra el de TIA."""
    evento = _lanzar(entorno_sync)

    n_max = evento["resultado"]["nmax"]
    assert n_max["current"] == {"N_MAX_ENTIDAD": 3}
    assert n_max["desired"] == {"N_MAX_ENTIDAD": 6}
    assert n_max["summary"]["actualizar"] == 1


def test_la_prevision_avisa_de_los_plc_tags_no_canonicos(entorno_sync: Any) -> None:
    """Una constante de TIA que no es ``ENT_<X>`` es un aviso."""
    evento = _lanzar(entorno_sync)

    avisos = evento["resultado"]["warnings"]
    assert any("ENT_099" in aviso for aviso in avisos)


def test_la_prevision_se_guarda_en_la_sesion(entorno_sync: Any) -> None:
    """La prevision sobrevive a un F5: se guarda en la sesion del backend."""
    sesion = Sesion()

    evento = _lanzar(entorno_sync, sesion)

    assert evento["estado"] == "ok", evento.get("error")
    guardado = sesion.datos_area("alimentacion").get("prevision_entidades")
    assert guardado is not None
    assert guardado["plc"] == "ZC_PLC_STD"
