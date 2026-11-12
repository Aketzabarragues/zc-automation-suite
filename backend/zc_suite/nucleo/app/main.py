"""zc_suite.nucleo.app.main — arranque de la aplicacion.

Punto unico de composicion: crea el hilo de TIA, el bus de eventos y la app
Flask, y monta las rutas. La lista ``AREAS`` es el unico sitio donde el
nucleo conoce las areas.

Dos modos de arranque:

- **Consola** (desarrollo): el servidor web ocupa el hilo principal y se
  para con Ctrl+C.
- **Bandeja** (empaquetado): la web levanta sola en un hilo daemon y el
  menu de la bandeja permite pararla, abrir el panel, ver el estado o
  salir. El navegador no se abre solo.
"""
from __future__ import annotations

import argparse
import logging
import platform
import sys
import webbrowser
from pathlib import Path
from typing import Any

from flask import Flask

from zc_suite.areas import alimentacion
from zc_suite.nucleo.app import logs
from zc_suite.nucleo.app.bandeja import Bandeja, desconectar_y_parar
from zc_suite.nucleo.app.config import (
    Config,
    ConfigEnUso,
    cargar_config,
    estado_config,
    resolver_config,
)
from zc_suite.nucleo.app.servidor import ServidorWeb
from zc_suite.nucleo.sesion import CLAVE_SESION, CLAVE_SESION_AREAS, Sesion
from zc_suite.nucleo.tia.eventos import BusEventos
from zc_suite.nucleo.tia.servicio import ServicioTIA
from zc_suite.nucleo.web.app import PUERTO_POR_DEFECTO, crear_app
from zc_suite.nucleo.web.rutas import catalogo as rutas_catalogo
from zc_suite.nucleo.web.rutas import conexion as rutas_conexion
from zc_suite.nucleo.web.rutas import config as rutas_config
from zc_suite.nucleo.web.rutas import plc as rutas_plc
from zc_suite.nucleo.web.rutas import sesion as rutas_sesion
from zc_suite.nucleo.web.rutas.config import CLAVE_ESTADO_CONFIG

logger = logging.getLogger(__name__)

#: Areas de la app. Se anaden aqui, una a una, y en ningun otro sitio.
AREAS: list[Any] = [alimentacion]

#: La version de la app.
VERSION = "0.1.0"


def carpeta_del_executable() -> Path:
    """La carpeta donde esta el ejecutable.

    Empaquetado: la del ``.exe``. Desarrollo: la del repo.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[4]


def carpeta_de_datos() -> Path:
    """La carpeta donde la app guarda sus datos.

    Empaquetado: junto al ejecutable. Desarrollo: el repo.
    """
    return carpeta_del_executable()


def _estado_de_tia(servicio: ServicioTIA) -> str:
    """El estado de TIA, como texto para el globo de la bandeja."""
    estado = servicio.estado()
    if estado["conectado"]:
        return f"conectado ({estado['version_tia'] or 'version desconocida'})"
    if estado["ultimo_error"]:
        return f"desconectado ({estado['ultimo_error']})"
    return "desconectado"


def log_de_arranque(
    config_en_uso: ConfigEnUso,
    catalogos: dict[str, dict[str, Any]],
) -> None:
    """Escribe en el log como esta la app.

    Args:
        config_en_uso: el ``config.json`` que se esta usando y de donde sale.
        catalogos: el catalogo de cada area.
    """
    logger.info("=" * 60)
    logger.info("ZC Automation Suite %s", VERSION)
    logger.info(
        "Python %s | empaquetado: %s",
        platform.python_version(),
        bool(getattr(sys, "frozen", False)),
    )
    logger.info("Ejecutable: %s", carpeta_del_executable())
    logger.info("Datos: %s", carpeta_de_datos())
    logger.info("Log: %s", logs.ruta_log())
    logger.info(
        "Config en uso: %s (origen: %s)",
        config_en_uso.ruta,
        config_en_uso.origen,
    )
    for id_area, catalogo in catalogos.items():
        tipos = len(catalogo.get("device_tabs") or [])
        n_max = len(catalogo.get("nmax") or [])
        logger.info(
            "Area '%s': %d tipos de dispositivo, %d N_MAX",
            id_area,
            tipos,
            n_max,
        )
        if not tipos:
            logger.warning(
                "El area '%s' no tiene tipos de dispositivo en el catalogo: la "
                "vista de dispositivos saldra vacia. Revisa el config.json en "
                "uso (%s): puede que este vacio o incompleto.",
                id_area,
                config_en_uso.ruta,
            )
        if not n_max:
            logger.warning(
                "El area '%s' no tiene N_MAX en el catalogo: las tarjetas de "
                "N_MAX saldran vacias. Revisa el config.json en uso (%s).",
                id_area,
                config_en_uso.ruta,
            )
    logger.info("=" * 60)


def montar_app(
    servicio: ServicioTIA,
    bus: BusEventos,
    desarrollo: bool = False,
    puerto: int = PUERTO_POR_DEFECTO,
    config: Config | None = None,
    config_en_uso: ConfigEnUso | None = None,
    sesion: Sesion | None = None,
) -> Flask:
    """Crea la app y monta las rutas del nucleo y de las areas.

    Args:
        servicio: el hilo de TIA.
        bus: el bus de eventos.
        desarrollo: si es ``True``, se admiten los origenes de Vite.
        puerto: puerto de escucha.
        config: configuracion validada. Por defecto se carga del
            ``config.json`` del usuario.
        config_en_uso: el ``config.json`` en uso y su origen. Por defecto se
            resuelve.
        sesion: el estado de la sesion. Por defecto se crea una vacia.

    Returns:
        La app lista para servir.
    """
    app = crear_app(servicio, bus, desarrollo=desarrollo, puerto=puerto)
    if config is None or config_en_uso is None:
        config_en_uso = resolver_config()
    config_app = config if config is not None else cargar_config(config_en_uso.ruta)
    app.config["ZC_CONFIG"] = config_app
    app.config[CLAVE_SESION] = sesion if sesion is not None else Sesion()
    ids_areas = [area.ID for area in AREAS]
    secciones = {
        area.ID: config_app.seccion_area(
            area.ID,
            area.defaults(config_app.areas.get(area.ID, {})),
        )
        for area in AREAS
    }
    estado = estado_config(config_app, config_en_uso, ids_areas)
    for area in AREAS:
        _anotar_incompatible(estado, area.valida_config(secciones[area.ID]))
    app.config[CLAVE_ESTADO_CONFIG] = estado
    if estado["incompatible"]:
        logger.error("Config incompatible: %s", estado["motivo"])
    rutas_conexion.registrar(app)
    rutas_plc.registrar(app)
    rutas_catalogo.registrar(app)
    rutas_config.registrar(app)
    rutas_sesion.registrar(app)
    catalogos: dict[str, Any] = {}
    session_areas: dict[str, Any] = {}
    for area in AREAS:
        seccion = secciones[area.ID]
        area.al_arrancar(seccion)
        catalogos[area.ID] = area.catalogo(seccion)
        session_areas[area.ID] = area.estado_sesion
        app.register_blueprint(area.rutas)
        logger.info("Area registrada: %s", area.ID)
    app.config["ZC_CATALOGO"] = catalogos
    app.config[CLAVE_SESION_AREAS] = session_areas
    log_de_arranque(config_en_uso, catalogos)
    return app


def _anotar_incompatible(estado: dict[str, Any], problema: str | None) -> None:
    """Anota en el estado del config el problema que ha encontrado un area.

    El nucleo no sabe que es valido en el config de un area: lo pregunta al
    area y anota lo que contesta.
    """
    if not problema:
        return
    estado["incompatible"] = True
    motivo = estado.get("motivo")
    estado["motivo"] = f"{motivo} {problema}" if motivo else problema


def arrancar(
    host: str = "127.0.0.1",
    puerto: int = PUERTO_POR_DEFECTO,
    desarrollo: bool = False,
    bandeja: bool = False,
    abrir_navegador: bool = False,
) -> None:
    """Arranca el hilo de TIA y el servidor web.

    Args:
        host: host de escucha.
        puerto: puerto de escucha.
        desarrollo: si es ``True``, se admiten los origenes de Vite.
        bandeja: si es ``True``, la app se abre con el icono de bandeja y
            el navegador no se abre solo.
        abrir_navegador: si es ``True``, se abre el navegador al arrancar.
    """
    bus = BusEventos()
    sesion = Sesion()
    servicio = ServicioTIA(publicador=bus.publicar)
    # Al desconectar o al perder el portal se vacia lo que dependia de TIA:
    # PLCs, seleccion, escaneos y datos de las areas (como main).
    servicio.enganchar_perdida_tia(sesion.perder_tia)
    servicio.arrancar()
    app = montar_app(servicio, bus, desarrollo=desarrollo, puerto=puerto, sesion=sesion)
    url = f"http://{host}:{puerto}"
    logger.info("ZC Automation Suite escuchando en %s", url)

    if not bandeja:
        if abrir_navegador:
            webbrowser.open(url)
        try:
            app.run(host=host, port=puerto, threaded=True)
        finally:
            servicio.parar()
            sesion.vaciar()
        return

    servidor = ServidorWeb(app, host, puerto)
    caja = Bandeja(
        url=url,
        web=servidor,
        estado_tia=lambda: _estado_de_tia(servicio),
        parar_tia=lambda: desconectar_y_parar(servicio),
    )
    try:
        caja.correr()
    finally:
        servidor.stop()
        servicio.parar()
        sesion.vaciar()


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
        help="Muestra el icono de bandeja del sistema.",
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

    # El log va primero: todo lo que pase despues queda escrito.
    logs.configurar_logging()
    logs.instalar_hooks_de_excepcion()

    # Empaquetada, la app se abre con doble click: no hay consola. Por eso
    # arranca con la bandeja, como la app anterior. En desarrollo el
    # arranque es de consola, salvo que se pida la bandeja con --bandeja.
    bandeja = argumentos.bandeja or bool(getattr(sys, "frozen", False))

    arrancar(
        host=host,
        puerto=int(puerto_texto),
        desarrollo=argumentos.desarrollo,
        bandeja=bandeja,
        abrir_navegador=argumentos.abrir,
    )


if __name__ == "__main__":
    main()
