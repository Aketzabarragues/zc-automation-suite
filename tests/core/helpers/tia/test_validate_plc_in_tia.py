"""Tests del helper ``validate_plc_in_tia`` (PR5, multi-PLC)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.helpers.tia.validate_plc_in_tia import validate_plc_in_tia


def _mock_tia_client(plc_names: list[str], ok: bool = True, error: str = "") -> MagicMock:
    """Crea un mock de SyncTIAClient con la respuesta de list_plcs."""
    client = MagicMock()
    if ok:
        response = {"ok": True, "result": {"plcs": [{"name": n} for n in plc_names]}}
    else:
        response = {"ok": False, "error": error}
    client.submit_and_wait.return_value = response
    return client


def test_validate_plc_in_tia_ok():
    """PLC existe en TIA: no lanza."""
    client = _mock_tia_client(["PLC1", "PLC2"])
    validate_plc_in_tia(client, "PLC1")  # no raise


def test_validate_plc_in_tia_plc_inexistente():
    """PLC no esta en TIA: lanza ValueError con PLCs disponibles."""
    client = _mock_tia_client(["PLC1", "PLC2"])
    with pytest.raises(ValueError) as exc_info:
        validate_plc_in_tia(client, "PLC_FOO")
    assert "PLC 'PLC_FOO'" in str(exc_info.value)
    assert "PLC1" in str(exc_info.value)  # PLCs disponibles


def test_validate_plc_in_tia_strict_equality():
    """Strict equality: 'PLC1' != 'plc1' (case-sensitive)."""
    client = _mock_tia_client(["PLC1"])
    with pytest.raises(ValueError):
        validate_plc_in_tia(client, "plc1")  # lowercase


def test_validate_plc_in_tia_lista_vacia():
    """TIA no devuelve PLCs: lanza RuntimeError."""
    client = _mock_tia_client([])
    with pytest.raises(RuntimeError) as exc_info:
        validate_plc_in_tia(client, "PLC1")
    assert "no devolvio PLCs" in str(exc_info.value)


def test_validate_plc_in_tia_tia_no_responde():
    """TIA falla al responder: lanza RuntimeError."""
    client = _mock_tia_client([], ok=False, error="timeout")
    with pytest.raises(RuntimeError) as exc_info:
        validate_plc_in_tia(client, "PLC1")
    assert "list_plcs fallo" in str(exc_info.value)
    assert "timeout" in str(exc_info.value)


def test_validate_plc_in_tia_timeout_no_aborta():
    """Worker TIA ocupado (timeout): no aborta el FB, solo avisa.

    La cola del worker es FIFO y de un solo hilo: si esta ocupada,
    ``list_plcs`` expira. Eso no dice nada sobre si el PLC existe, asi
    que la validacion se omite en vez de fallar con un falso "PLC no
    existe".
    """
    client = MagicMock()
    client.submit_and_wait.side_effect = TimeoutError("submit_and_wait supero el timeout")
    validate_plc_in_tia(client, "PLC1")  # no raise


def test_validate_plc_in_tia_timeout_no_consulta_mas():
    """Tras un timeout solo se hace UNA llamada a list_plcs."""
    client = MagicMock()
    client.submit_and_wait.side_effect = TimeoutError("timeout")
    validate_plc_in_tia(client, "PLC1")
    assert client.submit_and_wait.call_count == 1


def test_validate_plc_in_tia_plc_vacio():
    """plc_name vacio: lanza ValueError inmediato."""
    client = _mock_tia_client(["PLC1"])
    with pytest.raises(ValueError) as exc_info:
        validate_plc_in_tia(client, "")
    assert "vacio" in str(exc_info.value)


def test_validate_plc_in_tia_usa_submit_and_wait():
    """Llama a submit_and_wait con comando 'list_plcs'."""
    client = _mock_tia_client(["PLC1"])
    validate_plc_in_tia(client, "PLC1")
    client.submit_and_wait.assert_called_once()
    args, kwargs = client.submit_and_wait.call_args
    assert args[0] == "list_plcs"