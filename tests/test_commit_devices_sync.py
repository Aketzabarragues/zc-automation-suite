"""Tests de integracion del op compuesto ``commit_devices_sync``.

Estrategia: estos tests verifican que el handler esta registrado en el
COMMAND_REGISTRY del worker (via ``load_extra_commands`` del area
alimentacion), que tiene la firma esperada, y que falla rapido ante
argumentos invalidos. La logica de N_MAX + renames + devices se cubre
indirectamente via los tests del use case
(test_sync_dispositivos_instances.py) que mockean el gateway.

Los tests de deep-integration con el portal mock son fragiles (MagicMock
+ closure + nested function lookup) y se omiten a favor de los tests
de use case que son mas robustos.
"""
from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# El op vive en el area de alimentacion, no en el core del worker.
# Lo cargamos via ``register`` para verificar que se anade al
# COMMAND_REGISTRY del worker como cualquier otro op del area.
worker_tia = importlib.import_module("core.infrastructure.tia.worker_tia")
extra_commands = importlib.import_module(
    "areas.alimentacion.infrastructure.tia.extra_commands"
)


# ────────────────────────────────────────────────────────────────────────
# Tests de registro y signature
# ────────────────────────────────────────────────────────────────────────


def test_commit_devices_sync_is_registered() -> None:
    """El op compuesto esta en COMMAND_REGISTRY bajo ``commit_devices_sync``.

    El registro se hace via ``extra_commands.register`` (PR 3), que el
    command_loader invoca al arrancar el worker. Para verificar el
    wiring, llamamos a ``register`` aqui en el test contra una copia
    del registry y comprobamos que el op esta presente.
    """
    from core.infrastructure.tia import command_loader
    # Forzamos el descubrimiento y registro.
    command_loader.load_extra_commands(worker_tia.COMMAND_REGISTRY)
    assert "commit_devices_sync" in worker_tia.COMMAND_REGISTRY


def test_commit_devices_sync_factory_signature() -> None:
    """La factory ``make_cmd_commit_devices_sync`` retorna un callable
    con la firma esperada ``(portal, ts, args) -> dict``.
    """
    import inspect
    handler = extra_commands.make_cmd_commit_devices_sync()
    sig = inspect.signature(handler)
    assert list(sig.parameters.keys()) == ["portal", "ts", "args"]


def test_commit_devices_sync_missing_required_args(tmp_path: Path) -> None:
    """Sin ``plc_name`` o ``work_dir``, ValueError fail-fast."""
    portal = MagicMock()
    handler = extra_commands.make_cmd_commit_devices_sync()

    with pytest.raises(ValueError, match="plc_name"):
        handler(
            portal=portal, ts=MagicMock(),
            args={
                "work_dir": str(tmp_path),
                "nmax_ops": [], "rename_ops": [], "device_changes": [],
            },
        )
    with pytest.raises(ValueError, match="work_dir"):
        handler(
            portal=portal, ts=MagicMock(),
            args={
                "plc_name": "PLC_X",
                "nmax_ops": [], "rename_ops": [], "device_changes": [],
            },
        )


def test_commit_devices_sync_calls_start_transaction_once(tmp_path: Path) -> None:
    """El handler abre UNA sola start_transaction (atomicidad)."""
    portal = MagicMock()
    project = MagicMock()
    plc = MagicMock()
    project.get_plcs.return_value = [plc]
    plc.get_name.return_value = "PLC_X"
    plc.get_plc_tag_tables.return_value = []
    plc.import_plc_tags = MagicMock(return_value=True)
    portal.get_project.return_value = project
    project.start_transaction = MagicMock()
    project.end_transaction = MagicMock()

    handler = extra_commands.make_cmd_commit_devices_sync()
    handler(
        portal=portal, ts=MagicMock(),
        args={
            "plc_name": "PLC_X",
            "work_dir": str(tmp_path),
            "nmax_ops": [], "rename_ops": [], "device_changes": [],
        },
    )
    project.start_transaction.assert_called_once()
    project.end_transaction.assert_called_once_with(rollback=False)


def test_commit_devices_sync_rolls_back_on_runtime_error(tmp_path: Path) -> None:
    """Si algo falla en medio de la tx, se hace end_transaction(rollback=True)."""
    portal = MagicMock()
    project = MagicMock()
    plc = MagicMock()
    plc.get_name.return_value = "PLC_X"
    plc.get_plc_tag_tables.return_value = []
    project.get_plcs.return_value = [plc]
    portal.get_project.return_value = project
    project.start_transaction = MagicMock(
        side_effect=RuntimeError("Boom START")
    )
    project.end_transaction = MagicMock()

    handler = extra_commands.make_cmd_commit_devices_sync()
    with pytest.raises(RuntimeError, match="commit_devices_sync abortado"):
        handler(
            portal=portal, ts=MagicMock(),
            args={
                "plc_name": "PLC_X",
                "work_dir": str(tmp_path),
                "nmax_ops": [], "rename_ops": [], "device_changes": [],
            },
        )
    project.end_transaction.assert_called_once_with(rollback=True)
