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
    ConfigError,
    cargar_config,
    escribir_config,
    estado_config,
    leer_datos,
    resolver_config,
)
from zc_suite.nucleo.app.servidor import ServidorWeb
from zc_suite.nucleo.sesion import CLAVE_SESION, CLAVE_SESION_AREAS, Sesion
from zc_suite.nucleo.tia.eventos import BusEventos
from zc_suite.nucleo.tia.servicio import ServicioTIA
from zc_suite.nucleo.tia.workdir import carpeta_datos, carpeta_del_executable
from zc_suite.nucleo.web.app import (
    CLAVE_CONFIG,
    CLAVE_CONFIG_EN_USO,
    CLAVE_RECARGA_CONFIG,
    PUERTO_POR_DEFECTO,
    crear_app,
)
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


def _estado_de_tia(servicio: ServicioTIA) -> str:
    """El estado de TIA, como texto para el globo de la bandeja."""
    estado = servicio.estado()
    if estado["conectado"]:
        return f"conectado ({estado['version_tia'] or 'version desconocida'})"
    if estado["ultimo_error"]:
        return f"desconectado ({estado['ultimo_error']})"
    return "desconectado"


def log_de_arranque(config_en_uso: ConfigEnUso, ids_areas: list[str]) -> None:
    """Escribe en el log como esta la app.

    El detalle del catalogo de cada area (tipos, N_MAX y sus avisos) lo
    emite el propio area en su ``catalogo``: el nucleo no conoce esas claves.

    Args:
        config_en_uso: el ``config.json`` que se esta usando y de donde sale.
        ids_areas: los identificadores de las areas registradas.
    """
    logger.info("=" * 60)
    logger.info("ZC Automation Suite %s", VERSION)
    logger.info(
        "Python %s | empaquetado: %s",
        platform.python_version(),
        bool(getattr(sys, "frozen", False)),
    )
    logger.info("Ejecutable: %s", carpeta_del_executable())
    logger.info("Datos: %s", carpeta_datos())
    logger.info("Log: %s", logs.ruta_log())
    logger.info(
        "Config en uso: %s (origen: %s)",
        config_en_uso.ruta,
        config_en_uso.origen,
    )
    for id_area in ids_areas:
        logger.info("Area registrada: %s", id_area)
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
    if config_en_uso is None:
        config_en_uso = resolver_config()
    config_app = config if config is not None else cargar_config(config_en_uso.ruta)
    ids_areas = [area.ID for area in AREAS]
    secciones = _secciones_de(config_app)
    catalogos: dict[str, Any] = {}
    session_areas: dict[str, Any] = {}
    _montar_areas(app, secciones, catalogos, session_areas, config_en_uso)
    app.config[CLAVE_CONFIG] = config_app
    app.config[CLAVE_CONFIG_EN_USO] = config_en_uso
    app.config[CLAVE_RECARGA_CONFIG] = lambda id_area, clave_area, valor: recargar_config_app(
        app, id_area, clave_area, valor
    )
    app.config[CLAVE_ESTADO_CONFIG] = _estado_completo(
        config_app, config_en_uso, secciones, ids_areas
    )
    if app.config[CLAVE_ESTADO_CONFIG]["incompatible"]:
        logger.error(
            "Config incompatible: %s", app.config[CLAVE_ESTADO_CONFIG]["motivo"]
        )
    app.config[CLAVE_SESION] = sesion if sesion is not None else Sesion()
    rutas_conexion.registrar(app)
    rutas_plc.registrar(app)
    rutas_catalogo.registrar(app)
    rutas_config.registrar(app)
    rutas_sesion.registrar(app)
    log_de_arranque(config_en_uso, ids_areas)
    return app


def _secciones_de(config: Config) -> dict[str, dict[str, Any]]:
    """La seccion final de cada area: defaults del area + config del usuario."""
    return {
        area.ID: config.seccion_area(
            area.ID,
            area.defaults(config.areas.get(area.ID, {})),
        )
        for area in AREAS
    }


def _estado_completo(
    config: Config,
    config_en_uso: ConfigEnUso,
    secciones: dict[str, dict[str, Any]],
    ids_areas: list[str],
) -> dict[str, Any]:
    """El estado del config con los problemas que anota cada area."""
    estado = estado_config(config, config_en_uso, ids_areas)
    for area in AREAS:
        _anotar_incompatible(estado, area.valida_config(secciones[area.ID]))
    return estado


def _montar_areas(
    app: Flask,
    secciones: dict[str, dict[str, Any]],
    catalogos: dict[str, Any],
    session_areas: dict[str, Any],
    config_en_uso: ConfigEnUso,
) -> None:
    """Arranca las areas, refresca sus catalogos y registra sus rutas.

    Solo lo llama ``montar_app`` al arrancar: las rutas de un area no
    cambian con el config, asi que la recarga no las repite (Flask no
    permite registrar dos veces la misma blueprint).
    """
    for area in AREAS:
        seccion = secciones[area.ID]
        area.al_arrancar(seccion)
        catalogos[area.ID] = area.catalogo(seccion, config_en_uso.ruta)
        session_areas[area.ID] = area.estado_sesion
        app.register_blueprint(area.rutas)
        logger.info("Area registrada: %s", area.ID)
    app.config["ZC_CATALOGO"] = catalogos
    app.config[CLAVE_SESION_AREAS] = session_areas


def _refrescar_areas(
    secciones: dict[str, dict[str, Any]],
    catalogos: dict[str, Any],
    session_areas: dict[str, Any],
    config_en_uso: ConfigEnUso,
) -> None:
    """Refresca las areas sin tocar las rutas ni la sesion.

    ``al_recargar_config`` deja el modelo nuevo en el area sin vaciar lo que
    el operario ya cargo (el Excel) y ``catalogo`` solo lee la seccion.
    """
    for area in AREAS:
        seccion = secciones[area.ID]
        area.al_recargar_config(seccion)
        catalogos[area.ID] = area.catalogo(seccion, config_en_uso.ruta)
        session_areas[area.ID] = area.estado_sesion
        logger.info("Area refrescada: %s", area.ID)


def recargar_config_app(
    app: Flask,
    id_area: str,
    clave_area: str,
    valor: str,
) -> Path:
    """Guarda un ajuste del area en el ``config.json`` del usuario y lo recarga.

    Cadena completa: se leen los datos crudos del ``config.json`` en uso,
    se cambia ``areas.<id_area>.<clave_area>``, se escribe de forma atomica
    (``.tmp`` + rename) y se recarga el config en memoria: ``ZC_CONFIG``,
    la seccion del area en el almacen (via ``al_recargar_config``, que no
    vacia la sesion), el estado del
    config y el catalogo. Sin reiniciar la app.

    Args:
        app: la app en curso (las dependencias vienen de ``app.config``).
        id_area: el area cuyo ajuste se cambia.
        clave_area: la clave de la seccion del area (p. ej.
            ``"plantillas_procesos"``).
        valor: el nuevo valor (la cadena vacia es un valor valido).

    Returns:
        La ruta del ``config.json`` escrito.

    Raises:
        ConfigError: si el config no se puede leer, no tiene la seccion del
            area (config de otra version, que no se toca) o no se puede
            escribir. Si el config recargado no valida, la app se restaura
            al estado anterior y el error sigue subiendo.
    """
    config_en_uso: ConfigEnUso | None = app.config.get(CLAVE_CONFIG_EN_USO)
    if config_en_uso is None:
        raise ConfigError("No se registro el config.json en uso en la app.")
    ruta = config_en_uso.ruta
    datos = leer_datos(ruta)
    seccion_area = datos.get("areas", {}).get(id_area)
    if not isinstance(seccion_area, dict):
        raise ConfigError(
            f"El config.json en uso no tiene la seccion del area '{id_area}': "
            "es de otra version de la app y no se toca."
        )
    seccion_area[clave_area] = valor
    escribir_config(ruta, datos)
    config_recargado = cargar_config(ruta)
    ids_areas = [area.ID for area in AREAS]
    secciones = _secciones_de(config_recargado)
    anterior = (
        app.config.get(CLAVE_CONFIG),
        app.config.get(CLAVE_ESTADO_CONFIG),
    )
    try:
        app.config[CLAVE_CONFIG] = config_recargado
        _refrescar_areas(
            secciones,
            app.config["ZC_CATALOGO"],
            app.config[CLAVE_SESION_AREAS],
            config_en_uso,
        )
        app.config[CLAVE_ESTADO_CONFIG] = _estado_completo(
            config_recargado, config_en_uso, secciones, ids_areas
        )
    except Exception:
        # La seccion recargada no valida (el area la rechazaria): se restaura
        # el estado anterior para no dejar la app a medio recargar.
        logger.exception("No se pudo recargar el config: se restaura el estado.")
        config_anterior = anterior[0] or Config()
        app.config[CLAVE_CONFIG] = config_anterior
        app.config[CLAVE_ESTADO_CONFIG] = anterior[1]
        _refrescar_areas(
            _secciones_de(config_anterior),
            app.config["ZC_CATALOGO"],
            app.config[CLAVE_SESION_AREAS],
            config_en_uso,
        )
        raise
    return ruta


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
