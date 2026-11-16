"""Comprueba que los docs de agente citan rutas que existen.

Los docs de agente son la carta de cada agente: si nombran un modulo que ya
no esta, el agente trabaja sobre una estructura que ya no es la del repo.

Los docs de agente viven en dos sitios:

- ``.operator/``: notas locales del entorno. Es local: ``.operator/`` esta
  en el gitignore global, asi que en un clon limpio no existe.
- ``.opencode/agent/``: las definiciones de subagente que carga el harness.

``docs/`` queda fuera: es documentacion para humanos, no la carta de un
agente. ``referencia_ui/`` registra de donde salio cada captura (componentes
que ya no existen) y ``FLUJOS_ALIMENTACION.md`` documenta el layout de main
a proposito.

Si no hay ningun doc (clon limpio sin el cerebro), la comprobacion se
salta: no hay nada que verificar.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]

#: Las raices del repo donde viven los docs de agente.
RAICES_DOCS = (RAIZ / ".operator", RAIZ / ".opencode")

#: Las raices del repo que se pueden citar en los docs.
RAICES = ("backend/zc_suite", "tests", "scripts", "frontend")

#: Una ruta citada en los docs.
PATRON = re.compile(
    r"(?:backend/zc_suite|tests|scripts|frontend)/[A-Za-z0-9_./-]*",
)


def _docs() -> list[Path]:
    """Los docs de agente, sin los ``node_modules`` de los plugins."""
    docs: list[Path] = []
    for raiz in RAICES_DOCS:
        if not raiz.is_dir():
            continue
        docs.extend(
            doc for doc in raiz.rglob("*.md") if "node_modules" not in doc.parts
        )
    return sorted(docs)


def _rutas_citadas(texto: str) -> list[str]:
    """Las rutas del repo que cita un texto."""
    return [ruta.rstrip(".") for ruta in PATRON.findall(texto)]


def _rutas_reales(texto: str) -> list[str]:
    """Las rutas citadas que no son un patron con comodines."""
    return [ruta for ruta in _rutas_citadas(texto) if "*" not in ruta]


def test_hay_docs_de_agente() -> None:
    """Los docs de agente estan, y son los que se esperan."""
    docs = _docs()
    if not docs:
        pytest.skip("no hay docs de agente: clon limpio sin el cerebro del proyecto")
    assert docs, "no hay docs de agente"


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
    """Cada definicion de subagente sabe como se organiza un trabajo."""
    definiciones = RAIZ / ".opencode" / "agent"
    if not definiciones.is_dir():
        pytest.skip("no hay definiciones de subagente")
    for doc in sorted(definiciones.glob("*.md")):
        texto = doc.read_text(encoding="utf-8")
        assert "funciones/" in texto, f"{doc.name} no explica donde viven los trabajos"


#: El conocimiento durable del proyecto. Versionado: se comprueba siempre.
DOCS_DURABLES = ("TIA_OPENNESS.md", "REESCRITURA_ESTADO.md", "PERFIL_OPERARIO.md")


def test_los_docs_durables_citan_rutas_que_existen() -> None:
    """Cada ruta que cita el conocimiento durable existe en el repo."""
    fallos: list[str] = []
    for nombre in DOCS_DURABLES:
        doc = RAIZ / "docs" / nombre
        assert doc.is_file(), f"Falta el doc durable {nombre}"
        for ruta in _rutas_reales(doc.read_text(encoding="utf-8")):
            if not (RAIZ / ruta).exists():
                fallos.append(f"{nombre}: {ruta}")
    assert not fallos, "Rutas citadas que no existen:\n" + "\n".join(fallos)


def test_los_docs_durables_no_citan_la_estructura_vieja() -> None:
    """El conocimiento durable no nombra ficheros que se movieron."""
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
    for nombre in DOCS_DURABLES:
        doc = RAIZ / "docs" / nombre
        texto = doc.read_text(encoding="utf-8")
        for viejo in viejos:
            if viejo in texto:
                fallos.append(f"{nombre}: {viejo}")
    assert not fallos, "Rutas de la estructura anterior:\n" + "\n".join(fallos)
