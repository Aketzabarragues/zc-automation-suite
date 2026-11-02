"""Guard del contrato de la declaracion de steps en los FBs del repo.

Los 12 FBs del repo declaran sus steps con ``@step``, encima de su
propio codigo. Este modulo comprueba que se cumple en todos:

  1. El slug del metodo es el ``snake_case`` del nombre visible.
  2. Ningun FB pasa la lista ``steps=`` al base ni define ``run_step``
     (la forma antigua, ya retirada).
  3. Ningun step se queda sin handler: el dispatch no tiene fallback.
"""
from __future__ import annotations

import ast
import re
import unicodedata
from pathlib import Path
from unittest.mock import MagicMock

import areas.alimentacion as alimentacion
from core.composition import register_core_fbs
from core.composition.plc_engine import Engine
from core.infrastructure.tia.tia_loop import SyncTIAClient

REPO_ROOT = Path(__file__).resolve().parents[3]


def _build_engine() -> Engine:
    """Engine con los FBs core y los del area de alimentacion."""
    engine = Engine()
    tia_client = MagicMock(spec=SyncTIAClient)
    register_core_fbs.register(engine, tia_client=tia_client)
    alimentacion.register(engine, tia_client=tia_client)
    return engine


def _fb_files() -> list[Path]:
    """Ficheros de FB del repo (``function_*.py``)."""
    paths: list[Path] = []
    for pattern in (
        "core/composition/function_*.py",
        "areas/*/functions/function_*.py",
    ):
        paths.extend(REPO_ROOT.glob(pattern))
    return sorted(paths)


def _slug(nombre: str) -> str:
    """El slug de un nombre visible: minusculas, sin acentos, sin signos.

    Es la regla de ``docs/HOWTO_CREATE_FB.md`` (§3.1).
    """
    descompuesto = unicodedata.normalize("NFKD", nombre)
    plano = "".join(c for c in descompuesto if not unicodedata.combining(c))
    limpio = re.sub(r"[^a-z0-9]+", "_", plano.lower())
    return re.sub(r"_+", "_", limpio).strip("_")


def test_el_guard_arranca_con_los_fbs_del_repo() -> None:
    """Guard del propio guard: si no hay FBs, el resto no prueba nada."""
    engine = _build_engine()
    nombres = engine.registered_fb_names()
    assert len(nombres) >= 12, (
        f"se esperaban los 12 FBs del repo y hay {len(nombres)}: {nombres}"
    )


def test_el_slug_de_cada_step_es_el_snake_case_de_su_nombre_visible() -> None:
    """El metodo de un step se llama ``_stage_<n>_<slug del nombre visible>``.

    El nombre visible es la etiqueta del operario (no se toca); el slug
    es el identificador del metodo, y tiene que derivarse de ella de
    forma mecanica: si no, cada FB inventa su propia convencion.
    """
    engine = _build_engine()
    ofensores: list[str] = []
    for nombre in engine.registered_fb_names():
        fb = engine.get_fb(nombre)
        assert fb is not None, f"FB '{nombre}' registrado pero no resoluble"
        for idx, spec in enumerate(fb.pasos_declarados(), start=1):
            esperado = f"_stage_{idx}_{_slug(spec.nombre)}"
            if spec.metodo != esperado:
                ofensores.append(
                    f"{nombre}: {spec.metodo} (se esperaba {esperado})"
                )
    assert not ofensores, (
        "el slug del metodo no es el snake_case del nombre visible: "
        + ", ".join(ofensores)
    )


def test_ningun_fb_del_repo_pasa_la_lista_de_steps_al_base() -> None:
    """La forma antigua esta retirada: el base ya no acepta ``steps=``."""
    ficheros = _fb_files()
    assert ficheros, "el glob no ha encontrado ficheros de FB"

    ofensores: list[str] = []
    for path in ficheros:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "__init__"):
                continue
            for kw in node.keywords:
                if kw.arg == "steps":
                    rel = path.relative_to(REPO_ROOT)
                    ofensores.append(f"{rel}:{node.lineno}")
    assert not ofensores, (
        "FBs que pasan steps= al base (forma retirada): " + ", ".join(ofensores)
    )


def test_ningun_fb_del_repo_declara_run_step() -> None:
    """El dispatch lo hace el motor: ningun FB define ``run_step``."""
    ficheros = _fb_files()
    assert ficheros, "el glob no ha encontrado ficheros de FB"

    ofensores: list[str] = []
    for path in ficheros:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "run_step":
                rel = path.relative_to(REPO_ROOT)
                ofensores.append(f"{rel}:{node.lineno}")
    assert not ofensores, (
        "FBs que definen run_step (el dispatch es del motor): "
        + ", ".join(ofensores)
    )


def test_ningun_step_se_queda_sin_handler() -> None:
    """El dispatch no tiene fallback: todo step tiene su metodo."""
    engine = _build_engine()
    ofensores: list[str] = []
    for nombre in engine.registered_fb_names():
        fb = engine.get_fb(nombre)
        assert fb is not None, f"FB '{nombre}' registrado pero no resoluble"
        for idx, step in enumerate(fb.steps):
            handler = step.get("handler")
            if not handler:
                ofensores.append(f"{nombre}[{idx}] ({step.get('nombre')})")
            elif not hasattr(fb, handler):
                ofensores.append(
                    f"{nombre}[{idx}] -> {handler} no existe en el FB"
                )
    assert not ofensores, (
        "steps sin handler (el motor no tiene fallback): " + ", ".join(ofensores)
    )


def test_el_base_no_llama_a_run_step() -> None:
    """El motor llama al handler declarado y no tiene ruta alternativa."""
    from core.composition.plc_function_base import FunctionBase

    assert not hasattr(FunctionBase, "run_step")

    base = REPO_ROOT / "core/composition/plc_function_base.py"
    tree = ast.parse(base.read_text(encoding="utf-8-sig"), filename=str(base))
    ofensores: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "run_step"
            and isinstance(func.value, ast.Name)
            and func.value.id == "self"
        ):
            ofensores.append(f"linea {node.lineno}")
    assert not ofensores, (
        "el base sigue llamando a self.run_step: " + ", ".join(ofensores)
    )
