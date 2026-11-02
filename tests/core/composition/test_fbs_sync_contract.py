"""Guard del contrato sync de los Function Blocks.

El OB1 ejecuta cada FB con ``fb.execute()``, que es sync. Si el
handler de un step devuelve una corrutina, el base lanza
``TypeError`` y el trabajo muere en el hilo del dispatcher. Ese fallo
solo aparece contra la app real: el camino legacy ``tick()`` sigue
soportando FBs async, asi que los tests que usan ese camino pasan en
verde mientras el OB1 revienta.

Este modulo cierra el hueco de tres formas:

  1. Todos los FBs registrados (core + areas) tienen los hooks y los
     handlers de step sync.
  2. Ningun ``function_*.py`` del repo declara hooks ni handlers async.
  3. ``execute()`` no muere con el error de corrutina.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
from unittest.mock import MagicMock

import areas.alimentacion as alimentacion
from core.composition.plc_engine import Engine
from core.composition import register_core_fbs
from core.infrastructure.tia.tia_loop import SyncTIAClient

REPO_ROOT = Path(__file__).resolve().parents[3]
HOOKS = ("on_start", "on_finish")


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


# ----------------------------------------------------------------------
# 1. Los FBs registrados
# ----------------------------------------------------------------------


def test_se_registra_algun_fb():
    """Guard del propio test: si no hay FBs, el resto no prueba nada."""
    engine = _build_engine()
    assert engine.registered_fb_names(), "no se registro ningun FB"


def test_todos_los_fbs_registrados_tienen_hooks_sync():
    """Ningun FB registrado puede devolver una corrutina."""
    engine = _build_engine()
    ofensores: list[str] = []
    for nombre in engine.registered_fb_names():
        fb = engine.get_fb(nombre)
        assert fb is not None, f"FB '{nombre}' registrado pero no resoluble"
        for hook in HOOKS:
            if inspect.iscoroutinefunction(getattr(fb, hook, None)):
                ofensores.append(f"{nombre}.{hook}")
        for spec in fb.pasos_declarados():
            if inspect.iscoroutinefunction(getattr(fb, spec.metodo, None)):
                ofensores.append(f"{nombre}.{spec.metodo}")
    assert not ofensores, (
        "hooks o handlers async en FBs registrados (el OB1 los ejecuta "
        f"con execute() y muere): {', '.join(ofensores)}"
    )


# ----------------------------------------------------------------------
# 2. Barrido del codigo fuente
# ----------------------------------------------------------------------


def test_ningun_fichero_de_fb_declara_hooks_async():
    """Ningun ``function_*.py`` del repo declara hooks async.

    Cubre los FBs que todavia no se registran en el engine: si uno
    nace async, el fallo aparece el dia que se cablea.
    """
    ofensores: list[str] = []
    for path in _fb_files():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            if node.name in HOOKS or node.name.startswith("_stage_"):
                rel = path.relative_to(REPO_ROOT)
                ofensores.append(f"{rel}:{node.lineno} {node.name}")
    assert not ofensores, (
        "hooks o handlers async declarados en ficheros de FB: "
        + ", ".join(ofensores)
    )


# ----------------------------------------------------------------------
# 3. El camino del OB1
# ----------------------------------------------------------------------


def test_execute_de_scan_plc_blocks_no_muere_con_error_de_corrutina():
    """``scan_plc_blocks`` es el FB que dispara el scan desde la SPA."""
    from core.composition.function_scan_plc_blocks import FunctionScanPlcBlocks

    fb = FunctionScanPlcBlocks(
        nombre="scan_plc_blocks",
        tia_client=MagicMock(spec=SyncTIAClient),
    )
    fb.execute(plc_name="PLC_1")
    assert "corrutina" not in (fb.error_msg or ""), fb.error_msg


def test_execute_de_block_edit_prepare_no_muere_con_error_de_corrutina():
    """``block_edit_prepare`` es el FB que prepara la edicion de bloques."""
    from core.composition.function_block_edit_prepare import (
        FunctionBlockEditPrepare,
    )

    fb = FunctionBlockEditPrepare(
        nombre="block_edit_prepare",
        tia_client=MagicMock(spec=SyncTIAClient),
    )
    fb.execute(plc_name="PLC_1", selected_block_paths=[])
    assert "corrutina" not in (fb.error_msg or ""), fb.error_msg
