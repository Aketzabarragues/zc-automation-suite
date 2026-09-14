"""Smoke estructural del refactor de areas (sept-2026).

Tras los commits A-D, el shell SPA vive en
``core/web_server/static/js/`` y las areas solo aportan componentes
especificos + un manifest con la lista de views + viewLabels. Este
smoke verifica la separacion de responsabilidades SIN navegador,
parseando los endpoints HTTP del shell + el manifest del area.

Que valida:
  1. El manifest de "alimentacion" tiene la NUEVA shape:
     - ``components.viewLabels`` presente.
     - ``components.views.cache`` AUSENTE (la vista PLC es del shell).
     - ``components.sidebar`` AUSENTE (el sidebar es del shell).
     - ``loaders["AlimentacionSidebar"]`` AUSENTE (wrapper borrado).
     - ``loaders["BloquesCacheView"]`` AUSENTE (duplicado borrado).
  2. Los 3 componentes del shell estan servidos:
     - ``/js/components/plcpanelview.js`` (200 + name="plcpanelview").
     - ``/js/components/ShellSidebar.js`` (200 + sin props de area).
     - ``/js/components/ShellTopbar.js`` (200 + sin VIEW_LABELS).
  3. ``main.js`` importa los 3 componentes clave (ShellSidebar,
     ShellTopbar, plcpanelview).
  4. Los archivos borrados por el commit D ya no se sirven:
     - GET a ``/static/areas/alimentacion/frontend/components/Sidebar.js``
       debe ser 404.
     - GET a ``/static/areas/alimentacion/frontend/components/BloquesCacheView.js``
       debe ser 404.

Que NO valida (limitaciones de smoke sin navegador):
  - La reactividad real de Vue 3 al pulsar el boton PLC.
  - Que el breadcrumb cambie dinamicamente.
  Eso requiere la visual del operario con Ctrl+Shift+R.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

HOST = "127.0.0.1"
PORT = 19489  # puerto separado para no chocar con el e2e_full (19487)
BASE = f"http://{HOST}:{PORT}"


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def http_get(path: str) -> tuple[int, str]:
    """GET a un path del shell. Devuelve (status, body str)."""
    url = f"{BASE}{path}"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


def assert_in(needle: str, haystack: str, label: str) -> None:
    if needle not in haystack:
        snippet = haystack[:200].replace("\n", "\\n")
        raise AssertionError(f"[{label}] esperaba '{needle}' en el contenido")
    print(f"  - OK [{label}]: contiene '{needle[:60]}{'...' if len(needle) > 60 else ''}'")


def assert_not_in(needle: str, haystack: str, label: str) -> None:
    if needle in haystack:
        snippet = haystack[:200].replace("\n", "\\n")
        raise AssertionError(f"[{label}] NO esperaba '{needle}' en el contenido")
    print(f"  - OK [{label}]: NO contiene '{needle[:60]}{'...' if len(needle) > 60 else ''}'")


# ---------------------------------------------------------------------
# Setup: arranca el supervisor en un puerto separado
# ---------------------------------------------------------------------


def main() -> int:
    print("=" * 70)
    print("SMOKE UI NAV: refactor areas (manifest + plcpanelview + ShellSidebar)")
    print("=" * 70)

    from core.infrastructure.config.config_manager import ConfigManager
    from core.runtime.sse.sse_event_bus_sync import EventBusSync
    from core.runtime.sse.sse_publishers import wire_all
    from core.runtime.log_buffer import get_log_buffer
    from core.runtime.progress_buffer import get_progress_tracker
    from core.infrastructure.tia.tia_loop import SyncTIAClient
    from core.infrastructure.tia.tia_handlers import register_core_commands
    from core.composition.plc_engine import Engine
    from areas.alimentacion import register as register_alim
    from core.launcher.main_supervisor import MainServiceSupervisor

    cm = ConfigManager()
    tc = SyncTIAClient()
    register_core_commands(tc)
    tc.start_tia_loop()
    eng = Engine(tick_period_s=0.05)
    register_alim(eng)
    bus = EventBusSync()
    wire_all(
        log_buffer=get_log_buffer(),
        progress_tracker=get_progress_tracker(),
        tia_client=tc, engine=eng, bus=bus,
    )
    s = MainServiceSupervisor(
        host=HOST, port=PORT, tick_period_s=0.05,
        config_manager=cm, event_bus=bus,
    )
    s.start()
    if not s.wait_until_alive(timeout_s=5.0):
        print("FAIL: supervisor no arranco")
        return 1

    try:
        # -----------------------------------------------------------------
        # [1] Manifest del area "alimentacion" tiene la NUEVA shape
        # -----------------------------------------------------------------
        print("\n[1] GET /api/v1/areas/alimentacion/manifest (shape nueva)")
        status, body = http_get("/api/v1/areas/alimentacion/manifest")
        assert status == 200, f"manifest HTTP {status}, esperado 200"
        manifest = json.loads(body)
        assert manifest["id"] == "alimentacion", f"id={manifest.get('id')!r}"

        comps = manifest.get("components", {})
        views = comps.get("views", {})
        loaders = manifest.get("loaders", {})

        # Components.viewLabels: presente y con 4 keys canonicas.
        assert "viewLabels" in comps, "FALTA components.viewLabels"
        labels = comps["viewLabels"]
        for key in ("landing", "def", "disp", "proc"):
            assert key in labels, f"FALTA viewLabels['{key}']"
        print(f"  - OK viewLabels presente: {sorted(labels.keys())}")

        # Components.sidebar: AUSENTE (el sidebar es del shell).
        assert "sidebar" not in comps, (
            f"NO esperaba components.sidebar, recibido={comps.get('sidebar')!r}"
        )
        print("  - OK components.sidebar AUSENTE (sidebar es del shell)")

        # Components.views.cache: AUSENTE (la vista PLC es del shell).
        assert "cache" not in views, (
            f"NO esperaba views.cache, recibido={list(views.keys())}"
        )
        print(f"  - OK views.cache AUSENTE: views={list(views.keys())}")

        # loaders['AlimentacionSidebar']: AUSENTE (wrapper borrado).
        assert "AlimentacionSidebar" not in loaders, (
            f"NO esperaba loaders['AlimentacionSidebar'], recibido={list(loaders.keys())}"
        )
        print("  - OK loaders['AlimentacionSidebar'] AUSENTE (wrapper borrado)")

        # loaders['BloquesCacheView']: AUSENTE (duplicado borrado).
        assert "BloquesCacheView" not in loaders, (
            f"NO esperaba loaders['BloquesCacheView'], recibido={list(loaders.keys())}"
        )
        print("  - OK loaders['BloquesCacheView'] AUSENTE (duplicado borrado)")

        # loaders['plcpanelview']: AUSENTE (vive en el shell, no en el area).
        assert "plcpanelview" not in loaders, (
            f"NO esperaba loaders['plcpanelview'] en el manifest del area, "
            f"recibido={list(loaders.keys())}"
        )
        print("  - OK loaders['plcpanelview'] AUSENTE (vive en el shell)")

        # -----------------------------------------------------------------
        # [2] plcpanelview.js servido por el shell + name correcto
        # -----------------------------------------------------------------
        print("\n[2] GET /js/components/plcpanelview.js (comun, no del area)")
        status, body = http_get("/js/components/plcpanelview.js")
        assert status == 200, f"plcpanelview.js HTTP {status}, esperado 200"
        assert_in('name: "plcpanelview"', body, "plcpanelview.js")
        assert_in("loadAndApplyPlcBlocks", body, "plcpanelview.js")
        assert_in("connectTia", body, "plcpanelview.js")
        print(f"  - OK servido ({len(body)} bytes)")

        # -----------------------------------------------------------------
        # [3] ShellSidebar.js servido + sin props de area/navItems
        # -----------------------------------------------------------------
        print("\n[3] GET /js/components/ShellSidebar.js (sin props, lee del store)")
        status, body = http_get("/js/components/ShellSidebar.js")
        assert status == 200, f"ShellSidebar.js HTTP {status}, esperado 200"
        assert_in("ShellSidebar", body, "ShellSidebar.js")
        # El commit C quito los props area y navItems. Comprobamos que
        # NO estan en el componente refactorizado.
        assert_not_in("navItems: { type: Array, required: true }",
                      body, "ShellSidebar.js (post-commit C)")
        assert_not_in("area: { type: Object, required: true }",
                      body, "ShellSidebar.js (post-commit C)")
        # El componente SI tiene el boton PLC y la lectura del store.
        assert_in("navigate('plc')", body, "ShellSidebar.js")
        assert_in("areaManifest", body, "ShellSidebar.js (lee del store)")
        print(f"  - OK servido ({len(body)} bytes)")

        # -----------------------------------------------------------------
        # [4] ShellTopbar.js servido + sin VIEW_LABELS hardcoded
        # -----------------------------------------------------------------
        print("\n[4] GET /js/components/ShellTopbar.js (VIEW_LABELS eliminado)")
        status, body = http_get("/js/components/ShellTopbar.js")
        assert status == 200, f"ShellTopbar.js HTTP {status}, esperado 200"
        assert_in("ShellTopbar", body, "ShellTopbar.js")
        # El commit C quito el VIEW_LABELS hardcoded.
        assert_not_in("const VIEW_LABELS", body,
                      "ShellTopbar.js (post-commit C)")
        # El nuevo ShellTopbar lee viewLabels del manifest.
        assert_in("viewLabels", body, "ShellTopbar.js (lee del manifest)")
        # Y mantiene el label fijo "PLC" para esa key.
        assert_in('"PLC"', body, "ShellTopbar.js (label fijo para 'plc')")
        print(f"  - OK servido ({len(body)} bytes)")

        # -----------------------------------------------------------------
        # [5] main.js importa los 3 componentes clave
        # -----------------------------------------------------------------
        print("\n[5] GET /js/main.js (imports del shell)")
        status, body = http_get("/js/main.js")
        assert status == 200, f"main.js HTTP {status}, esperado 200"
        assert_in("./components/ShellSidebar.js", body, "main.js")
        assert_in("./components/ShellTopbar.js", body, "main.js")
        assert_in("./components/plcpanelview.js", body, "main.js")
        # El commit C aniadio el handler onShellNavigate y el
        # computado isPlcView. Verificamos que estan.
        assert_in("onShellNavigate", body, "main.js (handler del sidebar)")
        assert_in("isPlcView", body, "main.js (rama 'plc' del routing)")
        # Y la rama nueva del template.
        assert_in("<plcpanelview", body, "main.js (template con <plcpanelview>)")
        print(f"  - OK servido ({len(body)} bytes)")

        # -----------------------------------------------------------------
        # [6] Los archivos borrados por el commit D NO se sirven
        # -----------------------------------------------------------------
        print("\n[6] Archivos del area borrados en commit D NO se sirven")
        status, _ = http_get(
            "/static/areas/alimentacion/frontend/components/Sidebar.js"
        )
        assert status == 404, (
            f"esperado 404 para Sidebar.js borrado, recibido {status}"
        )
        print("  - OK Sidebar.js del area: 404")

        status, _ = http_get(
            "/static/areas/alimentacion/frontend/components/BloquesCacheView.js"
        )
        assert status == 404, (
            f"esperado 404 para BloquesCacheView.js borrado, recibido {status}"
        )
        print("  - OK BloquesCacheView.js del area: 404")

    finally:
        s.stop(timeout=5.0)

    print("\n" + "=" * 70)
    print("SMOKE UI NAV: PASS")
    print("=" * 70)
    print("Notas:")
    print("  - Esto valida la ESTRUCTURA del refactor (manifest shape,")
    print("    componentes servidos, imports correctos). NO prueba la")
    print("    reactividad de Vue 3 al pulsar el boton PLC.")
    print("  - Para la validacion visual de la SPA, abrir el navegador")
    print("    con Ctrl+Shift+R y pulsar el area -> boton PLC.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
