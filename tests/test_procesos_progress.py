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
from areas.alimentacion.application.use_cases.proc_sync_comentarios import (  # noqa: E402
    ProcSyncComentariosUseCase,
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
    use_case = ProcSyncComentariosUseCase(
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
    # Los 6 stages (check_state, check_blocks, build_slot_maps,
    # compute_nmax, export_and_diff, done) deben estar en DONE. El
    # export_and_diff cae en la rama de error (current=None)
    # porque el mock del gateway no escribe los .s7dcl/.s7res.
    # ``compute_nmax`` también cae en su rama degradada (current={})
    # porque el mock no escribe la tabla N_MAX.
    assert len(snap.stages) == 6
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
    # El contador de progreso debe ser 6/6.
    assert snap.current == 6
    assert snap.percent == 100


def test_generar_prevision_done_closes_when_missing_blocks() -> None:
    """Cuando los bloques están ausentes, el stage "done" también
    se cierra (con detail indicando los bloques faltantes)."""
    tracker = ProgressTracker()
    gateway = MagicMock(spec=TIAProcessGateway)
    config = MagicMock(spec=ConfigManager)
    use_case = ProcSyncComentariosUseCase(
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
    use_case = ProcSyncComentariosUseCase(
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
    use_case = ProcSyncComentariosUseCase(
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
    ProcCommentUpdater.read_current_comments.

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
    use_case = ProcSyncComentariosUseCase(
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
    # Esperado: 2 renombrar (PR[1], AL[1]) y 1 sin_cambios (PR[2]).
    # No hay agregar (todos los slots existen en TIA).
    # ``eliminados`` siempre vale 0 en este flujo (no borramos slots
    # de arrays, solo actualizamos comentarios).
    assert summary["total"] == 3
    assert summary["renombrados"] == 2
    assert summary["sin_cambios"] == 1
    assert summary["agregados"] == 0
    assert summary["eliminados"] == 0

    # Verificar el detalle por slot.
    preal = result["arrays"]["PReal"]["slot_map"]
    assert preal["1"]["current"] == "TIA_PR_1"
    assert preal["1"]["desired"] == "X"
    assert preal["1"]["action"] == "renombrar"
    assert preal["2"]["current"] == "TIA_PR_2"
    assert preal["2"]["desired"] == "TIA_PR_2"
    assert preal["2"]["action"] == "sin_cambios"

    alm = result["arrays"]["ALM"]["slot_map"]
    assert alm["1"]["current"] == "TIA_AL_1"
    assert alm["1"]["desired"] == "AL_NUEVO"
    assert alm["1"]["action"] == "renombrar"


def test_generar_prevision_incluye_nmax_block_en_response(tmp_path) -> None:
    """El preview siempre emite ``nmax`` en el response (incluso si
    el config no aporta sufijos, en cuyo caso el bloque viene con
    ``todos=[]``). Las cards SOLO VISUALES las consume la SPA; el
    apply actual NO las usa.
    """
    import asyncio
    from core.application.progress_buffer import ProgressTracker
    from core.infrastructure.gateway import TIAProcessGateway
    from core.models.bloque_cache import BloqueCache
    from core.models.bloque_plc import BloquePLC
    from unittest.mock import AsyncMock, MagicMock

    proc = MagicMock(uid=100, nombre="Compacto", codigo="CPR")
    ec = MagicMock()
    ec.procesos = [proc]
    ec.parametros_real = [
        MagicMock(uid=f"PR_{i}", codigo="CPR", num_db=53100,
                  comentario_db=f"PR {i}") for i in range(1, 6)
    ]
    ec.parametros_int = []
    ec.alarmas = [
        MagicMock(uid="AL_1", proceso="Compacto", num_db=55100,
                  comentario_db="AL 1")
    ]
    state = MagicMock(excel_cache=ec)
    bloques = BloqueCache(
        blocks={
            BloquePLC.normalize_name("DB53100_CPR_PARAM"):
                BloquePLC(nombre="DB53100_CPR_PARAM", numero=0,
                          tipo="DB", ruta=""),
            BloquePLC.normalize_name("DB55100_CPR_ALM"):
                BloquePLC(nombre="DB55100_CPR_ALM", numero=0,
                          tipo="DB", ruta=""),
        },
        tag_tables={
            BloquePLC.normalize_name("100_CPR"):
                BloquePLC(nombre="100_CPR", numero=0, tipo="TAG_TABLE",
                          ruta=""),
        },
        plc_name="PLC_X",
    )

    gateway = MagicMock(spec=TIAProcessGateway)
    # ``export_block`` y ``export_plc_tags_xml`` no escriben nada;
    # caen en la rama degradada (current=None / current={}).
    gateway.export_block = AsyncMock()
    gateway.export_plc_tags_xml = AsyncMock()

    config = MagicMock()
    # El config retorna {} (sin sufijos); el builder no computa nmax.
    config.get_proc_nmax_suffixes = MagicMock(return_value={})
    # ``get_tia_folder_nmax`` y ``get_global_config_table_name`` se
    # usan dentro de ``_compute_nmax_diff``, pero como ``nmax_names``
    # está vacío, el método retorna early sin tocar el gateway.
    config.get_tia_folder_nmax = MagicMock(return_value="000_Sistema")
    config.get_global_config_table_name = MagicMock(
        return_value="000_Config_Dispositivos"
    )

    tracker = ProgressTracker()
    use_case = ProcSyncComentariosUseCase(
        gateway=gateway,
        config_manager=config,
        app_state=state,
        progress=tracker,
        bloques_cache=bloques,
        build_cache_dir=tmp_path,
    )
    result = asyncio.run(use_case.generar_prevision(100))
    # El bloque ``nmax`` está presente en el response (puede ser
    # vacío si no hay config, pero debe existir).
    assert "nmax" in result
    assert result["nmax"]["todos"] == []
    assert result["nmax"]["summary"] == {
        "actualizar": 0, "sin_cambios": 0, "total": 0,
    }
    # El stage ``compute_nmax`` se ejecutó.
    snap = tracker.snapshot()
    nmax_stage = next(
        s for s in snap.stages if s["id"] == "compute_nmax"
    )
    assert nmax_stage["status"] == "done"


def test_generar_prevision_nmax_block_con_sufijos_usa_gateway(tmp_path) -> None:
    """Con sufijos en el config, el use case llama
    ``gateway.export_plc_tags_xml`` para la tabla N_MAX y emite
    un bloque con ``todos`` no vacío.
    """
    import asyncio
    from core.application.progress_buffer import ProgressTracker
    from core.infrastructure.gateway import TIAProcessGateway
    from core.models.bloque_cache import BloqueCache
    from core.models.bloque_plc import BloquePLC
    from unittest.mock import AsyncMock, MagicMock

    proc = MagicMock(uid=100, nombre="Compacto", codigo="CPR")
    ec = MagicMock()
    ec.procesos = [proc]
    ec.parametros_real = [
        MagicMock(uid="PR_1", codigo="CPR", num_db=53100,
                  comentario_db="PR 1")
    ]
    ec.parametros_int = []
    ec.alarmas = [
        MagicMock(uid="AL_1", proceso="Compacto", num_db=55100,
                  comentario_db="AL 1")
    ]
    state = MagicMock(excel_cache=ec)
    bloques = BloqueCache(
        blocks={
            BloquePLC.normalize_name("DB53100_CPR_PARAM"):
                BloquePLC(nombre="DB53100_CPR_PARAM", numero=0,
                          tipo="DB", ruta=""),
            BloquePLC.normalize_name("DB55100_CPR_ALM"):
                BloquePLC(nombre="DB55100_CPR_ALM", numero=0,
                          tipo="DB", ruta=""),
        },
        tag_tables={
            BloquePLC.normalize_name("100_CPR"):
                BloquePLC(nombre="100_CPR", numero=0, tipo="TAG_TABLE",
                          ruta=""),
        },
        plc_name="PLC_X",
    )

    gateway = MagicMock(spec=TIAProcessGateway)
    gateway.export_block = AsyncMock()
    # El export de la tabla N_MAX no escribe nada → ``current={}``,
    # todos los N_MAX se marcan como ``actualizar`` (current=None).
    gateway.export_plc_tags_xml = AsyncMock()

    config = MagicMock()
    config.get_proc_nmax_suffixes = MagicMock(
        return_value={"preal": "PREAL", "pint": "PINT", "alm": "ALM"}
    )
    config.get_tia_folder_nmax = MagicMock(return_value="000_Sistema")
    config.get_global_config_table_name = MagicMock(
        return_value="000_Config_Dispositivos"
    )

    tracker = ProgressTracker()
    use_case = ProcSyncComentariosUseCase(
        gateway=gateway,
        config_manager=config,
        app_state=state,
        progress=tracker,
        bloques_cache=bloques,
        build_cache_dir=tmp_path,
    )
    result = asyncio.run(use_case.generar_prevision(100))

    # El bloque ``nmax`` tiene 3 entries (PReal, PInt, ALM).
    nmax = result["nmax"]
    assert nmax["summary"]["total"] == 3
    assert len(nmax["todos"]) == 3
    kinds = {r["kind"] for r in nmax["todos"]}
    assert kinds == {"preal", "pint", "alm"}
    # Los nombres siguen la convención ``f"{uid}_N_MAX_{suffix}"``.
    names = {r["name"] for r in nmax["todos"]}
    assert names == {
        "100_N_MAX_PREAL", "100_N_MAX_PINT", "100_N_MAX_ALM",
    }
    # Como ``current={}`` (export degradado), todos los N_MAX se
    # marcan como ``actualizar`` (current=None vs desired).
    assert nmax["summary"]["actualizar"] == 3
    assert nmax["summary"]["sin_cambios"] == 0
    # El gateway fue llamado con la tabla del proceso
    # (``<uid>_<codigo>``, p. ej. ``100_CPR``), no con la tabla
    # ``000_Config_Dispositivos`` de dispositivos.
    gateway.export_plc_tags_xml.assert_called_once()
    call_kwargs = gateway.export_plc_tags_xml.call_args.kwargs
    assert call_kwargs["table_names"] == ["100_CPR"]


def test_generar_prevision_no_pisa_tracker_con_otra_operacion_activa(
    tmp_path,
) -> None:
    """Si el ``ProgressTracker`` está activo con otra operación
    (p. ej. un escaneo de bloques ``scan_plc_blocks::ZC_PLC_STD``),
    el ``generar_prevision`` NO debe hacer ``begin()`` ni emitir
    stages propios (que fallarían con ``ValueError`` porque el
    stage_id no está declarado en el ``begin()`` del otro caller).
    Patrón análogo a ``sync_dispositivos_instances``.
    """
    import asyncio
    from core.application.progress_buffer import ProgressTracker
    from core.infrastructure.gateway import TIAProcessGateway
    from core.models.bloque_cache import BloqueCache
    from core.models.bloque_plc import BloquePLC
    from unittest.mock import AsyncMock, MagicMock

    # Tracker YA activo con otra operación.
    tracker = ProgressTracker()
    tracker.begin(
        operation="scan_plc_blocks::ZC_PLC_STD",
        label="Escaneando bloques del PLC",
        stages=["scan_blocks"],
    )
    tracker.start_stage("scan_blocks", "Leyendo .ap*")
    assert tracker.active is True

    # El use case se construye con este tracker (que ya está activo).
    proc = MagicMock(uid=100, nombre="Compacto", codigo="CPR")
    ec = MagicMock()
    ec.procesos = [proc]
    ec.parametros_real = [
        MagicMock(uid="PR_1", codigo="CPR", num_db=53100,
                  comentario_db="PR 1")
    ]
    ec.parametros_int = []
    ec.alarmas = []
    state = MagicMock(excel_cache=ec)
    bloques = BloqueCache(
        blocks={
            BloquePLC.normalize_name("DB53100_CPR_PARAM"):
                BloquePLC(nombre="DB53100_CPR_PARAM", numero=0,
                          tipo="DB", ruta=""),
        },
        tag_tables={},
        plc_name="PLC_X",
    )

    gateway = MagicMock(spec=TIAProcessGateway)
    gateway.export_block = AsyncMock()
    gateway.export_plc_tags_xml = AsyncMock()
    config = MagicMock()
    config.get_proc_nmax_suffixes = MagicMock(return_value={})
    config.get_tia_folder_nmax = MagicMock(return_value="000_Sistema")
    config.get_global_config_table_name = MagicMock(
        return_value="000_Config_Dispositivos"
    )

    use_case = ProcSyncComentariosUseCase(
        gateway=gateway,
        config_manager=config,
        app_state=state,
        progress=tracker,
        bloques_cache=bloques,
        build_cache_dir=tmp_path,
    )
    asyncio.run(use_case.generar_prevision(100))

    # La operación activa sigue siendo la del escaneo (``scan_blocks``).
    # Si el ``generar_prevision`` hubiera hecho ``begin()`` o emitido
    # ``start_stage("done")``, esto habría fallado con ``ValueError``.
    snap = tracker.snapshot()
    assert snap.operation == "scan_plc_blocks::ZC_PLC_STD"
    assert snap.stages[0]["id"] == "scan_blocks"


def test_generar_prevision_slots_tia_no_excel_aparecen_como_eliminar(
    tmp_path,
) -> None:
    """Slots que están en TIA pero NO en el Excel del proceso
    aparecen en la tabla del preview con ``action="eliminar"`` y
    ``desired=None``. Caso real: el DB tiene 60 slots, el Excel
    solo trae 20 → el operario ve los 40 restantes listados como
    "ELIMINAR" (análogo a dispositivos).
    """
    import asyncio
    from core.application.progress_buffer import ProgressTracker
    from core.infrastructure.gateway import TIAProcessGateway
    from core.models.bloque_cache import BloqueCache
    from core.models.bloque_plc import BloquePLC
    from unittest.mock import AsyncMock, MagicMock

    db_param = "DB53100_CPR_PARAM"
    db_alm = "DB55100_CPR_ALM"
    # El Excel solo tiene 2 PReal.
    proc = MagicMock(uid=100, nombre="Compacto", codigo="CPR")
    ec = MagicMock()
    ec.procesos = [proc]
    ec.parametros_real = [
        MagicMock(uid="PR_1", codigo="CPR", num_db=53100,
                  comentario_db="PR 1"),
        MagicMock(uid="PR_2", codigo="CPR", num_db=53100,
                  comentario_db="PR 2"),
    ]
    ec.parametros_int = []
    ec.alarmas = []  # El test solo cubre PReal.
    state = MagicMock(excel_cache=ec)
    bloques = BloqueCache(
        blocks={
            BloquePLC.normalize_name(db_param):
                BloquePLC(nombre=db_param, numero=0, tipo="DB", ruta=""),
            # El test no cubre alarmas, pero el builder necesita que
            # el DB de alarmas exista en el cache. Con ``ec.alarmas=[]``
            # cae al fallback ``DB<proc.uid>_CPR_ALM`` (``DB100_CPR_ALM``).
            BloquePLC.normalize_name("DB100_CPR_ALM"):
                BloquePLC(nombre="DB100_CPR_ALM", numero=0, tipo="DB", ruta=""),
        },
        tag_tables={
            BloquePLC.normalize_name("100_CPR"):
                BloquePLC(nombre="100_CPR", numero=0, tipo="TAG_TABLE",
                          ruta=""),
        },
        plc_name="PLC_X",
    )

    # TIA tiene 5 PReal: slot 1 y 2 (los del Excel) + slot 3, 4, 5
    # (NO en el Excel → "eliminar"). El slot 6 también existe pero
    # con comentario vacío ("" → "sin_cambios", no molestar).
    fake_current_preal = {
        1: "TIA_PR_1", 2: "TIA_PR_2",
        3: "TIA_PR_3", 4: "TIA_PR_4", 5: "TIA_PR_5",
        6: "",
    }

    # Escribimos los .s7dcl/.s7res en el work_dir para que el
    # ``read_current_comments`` los pueda leer.
    work_dir = tmp_path / "procesos" / "preview"
    work_dir.mkdir(parents=True)
    s7dcl = (
        'DATA_BLOCK "DB53100_CPR_PARAM"\n'
        '    VAR RETAIN\n'
        '        { S7_MLC := "MLC_RU" }\n'
        '        PReal : Array[1.._."50100_N_MAX_PREAL"] of _.UDT_ZC_PREAL;\n'
        '    END_VAR\n'
        '\n'
        '        { S7_MLC := "MLC_PR_001" }\n'
        '        PReal[1] := ();\n'
        '        { S7_MLC := "MLC_PR_002" }\n'
        '        PReal[2] := ();\n'
        '        { S7_MLC := "MLC_PR_003" }\n'
        '        PReal[3] := ();\n'
        '        { S7_MLC := "MLC_PR_004" }\n'
        '        PReal[4] := ();\n'
        '        { S7_MLC := "MLC_PR_005" }\n'
        '        PReal[5] := ();\n'
        '        { S7_MLC := "MLC_PR_006" }\n'
        '        PReal[6] := ();\n'
    )
    s7res = (
        "MultiLingualTexts:\n"
        "  - id: MLC_PR_001\n"
        "    es-ES: TIA_PR_1\n"
        "  - id: MLC_PR_002\n"
        "    es-ES: TIA_PR_2\n"
        "  - id: MLC_PR_003\n"
        "    es-ES: TIA_PR_3\n"
        "  - id: MLC_PR_004\n"
        "    es-ES: TIA_PR_4\n"
        "  - id: MLC_PR_005\n"
        "    es-ES: TIA_PR_5\n"
        "  - id: MLC_PR_006\n"
        "    es-ES: ''\n"
    )
    (work_dir / f"{db_param}.s7dcl").write_text(s7dcl, encoding="utf-8")
    (work_dir / f"{db_param}.s7res").write_text(s7res, encoding="utf-8-sig")
    # El DB ALM no tiene alarmas del Excel. Como ``ec.alarmas=[]``,
    # el builder hace fallback a ``db_alm_name = "DB<proc.uid>_CPR_ALM"``
    # (``DB100_CPR_ALM``). El use case lo lee igualmente en
    # ``_export_and_read_current``; lo pre-escribimos vacío para que
    # el read no falle.
    db_alm_resolved = "DB100_CPR_ALM"
    (work_dir / f"{db_alm_resolved}.s7dcl").write_text(
        f'DATA_BLOCK "{db_alm_resolved}"\n    END_DATA_BLOCK\n',
        encoding="utf-8",
    )
    (work_dir / f"{db_alm_resolved}.s7res").write_text(
        "MultiLingualTexts:\n", encoding="utf-8-sig"
    )

    gateway = MagicMock(spec=TIAProcessGateway)

    async def fake_export_block(plc_name, block_name, target_dir):
        # El mock "exporta" los archivos que ya escribimos arriba.
        return target_dir

    gateway.export_block = AsyncMock(side_effect=fake_export_block)
    gateway.export_plc_tags_xml = AsyncMock()

    config = MagicMock()
    config.get_proc_nmax_suffixes = MagicMock(return_value={})
    config.get_tia_folder_nmax = MagicMock(return_value="000_Sistema")
    config.get_global_config_table_name = MagicMock(
        return_value="000_Config_Dispositivos"
    )
    config.get_tia_folder_proceso = MagicMock(return_value="003_Procesos")

    tracker = ProgressTracker()
    use_case = ProcSyncComentariosUseCase(
        gateway=gateway,
        config_manager=config,
        app_state=state,
        progress=tracker,
        bloques_cache=bloques,
        build_cache_dir=tmp_path,
    )
    result = asyncio.run(use_case.generar_prevision(100))

    preal = result["arrays"]["PReal"]["slot_map"]
    # Slots 1 y 2: del Excel, se comparan contra current.
    assert preal["1"]["action"] in ("renombrar", "sin_cambios")
    assert preal["1"]["current"] == "TIA_PR_1"
    assert preal["1"]["desired"] == "PR 1"
    assert preal["2"]["action"] in ("renombrar", "sin_cambios")
    # Slots 3, 4, 5: "eliminar" (en TIA, no en Excel, current con texto).
    for slot in (3, 4, 5):
        assert preal[str(slot)]["action"] == "eliminar", (
            f"slot {slot} esperaba 'eliminar', recibí "
            f"{preal[str(slot)]['action']!r}"
        )
        assert preal[str(slot)]["current"] == f"TIA_PR_{slot}"
        assert preal[str(slot)]["desired"] is None
    # Slot 6: en TIA con current="" → "sin_cambios" (no molestar).
    assert preal["6"]["action"] == "sin_cambios"

    # El summary cuenta los eliminados.
    summary = result["summary"]
    assert summary["eliminados"] == 3  # slots 3, 4, 5
    assert summary["total"] == 6  # 2 del Excel + 3 eliminar + 1 sin_cambios


def test_generar_prevision_closes_tracker_when_missing_blocks(tmp_path) -> None:
    """Cuando el proceso no existe en el PLC (``missing_blocks``
    poblado), el use case debe cerrar el ``ProgressTracker``
    (``active=False``) para que la SPA no muestre "En curso"
    indefinidamente. Antes del fix, la rama de ``missing_blocks``
    saltaba directamente al stage "done" sin pasar por
    "export_and_diff" ni llamar a ``finish(success=True)``.
    Caso real reportado por el operario el 2026-09-02: el
    progress bar se quedaba en 5/6 con el stage 5 (export_and_diff)
    en PENDING.
    """
    from core.application.progress_buffer import (
        ProgressTracker,
        STAGE_DONE,
    )
    from core.infrastructure.gateway import TIAProcessGateway
    from core.models.bloque_cache import BloqueCache
    from core.models.bloque_plc import BloquePLC
    from unittest.mock import MagicMock

    # Tracker LIMPIO (no activo). El use case va a ser el dueño
    # del tracker durante toda la operación.
    tracker = ProgressTracker()
    assert tracker.active is False

    # El proceso 1 NO existe en el PLC: el BloqueCache solo tiene
    # bloques del proceso 100, no del 1. ``proc_build_slot_maps``
    # lo detectará y poblará ``missing_blocks``.
    proc = MagicMock(uid=1, nombre="Genérico", codigo="GNR")
    ec = MagicMock()
    ec.procesos = [proc]
    ec.parametros_real = [
        MagicMock(uid="PR_1", codigo="GNR", num_db=3001,
                  comentario_db="X")
    ]
    ec.parametros_int = []
    ec.alarmas = [
        MagicMock(uid="AL_1", proceso="Genérico", num_db=5001,
                  comentario_db="Y")
    ]
    state = MagicMock(excel_cache=ec)
    # BloqueCache del proceso 100 (NO del 1 que estamos consultando).
    bloques = BloqueCache(
        blocks={
            BloquePLC.normalize_name("DB53100_CPR_PARAM"):
                BloquePLC(nombre="DB53100_CPR_PARAM", numero=0,
                          tipo="DB", ruta=""),
        },
        tag_tables={
            BloquePLC.normalize_name("100_CPR"):
                BloquePLC(nombre="100_CPR", numero=0, tipo="TAG_TABLE",
                          ruta=""),
        },
        plc_name="PLC_X",
    )

    gateway = MagicMock(spec=TIAProcessGateway)
    config = MagicMock()
    config.get_proc_nmax_suffixes = MagicMock(return_value={})
    config.get_tia_folder_nmax = MagicMock(return_value="000_Sistema")
    config.get_global_config_table_name = MagicMock(
        return_value="000_Config_Dispositivos"
    )

    use_case = ProcSyncComentariosUseCase(
        gateway=gateway,
        config_manager=config,
        app_state=state,
        progress=tracker,
        bloques_cache=bloques,
        build_cache_dir=tmp_path,
    )
    import asyncio
    result = asyncio.run(use_case.generar_prevision(1))

    # El use case retornó con precondiciones_ok=False.
    assert result["precondiciones_ok"] is False
    assert len(result["missing_blocks"]) == 3  # DB_PARAM + DB_ALM + tabla

    # El tracker se cerró (``active=False``). Antes del fix, esto
    # era True y la SPA mostraba "En curso" indefinidamente.
    assert tracker.active is False, (
        "El tracker no se cerró tras missing_blocks; la SPA se queda "
        f"en 'En curso'. Snapshot: {tracker.snapshot()}"
    )
    # Los 6 stages están en DONE (incluido ``export_and_diff``
    # marcado como "Saltado").
    snap = tracker.snapshot()
    assert len(snap.stages) == 6, f"Stages: {snap.stages}"
    assert all(s["status"] == STAGE_DONE for s in snap.stages), (
        f"Todos los stages deben estar en DONE. Actual: "
        f"{[(s['id'], s['status']) for s in snap.stages]}"
    )
    # El stage ``export_and_diff`` está marcado como saltado.
    export_stage = next(
        s for s in snap.stages if s["id"] == "export_and_diff"
    )
    assert "Saltado" in (export_stage["detail"] or ""), (
        f"export_and_diff debe tener detail 'Saltado...': {export_stage}"
    )
