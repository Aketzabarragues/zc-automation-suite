"""Smoke test del wiring SPA ↔ nueva vista "Procesos" (Fase 6.A).

Primera fase (UI) de la funcionalidad de "generación de procesos
en TIA Portal" anunciada en el plan canónico
``_plan/04_excel_cache_phased_plan.md`` (Fase 6, extensión). En
esta fase la nueva sub-vista ``Procesos`` (accesible con
``store.currentView === 'proc'``) tiene UI pero NO lógica
backend: 2 cards con ``@click="alert('TODO: ...')"`` como
placeholders. La lógica real vendrá en una segunda fase.

La SPA es Vue 3 ESM sin build step y sin infra de tests JS
(Jest/Vitest no están en el repo). En lugar de importar los
``.js`` desde pytest (que necesitaría Node + ESM + DOM mock),
este test verifica la **forma textual** del wiring: que los
símbolos públicos esperados aparezcan en los archivos correctos
(``Procesos.js`` declara la sub-vista, ``manifest.js`` y
``manifest.py`` la registran con key ``proc``, ``Sidebar.js``
añade el 5º botón de navegación, ``AreaLanding.js`` añade la
4ª tarjeta en la welcome).

Es un contract check barato. Si en el futuro se añade infra JS,
se puede sustituir por tests unitarios de verdad sobre el
componente ``Procesos``.

Marcado con ``@pytest.mark.frontend_smoke`` para permitir
filtrado (``pytest -m frontend_smoke``).
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

PROCESOS_JS = (
    REPO_ROOT
    / "areas"
    / "alimentacion"
    / "frontend"
    / "components"
    / "Procesos.js"
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
AREA_LANDING_JS = (
    REPO_ROOT
    / "areas"
    / "alimentacion"
    / "frontend"
    / "components"
    / "AreaLanding.js"
)


pytestmark = pytest.mark.frontend_smoke


# ── Helpers ──────────────────────────────────────────────────────────────


def _read(path: Path) -> str:
    assert path.exists(), f"Missing required SPA file: {path}"
    return path.read_text(encoding="utf-8")


# ── Tests ────────────────────────────────────────────────────────────────


def test_procesos_component_file_exists() -> None:
    """El componente nuevo existe y tiene contenido no trivial.

    Defaults Vue 3 ESM (mismo patrón que el resto de componentes
    del área: ``BloquesCacheView.js``, ``ProcesosPanel.js``, etc.).
    > 1 KB de cuerpo descarta stubs vacíos / placeholders.
    """
    assert PROCESOS_JS.exists(), (
        f"Falta el componente: {PROCESOS_JS}"
    )
    text = _read(PROCESOS_JS)
    assert len(text) > 1024, (
        f"Procesos.js demasiado corto ({len(text)} bytes)"
    )
    assert "export default" in text, (
        "Falta el export default (no es un componente Vue 3 válido)"
    )
    assert "vue.esm-browser.prod.js" in text, (
        "Falta el import de Vue 3 ESM"
    )
    # El name declarado debe ser exactamente "Procesos" (coincide
    # con el loader en manifest.js/manifest.py y con la key
    # ``views``).
    assert 'name: "Procesos"' in text, (
        'Falta "name: \\"Procesos\\"" en el setup del componente'
    )


def test_procesos_uses_memory_state_procesos() -> None:
    """El componente declara el computed ``procesos`` que lee de
    ``store.memoryState.procesos`` con fallback defensivo a ``[]``.

    Mismo patrón que ``ProcesosPanel.js:45-47``: si el operario aún
    no ha subido Excel o el backend aún no expone el campo, devuelve
    ``[]`` para que la UI renderice sin error.
    """
    text = _read(PROCESOS_JS)
    # El computed ``procesos`` está en el setup.
    assert "const procesos = computed" in text, (
        "Falta el computed 'procesos' en el setup"
    )
    # Lee de ``store.memoryState.procesos`` (defensivo).
    assert "store.memoryState.procesos" in text, (
        "El computed 'procesos' no lee de store.memoryState.procesos"
    )
    # Fallback defensivo a ``[]``.
    assert "|| []" in text, (
        "Falta el fallback defensivo '|| []' para procesos"
    )


def test_procesos_has_two_placeholder_cards() -> None:
    """El template tiene exactamente 2 cards placeholder con
    ``@click="alert(...)"`` — uno para "Crear proceso completo" y
    otro para "Actualizar comentarios de DB". El copy debe ser
    literal (es lo que verá el operario).
    """
    text = _read(PROCESOS_JS)
    # 2 botones con ``@click="alert(...)"`` (uno por acción).
    alert_clicks = text.count('@click="alert(')
    assert alert_clicks == 2, (
        f"Esperaba 2 @click='alert(...)' (uno por card), "
        f"encontré {alert_clicks}"
    )
    # Copy literal de los 2 labels de las cards.
    assert "Crear proceso completo" in text, (
        "Falta el label 'Crear proceso completo' en una de las cards"
    )
    assert "Actualizar comentarios de DB" in text, (
        "Falta el label 'Actualizar comentarios de DB' en una de las cards"
    )
    # Los TODOs son explícitos (contrato con el operario: las cards
    # son placeholders, la lógica real viene en una segunda fase).
    assert "TODO: Crear proceso completo" in text, (
        "Falta el alert placeholder 'TODO: Crear proceso completo'"
    )
    assert "TODO: Actualizar comentarios de DB" in text, (
        "Falta el alert placeholder 'TODO: Actualizar comentarios de DB'"
    )


def test_procesos_has_amber_banner() -> None:
    """Aparece un banner ámbar que se muestra condicionalmente con
    ``v-if`` cuando no hay Excel o cuando el array de procesos está
    vacío. Mismo patrón que el banner ámbar de Fase 6 (clases
    ``bg-amber-100``, ``border-amber-300``, ``text-amber-800``).
    """
    text = _read(PROCESOS_JS)
    # Clases del banner ámbar (ya en styles.css, verificado por
    # grep del bundle).
    assert "bg-amber-100" in text, (
        "Falta la clase bg-amber-100 del banner ámbar"
    )
    assert "border-amber-300" in text, (
        "Falta la clase border-amber-300 del banner ámbar"
    )
    assert "text-amber-800" in text, (
        "Falta la clase text-amber-800 del banner ámbar"
    )
    # El banner está protegido por ``v-if`` (cubre los 2 casos:
    # sin Excel o sin procesos).
    assert "!hasExcel || !hasProcesos" in text, (
        "Falta el v-if del banner ámbar "
        "('!hasExcel || !hasProcesos')"
    )


def test_procesos_cards_disabled_without_selection() -> None:
    """Los 2 botones tienen ``:disabled="!canAct"`` y clases
    ``disabled:opacity-50 disabled:cursor-not-allowed`` para que
    aparezcan en gris y no-clickables cuando NO hay proceso
    seleccionado.
    """
    text = _read(PROCESOS_JS)
    # El computed ``canAct`` está en el setup (true solo si hay
    # proceso seleccionado).
    assert "const canAct = computed" in text, (
        "Falta el computed 'canAct' en el setup"
    )
    # Los 2 botones usan ``:disabled="!canAct"`` (el docstring del
    # ``canAct`` también lo menciona como referencia, por eso la
    # aserción es ``>= 2`` y no ``== 2``).
    disabled_clicks = text.count(':disabled="!canAct"')
    assert disabled_clicks >= 2, (
        f"Esperaba al menos 2 botones con :disabled='!canAct', "
        f"encontré {disabled_clicks}"
    )
    # Clases de estado deshabilitado.
    assert "disabled:opacity-50" in text, (
        "Falta la clase disabled:opacity-50 (cards deshabilitadas)"
    )
    assert "disabled:cursor-not-allowed" in text, (
        "Falta la clase disabled:cursor-not-allowed "
        "(cursor en cards deshabilitadas)"
    )


def test_manifest_includes_procesos_view() -> None:
    """Ambos manifests declaran la sub-vista ``proc`` → ``Procesos``
    y el loader del componente ``Procesos`` (espejo JS y Python
    sincronizados).

    Si solo uno de los 2 manifests lo tiene, el shell SPA fallaría
    al cargar la vista en producción (la SPA carga del endpoint
    ``/api/v1/areas/alimentacion/manifest`` que serializa el
    Python).
    """
    js_text = _read(MANIFEST_JS)
    py_text = _read(MANIFEST_PY)

    # JS: la key ``proc`` está en views y el componente en loaders.
    assert '"proc":' in js_text or "'proc':" in js_text, (
        "Falta la key 'proc' en views de manifest.js"
    )
    assert '"Procesos":' in js_text, (
        'Falta el loader "Procesos" en _comps de manifest.js'
    )
    assert 'import("./components/Procesos.js")' in js_text, (
        "Falta el import('./components/Procesos.js') en manifest.js"
    )

    # Python: mismo shape, mismas keys, URL string del loader.
    assert '"proc":' in py_text or "'proc':" in py_text, (
        "Falta la key 'proc' en views de manifest.py"
    )
    assert '"Procesos":' in py_text, (
        'Falta el loader "Procesos" en _manifest["loaders"] de manifest.py'
    )
    assert "/components/Procesos.js" in py_text, (
        "El loader Python debe apuntar a la URL del componente "
        "(/components/Procesos.js)"
    )


def test_sidebar_has_procesos_nav_button() -> None:
    """El Sidebar tiene un 5º botón que navega a la vista ``proc``
    con el label "Procesos" y el icono ⚙️. Va después del botón
    "Dispositivos" (orden de los 5 botones:
    Inicio → Definición → Cache → Dispositivos → Procesos).
    """
    text = _read(SIDEBAR_JS)
    # El botón llama a ``goToSubview('proc')``.
    assert "goToSubview('proc')" in text, (
        "Falta el goToSubview('proc') en el Sidebar"
    )
    # Etiqueta humano-legible que verá el operario.
    assert "Procesos" in text, (
        'Falta el label "Procesos" en el Sidebar'
    )
    # Icono de la nueva entrada (⚙️, engranaje).
    assert "⚙️" in text, (
        "Falta el icono ⚙️ en el botón del Sidebar"
    )
    # El botón de Procesos va DESPUÉS del de Dispositivos (orden
    # de la consigna: 5º botón al final).
    disp_pos = text.find("goToSubview('disp')")
    proc_pos = text.find("goToSubview('proc')")
    assert 0 <= disp_pos < proc_pos, (
        "El botón 'proc' debe ir DESPUÉS del botón 'disp' en el Sidebar"
    )


def test_area_landing_has_procesos_option() -> None:
    """El ``AreaLanding.js`` tiene la 4ª entry en ``SUBVIEW_OPTIONS``
    con ``key: "proc"``, icono ⚙️ y label "Procesos". El grid
    también pasa a ``xl:grid-cols-4`` para acomodar la nueva tarjeta
    sin apretar el layout de ``lg``.
    """
    text = _read(AREA_LANDING_JS)
    # La entry en SUBVIEW_OPTIONS.
    assert 'key: "proc"' in text, (
        'Falta la entry con key: "proc" en SUBVIEW_OPTIONS'
    )
    # Icono y label.
    assert "⚙️" in text, (
        "Falta el icono ⚙️ en la nueva entry de SUBVIEW_OPTIONS"
    )
    assert "Procesos" in text, (
        'Falta el label "Procesos" en la nueva entry de SUBVIEW_OPTIONS'
    )
    # Grid actualizado a ``xl:grid-cols-4`` (mantiene 3 cols en
    # ``lg`` para no apretar el layout existente).
    assert "xl:grid-cols-4" in text, (
        "Falta xl:grid-cols-4 en el grid de la welcome "
        "(debería ampliarse a 4 columnas en pantallas anchas)"
    )
    assert "lg:grid-cols-3" in text, (
        "lg:grid-cols-3 debe mantenerse (3 columnas en lg, "
        "4 solo en xl para no apretar el layout)"
    )


def test_db_names_computed_from_uid_not_from_dto_properties() -> None:
    """Regression test: el sub-caption con los nombres de los 2 DBs
    del proceso (PARAM / ALM) se computa en línea a partir de
    ``uid`` siguiendo la convención del DTO ``ProcesoPLC``, NO
    leyendo las properties ``db_preal_nombre`` / ``db_pint_nombre``
    / ``db_alm_nombre``.

    Razón técnica: esas properties son ``@property`` Python del
    DTO. El backend serializa con ``dataclasses.asdict`` (o
    equivalente), que solo emite los campos declarados, NO las
    properties. El JSON que recibe la SPA trae ``uid`` y
    ``codigo`` pero NO ``db_preal_nombre``. Si el template las
    usa, los huecos aparecen vacíos ("UID 1100 · DBs: , ").

    Convención (verificada en
    ``areas/alimentacion/domain/models/excel_cache.py``):
       * DB PARAM: 3000 + uid   (DB unificado de parámetros:
                                 PReal y PInt del mismo proceso
                                 comparten el mismo Num.DB en el
                                 Excel real; el DB PINT no existe)
       * DB ALM:   5000 + uid
       * Formato:  DB{numero}_{codigo}_SUFIJO

    Mismo patrón que ``ProcesosPanel.js`` (líneas del template que
    pintan ``DB{{ 3000 + p.uid }}`` y ``DB{{ 5000 + p.uid }}``).
    """
    import re

    text = _read(PROCESOS_JS)
    # Extraer solo el cuerpo del template (lo que hay entre los
    # delimitadores `` ` `` del ``template: /* html */ `...` ,``).
    # El docstring del componente SÍ puede mencionar los nombres
    # de las properties (es texto explicativo, no código que
    # ejecuta), así que el check se scopea al template body.
    pattern = re.compile(
        r"template:\s*/\*\s*html\s*\*/\s*`(.*?)`\s*,",
        re.DOTALL,
    )
    match = pattern.search(text)
    assert match is not None, (
        "No se encontró el template del componente Procesos.js"
    )
    template_body = match.group(1)

    # POSITIVO: el template computa los 2 DBs desde ``uid`` con
    # la fórmula correcta.
    assert "3000 + selectedProc.uid" in template_body, (
        "Falta el cálculo del DB PARAM (3000 + uid) en el template"
    )
    assert "5000 + selectedProc.uid" in template_body, (
        "Falta el cálculo del DB ALM (5000 + uid) en el template"
    )
    # El template usa ``codigo`` para componer el nombre simbólico
    # (formato DB{num}_{codigo}_SUFIJO).
    assert "selectedProc.codigo" in template_body, (
        "Falta el uso de selectedProc.codigo para componer "
        "el nombre simbólico del DB"
    )
    # NEGATIVO: el template NO debe leer las properties del DTO
    # (que no sobreviven al roundtrip JSON).
    assert "db_preal_nombre" not in template_body, (
        "El template lee db_preal_nombre (property @property "
        "del DTO) que no sobrevive al roundtrip JSON. Usar el "
        "cálculo en línea con 3000 + uid."
    )
    assert "db_pint_nombre" not in template_body, (
        "El template lee db_pint_nombre (property @property "
        "del DTO) que no sobrevive al roundtrip JSON."
    )
    assert "db_alm_nombre" not in template_body, (
        "El template lee db_alm_nombre (property @property "
        "del DTO) que no sobrevive al roundtrip JSON."
    )


def test_no_backticks_in_template_bodies() -> None:
    """Regression test: ningún componente Vue 3 del área puede tener
    backticks literales (`` ` ``) dentro del cuerpo de su template
    (``template: /* html */ `...` ,``).

    Bug histórico: cuando un comentario HTML dentro del template
    contiene backticks Markdown (p.ej. `` `ProcesoPLC` ``, `` `xl` ``,
    `` `lg` ``), el primer backtick **cierra prematuramente** el
    template literal de JavaScript. El parser JS ve HTML a medias,
    Vue intenta llamar a la cadena como función y falla con
    ``TypeError: "..." is not a function at <Componente>.js:N:M``.

    Este test es defensivo: parsea el cuerpo del template de cada
    componente y falla si encuentra algún backtick. Los backticks
    FUERA del template (en docstrings JS, en strings normales, etc.)
    son válidos y no se chequean.

    Detectado en commit ``b8338bb`` (Fase 6.A — UI Procesos) tras
    2 rounds de fix en ``AreaLanding.js`` y ``Procesos.js``.
    """
    import re

    components_dir = REPO_ROOT / "areas" / "alimentacion" / "frontend" / "components"
    # Regex con DOTALL: el ``.`` matchea newlines, necesario para
    # capturar todo el template body (que es multi-línea).
    pattern = re.compile(
        r"template:\s*/\*\s*html\s*\*/\s*`(.*?)`\s*,",
        re.DOTALL,
    )
    offenders: list[tuple[str, int]] = []
    for js_file in sorted(components_dir.glob("*.js")):
        text = js_file.read_text(encoding="utf-8")
        match = pattern.search(text)
        if not match:
            continue
        body = match.group(1)
        # Contar backticks en el cuerpo (no en los delimitadores
        # del template literal, que ya están fuera del grupo 1).
        count = body.count("`")
        if count > 0:
            offenders.append((js_file.name, count))
    assert not offenders, (
        f"Backticks literales encontrados dentro de templates "
        f"(rompen el template literal de JS): {offenders}. "
        f"Reemplazar por comillas simples o dobles en los "
        f"comentarios HTML del template."
    )
