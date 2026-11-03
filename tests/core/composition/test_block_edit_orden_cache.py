"""Guard del orden entre el FB de block edit, el cache y el evento SSE.

El HMI (SPA) no lee el resultado del ``POST /prepare``: el router
responde ``202`` y el FB sigue corriendo en el hilo del dispatcher. La
SPA espera al estado terminal del FB (evento SSE ``fb_state``) y solo
despues pulls el cache ``block_edit_prepared[plc]``.

Eso solo funciona si, en el instante en que se publica el estado
terminal, el cache ya esta escrito. Este modulo fija ese invariante:

  1. El cache ``block_edit_prepared`` esta poblado cuando se publica
     el estado terminal del FB.
  2. El ``job_id`` del evento terminal sigue resoluble, para que el HMI
     pueda correlacionar el evento con el ``202`` que recibio.

Si alguien mueve la escritura del cache detras del estado terminal, o
cambia el ciclo de vida del job en el engine, este test se pone rojo.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from core.composition.function_block_edit_prepare import (
    FunctionBlockEditPrepare,
)
from core.composition.plc_engine import Engine
from core.data.data_block_cache import DataBloqueCache
from core.data.data_block_plc import DataBloquePLC
from core.helpers.blocks_edit._workdir_layout import BlocksEditLayout
from core.infrastructure.tia.tia_cache import plc_blocks_put
from core.infrastructure.tia.tia_loop import SyncTIAClient
from core.runtime.app_cache import AppCache

PLC = "PLC_TEST"
BLOQUE = "Test_DB"


def _dto(nombre: str, numero: int) -> DataBloquePLC:
    return DataBloquePLC(
        nombre=nombre,
        numero=numero,
        tipo="DB",
        ruta="",
        title=None,
        comment=None,
        author=None,
        version=None,
        programming_language=None,
        memory_layout=None,
    )


def _tia_client() -> MagicMock:
    client = MagicMock(spec=SyncTIAClient)
    client.dispatch.side_effect = lambda cmd, args: {
        "ok": True,
        "result": {
            "exported_to": args.get("target_dir", ""),
            "count": len(args.get("block_names", [])),
            "exported_names": list(args.get("block_names", [])),
            "skipped_names": [],
        },
    }
    return client


def _esperar_job(engine: Engine, job_id: str, timeout: float = 15.0) -> None:
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        job = engine.get_job(job_id)
        if job is not None and job.status in ("done", "error"):
            return
        time.sleep(0.02)
    raise AssertionError(f"el job {job_id} no terminó en {timeout}s")


def test_el_cache_esta_poblado_cuando_se_publica_el_estado_terminal(
    tmp_path: Path,
) -> None:
    """El cache se escribe ANTES del evento terminal: el HMI puede leerlo."""
    app_cache = AppCache()
    plc_blocks_put(
        app_cache,
        PLC,
        DataBloqueCache(
            plc_name=PLC,
            blocks={DataBloquePLC.normalize_name(BLOQUE): _dto(BLOQUE, 1)},
        ),
    )

    fb = FunctionBlockEditPrepare(
        nombre="block_edit_prepare",
        tia_client=_tia_client(),
        app_cache=app_cache,
        layout=BlocksEditLayout(root=tmp_path),
    )

    engine = Engine()
    engine.register_fb("block_edit_prepare", fb)

    observado: dict[str, Any] = {}

    def _hook(name: str, f: Any) -> None:
        if name != "block_edit_prepare" or not f.is_terminal():
            return
        job = engine.current_job_for(name)
        observado["job_id"] = job.job_id if job is not None else None
        observado["prepared"] = app_cache.get_block_edit_prepared(PLC)

    engine.on_fb_change = _hook
    engine.start_ob1()
    try:
        job_id = engine.submit(
            "block_edit_prepare",
            plc_name=PLC,
            selected_block_paths=[BLOQUE],
        )
        _esperar_job(engine, job_id)
    finally:
        engine.stop_ob1(timeout=5)

    assert observado, "no se publico ningun estado terminal del FB"
    assert observado["prepared"], (
        "el cache block_edit_prepared estaba vacio cuando se publico el "
        "estado terminal: la SPA leeria la tabla vacia"
    )
    assert list(observado["prepared"].keys()) == [BLOQUE]
    assert observado["job_id"], (
        "el job_id no era resoluble en el estado terminal: la SPA no "
        "podria correlacionar el evento fb_state con el 202"
    )


def test_el_estado_terminal_lleva_el_job_id_del_trabajo() -> None:
    """El evento terminal trae el ``job_id`` del trabajo en curso.

    ``waitForFbJob`` correlaciona por ``job_id``: si el engine lo
    devolviera vacio en el estado terminal, el HMI esperaria hasta el
    timeout en vez de continuar.
    """
    app_cache = AppCache()
    fb = FunctionBlockEditPrepare(
        nombre="block_edit_prepare",
        tia_client=_tia_client(),
        app_cache=app_cache,
    )

    engine = Engine()
    engine.register_fb("block_edit_prepare", fb)

    jobs_por_evento: list[str | None] = []

    def _hook(name: str, f: Any) -> None:
        if name != "block_edit_prepare" or not f.is_terminal():
            return
        job = engine.current_job_for(name)
        jobs_por_evento.append(job.job_id if job is not None else None)

    engine.on_fb_change = _hook
    engine.start_ob1()
    try:
        job_id = engine.submit(
            "block_edit_prepare",
            plc_name="PLC_TEST",
            selected_block_paths=[BLOQUE],
        )
        _esperar_job(engine, job_id)
    finally:
        engine.stop_ob1(timeout=5)

    assert jobs_por_evento == [job_id]
