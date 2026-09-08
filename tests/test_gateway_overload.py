"""Tests del overload de export_plc_tags_xml + los 2 nuevos handlers
del split online/offline (sept-2026 fix del bug "primer commit no
aplica, segundo sí" en TIA V21)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.infrastructure.gateway import TIAProcessGateway


@pytest.fixture
def gateway() -> TIAProcessGateway:
    """Gateway con ``_dispatch_worker`` mockeado (no arranca subprocesos)."""
    gw = TIAProcessGateway()
    gw._dispatch_worker = AsyncMock(
        return_value={"success": True, "operations_executed": 1, "details": []}
    )
    return gw


@pytest.mark.asyncio
async def test_export_plc_tags_xml_without_table_names(gateway: TIAProcessGateway) -> None:
    """Sin ``table_names``, el gateway NO envia el campo al worker (back-compat)."""
    await gateway.export_plc_tags_xml("PLC1", "C:/export")
    gateway._dispatch_worker.assert_called_once_with(
        "export_plc_tags_xml",
        {"plc_name": "PLC1", "target_dir": "C:/export"},
    )


@pytest.mark.asyncio
async def test_export_plc_tags_xml_with_table_names(gateway: TIAProcessGateway) -> None:
    """Con ``table_names``, el gateway envia la whitelist al worker."""
    tables = ["2000_Disp_ED", "2000_Disp_V", "000_Config_Dispositivos"]
    await gateway.export_plc_tags_xml("PLC1", "C:/export", table_names=tables)
    gateway._dispatch_worker.assert_called_once_with(
        "export_plc_tags_xml",
        {
            "plc_name": "PLC1",
            "target_dir": "C:/export",
            "table_names": tables,
        },
    )


@pytest.mark.asyncio
async def test_export_plc_tags_xml_with_empty_table_names(gateway: TIAProcessGateway) -> None:
    """Con ``table_names=[]`` (lista vacia), el gateway envia la lista vacia.

    Esto le dice al worker "exporta cero tablas" (util para tests que
    no quieren side effects).
    """
    await gateway.export_plc_tags_xml("PLC1", "C:/export", table_names=[])
    gateway._dispatch_worker.assert_called_once_with(
        "export_plc_tags_xml",
        {
            "plc_name": "PLC1",
            "target_dir": "C:/export",
            "table_names": [],
        },
    )


# ────────────────────────────────────────────────────────────────────────
# Tests del handler ONLINE: commit_disp_nmax_renames_online
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_commit_disp_nmax_renames_online_dispatches_single_op(
    gateway: TIAProcessGateway,
) -> None:
    """``commit_disp_nmax_renames_online`` envia UN SOLO op al worker
    (NO usa ``execute_transactional_batch``). El handler del worker
    abre/cierra su propia tx TIA.

    Verifica que:
      - El comando despachado es ``commit_disp_nmax_renames_online``.
      - Los args (plc_name, nmax_ops, rename_ops, undo_text) llegan tal cual.
    """
    nmax_ops = [{"table_name": "000_Config_Dispositivos", "constant_name": "N1", "new_value": 5}]
    rename_ops = [{"table_name": "2000_Disp_ED", "current_name": "A", "new_name": "B"}]
    await gateway.commit_disp_nmax_renames_online(
        plc_name="PLC_X",
        nmax_ops=nmax_ops,
        rename_ops=rename_ops,
        undo_text="Test online commit",
    )
    gateway._dispatch_worker.assert_called_once()
    call = gateway._dispatch_worker.call_args
    assert call.args[0] == "commit_disp_nmax_renames_online"
    args = call.args[1]
    assert args["plc_name"] == "PLC_X"
    assert args["nmax_ops"] == nmax_ops
    assert args["rename_ops"] == rename_ops
    assert args["undo_text"] == "Test online commit"


@pytest.mark.asyncio
async def test_commit_disp_nmax_renames_online_default_undo_text(
    gateway: TIAProcessGateway,
) -> None:
    """Sin ``undo_text`` explicito, usa el default online."""
    await gateway.commit_disp_nmax_renames_online(
        plc_name="PLC_X",
        nmax_ops=[],
        rename_ops=[],
    )
    call = gateway._dispatch_worker.call_args
    assert call.args[1]["undo_text"] == "Sync N_MAX + renames (online)"


@pytest.mark.asyncio
async def test_commit_disp_nmax_renames_online_timeout_scales_with_ops(
    gateway: TIAProcessGateway,
) -> None:
    """El timeout_override crece con N_MAX + renames + 2 (start+end tx)."""
    big_nmax = [
        {"table_name": "000_Config_Dispositivos",
         "constant_name": f"N{i}", "new_value": i}
        for i in range(20)
    ]
    big_renames = [
        {"table_name": "2000_Disp_ED",
         "current_name": f"V_{i}", "new_name": f"V_NEW_{i}"}
        for i in range(60)
    ]
    await gateway.commit_disp_nmax_renames_online(
        plc_name="PLC_X",
        nmax_ops=big_nmax,
        rename_ops=big_renames,
    )
    call = gateway._dispatch_worker.call_args
    timeout = call.kwargs.get("timeout_override")
    # 20 N_MAX + 60 renames + 2 (start+end tx) = 82 ops estimadas.
    # 82 * 5s = 410s, mas que el default de 300s.
    assert timeout is not None
    assert timeout >= 410, f"Timeout demasiado bajo: {timeout}s"


# ────────────────────────────────────────────────────────────────────────
# Tests del handler OFFLINE: commit_disp_devices_offline
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_commit_disp_devices_offline_dispatches_single_op(
    gateway: TIAProcessGateway,
) -> None:
    """``commit_disp_devices_offline`` envia UN SOLO op al worker
    (NO usa ``execute_transactional_batch``). El handler del worker
    abre/cierra su propia tx TIA.

    Verifica que:
      - El comando despachado es ``commit_disp_devices_offline``.
      - Los args (plc_name, device_changes, work_dir, undo_text) llegan tal cual.
    """
    device_changes = [
        {
            "table_name": "2000_Disp_ED",
            "tia_folder": "2000_Dispositivos",
            "adds": [{"plc_tag": "V_NEW", "uid": "5"}],
            "removes": [],
        }
    ]
    await gateway.commit_disp_devices_offline(
        plc_name="PLC_X",
        device_changes=device_changes,
        work_dir="C:/commit",
        undo_text="Test offline commit",
    )
    gateway._dispatch_worker.assert_called_once()
    call = gateway._dispatch_worker.call_args
    assert call.args[0] == "commit_disp_devices_offline"
    args = call.args[1]
    assert args["plc_name"] == "PLC_X"
    assert args["device_changes"] == device_changes
    assert args["work_dir"] == "C:/commit"
    assert args["undo_text"] == "Test offline commit"


@pytest.mark.asyncio
async def test_commit_disp_devices_offline_default_undo_text(
    gateway: TIAProcessGateway,
) -> None:
    """Sin ``undo_text`` explicito, usa el default offline."""
    await gateway.commit_disp_devices_offline(
        plc_name="PLC_X",
        device_changes=[],
        work_dir="C:/commit",
    )
    call = gateway._dispatch_worker.call_args
    assert call.args[1]["undo_text"] == "Sync devices (offline)"


@pytest.mark.asyncio
async def test_commit_disp_devices_offline_requires_absolute_work_dir() -> None:
    """``work_dir`` debe ser absoluto."""
    gw = TIAProcessGateway()
    gw._dispatch_worker = AsyncMock()
    with pytest.raises(ValueError, match="work_dir debe ser una ruta absoluta"):
        await gw.commit_disp_devices_offline(
            plc_name="PLC_X",
            device_changes=[],
            work_dir="relative/commit",
        )


@pytest.mark.asyncio
async def test_commit_disp_devices_offline_timeout_scales_with_ops(
    gateway: TIAProcessGateway,
) -> None:
    """El timeout_override crece con 3 * device_changes + 2 (start+end tx)."""
    big_devices = [
        {
            "table_name": f"2000_Disp_{hw}",
            "tia_folder": "2000_Dispositivos",
            "adds": [], "removes": [],
        }
        for hw in ["ED", "EA", "SA", "V", "M", "M_VF"]
    ]
    await gateway.commit_disp_devices_offline(
        plc_name="PLC_X",
        device_changes=big_devices,
        work_dir="C:/commit",
    )
    call = gateway._dispatch_worker.call_args
    timeout = call.kwargs.get("timeout_override")
    # 6 devices * 3 + 2 = 20 ops estimadas.
    # 20 * 5s = 100s. Como el default es 300s, NO se aplica el override
    # en este caso (es menor que el default). Verificamos que se
    # pasa el kwarg y es >= 100s.
    assert timeout is not None
    assert timeout >= 100, f"Timeout demasiado bajo: {timeout}s"


# ────────────────────────────────────────────────────────────────────────
# Tests del handler DEPRECATED: commit_devices_sync (compat)
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_commit_devices_sync_dispatches_single_op(
    gateway: TIAProcessGateway,
) -> None:
    """``commit_devices_sync`` (DEPRECATED) sigue enviando el batch con
    UN SOLO op ``commit_devices_sync`` al worker. Mantenido por compat
    con callers/tests legacy.
    """
    nmax_ops = [{"table_name": "000_Config_Dispositivos", "constant_name": "N1", "new_value": 5}]
    rename_ops = [{"table_name": "2000_Disp_ED", "current_name": "A", "new_name": "B"}]
    device_changes = [
        {
            "table_name": "2000_Disp_ED",
            "tia_folder": "2000_Dispositivos",
            "adds": [{"plc_tag": "V_NEW", "uid": "5"}],
            "removes": [],
        }
    ]
    await gateway.commit_devices_sync(
        plc_name="PLC_X",
        nmax_ops=nmax_ops,
        rename_ops=rename_ops,
        device_changes=device_changes,
        work_dir="C:/commit",
        undo_text="Test commit (deprecated)",
    )
    gateway._dispatch_worker.assert_called_once()
    call = gateway._dispatch_worker.call_args
    assert call.args[0] == "execute_transactional_batch"
    args = call.args[1]
    assert len(args["operations"]) == 1
    op = args["operations"][0]
    assert op["command"] == "commit_devices_sync"


@pytest.mark.asyncio
async def test_commit_devices_sync_default_undo_text(
    gateway: TIAProcessGateway,
) -> None:
    """Sin ``undo_text`` explicito, usa el default legacy."""
    await gateway.commit_devices_sync(
        plc_name="PLC_X",
        nmax_ops=[],
        rename_ops=[],
        device_changes=[],
        work_dir="C:/commit",
    )
    call = gateway._dispatch_worker.call_args
    assert call.args[1]["undo_text"] == "Sync dispositivos (N_MAX + devices)"


@pytest.mark.asyncio
async def test_commit_devices_sync_requires_absolute_work_dir() -> None:
    """``work_dir`` debe ser absoluto (igual que ``export_plc_tags_xml``)."""
    gw = TIAProcessGateway()
    gw._dispatch_worker = AsyncMock()
    with pytest.raises(ValueError, match="work_dir debe ser una ruta absoluta"):
        await gw.commit_devices_sync(
            plc_name="PLC_X",
            nmax_ops=[],
            rename_ops=[],
            device_changes=[],
            work_dir="relative/commit",
        )

