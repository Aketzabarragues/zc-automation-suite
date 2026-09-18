"""Tests de ``proc_compute_nmax_diff``: helper puro que difiere N_MAX
del proceso contra el estado exportado de TIA.

: reescritura tras el bug N_MAX diff=0. La version anterior
copiaba el patron de disp (tabla global); esta usa la tabla del
proceso (``slot_map.table_name``) + fail-fast si no esta exportada.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


# ────────────────────────────────────────────────────────────────────────
# Fakes
# ────────────────────────────────────────────────────────────────────────
class FakeSlotMap:
    """Replica ``DataProcSlotMap`` con los 4 campos que el helper usa."""

    def __init__(
        self,
        *,
        table_name: str = "100_CPR",
        nmax: dict[str, int] | None = None,
        nmax_names: dict[str, str] | None = None,
    ) -> None:
        self.table_name = table_name
        self.nmax = nmax if nmax is not None else {
            "preal": 5, "pint": 10, "alm": 8,
        }
        self.nmax_names = nmax_names if nmax_names is not None else {
            "preal": "100_N_MAX_PREAL",
            "pint": "100_N_MAX_PINT",
            "alm": "100_N_MAX_ALM",
        }


# ────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────
@pytest.fixture
def tags_base(tmp_path: Path) -> Path:
    return tmp_path


def _write_xml(tags_base: Path, table_name: str, content: str = "<root/>"):
    p = tags_base / f"{table_name}.xml"
    p.write_text(content, encoding="utf-8")
    return p


def _patch_parser_returning(values: dict[str, int]):
    return patch(
        "areas.alimentacion.helpers.xml.disp_tag_table_parser."
        "SimaticMLTagParser.parse_user_constants",
        return_value=values,
    )


# ────────────────────────────────────────────────────────────────────────
# Tests: diff correcto (happy paths)
# ────────────────────────────────────────────────────────────────────────
def test_proc_compute_nmax_diff_empty_when_no_changes(
    tags_base: Path,
) -> None:
    """Todos los N_MAX ya coinciden con current -> []."""
    sm = FakeSlotMap()
    _write_xml(tags_base, sm.table_name)
    with _patch_parser_returning({
        "100_N_MAX_PREAL": 5, "100_N_MAX_PINT": 10, "100_N_MAX_ALM": 8,
    }):
        from areas.alimentacion.helpers.proc.proc_compute_nmax_diff import (
            proc_compute_nmax_diff,
        )
        ops = proc_compute_nmax_diff(tags_base, proc_uid=100, slot_map=sm)

    assert ops == []


def test_proc_compute_nmax_diff_returns_diff_for_changed_values(
    tags_base: Path,
) -> None:
    """Solo los N_MAX cuyo valor difiere se incluyen."""
    sm = FakeSlotMap(nmax={"preal": 8, "pint": 10, "alm": 8})  # preal cambia
    _write_xml(tags_base, sm.table_name)
    with _patch_parser_returning({
        "100_N_MAX_PREAL": 5, "100_N_MAX_PINT": 10, "100_N_MAX_ALM": 8,
    }):
        from areas.alimentacion.helpers.proc.proc_compute_nmax_diff import (
            proc_compute_nmax_diff,
        )
        ops = proc_compute_nmax_diff(tags_base, proc_uid=100, slot_map=sm)

    assert ops == [{
        "table_name": "100_CPR",
        "constant_name": "100_N_MAX_PREAL",
        "new_value": 8,
    }]


def test_proc_compute_nmax_diff_uses_full_name_with_uid_prefix(
    tags_base: Path,
) -> None:
    """El constant_name retornado lleva el prefijo uid (forma completa TIA)."""
    sm = FakeSlotMap(
        table_name="50010_PRO_STD",
        nmax={"preal": 50},
        nmax_names={"preal": "50010_N_MAX_PREAL"},
    )
    _write_xml(tags_base, sm.table_name)
    with _patch_parser_returning({"50010_N_MAX_PREAL": 30}):
        from areas.alimentacion.helpers.proc.proc_compute_nmax_diff import (
            proc_compute_nmax_diff,
        )
        ops = proc_compute_nmax_diff(tags_base, proc_uid=50010, slot_map=sm)

    assert ops == [{
        "table_name": "50010_PRO_STD",
        "constant_name": "50010_N_MAX_PREAL",
        "new_value": 50,
    }]


def test_proc_compute_nmax_diff_returns_all_when_current_missing(
    tags_base: Path,
) -> None:
    """Si la tabla esta recien creada (current sin entradas), todas las
    desired != current(None) cuentan como diff. Sanity: 3 ops (preal
    cambia 5->8, pint nuevo, alm nuevo)."""
    sm = FakeSlotMap(nmax={"preal": 8, "pint": 10, "alm": 8})
    _write_xml(tags_base, sm.table_name)
    # current SOLO tiene preal (los demas faltan -> recien creados).
    with _patch_parser_returning({"100_N_MAX_PREAL": 5}):
        from areas.alimentacion.helpers.proc.proc_compute_nmax_diff import (
            proc_compute_nmax_diff,
        )
        ops = proc_compute_nmax_diff(tags_base, proc_uid=100, slot_map=sm)

    # 3 ops: preal cambia (5->8), pint nuevo, alm nuevo.
    assert len(ops) == 3
    by_name = {o["constant_name"]: o for o in ops}
    assert by_name["100_N_MAX_PREAL"]["new_value"] == 8
    assert by_name["100_N_MAX_PINT"]["new_value"] == 10
    assert by_name["100_N_MAX_ALM"]["new_value"] == 8


def test_proc_compute_nmax_diff_skips_kind_without_nmax_name(
    tags_base: Path,
    caplog,
) -> None:
    """Si un kind no tiene entry en nmax_names, se ignora con warning."""
    sm = FakeSlotMap()
    sm.nmax["orphan"] = 7  # kind sin nmax_name
    _write_xml(tags_base, sm.table_name)
    with _patch_parser_returning({
        "100_N_MAX_PREAL": 5, "100_N_MAX_PINT": 10, "100_N_MAX_ALM": 8,
    }):
        from areas.alimentacion.helpers.proc.proc_compute_nmax_diff import (
            proc_compute_nmax_diff,
        )
        ops = proc_compute_nmax_diff(tags_base, proc_uid=100, slot_map=sm)

    # Solo preal/pint/alm, no orphan.
    assert len(ops) == 0
    assert any(
        "orphan" in record.message for record in caplog.records
    )


def test_proc_compute_nmax_diff_includes_alm_hmi(
    tags_base: Path,
) -> None:
    """: 4to N_MAX ``alm_hmi`` (excelente de la columna
    ``Alarmas_Hmi`` del Excel, PlcUserConstant ``<uid>_N_MAX_ALM_HMI``).

    Mismo patron data-driven: si desired != current, se anyade como
    op; si coinciden, no aparece (sync_nmax aplica con lista vacia).
    """
    sm = FakeSlotMap(
        table_name="100_CPR",
        nmax={
            "preal":   5,
            "pint":    10,
            "alm":     8,
            "alm_hmi": 6,
        },
        nmax_names={
            "preal":   "100_N_MAX_PREAL",
            "pint":    "100_N_MAX_PINT",
            "alm":     "100_N_MAX_ALM",
            "alm_hmi": "100_N_MAX_ALM_HMI",
        },
    )
    _write_xml(tags_base, sm.table_name)
    # Current: solo preal coincide con desired. alm_hmi difiere
    # (current=4 vs desired=6), pint y alm faltan (recien creadas).
    with _patch_parser_returning({
        "100_N_MAX_PREAL": 5,
        "100_N_MAX_ALM_HMI": 4,
    }):
        from areas.alimentacion.helpers.proc.proc_compute_nmax_diff import (
            proc_compute_nmax_diff,
        )
        ops = proc_compute_nmax_diff(tags_base, proc_uid=100, slot_map=sm)

    # 3 ops (preal OK -> skip, alm_hmi diff, pint nuevo, alm nuevo).
    names = {o["constant_name"] for o in ops}
    assert "100_N_MAX_PREAL" not in names  # sin cambios
    assert "100_N_MAX_ALM_HMI" in names
    assert "100_N_MAX_PINT" in names
    assert "100_N_MAX_ALM" in names
    # Verifica valor de alm_hmi especificamente.
    alm_hmi_op = next(o for o in ops
                      if o["constant_name"] == "100_N_MAX_ALM_HMI")
    assert alm_hmi_op == {
        "table_name":   "100_CPR",
        "constant_name": "100_N_MAX_ALM_HMI",
        "new_value":    6,
    }


# ────────────────────────────────────────────────────────────────────────
# Tests: FAIL-FAST
# ────────────────────────────────────────────────────────────────────────
def test_proc_compute_nmax_diff_raises_when_xml_missing(
    tags_base: Path,
) -> None:
    """Si la tabla del proceso no esta exportada en tags_base (ni en
    raiz ni en subdirs como ``Tags/`` de TIA V21) -> RuntimeError."""
    sm = FakeSlotMap()
    # tags_base vacio: no creamos el XML en ningun sitio.
    from areas.alimentacion.helpers.proc.proc_compute_nmax_diff import (
        proc_compute_nmax_diff,
    )
    with pytest.raises(RuntimeError, match="preview"):
        proc_compute_nmax_diff(tags_base, proc_uid=100, slot_map=sm)


def test_proc_compute_nmax_diff_finds_xml_in_tags_subdir(
    tags_base: Path,
) -> None:
    """TIA V21 con keep_folder_structure=True deposita el .xml en
    un subdirectorio ``Tags/``. El helper debe encontrarlo via el
    fallback rglob de ``XmlTarget`` (no solo en raiz directa).

    : bug que rompio el sync en vivo. Preview funcionaba
    porque usa ``XmlTarget``; sync fallaba porque buscaba directo.
    """
    sm = FakeSlotMap(
        nmax={"preal": 5},  # Solo esta activa; el slot que difiere.
        nmax_names={"preal": "100_N_MAX_PREAL"},
    )
    # Simulamos TIA V21: archivo en subdir Tags/.
    tags_subdir = tags_base / "Tags"
    tags_subdir.mkdir(parents=True, exist_ok=True)
    xml_path = tags_subdir / f"{sm.table_name}.xml"
    xml_path.write_text("<root/>", encoding="utf-8")

    with _patch_parser_returning({}):
        from areas.alimentacion.helpers.proc.proc_compute_nmax_diff import (
            proc_compute_nmax_diff,
        )
        ops = proc_compute_nmax_diff(tags_base, proc_uid=100, slot_map=sm)

    # Encontro el archivo en Tags/ (gracias al rglob) y computo el diff.
    # current={} (no habia slot todavia), desired=5 -> op de crear.
    assert ops == [{
        "table_name": "100_CPR",
        "constant_name": "100_N_MAX_PREAL",
        "new_value": 5,
    }]


def test_proc_compute_nmax_diff_raises_when_slot_map_none(
    tags_base: Path,
) -> None:
    """slot_map=None -> RuntimeError claro."""
    from areas.alimentacion.helpers.proc.proc_compute_nmax_diff import (
        proc_compute_nmax_diff,
    )
    with pytest.raises(RuntimeError, match="slot_map es None"):
        proc_compute_nmax_diff(tags_base, proc_uid=100, slot_map=None)


def test_proc_compute_nmax_diff_raises_when_table_name_empty(
    tags_base: Path,
) -> None:
    """slot_map.table_name vacio -> RuntimeError (proc_uid no existe)."""
    sm = FakeSlotMap(table_name="")
    from areas.alimentacion.helpers.proc.proc_compute_nmax_diff import (
        proc_compute_nmax_diff,
    )
    with pytest.raises(RuntimeError, match="proc_uid=100"):
        proc_compute_nmax_diff(tags_base, proc_uid=100, slot_map=sm)


def test_proc_compute_nmax_diff_raises_when_nmax_names_empty(
    tags_base: Path,
) -> None:
    """nmax_names vacio -> RuntimeError (config sin suffixes)."""
    sm = FakeSlotMap(nmax_names={})
    _write_xml(tags_base, sm.table_name)
    from areas.alimentacion.helpers.proc.proc_compute_nmax_diff import (
        proc_compute_nmax_diff,
    )
    with pytest.raises(RuntimeError, match="n_max_suffixes"):
        proc_compute_nmax_diff(tags_base, proc_uid=100, slot_map=sm)


def test_proc_compute_nmax_diff_raises_on_parse_error(
    tags_base: Path,
) -> None:
    """Si el parser falla, el helper propaga RuntimeError (no retorna vacio)."""
    sm = FakeSlotMap()
    _write_xml(tags_base, sm.table_name)
    from areas.alimentacion.helpers.proc.proc_compute_nmax_diff import (
        proc_compute_nmax_diff,
    )
    with patch(
        "areas.alimentacion.helpers.xml.disp_tag_table_parser."
        "SimaticMLTagParser.parse_user_constants",
        side_effect=RuntimeError("XML corrupto"),
    ), pytest.raises(RuntimeError, match="parseo de"):
        proc_compute_nmax_diff(tags_base, proc_uid=100, slot_map=sm)
