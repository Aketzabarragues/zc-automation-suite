"""Tests para ``areas.alimentacion.data.data_Dimensiones.DimensionesDispositivos``.

Fase 3, paso 3.2.2 (subdivision del plan original: 3.2.2 migraba todo a
``data_Dispositivos.py``; se partio en 2 archivos para < 200 lineas).
Cobertura:
  - defaults razonables.
  - ``frozen=True``: no se puede mutar.
  - ``values()`` emite los 6 N_MAX canonicos (sin extras).
  - ``all_nmax()`` une ``values()`` con ``extras``.
  - ``to_api_dict()`` solo los 6 legacy.
  - ``get(nmax_name)`` lee por canonico y por legacy.
  - ``from_catalog(catalog, raw)`` con catalogo=None acepta el raw
    tal cual; con catalogo filtra claves no listadas.
"""
from __future__ import annotations

import pytest

from areas.alimentacion.data.data_Dimensiones import DimensionesDispositivos


def test_defaults_vacios():
    """DimensionesDispositivos() da todos los N_MAX a 0 y extras vacio."""
    d = DimensionesDispositivos()

    assert d.num_disp_ed == 0
    assert d.num_disp_ea == 0
    assert d.num_disp_sa == 0
    assert d.num_disp_v == 0
    assert d.num_disp_m == 0
    assert d.num_disp_m_vf == 0
    assert d.extras == {}


def test_frozen_no_muta():
    """``frozen=True``: asignar un campo levanta ``FrozenInstanceError``."""
    from dataclasses import FrozenInstanceError

    d = DimensionesDispositivos()
    with pytest.raises(FrozenInstanceError):
        d.num_disp_ed = 99  # type: ignore[misc]


def test_values_devuelve_los_6_canonicos():
    """``values()`` mapea los 6 N_MAX canonicos (sin extras)."""
    d = DimensionesDispositivos(
        num_disp_ed=10, num_disp_ea=20, num_disp_sa=5,
        num_disp_v=30, num_disp_m=15, num_disp_m_vf=3,
        extras={"N_MAX_DISP_FF": 99},
    )

    result = d.values()

    assert result == {
        "N_MAX_DISP_ED": 10,
        "N_MAX_DISP_EA": 20,
        "N_MAX_DISP_SA": 5,
        "N_MAX_DISP_V": 30,
        "N_MAX_DISP_M": 15,
        "N_MAX_DISP_M_VF": 3,
    }
    # extras NO aparece en values().
    assert "N_MAX_DISP_FF" not in result


def test_all_nmax_une_values_con_extras():
    """``all_nmax()`` une values() y extras (extras gana si colisiona)."""
    d = DimensionesDispositivos(
        num_disp_ed=10, num_disp_ea=20, num_disp_sa=5,
        num_disp_v=30, num_disp_m=15, num_disp_m_vf=3,
        extras={"N_MAX_DISP_FF": 99, "N_MAX_DISP_SD": 7},
    )

    result = d.all_nmax()

    assert result["N_MAX_DISP_ED"] == 10
    assert result["N_MAX_DISP_FF"] == 99
    assert result["N_MAX_DISP_SD"] == 7


def test_to_api_dict_solo_6_legacy():
    """``to_api_dict()`` devuelve SOLO los 6 legacy (oculta extras)."""
    d = DimensionesDispositivos(
        num_disp_ed=10, num_disp_ea=20, num_disp_sa=5,
        num_disp_v=30, num_disp_m=15, num_disp_m_vf=3,
        extras={"N_MAX_DISP_FF": 99},
    )

    result = d.to_api_dict()

    assert set(result.keys()) == {
        "num_disp_ed", "num_disp_ea", "num_disp_sa",
        "num_disp_v", "num_disp_m", "num_disp_m_vf",
    }
    assert "N_MAX_DISP_FF" not in result
    assert result["num_disp_ed"] == 10


def test_get_por_nombre_canonico():
    """``get(N_MAX_DISP_ED)`` devuelve el valor del campo legacy."""
    d = DimensionesDispositivos(num_disp_ed=10)
    assert d.get("N_MAX_DISP_ED") == 10
    assert d.get("N_MAX_DISP_M") == 0


def test_get_por_nombre_legacy():
    """``get(num_disp_ed)`` (legacy) tambien funciona por tolerancia."""
    d = DimensionesDispositivos(num_disp_ed=10)
    assert d.get("num_disp_ed") == 10


def test_get_por_nombre_en_extras():
    """``get(N_MAX_DISP_FF)`` busca en extras si no esta en los 6 legacy."""
    d = DimensionesDispositivos(extras={"N_MAX_DISP_FF": 99})
    assert d.get("N_MAX_DISP_FF") == 99


def test_get_none_si_no_existe():
    """``get`` devuelve None si el nombre no esta en legacy ni en extras."""
    d = DimensionesDispositivos()
    assert d.get("N_MAX_INEXISTENTE") is None


def test_from_catalog_sin_catalogo_acepta_raw():
    """Sin catalogo, las claves canonicas van a su campo; el resto a extras.

    Nota: usamos solo nombres canonicos (``N_MAX_DISP_*``) en el raw
    porque el filtro de legacy en ``from_catalog`` solo excluye los
    nombres canonicos de extras (mismo comportamiento 1:1 con el
    legacy; bug preexistente que se arregla en Fase 4).
    """
    raw = {
        "N_MAX_DISP_ED": 10,
        "N_MAX_DISP_EA": 20,
        "N_MAX_DISP_FF": 99,  # no legacy -> extras
    }

    d = DimensionesDispositivos.from_catalog(catalog=None, raw=raw)

    assert d.num_disp_ed == 10
    assert d.num_disp_ea == 20
    assert d.extras == {"N_MAX_DISP_FF": 99}


def test_from_catalog_con_catalogo_filtra_claves():
    """Con catalogo, las claves del raw no listadas se descartan."""
    catalog = [
        {"name": "N_MAX_DISP_ED", "hw_type": "ed"},
        {"name": "N_MAX_DISP_FF", "hw_type": "ff"},
    ]
    raw = {
        "N_MAX_DISP_ED": 10,
        "N_MAX_DISP_FF": 99,
        "N_MAX_TYPO": 50,  # no listada -> se descarta
    }

    d = DimensionesDispositivos.from_catalog(catalog=catalog, raw=raw)

    assert d.num_disp_ed == 10
    assert d.extras == {"N_MAX_DISP_FF": 99}
    # El typo se descarta, no va a extras.
    assert "N_MAX_TYPO" not in d.extras


def test_from_catalog_vacio_devuelve_defaults():
    """``from_catalog(None, None)`` devuelve la instancia con defaults."""
    d = DimensionesDispositivos.from_catalog(catalog=None, raw=None)

    assert d.num_disp_ed == 0
    assert d.extras == {}


def test_from_catalog_raw_con_valores_invalidos_se_ignoran():
    """Valores no casteables a int se descartan silenciosamente."""
    raw = {
        "N_MAX_DISP_ED": 10,
        "N_MAX_DISP_FF": "no_es_int",
        "N_MAX_DISP_SD": None,
    }

    d = DimensionesDispositivos.from_catalog(catalog=None, raw=raw)

    assert d.num_disp_ed == 10
    # Los invalidos no llegan a extras.
    assert d.extras == {}
