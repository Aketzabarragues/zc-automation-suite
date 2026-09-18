"""Tests de ``proc_compute_nmax_diff``: helper puro que difiere N_MAX
activos contra el estado deseado del AppState."""
from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


# ────────────────────────────────────────────────────────────────────────
# Fakes
# ────────────────────────────────────────────────────────────────────────
class FakeConfig:
    """Replica los 3 metodos que ``proc_compute_nmax_diff`` consume."""

    def __init__(
        self,
        *,
        nmax_table: str = "000_Config_Dispositivos",
        nmax_folder: str = "PLC_USER_CONSTANTS",
        active: list[str] | None = None,
    ) -> None:
        self._nmax_table = nmax_table
        self._nmax_folder = nmax_folder
        self._active = active if active is not None else [
            "N_MAX_PREAL", "N_MAX_PINT",
        ]

    def get_global_config_table_name(self) -> str:
        return self._nmax_table

    def get_tia_folder_nmax(self) -> str:
        return self._nmax_folder

    def list_nmax_active(self) -> list[str]:
        return list(self._active)


class FakeAppState:
    """Replica ``app_state.dimensiones`` (lo unico que el helper lee)."""

    def __init__(self, dimensiones: dict[str, int] | None) -> None:
        self.dimensiones = dimensiones


# ────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────
@pytest.fixture
def tags_base(tmp_path: Path) -> Path:
    """Crea la carpeta donde estaria el XML exportado por TIA."""
    base = tmp_path / "preview"
    base.mkdir()
    (base / "PLC_USER_CONSTANTS").mkdir()
    return base


@pytest.fixture
def write_nmax_xml(tags_base: Path):
    """Devuelve un callable que escribe el ``.xml`` con N_MAX dados."""
    def _write(values: dict[str, int]) -> Path:
        xml_path = tags_base / "PLC_USER_CONSTANTS" / "000_Config_Dispositivos.xml"
        # Formato minimo que ``parse_user_constants`` espera (no relevante:
        # mockeamos el parser, asi que el contenido solo necesita existir).
        xml_path.write_text("<root/>", encoding="utf-8")
        # Patch para que ``parse_user_constants`` devuelva nuestros valores.
        return xml_path
    return _write


def _patch_parser_returning(values: dict[str, int]):
    """Helper: parchear ``SimaticMLTagParser.parse_user_constants``."""
    return patch(
        "areas.alimentacion.helpers.xml.disp_tag_table_parser."
        "SimaticMLTagParser.parse_user_constants",
        return_value=values,
    )


# ────────────────────────────────────────────────────────────────────────
# Tests
# ────────────────────────────────────────────────────────────────────────
def test_proc_compute_nmax_diff_empty_when_no_changes(
    tags_base: Path, write_nmax_xml
) -> None:
    """Si todos los N_MAX ya coinciden con AppState, retorna []."""
    xml_path = write_nmax_xml({"N_MAX_PREAL": 10, "N_MAX_PINT": 20})
    cfg = FakeConfig(active=["N_MAX_PREAL", "N_MAX_PINT"])
    state = FakeAppState({"N_MAX_PREAL": 10, "N_MAX_PINT": 20})

    with _patch_parser_returning({"N_MAX_PREAL": 10, "N_MAX_PINT": 20}):
        from areas.alimentacion.helpers.proc.proc_compute_nmax_diff import (
            proc_compute_nmax_diff,
        )
        ops = proc_compute_nmax_diff(tags_base, cfg, state)

    assert ops == []


def test_proc_compute_nmax_diff_returns_diff_for_changed_values(
    tags_base: Path, write_nmax_xml
) -> None:
    """Solo incluye N_MAX cuyo valor difiere del estado actual."""
    write_nmax_xml({"N_MAX_PREAL": 10, "N_MAX_PINT": 20})
    cfg = FakeConfig(
        nmax_table="000_Config_Dispositivos",
        active=["N_MAX_PREAL", "N_MAX_PINT"],
    )
    # AppState sube N_MAX_PREAL de 10 a 15; N_MAX_PINT sin cambios.
    state = FakeAppState({"N_MAX_PREAL": 15, "N_MAX_PINT": 20})

    with _patch_parser_returning({"N_MAX_PREAL": 10, "N_MAX_PINT": 20}):
        from areas.alimentacion.helpers.proc.proc_compute_nmax_diff import (
            proc_compute_nmax_diff,
        )
        ops = proc_compute_nmax_diff(tags_base, cfg, state)

    assert ops == [
        {"table_name": "000_Config_Dispositivos",
         "constant_name": "N_MAX_PREAL", "new_value": 15},
    ]


def test_proc_compute_nmax_diff_handles_missing_xml(
    tags_base: Path,
) -> None:
    """Si el XML no existe (estado actual desconocido, ``current={}``),
    el helper retorna ``[]``: NO puede comparar contra None (defensivo,
    mismo comportamiento que ``_compute_nmax_ops_for_apply`` de disp).

    El FB aun despachara el handler con ``nmax_ops=[]`` por requisito
    "sync_nmax incondicional": TIA no aplicara nada, pero el flujo se
    ejecuta igual.
    """
    cfg = FakeConfig(active=["N_MAX_PREAL", "N_MAX_PINT"])
    state = FakeAppState({"N_MAX_PREAL": 5, "N_MAX_PINT": 10})

    from areas.alimentacion.helpers.proc.proc_compute_nmax_diff import (
        proc_compute_nmax_diff,
    )
    ops = proc_compute_nmax_diff(tags_base, cfg, state)

    assert ops == []


def test_proc_compute_nmax_diff_includes_only_active_nmax(
    tags_base: Path, write_nmax_xml
) -> None:
    """Solo se difieren los N_MAX que ``list_nmax_active()`` declara activos.
    Aunque el XML tenga N_MAX_PREAL, si no esta en active, se ignora.
    """
    write_nmax_xml({"N_MAX_PREAL": 5, "N_MAX_PINT": 5, "N_MAX_OTHER": 99})
    cfg = FakeConfig(active=["N_MAX_PINT"])  # solo PINT activo
    state = FakeAppState({"N_MAX_PREAL": 50, "N_MAX_PINT": 50, "N_MAX_OTHER": 99})

    with _patch_parser_returning(
        {"N_MAX_PREAL": 5, "N_MAX_PINT": 5, "N_MAX_OTHER": 99}
    ):
        from areas.alimentacion.helpers.proc.proc_compute_nmax_diff import (
            proc_compute_nmax_diff,
        )
        ops = proc_compute_nmax_diff(tags_base, cfg, state)

    assert ops == [
        {"table_name": "000_Config_Dispositivos",
         "constant_name": "N_MAX_PINT", "new_value": 50},
    ]


def test_proc_compute_nmax_diff_default_zero_for_missing_app_state(
    tags_base: Path, write_nmax_xml
) -> None:
    """Si AppState no tiene la key, el valor deseado es 0 (consistente
    con ``_compute_nmax_ops_for_apply`` de disp)."""
    write_nmax_xml({"N_MAX_PREAL": 10})
    cfg = FakeConfig(active=["N_MAX_PREAL"])
    # AppState vacio: N_MAX_PREAL deseado = 0, actual = 10 → diff.
    state = FakeAppState({})

    with _patch_parser_returning({"N_MAX_PREAL": 10}):
        from areas.alimentacion.helpers.proc.proc_compute_nmax_diff import (
            proc_compute_nmax_diff,
        )
        ops = proc_compute_nmax_diff(tags_base, cfg, state)

    assert ops == [
        {"table_name": "000_Config_Dispositivos",
         "constant_name": "N_MAX_PREAL", "new_value": 0},
    ]


def test_proc_compute_nmax_diff_returns_same_shape_as_disp(
    tags_base: Path, write_nmax_xml
) -> None:
    """Sanity: el shape de cada op es IDENTICO al de disp
    (``_compute_nmax_ops_for_apply``). Asi el handler genérico los acepta
    sin conversion."""
    write_nmax_xml({"N_MAX_PREAL": 5})
    cfg = FakeConfig(active=["N_MAX_PREAL"])
    state = FakeAppState({"N_MAX_PREAL": 12})

    with _patch_parser_returning({"N_MAX_PREAL": 5}):
        from areas.alimentacion.helpers.proc.proc_compute_nmax_diff import (
            proc_compute_nmax_diff,
        )
        ops = proc_compute_nmax_diff(tags_base, cfg, state)

    assert len(ops) == 1
    op = ops[0]
    assert set(op.keys()) == {"table_name", "constant_name", "new_value"}
    assert isinstance(op["new_value"], int)


def test_proc_compute_nmax_diff_handles_parse_error_gracefully(
    tags_base: Path, write_nmax_xml, caplog
) -> None:
    """Si el parser falla, el helper logea error y sigue con ``current={}``.
    Como NO puede comparar contra None, retorna ``[]`` (comportamiento
    defensivo, mismo que ``_compute_nmax_ops_for_apply`` de disp)."""
    write_nmax_xml({"N_MAX_PREAL": 5})
    cfg = FakeConfig(active=["N_MAX_PREAL"])
    state = FakeAppState({"N_MAX_PREAL": 10})

    with patch(
        "areas.alimentacion.helpers.xml.disp_tag_table_parser."
        "SimaticMLTagParser.parse_user_constants",
        side_effect=RuntimeError("XML corrupto"),
    ):
        from areas.alimentacion.helpers.proc.proc_compute_nmax_diff import (
            proc_compute_nmax_diff,
        )
        ops = proc_compute_nmax_diff(tags_base, cfg, state)

    # Sin info de estado actual, no se generan ops (defensivo).
    assert ops == []
    assert any(
        "Parse FAIL" in record.message for record in caplog.records
    )


def test_proc_compute_nmax_diff_app_state_dimensiones_none(
    tags_base: Path, write_nmax_xml
) -> None:
    """Si ``app_state.dimensiones`` es None, trata como ``{}`` (mismo
    fallback que disp). Si ademas el XML tiene valores, retorna las ops
    correspondientes para rebajar a 0."""
    write_nmax_xml({"N_MAX_PREAL": 5})
    cfg = FakeConfig(active=["N_MAX_PREAL"])
    state = FakeAppState(None)  # explicit None

    with _patch_parser_returning({"N_MAX_PREAL": 5}):
        from areas.alimentacion.helpers.proc.proc_compute_nmax_diff import (
            proc_compute_nmax_diff,
        )
        ops = proc_compute_nmax_diff(tags_base, cfg, state)

    # dimensiones=None -> desired["N_MAX_PREAL"]=0; XML=5 -> diff.
    assert ops == [
        {"table_name": "000_Config_Dispositivos",
         "constant_name": "N_MAX_PREAL", "new_value": 0},
    ]
