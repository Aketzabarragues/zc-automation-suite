"""Tests de las constantes de usuario del PLC."""

from __future__ import annotations

from typing import Any

import pytest

from zc_suite.tia_ops import OperacionError
from zc_suite.tia_ops import constantes as ops

# ── dobles de test ─────────────────────────────────────────────────────────


class ConstanteFalsa:
    def __init__(
        self,
        nombre: str,
        valor: Any = "0",
        codigo: int = 0,
        aplica: bool = True,
        error: Exception | None = None,
    ) -> None:
        self._nombre = nombre
        self._valor = valor
        self.codigo = codigo
        self.aplica = aplica
        self.error = error

    def get_property(self, name: str) -> Any:
        if name == "Name":
            return self._nombre
        if name == "Value":
            return self._valor
        return None

    def set_property(self, name: str, value: str) -> int:
        if self.error is not None:
            raise self.error
        if self.aplica:
            if name == "Name":
                self._nombre = value
            else:
                self._valor = value
        return self.codigo


class TablaFalsa:
    def __init__(self, constantes: list[ConstanteFalsa] | None = None) -> None:
        self.constantes = constantes or []

    def get_name(self) -> str:
        return "0_Config_Dispositivos"

    def get_user_constants(self) -> list[ConstanteFalsa]:
        return self.constantes


class PlcFalso:
    def __init__(self, tablas: list[TablaFalsa] | None = None) -> None:
        self.tablas = tablas or []

    def get_name(self) -> str:
        return "PLC_1"

    def get_plc_tag_tables(self) -> list[TablaFalsa]:
        return self.tablas


class ProyectoFalso:
    def __init__(self, plc: PlcFalso) -> None:
        self.plc = plc

    def get_plcs(self) -> list[PlcFalso]:
        return [self.plc]


class PortalFalso:
    def __init__(self, plc: PlcFalso | None = None) -> None:
        self.proyecto = ProyectoFalso(plc) if plc is not None else None

    def get_project(self) -> ProyectoFalso | None:
        return self.proyecto


def _portal(constantes: list[ConstanteFalsa] | None = None) -> tuple[PortalFalso, TablaFalsa]:
    tabla = TablaFalsa(constantes)
    plc = PlcFalso([tabla])
    return PortalFalso(plc), tabla


# ── leer ───────────────────────────────────────────────────────────────────


def test_leer_constantes_devuelve_nombre_y_valor() -> None:
    portal, _tabla = _portal(
        [ConstanteFalsa("N_MAX_DISP_ED", "5"), ConstanteFalsa("N_MAX_DISP_EA", "7")]
    )

    resultado = ops.leer_constantes(portal, "PLC_1", "0_Config_Dispositivos")

    assert resultado == [
        {"nombre": "N_MAX_DISP_ED", "valor": "5"},
        {"nombre": "N_MAX_DISP_EA", "valor": "7"},
    ]


def test_leer_constantes_de_una_tabla_vacia() -> None:
    portal, _tabla = _portal([])

    assert ops.leer_constantes(portal, "PLC_1", "0_Config_Dispositivos") == []


def test_leer_constantes_devuelve_el_valor_tal_cual() -> None:
    """El nucleo no filtra valores: eso es cosa de quien llama."""
    portal, _tabla = _portal([ConstanteFalsa("UNA", "texto")])

    resultado = ops.leer_constantes(portal, "PLC_1", "0_Config_Dispositivos")

    assert resultado[0]["valor"] == "texto"


def test_leer_constantes_falla_si_el_plc_no_existe() -> None:
    portal, _tabla = _portal()

    with pytest.raises(OperacionError, match="No se encontro ningun PLC"):
        ops.leer_constantes(portal, "PLC_9", "0_Config_Dispositivos")


def test_leer_constantes_falla_si_la_tabla_no_existe() -> None:
    portal, _tabla = _portal()

    with pytest.raises(OperacionError, match="no encontrada en el PLC"):
        ops.leer_constantes(portal, "PLC_1", "NO_EXISTE")


# ── cambiar el valor ───────────────────────────────────────────────────────


def test_cambiar_valor_cambia_el_valor() -> None:
    constante = ConstanteFalsa("N_MAX_DISP_ED", "5")
    portal, _tabla = _portal([constante])

    resultado = ops.cambiar_valor(portal, "PLC_1", "0_Config_Dispositivos", "N_MAX_DISP_ED", 9)

    assert resultado == {"nombre": "N_MAX_DISP_ED", "valor": 9}
    assert constante.get_property(name="Value") == "9"


def test_cambiar_valor_falla_si_la_constante_no_existe() -> None:
    portal, _tabla = _portal([ConstanteFalsa("OTRA", "1")])

    with pytest.raises(OperacionError, match="Constante 'N_MAX_DISP_ED' no encontrada"):
        ops.cambiar_valor(portal, "PLC_1", "0_Config_Dispositivos", "N_MAX_DISP_ED", 9)


def test_cambiar_valor_falla_si_tia_rechaza() -> None:
    constante = ConstanteFalsa("N_MAX_DISP_ED", "5", codigo=1)
    portal, _tabla = _portal([constante])

    with pytest.raises(OperacionError, match="TIA rechazo la modificacion"):
        ops.cambiar_valor(portal, "PLC_1", "0_Config_Dispositivos", "N_MAX_DISP_ED", 9)


def test_cambiar_valor_detecta_el_fallo_silencioso() -> None:
    """set_property devuelve 0 pero el valor no cambia: hay que avisar."""
    constante = ConstanteFalsa("N_MAX_DISP_ED", "5", aplica=False)
    portal, _tabla = _portal([constante])

    with pytest.raises(OperacionError, match="set_property devolvio 0"):
        ops.cambiar_valor(portal, "PLC_1", "0_Config_Dispositivos", "N_MAX_DISP_ED", 9)


# ── renombrar ──────────────────────────────────────────────────────────────


def test_renombrar_cambia_el_nombre() -> None:
    constante = ConstanteFalsa("VIEJO", "5")
    portal, _tabla = _portal([constante])

    resultado = ops.renombrar(portal, "PLC_1", "0_Config_Dispositivos", "VIEJO", "NUEVO")

    assert resultado == {"nombre": "VIEJO", "nuevo_nombre": "NUEVO"}
    assert constante.get_property(name="Name") == "NUEVO"


def test_renombrar_falla_si_la_constante_no_existe() -> None:
    portal, _tabla = _portal([ConstanteFalsa("OTRA", "1")])

    with pytest.raises(OperacionError, match="no encontrada en la tabla"):
        ops.renombrar(portal, "PLC_1", "0_Config_Dispositivos", "VIEJO", "NUEVO")


def test_renombrar_falla_si_tia_rechaza() -> None:
    constante = ConstanteFalsa("VIEJO", "5", codigo=2)
    portal, _tabla = _portal([constante])

    with pytest.raises(OperacionError, match="TIA rechazo la modificacion"):
        ops.renombrar(portal, "PLC_1", "0_Config_Dispositivos", "VIEJO", "NUEVO")


def test_renombrar_detecta_el_fallo_silencioso() -> None:
    constante = ConstanteFalsa("VIEJO", "5", aplica=False)
    portal, _tabla = _portal([constante])

    with pytest.raises(OperacionError, match="set_property devolvio 0"):
        ops.renombrar(portal, "PLC_1", "0_Config_Dispositivos", "VIEJO", "NUEVO")


def test_lo_publico_devuelve_solo_primitivos() -> None:
    portal, _tabla = _portal([ConstanteFalsa("UNA", "1")])

    resultado = ops.leer_constantes(portal, "PLC_1", "0_Config_Dispositivos")

    assert isinstance(resultado, list)
    assert all(isinstance(c, dict) for c in resultado)
    assert all(isinstance(v, str) for c in resultado for v in c.values())


def test_los_mensajes_hablan_de_constantes_y_tablas() -> None:
    """El mensaje nombra la constante y la tabla, en idioma de TIA."""
    portal, _tabla = _portal([ConstanteFalsa("OTRA", "1")])

    with pytest.raises(OperacionError) as fallo:
        ops.cambiar_valor(portal, "PLC_1", "0_Config_Dispositivos", "N_MAX_DISP_ED", 9)

    error = str(fallo.value)
    assert "Constante 'N_MAX_DISP_ED'" in error
    assert "tabla '0_Config_Dispositivos'" in error
