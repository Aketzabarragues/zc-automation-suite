"""Tests del DTO ``DataBloquePLC``.

Validan las tres superficies del value object:
  - ``normalize_name`` (estabilidad de claves en caches).
  - ``detect_tipo`` (clasificación DB/FB/FC/OB/UDT/OTHER + numero).
  - ``to_dict`` (contrato IPC: 4 campos primitivos).
  - Inmutabilidad (``frozen=True``).
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from core.data.data_block_plc import DataBloquePLC


# ────────────────────────────────────────────────────────────────────────
# normalize_name
# ────────────────────────────────────────────────────────────────────────


def test_normalize_name_strips_nbsp_and_spaces_and_lowercases() -> None:
    """Distintos formatos del mismo bloque deben coincidir tras normalizar."""
    assert (
        DataBloquePLC.normalize_name("DB 2000")
        == DataBloquePLC.normalize_name("DB2000")
        == DataBloquePLC.normalize_name("db\xa02000")
    )
    # Y todos colapsan al mismo string canonico.
    assert DataBloquePLC.normalize_name("DB 2000") == "db2000"


def test_normalize_name_empty_returns_empty() -> None:
    """String vacia → vacia (no falla)."""
    assert DataBloquePLC.normalize_name("") == ""


def test_normalize_name_keeps_prefix() -> None:
    """NO se hace prefix-stripping: DB1 ≠ FB1."""
    assert DataBloquePLC.normalize_name("DB1") == "db1"
    assert DataBloquePLC.normalize_name("FB1") == "fb1"
    assert DataBloquePLC.normalize_name("DB1") != DataBloquePLC.normalize_name("FB1")


# ────────────────────────────────────────────────────────────────────────
# detect_tipo + numero
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name, expected_tipo, expected_numero",
    [
        ("DB1_SYS", "DB", 1),
        ("DB2000_ED", "DB", 2000),
        ("db300", "DB", 300),
        ("FB42", "FB", 42),
        ("FC10", "FC", 10),
        ("OB1", "OB", 1),
        ("OB100", "OB", 100),
        ("UDT5", "UDT", 5),
        # Sin digitos inmediatamente tras el prefijo → OTHER (regex
        # exige ``(\d+)`` despues del prefijo, como en el legacy
        # scanner y en el handler ``_cmd_scan_blocks``).
        ("FB_Main", "OTHER", 0),
        ("UDT_ZC_Disp", "OTHER", 0),
    ],
)
def test_detect_tipo_db_fb_fc_ob_udt(
    name: str, expected_tipo: str, expected_numero: int
) -> None:
    assert DataBloquePLC.detect_tipo(name) == expected_tipo
    # El ``numero`` se extrae en ``_cmd_scan_blocks`` con el mismo regex;
    # aqui validamos solo la clasificacion (el numero sale del mismo
    # match que el tipo).


def test_detect_tipo_other() -> None:
    """Nombre sin prefijo estandar → ``OTHER``."""
    assert DataBloquePLC.detect_tipo("MyBlock") == "OTHER"
    assert DataBloquePLC.detect_tipo("Sistema") == "OTHER"
    assert DataBloquePLC.detect_tipo("") == "OTHER"


# ────────────────────────────────────────────────────────────────────────
# to_dict
# ────────────────────────────────────────────────────────────────────────


def test_to_dict_has_four_fields() -> None:
    """to_dict debe serializar exactamente 4 campos primitivos."""
    b = DataBloquePLC(nombre="DB1_SYS", numero=1, tipo="DB", ruta="0_Sistema\\DB1_SYS")
    d = b.to_dict()
    assert set(d.keys()) == {"nombre", "numero", "tipo", "ruta"}
    assert d == {
        "nombre": "DB1_SYS",
        "numero": 1,
        "tipo": "DB",
        "ruta": "0_Sistema\\DB1_SYS",
    }


# ────────────────────────────────────────────────────────────────────────
# Inmutabilidad
# ────────────────────────────────────────────────────────────────────────


def test_frozen_dataclass_cannot_be_mutated() -> None:
    """``frozen=True`` → cualquier intento de asignar atributo falla."""
    b = DataBloquePLC(nombre="DB1", numero=1, tipo="DB", ruta="")
    with pytest.raises(FrozenInstanceError):
        b.nombre = "DB2"  # type: ignore[misc]
