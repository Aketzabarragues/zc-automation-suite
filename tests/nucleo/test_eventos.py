"""Tests del bus de eventos SSE y del puente con el logging."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from zc_suite.eventos import (
    BusCerradoError,
    BusEventos,
    HandlerEventos,
    SerializacionError,
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


# ── hidratacion del ultimo job ────────────────────────────────────────────


def test_al_suscribirse_llega_el_ultimo_job() -> None:
    """Al recargar la pagina, la SPA sigue teniendo el resultado."""
    bus = BusEventos()
    bus.publicar("progress", {"active": False})
    bus.publicar("tia", {"conectado": True})
    bus.publicar("job", {"job": "abc", "estado": "ok", "resultado": {"cambios": 3}})

    suscriptor = bus.suscribir()

    primero = suscriptor.siguiente(timeout=1.0)
    segundo = suscriptor.siguiente(timeout=1.0)
    tercero = suscriptor.siguiente(timeout=1.0)
    assert primero is not None
    assert segundo is not None
    assert tercero is not None
    assert primero["type"] == "progress"
    assert segundo["type"] == "tia"
    assert tercero["type"] == "job"
    assert tercero["resultado"] == {"cambios": 3}


def test_el_ultimo_job_se_actualiza_con_cada_publicacion() -> None:
    bus = BusEventos()
    bus.publicar("job", {"job": "a"})
    bus.publicar("job", {"job": "b"})

    assert bus.ultimo_job() == {"type": "job", "job": "b"}


# ── politica de descarte ───────────────────────────────────────────────────


def _vaciar(suscriptor: Any) -> list[dict[str, Any]]:
    """Lee todos los eventos que quedan en la cola."""
    recibidos: list[dict[str, Any]] = []
    while True:
        evento = suscriptor.siguiente(timeout=0.3)
        if evento is None:
            return recibidos
        recibidos.append(evento)


def test_un_job_llega_aunque_el_cliente_no_consuma() -> None:
    bus = BusEventos(max_eventos=100)
    suscriptor = bus.suscribir()

    for i in range(500):
        bus.publicar("log", {"nivel": "info", "mensaje": f"linea {i}"})
    bus.publicar("job", {"job": "abc", "estado": "ok"})

    recibidos = _vaciar(suscriptor)
    assert any(evento["type"] == "job" for evento in recibidos)


def test_un_evento_tia_no_se_descarta_nunca() -> None:
    bus = BusEventos(max_eventos=10)
    suscriptor = bus.suscribir()
    bus.publicar("tia", {"conectado": True})

    for i in range(100):
        bus.publicar("log", {"nivel": "info", "mensaje": f"linea {i}"})

    recibidos = _vaciar(suscriptor)
    assert any(evento["type"] == "tia" for evento in recibidos)


def test_un_progress_nuevo_sustituye_al_anterior() -> None:
    bus = BusEventos(max_eventos=10)
    suscriptor = bus.suscribir()

    bus.publicar("progress", {"current": 1})
    bus.publicar("progress", {"current": 2})
    bus.publicar("progress", {"current": 3})

    evento = suscriptor.siguiente(timeout=1.0)
    assert evento is not None
    assert evento["type"] == "progress"
    assert evento["current"] == 3
    # Solo queda un progress en cola: los anteriores se fusionaron.
    assert _vaciar(suscriptor) == []


def test_los_logs_se_descartan_antes_que_los_progress() -> None:
    bus = BusEventos(max_eventos=10)
    suscriptor = bus.suscribir()
    bus.publicar("progress", {"current": 1})

    for i in range(50):
        bus.publicar("log", {"nivel": "info", "mensaje": f"linea {i}"})
    bus.publicar("job", {"job": "abc"})

    recibidos = _vaciar(suscriptor)
    assert any(evento["type"] == "progress" for evento in recibidos)
    assert any(evento["type"] == "job" for evento in recibidos)


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


def test_el_bus_no_publica_un_evento_no_serializable() -> None:
    """Un evento que no se puede serializar no llega a ningun suscriptor."""
    bus = BusEventos()
    suscriptor = bus.suscribir()

    with pytest.raises(SerializacionError):
        bus.publicar("job", {"job": "abc", "resultado": Path("x")})

    assert bus.ultimo_job() is None
    assert suscriptor.siguiente(timeout=0.2) is None


def test_el_bus_publica_un_resultado_serializable() -> None:
    bus = BusEventos()
    suscriptor = bus.suscribir()

    bus.publicar("job", {"job": "abc", "resultado": {"cambios": 3}})

    evento = suscriptor.siguiente(timeout=1.0)
    assert evento is not None
    assert evento["resultado"] == {"cambios": 3}


def test_el_bus_tiene_el_tipo_esperado() -> None:
    assert issubclass(HandlerEventos, logging.Handler)


# ── guard de reentrada y detalle del traceback ─────────────────────────────


def test_el_log_de_error_lleva_el_traceback_en_detalle() -> None:
    bus = BusEventos()
    suscriptor = bus.suscribir()
    logger_prueba = logging.getLogger("zc_suite.test_eventos_detalle")
    logger_prueba.propagate = False
    logger_prueba.setLevel(logging.INFO)
    handler = conectar_logging(bus, logger_prueba)
    try:
        try:
            raise ValueError("reventon")
        except ValueError:
            logger_prueba.exception("algo se rompio")
    finally:
        desconectar_logging(logger_prueba, handler)

    evento = suscriptor.siguiente(timeout=1.0)
    assert evento is not None
    assert evento["type"] == "log"
    assert evento["detalle"] is not None
    assert "ValueError" in evento["detalle"]
    assert "reventon" in evento["detalle"]


def test_un_log_sin_excepcion_tiene_detalle_none() -> None:
    bus = BusEventos()
    suscriptor = bus.suscribir()
    logger_prueba = logging.getLogger("zc_suite.test_eventos_sin_detalle")
    logger_prueba.propagate = False
    logger_prueba.setLevel(logging.INFO)
    handler = conectar_logging(bus, logger_prueba)
    try:
        logger_prueba.info("nada que ver aqui")
    finally:
        desconectar_logging(logger_prueba, handler)

    evento = suscriptor.siguiente(timeout=1.0)
    assert evento is not None
    assert evento["detalle"] is None


class BusQueRegistra(BusEventos):
    """Bus que escribe un log cada vez que se publica, para forzar reentrada."""

    def __init__(self) -> None:
        super().__init__()
        self.publicaciones = 0

    def publicar(self, tipo: str, carga: dict[str, Any]) -> None:
        self.publicaciones += 1
        if self.publicaciones > 50:
            raise RuntimeError("Recursion en el bus.")
        logging.getLogger("zc_suite.test_reentrada").warning("publicando %s", tipo)
        super().publicar(tipo, carga)


def test_el_handler_no_se_reentra() -> None:
    """Si publicar provoca un log, ese log no vuelve a publicar."""
    bus = BusQueRegistra()
    logger_prueba = logging.getLogger("zc_suite.test_reentrada")
    logger_prueba.propagate = False
    logger_prueba.setLevel(logging.WARNING)
    handler = conectar_logging(bus, logger_prueba)
    try:
        bus.publicar("log", {"nivel": "info", "mensaje": "hola"})
    finally:
        desconectar_logging(logger_prueba, handler)

    # Una publicacion exterior y la que provoca su propio log. Nada mas.
    assert bus.publicaciones == 2


def test_el_handler_ignora_los_registros_del_propio_logger() -> None:
    """El aviso de cola llena del bus no se vuelve a publicar."""
    bus = BusEventos(max_eventos=2)
    suscriptor = bus.suscribir()
    logger_padre = logging.getLogger("zc_suite")
    # El logger de la app se deja como estaba: si se queda sin propagar,
    # sus registros no llegan ni al log en fichero ni a los tests de
    # despues.
    propagate = logger_padre.propagate
    nivel = logger_padre.level
    logger_padre.propagate = False
    logger_padre.setLevel(logging.INFO)
    handler = conectar_logging(bus, logger_padre)
    try:
        for i in range(10):
            logger_padre.info("linea %d", i)
    finally:
        desconectar_logging(logger_padre, handler)
        logger_padre.propagate = propagate
        logger_padre.setLevel(nivel)

    recibidos = _vaciar(suscriptor)
    assert recibidos
    assert not any("Cola de la suscripcion" in evento["mensaje"] for evento in recibidos)


def test_el_bus_acepta_los_cuatro_tipos() -> None:
    bus = BusEventos()
    for tipo in ("progress", "job", "log", "tia"):
        bus.publicar(tipo, {})
    assert bus.suscriptores == 0
