"""zc_suite.main — arranque de la aplicacion.

Punto unico de composicion: crea el hilo de TIA, el bus de eventos y la app
Flask, y monta las rutas. La lista ``AREAS`` es el unico sitio donde el
nucleo conoce las areas.
"""
from __future__ import annotations

import argparse
import logging
import threading
import webbrowser
from typing import Any

from flask import Flask

from zc_suite.eventos import BusEventos
from zc_suite.rutas import conexion as rutas_conexion
from zc_suite.tia import ServicioTIA
from zc_suite.web import PUERTO_POR_DEFECTO, crear_app

logger = logging.getLogger(__name__)

#: Areas de la app. Se anaden aqui, una a una, y en ningun otro sitio.
AREAS: list[Any] = []


def configurar_logging(nivel: int = logging.INFO) -> None:
    """Prepara el logging de la app.

    El root se queda en DEBUG para el fichero, pero por consola solo sale a
    partir de INFO: los loggers de Werkzeug son ruidosos.
    """
    logging.basicConfig(
        level=nivel,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


def montar_app(
    servicio: ServicioTIA,
    bus: BusEventos,
    desarrollo: bool = False,
    puerto: int = PUERTO_POR_DEFECTO,
) -> Flask:
    """Crea la app y monta las rutas del nucleo y de las areas.

    Args:
        servicio: el hilo de TIA.
        bus: el bus de eventos.
        desarrollo: si es ``True``, se admiten los origenes de Vite.
        puerto: puerto de escucha.

    Returns:
        La app lista para servir.
    """
    app = crear_app(servicio, bus, desarrollo=desarrollo, puerto=puerto)
    rutas_conexion.registrar(app)
    for area in AREAS:
        app.register_blueprint(area.rutas)
        logger.info("Area registrada: %s", area.ID)
    return app


def _icono_bandeja() -> Any:
    """Icono de la bandeja: un circulo azul marino."""
    from PIL import Image, ImageDraw

    imagen = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    dibujo = ImageDraw.Draw(imagen)
    dibujo.ellipse((6, 6, 58, 58), fill=(0, 52, 102, 255))
    return imagen


def _bandeja(url: str, al_salir: Any) -> None:
    """Bandeja del sistema con 'Abrir' y 'Salir'."""
    import pystray

    menu = pystray.Menu(
        pystray.MenuItem("Abrir", lambda: webbrowser.open(url)),
        pystray.MenuItem("Salir", al_salir),
    )
    pystray.Icon("zc", _icono_bandeja(), "ZC Automation Suite", menu).run()


def arrancar(
    host: str = "127.0.0.1",
    puerto: int = PUERTO_POR_DEFECTO,
    desarrollo: bool = False,
    bandeja: bool = False,
    abrir_navegador: bool = False,
) -> None:
    """Arranca el hilo de TIA y el servidor web.

    Args:
        host: direccion de escucha.
        puerto: puerto de escucha.
        desarrollo: si es ``True``, se admiten los origenes de Vite.
        bandeja: si es ``True``, aparece el icono en la bandeja del sistema.
        abrir_navegador: si es ``True``, abre el navegador al arrancar.
    """
    bus = BusEventos()
    servicio = ServicioTIA(publicador=bus.publicar)
    servicio.arrancar()
    app = montar_app(servicio, bus, desarrollo=desarrollo, puerto=puerto)
    url = f"http://{host}:{puerto}"
    logger.info("ZC Automation Suite escuchando en %s", url)

    if not bandeja:
        if abrir_navegador:
            webbrowser.open(url)
        app.run(host=host, port=puerto, threaded=True)
        return

    servidor = threading.Thread(
        target=lambda: app.run(host=host, port=puerto, threaded=True),
        name="zc-web",
        daemon=True,
    )
    servidor.start()
    if abrir_navegador:
        webbrowser.open(url)
    try:
        _bandeja(url, servicio.parar)
    except KeyboardInterrupt:
        pass
    finally:
        servicio.parar()


def main() -> None:
    """Punto de entrada de la linea de ordenes."""
    parser = argparse.ArgumentParser(description="ZC Automation Suite")
    parser.add_argument(
        "--web",
        metavar="HOST:PUERTO",
        default=f"127.0.0.1:{PUERTO_POR_DEFECTO}",
        help="Direccion de escucha del servidor web.",
    )
    parser.add_argument(
        "--desarrollo",
        action="store_true",
        help="Admite los origenes del servidor de Vite.",
    )
    parser.add_argument(
        "--bandeja",
        action="store_true",
        help="Muestra el icono en la bandeja del sistema.",
    )
    parser.add_argument(
        "--abrir",
        action="store_true",
        help="Abre el navegador al arrancar.",
    )
    argumentos = parser.parse_args()

    host, _, puerto_texto = argumentos.web.rpartition(":")
    if not host or not puerto_texto.isdigit():
        parser.error(f"--web debe ser HOST:PUERTO, no '{argumentos.web}'")

    configurar_logging()
    arrancar(
        host=host,
        puerto=int(puerto_texto),
        desarrollo=argumentos.desarrollo,
        bandeja=argumentos.bandeja,
        abrir_navegador=argumentos.abrir,
    )


if __name__ == "__main__":
    main()
