"""Tests del bus de eventos SSE y del puente con el logging."""

from __future__ import annotations

import logging
import threading
import time

import pytest

from zc_suite.eventos import (
    BusCerradoError,
    BusEventos,
    HandlerEventos,
    conectar_logging,
    desconectar_logging,
)

# ── publicacion ────────────────────────────────────────────────────────────


def test_un_evento_llega_a_el_suscriptor() -> None:
    bus = BusEventos()
    suscriptor = bus.suscribir()

    bus.publicar("log", {"nivel": "info", "mensaje": "hola"})

    evento = suscriptor.siguiente(timeout=1.0)
    assert evento == {"type": "log", "nivel": "info", "mensaje": "hola"}


def test_el_tipo_va_dentro_del_evento() -> None:
    bus = BusEventos()
    suscriptor = bus.suscribir()

    bus.publicar("tia", {"conectado": True})

    evento = suscriptor.siguiente(timeout=1.0)
    assert evento is not None
    assert evento["type"] == "tia"


def test_un_tipo_desconocido_falla() -> None:
    bus = BusEventos()
    suscriptor = bus.suscribir()

    with pytest.raises(ValueError, match="Tipo de evento desconocido"):
        bus.publicar("inventado", {})

    assert suscriptor.siguiente(timeout=0.2) is None


def test_publicar_desde_varios_hilos_no_rompe_nada() -> None:
    bus = BusEventos(max_eventos=500)
    suscriptor = bus.suscribir()

    def publicar_lineas() -> None:
        for i in range(50):
            bus.publicar("log", {"nivel": "info", "mensaje": f"linea {i}"})

    hilos = [threading.Thread(target=publicar_lineas) for _ in range(4)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(5.0)

    recibidos = 0
    while True:
        evento = suscriptor.siguiente(timeout=0.3)
        if evento is None:
            break
        recibidos += 1
    assert recibidos == 200


def test_un_cliente_lento_no_bloquea_al_publicador() -> None:
    bus = BusEventos(max_eventos=2)
    suscriptor = bus.suscribir()

    for i in range(5):
        bus.publicar("log", {"nivel": "info", "mensaje": f"linea {i}"})

    primero = suscriptor.siguiente(timeout=1.0)
    assert primero is not None
    # El mas viejo se descarto para que la cola no crezca sin limite.
    assert primero["mensaje"] == "linea 3"


def test_una_suscripcion_retirada_no_recibe_mas() -> None:
    bus = BusEventos()
    suscriptor = bus.suscribir()
    suscriptor.cerrar()

    bus.publicar("log", {"nivel": "info", "mensaje": "hola"})

    assert bus.suscriptores == 0
    with pytest.raises(BusCerradoError):
        suscriptor.siguiente(timeout=0.2)


# ── hidratacion al suscribirse ─────────────────────────────────────────────


def test_al_suscribirse_llega_el_ultimo_progress_y_el_ultimo_tia() -> None:
    bus = BusEventos()
    bus.publicar("progress", {"active": True, "current": 1, "total": 3})
    bus.publicar("tia", {"conectado": True})

    suscriptor = bus.suscribir()

    primero = suscriptor.siguiente(timeout=1.0)
    segundo = suscriptor.siguiente(timeout=1.0)
    assert primero is not None
    assert segundo is not None
    assert primero["type"] == "progress"
    assert primero["current"] == 1
    assert segundo["type"] == "tia"
    assert segundo["conectado"] is True


def test_sin_eventos_previos_la_suscripcion_empieza_vacia() -> None:
    bus = BusEventos()
    suscriptor = bus.suscribir()

    assert suscriptor.siguiente(timeout=0.2) is None


def test_el_ultimo_progress_se_actualiza_con_cada_publicacion() -> None:
    bus = BusEventos()
    bus.publicar("progress", {"current": 1})
    bus.publicar("progress", {"current": 2})

    assert bus.ultimo_progress() == {"type": "progress", "current": 2}


def test_el_ultimo_tia_se_actualiza_con_cada_publicacion() -> None:
    bus = BusEventos()
    bus.publicar("tia", {"conectado": True})
    bus.publicar("tia", {"conectado": False})

    assert bus.ultimo_tia() == {"type": "tia", "conectado": False}


# ── keep-alive y cierre ────────────────────────────────────────────────────


def test_siguiente_devuelve_none_tras_el_timeout() -> None:
    bus = BusEventos()
    suscriptor = bus.suscribir()

    inicio = time.monotonic()
    assert suscriptor.siguiente(timeout=0.2) is None
    assert time.monotonic() - inicio >= 0.15


def test_cerrar_el_bus_termina_las_suscripciones() -> None:
    bus = BusEventos()
    suscriptor = bus.suscribir()

    bus.cerrar()

    with pytest.raises(BusCerradoError):
        suscriptor.siguiente(timeout=1.0)
    assert bus.cerrado is True


def test_suscribirse_a_un_bus_cerrado_falla() -> None:
    bus = BusEventos()
    bus.cerrar()

    with pytest.raises(BusCerradoError):
        bus.suscribir()


def test_publicar_en_un_bus_cerrado_no_falla() -> None:
    bus = BusEventos()
    bus.cerrar()

    bus.publicar("log", {"nivel": "info", "mensaje": "hola"})


# ── puente con el logging ──────────────────────────────────────────────────


def test_el_handler_publica_las_lineas_de_log() -> None:
    bus = BusEventos()
    suscriptor = bus.suscribir()
    logger_prueba = logging.getLogger("zc_suite.test_eventos")
    logger_prueba.propagate = False
    logger_prueba.setLevel(logging.INFO)
    handler = conectar_logging(bus, logger_prueba)
    try:
        logger_prueba.info("mensaje de operario")
        logger_prueba.error("algo se rompio")
    finally:
        desconectar_logging(logger_prueba, handler)

    primero = suscriptor.siguiente(timeout=1.0)
    segundo = suscriptor.siguiente(timeout=1.0)
    assert primero is not None
    assert segundo is not None
    assert primero["type"] == "log"
    assert primero["nivel"] == "info"
    assert primero["mensaje"] == "mensaje de operario"
    assert segundo["nivel"] == "error"
    assert segundo["mensaje"] == "algo se rompio"


def test_el_handler_ignora_un_bus_cerrado() -> None:
    bus = BusEventos()
    bus.cerrar()
    logger_prueba = logging.getLogger("zc_suite.test_eventos_cerrado")
    logger_prueba.propagate = False
    handler = conectar_logging(bus, logger_prueba)
    try:
        logger_prueba.info("no debe romper nada")
    finally:
        desconectar_logging(logger_prueba, handler)


def test_el_handler_se_puede_enchufar_y_desenchufar() -> None:
    bus = BusEventos()
    logger_prueba = logging.getLogger("zc_suite.test_eventos_desenchufe")
    logger_prueba.propagate = False
    logger_prueba.setLevel(logging.INFO)

    handler = conectar_logging(bus, logger_prueba)
    assert handler in logger_prueba.handlers
    desconectar_logging(logger_prueba, handler)
    assert handler not in logger_prueba.handlers


def test_el_handler_tiene_el_tipo_esperado() -> None:
    assert issubclass(HandlerEventos, logging.Handler)


def test_el_bus_acepta_los_cuatro_tipos() -> None:
    bus = BusEventos()
    for tipo in ("progress", "job", "log", "tia"):
        bus.publicar(tipo, {})
    assert bus.suscriptores == 0
