"""Tests de ``DimensionesDispositivos``.

Cobertura:
  - ``extras`` vacio por defecto.
  - ``to_api_dict()`` retorna copia serializable.
  - ``get()`` por nombre canonico.
"""
from __future__ import annotations

import pytest

from areas.alimentacion.data.data_dimensiones import DimensionesDispositivos


def test_defaults_extras_vacio():
    """Constructor sin argumentos deja ``extras={}``."""
    d = DimensionesDispositivos()
    assert dict(d.extras) == {}


def test_to_api_dict_retorna_copia_serializable():
    """``to_api_dict()`` retorna dict plano con nombres canonicos."""
    d = DimensionesDispositivos(extras={
        "N_MAX_DISP_ED": 21,
        "N_MAX_DISP_EA": 21,
        "N_MAX_DISP_M_SINA": 50,
    })
    result = d.to_api_dict()
    assert result == {
        "N_MAX_DISP_ED": 21,
        "N_MAX_DISP_EA": 21,
        "N_MAX_DISP_M_SINA": 50,
    }
    # Es una copia (no alias).
    result["NUEVA"] = 99
    assert "NUEVA" not in d.extras


def test_get_por_nombre_canonico():
    """``get(N_MAX_DISP_ED)`` devuelve el valor del extras."""
    d = DimensionesDispositivos(extras={"N_MAX_DISP_ED": 21})
    assert d.get("N_MAX_DISP_ED") == 21


def test_get_none_si_no_existe():
    """``get`` retorna ``None`` para nombre ausente."""
    d = DimensionesDispositivos(extras={"N_MAX_DISP_ED": 21})
    assert d.get("N_MAX_DISP_INEXISTENTE") is None


def test_frozen_no_muta():
    """``frozen=True``: asignar un campo levanta ``FrozenInstanceError``."""
    from dataclasses import FrozenInstanceError

    d = DimensionesDispositivos(extras={"N_MAX_DISP_ED": 21})
    with pytest.raises(FrozenInstanceError):
        d.extras = {"X": 1}  # type: ignore[misc]
