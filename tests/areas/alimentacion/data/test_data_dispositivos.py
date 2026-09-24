"""Tests para ``areas.alimentacion.data.data_dispositivos``.

Fase 3, paso 3.2.2.  Cobertura:
  - Cada ``Disp*`` se construye con los 5 campos del Protocol y
    los defaults razonables (``str""``, ``int=0``, ``float=0.0``).
  - ``frozen=True``: no se puede mutar ninguna ``Disp*``.
  - ``Dispositivo`` es ``runtime_checkable``: ``isinstance(disp, Dispositivo)`` es True.
"""
from __future__ import annotations

import pytest

from areas.alimentacion.data.data_dispositivos import (
    Dispositivo,
    DispED,
    DispEA,
    DispM,
    DispMSINA,
    DispM_VF,
    DispSA,
    DispTOT,
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


# ── DispMSINA ──────────────────────────────────────────────────────


def test_disp_msina_construccion_basica():
    """DispMSINA acepta los 5 campos del Protocol + defaults tolerantes."""
    d = DispMSINA(
        numero=1,
        plc_tag="MSINA_Motor_1",
        plc_comentario="Motor sinamics 1",
        descripcion="Variador bomba",
        uid="MSINA_001",
    )
    assert d.numero == 1
    assert d.plc_tag == "MSINA_Motor_1"
    assert d.uid == "MSINA_001"
    # Defaults analogicos.
    assert d.vel_min == 0.0
    assert d.vel_max == 0.0
    assert d.cons_k == 0.0
    # Defaults digitales (solo RT, no S/RM/SA).
    assert d.rt_byte == 0
    assert d.rt_bit == 0
    # Defaults str vacios.
    assert d.cfg_vel_min == ""
    assert d.cfg_vel_max == ""
    assert d.cfg_cons_k == ""
    assert d.comentario_db == ""


def test_disp_msina_campos_analogicos_populados():
    """DispMSINA persiste vel_min/vel_max/cons_k cuando se setean."""
    d = DispMSINA(
        1, "tag", "com", "desc", "uid",
        vel_min=10.5, vel_max=50.0, cons_k=0.85,
    )
    assert d.vel_min == 10.5
    assert d.vel_max == 50.0
    assert d.cons_k == 0.85


def test_disp_msina_isinstance_dispositivo():
    """``Dispositivo`` es ``runtime_checkable``: DispMSINA lo satisface."""
    d = DispMSINA(1, "tag", "com", "desc", "uid")
    assert isinstance(d, Dispositivo)


def test_disp_msina_frozen_no_muta():
    """``frozen=True``: asignar un campo levanta ``FrozenInstanceError``."""
    from dataclasses import FrozenInstanceError

    d = DispMSINA(1, "tag", "com", "desc", "uid")
    with pytest.raises(FrozenInstanceError):
        d.numero = 99  # type: ignore[misc]


def test_disp_msina_no_tiene_campos_digitales():
    """DispMSINA NO tiene S/RM/SA: solo RT (sin salida ni confirm. de marcha)."""
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(DispMSINA)}
    assert "s_byte" not in field_names
    assert "s_bit" not in field_names
    assert "rm_byte" not in field_names
    assert "rm_bit" not in field_names
    assert "sa_byte" not in field_names


# ── DispTOT ──────────────────────────────────────────────────────


def test_disp_tot_construccion_basica():
    """DispTOT acepta los 5 campos del Protocol + defaults tolerantes."""
    d = DispTOT(
        numero=1,
        plc_tag="V_TOT_001",
        plc_comentario="Totalizador 1",
        descripcion="Contador producto",
        uid="TOT_001",
    )
    assert d.numero == 1
    assert d.plc_tag == "V_TOT_001"
    assert d.uid == "TOT_001"
    # Defaults especificos TOT.
    assert d.tipo == ""
    assert d.incxpulso == 0.0
    assert d.proceso == ""
    # Defaults digitales.
    assert d.e_byte == 0
    assert d.e_bit == 0
    assert d.gr_alarma == 0
    assert d.comentario_db == ""


def test_disp_tot_campos_especificos_populados():
    """DispTOT persiste tipo/incxpulso/proceso cuando se setean."""
    d = DispTOT(
        1, "tag", "com", "desc", "uid",
        tipo="LITROS", incxpulso=0.5, proceso="PR1",
    )
    assert d.tipo == "LITROS"
    assert d.incxpulso == 0.5
    assert d.proceso == "PR1"


def test_disp_tot_isinstance_dispositivo():
    """``Dispositivo`` es ``runtime_checkable``: DispTOT lo satisface."""
    d = DispTOT(1, "tag", "com", "desc", "uid")
    assert isinstance(d, Dispositivo)


def test_disp_tot_frozen_no_muta():
    """``frozen=True``: asignar un campo levanta ``FrozenInstanceError``."""
    from dataclasses import FrozenInstanceError

    d = DispTOT(1, "tag", "com", "desc", "uid")
    with pytest.raises(FrozenInstanceError):
        d.numero = 99  # type: ignore[misc]


def test_disp_tot_no_tiene_campos_que_no_aplican():
    """DispTOT NO tiene ``cuadro`` (DispED si) ni ``cfg_grupoalarma``.

    TOT comparte con DispED los campos E.Byte/E.Bit pero NO hereda
    de el (clase independiente). Verificamos que el campo ``cuadro``
    que DispED tiene no esta presente en DispTOT.
    """
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(DispTOT)}
    assert "cuadro" not in field_names
    # cfg_grupoalarma tampoco (el operario no lo incluye en el Excel).
    assert "cfg_grupoalarma" not in field_names


# ── Defaults comunes ─────────────────────────────────────────────────────


def test_disp_defaults_str_vacios():
    """Los campos ``str`` tienen default ``""`` en todas las Disp*."""
    d_ed = DispED(1, "t", "c", "d", "u")
    d_ea = DispEA(1, "t", "c", "d", "u")
    d_sa = DispSA(1, "t", "c", "d", "u")
    d_v = DispV(1, "t", "c", "d", "u")
    d_m = DispM(1, "t", "c", "d", "u")
    d_vf = DispM_VF(1, "t", "c", "d", "u")
    d_msina = DispMSINA(1, "t", "c", "d", "u")
    d_tot = DispTOT(1, "t", "c", "d", "u")

    for d in (d_ed, d_ea, d_sa, d_v, d_m, d_vf, d_msina, d_tot):
        assert d.tag == ""
        assert d.fat == ""
        assert d.comentario_db == ""


def test_disp_defaults_int_cero():
    """Los campos ``int`` tienen default ``0`` en todas las Disp*."""
    d_ed = DispED(1, "t", "c", "d", "u")
    d_vf = DispM_VF(1, "t", "c", "d", "u")
    d_msina = DispMSINA(1, "t", "c", "d", "u")
    d_tot = DispTOT(1, "t", "c", "d", "u")

    assert d_ed.gr_alarma == 0
    assert d_ed.hmi_index == 0
    assert d_vf.s_byte == 0
    assert d_vf.sa_byte == 0
    assert d_msina.rt_byte == 0
    assert d_tot.e_byte == 0


def test_disp_msina_defaults_float_cero():
    """Los campos ``float`` de DispMSINA tienen default ``0.0``."""
    d_msina = DispMSINA(1, "t", "c", "d", "u")
    assert d_msina.vel_min == 0.0
    assert d_msina.vel_max == 0.0
    assert d_msina.cons_k == 0.0


def test_disp_tot_defaults_float_cero():
    """El campo ``float`` de DispTOT (``incxpulso``) tiene default ``0.0``."""
    d_tot = DispTOT(1, "t", "c", "d", "u")
    assert d_tot.incxpulso == 0.0
