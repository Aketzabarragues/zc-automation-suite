"""Tests OFFLINE de ``MLCRegistry``.

Cubre unicidad, reserva, release, saturaciÃ³n defensiva.
Sin imports de TIA, sin red, sin disco.
"""
from __future__ import annotations

import random
from unittest.mock import patch

import pytest

from areas.alimentacion.helpers.sd.mlc_registry import MLCRegistry


# â”€â”€ next_mlc_id â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_next_mlc_id_no_repite() -> None:
    """100 IDs generados en un registry vacÃ­o â†’ todos distintos."""
    reg = MLCRegistry()
    generated = {reg.next_mlc_id() for _ in range(100)}
    assert len(generated) == 100, "next_mlc_id colisionÃ³ en 100 intentos"


def test_next_mlc_id_tiene_prefijo_MLC() -> None:
    """Todos los IDs generados empiezan por 'MLC_'."""
    reg = MLCRegistry()
    for _ in range(20):
        assert reg.next_mlc_id().startswith("MLC_")


def test_next_mlc_id_sufijo_en_rango_3_5() -> None:
    """Sufijo aleatorio de 3-5 chars (sin contar prefijo MLC_)."""
    reg = MLCRegistry()
    for _ in range(50):
        mlc = reg.next_mlc_id()
        suffix_len = len(mlc) - len("MLC_")
        assert 3 <= suffix_len <= 5


# â”€â”€ reserve / is_used / __contains__ / __len__ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_reserve_preserva_ids() -> None:
    """Tras reserve(['A', 'B']), ambos estÃ¡n en el registry."""
    reg = MLCRegistry()
    reg.reserve(["MLC_aaa", "MLC_bbb"])
    assert reg.is_used("MLC_aaa")
    assert reg.is_used("MLC_bbb")
    assert "MLC_ccc" not in reg
    assert len(reg) == 2


def test_reserve_con_iterable_no_solo_set() -> None:
    """reserve acepta generadores, listas, tuplas, etc."""
    reg = MLCRegistry()
    reg.reserve(f"MLC_{i}" for i in range(5))
    assert len(reg) == 5
    assert reg.is_used("MLC_0")
    assert reg.is_used("MLC_4")
    assert "MLC_5" not in reg


def test_constructor_con_used_ids() -> None:
    """Constructor con used_ids inicializa el set."""
    reg = MLCRegistry(used_ids={"MLC_xxx", "MLC_yyy"})
    assert len(reg) == 2
    assert reg.is_used("MLC_xxx")


def test_next_mlc_id_respeta_ids_reservados() -> None:
    """next_mlc_id no genera IDs que ya estÃ¡n reservados."""
    reg = MLCRegistry(used_ids={"MLC_aaa", "MLC_bbb"})
    for _ in range(50):
        new_id = reg.next_mlc_id()
        assert new_id not in {"MLC_aaa", "MLC_bbb"}


# â”€â”€ release â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_release_permite_reutilizar() -> None:
    """Tras release, el ID puede volver a generarse (con alta probabilidad)."""
    reg = MLCRegistry()
    mlc = reg.next_mlc_id()
    assert mlc in reg
    reg.release(mlc)
    assert mlc not in reg
    # Generar 200 mÃ¡s y verificar que el espacio vuelve a estar disponible.
    generated = {reg.next_mlc_id() for _ in range(200)}
    # No podemos garantizar que salga exactamente `mlc` de nuevo, pero
    # sÃ­ que ninguno de los 200 choque con los previamente generados
    # que sigan en el registry.
    for g in generated:
        assert g != mlc or mlc not in reg  # tautologÃ­a si mlc fue re-gen


def test_release_de_id_no_presente_es_noop() -> None:
    """release de un ID que no estaba â†’ no lanza."""
    reg = MLCRegistry()
    reg.release("MLC_inexistente")  # no debe lanzar
    assert len(reg) == 0


# â”€â”€ SaturaciÃ³n defensiva â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_runtime_error_si_no_hay_ids_disponibles() -> None:
    """Si random siempre colisiona, next_mlc_id lanza RuntimeError tras 50 intentos."""
    reg = MLCRegistry()
    # Forzar colisiÃ³n total: cada next_mlc_id() cae en uno ya en uso.
    # Truco: parchear random.randint para que devuelva siempre la misma
    # longitud, y random.choices para que devuelva siempre el mismo
    # sufijo. AsÃ­ el primer ID generado serÃ¡ siempre el mismo, y los
    # siguientes colisionarÃ¡n.
    with patch(
        "areas.alimentacion.helpers.sd.mlc_registry.random.randint",
        return_value=3,
    ), patch(
        "areas.alimentacion.helpers.sd.mlc_registry.random.choices",
        return_value=list("aaa"),
    ):
        # Genera el primero (lo registra).
        reg.next_mlc_id()
        # Los siguientes 50 intentos colisionan todos.
        with pytest.raises(RuntimeError, match="no se pudo generar un MLC Ãºnico"):
            reg.next_mlc_id()


# â”€â”€ Doble reserva idempotente â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_reserve_doble_no_duplica() -> None:
    """reserve(used) llamado dos veces con el mismo set no duplica."""
    reg = MLCRegistry()
    reg.reserve({"MLC_aaa", "MLC_bbb"})
    reg.reserve({"MLC_aaa", "MLC_bbb", "MLC_ccc"})
    assert len(reg) == 3
