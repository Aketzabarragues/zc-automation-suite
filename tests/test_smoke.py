"""Smoke del esqueleto: los paquetes del nucleo existen y son importables."""

from __future__ import annotations

import importlib

import pytest

PAQUETES_NUCLEO: tuple[str, ...] = (
    "zc_suite",
    "zc_suite.tia_ops",
    "zc_suite.simatic",
    "zc_suite.simatic.ml",
    "zc_suite.simatic.sd",
    "zc_suite.nucleo.app",
    "zc_suite.nucleo.web",
    "zc_suite.nucleo.web.rutas",
    "zc_suite.nucleo.tia",
    "zc_suite.nucleo.funciones",
    "zc_suite.areas",
)


@pytest.mark.parametrize("nombre", PAQUETES_NUCLEO)
def test_paquete_del_nucleo_es_importable(nombre: str) -> None:
    modulo = importlib.import_module(nombre)
    assert modulo.__name__ == nombre


def test_version_del_paquete() -> None:
    from zc_suite import __version__

    assert __version__.count(".") == 2
