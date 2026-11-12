"""La prevision de dispositivos de extremo a extremo.

El recorrido completo: un Excel maestro -> el parser -> el almacen -> el
trabajo que exporta del PLC y calcula el diff. Ni el almacen ni el parser
estan mockeados: lo unico falso es el portal de TIA, que exporta las
tablas de tags con el contenido del fixture.

El fixture tiene un alta, una baja y un renombrado, mas dos dispositivos que
no cambian: los cuatro casos del diff.
"""
from __future__ import annotations

from typing import Any


def _filas(resultado: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Las filas del diff, indexadas por numero."""
    return {fila["numero"]: fila for fila in resultado["todos"]}


def test_el_diff_sale_de_altas_bajas_y_renombrados(entorno_disp: Any) -> None:
    """El Excel contra el PLC da un alta, una baja y un renombrado."""
    resultado = entorno_disp.prevision()

    assert resultado["summary"] == {
        "agregados": 1,
        "eliminados": 1,
        "renombrados": 1,
        "sin_cambios": 2,
        "total": 5,
    }


def test_el_dispositivo_que_no_cambia_no_aparece_como_cambio(entorno_disp: Any) -> None:
    """El numero 3 esta igual en el Excel y en TIA."""
    resultado = entorno_disp.prevision()

    filas = _filas(resultado)
    assert filas[3]["status"] == "sin_cambios"
    assert filas[3]["actual"] == "ED_003"
    assert filas[3]["nuevo"] == "ED_003"


def test_el_alta_es_el_numero_que_no_esta_en_tia(entorno_disp: Any) -> None:
    """El numero 4 esta en el Excel y no en TIA."""
    resultado = entorno_disp.prevision()

    filas = _filas(resultado)
    assert filas[4]["status"] == "agregar"
    assert filas[4]["actual"] is None
    assert filas[4]["nuevo"] == "ED_004"


def test_la_baja_es_el_numero_que_solo_esta_en_tia(entorno_disp: Any) -> None:
    """El numero 99 esta en TIA y no en el Excel."""
    resultado = entorno_disp.prevision()

    filas = _filas(resultado)
    assert filas[99]["status"] == "eliminar"
    assert filas[99]["actual"] == "ED_099"
    assert filas[99]["nuevo"] is None


def test_el_renombrado_es_el_mismo_numero_con_otro_tag(entorno_disp: Any) -> None:
    """El numero 2 tiene otro ``plc_tag`` en el Excel."""
    resultado = entorno_disp.prevision()

    filas = _filas(resultado)
    assert filas[2]["status"] == "renombrar"
    assert filas[2]["actual"] == "ED_002"
    assert filas[2]["nuevo"] == "ED_002_NUEVO"


def test_el_tipo_de_la_fila_es_la_clave_del_config(entorno_disp: Any) -> None:
    """El tipo es la clave del ``config.json`` (``"ed"``), no el canonico."""
    resultado = entorno_disp.prevision()

    assert {fila["type"] for fila in resultado["todos"]} == {"ed"}
    assert {fila["table"] for fila in resultado["todos"]} == {"2000_Disp_ED"}


def test_las_filas_salen_ordenadas_por_tipo_y_numero(entorno_disp: Any) -> None:
    """Las filas de la vista unificada van ordenadas por tipo y numero."""
    resultado = entorno_disp.prevision()

    assert [fila["numero"] for fila in resultado["todos"]] == [1, 2, 3, 4, 99]


def test_los_n_max_solo_los_de_dispositivos(entorno_disp: Any) -> None:
    """El bloque de N_MAX no incluye el de las entidades."""
    resultado = entorno_disp.prevision()

    assert "N_MAX_ENTIDAD" not in resultado["nmax"]["desired"]
    assert len(resultado["nmax"]["desired"]) == 12
    assert resultado["nmax"]["summary"] == {
        "actualizar": 9,
        "sin_cambios": 3,
        "total": 12,
    }


def test_los_n_max_salen_en_el_orden_del_catalogo(entorno_disp: Any) -> None:
    """Las tarjetas de N_MAX van en el orden del catalogo, no del Excel."""
    resultado = entorno_disp.prevision()

    assert [fila["name"] for fila in resultado["nmax"]["todos"]] == [
        "N_MAX_DISP_EA",
        "N_MAX_DISP_ED",
        "N_MAX_DISP_M",
        "N_MAX_DISP_M_SINA",
        "N_MAX_DISP_M_VF",
        "N_MAX_DISP_PID",
        "N_MAX_DISP_SA",
        "N_MAX_DISP_SD",
        "N_MAX_DISP_TOT",
        "N_MAX_DISP_TQ",
        "N_MAX_DISP_TQ_AE",
        "N_MAX_DISP_V",
    ]


def test_la_prevision_no_avisa_de_nada(entorno_disp: Any) -> None:
    """La prevision solo exporta: no escribe nada y no deja avisos."""
    resultado = entorno_disp.prevision()

    assert resultado["nmax"]["nmax_error"] is None
    assert resultado["summary"]["agregados"] == 1


def test_avisa_de_las_tablas_que_no_estan_en_tia(entorno_disp: Any) -> None:
    """Cada tabla que no existe en TIA se avisa: si no, el diff engaña."""
    entorno_disp.prevision()

    avisos = [
        carga["mensaje"]
        for tipo, carga in entorno_disp.eventos
        if tipo == "log" and carga.get("nivel") == "warning"
    ]

    assert any("no existe en TIA" in aviso for aviso in avisos)
    assert any("2000_Disp_EA" in aviso for aviso in avisos)


def test_avisa_si_no_hay_tablas_que_exportar(entorno_disp: Any) -> None:
    """Sin tipos de dispositivo en el catalogo, el trabajo avisa."""
    entorno_disp.modelo.dispositivos = {}

    entorno_disp.prevision()

    avisos = [
        carga["mensaje"]
        for tipo, carga in entorno_disp.eventos
        if tipo == "log" and carga.get("nivel") == "warning"
    ]

    assert any("No hay tablas de dispositivos que exportar" in aviso for aviso in avisos)


def test_la_prevision_queda_en_la_sesion(entorno_disp: Any) -> None:
    """Como ``preview_disp`` en main: la prevision sobrevive a un F5."""
    from zc_suite.areas.alimentacion.dispositivos import CLAVE_PREVISION
    from zc_suite.nucleo.sesion import Sesion

    sesion = Sesion()
    resultado = entorno_disp.prevision(sesion=sesion)

    guardada = sesion.datos_area("alimentacion")[CLAVE_PREVISION]
    assert guardada["plc"] == "ZC_PLC_STD"
    assert guardada["resultado"] == resultado
