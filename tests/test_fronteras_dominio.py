"""Comprueba que la logica pura de los dominios no depende de TIA.

Reglas:

- Los modulos de **dominio** (los que viven en ``areas/<area>/<dominio>/``,
  fuera de ``funciones/``) no importan ``zc_suite.nucleo.tia`` ni
  ``zc_suite.tia_ops``: son logica pura y se prueban sin TIA. Para lanzar un
  fallo esperado usan ``zc_suite.errores``.
- Solo los modulos de ``funciones/`` (y los de ``nucleo/tia/``) reciben el
  ``job``: son los unicos que declaran pasos y abren transacciones.
- Cada FB vive en su propio fichero y la funcion de dentro se llama como el
  fichero.

El comprobador recorre los ``import`` de cada fichero con ``ast``, asi que
detecta tambien los imports relativos.
"""
from __future__ import annotations

import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
BACKEND = RAIZ / "backend"
PAQUETE_DIR = BACKEND / "zc_suite"
AREAS_DIR = PAQUETE_DIR / "areas"

TIA = "zc_suite.nucleo.tia"
TIA_OPS = "zc_suite.tia_ops"

#: Prefijos de los modulos que pueden recibir el ``job``.
PREFIJOS_DE_FB = ("zc_suite.nucleo.funciones.", "zc_suite.nucleo.tia.")


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


def _arbol(ruta: Path) -> ast.Module:
    """El arbol de sintaxis de un fichero."""
    return ast.parse(ruta.read_text(encoding="utf-8"))


def _funciones_que_reciben_job(ruta: Path) -> list[str]:
    """Nombres de las funciones del fichero que reciben el ``job``."""
    return _funciones_que_reciben_job_de_codigo(ruta.read_text(encoding="utf-8"))


def _funciones_que_reciben_job_de_codigo(codigo: str) -> list[str]:
    """Nombres de las funciones de un codigo que reciben el ``job``."""
    nombres: list[str] = []
    for nodo in ast.walk(ast.parse(codigo)):
        if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        argumentos = nodo.args
        todos = [
            *argumentos.posonlyargs,
            *argumentos.args,
            *argumentos.kwonlyargs,
        ]
        if any(argumento.arg == "job" for argumento in todos):
            nombres.append(nodo.name)
    return nombres


def _funciones_de_nivel_sup(ruta: Path) -> set[str]:
    """Nombres de las funciones de primer nivel de un fichero."""
    return {
        nodo.name
        for nodo in _arbol(ruta).body
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


# ── que modulos son de dominio y cuales son FB ─────────────────────────────


def _dominios() -> list[Path]:
    """Las carpetas de dominio de cada area (todo menos ``funciones/``)."""
    carpetas: list[Path] = []
    for area in sorted(p for p in AREAS_DIR.iterdir() if p.is_dir()):
        carpetas.extend(
            p
            for p in sorted(area.iterdir())
            if p.is_dir() and p.name not in {"funciones", "__pycache__"}
        )
    return carpetas


def _modulos_de_dominio() -> list[Path]:
    """Los modulos de la logica pura de los dominios."""
    modulos: list[Path] = []
    for carpeta in _dominios():
        modulos.extend(_modulos(carpeta))
    return modulos


def _carpetas_de_fb() -> list[Path]:
    """Las carpetas ``funciones/`` del nucleo y de cada area."""
    carpetas = [PAQUETE_DIR / "nucleo" / "funciones"]
    carpetas.extend(area / "funciones" for area in sorted(AREAS_DIR.iterdir()) if area.is_dir())
    return [carpeta for carpeta in carpetas if carpeta.is_dir()]


def _modulos_de_fb() -> list[Path]:
    """Los modulos de los FB."""
    modulos: list[Path] = []
    for carpeta in _carpetas_de_fb():
        modulos.extend(_modulos(carpeta))
    return modulos


def _puede_recibir_job(modulo: str) -> bool:
    """``True`` si el modulo tiene derecho a recibir el ``job``."""
    if modulo.startswith(PREFIJOS_DE_FB):
        return True
    return any(
        modulo.startswith(f"zc_suite.areas.{area.name}.funciones.")
        for area in AREAS_DIR.iterdir()
        if area.is_dir()
    )


# ── fronteras ──────────────────────────────────────────────────────────────


def test_el_dominio_no_importa_el_motor_de_tia() -> None:
    """Los modulos de dominio no importan ``zc_suite.nucleo.tia``."""
    fallos: list[str] = []
    for ruta in _modulos_de_dominio():
        for importado in _importaciones(ruta):
            if importado == TIA or importado.startswith(f"{TIA}."):
                fallos.append(f"{_modulo_de(ruta)} importa {importado}")
    assert not fallos, "El dominio es logica pura: " + "; ".join(fallos)


def test_el_dominio_no_importa_las_operaciones_de_tia() -> None:
    """Los modulos de dominio no importan ``zc_suite.tia_ops``."""
    fallos: list[str] = []
    for ruta in _modulos_de_dominio():
        for importado in _importaciones(ruta):
            if importado == TIA_OPS or importado.startswith(f"{TIA_OPS}."):
                fallos.append(f"{_modulo_de(ruta)} importa {importado}")
    assert not fallos, "El dominio es logica pura: " + "; ".join(fallos)


def test_el_dominio_no_recibe_el_job() -> None:
    """Los modulos de dominio no reciben el ``job``."""
    fallos: list[str] = []
    for ruta in _modulos_de_dominio():
        for funcion in _funciones_que_reciben_job(ruta):
            fallos.append(f"{_modulo_de(ruta)}::{funcion} recibe el job")
    assert not fallos, "El job es solo de los FB: " + "; ".join(fallos)


def test_solo_los_fb_reciben_el_job() -> None:
    """El ``job`` solo se recibe en ``funciones/`` y en ``nucleo/tia/``."""
    fallos: list[str] = []
    for ruta in _modulos(PAQUETE_DIR):
        modulo = _modulo_de(ruta)
        if _puede_recibir_job(modulo):
            continue
        for funcion in _funciones_que_reciben_job(ruta):
            fallos.append(f"{modulo}::{funcion} recibe el job")
    assert not fallos, "El job es solo de los FB: " + "; ".join(fallos)


def test_cada_fb_vive_en_su_propio_fichero() -> None:
    """La funcion de un FB se llama como el fichero que lo contiene."""
    fallos: list[str] = []
    for ruta in _modulos_de_fb():
        if ruta.name == "__init__.py":
            continue
        if ruta.stem not in _funciones_de_nivel_sup(ruta):
            fallos.append(f"{_modulo_de(ruta)} no define {ruta.stem}()")
    assert not fallos, "Cada FB tiene su funcion: " + "; ".join(fallos)


# ── autocomprobacion del comprobador ───────────────────────────────────────


def test_el_comprobador_detecta_un_import_de_tia_ops() -> None:
    codigo = "from zc_suite.tia_ops import OperacionError\n"

    modulos = _importaciones_de_codigo(codigo, ["zc_suite", "areas", "alimentacion"])

    assert "zc_suite.tia_ops" in modulos


def test_el_comprobador_detecta_un_import_relativo_de_tia() -> None:
    """Desde el area, ``....nucleo.tia`` es el motor de TIA."""
    codigo = "from ....nucleo.tia.job import Job\n"

    modulos = _importaciones_de_codigo(
        codigo,
        ["zc_suite", "areas", "alimentacion", "excel"],
    )

    assert "zc_suite.nucleo.tia.job" in modulos


def test_el_comprobador_detecta_el_job_recibido() -> None:
    codigo = "def buscar(job: Job) -> dict[str, str]:\n    return {}\n"

    assert _funciones_que_reciben_job_de_codigo(codigo) == ["buscar"]
