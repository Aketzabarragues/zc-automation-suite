"""Tests para ``areas.alimentacion.data.data_Dispositivos``.

Fase 3, paso 3.2.2.  Cobertura:
  - Cada ``Disp*`` se construye con los 5 campos del Protocol y
    los defaults razonables (``str""``, ``int=0``, ``float=0.0``).
  - ``frozen=True``: no se puede mutar ninguna ``Disp*``.
  - ``Dispositivo`` es ``runtime_checkable``: ``isinstance(disp, Dispositivo)`` es True.
"""
from __future__ import annotations

import pytest

from areas.alimentacion.data.data_Dispositivos import (
    Dispositivo,
    DispED,
    DispEA,
    DispM,
    DispM_VF,
    DispSA,
    DispV,
)


# ── DispED ───────────────────────────────────────────────────────────────


def test_disp_ed_construccion_basica():
    """DispED acepta los 5 campos del Protocol + defaults tolerantes."""
    d = DispED(
        numero=1,
        plc_tag="ED_Motor_1",
        plc_comentario="Entrada digital motor 1",
        descripcion="Botonera marcha",
        uid="ED_001",
    )
    assert d.numero == 1
    assert d.plc_tag == "ED_Motor_1"
    assert d.uid == "ED_001"
    # Defaults
    assert d.e_byte == 0
    assert d.e_bit == 0
    assert d.comentario_db == ""


def test_disp_ed_isinstance_dispositivo():
    """``Dispositivo`` es ``runtime_checkable``: DispED lo satisface."""
    d = DispED(1, "tag", "com", "desc", "uid")
    assert isinstance(d, Dispositivo)


def test_disp_ed_frozen_no_muta():
    """``frozen=True``: asignar un campo levanta ``FrozenInstanceError``."""
    from dataclasses import FrozenInstanceError

    d = DispED(1, "tag", "com", "desc", "uid")
    with pytest.raises(FrozenInstanceError):
        d.numero = 99  # type: ignore[misc]


# ── DispEA / DispSA ─────────────────────────────────────────────────────


def test_disp_ea_construccion_basica():
    d = DispEA(1, "tag", "com", "desc", "uid", unidades="bar")
    assert d.unidades == "bar"
    assert d.rii == 0.0
    assert d.rsi == 0.0


def test_disp_ea_isinstance_dispositivo():
    d = DispEA(1, "tag", "com", "desc", "uid")
    assert isinstance(d, Dispositivo)


def test_disp_sa_construccion_basica():
    d = DispSA(1, "tag", "com", "desc", "uid")
    assert d.numero == 1
    assert d.rii == 0.0


def test_disp_sa_isinstance_dispositivo():
    d = DispSA(1, "tag", "com", "desc", "uid")
    assert isinstance(d, Dispositivo)


# ── DispV / DispM / DispM_VF ─────────────────────────────────────────────


def test_disp_v_construccion_basica():
    d = DispV(1, "tag", "com", "desc", "uid")
    assert d.rr_byte == 0
    assert d.rt_byte == 0
    assert isinstance(d, Dispositivo)


def test_disp_m_construccion_basica():
    d = DispM(1, "tag", "com", "desc", "uid")
    assert d.s_byte == 0
    assert d.rm_byte == 0
    assert isinstance(d, Dispositivo)


def test_disp_m_vf_campos_exclusivos_vfd():
    """DispM_VF anade ``sa_byte`` y ``cfg_byteanalogica`` a los campos de DispM."""
    d = DispM_VF(1, "tag", "com", "desc", "uid", sa_byte=42, cfg_byteanalogica="x")
    assert d.sa_byte == 42
    assert d.cfg_byteanalogica == "x"
    # Heredados de DispM.
    assert d.s_byte == 0
    assert d.rm_byte == 0


def test_disp_m_vf_isinstance_dispositivo():
    d = DispM_VF(1, "tag", "com", "desc", "uid")
    assert isinstance(d, Dispositivo)


# ── Defaults comunes ─────────────────────────────────────────────────────


def test_disp_defaults_str_vacios():
    """Los campos ``str`` tienen default ``""`` en todas las Disp*."""
    d_ed = DispED(1, "t", "c", "d", "u")
    d_ea = DispEA(1, "t", "c", "d", "u")
    d_sa = DispSA(1, "t", "c", "d", "u")
    d_v = DispV(1, "t", "c", "d", "u")
    d_m = DispM(1, "t", "c", "d", "u")
    d_vf = DispM_VF(1, "t", "c", "d", "u")

    for d in (d_ed, d_ea, d_sa, d_v, d_m, d_vf):
        assert d.tag == ""
        assert d.fat == ""
        assert d.cuadro == ""
        assert d.comentario_db == ""


def test_disp_defaults_int_cero():
    """Los campos ``int`` tienen default ``0`` en todas las Disp*."""
    d_ed = DispED(1, "t", "c", "d", "u")
    d_vf = DispM_VF(1, "t", "c", "d", "u")

    assert d_ed.gr_alarma == 0
    assert d_ed.hmi_index == 0
    assert d_vf.s_byte == 0
    assert d_vf.sa_byte == 0
