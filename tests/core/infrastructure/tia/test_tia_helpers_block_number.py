"""Tests para ``core.infrastructure.tia.tia_helpers._safe_get_block_number``.

El numero del bloque se lee de TIA (``get_property(name="Number")``),
NO se deduce del nombre. Deducirlo del nombre devolvia 0 para bloques
legitimos cuyo nombre no sigue la convencion numerica (e.g. un FC
llamado ``"Documentacion"`` que en TIA tiene numero asignado).
"""
from __future__ import annotations

from unittest.mock import MagicMock

from core.infrastructure.tia.tia_helpers import _safe_get_block_number


def _make_block_with_property(raw):
    """Bloque que responde a ``get_property(name="Number")``."""
    b = MagicMock()

    def _get_property(name: str):
        assert name == "Number", f"propiedad inesperada: {name!r}"
        return raw

    b.get_property.side_effect = _get_property
    return b


def _make_block_with_attr(raw):
    """Bloque sin ``get_property`` util, solo atributo ``.Number``."""
    b = MagicMock(spec=["Number"])
    b.Number = raw
    return b


def _make_block_without_number():
    """Bloque sin numero en TIA ni en el atributo (get_property lanza)."""
    b = MagicMock(spec=[])
    return b


# ── camino 1: valor real de TIA ──────────────────────────────────────


def test_lee_numero_real_de_tia():
    """``get_property("Number")`` manda: el nombre no importa."""
    block = _make_block_with_property("2000")
    assert _safe_get_block_number(block, "FC1_MAIN") == 2000


def test_numero_real_vence_al_nombre():
    """El caso del bug: FC 'Documentacion' con numero real en TIA."""
    block = _make_block_with_property("17")
    assert _safe_get_block_number(block, "Documentacion") == 17


def test_numero_cero_real_no_cae_al_nombre():
    """Un numero 0 real en TIA no debe triggering el fallback al nombre.

    ``FC5_COSA`` con ``get_property`` devolviendo ``"0"`` debe dar 0,
    no 5 (que es lo que devolveria el regex sobre el nombre).
    """
    block = _make_block_with_property("0")
    assert _safe_get_block_number(block, "FC5_COSA") == 0


def test_acepta_numero_como_int():
    """TIA puede devolver int en vez de str."""
    block = _make_block_with_property(123)
    assert _safe_get_block_number(block, "DB99_X") == 123


# ── camino 2: atributo .Number ───────────────────────────────────────


def test_usa_atributo_number_sin_get_property():
    """Si no hay ``get_property``, cae al atributo ``.Number``."""
    block = _make_block_with_attr("4321")
    assert _safe_get_block_number(block, "Documentacion") == 4321


def test_atributo_number_invalido_cae_al_regex():
    """Atributo no numerico -> fallback al regex del nombre."""
    block = _make_block_with_attr("no-es-un-numero")
    assert _safe_get_block_number(block, "FC7_LO_QUE_SEA") == 7


# ── camino 3: fallback al regex ──────────────────────────────────────


def test_fallback_regex_si_tia_no_expone_numero():
    """Sin numero en TIA y sin atributo, deduce del nombre."""
    block = _make_block_without_number()
    assert _safe_get_block_number(block, "FC1_MAIN") == 1


def test_fallback_regex_db_y_ob():
    block = _make_block_without_number()
    assert _safe_get_block_number(block, "DB2000_ED") == 2000
    assert _safe_get_block_number(block, "OB30_PID") == 30


def test_nombre_sin_convencion_numerica_devuelve_cero():
    """Nombre que no sigue la convencion y TIA sin numero -> 0."""
    block = _make_block_without_number()
    assert _safe_get_block_number(block, "Documentacion") == 0


def test_get_property_que_lanza_cae_al_regex():
    """``get_property`` que revienta (COM) no debe tumbar el scan."""

    def _boom(name: str):
        raise RuntimeError("COM error")

    block = MagicMock()
    block.get_property.side_effect = _boom
    assert _safe_get_block_number(block, "FC3_ALGO") == 3


def test_get_property_devuelve_none_cae_al_regex():
    """``get_property`` que devuelve None (prop no expuesta) -> regex."""

    def _none(name: str):
        return None

    block = MagicMock()
    block.get_property.side_effect = _none
    assert _safe_get_block_number(block, "DB500_ED") == 500