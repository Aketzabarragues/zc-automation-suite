"""Test de drift entre ``manifest.js`` y ``manifest.py`` del área "alimentacion".

Contexto
--------
El área "alimentacion" expone su UI al shell SPA mediante DOS manifests
espejo:

  * ``areas/alimentacion/frontend/manifest.js``  — objeto JS ``_comps``
    con ``() => import(...)`` por componente (lo consume el shell SPA
    si decide bypasear el endpoint y cargar el manifest como módulo
    ESM).
  * ``areas/alimentacion/frontend/manifest.py``  — función ``build()``
    con un dict ``loaders`` cuyas keys son nombres de componente y
    cuyos valores son **strings** (URLs HTTP). El backend lo serializa
    a JSON en ``GET /api/v1/areas/alimentacion/manifest``.

Ambos deben declarar **exactamente las mismas keys**: si en el futuro
alguien añade un componente a uno de los dos y se olvida del otro, el
endpoint del backend devuelve un shape inconsistente con lo que la SPA
espera (loader faltante o desconocido) y el operario ve un
``Failed to resolve component`` en runtime.

Este test es un **contract check** (no es E2E): no ejecuta el código
JS, solo hace regex sobre el source de ``manifest.js`` y llama a
``manifest.build()`` para ``manifest.py``. Si la regex cambia porque
se reformatea el dict, el assert secundario de tamaño
(``len(keys_js) >= 5``) detecta la regresión con un mensaje claro.

Las keys son **case-sensitive**: ``AlimentacionSidebar`` ≠
``alimentacionsidebar``.

Si el test falla:
  1. Mira qué key se añadió/quitó en uno de los dos manifests.
  2. Sincronízalo (mismas keys en ambos).
  3. Vuelve a correr el test.

Marcado con ``@pytest.mark.frontend_smoke`` para permitir filtrado
(``pytest -m frontend_smoke``), igual que el resto de tests de
manifest del área.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

MANIFEST_JS = (
    REPO_ROOT
    / "areas"
    / "alimentacion"
    / "frontend"
    / "manifest.js"
)
MANIFEST_PY = (
    REPO_ROOT
    / "areas"
    / "alimentacion"
    / "frontend"
    / "manifest.py"
)

# Mínimo de keys que se esperan en el dict ``_comps`` de manifest.js.
# Es un sanity check: si la regex cambia o el dict se vacía por error,
# este assert falla con un mensaje claro en vez de pasar
# silenciosamente con un set vacío.
MIN_EXPECTED_KEYS = 5

pytestmark = pytest.mark.frontend_smoke


# ── Helpers ──────────────────────────────────────────────────────────────


def _extract_comps_keys_from_js(manifest_js_path: Path) -> list[str]:
    """Lee ``manifest.js`` y devuelve las keys del dict ``_comps``.

    Estrategia:
      1. Lee el archivo como texto UTF-8.
      2. Localiza el cuerpo del dict ``_comps = { ... };``.
         La regex es no-greedy (``.*?``) y exige que el cierre sea
         un ``};`` en su propia línea (así no se confunde con un
         cierre anidado de un sub-objeto).
      3. Elimina las líneas de comentario (// ...) para no capturar
         strings que aparezcan en comentarios del estilo
         ``// "Foo": () => ...``.
      4. Acepta tanto comillas dobles como simples (defensivo: hoy
         el archivo usa dobles, pero si en el futuro alguien usa
         simples la regex no rompe).
      5. Acepta espacios opcionales entre ``:`` y ``()`` y entre
         ``()`` y ``=>``.

    Si el bloque no se encuentra o no contiene keys válidas, lanza
    ``AssertionError`` con un mensaje claro (no un ``IndexError``
    opaco de ``re.search`` o ``re.findall``).
    """
    assert manifest_js_path.exists(), (
        f"Falta el archivo manifest.js: {manifest_js_path}"
    )
    text = manifest_js_path.read_text(encoding="utf-8")

    # 1) Localizar el cuerpo del dict ``_comps = { ... };``.
    block_match = re.search(
        r"_comps\s*=\s*\{(.*?)^};",
        text,
        re.DOTALL | re.MULTILINE,
    )
    assert block_match is not None, (
        "No se encontró el dict `const _comps = { ... };` en "
        f"{manifest_js_path}. Si reformateaste manifest.js, adapta "
        "la regex de _extract_comps_keys_from_js() en este test."
    )
    block = block_match.group(1)

    # 2) Eliminar comentarios de línea (// ...) para no capturar
    #    strings que aparezcan en comentarios. Aplicado SOLO dentro
    #    del bloque, no al archivo entero, para no tocar el shape
    #    del bloque antes de extraerlo.
    block_no_comments = re.sub(r"^\s*//.*$", "", block, flags=re.MULTILINE)

    # 3) Extraer keys. Acepta comillas dobles o simples.
    pattern = re.compile(
        r"""['"]([^'"]+)['"]           # key: string entre comillas (dobles o simples)
            \s*:\s*                   # dos puntos con espacios opcionales
            \(\s*\)\s*=>              # arrow function () =>  (con espacios opcionales)
        """,
        re.VERBOSE,
    )
    keys = pattern.findall(block_no_comments)
    return keys


# ── Tests ────────────────────────────────────────────────────────────────


def test_manifest_files_exist() -> None:
    """Ambos manifests existen y son archivos no vacíos.

    Sanity check antes de hacer el assert de igualdad: si alguno
    falta, el ``Path.read_text`` posterior falla con un mensaje
    genérico. Este test previo lo convierte en un fallo explícito
    y dirigido.
    """
    assert MANIFEST_JS.exists(), f"Falta el manifest JS: {MANIFEST_JS}"
    assert MANIFEST_PY.exists(), f"Falta el manifest Python: {MANIFEST_PY}"

    js_size = MANIFEST_JS.stat().st_size
    py_size = MANIFEST_PY.stat().st_size
    assert js_size > 0, f"manifest.js está vacío: {MANIFEST_JS}"
    assert py_size > 0, f"manifest.py está vacío: {MANIFEST_PY}"


def test_manifest_js_regex_extracted_reasonable_number_of_keys() -> None:
    """La regex del test extrae al menos ``MIN_EXPECTED_KEYS`` keys.

    Esto protege contra 2 clases de regresión silenciosa:
      a) Que alguien reformatee el dict ``_comps`` de ``manifest.js``
         y rompa la regex (el test pasaría con ``[]`` en lugar de
         fallar con un mensaje útil).
      b) Que alguien vacíe ``_comps`` o borre todas las entries por
         error.

    Si esto falla, la regex del helper es probablemente la culpable
    (no los manifests en sí).
    """
    keys_js = _extract_comps_keys_from_js(MANIFEST_JS)
    assert len(keys_js) >= MIN_EXPECTED_KEYS, (
        f"La regex extrajo {len(keys_js)} keys del dict _comps "
        f"de manifest.js, pero se esperaban al menos {MIN_EXPECTED_KEYS}. "
        "Posible causa: la regex de "
        "_extract_comps_keys_from_js() ya no encaja con el formato "
        "del dict (¿alguien reformateó _comps a otro estilo?). Keys "
        f"extraídas: {sorted(keys_js)}"
    )


def test_manifest_loaders_keys_match_between_js_and_py() -> None:
    """Drift check: las keys de ``_comps`` (JS) y ``loaders`` (PY)
    coinciden exactamente.

    Es un contract check: si en el futuro alguien añade un componente
    a uno de los dos manifests y se olvida del otro, este test
    cazará la divergencia con un mensaje que lista explícitamente
    las keys en JS pero no en PY (y viceversa).

    No se chequea el orden (los dos manifests pueden declarar las
    keys en orden distinto: lo importante es la igualdad de sets).
    """
    keys_js = _extract_comps_keys_from_js(MANIFEST_JS)

    # Importamos ``manifest.build()`` desde el área. Esto también
    # ejercita que el módulo sigue siendo importable (no se ha
    # roto la sintaxis de manifest.py).
    from areas.alimentacion.frontend.manifest import build

    manifest_dict = build()
    assert "loaders" in manifest_dict, (
        "El dict devuelto por manifest.build() no contiene la key "
        "'loaders'. ¿Se ha reformateado el shape del manifest? "
        f"Keys presentes: {sorted(manifest_dict.keys())}"
    )
    keys_py = list(manifest_dict["loaders"].keys())

    set_js = set(keys_js)
    set_py = set(keys_py)

    only_in_js = sorted(set_js - set_py)
    only_in_py = sorted(set_py - set_js)

    assert not only_in_js, (
        "Drift detectado: hay keys declaradas en "
        "manifest.js (_comps) que NO están en manifest.py (loaders). "
        f"Keys en JS pero no en PY: {only_in_js}. "
        "Sincroniza manifest.py añadiendo esas keys al dict 'loaders'."
    )
    assert not only_in_py, (
        "Drift detectado: hay keys declaradas en "
        "manifest.py (loaders) que NO están en manifest.js (_comps). "
        f"Keys en PY pero no en JS: {only_in_py}. "
        "Sincroniza manifest.js añadiendo esas keys al dict '_comps'."
    )

    # Bonus: si la diferencia es solo de case (p. ej. alguien escribe
    # ``alimentacionsidebar`` en un lado y ``AlimentacionSidebar`` en
    # el otro), el set-compare ya lo detecta (case-sensitive), pero
    # añadimos este check explícito para que el mensaje sea aún más
    # claro si se da el caso.
    lower_js = {k.lower() for k in keys_js}
    lower_py = {k.lower() for k in keys_py}
    only_in_js_lower = lower_js - lower_py
    only_in_py_lower = lower_py - lower_js
    if only_in_js_lower or only_in_py_lower:
        # Construimos un mapa case-insensitive para sugerir el
        # candidato más probable de typo.
        hints = []
        for lower_key in only_in_js_lower:
            for py_key in keys_py:
                if py_key.lower() == lower_key:
                    hints.append(
                        f"JS tiene {lower_key!r} pero PY tiene "
                        f"{py_key!r} (case distinto)"
                    )
        for lower_key in only_in_py_lower:
            for js_key in keys_js:
                if js_key.lower() == lower_key:
                    hints.append(
                        f"PY tiene {lower_key!r} pero JS tiene "
                        f"{js_key!r} (case distinto)"
                    )
        if hints:
            pytest.fail(
                "Drift de CASE detectado entre manifest.js y "
                "manifest.py (las keys SON case-sensitive). "
                + "; ".join(hints)
            )
