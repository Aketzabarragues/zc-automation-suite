"""zc_suite.servidor — el servidor de Flask en un hilo, con parada limpia.

Porta el supervisor de la app anterior (``core/launcher/main_supervisor.py``):
Flask corre en un hilo daemon con ``werkzeug.serving.make_server``, que se
puede apagar con ``shutdown()``.

Con ``app.run()`` no se puede: ahi el menu de la bandeja no podria parar y
volver a arrancar la web. ``make_server`` deja el socket bajo control del
supervisor.
"""
from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Any

from flask import Flask
from werkzeug.serving import make_server

logger = logging.getLogger(__name__)


class ServidorWeb:
    """El servidor de Flask, con arranque y parada limpios.

    Contrato:

    - ``start()`` levanta el servidor en un hilo daemon. Idempotente.
    - ``stop()`` apaga el servidor y espera al hilo.
    - ``is_alive()`` dice si esta sirviendo.
    """

    def __init__(self, app: Flask, host: str, port: int) -> None:
        self._app = app
        self.host = host
        self.port = port
        self._lock = threading.Lock()
        self._hilo: threading.Thread | None = None
        self._servidor: Any = None
        self._vivo = threading.Event()

    def start(self) -> None:
        """Arranca el servidor en un hilo daemon. Idempotente."""
        with self._lock:
            if self._hilo is not None and self._hilo.is_alive():
                logger.debug("start() llamado pero el servidor ya estaba vivo.")
                return
            self._hilo = threading.Thread(
                target=self._servir,
                name="zc-web",
                daemon=True,
            )
            self._hilo.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Apaga el servidor y espera al hilo."""
        with self._lock:
            servidor = self._servidor
            hilo = self._hilo
        if servidor is not None:
            try:
                servidor.shutdown()
            except Exception as exc:
                logger.warning("El servidor web no se pudo apagar: %s", exc)
        if hilo is not None:
            hilo.join(timeout=timeout)
            if hilo.is_alive():
                logger.warning("El hilo web no termino en %.1fs; se abandona.", timeout)
        with self._lock:
            self._hilo = None
            self._servidor = None
        self._vivo.clear()
        logger.info("Servidor web parado.")

    def is_alive(self) -> bool:
        """``True`` si el servidor esta sirviendo."""
        return self._vivo.is_set() and self._hilo is not None and self._hilo.is_alive()

    def wait_until_alive(self, timeout_s: float = 10.0) -> bool:
        """Espera a que el servidor este bindeado.

        Returns:
            ``True`` si estaba vivo antes de que venciera la espera.
        """
        limite = time.time() + timeout_s
        while time.time() < limite:
            if self.is_alive():
                return True
            time.sleep(0.1)
        return False

    def _servir(self) -> None:
        """El hilo del servidor: bindea y sirve hasta que se apaga."""
        if not self._puerto_disponible():
            logger.error(
                "El puerto %d esta ocupado: no se levanta la web. Puede que haya "
                "otra instancia de la app funcionando.",
                self.port,
            )
            self._vivo.clear()
            return
        try:
            servidor = make_server(self.host, self.port, self._app, threaded=True)
        except Exception as exc:
            logger.error(
                "No se pudo levantar el servidor web en %s:%d: %s",
                self.host,
                self.port,
                exc,
            )
            self._vivo.clear()
            return
        with self._lock:
            self._servidor = servidor
        self._vivo.set()
        logger.info("Servidor web escuchando en http://%s:%d", self.host, self.port)
        try:
            servidor.serve_forever()
        except Exception as exc:
            logger.error("El servidor web se caido: %s", exc)
        finally:
            self._vivo.clear()
            with self._lock:
                self._servidor = None

    def _puerto_disponible(self) -> bool:
        """Si el puerto se puede tomar.

        En Windows, ``SO_REUSEADDR`` deja que dos sockets seoquen el
        mismo puerto (y no se sabe cual atiende las peticiones). Sin
        comprobarlo, una segunda instancia se quedaria con las peticiones
        de la primera.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as enchufe:
            try:
                enchufe.bind((self.host, self.port))
            except OSError:
                return False
        return True
