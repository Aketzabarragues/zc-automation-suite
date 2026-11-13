"""Tests de la compilacion del software del PLC."""

from __future__ import annotations

from typing import Any

import pytest

from zc_suite.errores import OperacionError
from zc_suite.tia_ops import compilar as ops

# ── dobles de test ─────────────────────────────────────────────────────────


class ResultadoFalso:
    """El ``ExecutionResult`` del SDK, como lo devuelve TIA V18/V21.

    Los mensajes son los de una prueba real contra TIA (DB_NO_OK).
    """

    def __init__(self, nombre: str = "DB_X", tiene_errores: bool = False) -> None:
        if tiene_errores:
            self._errores = [
                f"PLC_1 > Program blocks > {nombre} (DB5) > Interface > "
                "Data type Boo is unknown.",
                "Compiling finished (errors: 1; warnings: 0)",
            ]
            self._informacion: list[str] = []
            self._estado = 20
        else:
            self._errores = []
            self._informacion = [
                f"PLC_1 > Program blocks > {nombre} (DB2) > Block was successfully compiled."
            ]
            self._estado = 0
        self._resumen = (
            "Compiling finished (errors: 1; warnings: 0)"
            if tiene_errores
            else "Compiling finished (errors: 0; warnings: 0)"
        )

    def get_result_state(self) -> int:
        return self._estado

    def get_errors(self) -> list[str]:
        return list(self._errores)

    def get_warnings(self) -> list[str]:
        return []

    def get_information(self) -> list[str]:
        return list(self._informacion)

    def get_all_messages(self) -> list[str]:
        mensajes = [m for m in self._errores if not m.startswith("Compiling")]
        return mensajes + self._informacion + [self._resumen]


class BloqueFalso:
    def __init__(
        self,
        nombre: str | None,
        consistente: bool = True,
        error_compilar: Exception | None = None,
        error_consistente: Exception | None = None,
        tiene_errores: bool = False,
        devuelve: Any = None,
    ) -> None:
        self._nombre = nombre
        self.consistente = consistente
        self.error_compilar = error_compilar
        self.error_consistente = error_consistente
        self.tiene_errores = tiene_errores
        # None: devuelve un ExecutionResult como TIA. Otro valor: se devuelve
        # tal cual (para probar SDKs que devolvieran otra cosa).
        self.devuelve = devuelve
        self.compilado = False

    def get_name(self) -> str | None:
        return self._nombre

    def is_consistent(self) -> bool:
        if self.error_consistente is not None:
            raise self.error_consistente
        return self.consistente

    def compile(self) -> Any:
        if self.error_compilar is not None:
            raise self.error_compilar
        self.compilado = True
        # Como en TIA: compilado sin errores deja el bloque consistente.
        self.consistente = not self.tiene_errores
        if self.error_consistente is not None and self.consistente:
            self.error_consistente = None
        if self.devuelve is not None:
            return self.devuelve
        return ResultadoFalso(self._nombre or "DB_X", self.tiene_errores)


class PlcFalso:
    def __init__(
        self,
        bloques: list[BloqueFalso] | None = None,
        error_software: Exception | None = None,
        tiene_errores: bool = False,
        devuelve: Any = None,
    ) -> None:
        self.bloques = bloques or []
        self.error_software = error_software
        self.tiene_errores = tiene_errores
        self.devuelve = devuelve
        self.compilado = False

    def get_name(self) -> str:
        return "PLC_1"

    def get_program_blocks(self) -> list[BloqueFalso]:
        return self.bloques

    def compile_software(self) -> Any:
        if self.error_software is not None:
            raise self.error_software
        self.compilado = True
        if self.devuelve is not None:
            return self.devuelve
        return ResultadoFalso("PLC_1", self.tiene_errores)


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

    assert resultado["tiene_errores"] is False
    assert resultado["errores"] == []
    assert resultado["resumen"] == "Compiling finished (errors: 0; warnings: 0)"
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
    """Un bloque que sigue inconsistente tras compilar tiene errores."""
    bloque = BloqueFalso("DB2000_ED", consistente=False, tiene_errores=True)
    portal, _plc = _portal([bloque])

    resultado = ops.compilar_bloques(portal, "PLC_1", ["DB2000_ED"])

    assert resultado["n_compilados_ok"] == 0
    assert resultado["n_compilados_error"] == 1
    assert resultado["compilados"][0]["tiene_errores"] is True
    assert resultado["con_errores"] == ["DB2000_ED"]


def test_un_execution_result_sin_errores_no_es_un_error() -> None:
    """Caso real: compile() devuelve un objeto (siempre verdadero). main hacia
    bool() y contaba como error todo lo que compilaba."""
    bloque = BloqueFalso("DB_OK", consistente=False)
    portal, _plc = _portal([bloque])

    resultado = ops.compilar_bloques(portal, "PLC_1", ["DB_OK"])

    assert resultado["n_compilados_ok"] == 1
    assert resultado["n_compilados_error"] == 0
    assert resultado["con_errores"] == []
    assert resultado["compilados"][0]["mensajes"] == []


def test_los_errores_traen_el_mensaje_de_tia_sin_el_resumen() -> None:
    bloque = BloqueFalso("DB_NO_OK", consistente=False, tiene_errores=True)
    portal, _plc = _portal([bloque])

    resultado = ops.compilar_bloques(portal, "PLC_1", ["DB_NO_OK"])

    assert resultado["con_errores"] == ["DB_NO_OK"]
    assert resultado["compilados"][0]["mensajes"] == [
        "PLC_1 > Program blocks > DB_NO_OK (DB5) > Interface > Data type Boo is unknown."
    ]


def test_un_bloque_que_sigue_inconsistente_es_un_error_aunque_no_haya_mensajes() -> None:
    """Respaldo: si el SDK no diera mensajes, manda is_consistent()."""
    bloque = BloqueFalso("DB_X", consistente=False, tiene_errores=True, devuelve=object())
    portal, _plc = _portal([bloque])

    resultado = ops.compilar_bloques(portal, "PLC_1", ["DB_X"])

    assert resultado["con_errores"] == ["DB_X"]
    assert resultado["compilados"][0]["mensajes"] == []


def test_un_booleano_de_compile_en_un_bloque_se_ignora() -> None:
    """Si un SDK devolviera un booleano en un bloque, no se interpreta."""
    bloque = BloqueFalso("DB_X", consistente=False, devuelve=True)
    portal, _plc = _portal([bloque])

    resultado = ops.compilar_bloques(portal, "PLC_1", ["DB_X"])

    assert resultado["con_errores"] == []


def test_compilar_plc_con_un_booleano_usa_el_manual() -> None:
    """SDK antiguo: compile_software() devuelve True si hay errores (§2.2.11)."""
    portal, _plc = _portal(devuelve=True)

    assert ops.compilar_plc(portal, "PLC_1")["tiene_errores"] is True


def test_compilar_plc_trae_los_mensajes_de_tia() -> None:
    portal, _plc = _portal(tiene_errores=True)

    resultado = ops.compilar_plc(portal, "PLC_1")

    assert resultado["tiene_errores"] is True
    assert resultado["errores"] == [
        "PLC_1 > Program blocks > PLC_1 (DB5) > Interface > Data type Boo is unknown."
    ]
    assert resultado["resumen"] == "Compiling finished (errors: 1; warnings: 0)"


def test_leer_resultado_de_algo_que_no_es_un_execution_result() -> None:
    leido = ops.leer_resultado(None)

    assert leido == {"estado": None, "errores": [], "avisos": [], "resumen": ""}


def test_las_excepciones_no_se_cuentan_dos_veces() -> None:
    """Un bloque que revienta al compilar va en errores, no en n_compilados_error."""
    portal, _plc = _portal(
        [BloqueFalso("A", consistente=False, error_compilar=RuntimeError("reventon"))]
    )

    resultado = ops.compilar_bloques(portal, "PLC_1", ["A"])

    assert resultado["n_errores"] == 1
    assert resultado["n_compilados_error"] == 0


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
