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


def test_commit_devices_sync_does_not_open_transaction(tmp_path: Path) -> None:
    """El op NO abre su propia ``start_transaction`` ni llama a
    ``end_transaction``.

    Razon: el batch wrapper (``_cmd_execute_transactional_batch``) ya
    abrio la transaccion. Si este op abriera otra, TIA Portal V21
    rechaza con ``OpennessAccessException: Multiple instances of
    ExclusiveAccess is not supported`` (bug 2026-08-28). El rollback
    del lote lo gestiona el wrapper.
    """
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
    # Ningun start_transaction ni end_transaction en el op.
    project.start_transaction.assert_not_called()
    project.end_transaction.assert_not_called()


def test_commit_devices_sync_propagates_exception_to_wrapper(
    tmp_path: Path,
) -> None:
    """Si algo falla, el op PROPAGA la excepcion. El batch wrapper
    es el que hace ``end_transaction(rollback=True)``.

    Verifica que el op NO cierra la tx por su cuenta (deja la tx
    abierta en estado fallido para que el wrapper la cierre con
    rollback=True).
    """
    portal = MagicMock()
    project = MagicMock()
    plc = MagicMock()
    plc.get_name.return_value = "PLC_X"
    plc.get_plc_tag_tables.return_value = []
    project.get_plcs.return_value = [plc]
    portal.get_project.return_value = project
    # Forzamos fallo: el primer N_MAX buscara "000_Config_Dispositivos"
    # en plc.get_plc_tag_tables() (que devuelve []), y fallara.
    project.start_transaction = MagicMock()
    project.end_transaction = MagicMock()

    handler = extra_commands.make_cmd_commit_devices_sync()
    with pytest.raises(
        RuntimeError,
        match="Excepcion propagada al batch wrapper",
    ):
        handler(
            portal=portal, ts=MagicMock(),
            args={
                "plc_name": "PLC_X",
                "work_dir": str(tmp_path),
                "nmax_ops": [
                    {
                        "table_name": "000_Config_Dispositivos",
                        "constant_name": "N1",
                        "new_value": 1,
                    },
                ],
                "rename_ops": [],
                "device_changes": [],
            },
        )
    # El op NO cerro la tx (deja que el wrapper lo haga).
    project.end_transaction.assert_not_called()




def test_commit_devices_sync_runs_all_phases_when_lists_non_empty(tmp_path):
    """Las 3 fases (N_MAX, renames, devices) se ejecutan siempre, sin
    bypass. Si una lista llega vacia, simplemente no se itera.

    Equivalente al antiguo test de bypass, pero SIN flags: el device_change
    SI se procesa y se intenta localizar la tabla.
    """
    portal = MagicMock()
    project = MagicMock()
    plc = MagicMock()
    project.get_plcs.return_value = [plc]
    plc.get_name.return_value = "PLC_X"
    plc.get_plc_tag_tables.return_value = []  # tabla no encontrada -> error
    plc.import_plc_tags = MagicMock(return_value=True)
    portal.get_project.return_value = project
    project.start_transaction = MagicMock()
    project.end_transaction = MagicMock()

    handler = extra_commands.make_cmd_commit_devices_sync()
    # Forzamos la excepcion esperada: la tabla no existe en el PLC mock.
    # Eso confirma que SI entramos en la fase 3 (devices).
    with pytest.raises(RuntimeError, match="Tabla"):
        handler(
            portal=portal, ts=MagicMock(),
            args={
                "plc_name": "PLC_X",
                "work_dir": str(tmp_path),
                "nmax_ops": [],
                "rename_ops": [],
                "device_changes": [
                    {
                        "table_name": "2000_Disp_ED",
                        "tia_folder": "2000_Dispositivos",
                        "adds": [{"plc_tag": "V_X", "uid": "99"}],
                        "removes": [],
                    },
                ],
            },
        )
    # La tx NO se cierra aqui (la gestiona el batch wrapper).
    project.end_transaction.assert_not_called()
