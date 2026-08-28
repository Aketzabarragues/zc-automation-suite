"""Tests del overload de export_plc_tags_xml + commit_devices_sync en el gateway."""
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


@pytest.mark.asyncio
async def test_commit_devices_sync_dispatches_single_op(
    gateway: TIAProcessGateway,
) -> None:
    """``commit_devices_sync`` envia UN SOLO op ``commit_devices_sync`` al worker.

    Verifica que:
      - El batch tiene exactamente 1 op.
      - El op es ``commit_devices_sync``.
      - Los args (nmax_ops, rename_ops, device_changes, work_dir) llegan tal cual.
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
        undo_text="Test commit",
    )
    gateway._dispatch_worker.assert_called_once()
    call = gateway._dispatch_worker.call_args
    assert call.args[0] == "execute_transactional_batch"
    args = call.args[1]
    assert len(args["operations"]) == 1
    op = args["operations"][0]
    assert op["command"] == "commit_devices_sync"
    op_args = op["args"]
    assert op_args["plc_name"] == "PLC_X"
    assert op_args["nmax_ops"] == nmax_ops
    assert op_args["rename_ops"] == rename_ops
    assert op_args["device_changes"] == device_changes
    assert op_args["work_dir"] == "C:/commit"
    assert op_args["undo_text"] == "Test commit"
    # undo_text a nivel del batch.
    assert args["undo_text"] == "Test commit"


@pytest.mark.asyncio
async def test_commit_devices_sync_default_undo_text(
    gateway: TIAProcessGateway,
) -> None:
    """Sin ``undo_text`` explicito, usa el default "Sync dispositivos (N_MAX + devices)"."""
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
            work_dir="relative/commit",  # No absoluta.
        )


@pytest.mark.asyncio
async def test_commit_devices_sync_timeout_scales_with_ops(
    gateway: TIAProcessGateway,
) -> None:
    """El timeout_override crece con el numero de ops estimadas.

    Con N_MAX + renames + device_changes grandes, el timeout debe
    ser mayor que el default. Verificamos que se pasa un
    ``timeout_override`` al ``_dispatch_worker``.
    """
    # Muchas ops para forzar un timeout alto.
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
    big_devices = [
        {
            "table_name": f"2000_Disp_{hw}",
            "tia_folder": "2000_Dispositivos",
            "adds": [], "removes": [],
        }
        for hw in ["ED", "EA", "SA", "V", "M", "M_VF"]
    ]
    await gateway.commit_devices_sync(
        plc_name="PLC_X",
        nmax_ops=big_nmax,
        rename_ops=big_renames,
        device_changes=big_devices,
        work_dir="C:/commit",
    )
    call = gateway._dispatch_worker.call_args
    timeout = call.kwargs.get("timeout_override")
    # 20 N_MAX + 60 renames + 6 devices * 3 + 2 = 100 ops estimadas.
    # 100 * 5s = 500s, mas que el default de 30s.
    assert timeout is not None
    assert timeout >= 500, f"Timeout demasiado bajo: {timeout}s"
