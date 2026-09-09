"""Tests de integracion de los handlers ``commit_disp_nmax_renames_online``
y ``commit_disp_devices_offline`` (sept-2026 fix del bug "primer commit
no aplica, segundo sí" en TIA V21).

Sept-2026: el antiguo ``commit_devices_sync`` mezclaba cambios online
(N_MAX+renames via ``set_property``) con cambios offline (devices via
``import_plc_tags``) en una sola ``start_transaction``. TIA V21 hace
rollback silencioso de los ``set_property`` cuando se mezclan con
``import_plc_tags`` en la misma tx. La solución es partir el flujo en
2 transacciones SECUENCIALES, cada una abriendo su propia tx:

  Tx A (online puro): ``commit_disp_nmax_renames_online``
  Tx B (offline puro): ``commit_disp_devices_offline``

Estrategia: estos tests verifican que los handlers están registrados en
el COMMAND_REGISTRY del worker, que tienen la firma esperada, que
abren/cierran su propia ``start_transaction`` / ``end_transaction``,
y que hacen rollback atómico si una op falla.
"""
from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Los handlers viven en el area de alimentacion, no en el core del worker.
# Los cargamos via ``register`` para verificar que se anaden al
# COMMAND_REGISTRY del worker como cualquier otro op del area.
worker_tia = importlib.import_module("core.infrastructure.tia.worker_tia")
extra_commands = importlib.import_module(
    "areas.alimentacion.infrastructure.tia.extra_commands"
)


# ────────────────────────────────────────────────────────────────────────
# Tests de registro
# ────────────────────────────────────────────────────────────────────────


def test_commit_disp_nmax_renames_online_is_registered() -> None:
    """El handler online está en COMMAND_REGISTRY bajo
    ``commit_disp_nmax_renames_online``."""
    from core.infrastructure.tia import command_loader
    command_loader.load_extra_commands(worker_tia.COMMAND_REGISTRY)
    assert "commit_disp_nmax_renames_online" in worker_tia.COMMAND_REGISTRY


def test_commit_disp_devices_offline_is_registered() -> None:
    """El handler offline está en COMMAND_REGISTRY bajo
    ``commit_disp_devices_offline``."""
    from core.infrastructure.tia import command_loader
    command_loader.load_extra_commands(worker_tia.COMMAND_REGISTRY)
    assert "commit_disp_devices_offline" in worker_tia.COMMAND_REGISTRY


def test_commit_disp_nmax_renames_online_factory_signature() -> None:
    """La factory retorna un callable con firma ``(portal, ts, args) -> dict``."""
    handler = extra_commands.make_cmd_commit_disp_nmax_renames_online()
    sig = inspect.signature(handler)
    assert list(sig.parameters.keys()) == ["portal", "ts", "args"]


def test_commit_disp_devices_offline_factory_signature() -> None:
    """La factory retorna un callable con firma ``(portal, ts, args) -> dict``."""
    handler = extra_commands.make_cmd_commit_disp_devices_offline()
    sig = inspect.signature(handler)
    assert list(sig.parameters.keys()) == ["portal", "ts", "args"]


# ────────────────────────────────────────────────────────────────────────
# Tests del handler online: abre/cierra su propia tx
# ────────────────────────────────────────────────────────────────────────


def _build_online_mock_portal() -> MagicMock:
    """Portal mock con PLC y proyecto listos para tests del handler online."""
    portal = MagicMock()
    project = MagicMock()
    plc = MagicMock()
    project.get_plcs.return_value = [plc]
    plc.get_name.return_value = "PLC_X"
    plc.get_plc_tag_tables.return_value = []  # sin tablas: N_MAX/renames vacios
    portal.get_project.return_value = project
    project.start_transaction = MagicMock()
    project.end_transaction = MagicMock()
    return portal


def test_commit_disp_nmax_renames_online_opens_own_transaction() -> None:
    """El handler online abre y cierra su propia ``start_transaction`` /
    ``end_transaction(rollback=False)``.
    """
    portal = _build_online_mock_portal()
    handler = extra_commands.make_cmd_commit_disp_nmax_renames_online()

    handler(
        portal=portal, ts=MagicMock(),
        args={
            "plc_name": "PLC_X",
            "nmax_ops": [],
            "rename_ops": [],
        },
    )
    project = portal.get_project.return_value
    # Debe haber llamado start_transaction exactamente 1 vez.
    project.start_transaction.assert_called_once()
    # Y end_transaction con rollback=False (no es rollback).
    project.end_transaction.assert_called_once_with(rollback=False)


def test_commit_disp_nmax_renames_online_rollback_on_failure() -> None:
    """Si una op falla, hace ``end_transaction(rollback=True)`` y re-lanza.

    Forzamos un fallo pasando un nmax_op contra un PLC sin la tabla
    esperada: ``_cmd_update_user_constant_value`` lanza ``RuntimeError``.
    El handler debe hacer rollback y propagar.
    """
    portal = _build_online_mock_portal()
    handler = extra_commands.make_cmd_commit_disp_nmax_renames_online()

    with pytest.raises(RuntimeError, match="commit_disp_nmax_renames_online"):
        handler(
            portal=portal, ts=MagicMock(),
            args={
                "plc_name": "PLC_X",
                "nmax_ops": [
                    {
                        "table_name": "000_Config_Dispositivos",
                        "constant_name": "N1",
                        "new_value": 1,
                    },
                ],
                "rename_ops": [],
            },
        )
    project = portal.get_project.return_value
    # start_transaction se llamó (la tx se abrió).
    project.start_transaction.assert_called_once()
    # end_transaction con rollback=True (no False).
    project.end_transaction.assert_called_once_with(rollback=True)


def test_commit_disp_nmax_renames_online_missing_plc_name() -> None:
    """Sin ``plc_name``, ValueError fail-fast."""
    portal = MagicMock()
    handler = extra_commands.make_cmd_commit_disp_nmax_renames_online()
    with pytest.raises(ValueError, match="plc_name"):
        handler(
            portal=portal, ts=MagicMock(),
            args={"nmax_ops": [], "rename_ops": []},
        )


# ────────────────────────────────────────────────────────────────────────
# Tests del handler offline: abre/cierra su propia tx
# ────────────────────────────────────────────────────────────────────────


def _build_offline_mock_portal(tmp_path: Path) -> MagicMock:
    """Portal mock con PLC sin tablas (handler no llega a export si
    ``device_changes`` está vacío)."""
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
    return portal


def test_commit_disp_devices_offline_opens_own_transaction(
    tmp_path: Path,
) -> None:
    """El handler offline abre y cierra su propia ``start_transaction`` /
    ``end_transaction(rollback=False)``."""
    portal = _build_offline_mock_portal(tmp_path)
    handler = extra_commands.make_cmd_commit_disp_devices_offline()

    # device_changes vacío: la tx se abre/cierra igualmente, sin entrar
    # al bucle de export/edit/import.
    handler(
        portal=portal, ts=MagicMock(),
        args={
            "plc_name": "PLC_X",
            "work_dir": str(tmp_path),
            "device_changes": [],
        },
    )
    project = portal.get_project.return_value
    project.start_transaction.assert_called_once()
    project.end_transaction.assert_called_once_with(rollback=False)


def test_commit_disp_devices_offline_rollback_on_failure(
    tmp_path: Path,
) -> None:
    """Si una op falla, hace ``end_transaction(rollback=True)`` y re-lanza.

    Forzamos un fallo: el ``device_change`` referencia una tabla que
    no existe en el PLC (la lista está vacía en el mock).
    """
    portal = _build_offline_mock_portal(tmp_path)
    handler = extra_commands.make_cmd_commit_disp_devices_offline()

    with pytest.raises(RuntimeError, match="commit_disp_devices_offline"):
        handler(
            portal=portal, ts=MagicMock(),
            args={
                "plc_name": "PLC_X",
                "work_dir": str(tmp_path),
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
    project = portal.get_project.return_value
    project.start_transaction.assert_called_once()
    project.end_transaction.assert_called_once_with(rollback=True)


def test_commit_disp_devices_offline_missing_required_args(
    tmp_path: Path,
) -> None:
    """Sin ``plc_name`` o ``work_dir``, ValueError fail-fast."""
    portal = MagicMock()
    handler = extra_commands.make_cmd_commit_disp_devices_offline()

    with pytest.raises(ValueError, match="plc_name"):
        handler(
            portal=portal, ts=MagicMock(),
            args={"work_dir": str(tmp_path), "device_changes": []},
        )
    with pytest.raises(ValueError, match="work_dir"):
        handler(
            portal=portal, ts=MagicMock(),
            args={"plc_name": "PLC_X", "device_changes": []},
        )


def test_table_export_not_in_devices_offline_handler(tmp_path: Path) -> None:
    """Sept-2026 fix del race condition online+offline: el handler
    ``commit_disp_devices_offline`` ya NO hace ``table.export``
    internamente.

    Por qué se quitó: el export dentro de Tx B leía los datos de TIA
    antes de que la consolidación interna de los cambios online de Tx A
    terminara, veía los nombres VIEJOS de los PlcUserConstant
    (pre-renames), los SOBREESCRIBÍA en ``modified/variables/`` y el
    ``import_plc_tags`` los re-importaba → rollback silencioso de los
    renames aplicados en Tx A.

    Solución: el export lo hace IT en el Stage 6 ``export_post_tx_a``
    de ``ejecutar_transaccion``, después de Tx A y con sleep de
    consolidación. El handler offline solo importa los XMLs ya
    editados (Stage 7 ``copy_and_edit``).

    Verifica que:
      - El handler hace ``import_plc_tags`` por cada ``device_change``.
      - El handler NO hace ``table.export`` (el método ``table.export``
        del PlcTagTable no debe ser llamado).
    """
    portal = MagicMock()
    project = MagicMock()
    plc = MagicMock()
    # Mockeamos una tabla que el handler pueda "encontrar".
    table = MagicMock()
    table.export = MagicMock()  # NO debe llamarse.
    plc.get_name.return_value = "PLC_X"
    plc.get_plc_tag_tables.return_value = [table]
    plc.import_plc_tags = MagicMock(return_value=True)
    project.get_plcs.return_value = [plc]
    portal.get_project.return_value = project
    project.start_transaction = MagicMock()
    project.end_transaction = MagicMock()
    # El handler llama ``_safe_get_table_name(table)`` y compara
    # con ``table_name``. Patcheamos para que retorne el nombre
    # esperado sin importar lo que el mock de la tabla diga.
    with patch.object(
        worker_tia, "_safe_get_table_name",
        return_value="2000_Disp_ED",
    ):
        handler = extra_commands.make_cmd_commit_disp_devices_offline()
        # Pre-poblamos el ``work_dir`` con el XML que el handler
        # espera encontrar (Stage 7 ``copy_and_edit`` lo habría
        # escrito). Sin esto, el handler raise con "XML no
        # encontrado" antes de llegar al import.
        table_xml = (
            tmp_path / "2000_Dispositivos" / "2000_Disp_ED.xml"
        )
        table_xml.parent.mkdir(parents=True, exist_ok=True)
        table_xml.write_text("<root/>", encoding="utf-8")

        handler(
            portal=portal, ts=MagicMock(),
            args={
                "plc_name": "PLC_X",
                "work_dir": str(tmp_path),
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

    # 1. ``table.export`` NO debe haberse llamado (sept-2026 fix).
    table.export.assert_not_called()
    # 2. ``import_plc_tags`` SÍ se llamó (es lo único que hace este
    #    handler: importar XMLs ya editados).
    plc.import_plc_tags.assert_called()
    # 3. La tx se abrió y cerró OK (no rollback).
    project.start_transaction.assert_called_once()
    project.end_transaction.assert_called_once_with(rollback=False)


# ────────────────────────────────────────────────────────────────────────
# Tests del handler DEPRECATED ``commit_devices_sync`` (compat)
# ────────────────────────────────────────────────────────────────────────


def test_commit_devices_sync_still_registered_as_deprecated() -> None:
    """El handler DEPRECATED sigue en el registry por compat con callers/tests
    legacy. Se retira en PR siguiente tras confirmar el fix en prod.
    """
    from core.infrastructure.tia import command_loader
    command_loader.load_extra_commands(worker_tia.COMMAND_REGISTRY)
    assert "commit_devices_sync" in worker_tia.COMMAND_REGISTRY


def test_commit_devices_sync_does_not_open_transaction(tmp_path: Path) -> None:
    """El handler DEPRECATED NO abre su propia ``start_transaction`` ni
    llama a ``end_transaction``: depende del batch wrapper (como el
    legacy).
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
    # Ningun start_transaction ni end_transaction en el op (la tx la
    # gestiona el batch wrapper legacy).
    project.start_transaction.assert_not_called()
    project.end_transaction.assert_not_called()
