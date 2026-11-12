"""Los valores esperados y las ayudas que comparten los tests del Excel maestro.

``ESPERADO_PLCS`` lo usan el test de paridad del parser y el test de la cache.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

ESPERADO_PLCS = [
    {
        "plc": "PLC1",
        "uid": 1,
    },
    {
        "plc": "PLC2",
        "uid": 2,
    },
]


def _tabla(datos: dict[str, Any], tipo: str) -> dict[str, Any]:
    """La tabla de un tipo de dispositivo del volcado."""
    for tabla in datos["dispositivos"]:
        if tabla["tipo"] == tipo:
            return tabla
    raise AssertionError(f"El volcado no tiene la tabla {tipo}.")




@pytest.fixture
def esperado_plcs() -> dict[str, Any]:
    """Los PLCs que espera el parser, tal y como los deja ``main``."""
    return ESPERADO_PLCS


@pytest.fixture
def tabla() -> Callable[..., dict[str, Any]]:
    """La tabla de un tipo de dispositivo del volcado."""
    return _tabla
