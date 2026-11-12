"""Tests del estado de la sesion."""

from __future__ import annotations

from datetime import datetime, timedelta

from zc_suite.nucleo.sesion import TTL_ESCANEO, Escaneo, Sesion


def _sesion() -> Sesion:
    """Una sesion nueva, vacia."""
    return Sesion()


def test_la_sesion_empieza_vacia() -> None:
    """Nada sobrevive de una sesion anterior."""
    sesion = _sesion()

    estado = sesion.estado()

    assert estado["plcs"] == []
    assert estado["proyecto"] is None
    assert estado["plc_seleccionado"] == ""
    assert estado["escaneo"] is None


def test_guardar_los_plcs_y_el_proyecto() -> None:
    """La lista de PLCs y el proyecto abierto quedan en la sesion."""
    sesion = _sesion()

    sesion.guardar_plcs(
        [{"nombre": "ZC_PLC_STD"}],
        {"nombre": "Alimentacion", "ruta": "D:\\proyectos\\Alimentacion.ap21"},
    )

    assert sesion.plcs == [{"nombre": "ZC_PLC_STD"}]
    assert sesion.proyecto is not None
    assert sesion.proyecto["nombre"] == "Alimentacion"


def test_seleccionar_un_plc_lo_guarda() -> None:
    """La seleccion vive en el servidor."""
    sesion = _sesion()

    sesion.seleccionar("ZC_PLC_STD")

    assert sesion.seleccionado == "ZC_PLC_STD"
    assert sesion.estado()["plc_seleccionado"] == "ZC_PLC_STD"


def test_guardar_un_escaneo_lo_deja_disponible() -> None:
    """El escaneo guarda bloques, tablas y tipos."""
    sesion = _sesion()

    sesion.guardar_escaneo(
        "ZC_PLC_STD",
        [{"nombre": "DB2000_ED"}],
        [{"nombre": "2000_Disp_ED"}],
        [{"nombre": "UDT_ZC"}],
    )

    escaneo = sesion.escaneo("ZC_PLC_STD")
    assert escaneo is not None
    assert escaneo.bloques == [{"nombre": "DB2000_ED"}]
    assert escaneo.tablas == [{"nombre": "2000_Disp_ED"}]
    assert escaneo.tipos == [{"nombre": "UDT_ZC"}]


def test_un_escaneo_fresco_sirve() -> None:
    """Un escaneo de hace nada sigue valiendo."""
    sesion = _sesion()
    sesion.guardar_escaneo("ZC_PLC_STD", [], [], [])

    assert sesion.escaneo_fresco("ZC_PLC_STD") is not None
    assert sesion.escaneo("ZC_PLC_STD") is not None


def test_un_escaneo_caducado_no_sirve() -> None:
    """Pasado el TTL, el escaneo hay que rehacerlo."""
    sesion = _sesion()
    sesion.guardar_escaneo("ZC_PLC_STD", [], [], [])
    escaneo = sesion.escaneo("ZC_PLC_STD")
    assert escaneo is not None
    escaneo.momento = datetime.now() - timedelta(seconds=TTL_ESCANEO + 1)

    assert escaneo.caducado() is True
    assert sesion.escaneo_fresco("ZC_PLC_STD") is None
    # El escaneo sigue ahi: caducado no es lo mismo que borrado.
    assert sesion.escaneo("ZC_PLC_STD") is not None


def test_el_estado_marca_el_escaneo_caducado() -> None:
    """La SPA sabe si lo que ve esta al dia."""
    sesion = _sesion()
    sesion.seleccionar("ZC_PLC_STD")
    sesion.guardar_escaneo("ZC_PLC_STD", [], [], [])
    escaneo = sesion.escaneo("ZC_PLC_STD")
    assert escaneo is not None
    escaneo.momento = datetime.now() - timedelta(seconds=TTL_ESCANEO + 1)

    estado = sesion.estado()

    assert estado["escaneo"] is not None
    assert estado["escaneo"]["caducado"] is True
    assert estado["escaneo"]["plc"] == "ZC_PLC_STD"


def test_invalidar_los_escaneos_los_borra() -> None:
    """Al desconectar de TIA los escaneos dejan de servir."""
    sesion = _sesion()
    sesion.seleccionar("ZC_PLC_STD")
    sesion.guardar_escaneo("ZC_PLC_STD", [], [], [])

    sesion.invalidar_escaneos()

    assert sesion.escaneo("ZC_PLC_STD") is None
    assert sesion.escaneo_fresco("ZC_PLC_STD") is None
    # La seleccion y la lista de PLCs no se tocan: siguen siendo validas.
    assert sesion.seleccionado == "ZC_PLC_STD"


def test_vaciar_deja_la_sesion_en_blanco() -> None:
    """Reiniciar la app vacia la sesion entera."""
    sesion = _sesion()
    sesion.guardar_plcs([{"nombre": "ZC_PLC_STD"}], {"nombre": "Alimentacion"})
    sesion.seleccionar("ZC_PLC_STD")
    sesion.guardar_escaneo("ZC_PLC_STD", [], [], [])

    sesion.vaciar()

    estado = sesion.estado()
    assert estado["plcs"] == []
    assert estado["proyecto"] is None
    assert estado["plc_seleccionado"] == ""
    assert estado["escaneo"] is None


def test_el_escaneo_parte_de_listas_vacias() -> None:
    """Un escaneo sin datos no rompe nada."""
    escaneo = Escaneo(plc="ZC_PLC_STD")

    assert escaneo.bloques == []
    assert escaneo.caducado() is False
    assert escaneo.estado()["plc"] == "ZC_PLC_STD"
