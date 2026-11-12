"""Tests de ``generador_mlc`` .

Cubre las funciones puras del modulo:
- ``ids_mlc_existentes``: extrae IDs del .s7res.
- ``siguiente_id_mlc``: genera IDs sin colision.
- ``mapa_mlc``: devuelve el mapping MLC_id -> texto es-ES.
"""
from __future__ import annotations

from zc_suite.simatic.sd.mlc import (
    ids_mlc_existentes,
    mapa_mlc,
    siguiente_id_mlc,
)

# ── ids_mlc_existentes ────────────────────────────────────────

def test_collect_devuelve_set_vacio_si_no_hay_mlcs() -> None:
    """Sin entradas ``- id: MLC_xxx`` devuelve set vacio."""
    assert ids_mlc_existentes("") == set()
    assert ids_mlc_existentes("MultiLingualTexts:\n") == set()


def test_collect_extrae_un_mlc() -> None:
    """Una entrada ``- id: MLC_xxx`` se extrae correctamente."""
    res = "MultiLingualTexts:\n  - id: MLC_q2\n    es-ES: test\n"
    assert ids_mlc_existentes(res) == {"MLC_q2"}


def test_collect_extrae_multiples_mlcs() -> None:
    """Multiples entradas se extraen todas, sin duplicados."""
    res = (
        "MultiLingualTexts:\n"
        "  - id: MLC_q2\n    es-ES: a\n"
        "  - id: MLC_Dz8\n    es-ES: b\n"
        "  - id: MLC_hsVUv\n    es-ES: c\n"
    )
    assert ids_mlc_existentes(res) == {"MLC_q2", "MLC_Dz8", "MLC_hsVUv"}


def test_collect_acepta_indentacion_variable() -> None:
    """El regex acepta cualquier nivel de indentacion antes de ``- id:``."""
    res = (
        "MultiLingualTexts:\n"
        "- id: MLC_a\n  es-ES: x\n"          # sin indent
        "    - id: MLC_b\n      es-ES: y\n"  # 4 espacios
        "        - id: MLC_c\n          es-ES: z\n"  # 8 espacios
    )
    assert ids_mlc_existentes(res) == {"MLC_a", "MLC_b", "MLC_c"}


def test_collect_ignora_otras_claves_id() -> None:
    """Solo captura IDs con prefijo ``MLC_`` (ignora otras claves ``id:``)."""
    res = (
        "SomeOtherBlock:\n"
        "  - id: NO_MLC_xxx\n"
        "MultiLingualTexts:\n"
        "  - id: MLC_q2\n    es-ES: test\n"
    )
    assert ids_mlc_existentes(res) == {"MLC_q2"}


def test_collect_no_captura_atributos_incorrectos() -> None:
    """No captura ``S7_MLC := "..."`` ni lineas que no sean ``- id:``."""
    res = (
        "DATA_BLOCK DB\n"
        "  { S7_MLC := \"MLC_inline\"; }\n"
        "MultiLingualTexts:\n"
        "  - id: MLC_q2\n"
    )
    assert ids_mlc_existentes(res) == {"MLC_q2"}


# ── siguiente_id_mlc ─────────────────────────────────────────────────────

def test_next_mlc_id_formato_correcto() -> None:
    """El ID generado tiene formato ``MLC_`` + 5 chars hex."""
    new_id = siguiente_id_mlc(set())
    assert new_id.startswith("MLC_")
    assert len(new_id) == 9  # "MLC_" + 5 chars
    suffix = new_id[4:]
    assert all(c in "0123456789abcdef" for c in suffix)


def test_next_mlc_id_no_colisiona_con_usados() -> None:
    """El ID generado NO esta en el set de usados."""
    used = {"MLC_q2", "MLC_Dz8"}
    new_id = siguiente_id_mlc(used)
    assert new_id not in used


def test_next_mlc_id_unico_en_multiples_llamadas() -> None:
    """Multiples llamadas generan IDs distintos."""
    used: set[str] = set()
    generated = [siguiente_id_mlc(used) for _ in range(100)]
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
    new_id = siguiente_id_mlc(used)
    assert new_id.startswith("MLC_")
    assert new_id not in used


def test_next_mlc_id_formato_hex() -> None:
    """El sufijo del ID son exactamente 5 chars hex (0-9a-f)."""
    for _ in range(20):
        new_id = siguiente_id_mlc(set())
        suffix = new_id[len("MLC_"):]
        assert len(suffix) == 5
        assert all(c in "0123456789abcdef" for c in suffix)


# ── mapa_mlc ────────────────────────────────────────────────

def test_parse_mlc_lookup_basic() -> None:
    """Caso feliz: un .s7res con varias entradas MLC devuelve el mapping.

    Cada entrada ``- id: MLC_xxx`` con campo ``es-ES`` aparece como
    ``{MLC_xxx: "texto es-ES"}`` en el dict resultante."""
    res = (
        "MultiLingualTexts:\n"
        "  - id: MLC_q2\n    es-ES: PRINCIPAL\n"
        "  - id: MLC_Dz8\n    es-ES: SECUNDARIO\n"
        "  - id: MLC_hsVUv\n    es-ES: auxiliar\n"
    )
    assert mapa_mlc(res) == {
        "MLC_q2": "PRINCIPAL",
        "MLC_Dz8": "SECUNDARIO",
        "MLC_hsVUv": "auxiliar",
    }


def test_parse_mlc_lookup_fallback_otros_idiomas() -> None:
    """Sin ``es-ES``, cae a ``en-US`` y luego ``de-DE``.

    Caso real: bloques importados de proyectos alemanes donde solo
    existe ``de-DE``. La utilidad prioriza espanol, luego los demas."""
    res = (
        "MultiLingualTexts:\n"
        "  - id: MLC_a\n    en-US: english text\n"
        "  - id: MLC_b\n    de-DE: deutscher text\n"
        "  - id: MLC_c\n    es-ES: espanol\n"
    )
    assert mapa_mlc(res) == {
        "MLC_a": "english text",
        "MLC_b": "deutscher text",
        "MLC_c": "espanol",
    }


def test_parse_mlc_lookup_inputs_vacios() -> None:
    """``""`` y ``None`` retornan dict vacio sin raise.

    El caller decide si falla o no; la utility no es defensiva."""
    assert mapa_mlc("") == {}
    assert mapa_mlc(None) == {}  # type: ignore[arg-type]


def test_parse_mlc_lookup_filtra_entradas_no_mlc() -> None:
    """Solo conserva entradas con ``id`` que empieza por ``MLC_``.

    Ignora entradas sin ``id``, con ``id`` vacio, o con otro prefijo.
    Esto evita contaminar el lookup con IDs que el caller nunca
    buscara (los MLCs del .s7dcl siempre tienen prefijo ``MLC_``)."""
    res = (
        "MultiLingualTexts:\n"
        "  - id: MLC_keep\n    es-ES: keep me\n"
        "  - id: NO_MLC_skip\n    es-ES: skip me\n"
        "  - other: NO_ID_FIELD\n    es-ES: skip me too\n"
        "  - id: ''\n    es-ES: empty id, skip\n"
        "  - id: MLC_also_keep\n    es-ES: keep me 2\n"
    )
    assert mapa_mlc(res) == {
        "MLC_keep": "keep me",
        "MLC_also_keep": "keep me 2",
    }
