"""Tests para ``areas.alimentacion.data.data_entidades``.

Cobertura:
  - ``Entidad`` se construye con los 3 campos required + defaults tolerantes.
  - ``frozen=True``: no se puede mutar ningun campo.
  - ``__post_init__`` rechaza ``numero < 0`` y ``plc_name``/``plc_tag`` vacios.
  - Equality y hash por valor (es congelada, sirve como dict key / set member).
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from areas.alimentacion.data.data_entidades import Entidad


# ── Construccion ─────────────────────────────────────────────────────────


def test_entidad_required_solo_3_campos():
    """3 campos required; el resto toma defaults tolerantes."""
    e = Entidad(numero=1, plc_name="PLC1", plc_tag="ent_001")
    assert e.numero == 1
    assert e.plc_name == "PLC1"
    assert e.plc_tag == "ent_001"
    # Defaults
    assert e.descripcion == ""
    assert e.plc_comentario == ""
    assert e.plc_tipo == 0
    assert e.plc_index == 0


def test_entidad_todos_los_campos():
    """Los 7 campos se pueden pasar en una sola sentencia."""
    e = Entidad(
        numero=42,
        plc_name="ZC_PLC_STD",
        plc_tag="ent_042",
        descripcion="Valvula de cierre",
        plc_comentario="// comentario del slot 42",
        plc_tipo=1,
        plc_index=7,
    )
    assert e.numero == 42
    assert e.plc_name == "ZC_PLC_STD"
    assert e.plc_tag == "ent_042"
    assert e.descripcion == "Valvula de cierre"
    assert e.plc_comentario == "// comentario del slot 42"
    assert e.plc_tipo == 1
    assert e.plc_index == 7


def test_entidad_numero_cero_es_valido():
    """Slot 0 = "NO USAR" en proc_db; aqui tambien permitimos ``numero=0``.

    El parser usa ``numero >= 0`` como filtro; el DTO solo valida el
    limite inferior. La decision de saltar slot 0 la toma el FB sync.
    """
    e = Entidad(numero=0, plc_name="PLC1", plc_tag="ent_000")
    assert e.numero == 0


# ── Inmutabilidad (frozen=True) ──────────────────────────────────────────


def test_entidad_frozen_no_muta_campo_primitivo():
    """Asignar un campo ``int`` levanta ``FrozenInstanceError``."""
    e = Entidad(numero=1, plc_name="PLC1", plc_tag="ent_001")
    with pytest.raises(FrozenInstanceError):
        e.numero = 99  # type: ignore[misc]


def test_entidad_frozen_no_muta_campo_str():
    """Asignar un campo ``str`` levanta ``FrozenInstanceError``."""
    e = Entidad(numero=1, plc_name="PLC1", plc_tag="ent_001")
    with pytest.raises(FrozenInstanceError):
        e.plc_tag = "otro"  # type: ignore[misc]


# ── Validacion __post_init__ ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "numero_invalido",
    [-1, -10, -9999],
)
def test_entidad_rechaza_numero_negativo(numero_invalido):
    """``__post_init__`` rechaza ``numero < 0`` con ``ValueError``."""
    with pytest.raises(ValueError, match="numero debe ser >= 0"):
        Entidad(numero=numero_invalido, plc_name="PLC1", plc_tag="ent_x")


def test_entidad_rechaza_plc_name_vacio():
    """``__post_init__`` rechaza ``plc_name == ""``.

    El parser es responsable de ``.strip()`` antes de instanciar el DTO;
    el DTO solo valida el sentinela vacio (``""``), no la presentacion.
    """
    with pytest.raises(ValueError, match="plc_name no puede ser vacio"):
        Entidad(numero=1, plc_name="", plc_tag="ent_x")


def test_entidad_rechaza_plc_tag_vacio():
    """``__post_init__`` rechaza ``plc_tag == ""``.

    Misma politica que ``plc_name``: sentinela vacio (``""``), no
    presentacion. El parser normaliza con ``.strip()``.
    """
    with pytest.raises(ValueError, match="plc_tag no puede ser vacio"):
        Entidad(numero=1, plc_name="PLC1", plc_tag="")


# ── Equality y hash por valor ────────────────────────────────────────────


def test_entidad_equality_por_valor():
    """Dos ``Entidad`` con los mismos campos son ``==`` (dataclass eq)."""
    a = Entidad(numero=1, plc_name="PLC1", plc_tag="ent_001")
    b = Entidad(numero=1, plc_name="PLC1", plc_tag="ent_001")
    assert a == b


def test_entidad_inequality_si_cambia_un_campo():
    """Cambiar un campo cualquiera rompe la equality."""
    base = Entidad(numero=1, plc_name="PLC1", plc_tag="ent_001")
    otro_numero = Entidad(numero=2, plc_name="PLC1", plc_tag="ent_001")
    otro_plc = Entidad(numero=1, plc_name="PLC2", plc_tag="ent_001")
    otro_tag = Entidad(numero=1, plc_name="PLC1", plc_tag="ent_002")
    assert base != otro_numero
    assert base != otro_plc
    assert base != otro_tag


def test_entidad_hash_usable_en_set():
    """``frozen=True`` genera ``__hash__``; sirve como ``set`` member."""
    a = Entidad(numero=1, plc_name="PLC1", plc_tag="ent_001")
    b = Entidad(numero=1, plc_name="PLC1", plc_tag="ent_001")  # dup de a
    c = Entidad(numero=2, plc_name="PLC1", plc_tag="ent_001")
    s = {a, b, c}
    # a y b son iguales por valor → colapsan en el set
    assert len(s) == 2
    assert a in s
    assert c in s