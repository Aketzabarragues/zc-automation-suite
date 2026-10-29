"""Guard del reinicio de estado entre ejecuciones de un Function Block.

El dispatcher del OB1 reutiliza la misma instancia del FB para cada
trabajo: ``engine.submit(nombre_fb, ...)`` -> ``fb.execute(**params)``. Un
FB que acumule estado entre steps y no lo reinicie arrastra el estado
del run anterior:

- ``block_edit_apply`` acumulaba las ops del batch transaccional: un
  segundo ``execute()`` volvia a mandar a TIA los cambios ya aplicados.
- los FBs de proc_db se quedaban con el cache de bloques del run
  anterior cuando el ``AppCache`` no tenia cache para el PLC pedido
  (puede ser el de otro PLC).

Este modulo lo cierra de dos formas:

  1. Guard estructural: ningun FB puede mutar en un hook un atributo
     inicializado en ``__init__`` sin reiniciarlo en ``on_start`` o en
     ``reset_run_state``.
  2. Guard de comportamiento: dos ``execute()`` seguidos sobre la misma
     instancia no acumulan estado.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from core.composition.function_block_edit_apply import FunctionBlockEditApply
from core.data.data_block_plc import DataBloquePLC
from core.infrastructure.tia.tia_loop import SyncTIAClient
from core.runtime.app_cache import AppCache
from core.runtime.progress_buffer import ProgressTracker

REPO_ROOT = Path(__file__).resolve().parents[3]

MUTATORS = {"append", "extend", "update", "setdefault", "add", "insert"}
RESET_HOOKS = ("on_start", "reset_run_state")


# ── 1. Guard estructural ────────────────────────────────────────────


def _fb_files() -> list[Path]:
    """Ficheros de FB del repo (``function_*.py``)."""
    paths: list[Path] = []
    for pattern in (
        "core/composition/function_*.py",
        "areas/*/functions/function_*.py",
    ):
        paths.extend(REPO_ROOT.glob(pattern))
    return sorted(paths)


def _self_attrs(node: ast.AST) -> set[str]:
    """Atributos ``self.X`` asignados en el nodo."""
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Assign):
            targets = n.targets
        elif isinstance(n, ast.AnnAssign):
            targets = [n.target]
        else:
            continue
        for t in targets:
            if (
                isinstance(t, ast.Attribute)
                and isinstance(t.value, ast.Name)
                and t.value.id == "self"
            ):
                out.add(t.attr)
    return out


def _mutated_attrs(node: ast.AST) -> set[str]:
    """Atributos ``self.X`` mutados in-place (append, update, item assign)."""
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute) and f.attr in MUTATORS:
                v = f.value
                if (
                    isinstance(v, ast.Attribute)
                    and isinstance(v.value, ast.Name)
                    and v.value.id == "self"
                ):
                    out.add(v.attr)
        if isinstance(n, ast.Subscript):
            v = n.value
            if (
                isinstance(v, ast.Attribute)
                and isinstance(v.value, ast.Name)
                and v.value.id == "self"
            ):
                out.add(v.attr)
    return out


def _unconditional_attrs(method: ast.FunctionDef) -> set[str]:
    """Atributos asignados en el cuerpo del metodo (no dentro de un ``if``)."""
    out: set[str] = set()
    for stmt in method.body:
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            out |= _self_attrs(stmt)
    return out


def test_ningun_fb_acumula_estado_sin_reiniciarlo() -> None:
    """Ningun FB muta un atributo de Zona 3 sin reiniciarlo por run.

    El dispatcher del OB1 reutiliza la instancia del FB: si el estado no
    se reinicia, el segundo trabajo arrastra el del primero (doble
    escritura a TIA, diff contra un cache viejo).
    """
    ofensores: list[str] = []
    for path in _fb_files():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            methods = {m.name: m for m in cls.body if isinstance(m, ast.FunctionDef)}
            if "__init__" not in methods:
                continue
            init_attrs = _self_attrs(methods["__init__"])
            if not init_attrs:
                continue
            mutated = _mutated_attrs(cls)
            reset_attrs: set[str] = set()
            for hook in RESET_HOOKS:
                if hook in methods:
                    reset_attrs |= _unconditional_attrs(methods[hook])
            for attr in sorted(init_attrs & mutated - reset_attrs):
                ofensores.append(
                    f"{path.relative_to(REPO_ROOT)}::{cls.name}.{attr}"
                )
    assert not ofensores, (
        "FBs que acumulan estado entre runs sin reiniciarlo en "
        "on_start/reset_run_state: " + ", ".join(ofensores)
    )


def test_la_base_invoca_el_hook_de_reset() -> None:
    """``FunctionBase`` debe llamar a ``reset_run_state()`` en cada run.

    Sin la llamada, los FBs que definan el hook no lo ejecutarian: el
    estado seguiria arrastrándose entre trabajos.
    """
    base_path = REPO_ROOT / "core" / "composition" / "plc_function_base.py"
    tree = ast.parse(base_path.read_text(encoding="utf-8-sig"), filename=str(base_path))
    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        for method in [m for m in cls.body if isinstance(m, ast.FunctionDef)]:
            if method.name != "_reset_state_for_run":
                continue
            llama = any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "reset_run_state"
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "self"
                for n in ast.walk(method)
            )
            assert llama, (
                "FunctionBase._reset_state_for_run() no llama a "
                "self.reset_run_state(): el estado de Zona 3 no se reinicia"
            )
            return
    pytest.fail("FunctionBase._reset_state_for_run() no encontrado")


# ── 2. Guard de comportamiento ──────────────────────────────────────


def _make_dto(name: str, number: int, tipo: str = "DB") -> DataBloquePLC:
    return DataBloquePLC(
        nombre=name,
        numero=number,
        tipo=tipo,
        ruta="",
        title=None,
        comment=None,
        author=None,
        version=None,
        programming_language=None,
        memory_layout=None,
    )


def _make_fb() -> tuple[FunctionBlockEditApply, AppCache]:
    app_cache = AppCache()
    fb = FunctionBlockEditApply(
        nombre="block_edit_apply",
        tia_client=MagicMock(spec=SyncTIAClient),
        app_cache=app_cache,
        tracker=ProgressTracker(),
    )
    fb._tia_client.wrapper = MagicMock()
    return fb, app_cache


def _seed(app_cache: AppCache) -> None:
    """Siembra el cache de bloques preparados.

    El FB limpia el cache tras un commit exitoso (fuerza re-lectura en el
    proximo prepare), asi que hay que re-sembrarlo antes de cada run.
    """
    app_cache.set_block_edit_prepared(
        "PLC_1",
        {
            "DB2000_ED": _make_dto("DB2000_ED", 2000),
            "FC2000_ZC_ED": _make_dto("FC2000_ZC_ED", 2000, tipo="FC"),
        },
    )


def _submit_mock() -> MagicMock:
    inner: dict[str, Any] = {
        "success": True,
        "operations_executed": 2,
        "details": [],
    }
    return MagicMock(return_value={"ok": True, "result": inner})


def _scan_mock() -> MagicMock:
    cache = MagicMock()
    cache.blocks = [MagicMock(), MagicMock()]
    return MagicMock(return_value=cache)


def test_block_edit_apply_no_acumula_ops_entre_runs() -> None:
    """El 2o ``execute()`` no debe reenviar las ops del 1o a TIA.

    Sin el reset, el batch del 2o run lleva las 2 ops del 1o mas las 2
    suyas: TIA recibiria los cambios ya aplicados otra vez.
    """
    fb, app_cache = _make_fb()
    submit_mock = _submit_mock()
    fb._tia_client.submit_and_wait = submit_mock

    edits = {
        "DB2000_ED": {"number": 2001},
        "FC2000_ZC_ED": {"name": "FC2000_ZC_ED_NEW"},
    }

    with patch(
        "core.composition.function_block_edit_apply.scan_plc_blocks",
        new=_scan_mock(),
    ):
        _seed(app_cache)
        fb.execute(plc_name="PLC_1", edits=edits)
        _seed(app_cache)
        fb.execute(plc_name="PLC_1", edits=edits)

    assert fb.nStep == fb.n_done, fb.error_msg
    assert submit_mock.call_count == 2
    for call in submit_mock.call_args_list:
        ops = call.args[1]["operations"]
        assert len(ops) == 2, f"batch con {len(ops)} ops (esperado 2): {ops}"
    assert fb.result is not None
    assert fb.result["n_ops"] == 2


def test_block_edit_apply_no_arrastra_el_flag_no_op() -> None:
    """Un run sin cambios no puede dejar el FB en modo no-op.

    Si ``_noop_mode`` se queda en True, el run siguiente con cambios
    reales se creeria no-op y no aplicaria nada (fallo silencioso).
    """
    fb, app_cache = _make_fb()
    submit_mock = _submit_mock()
    fb._tia_client.submit_and_wait = submit_mock

    # Run 1: sin cambios (los edits coinciden con el cache) -> no-op.
    with patch(
        "core.composition.function_block_edit_apply.scan_plc_blocks",
        new=_scan_mock(),
    ):
        _seed(app_cache)
        fb.execute(
            plc_name="PLC_1",
            edits={
                "DB2000_ED": {"number": 2000},
                "FC2000_ZC_ED": {"name": "FC2000_ZC_ED"},
            },
        )
    assert fb.nStep == fb.n_done, fb.error_msg
    assert fb.result is not None
    assert fb.result["no_op"] is True
    assert submit_mock.call_count == 0

    # Run 2: con cambios reales -> debe dispatchar el batch.
    with patch(
        "core.composition.function_block_edit_apply.scan_plc_blocks",
        new=_scan_mock(),
    ):
        _seed(app_cache)
        fb.execute(
            plc_name="PLC_1",
            edits={
                "DB2000_ED": {"number": 2001},
                "FC2000_ZC_ED": {"name": "FC2000_ZC_ED_NEW"},
            },
        )
    assert fb.nStep == fb.n_done, fb.error_msg
    assert fb.result is not None
    assert fb.result["no_op"] is False
    assert fb.result["n_ops"] == 2
    assert submit_mock.call_count == 1


def test_fbs_de_proc_db_vuelven_al_cache_inyectado() -> None:
    """Los FBs de proc_db no deben reusar el cache de bloques anterior.

    Si el ``AppCache`` no tiene cache para el PLC pedido, el FB se
    queda sin cache: reusar el del run anterior (puede ser de otro PLC)
    diffearia contra bloques equivocados.
    """
    from areas.alimentacion.functions.function_proc_db_generar_preview import (
        FunctionProcDBGenerarPreview,
    )
    from areas.alimentacion.functions.function_proc_db_sincronizar import (
        FunctionProcDBSincronizar,
    )

    inyectado = {"DB1": _make_dto("DB1", 1)}
    for fb_cls in (FunctionProcDBSincronizar, FunctionProcDBGenerarPreview):
        fb = fb_cls(
            nombre="proc_db",
            tia_client=MagicMock(spec=SyncTIAClient),
            bloques_cache=inyectado,
        )
        fb._bloques_cache = "CACHE_VIEJO"
        fb.reset_run_state()
        assert fb._bloques_cache is inyectado, fb_cls.__name__
