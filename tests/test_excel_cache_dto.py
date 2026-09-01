"""Tests de los DTOs del Excel (``excel_cache.py``) consolidados en Fase 5.

Cubre:
  * ``frozen=True`` y ``hash`` de las 6 dataclasses de dispositivos
    (``DispED``/``EA``/``SA``/``V``/``M``/``M_VF``).
  * ``DimensionesDispositivos``: ``values()``, ``all_nmax()``,
    ``to_api_dict()``, ``get()``, ``from_catalog()``.
  * ``Protocol Dispositivo`` con ``@runtime_checkable``:
    ``isinstance(DispED(...), Dispositivo) is True``.
  * ``ExcelCache`` (DTO raíz): ``to_dict()`` con las 4 listas +
    flag; ``software_parsers_implemented=True`` por default;
    ``frozen=True``.
  * Coexistencia de los 4 DTOs de software (ProcesoPLC, ParamRealPLC,
    ParamIntPLC, AlarmaPLC) en el mismo módulo.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from areas.alimentacion.domain.models.excel_cache import (
    AlarmaPLC,
    DimensionesDispositivos,
    DispEA,
    DispED,
    DispM,
    DispM_VF,
    DispSA,
    DispV,
    Dispositivo,
    ExcelCache,
    ParamIntPLC,
    ParamRealPLC,
    ProcesoPLC,
)


# ── DispED ──────────────────────────────────────────────────────────────


def test_disp_ed_is_frozen() -> None:
    """``DispED`` es inmutable: intentar mutar un atributo lanza."""
    d = DispED(numero=1, plc_tag="V_ED_001", plc_comentario="c",
               descripcion="d", uid="ED_001")
    with pytest.raises(Exception):  # FrozenInstanceError subclass of AttributeError
        d.numero = 99  # type: ignore[misc]


def test_disp_ed_equality_and_hash() -> None:
    """Dos ``DispED`` con mismos campos son iguales y tienen mismo hash."""
    a = DispED(numero=1, plc_tag="V_ED_001", plc_comentario="c",
               descripcion="d", uid="ED_001", tag="T", fat="F")
    b = DispED(numero=1, plc_tag="V_ED_001", plc_comentario="c",
               descripcion="d", uid="ED_001", tag="T", fat="F")
    assert a == b
    assert hash(a) == hash(b)


def test_disp_ed_satisfies_protocol() -> None:
    """``DispED`` satisface estructuralmente el ``Protocol Dispositivo``."""
    d = DispED(numero=1, plc_tag="V_ED_001", plc_comentario="c",
               descripcion="d", uid="ED_001")
    assert isinstance(d, Dispositivo)


def test_disp_ed_defaults() -> None:
    """Los campos no obligatorios tienen defaults tolerantes."""
    d = DispED(numero=1, plc_tag="X", plc_comentario="X",
               descripcion="X", uid="X")
    assert d.tag == ""
    assert d.fat == ""
    assert d.e_byte == 0
    assert d.e_bit == 0
    assert d.gr_alarma == 0
    assert d.cuadro == ""
    assert d.observaciones == ""
    assert d.plc_tipo == ""
    assert d.plc_index == 0
    assert d.hmi_index == 0
    assert d.hmi_texto == ""
    assert d.cfg_habilitar == ""
    assert d.cfg_byte_entrada == ""
    assert d.cfg_bit_entrada == ""
    assert d.cfg_grupo_alarma == ""
    assert d.comentario_db == ""


# ── DispEA / DispSA ─────────────────────────────────────────────────────


def test_disp_ea_has_float_rii_rsi() -> None:
    """``DispEA`` tiene ``rii`` y ``rsi`` como ``float``."""
    d = DispEA(numero=1, plc_tag="X", plc_comentario="X",
               descripcion="X", uid="X",
               rii=1.5, rsi=10.0)
    assert d.rii == 1.5
    assert d.rsi == 10.0
    assert isinstance(d.rii, float)
    assert isinstance(d.rsi, float)


def test_disp_sa_satisfies_protocol() -> None:
    """``DispSA`` también satisface el Protocol (estructura idéntica a EA)."""
    d = DispSA(numero=1, plc_tag="X", plc_comentario="X",
               descripcion="X", uid="X")
    assert isinstance(d, Dispositivo)


# ── DispV / DispM / DispM_VF ────────────────────────────────────────────


def test_disp_v_rr_rt_fields() -> None:
    """``DispV`` tiene los 4 campos específicos de retorno."""
    d = DispV(numero=1, plc_tag="X", plc_comentario="X",
              descripcion="X", uid="X",
              rr_byte=0, rr_bit=1, rt_byte=2, rt_bit=3)
    assert d.rr_byte == 0
    assert d.rr_bit == 1
    assert d.rt_byte == 2
    assert d.rt_bit == 3


def test_disp_m_satisfies_protocol() -> None:
    """``DispM`` satisface el Protocol."""
    d = DispM(numero=1, plc_tag="X", plc_comentario="X",
              descripcion="X", uid="X")
    assert isinstance(d, Dispositivo)


def test_disp_m_vf_has_sa_byte_and_cfg_byteanalogica() -> None:
    """``DispM_VF`` añade ``sa_byte`` y ``cfg_byteanalogica`` exclusivos."""
    d = DispM_VF(numero=1, plc_tag="X", plc_comentario="X",
                  descripcion="X", uid="X",
                  sa_byte=42, cfg_byteanalogica="line := 1;")
    assert d.sa_byte == 42
    assert d.cfg_byteanalogica == "line := 1;"


# ── DimensionesDispositivos ─────────────────────────────────────────────


def test_dimensiones_defaults_are_zero() -> None:
    """Sin argumentos, los 6 canónicos son 0 y ``extras`` está vacío."""
    d = DimensionesDispositivos()
    assert d.num_disp_ed == 0
    assert d.num_disp_ea == 0
    assert d.num_disp_sa == 0
    assert d.num_disp_v == 0
    assert d.num_disp_m == 0
    assert d.num_disp_m_vf == 0
    assert dict(d.extras) == {}


def test_dimensiones_values_returns_canonical_nmax_names() -> None:
    """``values()`` devuelve ``{N_MAX_DISP_X: count}`` para los 6."""
    d = DimensionesDispositivos(
        num_disp_ed=10, num_disp_ea=20, num_disp_sa=30,
        num_disp_v=40, num_disp_m=50, num_disp_m_vf=60,
    )
    v = d.values()
    assert v == {
        "N_MAX_DISP_ED": 10,
        "N_MAX_DISP_EA": 20,
        "N_MAX_DISP_SA": 30,
        "N_MAX_DISP_V": 40,
        "N_MAX_DISP_M": 50,
        "N_MAX_DISP_M_VF": 60,
    }


def test_dimensiones_all_nmax_includes_extras() -> None:
    """``all_nmax()`` = ``values()`` ∪ ``extras`` (extras gana si colisión)."""
    d = DimensionesDispositivos(
        num_disp_ed=10, num_disp_v=20,
        extras={"N_MAX_DISP_FF": 99, "N_MAX_DISP_ED": 1000},
    )
    all_n = d.all_nmax()
    assert all_n["N_MAX_DISP_FF"] == 99
    assert all_n["N_MAX_DISP_ED"] == 1000  # extras gana


def test_dimensiones_to_api_dict_hides_extras() -> None:
    """``to_api_dict()`` oculta ``extras`` (contrato del API)."""
    d = DimensionesDispositivos(
        num_disp_ed=10, num_disp_v=20,
        extras={"N_MAX_DISP_FF": 99},
    )
    api = d.to_api_dict()
    assert api == {
        "num_disp_ed": 10,
        "num_disp_ea": 0,
        "num_disp_sa": 0,
        "num_disp_v": 20,
        "num_disp_m": 0,
        "num_disp_m_vf": 0,
    }
    assert "extras" not in api
    assert "N_MAX_DISP_FF" not in api


def test_dimensiones_get_supports_canonical_and_legacy_names() -> None:
    """``get()`` acepta tanto el nombre canónico como el legacy."""
    d = DimensionesDispositivos(num_disp_ed=10)
    assert d.get("N_MAX_DISP_ED") == 10
    assert d.get("num_disp_ed") == 10
    assert d.get("N_MAX_DISP_FF") is None


def test_dimensiones_get_with_extras() -> None:
    """``get()`` también consulta ``extras``."""
    d = DimensionesDispositivos(extras={"N_MAX_DISP_FF": 99})
    assert d.get("N_MAX_DISP_FF") == 99


def test_dimensiones_from_catalog_no_catalog() -> None:
    """``from_catalog(None, raw)`` → acepta todo, legacy a campos, resto a extras."""
    raw = {
        "N_MAX_DISP_ED": 10,
        "N_MAX_DISP_V": 20,
        "N_MAX_DISP_FF": 30,
    }
    d = DimensionesDispositivos.from_catalog(None, raw)
    assert d.num_disp_ed == 10
    assert d.num_disp_v == 20
    assert d.extras.get("N_MAX_DISP_FF") == 30


def test_dimensiones_from_catalog_with_catalog() -> None:
    """``from_catalog(catalog, raw)`` → descarta claves no listadas en catalog."""
    catalog = [
        {"name": "N_MAX_DISP_ED", "hw_type": "ed"},
        {"name": "N_MAX_DISP_V",  "hw_type": "v"},
    ]
    raw = {
        "N_MAX_DISP_ED": 10,
        "N_MAX_DISP_V": 20,
        "N_MAX_DISP_FF": 30,  # no está en catalog → descartado
    }
    d = DimensionesDispositivos.from_catalog(catalog, raw)
    assert d.num_disp_ed == 10
    assert d.num_disp_v == 20
    # No debe haber acabado en extras
    assert "N_MAX_DISP_FF" not in d.extras


def test_dimensiones_is_frozen() -> None:
    """``DimensionesDispositivos`` es inmutable."""
    d = DimensionesDispositivos(num_disp_ed=10)
    with pytest.raises(Exception):
        d.num_disp_ed = 99  # type: ignore[misc]


# ── ExcelCache (DTO raíz) ───────────────────────────────────────────────


def _make_minimal_cache() -> ExcelCache:
    """Helper: cache mínimo con todos los campos requeridos."""
    d_ed = DispED(numero=1, plc_tag="V_ED_001", plc_comentario="c",
                  descripcion="d", uid="ED_001")
    d_ea = DispEA(numero=1, plc_tag="V_EA_001", plc_comentario="c",
                  descripcion="d", uid="EA_001")
    p = ProcesoPLC(uid=1, nombre="P1", codigo="PR1", alarmas=16)
    pr = ParamRealPLC(uid="PR_1_001", numero="001", proceso="P1",
                      codigo="PR1", num_db=3001, producto="X", tipo="S",
                      descripcion="d", comentario_db="c", visibilidad="Si",
                      num_lista=1, txt_lista="T")
    pi = ParamIntPLC(uid="PI_1_001", numero="001", proceso="P1",
                     codigo="PR1", num_db=3002, producto="X", tipo="C",
                     descripcion="d", comentario_db="c", visibilidad="Si",
                     num_lista="TODOS", txt_lista="T")
    al = AlarmaPLC(uid="AL_1_001", numero="001", proceso="P1",
                   num_db=5001, descripcion="d", comentario_db="c")
    return ExcelCache(
        excel_path="/tmp/test.xlsx",
        excel_mtime_ns=1234567890,
        parsed_at=datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc),
        dispositivos={
            "ed": (d_ed,),
            "ea": (d_ea,),
            "sa": (),
            "v":  (),
            "m":  (),
            "m_vf": (),
        },
        n_max=DimensionesDispositivos(num_disp_ed=10, num_disp_ea=20),
        procesos=(p,),
        parametros_real=(pr,),
        parametros_int=(pi,),
        alarmas=(al,),
        procesos_by_codigo={"PR1": p},
        parametros_real_by_codigo={"PR1": pr},
        parametros_int_by_codigo={"PR1": pi},
    )


def test_excel_cache_is_frozen() -> None:
    """``ExcelCache`` es inmutable."""
    cache = _make_minimal_cache()
    with pytest.raises(Exception):
        cache.excel_path = "/otro.xlsx"  # type: ignore[misc]


def test_excel_cache_software_parsers_implemented_default_true() -> None:
    """El flag ``software_parsers_implemented`` es ``True`` por default."""
    cache = _make_minimal_cache()
    assert cache.software_parsers_implemented is True


def test_excel_cache_to_dict_includes_all_lists() -> None:
    """``to_dict()`` incluye las 4 listas serializadas y el flag."""
    import json

    cache = _make_minimal_cache()
    d = cache.to_dict()
    assert "excel_path" in d
    assert "excel_mtime_ns" in d
    assert "parsed_at" in d
    assert "n_max" in d
    assert "procesos" in d
    assert "parametros_real" in d
    assert "parametros_int" in d
    assert "alarmas" in d
    assert "software_parsers_implemented" in d
    assert d["software_parsers_implemented"] is True
    assert len(d["procesos"]) == 1
    assert len(d["parametros_real"]) == 1
    assert len(d["parametros_int"]) == 1
    assert len(d["alarmas"]) == 1
    # El dict es JSON-serializable
    json.dumps(d)


def test_excel_cache_to_dict_lookups_omitted() -> None:
    """``to_dict()`` NO incluye los lookups precomputados (son derivables)."""
    cache = _make_minimal_cache()
    d = cache.to_dict()
    assert "procesos_by_codigo" not in d
    assert "parametros_real_by_codigo" not in d
    assert "parametros_int_by_codigo" not in d


def test_excel_cache_n_max_in_to_dict_hides_extras() -> None:
    """``to_dict()`` aplica ``to_api_dict()`` al ``n_max`` (oculta ``extras``)."""
    cache = _make_minimal_cache()
    d = cache.to_dict()
    assert "extras" not in d["n_max"]
    # Solo los 6 legacy en el shape del API
    assert set(d["n_max"].keys()) == {
        "num_disp_ed", "num_disp_ea", "num_disp_sa",
        "num_disp_v", "num_disp_m", "num_disp_m_vf",
    }


# ── Coexistencia de los 4 DTOs de software ──────────────────────────────


def test_software_dtos_coexist_in_excel_cache() -> None:
    """Los 4 DTOs de software están en el mismo módulo ``excel_cache``."""
    # Todos importables y usables.
    p = ProcesoPLC(uid=1, nombre="P1", codigo="PR1")
    pr = ParamRealPLC(uid="PR_1_001", numero="001", proceso="P1",
                      codigo="PR1", num_db=3001, producto="X", tipo="S",
                      descripcion="d", comentario_db="c", visibilidad="Si",
                      num_lista=1, txt_lista="T")
    pi = ParamIntPLC(uid="PI_1_001", numero="001", proceso="P1",
                     codigo="PR1", num_db=3002, producto="X", tipo="C",
                     descripcion="d", comentario_db="c", visibilidad="Si",
                     num_lista=0, txt_lista="T")
    al = AlarmaPLC(uid="AL_1_001", numero="001", proceso="P1",
                   num_db=5001, descripcion="d", comentario_db="c")
    # Propiedades siguen funcionando en ``ProcesoPLC``.
    assert p.db_preal_numero == 3001
    assert p.db_alm_numero == 5001
    assert p.alm_hmi == 0  # sin alarmas
    # ``num_lista`` acepta ``int|str``.
    assert pr.num_lista == 1
    assert pi.num_lista == 0


def test_proceso_plc_alm_hmi_cases() -> None:
    """``ProcesoPLC.alm_hmi`` cubre los casos borde según la fórmula.

    Fórmula: ``max(0, alarmas // 16 - 1)``.
        * ``alarmas = 0``  → ``max(0, -1) = 0`` (sin alarmas).
        * ``alarmas = 1``  → ``max(0, -1) = 0`` (palabra 0).
        * ``alarmas = 16`` → ``max(0, 0) = 0`` (palabra 0).
        * ``alarmas = 17`` → ``max(0, 0) = 0`` (palabra 0).
        * ``alarmas = 32`` → ``max(0, 1) = 1`` (palabra 1).
        * ``alarmas = 100`` → ``max(0, 5) = 5`` (palabra 5).
    """
    assert ProcesoPLC(uid=1, nombre="P", codigo="C", alarmas=0).alm_hmi == 0
    assert ProcesoPLC(uid=1, nombre="P", codigo="C", alarmas=1).alm_hmi == 0
    assert ProcesoPLC(uid=1, nombre="P", codigo="C", alarmas=16).alm_hmi == 0
    assert ProcesoPLC(uid=1, nombre="P", codigo="C", alarmas=17).alm_hmi == 0
    assert ProcesoPLC(uid=1, nombre="P", codigo="C", alarmas=32).alm_hmi == 1
    assert ProcesoPLC(uid=1, nombre="P", codigo="C", alarmas=100).alm_hmi == 5
