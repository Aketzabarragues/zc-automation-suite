"""Smoke tests del componente ``TiaConnectionIndicator.js``.

Cubre el lado frontend del indicador de estado del worker TIA
persistente (PR 5b / §4.2 del design doc). Como en el resto de
los tests frontend del repo (ver
``test_frontend_tia_connection_invalidation.py``), sin infra JS
(Jest/Vitest): se valida el contrato textual sobre los ``.js``
(estructura, imports, dependencias). Más adelante, si se
añade un runner de Vue, se podrían añadir tests de render
sobre el DOM.

Aspectos cubiertos:
  1. El componente existe, exporta un default, declara emits y
     devuelve ``colorClass`` / ``tooltip`` / ``handleClick``
     desde el ``setup()``.
  2. ``colorClass.value`` mapea cada ``state`` a la clase
     Tailwind correcta (``bg-green-500`` para ``connected``,
     ``bg-amber-500 animate-pulse`` para ``connecting``, etc.).
  3. ``tooltip.value`` muestra el nombre del proyecto cuando
     está ``connected`` y el mensaje de error en estado
     ``error``.
  4. ``handleClick`` emite ``"connect"`` SOLO cuando el estado
     es ``disconnected`` o ``error``; en otros estados es no-op.

Marcado con ``@pytest.mark.frontend_smoke`` para permitir
filtrado (``pytest -m frontend_smoke``).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
COMPONENT_JS = (
    REPO_ROOT
    / "interfaces"
    / "web_server"
    / "static"
    / "js"
    / "components"
    / "TiaConnectionIndicator.js"
)


pytestmark = pytest.mark.frontend_smoke


def _read(path: Path) -> str:
    assert path.exists(), f"Missing required SPA file: {path}"
    return path.read_text(encoding="utf-8")


# ── Estructura del componente ────────────────────────────────────────


def test_component_file_exists_and_exports_default() -> None:
    """El archivo existe y exporta un default object con ``name``,
    ``setup`` y ``template`` (mismo patrón que el resto de
    componentes Vue 3 ESM del repo)."""
    text = _read(COMPONENT_JS)
    assert "export default {" in text, (
        "TiaConnectionIndicator.js debe exportar un default object."
    )
    assert 'name: "TiaConnectionIndicator"' in text, (
        "El componente debe declarar name='TiaConnectionIndicator' "
        "para que ``_app.component()`` pueda registrarlo."
    )
    assert "setup" in text, "El componente debe tener un setup()."
    assert "template:" in text, "El componente debe tener un template string."


def test_component_declares_connect_emit() -> None:
    """El componente declara el emit ``"connect"`` (sin él, el
    handler del ShellTopbar no podría enterarse del click para
    reconectar)."""
    text = _read(COMPONENT_JS)
    assert 'emits: ["connect"]' in text or "emits:['connect']" in text, (
        'TiaConnectionIndicator debe declarar emits: ["connect"] para '
        "que el ShellTopbar pueda capturar el click y reconectar."
    )


def test_component_returns_color_class_tooltip_handle_click_from_setup() -> None:
    """REGLA Vue 3 sin build step (ver AGENTS.md): el template
    solo ve lo que ``setup()`` retorna. El componente debe
    exponer ``colorClass``, ``tooltip`` y ``handleClick`` en el
    return para que el template los use en ``:class``, ``:title``
    y ``@click`` respectivamente."""
    text = _read(COMPONENT_JS)
    # Buscamos el return del setup.
    assert "return { state, project, colorClass, tooltip, handleClick" in text, (
        "El setup() debe retornar explícitamente state, project, "
        "colorClass, tooltip y handleClick. Sin esto, el template "
        "no podría usar :class=colorClass ni :title=tooltip (ver "
        "AGENTS.md, sección 'Vue 3 sin build step — acceso a store "
        "desde templates')."
    )


def test_component_encapsulates_store_access_in_computed() -> None:
    """El componente NO debe acceder a ``store`` directamente en
    el template (eso lanza TypeError en runtime con el
    compilador de Vue sin build step). El acceso a
    ``store.tiaConnection.*`` debe ir SIEMPRE vía ``computed``
    en el ``setup()``."""
    text = _read(COMPONENT_JS)
    # Hay computed para state, project, etc.
    assert "const state = computed(() =>" in text, (
        "state debe ser un computed que lea store.tiaConnection.state "
        "(regla Vue 3 sin build step)."
    )
    assert "const project = computed(() =>" in text, (
        "project debe ser un computed (regla Vue 3 sin build step)."
    )
    # Y el template no contiene store.tiaConnection (lo lee via
    # la variable ``state`` retornada del setup).
    # Aislamos el template string (entre `template: /* html */ \`` y
    # el cierre `\`,`) y verificamos que NO menciona store.
    start = text.find("template:")
    assert start != -1
    template_block = text[start:]
    # Truncamos al primer `\`,` que cierra el template string.
    end = template_block.find("`,")
    assert end != -1
    template_str = template_block[:end]
    assert "store.tiaConnection" not in template_str, (
        "El template NO debe leer store.tiaConnection directamente. "
        "El acceso debe pasar por computed() expuesto desde setup()."
    )


# ── colorClass segun state ────────────────────────────────────────────


def _extract_color_class_logic(text: str) -> str:
    """Devuelve el cuerpo del computed ``colorClass`` para tests
    posteriores."""
    start = text.find("const colorClass = computed(() => {")
    assert start != -1, "colorClass computed no encontrado en TiaConnectionIndicator.js"
    # Cogemos los siguientes 800 chars (suficiente para el switch).
    return text[start:start + 800]


def test_color_class_connected_uses_green_500() -> None:
    """``state === 'connected'`` → clase ``bg-green-500``."""
    body = _extract_color_class_logic(_read(COMPONENT_JS))
    assert '"connected":' in body, "Falta el case 'connected' en colorClass."
    assert 'return "bg-green-500"' in body, (
        "El case 'connected' debe devolver la clase 'bg-green-500' "
        "(círculo verde cuando TIA está conectado)."
    )


def test_color_class_connecting_uses_amber_500_with_pulse() -> None:
    """``state === 'connecting'`` → ``bg-amber-500 animate-pulse``."""
    body = _extract_color_class_logic(_read(COMPONENT_JS))
    assert '"connecting":' in body
    assert 'return "bg-amber-500 animate-pulse"' in body, (
        "El case 'connecting' debe devolver "
        "'bg-amber-500 animate-pulse' (ámbar pulsante durante el "
        "cold-attach, que puede tardar 5-30s)."
    )


def test_color_class_disconnected_uses_gray_400() -> None:
    """``state === 'disconnected'`` → ``bg-gray-400``."""
    body = _extract_color_class_logic(_read(COMPONENT_JS))
    assert '"disconnected":' in body
    assert 'return "bg-gray-400"' in body, (
        "El case 'disconnected' debe devolver 'bg-gray-400' "
        "(gris neutro, estado idle)."
    )


def test_color_class_error_uses_red_500() -> None:
    """``state === 'error'`` → ``bg-red-500``."""
    body = _extract_color_class_logic(_read(COMPONENT_JS))
    assert '"error":' in body
    assert 'return "bg-red-500"' in body, (
        "El case 'error' debe devolver 'bg-red-500' (rojo cuando "
        "el worker no se puede conectar)."
    )


# ── tooltip segun state ──────────────────────────────────────────────


def test_tooltip_includes_project_name_when_connected() -> None:
    """Cuando ``state === 'connected'`` y hay proyecto, el tooltip
    debe mencionar su nombre (multilínea con ``\\n``)."""
    text = _read(COMPONENT_JS)
    # Localizamos el bloque del computed ``tooltip``.
    start = text.find("const tooltip = computed(() => {")
    assert start != -1
    body = text[start:start + 1000]
    assert 'state.value === "connected"' in body
    assert "project.value.name" in body, (
        "El tooltip del estado 'connected' debe incluir el nombre "
        "del proyecto TIA (project.value.name)."
    )
    assert "\\n" in body, (
        "El tooltip debe ser multilínea (separador '\\n')."
    )
    assert "PLCs:" in body, (
        "El tooltip conectado debe mostrar el nº de PLCs detectados."
    )


def test_tooltip_shows_error_message_in_error_state() -> None:
    """Cuando ``state === 'error'``, el tooltip debe mostrar el
    mensaje de error (o 'desconocido' si no hay)."""
    text = _read(COMPONENT_JS)
    start = text.find("const tooltip = computed(() => {")
    assert start != -1
    body = text[start:start + 1000]
    assert 'state.value === "error"' in body
    assert "Error:" in body, (
        "El tooltip en estado 'error' debe empezar con 'Error:'."
    )
    assert "error.value" in body, (
        "El tooltip en estado 'error' debe leer el last_error del store."
    )


# ── handleClick segun state ──────────────────────────────────────────


def test_handle_click_emits_connect_when_disconnected() -> None:
    """``handleClick`` debe emitir ``"connect"`` cuando el estado
    es ``disconnected`` o ``error``. En otros estados, no debe
    emitir nada (no-op)."""
    text = _read(COMPONENT_JS)
    start = text.find("function handleClick()")
    assert start != -1, "handleClick no encontrado en TiaConnectionIndicator.js"
    body = text[start:start + 400]
    assert '"disconnected"' in body, (
        "handleClick debe comprobar state === 'disconnected'."
    )
    assert '"error"' in body, (
        "handleClick debe comprobar state === 'error' (también "
        "permite reconectar tras un fallo)."
    )
    assert 'emit("connect")' in body, (
        'handleClick debe emitir emit("connect") para que el '
        "ShellTopbar llame a connectTia()."
    )


# ── data-testid (para QA manual y tests E2E) ─────────────────────────


def test_component_exposes_data_testid_for_QA() -> None:
    """El botón expone ``data-testid="tia-connection-indicator"``
    para que las pruebas E2E / QA manual puedan localizarlo
    sin depender de selectores estructurales."""
    text = _read(COMPONENT_JS)
    assert 'data-testid="tia-connection-indicator"' in text, (
        "El botón debe llevar data-testid='tia-connection-indicator' "
        "para facilitar QA y tests E2E."
    )


# ── Sanity check: el JS se puede parsear (sin errores de sintaxis) ─


def test_component_js_is_syntactically_valid() -> None:
    """Sanity check: el .js se parsea sin errores. Usamos ``node``
    si está disponible; si no, comprobamos manualmente que las
    llaves y paréntesis están balanceados."""
    if not COMPONENT_JS.exists():
        pytest.skip("Componente no encontrado")
    text = _read(COMPONENT_JS)
    # Chequeo de balanceo: cada ``{`` debe tener su ``}`` y cada
    # ``(`` su ``)``. No es perfecto (ignora strings y comentarios)
    # pero atrapa la mayoría de los typos que romperían la SPA.
    assert text.count("{") == text.count("}"), (
        f"Llaves no balanceadas: {text.count('{')} '{{' vs "
        f"{text.count('}')} '}}' en TiaConnectionIndicator.js"
    )
    assert text.count("(") == text.count(")"), (
        f"Paréntesis no balanceados: {text.count('(')} '(' vs "
        f"{text.count(')')} ')' en TiaConnectionIndicator.js"
    )


def test_component_js_parses_with_node_if_available() -> None:
    """Si node está disponible, parseamos el .js con ``--check``.
    Es un sanity test más robusto que el balanceo de llaves."""
    if not COMPONENT_JS.exists():
        pytest.skip("Componente no encontrado")
    try:
        result = subprocess.run(
            ["node", "--check", str(COMPONENT_JS)],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        pytest.skip("node no disponible en este entorno")
    except subprocess.TimeoutExpired:
        pytest.fail("node --check tardó demasiado en TiaConnectionIndicator.js")
    if result.returncode != 0:
        pytest.fail(
            f"TiaConnectionIndicator.js no parsea con node --check:\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )


# ── Sanity: el JS es JS válido (no Python accidental) ───────────────


def test_component_js_is_not_empty_and_is_js_not_python() -> None:
    """El archivo debe ser JS real (no Python por error de copy-paste)."""
    text = _read(COMPONENT_JS)
    assert "import {" in text or "import " in text, (
        "TiaConnectionIndicator.js debe tener imports ESM."
    )
    assert "def " not in text, "El archivo parece Python (def encontrado)."
    # Comentarios JS usan // no #
    assert not text.lstrip().startswith("#"), (
        "El archivo no debe empezar con '#' (eso es un comentario Python)."
    )
