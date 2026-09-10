"""Tests para ``core.data.data_bloque_plc.DataBloquePLC``.

Fase 3, paso 3.1.3.  Cobertura:
  - Construccion basica con los 4 campos.
  - ``frozen=True``: no se puede mutar (intentar asignar lanza
    ``FrozenInstanceError``).
  - ``normalize_name`` cubre NBSP, espacios, mayusculas/minusculas
    y ``strip()``.
  - ``normalize_name`` NO hace prefix-stripping: ``DB1`` y ``FB1``
    se mantienen distintos.
  - ``detect_tipo`` reconoce ``DB/FB/FC/OB/UDT`` (case-insensitive)
    y devuelve ``"OTHER"`` en cualquier otro caso.
  - ``to_dict()`` emite exactamente los 4 campos.
"""
from __future__ import annotations

import pytest

from core.data.data_bloque_plc import DataBloquePLC


def test_construccion_basica():
    """DataBloquePLC acepta los 4 campos en orden."""
    b = DataBloquePLC("DB1_SYS", 1, "DB", "0_Sistema\\DB1_SYS")

    assert b.nombre == "DB1_SYS"
    assert b.numero == 1
    assert b.tipo == "DB"
    assert b.ruta == "0_Sistema\\DB1_SYS"


def test_frozen_no_se_puede_mutar():
    """``frozen=True``: asignar un campo levanta ``FrozenInstanceError``."""
    from dataclasses import FrozenInstanceError

    b = DataBloquePLC("DB1_SYS", 1, "DB", "0_Sistema\\DB1_SYS")

    with pytest.raises(FrozenInstanceError):
        b.nombre = "DB2"  # type: ignore[misc]


def test_normalize_name_minusculas_espacios_y_strip():
    """``normalize_name`` baja a minusculas, quita espacios y strip."""
    assert DataBloquePLC.normalize_name("DB1 SYS") == "db1sys"
    assert DataBloquePLC.normalize_name("  db1  ") == "db1"
    assert DataBloquePLC.normalize_name("DB1") == "db1"


def test_normalize_name_tolera_nbsp():
    """``normalize_name`` sustituye NBSP (\\xa0) por vacio antes de strip."""
    # "DB\xa01" -> "DB1" -> "db1"
    assert DataBloquePLC.normalize_name("DB\xa01") == "db1"
    # "DB 1" con NBSP en lugar de espacio -> "DB1" -> "db1"
    assert DataBloquePLC.normalize_name("DB\xa01") == "db1"


def test_normalize_name_no_hace_prefix_strip():
    """``normalize_name`` NO quita prefijos: ``DB1`` y ``FB1`` son distintos."""
    assert DataBloquePLC.normalize_name("DB1") != DataBloquePLC.normalize_name(
        "FB1"
    )
    assert DataBloquePLC.normalize_name("DB1") == "db1"
    assert DataBloquePLC.normalize_name("FB1") == "fb1"


def test_detect_tipo_reconoce_familias_estandar():
    """``detect_tipo`` identifica los 5 prefijos canonicos."""
    assert DataBloquePLC.detect_tipo("DB1") == "DB"
    assert DataBloquePLC.detect_tipo("FB100") == "FB"
    assert DataBloquePLC.detect_tipo("FC12") == "FC"
    assert DataBloquePLC.detect_tipo("OB1") == "OB"
    assert DataBloquePLC.detect_tipo("UDT5") == "UDT"


def test_detect_tipo_case_insensitive():
    """``detect_tipo`` es case-insensitive en el prefijo."""
    assert DataBloquePLC.detect_tipo("db1") == "DB"
    assert DataBloquePLC.detect_tipo("fb1") == "FB"
    assert DataBloquePLC.detect_tipo("uDt42") == "UDT"


def test_detect_tipo_other_para_nombres_sin_prefijo_estandar():
    """``detect_tipo`` devuelve ``"OTHER"`` si el nombre no encaja."""
    assert DataBloquePLC.detect_tipo("Main") == "OTHER"
    assert DataBloquePLC.detect_tipo("") == "OTHER"
    assert DataBloquePLC.detect_tipo("XYZ1") == "OTHER"
    # Prefijo correcto pero sin digitos -> no encaja.
    assert DataBloquePLC.detect_tipo("DB") == "OTHER"


def test_to_dict_shape():
    """``to_dict()`` emite exactamente los 4 campos primitivos."""
    b = DataBloquePLC("FB_Main", 42, "FB", "Programa\\FB_Main")
    snapshot = b.to_dict()

    assert set(snapshot.keys()) == {"nombre", "numero", "tipo", "ruta"}
    assert snapshot == {
        "nombre": "FB_Main",
        "numero": 42,
        "tipo": "FB",
        "ruta": "Programa\\FB_Main",
    }


def test_to_dict_con_ruta_vacia():
    """``to_dict()`` preserva ``ruta=""`` como cadena vacia (defensivo)."""
    b = DataBloquePLC("OB1", 1, "OB", "")
    assert b.to_dict()["ruta"] == ""
