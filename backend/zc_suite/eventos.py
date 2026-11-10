"""zc_suite.eventos — bus de eventos SSE y puente con el logging.

El bus es el unico canal del backend hacia la SPA. Hay cuatro tipos de
evento y ni uno mas:

- ``progress``  cambia el avance de un trabajo.
- ``job``       termina un trabajo.
- ``log``       linea de log.
- ``tia``       cambia la conexion con TIA Portal.

Publicar es thread-safe y nunca bloquea a quien publica: el hilo de TIA
publica desde su propio hilo. Si un cliente va lento, se le descarta el
evento mas viejo de su cola en vez de frenarlo.

Al suscribirse, un cliente recibe de inmediato el ultimo ``progress`` y el
ultimo ``tia``, para que la SPA se hidrate sin tener que pedir nada.
"""
from __future__ import annotations

import contextlib
import logging
import queue
import threading
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger(__name__)

#: Tipos de evento que el bus admite.
TIPOS = ("progress", "job", "log", "tia")


class BusCerradoError(Exception):
    """El bus se ha cerrado y ya no admite suscripciones."""


class _Cierre:
    """Marca de fin de la cola de una suscripcion."""


class Suscripcion:
    """Suscripcion a los eventos del bus.

    La entrega es una cola propia: cada suscriptor ve los eventos desde el
    momento en que se suscribe, y nunca bloquea al que publica.
    """

    def __init__(self, bus: BusEventos, id_suscripcion: int, max_eventos: int) -> None:
        self.id = id_suscripcion
        self._bus = bus
        self._cola: queue.Queue[Any] = queue.Queue(maxsize=max_eventos)
        self._max_eventos = max_eventos
        self._cerrada = False

    def siguiente(self, timeout: float = 15.0) -> dict[str, Any] | None:
        """Espera el siguiente evento.

        Args:
            timeout: segundos maximos de espera.

        Returns:
            El evento, o ``None`` si solo vencio el timeout (keep-alive: el
            servidor SSE debe comentar la linea para mantener viva la
            conexion).

        Raises:
            BusCerradoError: si el bus se ha cerrado.
        """
        if self._cerrada:
            raise BusCerradoError("El bus de eventos esta cerrado.")
        try:
            evento = self._cola.get(timeout=timeout)
        except queue.Empty:
            return None
        if isinstance(evento, _Cierre):
            raise BusCerradoError("El bus de eventos esta cerrado.")
        return evento

    def cerrar(self) -> None:
        """Cierra la suscripcion y la retira del bus."""
        self._cerrada = True
        self._bus.retirar(self)

    def _encolar(self, evento: dict[str, Any]) -> None:
        """Mete el evento en la cola, descartando el mas viejo si esta llena."""
        try:
            self._cola.put_nowait(evento)
        except queue.Full:
            try:
                self._cola.get_nowait()
                self._cola.put_nowait(evento)
            except (queue.Empty, queue.Full):
                logger.warning("Cola de la suscripcion %s llena; evento descartado.", self.id)


class BusEventos:
    """Bus de eventos de la SPA.

    Publica los cuatro tipos de evento y lleva el ultimo ``progress`` y el
    ultimo ``tia`` para hidratar a los clientes que se conectan despues.
    """

    def __init__(self, max_eventos: int = 100) -> None:
        """Crea el bus.

        Args:
            max_eventos: eventos en cola por suscriptor. Al superarlos se
                descarta el mas viejo.
        """
        self._lock = threading.Lock()
        self._max_eventos = max_eventos
        self._siguiente_id = 0
        self._suscriptores: dict[int, Suscripcion] = {}
        self._ultimo_progress: dict[str, Any] | None = None
        self._ultimo_tia: dict[str, Any] | None = None
        self._cerrado = False

    # ── publicacion ──────────────────────────────────────────────────────

    def publicar(self, tipo: str, carga: dict[str, Any]) -> None:
        """Publica un evento a todos los suscriptores.

        Args:
            tipo: ``progress``, ``job``, ``log`` o ``tia``.
            carga: cuerpo del evento. Se copia el dict ``type`` al evento.

        Raises:
            ValueError: si ``tipo`` no es uno de los cuatro admitidos.
        """
        if tipo not in TIPOS:
            raise ValueError(f"Tipo de evento desconocido: {tipo!r}. Admite: {TIPOS}.")
        evento = {"type": tipo, **carga}
        with self._lock:
            if self._cerrado:
                return
            if tipo == "progress":
                self._ultimo_progress = evento
            elif tipo == "tia":
                self._ultimo_tia = evento
            suscriptores = list(self._suscriptores.values())
        for suscriptor in suscriptores:
            suscriptor._encolar(evento)

    # ── suscripcion ──────────────────────────────────────────────────────

    def suscribir(self) -> Suscripcion:
        """Crea una suscripcion.

        La suscripcion recibe de inmediato el ultimo ``progress`` y el ultimo
        ``tia`` conocidos, si los hay.

        Raises:
            BusCerradoError: si el bus ya esta cerrado.
        """
        with self._lock:
            if self._cerrado:
                raise BusCerradoError("El bus de eventos esta cerrado.")
            self._siguiente_id += 1
            suscriptor = Suscripcion(self, self._siguiente_id, self._max_eventos)
            self._suscriptores[suscriptor.id] = suscriptor
            if self._ultimo_progress is not None:
                suscriptor._encolar(self._ultimo_progress)
            if self._ultimo_tia is not None:
                suscriptor._encolar(self._ultimo_tia)
            return suscriptor

    def retirar(self, suscriptor: Suscripcion) -> None:
        """Retira una suscripcion del bus."""
        with self._lock:
            self._suscriptores.pop(suscriptor.id, None)

    # ── cierre ───────────────────────────────────────────────────────────

    def cerrar(self) -> None:
        """Cierra el bus y termina las suscripciones abiertas."""
        with self._lock:
            if self._cerrado:
                return
            self._cerrado = True
            suscriptores = list(self._suscriptores.values())
            self._suscriptores.clear()
        for suscriptor in suscriptores:
            suscriptor._cerrada = True
            with contextlib.suppress(queue.Full):
                suscriptor._cola.put_nowait(_Cierre())

    @property
    def cerrado(self) -> bool:
        """``True`` si el bus esta cerrado."""
        with self._lock:
            return self._cerrado

    @property
    def suscriptores(self) -> int:
        """Numero de suscripciones abiertas."""
        with self._lock:
            return len(self._suscriptores)

    # ── estado para la SPA ───────────────────────────────────────────────

    def ultimo_progress(self) -> dict[str, Any] | None:
        """Ultimo evento ``progress`` publicado, o ``None``."""
        with self._lock:
            return self._ultimo_progress

    def ultimo_tia(self) -> dict[str, Any] | None:
        """Ultimo evento ``tia`` publicado, o ``None``."""
        with self._lock:
            return self._ultimo_tia


# ── puente con el logging ─────────────────────────────────────────────────


class HandlerEventos(logging.Handler):
    """Handler de logging que publica cada linea en el bus.

    El nivel viaja como ``nivel`` y el texto como ``mensaje``, que es la
    forma del evento ``log``.
    """

    def __init__(self, bus: BusEventos) -> None:
        super().__init__()
        self._bus = bus

    def emit(self, record: logging.LogRecord) -> None:
        """Publica el registro como evento ``log``."""
        try:
            mensaje = record.getMessage()
        except Exception:
            mensaje = str(record.msg)
        try:
            self._bus.publicar(
                "log",
                {"nivel": record.levelname.lower(), "mensaje": mensaje},
            )
        except Exception:
            self.handleError(record)


def conectar_logging(bus: BusEventos, logger_objetivo: logging.Logger) -> HandlerEventos:
    """Conecta un logger al bus de eventos.

    Args:
        bus: bus donde se publican las lineas.
        logger_objetivo: logger al que se engancha el handler.

    Returns:
        El handler instalado, para poder desenchufarlo.
    """
    handler = HandlerEventos(bus)
    logger_objetivo.addHandler(handler)
    return handler


def desconectar_logging(logger_objetivo: logging.Logger, handler: logging.Handler) -> None:
    """Desenchufa un handler de logging del bus."""
    logger_objetivo.removeHandler(handler)


def eventos_de(bus: BusEventos) -> Iterator[dict[str, Any]]:
    """Itera los eventos de una suscripcion, terminada por el cierre del bus.

    Pensado para tests y para depurar: el stream SSE real vive en
    ``zc_suite.web``.
    """
    suscriptor = bus.suscribir()
    try:
        while True:
            evento = suscriptor.siguiente(timeout=5.0)
            if evento is not None:
                yield evento
    except BusCerradoError:
        return
    finally:
        suscriptor.cerrar()
