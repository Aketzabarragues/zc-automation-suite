"""Tests de ``simatic_sd_mlc_generator`` .

Cubre las dos funciones puras del modulo:
- ``collect_existing_mlc_ids``: extrae IDs del .s7res.
- ``next_mlc_id``: genera IDs sin colision.
"""
from __future__ import annotations

from core.helpers.simatic_sd.simatic_sd_mlc_generator import (
    collect_existing_mlc_ids,
    next_mlc_id,
)


# ── collect_existing_mlc_ids ────────────────────────────────────────

def test_collect_devuelve_set_vacio_si_no_hay_mlcs() -> None:
    """Sin entradas ``- id: MLC_xxx`` devuelve set vacio."""
    assert collect_existing_mlc_ids("") == set()
    assert collect_existing_mlc_ids("MultiLingualTexts:\n") == set()


def test_collect_extrae_un_mlc() -> None:
    """Una entrada ``- id: MLC_xxx`` se extrae correctamente."""
    res = "MultiLingualTexts:\n  - id: MLC_q2\n    es-ES: test\n"
    assert collect_existing_mlc_ids(res) == {"MLC_q2"}


def test_collect_extrae_multiples_mlcs() -> None:
    """Multiples entradas se extraen todas, sin duplicados."""
    res = (
        "MultiLingualTexts:\n"
        "  - id: MLC_q2\n    es-ES: a\n"
        "  - id: MLC_Dz8\n    es-ES: b\n"
        "  - id: MLC_hsVUv\n    es-ES: c\n"
    )
    assert collect_existing_mlc_ids(res) == {"MLC_q2", "MLC_Dz8", "MLC_hsVUv"}


def test_collect_acepta_indentacion_variable() -> None:
    """El regex acepta cualquier nivel de indentacion antes de ``- id:``."""
    res = (
        "MultiLingualTexts:\n"
        "- id: MLC_a\n  es-ES: x\n"          # sin indent
        "    - id: MLC_b\n      es-ES: y\n"  # 4 espacios
        "        - id: MLC_c\n          es-ES: z\n"  # 8 espacios
    )
    assert collect_existing_mlc_ids(res) == {"MLC_a", "MLC_b", "MLC_c"}


def test_collect_ignora_otras_claves_id() -> None:
    """Solo captura IDs con prefijo ``MLC_`` (ignora otras claves ``id:``)."""
    res = (
        "SomeOtherBlock:\n"
        "  - id: NO_MLC_xxx\n"
        "MultiLingualTexts:\n"
        "  - id: MLC_q2\n    es-ES: test\n"
    )
    assert collect_existing_mlc_ids(res) == {"MLC_q2"}


def test_collect_no_captura_atributos_incorrectos() -> None:
    """No captura ``S7_MLC := "..."`` ni lineas que no sean ``- id:``."""
    res = (
        "DATA_BLOCK DB\n"
        "  { S7_MLC := \"MLC_inline\"; }\n"
        "MultiLingualTexts:\n"
        "  - id: MLC_q2\n"
    )
    assert collect_existing_mlc_ids(res) == {"MLC_q2"}


# ── next_mlc_id ─────────────────────────────────────────────────────

def test_next_mlc_id_formato_correcto() -> None:
    """El ID generado tiene formato ``MLC_`` + 5 chars hex."""
    new_id = next_mlc_id(set())
    assert new_id.startswith("MLC_")
    assert len(new_id) == 9  # "MLC_" + 5 chars
    suffix = new_id[4:]
    assert all(c in "0123456789abcdef" for c in suffix)


def test_next_mlc_id_no_colisiona_con_usados() -> None:
    """El ID generado NO esta en el set de usados."""
    used = {"MLC_q2", "MLC_Dz8"}
    new_id = next_mlc_id(used)
    assert new_id not in used


def test_next_mlc_id_unico_en_multiples_llamadas() -> None:
    """Multiples llamadas generan IDs distintos."""
    used: set[str] = set()
    generated = [next_mlc_id(used) for _ in range(100)]
    # Todos los IDs son distintos entre si.
    assert len(set(generated)) == 100
    # El caller debe actualizar el set; simulamos:
    used.update(generated)
    for new_id in generated:
        assert new_id in used


def test_next_mlc_id_maneja_set_no_vacio() -> None:
    """Con un set con IDs realistas (decenas), sigue generando unicos.

    Caso normal: el .s7res de un DB de proceso tiene 30-100 IDs MLC
    (PReal 1..15, PInt 1..15, ALM 1..16, + satellites + headers).
    El set realista nunca llega a saturar el espacio de 16^5 = 1M IDs."""
    used = {f"MLC_{i:05x}" for i in range(50)}  # 50 IDs hex ya usados.
    new_id = next_mlc_id(used)
    assert new_id.startswith("MLC_")
    assert new_id not in used


def test_next_mlc_id_formato_hex() -> None:
    """El sufijo del ID son exactamente 5 chars hex (0-9a-f)."""
    for _ in range(20):
        new_id = next_mlc_id(set())
        suffix = new_id[len("MLC_"):]
        assert len(suffix) == 5
        assert all(c in "0123456789abcdef" for c in suffix)
