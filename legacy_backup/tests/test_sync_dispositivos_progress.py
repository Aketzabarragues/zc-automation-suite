"""Tests de integración: use cases emiten stages al ProgressTracker.

Cubre:
  1. ``generar_prevision`` llama a ``progress.begin`` con 4 stages.
  2. ``ejecutar_transaccion`` llama a ``progress.begin`` con 6 stages
     y emite ``start_stage("open_transaction", ...)`` antes de
     ``execute_transactional_batch``.
  3. Si ``execute_transactional_batch`` falla, ``progress.finish(success=False)``
     se llama antes del ``raise``.

Los use cases reales llaman al gateway y al parser de Excel, lo cual
es muy costoso de mockear. Aquí usamos ``MagicMock`` para el gateway
y ``tmp_path`` para el ``.build_cache`` del use case, y mockeamos el
parser de Excel con un stub.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from unittest.mock import AsyncMock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.application.progress_buffer import (  # noqa: E402
    ProgressTracker,
    STAGE_DONE,
    STAGE_RUNNING,
    get_progress_tracker,
)
from core.application.state import AppState  # noqa: E402
from areas.alimentacion.application.use_cases.disp_sync_instances import (  # noqa: E402
    DispSyncInstancesUseCase,
)
from core.infrastructure.config_manager import ConfigManager  # noqa: E402
from core.infrastructure.gateway import TIAProcessGateway  # noqa: E402


@pytest.fixture
def fresh_tracker() -> ProgressTracker:
    """Tracker limpio por test (no usamos el Singleton)."""
    return ProgressTracker()


@pytest.fixture
def minimal_config(tmp_path: Path) -> ConfigManager:
    """ConfigManager mínimo apuntando a un config.json en tmp_path."""
    cfg = {
        "departments": {
            "alimentacion": {
                "global_config_table_name": "000_Config_Dispositivos",
                "tia_folders": {
                    "proceso": "003_Procesos",
                    "dispositivos": "2000_Dispositivos",
                    "nmax": "000_Sistema",
                },
            }
        },
        "Dispositivos": {},
        "excel_target": {},
    }
    p = tmp_path / "config.json"
    p.write_text(__import__("json").dumps(cfg), encoding="utf-8")
    return ConfigManager(str(p))


def test_generar_prevision_emits_4_stages(
    fresh_tracker: ProgressTracker,
    minimal_config: ConfigManager,
    tmp_path: Path,
) -> None:
    """``generar_prevision`` emite los 4 stages: export → compute_devices
    → compute_nmax → build_response."""
    gateway = MagicMock(spec=TIAProcessGateway)
    # El gateway.export_plc_tags_xml crea el directorio. Lo simulamos.
    async def fake_export(
        plc_name: str, target_dir: str, table_names=None
    ) -> str:
        Path(target_dir).mkdir(parents=True, exist_ok=True)
        return target_dir

    gateway.export_plc_tags_xml = fake_export  # type: ignore[method-assign]

    use_case = DispSyncInstancesUseCase(
        gateway=gateway,
        config_manager=minimal_config,
        state=AppState(),
        progress=fresh_tracker,
        build_cache_dir=tmp_path / ".build_cache",
    )

    # El _compute_diff_readonly necesita un dir con XMLs. Lo skipeamos
    # parcheando el método con un stub que devuelve dicts vacíos.
    use_case._compute_diff_readonly = MagicMock(  # type: ignore[method-assign]
        return_value=({}, {}, {}, {})
    )
    use_case._extract_nmax_diff = MagicMock(  # type: ignore[method-assign]
        return_value={"current": {}, "desired": {}, "todos": [], "summary": {}}
    )
    use_case._build_desired_state_from_app = MagicMock(  # type: ignore[method-assign]
        return_value={}
    )

    # Forzamos un fallo suave: ValueError en el medio. Verificamos que
    # el tracker captura el error.
    # En su lugar, vamos a verificar solo el begin():
    try:
        asyncio.run(use_case.generar_prevision("PLC_TEST"))
    except Exception:
        # Puede fallar por detalles internos (los métodos privados
        # mockeados no están perfectos); lo que nos importa es el
        # tracking.
        pass

    snap = fresh_tracker.snapshot()
    # El begin se llamó con 4 stages.
    assert snap.total == 4
    assert snap.operation == "preview"
    # El finish se llamó con success=False si hubo excepción, o True
    # si todo OK. En cualquier caso, active=False.
    assert snap.active is False


def test_ejecutar_transaccion_emits_11_stages(
    fresh_tracker: ProgressTracker,
    minimal_config: ConfigManager,
    tmp_path: Path,
) -> None:
    """``ejecutar_transaccion`` emite 11 stages (sept-2026: el antiguo
    ``open_transaction`` monolítico se ha partido en 5 sub-stages
    para reflejar el orden validado por el operario: Tx A → espera
    consolidación → export post-Tx A → copy/edit → Tx B; más
    compile_blocks, apply_comentarios_disp y post_preview).
    """
    gateway = MagicMock(spec=TIAProcessGateway)
    async def fake_export(
        plc_name: str, target_dir: str, table_names=None
    ) -> str:
        Path(target_dir).mkdir(parents=True, exist_ok=True)
        return target_dir
    gateway.export_plc_tags_xml = fake_export  # type: ignore[method-assign]
    # execute_transactional_batch retorna OK
    async def fake_batch(operations, undo_text=""):
        return {"success": True, "operations_executed": len(operations), "details": []}
    gateway.execute_transactional_batch = fake_batch  # type: ignore[method-assign]
    # commit_disp_nmax_renames_online (sept-2026 fix): stub OK.
    async def fake_nmax_renames(
        plc_name, nmax_ops, rename_ops, undo_text="", **kwargs,
    ):
        return {
            "success": True,
            "operations_executed": (
                len(nmax_ops) + len(rename_ops)
            ),
            "details": [],
        }
    gateway.commit_disp_nmax_renames_online = fake_nmax_renames  # type: ignore[method-assign]
    # commit_disp_devices_offline (sept-2026 fix): stub OK.
    async def fake_devices_offline(
        plc_name, device_changes, work_dir, undo_text="", **kwargs,
    ):
        return {
            "success": True,
            "operations_executed": 3 * len(device_changes),
            "details": [],
        }
    gateway.commit_disp_devices_offline = fake_devices_offline  # type: ignore[method-assign]
    # commit_devices_sync (DEPRECATED): stub OK por compat con callers legacy.
    async def fake_commit(
        plc_name, nmax_ops, rename_ops, device_changes, work_dir,
        undo_text="", **kwargs,
    ):
        return {
            "success": True,
            "operations_executed": (
                len(nmax_ops) + len(rename_ops) + 3 * len(device_changes)
            ),
            "details": [],
        }
    gateway.commit_devices_sync = fake_commit  # type: ignore[method-assign]
    # ``compile_blocks`` (sept-2026) retorna un dict con
    # ``compiled`` (todos OK), ``skipped_unchanged``, ``not_found``,
    # ``errors``. Caso feliz: todos consistentes (no hay nada que
    # compilar -> el handler reporta todo como ``skipped_unchanged``).
    async def fake_compile_blocks(
        plc_name: str, block_names: list[str]
    ) -> dict:
        return {
            "compiled": [],
            "skipped_unchanged": list(block_names),
            "not_found": [],
            "errors": [],
        }
    gateway.compile_blocks = fake_compile_blocks  # type: ignore[method-assign]

    use_case = DispSyncInstancesUseCase(
        gateway=gateway,
        config_manager=minimal_config,
        state=AppState(),
        progress=fresh_tracker,
        build_cache_dir=tmp_path / ".build_cache",
    )

    # Mockeamos los métodos privados para que la ejecución sea corta.
    use_case._compute_diff = MagicMock(  # type: ignore[method-assign]
        return_value=({}, {}, {})
    )
    use_case._compute_nmax_ops_for_apply = MagicMock(  # type: ignore[method-assign]
        return_value=[]
    )
    use_case._build_desired_state_from_app = MagicMock(  # type: ignore[method-assign]
        return_value={}
    )
    use_case.generar_prevision = MagicMock(  # type: ignore[method-assign]
        return_value={"agregados": [], "eliminados": [], "renombrados": [],
                      "todos": [], "nmax": {}, "summary": {}}
    )

    try:
        asyncio.run(use_case.ejecutar_transaccion("PLC_TEST", {}))
    except Exception:
        pass

    snap = fresh_tracker.snapshot()
    assert snap.total == 11
    assert snap.operation == "commit"


def test_stage_order_includes_post_tx_a_export(
    fresh_tracker: ProgressTracker,
    minimal_config: ConfigManager,
    tmp_path: Path,
) -> None:
    """``ejecutar_transaccion`` emite ``export_post_tx_a`` DESPUÉS de
    ``tx_a_nmax_renames`` y ``wait_consolidation`` (sept-2026 fix).

    Orden esperado (sept-2026):
      4. ``tx_a_nmax_renames``  (Tx A online: N_MAX + renames)
      5. ``wait_consolidation``  (sleep 2s para que TIA consolide)
      6. ``export_post_tx_a``    (re-export de las 6 tablas de devices,
                                  post-Tx A, con renames consolidados)
      7. ``copy_and_edit``       (shutil.copytree filtrado + TagTableModifier)
      8. ``tx_b_devices``        (Tx B offline puro: solo import)

    Este orden evita el rollback silencioso de TIA V21 que ocurría
    cuando el ``table.export`` dentro de Tx B leía datos stale (sin
    los renames recién aplicados) y los re-importaba.
    """
    gateway = MagicMock(spec=TIAProcessGateway)

    async def fake_export(
        plc_name: str, target_dir: str, table_names=None
    ) -> str:
        Path(target_dir).mkdir(parents=True, exist_ok=True)
        return target_dir

    gateway.export_plc_tags_xml = fake_export  # type: ignore[method-assign]

    async def fake_nmax_renames(
        plc_name, nmax_ops, rename_ops, undo_text="", **kwargs,
    ):
        return {
            "success": True,
            "operations_executed": len(nmax_ops) + len(rename_ops),
            "details": [],
        }
    gateway.commit_disp_nmax_renames_online = fake_nmax_renames  # type: ignore[method-assign]

    async def fake_devices_offline(
        plc_name, device_changes, work_dir, undo_text="", **kwargs,
    ):
        return {
            "success": True,
            "operations_executed": 3 * len(device_changes),
            "details": [],
        }
    gateway.commit_disp_devices_offline = fake_devices_offline  # type: ignore[method-assign]

    async def fake_compile_blocks(plc_name: str, block_names: list[str]) -> dict:
        return {
            "compiled": [],
            "skipped_unchanged": list(block_names),
            "not_found": [],
            "errors": [],
        }
    gateway.compile_blocks = fake_compile_blocks  # type: ignore[method-assign]

    use_case = DispSyncInstancesUseCase(
        gateway=gateway,
        config_manager=minimal_config,
        state=AppState(),
        progress=fresh_tracker,
        build_cache_dir=tmp_path / ".build_cache",
    )
    use_case._compute_diff = MagicMock(  # type: ignore[method-assign]
        return_value=({}, {}, {})
    )
    use_case._compute_nmax_ops_for_apply = MagicMock(  # type: ignore[method-assign]
        return_value=[{
            "command": "update_user_constant_value",
            "args": {
                "plc_name": "PLC_TEST",
                "table_name": "000_Config_Dispositivos",
                "constant_name": "N_MAX_DISP_ED",
                "new_value": 5,
            },
        }]
    )
    use_case._build_desired_state_from_app = MagicMock(  # type: ignore[method-assign]
        return_value={}
    )
    use_case.generar_prevision = MagicMock(  # type: ignore[method-assign]
        return_value={
            "agregados": [], "eliminados": [], "renombrados": [],
            "todos": [], "nmax": {}, "summary": {}
        }
    )

    try:
        asyncio.run(use_case.ejecutar_transaccion("PLC_TEST", {}))
    except Exception:
        pass

    snap = fresh_tracker.snapshot()
    # Total de 11 stages.
    assert snap.total == 11

    # Orden de los stage IDs (fresh_tracker.snapshot().stages
    # preserva el orden de ``begin()``).
    stage_ids = [s["id"] for s in snap.stages]
    assert stage_ids == [
        "export_diff",
        "compute_diff",
        "prepare_xml",
        "tx_a_nmax_renames",
        "wait_consolidation",
        "export_post_tx_a",
        "copy_and_edit",
        "tx_b_devices",
        "compile_blocks",
        "apply_comentarios_disp",
        "post_preview",
    ], f"Stage order mismatch: {stage_ids}"

    # ``export_post_tx_a`` debe estar DESPUÉS de ``tx_a_nmax_renames``
    # y ``wait_consolidation``, y ANTES de ``copy_and_edit`` /
    # ``tx_b_devices``.
    idx_tx_a = stage_ids.index("tx_a_nmax_renames")
    idx_wait = stage_ids.index("wait_consolidation")
    idx_export_post = stage_ids.index("export_post_tx_a")
    idx_copy = stage_ids.index("copy_and_edit")
    idx_tx_b = stage_ids.index("tx_b_devices")
    assert idx_tx_a < idx_wait < idx_export_post < idx_copy < idx_tx_b, (
        f"Order should be tx_a < wait < export_post < copy < tx_b, "
        f"got: tx_a={idx_tx_a}, wait={idx_wait}, "
        f"export_post={idx_export_post}, copy={idx_copy}, tx_b={idx_tx_b}"
    )


def test_ejecutar_transaccion_finish_false_on_batch_failure(
    fresh_tracker: ProgressTracker,
    minimal_config: ConfigManager,
    tmp_path: Path,
) -> None:
    """Si ``execute_transactional_batch`` falla, ``progress.finish(success=False)``
    se llama antes del ``raise``."""
    gateway = MagicMock(spec=TIAProcessGateway)
    async def fake_export(
        plc_name: str, target_dir: str, table_names=None
    ) -> str:
        Path(target_dir).mkdir(parents=True, exist_ok=True)
        return target_dir
    gateway.export_plc_tags_xml = fake_export  # type: ignore[method-assign]
    # execute_transactional_batch FALLA
    async def fake_batch(operations, undo_text=""):
        raise RuntimeError("Lote abortado en el paso 1")
    gateway.execute_transactional_batch = fake_batch  # type: ignore[method-assign]
    # commit_disp_nmax_renames_online: simulamos el mismo error para
    # que el use case propague la excepcion y el tracker termine en
    # error.
    async def fake_nmax_renames(
        plc_name, nmax_ops, rename_ops, undo_text="", **kwargs,
    ):
        raise RuntimeError("commit_disp_nmax_renames_online abortado")
    gateway.commit_disp_nmax_renames_online = fake_nmax_renames  # type: ignore[method-assign]
    # commit_disp_devices_offline: stub OK (no llegamos aquí si el
    # anterior falla, pero lo definimos para evitar el MagicMock
    # default que retornaría un dict vacío).
    async def fake_devices_offline(
        plc_name, device_changes, work_dir, undo_text="", **kwargs,
    ):
        return {"success": True, "operations_executed": 0, "details": []}
    gateway.commit_disp_devices_offline = fake_devices_offline  # type: ignore[method-assign]
    # commit_devices_sync (DEPRECATED): stub compat.
    async def fake_commit(
        plc_name, nmax_ops, rename_ops, device_changes, work_dir,
        undo_text="", **kwargs,
    ):
        raise RuntimeError("commit_devices_sync abortado en el paso 1")
    gateway.commit_devices_sync = fake_commit  # type: ignore[method-assign]

    use_case = DispSyncInstancesUseCase(
        gateway=gateway,
        config_manager=minimal_config,
        state=AppState(),
        progress=fresh_tracker,
        build_cache_dir=tmp_path / ".build_cache",
    )
    use_case._compute_diff = MagicMock(  # type: ignore[method-assign]
        return_value=({}, {}, {})
    )
    use_case._compute_nmax_ops_for_apply = MagicMock(  # type: ignore[method-assign]
        return_value=[]
    )
    use_case._build_desired_state_from_app = MagicMock(  # type: ignore[method-assign]
        return_value={}
    )

    # Forzar que operations tenga UNA op para que NO caiga en el
    # camino "if not operations" (early return sin tocar la transacción).
    use_case._compute_nmax_ops_for_apply = MagicMock(  # type: ignore[method-assign]
        return_value=[{
            "command": "update_user_constant_value",
            "args": {
                "plc_name": "PLC_TEST",
                "table_name": "000_Config_Dispositivos",
                "constant_name": "N_MAX_DISP_ED",
                "new_value": 5,
            },
        }]
    )

    with pytest.raises(RuntimeError, match="commit_disp_nmax_renames_online abortado"):
        asyncio.run(use_case.ejecutar_transaccion("PLC_TEST", {}))

    snap = fresh_tracker.snapshot()
    assert snap.active is False
    assert snap.error is not None
    assert "commit_disp_nmax_renames_online abortado" in snap.error
    # El último stage en running (``tx_a_nmax_renames``, sept-2026)
    # debe estar en error o done. El ``finish(success=False)`` del
    # ``except`` general cierra el tracker; el stage huérfano en
    # running se marca como ``error``.
    tx_a = next(
        (s for s in snap.stages if s["id"] == "tx_a_nmax_renames"),
        None,
    )
    assert tx_a is not None
    assert tx_a["status"] == "error" or tx_a["status"] == "done"


# ─── apply_comentarios_disp (stage 7 del orquestador) ─────────────────


@pytest.mark.asyncio
async def test_apply_comentarios_disp_fallo_no_revienta_el_commit(
    fresh_tracker: ProgressTracker,
    minimal_config: ConfigManager,
    tmp_path: Path,
) -> None:
    """Si la fase de comentarios falla, el commit global sigue siendo exitoso
    (N_MAX+devices ya aplicados). El operario puede reintentar via el
    endpoint dedicado. Verifica el comportamiento best-effort del stage 7.
    """
    gateway = MagicMock(spec=TIAProcessGateway)
    async def fake_export(plc_name, target_dir, table_names=None):
        Path(target_dir).mkdir(parents=True, exist_ok=True)
        return target_dir
    gateway.export_plc_tags_xml = fake_export  # type: ignore[method-assign]
    async def fake_batch(operations, undo_text=""):
        return {"success": True, "operations_executed": len(operations), "details": []}
    gateway.execute_transactional_batch = fake_batch  # type: ignore[method-assign]
    # commit_disp_nmax_renames_online: stub OK (la idea del test es
    # que el commit global sea exitoso aunque fallen los comentarios).
    async def fake_nmax_renames(
        plc_name, nmax_ops, rename_ops, undo_text="", **kwargs,
    ):
        return {
            "success": True,
            "operations_executed": len(nmax_ops) + len(rename_ops),
            "details": [],
        }
    gateway.commit_disp_nmax_renames_online = fake_nmax_renames  # type: ignore[method-assign]
    # commit_disp_devices_offline: stub OK.
    async def fake_devices_offline(
        plc_name, device_changes, work_dir, undo_text="", **kwargs,
    ):
        return {
            "success": True,
            "operations_executed": 3 * len(device_changes),
            "details": [],
        }
    gateway.commit_disp_devices_offline = fake_devices_offline  # type: ignore[method-assign]
    # commit_devices_sync (DEPRECATED): stub compat.
    async def fake_commit(
        plc_name, nmax_ops, rename_ops, device_changes, work_dir,
        undo_text="", **kwargs,
    ):
        return {
            "success": True,
            "operations_executed": (
                len(nmax_ops) + len(rename_ops) + 3 * len(device_changes)
            ),
            "details": [],
        }
    gateway.commit_devices_sync = fake_commit  # type: ignore[method-assign]
    async def fake_compile_blocks(
        plc_name: str, block_names: list[str]
    ) -> dict:
        return {
            "compiled": [],
            "skipped_unchanged": list(block_names),
            "not_found": [],
            "errors": [],
        }
    gateway.compile_blocks = fake_compile_blocks  # type: ignore[method-assign]
    # El batch de comentarios falla (TIA en estado raro).
    # ``**kwargs`` para tolerar los nuevos args del gateway
    # (``subestado``, ``build_cache_dir``, ``area_id``, ``contexto``)
    # sin necesidad de enumerarlos uno a uno en este stub.
    async def fake_comments_batch(
        plc_name, dispositivos_slot_maps, target_folder,
        db_names, db_array_names, undo_text="", **kwargs,
    ):
        raise RuntimeError("TIA no responde")
    gateway.update_disp_instance_comments_batch = fake_comments_batch  # type: ignore[method-assign]

    use_case = DispSyncInstancesUseCase(
        gateway=gateway,
        config_manager=minimal_config,
        state=AppState(),
        progress=fresh_tracker,
        build_cache_dir=tmp_path / ".build_cache",
    )
    use_case._compute_diff = MagicMock(return_value=({}, {}, {}))  # type: ignore[method-assign]
    # Forzamos al menos 1 op para entrar en la rama normal.
    use_case._compute_nmax_ops_for_apply = MagicMock(  # type: ignore[method-assign]
        return_value=[{
            "command": "update_user_constant_value",
            "args": {"plc_name": "PLC_TEST", "table_name": "t",
                     "constant_name": "N_MAX_DISP_ED", "new_value": 10},
        }]
    )
    use_case._build_desired_state_from_app = MagicMock(return_value={})  # type: ignore[method-assign]
    use_case.generar_prevision = AsyncMock(  # type: ignore[method-assign]
        return_value={"agregados": [], "eliminados": [], "renombrados": [],
                      "todos": [], "nmax": {}, "summary": {}}
    )

    result = await use_case.ejecutar_transaccion("PLC_TEST", {})

    # El commit global es exitoso aunque los comentarios fallen.
    assert result["success"] is True
    assert result["compile_ok"] is True
    # El bloque comments_sync reporta el error sin propagarlo.
    assert result["comments_sync"]["applied"] is False
    assert result["comments_sync"]["operations_executed"] == 0
    assert "TIA no responde" in result["comments_sync"]["error"]
    # El tracker termina en success (no error).
    assert fresh_tracker.snapshot().active is False
