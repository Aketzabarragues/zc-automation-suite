"""Tests de integración: use cases de procesos emiten stages al
ProgressTracker.

Cubre:
  1. ``generar_prevision`` cierra correctamente el stage "done"
     (regression: el stage "done" se quedaba en ``pending``
     para siempre porque el use case llamaba a
     ``finish_stage("done")`` sin hacer antes un
     ``start_stage("done")``. El método ``finish_stage`` es
     no-op si el stage no está en ``STAGE_RUNNING``).
  2. ``ejecutar_transaccion`` cierra correctamente el stage
     "done" y emite los 5 stages en orden.

Los use cases reales llaman al gateway y al parser de Excel, lo
cual es costoso de mockear. Aquí usamos ``MagicMock`` para el
gateway y ``MagicMock`` para el state con un ``excel_cache``
mínimo.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.application.progress_buffer import (  # noqa: E402
    ProgressTracker,
    STAGE_DONE,
    STAGE_ERROR,
    STAGE_PENDING,
    STAGE_RUNNING,
)
from core.infrastructure.config_manager import ConfigManager  # noqa: E402
from core.infrastructure.gateway import TIAProcessGateway  # noqa: E402
from core.models.bloque_cache import BloqueCache  # noqa: E402
from core.models.bloque_plc import BloquePLC  # noqa: E402
from areas.alimentacion.application.use_cases.sync_procesos_comentarios import (  # noqa: E402
    SyncProcesosComentariosUseCase,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_excel_cache() -> MagicMock:
    """Excel cache con 1 proceso, 2 PReal, 1 ALM (uid=100, codigo=CPR)."""
    proc = MagicMock(uid=100, nombre="Compacto", codigo="CPR")
    ec = MagicMock()
    ec.procesos = [proc]
    ec.parametros_real = [
        MagicMock(uid="PR_1", codigo="CPR", num_db=53100, comentario_db="X"),
        MagicMock(uid="PR_2", codigo="CPR", num_db=53100, comentario_db="Y"),
    ]
    ec.parametros_int = []
    ec.alarmas = [
        MagicMock(uid="AL_1", proceso="Compacto", num_db=55100,
                  comentario_db="Z")
    ]
    return ec


def _make_state(excel_cache: MagicMock | None) -> MagicMock:
    s = MagicMock()
    s.excel_cache = excel_cache
    return s


def _make_populated_cache() -> BloqueCache:
    """Cache con los 3 nombres esperados para proc uid=100, codigo=CPR."""
    return BloqueCache(
        blocks={
            BloquePLC.normalize_name("DB53100_CPR_PARAM"):
                BloquePLC(nombre="DB53100_CPR_PARAM", numero=0, tipo="DB", ruta=""),
            BloquePLC.normalize_name("DB55100_CPR_ALM"):
                BloquePLC(nombre="DB55100_CPR_ALM", numero=0, tipo="DB", ruta=""),
        },
        tag_tables={
            BloquePLC.normalize_name("100_CPR"):
                BloquePLC(nombre="100_CPR", numero=0, tipo="TAG_TABLE", ruta=""),
        },
        plc_name="PLC_X",
    )


# ── Tests ───────────────────────────────────────────────────────────────


def test_generar_prevision_done_stage_closes_correctly() -> None:
    """Regression: ``generar_prevision`` cierra el stage "done".

    Bug: el use case llamaba a ``finish_stage("done")`` sin antes
    hacer ``start_stage("done")``, así que ``finish_stage`` era
    no-op (solo actúa si el stage está en ``STAGE_RUNNING``) y el
    stage "done" se quedaba en ``STAGE_PENDING`` para siempre. La
    SPA mostraba el overlay con "Done" en estado running incluso
    después de que la operación había terminado.

    Tras el fix, el stage "done" transita a ``STAGE_DONE``.

    Nota: el preview ahora hace un export_and_diff stage adicional
    que llama a ``gateway.export_block``. En este test el mock
    del gateway NO escribe archivos, así que el export falla y
    caemos en la rama de "current=None" (que es la rama
    accionable: el operario ve que algo falló y puede
    investigar). Lo que importa para este test es que el stage
    "done" se cierre.
    """
    tracker = ProgressTracker()
    gateway = MagicMock(spec=TIAProcessGateway)
    config = MagicMock(spec=ConfigManager)
    use_case = SyncProcesosComentariosUseCase(
        gateway=gateway,
        config_manager=config,
        app_state=_make_state(_make_excel_cache()),
        progress=tracker,
        bloques_cache=_make_populated_cache(),
    )

    import asyncio
    result = asyncio.run(use_case.generar_prevision(100))

    assert result["precondiciones_ok"] is True
    snap = tracker.snapshot()
    # Los 5 stages (check_state, check_blocks, build_slot_maps,
    # export_and_diff, done) deben estar en DONE. El
    # export_and_diff cae en la rama de error (current=None)
    # porque el mock del gateway no escribe los .s7dcl/.s7res.
    assert len(snap.stages) == 5
    assert all(s["status"] == STAGE_DONE for s in snap.stages), (
        f"Todos los stages deben estar en DONE. Actual: "
        f"{[(s['id'], s['status']) for s in snap.stages]}"
    )
    # El stage "done" en concreto.
    done_stage = next(s for s in snap.stages if s["id"] == "done")
    assert done_stage["status"] == STAGE_DONE
    # El export_and_diff stage debe tener un detail de error
    # porque el mock del gateway no escribió los archivos.
    export_stage = next(
        s for s in snap.stages if s["id"] == "export_and_diff"
    )
    assert export_stage["status"] == STAGE_DONE
    assert "Error" in (export_stage["detail"] or "") or \
           "Preview" in (export_stage["detail"] or "")
    # El contador de progreso debe ser 5/5.
    assert snap.current == 5
    assert snap.percent == 100


def test_generar_prevision_done_closes_when_missing_blocks() -> None:
    """Cuando los bloques están ausentes, el stage "done" también
    se cierra (con detail indicando los bloques faltantes)."""
    tracker = ProgressTracker()
    gateway = MagicMock(spec=TIAProcessGateway)
    config = MagicMock(spec=ConfigManager)
    use_case = SyncProcesosComentariosUseCase(
        gateway=gateway,
        config_manager=config,
        app_state=_make_state(_make_excel_cache()),
        progress=tracker,
        bloques_cache=BloqueCache(),  # VACÍA → missing_blocks
    )

    import asyncio
    result = asyncio.run(use_case.generar_prevision(100))

    assert result["precondiciones_ok"] is False
    assert len(result["missing_blocks"]) == 3
    snap = tracker.snapshot()
    done_stage = next(s for s in snap.stages if s["id"] == "done")
    assert done_stage["status"] == STAGE_DONE
    assert "Faltan 3 bloques" in done_stage["detail"]


def test_generar_prevision_done_closes_when_cache_is_none() -> None:
    """Cuando el cache es ``None`` (PLC no escaneado), el stage
    "done" también se cierra (con detail accionable)."""
    tracker = ProgressTracker()
    gateway = MagicMock(spec=TIAProcessGateway)
    config = MagicMock(spec=ConfigManager)
    use_case = SyncProcesosComentariosUseCase(
        gateway=gateway,
        config_manager=config,
        app_state=_make_state(_make_excel_cache()),
        progress=tracker,
        bloques_cache=None,  # PLC no escaneado
    )

    import asyncio
    result = asyncio.run(use_case.generar_prevision(100))

    assert result["precondiciones_ok"] is False
    assert "Cache de bloques" in result["missing_blocks"][0]
    snap = tracker.snapshot()
    done_stage = next(s for s in snap.stages if s["id"] == "done")
    assert done_stage["status"] == STAGE_DONE
    assert "Sin cache de bloques" in done_stage["detail"]


def test_ejecutar_transaccion_done_stage_closes_correctly() -> None:
    """Regression equivalente para ``ejecutar_transaccion``: el
    stage "done" se cierra tras la transacción exitosa."""
    tracker = ProgressTracker()
    gateway = MagicMock(spec=TIAProcessGateway)
    gateway.execute_transactional_batch = AsyncMock(
        return_value={
            "success": True,
            "operations_executed": 3,
            "details": [],
        }
    )
    config = MagicMock(spec=ConfigManager)
    config.get_tia_folder_proceso.return_value = "003_Procesos"
    use_case = SyncProcesosComentariosUseCase(
        gateway=gateway,
        config_manager=config,
        app_state=_make_state(_make_excel_cache()),
        progress=tracker,
        bloques_cache=_make_populated_cache(),
    )

    import asyncio
    result = asyncio.run(
        use_case.ejecutar_transaccion(
            100, {"plc_name": "PLC_X", "proc_uid": 100}
        )
    )

    assert result["success"] is True
    assert result["operations_executed"] == 3
    snap = tracker.snapshot()
    # 5 stages: check_state, check_blocks, build_slot_maps,
    # open_transaction, done. Todos DONE.
    assert len(snap.stages) == 5
    assert all(s["status"] == STAGE_DONE for s in snap.stages), (
        f"Todos los stages deben estar en DONE. Actual: "
        f"{[(s['id'], s['status']) for s in snap.stages]}"
    )
    done_stage = next(s for s in snap.stages if s["id"] == "done")
    assert done_stage["status"] == STAGE_DONE
    assert "3 ops" in done_stage["detail"]


def test_generar_prevision_diff_real_con_archivos_tia(tmp_path) -> None:
    """Verifica el flujo completo de export + read + diff con
    archivos .s7dcl/.s7res REALES en disco. El mock del gateway
    escribe los archivos en lugar de llamar a TIA (simula lo que
    haría export_block), y el use case los lee con
    ProcesoCommentUpdater.read_current_comments.

    Escenario:
      - DB_PARAM con PReal[1..2] y ALM[1] (en DB_ALM).
      - .s7res con MLC_PR_001 = "TIA_PR_1", MLC_PR_002 = "TIA_PR_2",
        MLC_ALM_001 = "TIA_AL_1".
      - Excel con PReal[1] = "X" (≠ TIA, update), PReal[2] = "TIA_PR_2"
        (= TIA, equal), ALM[1] = "AL_NUEVO" (≠ TIA, update).
      - PInt: el Excel no tiene filas → slot_map vacío.
    """
    import asyncio
    import re
    from core.infrastructure.gateway import TIAProcessGateway
    from core.models.bloque_cache import BloqueCache
    from core.models.bloque_plc import BloquePLC
    from unittest.mock import AsyncMock

    # 1. Preparar los archivos .s7dcl/.s7res en el work_dir que
    # construirá el use case como si vinieran de TIA. El caso de uso
    # los monta en ``<build_cache>/procesos/preview/``, por lo que
    # pre-escribimos directamente ahí.
    work_dir = tmp_path / "procesos" / "preview"
    work_dir.mkdir(parents=True)
    db_param = "DB53100_CPR_PARAM"
    db_alm = "DB55100_CPR_ALM"

    s7dcl_param = (
        'DATA_BLOCK "DB53100_CPR_PARAM"\n'
        '    VAR RETAIN\n'
        '        { S7_MLC := "MLC_RU" }\n'
        '        PReal : Array[1.._."50100_N_MAX_PREAL"] of _.UDT_ZC_PREAL;\n'
        '    END_VAR\n'
        '    VAR\n'
        '        PReal_Vis : Array[1..2] of Bool;\n'
        '    END_VAR\n'
        '\n'
        '        { S7_MLC := "MLC_PR_001" }\n'
        '        PReal[1] := ();\n'
        '        { S7_MLC := "MLC_PR_002" }\n'
        '        PReal[2] := ();\n'
        'END_DATA_BLOCK\n'
    )
    s7res_param = (
        "MultiLingualTexts:\n"
        "  - id: MLC_PR_001\n"
        "    es-ES: TIA_PR_1\n"
        "  - id: MLC_PR_002\n"
        "    es-ES: TIA_PR_2\n"
    )
    s7dcl_alm = (
        'DATA_BLOCK "DB55100_CPR_ALM"\n'
        '    VAR RETAIN\n'
        '        { S7_MLC := "MLC_RU" }\n'
        '        ALM : Array[1.._."50100_N_MAX_ALARMAS"] of _.UDT_ZC_ALARMA;\n'
        '    END_VAR\n'
        '\n'
        '        { S7_MLC := "MLC_ALM_001" }\n'
        '        ALM[1] := ();\n'
        'END_DATA_BLOCK\n'
    )
    s7res_alm = (
        "MultiLingualTexts:\n"
        "  - id: MLC_ALM_001\n"
        "    es-ES: TIA_AL_1\n"
    )
    (work_dir / f"{db_param}.s7dcl").write_text(s7dcl_param, encoding="utf-8")
    (work_dir / f"{db_param}.s7res").write_text(s7res_param, encoding="utf-8-sig")
    (work_dir / f"{db_alm}.s7dcl").write_text(s7dcl_alm, encoding="utf-8")
    (work_dir / f"{db_alm}.s7res").write_text(s7res_alm, encoding="utf-8-sig")

    # 2. Mock del gateway: export_block escribe los archivos en
    # work_dir. En producción, TIA hace esto; aquí lo simula el mock.
    gateway = MagicMock(spec=TIAProcessGateway)

    async def fake_export(plc_name, block_name, target_dir):
        # En producción TIA escribe; aquí ya están escritos.
        return target_dir

    gateway.export_block = AsyncMock(side_effect=fake_export)

    # 3. Excel con 2 PReal (1 distinto, 1 igual) y 1 ALM (distinto).
    proc = MagicMock(uid=100, nombre="Compacto", codigo="CPR")
    ec = MagicMock()
    ec.procesos = [proc]
    ec.parametros_real = [
        MagicMock(uid="PR_1", codigo="CPR", num_db=53100, comentario_db="X"),
        MagicMock(uid="PR_2", codigo="CPR", num_db=53100, comentario_db="TIA_PR_2"),
    ]
    ec.parametros_int = []
    ec.alarmas = [
        MagicMock(uid="AL_1", proceso="Compacto", num_db=55100,
                  comentario_db="AL_NUEVO")
    ]
    state = MagicMock()
    state.excel_cache = ec

    # 4. Cache de bloques con los 3 nombres.
    bloques = BloqueCache(
        blocks={
            BloquePLC.normalize_name(db_param):
                BloquePLC(nombre=db_param, numero=0, tipo="DB", ruta=""),
            BloquePLC.normalize_name(db_alm):
                BloquePLC(nombre=db_alm, numero=0, tipo="DB", ruta=""),
        },
        tag_tables={
            BloquePLC.normalize_name("100_CPR"):
                BloquePLC(nombre="100_CPR", numero=0, tipo="TAG_TABLE", ruta=""),
        },
        plc_name="PLC_X",
    )

    # 5. Use case con work_dir en tmp_path (el preview escribe aquí).
    # Inyectamos tmp_path como build_cache_dir: el caso de uso monta
    # ``<build_cache>/procesos/<suffix>`` por debajo, por lo que el
    # preview acabará escribiendo en ``tmp_path/procesos/preview``.
    config = MagicMock(spec=ConfigManager)
    tracker = ProgressTracker()
    use_case = SyncProcesosComentariosUseCase(
        gateway=gateway,
        config_manager=config,
        app_state=state,
        progress=tracker,
        bloques_cache=bloques,
        build_cache_dir=tmp_path,
    )

    result = asyncio.run(use_case.generar_prevision(100))

    # El preview debe haber escrito los exports en
    # ``<build_cache>/procesos/preview/`` (no en ``work_dir`` directo).
    expected_work_dir = tmp_path / "procesos" / "preview"
    assert expected_work_dir.is_dir(), (
        f"El preview no creó su work_dir: {expected_work_dir}"
    )

    # 6. Verificar el diff.
    assert result["precondiciones_ok"] is True
    summary = result["summary"]
    # Esperado: 1 update (PR[1]), 1 equal (PR[2]), 1 update (AL[1]).
    # No hay new (todos los slots existen en TIA).
    assert summary["total_ops"] == 3
    assert summary["to_update"] == 2
    assert summary["to_equal"] == 1
    assert summary["to_insert"] == 0

    # Verificar el detalle por slot.
    preal = result["arrays"]["PReal"]["slot_map"]
    assert preal["1"]["current"] == "TIA_PR_1"
    assert preal["1"]["desired"] == "X"
    assert preal["1"]["action"] == "update"
    assert preal["2"]["current"] == "TIA_PR_2"
    assert preal["2"]["desired"] == "TIA_PR_2"
    assert preal["2"]["action"] == "equal"

    alm = result["arrays"]["ALM"]["slot_map"]
    assert alm["1"]["current"] == "TIA_AL_1"
    assert alm["1"]["desired"] == "AL_NUEVO"
    assert alm["1"]["action"] == "update"
