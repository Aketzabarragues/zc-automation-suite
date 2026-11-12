"""Comprueba las fronteras de importacion del nucleo.

Reglas:

- El nucleo (todo ``zc_suite`` menos ``areas/``) no importa areas. La
  unica excepcion es ``zc_suite.nucleo.app.main``, que registra las areas en su lista
  ``AREAS``.
- Las areas no se importan entre si.

El comprobador recorre los ``import`` de cada fichero con ``ast``, asi que
detecta tambien los imports relativos (``from ..otra_area import x``).
"""
from __future__ import annotations

import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
BACKEND = RAIZ / "backend"
PAQUETE = "zc_suite"
AREAS = f"{PAQUETE}.areas"
EXCEPCIONES = frozenset({f"{PAQUETE}.nucleo.app.main"})

PAQUETE_DIR = BACKEND / PAQUETE
AREAS_DIR = PAQUETE_DIR / "areas"


# ── recorrido de imports ───────────────────────────────────────────────────


def _modulos(directorio: Path) -> list[Path]:
    """Ficheros python de un directorio, sin los ``__pycache__``."""
    return sorted(p for p in directorio.rglob("*.py") if "__pycache__" not in p.parts)


def _modulo_de(ruta: Path) -> str:
    """Nombre dotted de un modulo a partir de su ruta."""
    relativo = ruta.relative_to(BACKEND).with_suffix("")
    partes = list(relativo.parts)
    if partes[-1] == "__init__":
        partes.pop()
    return ".".join(partes)


def _paquete_de(ruta: Path) -> list[str]:
    """Paquete (con sus partes) al que pertenece un fichero."""
    partes = _modulo_de(ruta).split(".")
    if ruta.name != "__init__.py":
        partes.pop()
    return partes


def _importaciones_de_codigo(codigo: str, paquete: list[str]) -> set[str]:
    """Modulos absolutos importados por un codigo.

    Args:
        codigo: fuente del fichero.
        paquete: partes del paquete al que pertenece el fichero, para
            resolver los imports relativos.
    """
    arbol = ast.parse(codigo)
    modulos: set[str] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                modulos.add(alias.name)
        elif isinstance(nodo, ast.ImportFrom):
            if nodo.level:
                base = paquete[: len(paquete) - (nodo.level - 1)]
                if nodo.module:
                    base = base + nodo.module.split(".")
                modulos.add(".".join(base))
            elif nodo.module:
                modulos.add(nodo.module)
    return modulos


def _importaciones(ruta: Path) -> set[str]:
    """Modulos absolutos importados por un fichero."""
    return _importaciones_de_codigo(
        ruta.read_text(encoding="utf-8"),
        _paquete_de(ruta),
    )


def _es_de_area(ruta: Path) -> bool:
    """``True`` si el fichero vive dentro de ``zc_suite/areas``."""
    return AREAS_DIR in ruta.parents


# ── fronteras ──────────────────────────────────────────────────────────────


def test_el_nucleo_no_importa_areas() -> None:
    """Ningun modulo del nucleo importa un area."""
    fallos: list[str] = []
    for ruta in _modulos(PAQUETE_DIR):
        if _es_de_area(ruta):
            continue
        modulo = _modulo_de(ruta)
        if modulo in EXCEPCIONES:
            continue
        for importado in _importaciones(ruta):
            if importado == AREAS or importado.startswith(f"{AREAS}."):
                fallos.append(f"{modulo} importa {importado}")
    assert not fallos, "El nucleo no puede importar areas: " + "; ".join(fallos)


def test_main_es_la_unica_excepcion() -> None:
    """``main`` puede importar areas: es donde se registran."""
    ruta = BACKEND / PAQUETE.replace(".", "/") / "nucleo" / "app" / "main.py"

    assert ruta.is_file()
    assert _modulo_de(ruta) in EXCEPCIONES


def test_las_areas_no_se_importan_entre_si() -> None:
    """Un area no puede usar el codigo de otro area."""
    fallos: list[str] = []
    for area in sorted(p for p in AREAS_DIR.iterdir() if p.is_dir()):
        for ruta in _modulos(area):
            modulo = _modulo_de(ruta)
            for importado in _importaciones(ruta):
                if not importado.startswith(f"{AREAS}."):
                    continue
                otra = importado[len(AREAS) + 1 :].split(".")[0]
                if otra != area.name:
                    fallos.append(f"{modulo} importa {importado}")
    assert not fallos, "Las areas no se importan entre si: " + "; ".join(fallos)


def test_el_nucleo_no_importa_el_frontend() -> None:
    """El backend no sabe nada del frontend."""
    fallos: list[str] = []
    for ruta in _modulos(PAQUETE_DIR):
        if _es_de_area(ruta):
            continue
        for importado in _importaciones(ruta):
            if importado.startswith("frontend"):
                fallos.append(f"{_modulo_de(ruta)} importa {importado}")
    assert not fallos, "; ".join(fallos)


# ── autocomprobacion del comprobador ───────────────────────────────────────


def test_el_comprobador_detecta_un_import_de_area() -> None:
    codigo = "from zc_suite.areas.alimentacion import cosas\n"

    modulos = _importaciones_de_codigo(codigo, ["zc_suite", "tia_ops"])

    assert "zc_suite.areas.alimentacion" in modulos


def test_el_comprobador_detecta_un_import_relativo_de_otra_area() -> None:
    """Desde un area, ``..otra_area`` es otra area."""
    codigo = "from ..otra_area import cosas\n"

    modulos = _importaciones_de_codigo(
        codigo,
        ["zc_suite", "areas", "alimentacion"],
    )

    assert "zc_suite.areas.otra_area" in modulos


def test_el_comprobador_ignora_los_imports_de_su_propia_area() -> None:
    codigo = "from . import cosas\nfrom .hermanos import mas\n"

    modulos = _importaciones_de_codigo(
        codigo,
        ["zc_suite", "areas", "alimentacion", "datos"],
    )

    assert "zc_suite.areas.alimentacion.datos" in modulos
    assert "zc_suite.areas.alimentacion.datos.hermanos" in modulos
