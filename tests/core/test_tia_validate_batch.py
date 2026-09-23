"""Tests del helper ``validate_execute_batch_result`` (F17)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.helpers.tia import validate_execute_batch_result


# ------------------------------------------------------------ happy paths
def test_validate_ok_passes_silently():
    validate_execute_batch_result({
        "success": True,
        "operations_executed": 3,
        "operations_failed": 0,
        "details": [
            {"step": 1, "command": "a", "ok": True, "result": {}},
            {"step": 2, "command": "b", "ok": True, "result": {}},
            {"step": 3, "command": "c", "ok": True, "result": {}},
        ],
    })


def test_validate_non_dict_passes_silently():
    """Defensivo: si el caller pasa algo raro, no raise."""
    validate_execute_batch_result(None)
    validate_execute_batch_result("ok")
    validate_execute_batch_result(42)


def test_validate_missing_success_field_passes():
    """Sin ``success`` explicito, el resultado se considera OK."""
    validate_execute_batch_result({"operations_executed": 1, "details": []})


# ------------------------------------------------------------ error paths
def test_validate_all_failed_raises_with_all_steps():
    result = {
        "success": False,
        "operations_executed": 2,
        "operations_failed": 2,
        "details": [
            {
                "step": 1,
                "command": "export_block",
                "ok": False,
                "error": "TIA said no",
            },
            {
                "step": 2,
                "command": "export_plc_tags_xml",
                "ok": False,
                "error": "boom",
            },
        ],
    }
    with pytest.raises(RuntimeError) as excinfo:
        validate_execute_batch_result(
            result,
            undo_text="Post-sync preview",
            plc_name="PLC_1",
        )
    msg = str(excinfo.value)
    assert "Post-sync preview" in msg
    assert "PLC_1" in msg
    assert "2/2" in msg
    assert "'export_block'" in msg
    assert "TIA said no" in msg
    assert "'export_plc_tags_xml'" in msg
    assert "boom" in msg


def test_validate_partial_failure_raises():
    """Algunas ops OK + algunas failed -> sigue raise (success=False)."""
    result = {
        "success": False,
        "operations_executed": 3,
        "operations_failed": 1,
        "details": [
            {"step": 1, "command": "good1", "ok": True, "result": {}},
            {"step": 2, "command": "bad", "ok": False, "error": "x failed"},
            {"step": 3, "command": "good2", "ok": True, "result": {}},
        ],
    }
    with pytest.raises(RuntimeError) as excinfo:
        validate_execute_batch_result(result)
    msg = str(excinfo.value)
    assert "1/3" in msg
    assert "'bad'" in msg
    assert "'good1'" not in msg
    assert "'good2'" not in msg


def test_validate_truncates_long_error():
    long_err = "A" * 1000
    result = {
        "success": False,
        "operations_executed": 1,
        "operations_failed": 1,
        "details": [
            {"step": 1, "command": "op", "ok": False, "error": long_err},
        ],
    }
    with pytest.raises(RuntimeError) as excinfo:
        validate_execute_batch_result(result)
    msg = str(excinfo.value)
    assert long_err[:200] in msg
    assert long_err[250:] not in msg


def test_validate_failure_detail_is_clean_for_newlines():
    """Los ``\\n`` en el error se reemplazan por espacio (mensaje plano)."""
    result = {
        "success": False,
        "operations_executed": 1,
        "operations_failed": 1,
        "details": [
            {
                "step": 1,
                "command": "op",
                "ok": False,
                "error": "line1\nline2",
            },
        ],
    }
    with pytest.raises(RuntimeError) as excinfo:
        validate_execute_batch_result(result)
    msg = str(excinfo.value)
    assert "line1 line2" in msg


def test_validate_no_details_passes_silently_or_raises_gracefully():
    """Sin ``details`` el mensaje es 'sin detalle' (no explota)."""
    result = {
        "success": False,
        "operations_executed": 0,
        "operations_failed": 0,
    }
    with pytest.raises(RuntimeError) as excinfo:
        validate_execute_batch_result(result)
    assert "sin detalle" in str(excinfo.value)


def test_validate_with_logger_warns_before_raising():
    log = MagicMock()
    result = {
        "success": False,
        "operations_executed": 1,
        "operations_failed": 1,
        "details": [
            {"step": 1, "command": "op", "ok": False, "error": "fail"},
        ],
    }
    with pytest.raises(RuntimeError):
        validate_execute_batch_result(result, log=log)
    log.warning.assert_called_once()
