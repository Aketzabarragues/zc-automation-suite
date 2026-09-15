"""Smoke test del wiring SPA â†” nueva vista "Procesos" (Fase 6.A).

Primera fase (UI) de la funcionalidad de "generaciÃ³n de procesos
en TIA Portal" anunciada en el plan canÃ³nico
``_plan/04_excel_cache_phased_plan.md`` (Fase 6, extensiÃ³n). En
esta fase la nueva sub-vista ``Procesos`` (accesible con
``store.currentView === 'proc'``) tiene UI pero NO lÃ³gica
backend: 2 cards con ``@click="alert('TODO: ...')"`` como
placeholders. La lÃ³gica real vendrÃ¡ en una segunda fase.

La SPA es Vue 3 ESM sin build step y sin infra de tests JS
(Jest/Vitest no estÃ¡n en el repo). En lugar de importar los
``.js`` desde pytest (que necesitarÃ­a Node + ESM + DOM mock),
este test verifica la **forma textual** del wiring: que los
sÃ­mbolos pÃºblicos esperados aparezcan en los archivos correctos
(``Procesos.js`` declara la sub-vista, ``manifest.js`` y
``manifest.py`` la registran con key ``proc``, ``Sidebar.js``
aÃ±ade el 5Âº botÃ³n de navegaciÃ³n, ``AreaLanding.js`` aÃ±ade la
4Âª tarjeta en la welcome).

Es un contract check barato. Si en el futuro se aÃ±ade infra JS,
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
API_JS = (
    REPO_ROOT
    / "interfaces"
    / "web_server"
    / "static"
    / "js"
    / "api.js"
)


pytestmark = pytest.mark.frontend_smoke


# â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _read(path: Path) -> str:
    assert path.exists(), f"Missing required SPA file: {path}"
    return path.read_text(encoding="utf-8")


# â”€â”€ Tests â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_procesos_component_file_exists() -> None:
    """El componente nuevo existe y tiene contenido no trivial.

    Defaults Vue 3 ESM (mismo patrÃ³n que el resto de componentes
    del Ã¡rea: ``BloquesCacheView.js``, ``ProcesosPanel.js``, etc.).
    > 1 KB de cuerpo descarta stubs vacÃ­os / placeholders.
    """
    assert PROCESOS_JS.exists(), (
        f"Falta el componente: {PROCESOS_JS}"
    )
    text = _read(PROCESOS_JS)
    assert len(text) > 1024, (
        f"Procesos.js demasiado corto ({len(text)} bytes)"
    )
    assert "export default" in text, (
        "Falta el export default (no es un componente Vue 3 vÃ¡lido)"
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

    Mismo patrÃ³n que ``ProcesosPanel.js:45-47``: si el operario aÃºn
    no ha subido Excel o el backend aÃºn no expone el campo, devuelve
    ``[]`` para que la UI renderice sin error.
    """
    text = _read(PROCESOS_JS)
    # El computed ``procesos`` estÃ¡ en el setup.
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
    """El template tiene 2 cards: 1 placeholder con ``@click="alert(...)"``
    ("Crear proceso completo", aÃºn sin lÃ³gica) y 1 funcional con
    ``@click="openSyncView"`` ("Actualizar comentarios de DB", que
    navega a la sub-vista ``proc_sync``). El copy debe ser literal
    (es lo que verÃ¡ el operario).
    """
    text = _read(PROCESOS_JS)
    # 1 alert restante (solo para "Crear proceso completo" que aÃºn
    # no tiene lÃ³gica en este ticket). El segundo card ya tiene
    # openSyncView (test_procesos_card_llama_open_sync_view).
    alert_clicks = text.count('@click="alert(')
    assert alert_clicks == 1, (
        f"Esperaba 1 @click='alert(...)' (card 'Crear proceso'), "
        f"encontrÃ© {alert_clicks}"
    )
    # Copy literal de los 2 labels de las cards.
    assert "Crear proceso completo" in text, (
        "Falta el label 'Crear proceso completo' en una de las cards"
    )
    assert "Actualizar comentarios de DB" in text, (
        "Falta el label 'Actualizar comentarios de DB' en una de las cards"
    )
    # El TODO solo estÃ¡ en el card de "Crear proceso completo".
    assert "TODO: Crear proceso completo" in text, (
        "Falta el alert placeholder 'TODO: Crear proceso completo'"
    )
    # Y NO debe estar en el card de comentarios (que ya tiene lÃ³gica).
    assert "TODO: Actualizar comentarios de DB" not in text, (
        "El card 'Actualizar comentarios de DB' ya no debe ser un "
        "placeholder alert â€” debe llamar a openSyncView."
    )


def test_procesos_card_llama_open_sync_view() -> None:
    """El card 'Actualizar comentarios de DB' llama a ``openSyncView``
    (NO a ``alert``) y la funciÃ³n estÃ¡ definida en el setup del
    componente. El handler NO cambia ``store.currentView`` â€” el
    sync view se renderiza inline (no es una sub-vista separada).
    """
    text = _read(PROCESOS_JS)
    # El @click del card de comentarios llama a openSyncView.
    assert '@click="openSyncView"' in text, (
        "El card de comentarios debe usar @click='openSyncView', "
        "no alert(...)"
    )
    # La funciÃ³n openSyncView estÃ¡ definida en el setup.
    assert "function openSyncView" in text, (
        "Falta la definiciÃ³n de openSyncView() en el setup del componente"
    )
    # CRÃTICO: openSyncView NO cambia store.currentView. Renderiza
    # el sync view inline (panel hijo), no como sub-vista separada.
    # Esto evita que el operario pierda el contexto del selector
    # de proceso (regresiÃ³n reportada el 2026-09-02 por el operario).
    assert 'store.currentView = "proc_sync"' not in text, (
        "openSyncView NO debe setear store.currentView = 'proc_sync' "
        "(serÃ­a una sub-vista separada y harÃ­a perder el contexto "
        "del selector de proceso al operario)"
    )
    assert "showSyncView.value = true" in text, (
        "openSyncView debe setear showSyncView.value = true "
        "(ref local que renderiza el sync view inline)"
    )


def test_procesos_renderiza_sync_view_inline() -> None:
    """El componente Procesos.js monta ``<procesos-sync-view>`` como
    panel hijo INLINE (no como sub-vista separada). Esto preserva el
    contexto del selector de proceso cuando el operario revisa el
    diff o aplica cambios."""
    text = _read(PROCESOS_JS)
    # El componente ProcesosSyncView se monta dentro del template.
    assert "<procesos-sync-view" in text, (
        "Falta el tag <procesos-sync-view> en el template de Procesos.js"
    )
    # Se le pasa el procUid del selector (prop) y se escucha el
    # evento close para colapsar el panel.
    assert 'proc-uid="selectedProcUid"' in text, (
        "Falta el binding :proc-uid del componente inline "
        "(debe pasar el procUid seleccionado)"
    )
    assert '@close="closeSyncView"' in text, (
        "Falta el listener @close para colapsar el panel"
    )
    # El panel estÃ¡ envuelto en un v-if para que se renderice
    # condicionalmente.
    assert 'v-if="showSyncView' in text, (
        "Falta el v-if que muestra/oculta el panel inline"
    )
    # Hay un data-testid estable para tests E2E.
    assert 'data-testid="procesos-sync-inline-host"' in text, (
        "Falta el data-testid del host del panel inline"
    )
    # closeSyncView estÃ¡ definido en el setup.
    assert "function closeSyncView" in text, (
        "Falta la definiciÃ³n de closeSyncView() en el setup"
    )


def test_procesos_card_comentarios_deshabilitado_sin_plc() -> None:
    """El card 'Actualizar comentarios de DB' se deshabilita si NO hay
    cache de bloques del PLC (computed ``canOpenSync``) y muestra un
    tooltip accionable."""
    text = _read(PROCESOS_JS)
    # El computed ``canOpenSync`` estÃ¡ en el setup.
    assert "const canOpenSync = computed" in text, (
        "Falta el computed 'canOpenSync' en el setup"
    )
    # El card usa :disabled="!canOpenSync" (no :disabled="!canAct"
    # como el otro card).
    assert ':disabled="!canOpenSync"' in text, (
        "El card 'Actualizar comentarios de DB' debe deshabilitarse "
        "con :disabled='!canOpenSync'"
    )
    # El tooltip menciona la acciÃ³n manual esperada del operario.
    assert "Selecciona un PLC en el sidebar" in text, (
        "Falta el tooltip accionable sobre seleccionar un PLC en el sidebar"
    )


def test_manifest_loader_procesos_sync_sin_view_top_level() -> None:
    """``ProcesosSyncView`` se carga como loader pero NO aparece en
    el map ``views`` (es un panel inline de ``Procesos.js``, no una
    sub-vista top-level del Sidebar). El shell SPA lo necesita
    registrado para que ``<procesos-sync-view>`` funcione como
    etiqueta dentro del template de Procesos.js.

    Espejo JS y Python sincronizados.
    """
    js_text = _read(MANIFEST_JS)
    py_text = _read(MANIFEST_PY)
    # JS: el loader existe.
    assert '"ProcesosSyncView":' in js_text, (
        'Falta el loader "ProcesosSyncView" en _comps de manifest.js'
    )
    assert 'import("./components/ProcesosSyncView.js")' in js_text, (
        "Falta el import('./components/ProcesosSyncView.js') en manifest.js"
    )
    # JS: NO estÃ¡ en views (porque es inline, no top-level).
    assert '"proc_sync":' not in js_text, (
        '"proc_sync" no debe estar en views de manifest.js '
        "(ProcesosSyncView se renderiza inline, no como sub-vista)"
    )
    # Python: mismo shape. (El loader es un f-string con
    # ``_STATIC_PREFIX`` + el path del componente.)
    assert '"ProcesosSyncView":' in py_text, (
        'Falta el loader "ProcesosSyncView" en manifest.py'
    )
    assert "ProcesosSyncView.js" in py_text, (
        "Falta el path del componente ProcesosSyncView en manifest.py"
    )
    # Python: NO estÃ¡ en views.
    assert '"proc_sync":' not in py_text, (
        '"proc_sync" no debe estar en views de manifest.py'
    )


def test_api_js_exporta_procesos_sync() -> None:
    """El mÃ³dulo ``api.js`` exporta ``apiProcesosSyncPreview`` y
    ``apiProcesosSyncCommit`` que apuntan a los endpoints del
    router ``procesos_sync.py``."""
    text = _read(API_JS)
    # Export de la funciÃ³n preview.
    assert "export function apiProcesosSyncPreview" in text, (
        "Falta el export de apiProcesosSyncPreview en api.js"
    )
    # Export de la funciÃ³n commit.
    assert "export function apiProcesosSyncCommit" in text, (
        "Falta el export de apiProcesosSyncCommit en api.js"
    )
    # Las URLs correctas.
    assert "/api/v1/procesos/sync/preview" in text, (
        "apiProcesosSyncPreview debe apuntar a /api/v1/procesos/sync/preview"
    )
    assert "/api/v1/procesos/sync/commit" in text, (
        "apiProcesosSyncCommit debe apuntar a /api/v1/procesos/sync/commit"
    )


def test_procesos_has_amber_banner() -> None:
    """Aparece un banner Ã¡mbar que se muestra condicionalmente con
    ``v-if`` cuando no hay Excel o cuando el array de procesos estÃ¡
    vacÃ­o. Mismo patrÃ³n que el banner Ã¡mbar de Fase 6 (clases
    ``bg-amber-100``, ``border-amber-300``, ``text-amber-800``).
    """
    text = _read(PROCESOS_JS)
    # Clases del banner Ã¡mbar (ya en styles.css, verificado por
    # grep del bundle).
    assert "bg-amber-100" in text, (
        "Falta la clase bg-amber-100 del banner Ã¡mbar"
    )
    assert "border-amber-300" in text, (
        "Falta la clase border-amber-300 del banner Ã¡mbar"
    )
    assert "text-amber-800" in text, (
        "Falta la clase text-amber-800 del banner Ã¡mbar"
    )
    # El banner estÃ¡ protegido por ``v-if`` (cubre los 2 casos:
    # sin Excel o sin procesos).
    assert "!hasExcel || !hasProcesos" in text, (
        "Falta el v-if del banner Ã¡mbar "
        "('!hasExcel || !hasProcesos')"
    )


def test_procesos_cards_disabled_without_selection() -> None:
    """Los 2 botones tienen ``:disabled="!canAct"`` y clases
    ``disabled:opacity-50 disabled:cursor-not-allowed`` para que
    aparezcan en gris y no-clickables cuando NO hay proceso
    seleccionado.
    """
    text = _read(PROCESOS_JS)
    # El computed ``canAct`` estÃ¡ en el setup (true solo si hay
    # proceso seleccionado).
    assert "const canAct = computed" in text, (
        "Falta el computed 'canAct' en el setup"
    )
    # Los 2 botones usan ``:disabled="!canAct"`` (el docstring del
    # ``canAct`` tambiÃ©n lo menciona como referencia, por eso la
    # aserciÃ³n es ``>= 2`` y no ``== 2``).
    disabled_clicks = text.count(':disabled="!canAct"')
    assert disabled_clicks >= 2, (
        f"Esperaba al menos 2 botones con :disabled='!canAct', "
        f"encontrÃ© {disabled_clicks}"
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
    """Ambos manifests declaran la sub-vista ``proc`` â†’ ``Procesos``
    y el loader del componente ``Procesos`` (espejo JS y Python
    sincronizados).

    Si solo uno de los 2 manifests lo tiene, el shell SPA fallarÃ­a
    al cargar la vista en producciÃ³n (la SPA carga del endpoint
    ``/api/v1/areas/alimentacion/manifest`` que serializa el
    Python).
    """
    js_text = _read(MANIFEST_JS)
    py_text = _read(MANIFEST_PY)

    # JS: la key ``proc`` estÃ¡ en views y el componente en loaders.
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
    """El Sidebar tiene la 5Âª entry en ``NAV_ITEMS`` que navega a
    la vista ``proc`` con el label "Procesos" y el icono âš™ï¸. Va
    DESPUÃ‰S de la entry de ``disp`` (orden de la consigna:
    Inicio â†’ DefiniciÃ³n â†’ Cache â†’ Dispositivos â†’ Procesos).

    Tras el rediseÃ±o "Modern Corporate" (PR), el Sidebar del
    Ã¡rea es un wrapper fino sobre ``ShellSidebar`` y las
    entradas viven en ``NAV_ITEMS``. AquÃ­ validamos el
    **contrato** (la entry existe con los campos correctos y
    estÃ¡ en el orden esperado) en lugar de la implementaciÃ³n
    (calls literales ``goToSubview('proc')`` que ya no estÃ¡n
    inline en el wrapper).
    """
    text = _read(SIDEBAR_JS)
    # El wrapper mapea el evento ``navigate`` del ShellSidebar a
    # ``goToSubview`` (un Ãºnico punto de routing por Ã¡rea).
    assert '@navigate="goToSubview"' in text, (
        "El Sidebar del Ã¡rea debe enrutar @navigate â†’ goToSubview "
        "para que el ShellSidebar genÃ©rico pueda delegar el routing"
    )
    # La entry para proc estÃ¡ en NAV_ITEMS con key canÃ³nica.
    assert 'key: "proc"' in text, (
        'Falta la entry { key: "proc", ... } en NAV_ITEMS del Sidebar'
    )
    # Etiqueta humano-legible que verÃ¡ el operario.
    assert "Procesos" in text, (
        'Falta el label "Procesos" en el Sidebar'
    )
    # Icono de la nueva entrada (âš™ï¸, engranaje).
    assert "âš™ï¸" in text, (
        "Falta el icono âš™ï¸ en la entry del Sidebar"
    )
    # La entry de Procesos va DESPUÃ‰S de la de Dispositivos (orden
    # de la consigna: 5Âª entry al final).
    disp_pos = text.find('key: "disp"')
    proc_pos = text.find('key: "proc"')
    assert 0 <= disp_pos < proc_pos, (
        "La entry 'proc' debe ir DESPUÃ‰S de la entry 'disp' en NAV_ITEMS"
    )


def test_area_landing_has_procesos_option() -> None:
    """El ``AreaLanding.js`` tiene la 4Âª entry en ``SUBVIEW_OPTIONS``
    con ``key: "proc"``, icono âš™ï¸ y label "Procesos". El layout
    es la "lista vertical" (modo lista) introducida tras el demo
    de Gemini ``_source/modo_lista.html``: el contenedor exterior
    es ``flex flex-col`` con ``max-w-3xl`` y cada item es un
    botÃ³n horizontal.
    """
    text = _read(AREA_LANDING_JS)
    # La entry en SUBVIEW_OPTIONS.
    assert 'key: "proc"' in text, (
        'Falta la entry con key: "proc" en SUBVIEW_OPTIONS'
    )
    # Icono y label.
    assert "âš™ï¸" in text, (
        "Falta el icono âš™ï¸ en la nueva entry de SUBVIEW_OPTIONS"
    )
    assert "Procesos" in text, (
        'Falta el label "Procesos" en la nueva entry de SUBVIEW_OPTIONS'
    )
    # Layout "modo lista": contenedor flex-col con max-w-3xl y
    # ``data-testid="area-landing-list"`` para anclar el smoke test.
    # El grid anterior (``xl:grid-cols-4``) se eliminÃ³ porque la
    # lista vertical escala mejor en monitores anchos.
    assert "flex flex-col" in text, (
        "El contenedor de la lista debe ser flex-col (modo lista)"
    )
    assert "max-w-3xl" in text, (
        "El contenedor de la lista debe tener max-w-3xl para "
        "limitar el ancho en monitores anchos"
    )
    assert 'data-testid="area-landing-list"' in text, (
        'Falta el data-testid="area-landing-list" en el contenedor'
    )


def test_db_names_block_legacy_eliminado() -> None:
    """El sub-caption con los nombres de los 2 DBs del proceso
    (formato ``UID X Â· DBs: DB{3000+uid}_CPR_PARAM,
    DB{5000+uid}_CPR_ALM``) se ELIMINÃ“ el 2026-09-02 por
    feedback del operario: era legacy, el UID ya viene en el
    selector y los nombres de DB los computa el use case
    internamente. Este test verifica que el bloque NO se
    reintroduce por accidente.
    """
    import re

    text = _read(PROCESOS_JS)
    # Extraer solo el cuerpo del template.
    pattern = re.compile(
        r"template:\s*/\*\s*html\s*\*/\s*`(.*?)`\s*,",
        re.DOTALL,
    )
    match = pattern.search(text)
    assert match is not None, (
        "No se encontrÃ³ el template del componente Procesos.js"
    )
    template_body = match.group(1)

    # El bloque legacy NO debe estar en el template.
    assert "3000 + selectedProc.uid" not in template_body, (
        "El bloque legacy 'UID X Â· DBs: DB{3000+uid}_..._PARAM' "
        "se reintrodujo en el template. ElimÃ­nalo: el operario "
        "lo marcÃ³ como legacy el 2026-09-02."
    )
    assert "5000 + selectedProc.uid" not in template_body, (
        "El bloque legacy 'UID X Â· DBs: DB{5000+uid}_..._ALM' "
        "se reintrodujo en el template. ElimÃ­nalo: el operario "
        "lo marcÃ³ como legacy el 2026-09-02."
    )
    # Y tampoco debe aparecer el sub-caption con "DBs:" (era el
    # contenedor del bloque legacy).
    assert ">DBs:</span>" not in template_body, (
        "El contenedor 'DBs:' del bloque legacy se reintrodujo."
    )
    # Salvaguarda contra reintroducciÃ³n de las properties del DTO.
    assert "db_preal_nombre" not in template_body, (
        "Property 'db_preal_nombre' reintroducida y usada en template."
    )
    assert "db_pint_nombre" not in template_body, (
        "Property 'db_pint_nombre' reintroducida y usada en template."
    )
    assert "db_alm_nombre" not in template_body, (
        "Property 'db_alm_nombre' reintroducida y usada en template."
    )


def test_no_backticks_in_template_bodies() -> None:
    """Regression test: ningÃºn componente Vue 3 del Ã¡rea puede tener
    backticks literales (`` ` ``) dentro del cuerpo de su template
    (``template: /* html */ `...` ,``).

    Bug histÃ³rico: cuando un comentario HTML dentro del template
    contiene backticks Markdown (p.ej. `` `DataProcesoPLC` ``, `` `xl` ``,
    `` `lg` ``), el primer backtick **cierra prematuramente** el
    template literal de JavaScript. El parser JS ve HTML a medias,
    Vue intenta llamar a la cadena como funciÃ³n y falla con
    ``TypeError: "..." is not a function at <Componente>.js:N:M``.

    Este test es defensivo: parsea el cuerpo del template de cada
    componente y falla si encuentra algÃºn backtick. Los backticks
    FUERA del template (en docstrings JS, en strings normales, etc.)
    son vÃ¡lidos y no se chequean.

    Detectado en commit ``b8338bb`` (Fase 6.A â€” UI Procesos) tras
    2 rounds de fix en ``AreaLanding.js`` y ``Procesos.js``.

    Endurecido en commit ``e49b963`` (post-v3.0 dashboard layout):
    el regex original usaba ``.*?`` (non-greedy) que cerraba en
    el PRIMER backtick encontrado dentro del template, escapando
    a la deteccion de backticks literales que cierran el template
    prematuramente (causa del TypeError en runtime). Ahora se usa
    ``.*`` (greedy) con delimitador obligatorio ``\s*[,;}]`` para
    forzar al regex a encontrar el ULTIMO backtick antes de la
    coma/cierre del ``export default``. Asi, cualquier backtick
    literal dentro del template queda dentro del ``body`` capturado
    y se cuenta correctamente.
    """
    import re

    components_dir = REPO_ROOT / "areas" / "alimentacion" / "frontend" / "components"
    # Regex con DOTALL: el ``.`` matchea newlines, necesario para
    # capturar todo el template body (que es multi-linea).
    #
    # IMPORTANTE: ``.*`` GREEDY (no ``.*?`` non-greedy) + delimitador
    # obligatorio ``\s*[,;}]`` al final. Esto fuerza al regex a
    # buscar el ULTIMO backtick que sea seguido de coma, ``;`` o
    # cierre de objeto ``}`` â€” que es donde termina legitimamente
    # el template literal. Un backtick literal dentro del template
    # (e.g. `` `my-4` `` en un comentario HTML) no tiene ese delimitador
    # justo despues, asi que el regex lo SOBREPASA y termina en el
    # backtick de cierre real, dejando el backtick literal dentro
    # del body capturado (que es lo que queremos detectar).
    pattern = re.compile(
        r"template:\s*/\*\s*html\s*\*/\s*`(.*)`\s*[,;}]",
        re.DOTALL,
    )
    offenders: list[tuple[str, int]] = []
    for js_file in sorted(components_dir.glob("*.js")):
        text = js_file.read_text(encoding="utf-8")
        match = pattern.search(text)
        if not match:
            continue
        body = match.group(1)
        # Ignorar escapes ``\X`` (backslash seguido de cualquier
        # caracter) para no contar como bug los backticks ESCAPADOS
        # legitimos (`` \` `` produce un backtick literal en el output
        # sin cerrar el template). Solo los backticks NO-escapados
        # cuentan como bug.
        body_no_escapes = re.sub(r"\\.", "", body)
        unescaped_backticks = body_no_escapes.count("`")
        if unescaped_backticks > 0:
            offenders.append((js_file.name, unescaped_backticks))
    assert not offenders, (
        f"Backticks literales encontrados dentro de templates "
        f"(rompen el template literal de JS): {offenders}. "
        f"Reemplazar por comillas simples o dobles en los "
        f"comentarios HTML del template."
    )


def test_componentes_js_no_tienen_duplicados_de_setup() -> None:
    """Regression test: ningÃºn componente Vue 3 del Ã¡rea puede tener
    declaraciones duplicadas dentro de su ``setup()`` (e.g. dos
    ``const activeTab = ref(...)`` consecutivos por un edit parcial
    mal aplicado).

    SÃ­ntoma: ``SyntaxError: Identifier 'X' has already been declared``
    al cargar el componente desde el navegador. Los tests pytest
    no cogen este tipo de error porque solo leen texto, no
    parsean JS.

    Estrategia: parseamos los .js con ``node --check`` (modo
    syntax-only, sin ejecutar) y fallamos si node reporta un
    error de sintaxis. Esto es defensivo: cualquier SyntaxError
    en un .js del frontend rompe la SPA entera.
    """
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node no estÃ¡ en PATH; saltando syntax check de .js")

    components_dir = REPO_ROOT / "areas" / "alimentacion" / "frontend" / "components"
    errors: list[tuple[str, str]] = []
    for js_file in sorted(components_dir.glob("*.js")):
        result = subprocess.run(
            [node, "--check", str(js_file)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            # ``--check`` solo escribe en stderr si hay error.
            err_msg = (result.stderr or result.stdout or "").strip()
            errors.append((js_file.name, err_msg))
    assert not errors, (
        "Errores de sintaxis JS en componentes del frontend:\n"
        + "\n".join(f"  - {name}: {msg}" for name, msg in errors)
    )



