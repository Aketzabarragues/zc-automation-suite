"""Tests de la compilacion del software del PLC."""

from __future__ import annotations

from typing import Any

import pytest

from zc_suite.errores import OperacionError
from zc_suite.tia_ops import compilar as ops

# ── dobles de test ─────────────────────────────────────────────────────────


class BloqueFalso:
    def __init__(
        self,
        nombre: str | None,
        consistente: bool = True,
        error_compilar: Exception | None = None,
        error_consistente: Exception | None = None,
        tiene_errores: bool = False,
    ) -> None:
        self._nombre = nombre
        self.consistente = consistente
        self.error_compilar = error_compilar
        self.error_consistente = error_consistente
        self.tiene_errores = tiene_errores
        self.compilado = False

    def get_name(self) -> str | None:
        return self._nombre

    def is_consistent(self) -> bool:
        if self.error_consistente is not None:
            raise self.error_consistente
        return self.consistente

    def compile(self) -> bool:
        if self.error_compilar is not None:
            raise self.error_compilar
        self.compilado = True
        return self.tiene_errores


class PlcFalso:
    def __init__(
        self,
        bloques: list[BloqueFalso] | None = None,
        error_software: Exception | None = None,
        tiene_errores: bool = False,
    ) -> None:
        self.bloques = bloques or []
        self.error_software = error_software
        self.tiene_errores = tiene_errores
        self.compilado = False

    def get_name(self) -> str:
        return "PLC_1"

    def get_program_blocks(self) -> list[BloqueFalso]:
        return self.bloques

    def compile_software(self) -> bool:
        if self.error_software is not None:
            raise self.error_software
        self.compilado = True
        return self.tiene_errores


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


def _portal(
    bloques: list[BloqueFalso] | None = None,
    **kwargs: Any,
) -> tuple[PortalFalso, PlcFalso]:
    plc = PlcFalso(bloques, **kwargs)
    return PortalFalso(plc), plc


# ── compilar todo el PLC ───────────────────────────────────────────────────


def test_compilar_plc_devuelve_si_hay_errores() -> None:
    portal, plc = _portal()

    resultado = ops.compilar_plc(portal, "PLC_1")

    assert resultado == {"tiene_errores": False}
    assert plc.compilado is True


def test_compilar_plc_informa_de_los_errores() -> None:
    portal, _plc = _portal(tiene_errores=True)

    resultado = ops.compilar_plc(portal, "PLC_1")

    assert resultado["tiene_errores"] is True


def test_compilar_plc_falla_si_el_plc_no_existe() -> None:
    portal, _plc = _portal()

    with pytest.raises(OperacionError, match="No se encontro ningun PLC"):
        ops.compilar_plc(portal, "PLC_9")


def test_compilar_plc_falla_si_tia_rechaza() -> None:
    portal, _plc = _portal(error_software=RuntimeError("TIA dice que no"))

    with pytest.raises(OperacionError, match="No se pudo compilar el software"):
        ops.compilar_plc(portal, "PLC_1")


# ── compilar bloques ───────────────────────────────────────────────────────


def test_compilar_bloques_compila_los_inconsistentes() -> None:
    bloque = BloqueFalso("DB2000_ED", consistente=False)
    portal, _plc = _portal([bloque])

    resultado = ops.compilar_bloques(portal, "PLC_1", ["DB2000_ED"])

    assert bloque.compilado is True
    assert resultado["n_compilados_ok"] == 1
    assert resultado["compilados"][0]["nombre"] == "DB2000_ED"


def test_compilar_bloques_salta_los_consistentes() -> None:
    bloque = BloqueFalso("DB2000_ED", consistente=True)
    portal, _plc = _portal([bloque])

    resultado = ops.compilar_bloques(portal, "PLC_1", ["DB2000_ED"])

    assert bloque.compilado is False
    assert resultado["n_sin_cambios"] == 1
    assert resultado["sin_cambios"] == ["DB2000_ED"]


def test_compilar_bloques_anota_los_no_encontrados() -> None:
    portal, _plc = _portal([BloqueFalso("DB2000_ED", consistente=False)])

    resultado = ops.compilar_bloques(portal, "PLC_1", ["NO_EXISTE"])

    assert resultado["no_encontrados"] == ["NO_EXISTE"]
    assert resultado["n_no_encontrados"] == 1


def test_compilar_bloques_anota_los_errores_sin_parar() -> None:
    portal, _plc = _portal(
        [
            BloqueFalso("A", consistente=False, error_compilar=RuntimeError("reventon")),
            BloqueFalso("B", consistente=False),
        ]
    )

    resultado = ops.compilar_bloques(portal, "PLC_1", ["A", "B"])

    assert resultado["n_errores"] == 1
    assert resultado["errores"][0]["nombre"] == "A"
    assert "reventon" in resultado["errores"][0]["error"]
    # El segundo bloque se compila igualmente.
    assert resultado["n_compilados_ok"] == 1


def test_compilar_bloques_compila_si_is_consistent_falla() -> None:
    bloque = BloqueFalso(
        "DB2000_ED", error_consistente=RuntimeError("no se puede saber")
    )
    portal, _plc = _portal([bloque])

    resultado = ops.compilar_bloques(portal, "PLC_1", ["DB2000_ED"])

    assert bloque.compilado is True
    assert resultado["n_compilados_ok"] == 1


def test_compilar_bloques_cuenta_los_errores_de_compilacion() -> None:
    bloque = BloqueFalso("DB2000_ED", consistente=False, tiene_errores=True)
    portal, _plc = _portal([bloque])

    resultado = ops.compilar_bloques(portal, "PLC_1", ["DB2000_ED"])

    assert resultado["n_compilados_ok"] == 0
    assert resultado["n_compilados_error"] == 1
    assert resultado["compilados"][0]["tiene_errores"] is True


def test_compilar_bloques_exige_una_lista() -> None:
    portal, _plc = _portal()

    with pytest.raises(OperacionError, match="lista de bloques"):
        ops.compilar_bloques(portal, "PLC_1", [])


def test_compilar_bloques_falla_si_el_plc_no_existe() -> None:
    portal, _plc = _portal()

    with pytest.raises(OperacionError, match="No se encontro ningun PLC"):
        ops.compilar_bloques(portal, "PLC_9", ["DB2000_ED"])


def test_lo_publico_devuelve_solo_primitivos() -> None:
    portal, _plc = _portal([BloqueFalso("DB2000_ED", consistente=False)])

    resultado = ops.compilar_bloques(portal, "PLC_1", ["DB2000_ED"])

    assert isinstance(resultado, dict)
    assert isinstance(resultado["compilados"], list)
    assert isinstance(resultado["n_compilados_ok"], int)
    assert all(
        isinstance(c, (str, int, bool))
        for c in resultado.values()
        if not isinstance(c, list)
    )
