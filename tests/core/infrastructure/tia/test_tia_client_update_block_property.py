"""Tests de ``core.infrastructure.tia.tia_cmd_blocks.update_block_property``.

Mockeamos ``tia_client`` + ``block`` con ``MagicMock``. ``_find_block_in_plc``
esta stubbed inline en el modulo y ``_get_active_project`` / ``_find_plc``
se monkey-patchean para no tocar el wrapper nativo TIA.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.infrastructure.tia import tia_cmd_blocks


@pytest.fixture
def block_factory(monkeypatch):
    """Devuelve un setup (plc, block, tia_client) + parchea los helpers.

    Los tests que necesiten llamar al handler solo tienen que configurar
    ``block.set_property.return_value`` y ``block.get_property.return_value``
    sobre el ``block`` devuelto. Los helpers ``_get_active_project``,
    ``_find_plc`` y ``_find_block_in_plc`` quedan monkey-patched en el
    modulo para apuntar al chain mockeado.
    """
    block = MagicMock()
    plc = MagicMock()
    plc._mock_block = block

    monkeypatch.setattr(
        tia_cmd_blocks, "_get_active_project", lambda _portal: MagicMock()
    )
    monkeypatch.setattr(
        tia_cmd_blocks, "_find_plc", lambda _project, _plc_name: plc
    )
    monkeypatch.setattr(
        tia_cmd_blocks,
        "_find_block_in_plc",
        lambda _plc, _block_name, _block_path: block,
    )

    tia_client = MagicMock()
    tia_client.wrapper = MagicMock()
    return tia_client, block


# ---------------------------------------------------------------- happy paths
def test_happy_path_name(block_factory):
    """set_property rc=0 + re-read coincide -> returns payload sin ok."""
    tia_client, block = block_factory
    block.set_property.return_value = 0
    block.get_property.return_value = "DB1_NEW"

    result = tia_cmd_blocks._h_update_block_property(
        args={
            "plc_name": "PLC_1500",
            "block_name": "DB1",
            "block_path": "",
            "property_name": "Name",
            "new_value": "DB1_NEW",
        },
        tia_client=tia_client,
    )

    assert result == {
        "block_name": "DB1",
        "block_path": "",
        "property_name": "Name",
        "new_value": "DB1_NEW",
    }
    assert "ok" not in result  # el dispatch del SyncTIAClient anade el ok
    block.set_property.assert_called_once_with(name="Name", value="DB1_NEW")
    block.get_property.assert_called_once_with(name="Name")


def test_happy_path_number(block_factory):
    """set_property rc=0 + re-read coincide sobre Number."""
    tia_client, block = block_factory
    block.set_property.return_value = 0
    block.get_property.return_value = "42"

    result = tia_cmd_blocks._h_update_block_property(
        args={
            "plc_name": "PLC_1500",
            "block_name": "DB1",
            "block_path": "Sistema",
            "property_name": "Number",
            "new_value": 42,
        },
        tia_client=tia_client,
    )

    assert result == {
        "block_name": "DB1",
        "block_path": "Sistema",
        "property_name": "Number",
        "new_value": 42,
    }
    block.set_property.assert_called_once_with(name="Number", value="42")


# ------------------------------------------------------------- casos de error
def test_rc_nonzero_raises_runtime_error(block_factory):
    """set_property rc=20 -> RuntimeError que menciona rc=20."""
    tia_client, block = block_factory
    block.set_property.return_value = 20

    with pytest.raises(RuntimeError, match="rc=20"):
        tia_cmd_blocks._h_update_block_property(
            args={
                "plc_name": "PLC_1500",
                "block_name": "DB1",
                "block_path": "",
                "property_name": "Name",
                "new_value": "X",
            },
            tia_client=tia_client,
        )


def test_reread_mismatch_raises_runtime_error(block_factory):
    """set_property rc=0 OK pero re-read no coincide -> RuntimeError."""
    tia_client, block = block_factory
    block.set_property.return_value = 0
    block.get_property.return_value = "OLD_VALUE"  # no coincide con new_value

    with pytest.raises(RuntimeError, match="no coincide"):
        tia_cmd_blocks._h_update_block_property(
            args={
                "plc_name": "PLC_1500",
                "block_name": "DB1",
                "block_path": "",
                "property_name": "Name",
                "new_value": "NEW_VALUE",
            },
            tia_client=tia_client,
        )


def test_property_name_invalido_raises_value_error():
    """property_name='Title' (no en whitelist) -> ValueError, no llega a TIA."""
    tia_client = MagicMock()
    tia_client.wrapper = MagicMock()

    with pytest.raises(ValueError, match="whitelist"):
        tia_cmd_blocks._h_update_block_property(
            args={
                "plc_name": "PLC_1500",
                "block_name": "DB1",
                "block_path": "",
                "property_name": "Title",
                "new_value": "X",
            },
            tia_client=tia_client,
        )


def test_plc_name_missing_raises_value_error():
    """plc_name vacio -> ValueError sin tocar TIA."""
    tia_client = MagicMock()
    tia_client.wrapper = MagicMock()

    with pytest.raises(ValueError, match="plc_name"):
        tia_cmd_blocks._h_update_block_property(
            args={
                "plc_name": "",
                "block_name": "DB1",
                "block_path": "",
                "property_name": "Name",
                "new_value": "X",
            },
            tia_client=tia_client,
        )
