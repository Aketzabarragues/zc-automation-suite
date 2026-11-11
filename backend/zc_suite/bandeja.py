"""zc_suite.bandeja — el icono de bandeja y su menu.

Porta ``core/launcher/tray_app.py`` de la app anterior.

Menu (click derecho):

- **Iniciar/Parar web**: alterna segun el estado de la web.
- **Abrir panel web**: abre el navegador. Es la opcion por defecto (doble
  clic). Solo esta activa si la web esta viva.
- **Estado**: Globo con el estado de la web y de TIA.
- **Salir**: para la web y el hilo de TIA (desconecta limpio) y hace
  ``icon.stop()``: el proceso termina.

El navegador **no** se abre solo: al abrir el ``.exe`` arranca la web y el
operario abre el panel cuando quiere.

Ojo con las acciones de pystray: se llaman como ``accion(icono, item)``.
Por eso "Salir" no puede ser directamente ``servicio.parar`` (que no
acepta argumentos): fallaria en silencio y el icono nunca se detendria.
"""
from __future__ import annotations

import contextlib
import logging
import time
import webbrowser
from collections.abc import Callable
from typing import Any

from zc_suite.icono import imagen_del_icono

logger = logging.getLogger(__name__)

#: El nombre que se ve en la bandeja.
NOMBRE_APP = "ZC Automation Suite"

#: Segundos que se espera a que la web bindee al arrancar.
ESPERA_WEB = 10.0

#: Segundos que se espera a que la web se apague.
ESPERA_PARADA = 5.0


class Bandeja:
    """El icono de bandeja y su menu.

    Las acciones se guardan como metodos para poder probarlas sin
    pystray: se les pasa un icono falso.
    """

    def __init__(
        self,
        *,
        url: str,
        web: Any,
        estado_tia: Callable[[], str],
        parar_tia: Callable[[], None],
    ) -> None:
        """Crea la bandeja.

        Args:
            url: la URL de la SPA.
            web: el servidor web, con ``start()``, ``stop()`` e
                ``is_alive()``.
            estado_tia: devuelve el estado de TIA como texto.
            parar_tia: para el hilo de TIA (desconecta limpio).
        """
        self.url = url
        self.web = web
        self.estado_tia = estado_tia
        self.parar_tia = parar_tia
        self.icono: Any = None

    # ── acciones ──────────────────────────────────────────────────────────

    def al_alternar_web(self, _icono: Any, _item: Any) -> None:
        """Inicia o para la web."""
        if self.web.is_alive():
            logger.info("Menu -> Parar web")
            self.web.stop(timeout=ESPERA_PARADA)
        else:
            logger.info("Menu -> Iniciar web")
            self._arrancar_web()
        self._refrescar_menu()

    def al_abrir_web(self, _icono: Any, _item: Any) -> None:
        """Abre el panel web en el navegador."""
        if not self.web.is_alive():
            logger.warning("Menu -> Abrir panel web: la web no esta corriendo.")
            return
        logger.info("Menu -> Abrir panel web (%s)", self.url)
        webbrowser.open(self.url)

    def al_estado(self, icono: Any, _item: Any) -> None:
        """Notifica el estado de la web y de TIA."""
        texto = self.texto_del_estado()
        logger.info("Menu -> Estado:\n%s", texto)
        try:
            icono.notify(NOMBRE_APP, texto)
        except Exception as exc:
            logger.warning("El globo de estado no se pudo mostrar: %s", exc)

    def al_salir(self, icono: Any, _item: Any) -> None:
        """Para todo y cierra el icono.

        Un fallo al parar **no** impide cerrar: el proceso tiene que
        terminar, que es lo que el operario quiere.
        """
        logger.info("Menu -> Salir solicitado por el operario.")
        try:
            self._parar_todo()
        except Exception as exc:
            logger.error("No se pudo parar todo cleanly; se continua con stop: %s", exc)
        icono.stop()

    # ── ayudantes ─────────────────────────────────────────────────────────

    def texto_del_estado(self) -> str:
        """El texto del globo de estado."""
        web = "OK" if self.web.is_alive() else "DOWN"
        return (
            f"Web: {web}\n"
            f"  {self.url}\n"
            f"TIA: {self.estado_tia()}\n"
        )

    def _arrancar_web(self) -> None:
        """Arranca la web y espera a que bindee."""
        self.web.start()
        if not self.web.wait_until_alive(timeout_s=ESPERA_WEB):
            logger.error("La web no bindeo el puerto en %.0fs.", ESPERA_WEB)

    def _parar_todo(self) -> None:
        """Para la web y el hilo de TIA."""
        try:
            self.web.stop(timeout=ESPERA_PARADA)
        except Exception as exc:
            logger.error("No se pudo parar la web: %s", exc)
        try:
            self.parar_tia()
        except Exception as exc:
            logger.error("No se pudo parar el hilo de TIA: %s", exc)

    def _refrescar_menu(self) -> None:
        """Re-dibuja el menu, para que el texto de Iniciar/Parar sea el nuevo."""
        if self.icono is None:
            return
        with contextlib.suppress(Exception):
            self.icono.update_menu()

    def texto_del_menu_web(self) -> str:
        """El texto del primer item: "Iniciar web" o "Parar web"."""
        return "Parar web" if self.web.is_alive() else "Iniciar web"

    def web_abierta(self) -> bool:
        """``True`` si la web esta viva: habilita "Abrir panel web"."""
        return self.web.is_alive()

    # ── el menu ───────────────────────────────────────────────────────────

    def correr(self) -> None:
        """Muestra el icono y bloquea hasta que el operario elige "Salir"."""
        from pystray import Icon, Menu, MenuItem

        menu = Menu(
            MenuItem(lambda _item: self.texto_del_menu_web(), self.al_alternar_web),
            Menu.SEPARATOR,
            MenuItem(
                "Abrir panel web",
                self.al_abrir_web,
                enabled=lambda _item: self.web_abierta(),
                default=True,
            ),
            MenuItem("Estado", self.al_estado),
            Menu.SEPARATOR,
            MenuItem("Salir", self.al_salir),
        )

        icono = Icon(
            name="zc_automation_suite",
            icon=imagen_del_icono(),
            title=NOMBRE_APP,
            menu=menu,
        )
        self.icono = icono
        # Auto-arranque: al abrir el .exe la web levanta sola. El
        # navegador NO se abre: el operario usa "Abrir panel web".
        self._arrancar_web()
        logger.info("Icono de bandeja mostrado. Click derecho -> menu.")
        icono.run()
        logger.info("Bucle del icono de bandeja terminado.")


def desconectar_y_parar(servicio: Any, timeout: float = ESPERA_PARADA) -> None:
    """Desconecta del portal de TIA y para el hilo.

    La desconexion va como trabajo: el portal es un objeto COM y solo el
    hilo de TIA lo puede cerrar.

    Args:
        servicio: el ``ServicioTIA``.
        timeout: segundos que se espera a que se desconecte.
    """
    from zc_suite import tia

    try:
        servicio.lanzar(tia.desconectar)
    except Exception as exc:
        logger.warning("No se pudo encolar la desconexion de TIA: %s", exc)
    limite = time.time() + timeout
    while time.time() < limite:
        if not servicio.estado()["conectado"]:
            break
        time.sleep(0.1)
    servicio.parar()
    logger.info("Hilo de TIA parado.")
