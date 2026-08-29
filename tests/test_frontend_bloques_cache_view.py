"""Smoke test del wiring SPA ↔ vista "Cache de bloques".

La SPA es Vue 3 ESM sin build step y sin infra de tests JS
(Jest/Vitest no están en el repo). En lugar de importar los
``.js`` desde pytest (que necesitaría Node + ESM + DOM mock),
este test verifica la **forma textual** del wiring: que los
símbolos públicos esperados aparezcan en los archivos correctos.

Es un contract check barato. Si en el futuro se añade infra JS,
se puede sustituir por tests unitarios de verdad sobre el
componente ``BloquesCacheView`` y los helpers
``loadPlcBlocksCache`` / ``refreshPlcBlocksCache``.

Marcado con ``@pytest.mark.frontend_smoke`` para permitir
filtrado (``pytest -m frontend_smoke``).
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

BLOQUES_CACHE_VIEW_JS = (
    REPO_ROOT
    / "areas"
    / "alimentacion"
    / "frontend"
    / "components"
    / "BloquesCacheView.js"
)
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
SIDEBAR_JS = (
    REPO_ROOT
    / "areas"
    / "alimentacion"
    / "frontend"
    / "components"
    / "Sidebar.js"
)
STORE_JS = REPO_ROOT / "interfaces" / "web_server" / "static" / "js" / "store.js"
STYLES_CSS = REPO_ROOT / "interfaces" / "web_server" / "static" / "styles.css"


pytestmark = pytest.mark.frontend_smoke


def _read(path: Path) -> str:
    assert path.exists(), f"Missing required SPA file: {path}"
    return path.read_text(encoding="utf-8")


def test_bloques_cache_view_file_exists() -> None:
    """El componente nuevo existe y tiene contenido no trivial."""
    assert BLOQUES_CACHE_VIEW_JS.exists(), (
        f"Falta el componente: {BLOQUES_CACHE_VIEW_JS}"
    )
    text = _read(BLOQUES_CACHE_VIEW_JS)
    # > 1 KB de cuerpo: descarta stubs vacíos / placeholders.
    assert len(text) > 1024, (
        f"BloquesCacheView.js demasiado corto ({len(text)} bytes)"
    )
    # Defaults Vue 3 ESM.
    assert "export default" in text
    assert "vue.esm-browser.prod.js" in text


def test_bloques_cache_view_uses_three_tabs() -> None:
    """La vista declara las 3 pestañas: Bloques / Variables / UDT."""
    text = _read(BLOQUES_CACHE_VIEW_JS)
    assert "Bloques" in text
    assert "Variables" in text
    assert "UDT" in text
    # Hay 3 mutaciones de ``activeTab`` (1 por pestaña) — sanity check.
    assert text.count("activeTab = ") >= 3


def test_bloques_cache_view_has_refresh_button() -> None:
    """La vista tiene un botón de refresh manual.

    El operario lo usa para forzar un re-scan del PLC sin esperar
    al TTL de 5 min del cache backend. Lo identificamos por su
    label (acepta tanto el glifo ↻ como la palabra "Refrescar").
    """
    text = _read(BLOQUES_CACHE_VIEW_JS)
    assert "Refrescar" in text
    assert "↻" in text
    # El handler está cableado al click del botón.
    assert "@click=\"handleRefresh\"" in text
    assert "function handleRefresh" in text


def test_manifest_includes_cache_view() -> None:
    """Ambos manifests declaran la vista ``cache`` y el componente
    ``BloquesCacheView`` (espejo JS y Python sincronizados).
    """
    js_text = _read(MANIFEST_JS)
    py_text = _read(MANIFEST_PY)

    # JS: routes + loaders.
    assert '"cache":' in js_text or "'cache':" in js_text
    assert "BloquesCacheView" in js_text
    assert "import(\"./components/BloquesCacheView.js\")" in js_text

    # Python: mismo shape, mismas keys, URL string del loader.
    assert '"cache":' in py_text or "'cache':" in py_text
    assert "BloquesCacheView" in py_text
    assert (
        "/components/BloquesCacheView.js" in py_text
    ), "El loader Python debe apuntar a la URL del componente"


def test_sidebar_has_cache_nav_button() -> None:
    """El Sidebar tiene un botón que navega a la vista ``cache``."""
    text = _read(SIDEBAR_JS)
    # El botón llama a ``goToSubview('cache')``.
    assert "goToSubview('cache')" in text
    # Y referencia la etiqueta humano-legible que verá el operario.
    assert "Cache de bloques" in text


def test_store_has_plc_blocks_cache() -> None:
    """``store.js`` re-introduce ``plcBlocksCache`` + los dos helpers
    de carga/refresh para la nueva vista.
    """
    text = _read(STORE_JS)
    # Slot de datos en el ``reactive({...})``.
    assert "plcBlocksCache:" in text
    # Helpers exportados.
    assert "export async function loadPlcBlocksCache" in text
    assert "export async function refreshPlcBlocksCache" in text


def test_styles_css_regenerated() -> None:
    """El bundle CSS existe y tiene tamaño no trivial tras el
    recompile de Tailwind posterior a la alta de la vista.

    El input.css ya incluye el glob ``areas/**/frontend/**/*.js``
    (ver ``interfaces/web_server/static/src/input.css``), así que
    las clases nuevas de ``BloquesCacheView`` se detectan
    automáticamente. Aquí solo validamos que la recompilación
    efectivamente regeneró el bundle.
    """
    assert STYLES_CSS.exists(), (
        "styles.css no se regeneró — ejecutar run_tailwind.bat "
        "antes de commit"
    )
    size = STYLES_CSS.stat().st_size
    assert size > 10_000, (
        f"styles.css demasiado pequeño ({size} bytes); "
        "recompilar Tailwind antes de commit"
    )
