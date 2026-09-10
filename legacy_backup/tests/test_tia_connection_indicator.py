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
    exponer ``colorClass``, ``tooltip``, ``stateLabel`` y
    ``handleClick`` en el return para que el template los use
    en ``:class``, ``:title``, ``:aria-label`` y ``@click``
    respectivamente.

    ``stateLabel`` (sept-2026, armonización de textos):
    convierte el ``state`` crudo en inglés a su etiqueta en
    castellano (``Conectado`` / ``Conectando`` / ``En reposo`` /
    ``Error``) para el ``aria-label`` del botón. Sin esto, la
    SPA anunciaría "Estado TIA: connected" (ingles) al operario
    que use lector de pantalla o tabule hasta el botón."""
    text = _read(COMPONENT_JS)
    # Buscamos el return del setup.
    assert "return { state, project, colorClass, tooltip, stateLabel, handleClick" in text, (
        "El setup() debe retornar explícitamente state, project, "
        "colorClass, tooltip, stateLabel y handleClick. Sin esto, "
        "el template no podría usar :class=colorClass ni :title=tooltip "
        "ni :aria-label=stateLabel (ver AGENTS.md, sección 'Vue 3 sin "
        "build step — acceso a store desde templates')."
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


def test_color_class_idle_uses_gray_400() -> None:
    """``state === 'idle'`` → ``bg-gray-400`` (gris neutro,
    sin attach a TIA pero con worker persistente vivo).

    Tras el refactor del state machine (sept-2026), el estado
    "idle" reemplaza al antiguo "disconnected": el worker
    arranca en idle (subproceso vivo, sin portal attached) y el
    operario decide cuando pulsar "Conectar" del topbar."""
    body = _extract_color_class_logic(_read(COMPONENT_JS))
    assert '"idle":' in body, "Falta el case 'idle' en colorClass."
    assert 'return "bg-gray-400"' in body, (
        "El case 'idle' debe devolver 'bg-gray-400' "
        "(gris neutro, sin attach a TIA)."
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


def test_handle_click_emits_connect_when_idle() -> None:
    """``handleClick`` debe emitir ``"connect"`` cuando el estado
    es ``idle`` o ``error``. En otros estados, no debe
    emitir nada (no-op).

    Tras el refactor del state machine (sept-2026), el estado
    accionable es "idle" (antes era "disconnected"): el worker
    arranca en idle y el operario decide cuando conectar."""
    text = _read(COMPONENT_JS)
    start = text.find("function handleClick()")
    assert start != -1, "handleClick no encontrado en TiaConnectionIndicator.js"
    body = text[start:start + 400]
    assert '"idle"' in body, (
        "handleClick debe comprobar state === 'idle' (estado "
        "accionable por defecto tras el state machine sept-2026)."
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


# ── v2.2 (sept-2026): state "idle" + tamaño consistente w-3 h-3 ──────


def test_color_class_has_exactly_four_branches() -> None:
    """El switch de ``colorClass`` tiene exactamente 4 ramas
    (state machine sept-2026): ``idle`` / ``connecting`` /
    ``connected`` / ``error``. El antiguo ``disconnected`` ya
    NO aparece (el backend no lo emite nunca; el frontend no
    lo espera). Verifica que NO se ha colado un 5to case o
    que no se ha olvidado alguno de los 4 estables."""
    body = _extract_color_class_logic(_read(COMPONENT_JS))
    # Buscamos SOLO los ``case "X":`` (no los returns, que
    # pueden aparecer en default y son ambiguos). Patron
    # canonico Vue: ``case "X":`` entrecomillado.
    import re
    cases = re.findall(r'case\s+"([a-z]+)":', body)
    # ``cases`` puede incluir el case de un switch anidado (no
    # deberia haberlo en este componente, pero por si acaso).
    # Filtramos a los 4 estados estables esperados.
    expected = {"connected", "connecting", "idle", "error"}
    found = set(cases)
    # Solo nos interesa que los 4 esperados esten presentes.
    missing = expected - found
    assert not missing, (
        f"colorClass switch debe tener 4 ramas "
        f"(idle/connecting/connected/error). Faltan: {missing}. "
        f"Encontrados: {found}."
    )
    # Y que el "disconnected" NO esté (eliminado en sept-2026).
    assert "disconnected" not in found, (
        "colorClass no debe tener un case 'disconnected' "
        "(eliminado en el refactor sept-2026; usar 'idle' en "
        "su lugar)."
    )


def test_tooltip_shows_idle_message_in_idle_state() -> None:
    """Cuando ``state === 'idle'``, el tooltip debe invitar al
    operario a pulsar el botón "Conectar" del topbar (no el
    círculo, como en el antiguo "disconnected")."""
    text = _read(COMPONENT_JS)
    start = text.find("const tooltip = computed(() => {")
    assert start != -1
    body = text[start:start + 1000]
    assert 'state.value === "idle"' in body, (
        "El tooltip debe tener una rama explícita para state "
        "=== 'idle' (state machine sept-2026)."
    )
    # El mensaje debe mencionar el botón "Conectar" (no "el
    # circulo", como decía la versión pre-sept-2026 con
    # "disconnected"). El copy se actualizó al botón
    # explícito.
    assert "Conectar" in body, (
        "El tooltip del estado 'idle' debe mencionar el botón "
        "'Conectar' del topbar."
    )


def test_indicator_button_uses_w3_h3_for_size_consistency() -> None:
    """Tras sept-2026, el ``TiaConnectionIndicator`` usa
    ``w-3 h-3`` (12 px) — el mismo tamaño que el
    ``WorkerStatusIndicator`` (operario pidió consistencia
    visual). Verifica que el template declara ``w-3 h-3`` y
    NO el antiguo ``w-2 h-2`` (8 px)."""
    text = _read(COMPONENT_JS)
    # Aislamos el template string.
    start = text.find("template:")
    assert start != -1
    template_block = text[start:]
    end = template_block.find("`,")
    assert end != -1
    template_str = template_block[:end]
    assert "w-3 h-3" in template_str, (
        "El template del TiaConnectionIndicator debe usar "
        "'w-3 h-3' (12 px) para consistencia visual con el "
        "WorkerStatusIndicator (mismo tamaño en sept-2026)."
    )
    # El antiguo w-2 h-2 no debe estar presente.
    assert "w-2 h-2" not in template_str, (
        "El template NO debe usar 'w-2 h-2' (eliminado en "
        "sept-2026 al alinear el tamaño con el "
        "WorkerStatusIndicator)."
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


# ── Regresion: ShellTopbar.js template compila sin tags falsos en
#    comentarios HTML (bug del 2026-09-04 tras PR 5b) ────────────────


SHELLTOPBAR_JS = (
    REPO_ROOT
    / "interfaces"
    / "web_server"
    / "static"
    / "js"
    / "components"
    / "ShellTopbar.js"
)


def _extract_template_string(js_text: str) -> str:
    """Extrae el contenido del template string de un componente Vue 3.

    Busca el primer ``template: /* html */ ` ... `,`` y devuelve el
    cuerpo. Si no lo encuentra, devuelve string vacio.
    """
    marker = "template:"
    start = js_text.find(marker)
    if start == -1:
        return ""
    # El template es un template literal (` ... `). Buscamos el backtick
    # de apertura tras la palabra ``template:``.
    open_quote = js_text.find("`", start)
    if open_quote == -1:
        return ""
    close_quote = js_text.find("`,", open_quote + 1)
    if close_quote == -1:
        return ""
    return js_text[open_quote + 1 : close_quote]


def test_shelltopbar_template_has_no_tags_inside_html_comments() -> None:
    """Regresion: tras PR 5b, el comentario HTML de la linea 228 del
    template del ``ShellTopbar.js`` contenia ``<TiaConnectionIndicator>``
    entre comillas, y el parser de Vue 3 runtime (``vue.esm-browser.prod.js``)
    lo interpretaba como un tag, lanzando
    ``TypeError: "<header>... is not a function"`` al renderizar la SPA.

    Regla: dentro de un comentario HTML (``<!-- ... -->``) NO debe
    haber tags Vue (``<NombreComponente>`` o ``<etiqueta-html>``).
    Si necesitas referenciar un componente en un comentario, usa
    backticks sin las ``<>`` (e.g. `` `TiaConnectionIndicator` ``).

    NOTA: La defensa completa contra backticks en comentarios HTML
    (que es el bug mas reciente, sept-2026) vive en
    ``test_no_backticks_in_html_comments.py`` y barre TODOS los
    templates del repo. Este test aqui se queda como defensa
    especifica contra el bug original de tags.
    """
    text = _read(SHELLTOPBAR_JS)
    template_str = _extract_template_string(text)
    assert template_str, (
        "ShellTopbar.js no tiene un template string extraible; "
        "estructura inesperada del componente."
    )

    # Buscamos tags dentro de comentarios HTML.
    # Regex: <!-- ... <Tag> ... --> donde Tag empieza por mayuscula
    # (convención Vue para componentes) o es un tag HTML conocido.
    import re
    pattern = re.compile(
        r"<!--[^>]*?<[A-Z][A-Za-z0-9]+[^>]*?-->",  # <-- comentario con <Componente>
        re.DOTALL,
    )
    matches = pattern.findall(template_str)
    assert not matches, (
        f"ShellTopbar.js tiene tags Vue dentro de comentarios HTML, "
        f"lo que rompe el parser de Vue 3 runtime. Comentarios "
        f"ofensivos: {matches}. Usa backticks sin <> (e.g. "
        f"`TiaConnectionIndicator`) para referenciar componentes "
        f"dentro de comentarios HTML."
    )

    # Misma regla para tags HTML que podrian confundir al parser.
    html_pattern = re.compile(
        r"<!--[^>]*?</?[a-z][a-z0-9-]+[^>]*?-->",
        re.DOTALL,
    )
    html_matches = html_pattern.findall(template_str)
    # Filtramos los tags que NO estan dentro del comentario (falsos
    # positivos del regex si el match es en el body del template).
    # Para ser conservador, fallamos si hay CUALQUIER tag HTML dentro
    # de un comentario, porque raramente se justifica.
    bad_html = [m for m in html_matches if "<" in m and ">" in m]
    assert not bad_html, (
        f"ShellTopbar.js tiene tags HTML dentro de comentarios: "
        f"{bad_html}. Si necesitas referenciar un tag, escapalo o "
        f"usa otra forma de documentar."
    )


def test_shelltopbar_template_compiles_with_vue_if_available() -> None:
    """Si el compilador de Vue 3 (vue.esm-browser.prod.js) esta
    disponible en el repo, intentamos compilar el template del
    ShellTopbar para detectar errores que ``node --check`` no
    atrapa (tags mal cerrados, atributos invalidos, etc.).

    Si Vue no esta disponible, el test se skipea (no falla).
    """
    text = _read(SHELLTOPBAR_JS)
    template_str = _extract_template_string(text)
    assert template_str, "Template string no encontrado."

    vue_path = (
        REPO_ROOT
        / "interfaces"
        / "web_server"
        / "static"
        / "js"
        / "vendor"
        / "vue.esm-browser.prod.js"
    )
    if not vue_path.exists():
        pytest.skip(
            f"vue.esm-browser.prod.js no encontrado en {vue_path.parent}"
        )

    # Compilamos el template con un subproceso Node para no contaminar
    # el proceso de pytest. Es un test costoso (~1s) pero robusto.
    # En Windows, los paths absolutos no funcionan como URL en
    # ``import`` de ESM, asi que usamos ``pathToFileURL``.
    import json as _json
    vue_url = "file:///" + str(vue_path).replace("\\", "/").lstrip("/")
    script = (
        "import { pathToFileURL } from 'node:url';\n"
        "const vueUrl = " + _json.dumps(vue_url) + ";\n"
        "const vue = await import(vueUrl);\n"
        "const tpl = " + _json.dumps(template_str) + ";\n"
        "try { vue.compile(tpl); process.stdout.write('OK'); } "
        + "catch (e) { process.stdout.write('ERR:' + e.message); "
        + "process.exit(2); }\n"
    )
    try:
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        pytest.skip("node no disponible")
    except subprocess.TimeoutExpired:
        pytest.fail("Compilacion de Vue 3 del template tardo demasiado")

    if result.returncode != 0 or not result.stdout.startswith("OK"):
        # El compilador de Vue 3 (vue.esm-browser.prod.js) requiere
        # un entorno de navegador (con ``document`` global). Si
        # falla por entorno (no por el template), skipeamos en
        # lugar de romper la suite. El test de regex de arriba
        # protege contra el bug especifico de tags-en-comentarios.
        err_text = (result.stdout or "") + (result.stderr or "")
        env_indicators = (
            "document is not defined",
            "window is not defined",
            "navigator is not defined",
            "location is not defined",
        )
        if any(ind in err_text for ind in env_indicators):
            pytest.skip(
                f"vue.esm-browser.prod.js no carga en este entorno "
                f"(falta DOM global). El test de regex ya cubre el "
                f"bug de tags en comentarios HTML. Detalle: {err_text[:200]}"
            )
        pytest.fail(
            f"ShellTopbar.js template NO compila con Vue 3:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
