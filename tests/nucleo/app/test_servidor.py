"""Tests del servidor web: arranque, parada y estado."""

from __future__ import annotations

import socket
from typing import Any

import pytest
from flask import Flask

from zc_suite.nucleo.app.servidor import ServidorWeb


def _puerto_libre() -> int:
    """Un puerto que esta libre ahora mismo."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def app() -> Flask:
    """Una app minima que responde."""
    aplicacion = Flask(__name__)

    @aplicacion.get("/ping")
    def ping() -> Any:
        return {"pong": True}

    return aplicacion


def test_arrancar_sirve_y_parar_lo_apaga(app: Flask) -> None:
    """Con la web viva responde; al pararla, no."""
    puerto = _puerto_libre()
    servidor = ServidorWeb(app, "127.0.0.1", puerto)

    servidor.start()
    try:
        assert servidor.wait_until_alive(timeout_s=10) is True
        assert servidor.is_alive() is True
        with app.test_client() as cliente:
            assert cliente.get("/ping").get_json() == {"pong": True}
    finally:
        servidor.stop()

    assert servidor.is_alive() is False


def test_arrancar_dos_veces_no_hace_nada(app: Flask) -> None:
    """``start()`` es idempotente: no levanta dos servidores."""
    puerto = _puerto_libre()
    servidor = ServidorWeb(app, "127.0.0.1", puerto)

    servidor.start()
    try:
        servidor.start()
        assert servidor.wait_until_alive(timeout_s=10) is True
        assert servidor.is_alive() is True
    finally:
        servidor.stop()


def test_parar_sin_arrancar_no_falla(app: Flask) -> None:
    """``stop()`` sin arrancar no rompe nada."""
    servidor = ServidorWeb(app, "127.0.0.1", _puerto_libre())

    servidor.stop()

    assert servidor.is_alive() is False


def test_un_puerto_ocupado_no_deja_el_servidor_vivo(app: Flask) -> None:
    """Si el puerto esta ocupado, el servidor no queda vivo."""
    servidor = ServidorWeb(app, "127.0.0.1", _puerto_libre())
    servidor.start()
    assert servidor.wait_until_alive(timeout_s=10) is True

    segundo = ServidorWeb(app, "127.0.0.1", servidor.port)
    segundo.start()

    assert segundo.wait_until_alive(timeout_s=2) is False
    assert segundo.is_alive() is False

    servidor.stop()
