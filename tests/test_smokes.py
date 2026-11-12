"""Los smokes de ``scripts/smoke/``: su nombre y el uso que documentan.

Los smokes se lanzan a mano, contra un TIA Portal real. El texto de uso va en
el docstring del propio script, asi que se puede copiar y pegar sin mirar
nada mas. Este test lo vigila: si el script se renombra o se mueve, el uso
que documenta tiene que seguir citando su ruta real.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
CARPETA = RAIZ / "scripts" / "smoke"

#: Separador de Windows: el uso se escribe para PowerShell.
BARRA = "\\"


def _smokes() -> list[Path]:
    """Los scripts de smoke del repo."""
    return sorted(p for p in CARPETA.glob("*.py") if not p.name.startswith("_"))


def _docstring(ruta: Path) -> str:
    """El docstring del modulo."""
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    return ast.get_docstring(arbol) or ""


def test_hay_smokes() -> None:
    """Hay smokes que lanzar a mano."""
    assert _smokes()


@pytest.mark.parametrize("ruta", _smokes(), ids=lambda p: p.name)
def test_el_uso_cita_la_ruta_real(ruta: Path) -> None:
    """El docstring del smoke cita su propia ruta, tal y como se ejecuta."""
    docstring = _docstring(ruta)
    propia = f"scripts{BARRA}smoke{BARRA}{ruta.name}"

    assert propia in docstring, f"El uso de {ruta.name} no cita {propia}."


@pytest.mark.parametrize("ruta", _smokes(), ids=lambda p: p.name)
def test_el_uso_no_cita_una_ruta_que_no_existe(ruta: Path) -> None:
    """El docstring no cita la carpeta vieja de los smokes."""
    docstring = _docstring(ruta)

    assert "tests/smoke" not in docstring
    assert f"tests{BARRA}smoke" not in docstring


@pytest.mark.parametrize("ruta", _smokes(), ids=lambda p: p.name)
def test_el_smoke_esta_fuera_de_la_suite(ruta: Path) -> None:
    """Los smokes no forman parte de la recogida de pytest."""
    nombre = ruta.stem

    assert nombre not in {"test_tia", "test_errores", "test_smokes"}
    assert not nombre.startswith("test_")
