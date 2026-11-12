"""Comprueba que los docs de agente citan rutas que existen.

Los ficheros de ``.opencode/`` son la carta de cada agente: si nombran un
modulo que ya no esta, el agente trabaja sobre una estructura que ya no es
la del repo.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DOCS = RAIZ / ".opencode"

#: Las raices del repo que se pueden citar en los docs.
RAICES = ("backend/zc_suite", "tests", "scripts", "frontend")

#: Una ruta citada en los docs.
PATRON = re.compile(
    r"(?:backend/zc_suite|tests|scripts|frontend)/[A-Za-z0-9_./-]*",
)


def _docs() -> list[Path]:
    """Los ficheros de ``.opencode/``."""
    return sorted(DOCS.rglob("*.md"))


def _rutas_citadas(texto: str) -> list[str]:
    """Las rutas del repo que cita un texto."""
    return [ruta.rstrip(".") for ruta in PATRON.findall(texto)]


def _rutas_reales(texto: str) -> list[str]:
    """Las rutas citadas que no son un patron con comodines."""
    return [ruta for ruta in _rutas_citadas(texto) if "*" not in ruta]


def test_hay_docs_de_agente() -> None:
    """Los docs de agente estan, y son los que se esperan."""
    assert _docs(), "no hay docs en .opencode/"


def test_los_docs_citan_rutas_que_existen() -> None:
    """Cada ruta citada en los docs existe en el repo."""
    fallos: list[str] = []
    for doc in _docs():
        texto = doc.read_text(encoding="utf-8")
        for ruta in _rutas_reales(texto):
            if not (RAIZ / ruta).exists():
                fallos.append(f"{doc.relative_to(RAIZ)}: {ruta}")
    assert not fallos, "Rutas citadas que no existen:\n" + "\n".join(fallos)


def test_los_docs_no_citan_la_estructura_vieja() -> None:
    """Los docs no nombran ficheros que se movieron de sitio."""
    viejos = (
        "zc_suite/tia.py",
        "zc_suite/web.py",
        "zc_suite/eventos.py",
        "zc_suite/config.py",
        "zc_suite/workdir.py",
        "zc_suite/main.py",
        "simatic_sd/",
        "simatic_ml/",
    )
    fallos: list[str] = []
    for doc in _docs():
        texto = doc.read_text(encoding="utf-8")
        for viejo in viejos:
            if viejo in texto:
                fallos.append(f"{doc.relative_to(RAIZ)}: {viejo}")
    assert not fallos, "Rutas de la estructura anterior:\n" + "\n".join(fallos)


def test_cada_doc_de_agente_explica_el_contracto_de_los_trabajos() -> None:
    """Cada agente sabe como se organiza un trabajo."""
    for doc in _docs():
        if doc.name == "SKILL.md":
            continue
        texto = doc.read_text(encoding="utf-8")
        assert "funciones/" in texto, f"{doc.name} no explica donde viven los trabajos"
