"""Composition Root del launcher con system tray (Fase 0.5 spike).

Entry point único de la app (modo dev + frozen):

    python main_tray.py             # CON consola (debug)
    pythonw.exe main_tray.py        # SIN consola (manual)
    zc-automation-suite.exe         # PyInstaller --onefile (Fase 5)

Responsabilidades de esta capa (Fase 0.5):
  1. Configurar logging a fichero + stdout.
  2. Comprobar que ``siemens_tia_scripting`` está disponible (best-effort,
     no crashear si no lo está — los endpoints REST básicos siguen vivos).
  3. Lanzar uvicorn con la app FastAPI en un thread daemon.
  4. Lanzar ``pystray.Icon`` con un icono 16x16 placeholder.
  5. Al cerrar la bandeja (menú "Salir"), detener uvicorn limpiamente.

Lo que esta capa NO hace (Fase 0.5 — diferido a Fase 1):
  - NO instancia ``WorkerBridge``: eso es Fase 1.
  - NO carga ``siemens_tia_scripting``: solo verifica el import. La carga
    perezosa real se hace desde ``core/worker/worker_tia.py``.
  - NO monta el shutdown handler del worker persistente (lección X2): eso
    es Fase 1, con un test explícito en ``tests/core/test_worker_*.py``.

Convenciones (.clinerules §1, §2, §9):
  - Type hints en todas las firmas.
  - ``from __future__ import annotations``.
  - ``asyncio`` eficiente: uvicorn corre en su propio event loop dentro
    del thread; el main thread queda libre para pystray.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from typing import Any

import uvicorn
from PIL import Image
from pystray import Icon, Menu, MenuItem


log = logging.getLogger("zc_tray")


# ── Comprobación best-effort del SDK de Siemens ─────────────────────────
def _check_siemens_sdk() -> None:
    """Comprueba que el SDK de TIA Portal está disponible.

    Si NO está (p.ej. en una máquina sin TIA Portal instalado, o en un
    venv de CI), loggea un warning pero sigue. La app funciona en modo
    "1-shot/MCP no disponible" — los endpoints REST básicos del spike
    (``/api/v1/ping``, ``/api/v1/events``) siguen respondiendo.

    En Fase 1, esta función se sustituye por la inicialización del
    ``WorkerBridge`` (lifespan de FastAPI) con un test que cubre el
    shutdown handler (lección X2, ``.clinerules`` §2).
    """
    try:
        import siemens_tia_scripting  # noqa: F401
    except ImportError as exc:
        log.warning(
            "siemens_tia_scripting no disponible (%s). "
            "Modo 1-shot/MCP no disponible — los endpoints basicos "
            "siguen funcionando.",
            exc,
        )
        return
    log.info("siemens_tia_scripting detectado. Modo OT disponible (Fase 1+).")


# ── Uvicorn en background thread ────────────────────────────────────────
class _UvicornThread:
    """Wrapper de ``uvicorn.Server`` ejecutándose en un thread daemon.

    FastAPI/Starlette corren en su propio event loop dentro del thread.
    El main thread queda libre para ``pystray`` (pystray en Windows
    requiere el main thread, no se puede delegar a un thread secundario).

    Convenciones:
      - ``start()`` espera a ``server.started == True`` (no más de 5s)
        antes de retornar, para que el icono de bandeja pueda mostrar
        "abrir panel web" solo cuando el servidor está escuchando.
      - ``stop()`` usa ``server.should_exit = True`` (patrón oficial de
        uvicorn) y espera al thread con timeout.
    """

    _READY_TIMEOUT_S = 5.0
    _READY_POLL_S = 0.1

    def __init__(self, host: str, port: int) -> None:
        config = uvicorn.Config(
            "core.web.app:app",
            host=host,
            port=port,
            log_level="info",
            lifespan="on",
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._server.run,
            name="uvicorn-main",
            daemon=True,
        )

    def start(self) -> None:
        """Arranca uvicorn y bloquea hasta que esté ``started`` (o timeout)."""
        self._thread.start()
        waited_s = 0.0
        while waited_s < self._READY_TIMEOUT_S:
            if self._server.started:
                return
            time.sleep(self._READY_POLL_S)
            waited_s += self._READY_POLL_S
        log.warning(
            "Uvicorn no confirmo started=True en %.1fs; seguimos.",
            self._READY_TIMEOUT_S,
        )

    def stop(self, timeout: float = 5.0) -> None:
        """Solicita el cierre limpio de uvicorn y espera al thread."""
        log.info("Deteniendo uvicorn...")
        self._server.should_exit = True
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            log.warning("Uvicorn no termino en %.1fs.", timeout)
        else:
            log.info("Uvicorn detenido.")


# ── Icono placeholder ───────────────────────────────────────────────────
def _make_icon() -> Image.Image:
    """Genera un icono 16x16 placeholder (Pillow puro, sin assets).

    En Fase 5 se sustituirá por ``launcher/icon.ico`` (heredado del
    legacy). Para el spike, cualquier imagen Pillow sirve: pystray
    necesita un ``PIL.Image.Image`` o una ruta a .ico.
    """
    return Image.new("RGB", (16, 16), "blue")


# ── Menú de la bandeja ──────────────────────────────────────────────────
def _build_menu(host: str, port: int) -> Menu:
    """Construye el menú de la bandeja.

    Items:
      - "Abrir panel web": abre ``http://<host>:<port>`` en el navegador.
      - "Salir": detiene pystray (el main thread liberará la bandeja y
        el ``finally`` de ``main()`` apaga uvicorn).
    """
    def on_open(icon: Icon, item: MenuItem) -> None:
        import webbrowser

        webbrowser.open(f"http://{host}:{port}")

    def on_quit(icon: Icon, item: MenuItem) -> None:
        log.info("Salir seleccionado desde la bandeja.")
        icon.stop()

    return Menu(
        MenuItem("Abrir panel web", on_open),
        MenuItem("Salir", on_quit),
    )


# ── Entry point ─────────────────────────────────────────────────────────
def main() -> int:
    """Arranca uvicorn + bandeja; al cerrar la bandeja apaga uvicorn."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    log.info("=" * 60)
    log.info("ZC Automation Suite (Fase 0.5 spike) iniciando.")
    log.info(
        "Python: %s | frozen=%s",
        sys.version.split()[0],
        getattr(sys, "frozen", False),
    )

    _check_siemens_sdk()

    host = "127.0.0.1"
    port = 8000
    web = _UvicornThread(host=host, port=port)
    web.start()
    log.info("Web server en http://%s:%d", host, port)

    icon = Icon(
        name="zc-automation-suite",
        icon=_make_icon(),
        title="ZC Automation Suite (Fase 0.5 spike)",
        menu=_build_menu(host, port),
    )

    try:
        log.info("Bandeja activa. Menu: Abrir panel web | Salir.")
        icon.run()
    except Exception:
        log.exception("Bandeza fallo; cerrando.")
    finally:
        web.stop()

    log.info("Adios.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
