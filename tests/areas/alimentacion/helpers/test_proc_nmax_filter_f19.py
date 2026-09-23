"""Tests del filtro N_MAX de ``compute_nmax_diff_for_proc``.

Cubre el bug F19 step 1: el filtro ``if k in nmax_names`` comparaba
nombres TIA del XML con kinds del Excel (las keys del dict), no
con nombres TIA canónicos (los values). Resultado: ``current_filtered``
quedaba vacio aunque el XML tuviese los 4 N_MAX correctos.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from areas.alimentacion.helpers.proc.proc_db_generar_preview import (
    NmaxDiff,
    compute_nmax_diff_for_proc,
)


def _xml(path: Path) -> Path:
    return path


def test_filtro_xml_con_nmax_match_no_empty_current_filtered():
    """XML tiene los 4 N_MAX correctos + valores coherentes con desired.

    Esperado: todos los ``status='sin_cambios'`` y ``current_filtered``
    tiene los 4 valores reales. Caso del bug Aketza en F19.
    """
    raw = {
        "50010_N_MAX_PINT": 15,
        "50010_N_MAX_PREAL": 3,
        "50010_N_MAX_ALM": 64,
        "50010_N_MAX_ALM_HMI": 3,
        # Etapas que NO son N_MAX (no cuentan):
        "50010_ETAPA_0": 0,
        "50010_ETAPA_1": 1,
    }
    nmax_names = {
        "preal": "50010_N_MAX_PREAL",
        "pint": "50010_N_MAX_PINT",
        "alm": "50010_N_MAX_ALM",
        "alm_hmi": "50010_N_MAX_ALM_HMI",
    }
    nmax_desired = {"preal": 3, "pint": 15, "alm": 64, "alm_hmi": 3}

    with patch(
        "areas.alimentacion.helpers.proc.proc_db_generar_preview._read_nmax_xml",
        return_value=(raw, None),
    ):
        diff = compute_nmax_diff_for_proc(
            table_name="50010_PRO_STD",
            nmax_names=nmax_names,
            nmax_desired=nmax_desired,
            xml_path=_xml(Path("/fake/50010_PRO_STD.xml")),
        )

    assert diff.missing_xml is False
    assert diff.current == {
        "50010_N_MAX_PREAL": 3,
        "50010_N_MAX_PINT": 15,
        "50010_N_MAX_ALM": 64,
        "50010_N_MAX_ALM_HMI": 3,
    }
    assert diff.desired == diff.current
    assert diff.summary == {
        "actualizar": 0,
        "sin_cambios": 4,
        "total": 4,
    }
    for todo in diff.todos:
        assert todo["status"] == "sin_cambios", todo
        assert todo["actual"] is not None, todo
        assert todo["actual"] == todo["nuevo"], todo


def test_filtro_xml_con_nmax_mismatch_genera_todos_con_actualizar():
    """XML tiene valores distintos al desired.

    Esperado: ``status='actualizar'`` para los 4, ``actual`` distinto
    de ``nuevo``. (El caso real de Aketza era este: el filtro
    mal ponia ``actual=None`` aunque el XML tuviese los valores.)
    """
    raw = {
        "50010_N_MAX_PREAL": 0,
        "50010_N_MAX_PINT": 0,
        "50010_N_MAX_ALM": 0,
        "50010_N_MAX_ALM_HMI": 0,
    }
    nmax_names = {
        "preal": "50010_N_MAX_PREAL",
        "pint": "50010_N_MAX_PINT",
        "alm": "50010_N_MAX_ALM",
        "alm_hmi": "50010_N_MAX_ALM_HMI",
    }
    nmax_desired = {"preal": 3, "pint": 15, "alm": 64, "alm_hmi": 3}

    with patch(
        "areas.alimentacion.helpers.proc.proc_db_generar_preview._read_nmax_xml",
        return_value=(raw, None),
    ):
        diff = compute_nmax_diff_for_proc(
            table_name="50010_PRO_STD",
            nmax_names=nmax_names,
            nmax_desired=nmax_desired,
            xml_path=_xml(Path("/fake/50010_PRO_STD.xml")),
        )

    assert diff.missing_xml is False
    for todo in diff.todos:
        assert todo["status"] == "actualizar", todo
        assert todo["actual"] == 0, todo
        assert todo["nuevo"] in {3, 15, 64}, todo
    assert diff.summary["actualizar"] == 4
    assert diff.summary["sin_cambios"] == 0


def test_filtro_xml_sin_constantes_genera_todos_con_actual_y_actual_none():
    """XML no tiene ninguno de los 4 N_MAX que el config dice.

    Esperado (caso F19 step 1 original bug): ``current_filtered = {}``
    Y ``actual = None`` para cada todo, ``status = 'actualizar'``. Esto
    es la firma del bug pre-fix: el log decia '4 N_MAX actualizar' y la
    SPA mostraba '?' aunque el XML tuviese esos nombres.
    """
    raw = {"50010_ETAPA_0": 0}  # No incluye los 4 N_MAX del config
    nmax_names = {
        "preal": "50010_N_MAX_PREAL",
        "pint": "50010_N_MAX_PINT",
        "alm": "50010_N_MAX_ALM",
        "alm_hmi": "50010_N_MAX_ALM_HMI",
    }
    nmax_desired = {"preal": 3, "pint": 15, "alm": 64, "alm_hmi": 3}

    with patch(
        "areas.alimentacion.helpers.proc.proc_db_generar_preview._read_nmax_xml",
        return_value=(raw, None),
    ):
        diff = compute_nmax_diff_for_proc(
            table_name="50010_PRO_STD",
            nmax_names=nmax_names,
            nmax_desired=nmax_desired,
            xml_path=_xml(Path("/fake/50010_PRO_STD.xml")),
        )

    assert diff.missing_xml is False
    assert diff.current == {}  # <-- Bug F19: pre-fix daba current={} tambien
    # En realidad esto es lo CORRECTO post-fix: si el XML no tiene esos
    # nombres, current esta vacio. La DIFFERENCIA con el bug es que el
    # log mostraria '4 N_MAX actualizar' (correcto) y la SPA mostraria
    # '? -> NUEVO' (correcto: "slot no existe en TIA, se crea").
    for todo in diff.todos:
        assert todo["status"] == "actualizar", todo
        assert todo["actual"] is None, todo  # <-- not None significaba bug
        assert todo["nuevo"] in {3, 15, 64}, todo


def test_filtro_xml_missing_quiere_decir_todos_empty_con_missing_flag():
    """XML no existe (missing_xml=True) → todos=[], error_message=None."""
    nmax_names = {"preal": "50010_N_MAX_PREAL"}
    nmax_desired = {"preal": 3}

    with patch(
        "areas.alimentacion.helpers.proc.proc_db_generar_preview._read_nmax_xml",
        return_value=({}, "XML de N_MAX no encontrado en TIA export"),
    ):
        diff = compute_nmax_diff_for_proc(
            table_name="50010_PRO_STD",
            nmax_names=nmax_names,
            nmax_desired=nmax_desired,
            xml_path=_xml(Path("/fake/50010_PRO_STD.xml")),
        )

    assert diff.missing_xml is True
    assert diff.todos == []
    assert diff.summary == {"actualizar": 0, "sin_cambios": 1, "total": 1}
    assert diff.desired == {"50010_N_MAX_PREAL": 3}


def test_filtro_no_case_sensitive_en_nombres():
    """Nombres con distinta capitalizacion NO hacen match
    (TIA exporta lo que tiene, sin normalizar). Comportamiento
    esperado: el filtro set-based no normaliza, asi que NO hay
    match → ``current_filtered={}``, ``actual=None``, ``status='actualizar'``.
    """
    raw = {
        "50010_n_max_preal": 3,  # TIA usa minusculas
    }
    nmax_names = {
        "preal": "50010_N_MAX_PREAL",  # config dice mayusculas
    }
    nmax_desired = {"preal": 3}

    with patch(
        "areas.alimentacion.helpers.proc.proc_db_generar_preview._read_nmax_xml",
        return_value=(raw, None),
    ):
        diff = compute_nmax_diff_for_proc(
            table_name="50010_PRO_STD",
            nmax_names=nmax_names,
            nmax_desired=nmax_desired,
            xml_path=_xml(Path("/fake/50010_PRO_STD.xml")),
        )

    assert diff.current == {}
    assert len(diff.todos) == 1
    assert diff.todos[0]["status"] == "actualizar"
    assert diff.todos[0]["actual"] is None  # key no presente → None
    assert diff.todos[0]["nuevo"] == 3
    assert diff.summary == {"actualizar": 1, "sin_cambios": 0, "total": 1}
