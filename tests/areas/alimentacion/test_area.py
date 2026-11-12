"""Tests del contrato del area de alimentacion.

El area no guarda nada en disco: al arrancar deja el almacen en blanco y
solo expone lo que hay en la sesion.
"""

from __future__ import annotations

from typing import Any

from zc_suite.areas import alimentacion


def test_al_arrancar_deja_el_excel_en_blanco() -> None:
    """Cada sesion de la app empieza sin Excel."""
    almacen = alimentacion.ALMACEN
    almacen._datos = {"plcs": [{"plc": "PLC1", "uid": 1}]}
    almacen._archivo = "maestro.xlsm"

    alimentacion.al_arrancar({})

    assert almacen.cargado is False
    assert almacen.archivo is None


def test_al_arrancar_no_parsea_ningun_excel(monkeypatch: Any) -> None:
    """Al arrancar no se lee ningun Excel: no hay copia que recargar."""
    leidos: list[Any] = []

    def espia(*args: Any, **kwargs: Any) -> dict[str, Any]:
        leidos.append(args)
        return {}

    monkeypatch.setattr(
        "zc_suite.areas.alimentacion.excel.parser.leer_excel",
        espia,
    )

    alimentacion.al_arrancar({})

    assert leidos == []


def test_el_estado_de_la_sesion_devuelve_el_excel() -> None:
    """Lo que el area tiene en la sesion: el Excel cargado."""
    estado = alimentacion.estado_sesion()

    assert "excel" in estado
    assert "cargado" in estado["excel"]
    assert "archivo" in estado["excel"]
