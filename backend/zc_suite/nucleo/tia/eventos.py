"""zc_suite.nucleo.tia.eventos — bus de eventos SSE y puente con el logging.

El bus es el unico canal del backend hacia la SPA. Hay cuatro tipos de
evento y ni uno mas:

- ``progress``  cambia el avance de un trabajo.
- ``job``       termina un trabajo.
- ``log``       linea de log.
- ``tia``       cambia la conexion con TIA Portal.

Publicar es thread-safe y nunca bloquea a quien publica: el hilo de TIA
publica desde su propio hilo. La cola de cada suscriptor tiene un tope; al
superarlo se descarta lo menos importante, nunca un ``job`` ni un ``tia``:

- Un ``progress`` nuevo sustituye al ``progress`` que ya estaba en cola: la
  SPA solo necesita el estado mas reciente.
- Para hacer sitio se expulsa primero un ``log``, y despues un ``progress``.

Al suscribirse, un cliente recibe de inmediato el ultimo ``progress``, el
ultimo ``tia`` y el ultimo ``job``, para que la SPA se hidrate sin tener que
pedir nada.
"""
from __future__ import annotations

import json
import logging
import threading
import traceback
from collections import deque
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger(__name__)

#: Tipos de evento que el bus admite.
TIPOS = ("progress", "job", "log", "tia")

#: Nombre del logger de este modulo. Sus registros no se publican como
#: eventos: el bus avisa cuando una cola se llena y se reventaria.
NOMBRE_LOGGER = __name__


class BusCerradoError(Exception):
    """El bus se ha cerrado y ya no admite suscripciones."""


class SerializacionError(Exception):
    """Un evento no se puede serializar a JSON y no se publica."""


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
        self._max_eventos = max_eventos
        self._cond = threading.Condition()
        self._eventos: deque[Any] = deque()
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
        with self._cond:
            if not self._eventos and not self._cerrada:
                self._cond.wait(timeout)
            if self._eventos:
                return self._eventos.popleft()
            if self._cerrada:
                raise BusCerradoError("El bus de eventos esta cerrado.")
            return None

    def cerrar(self) -> None:
        """Cierra la suscripcion y la retira del bus."""
        with self._cond:
            self._cerrada = True
            self._cond.notify_all()
        self._bus.retirar(self)

    def _encolar(self, evento: dict[str, Any]) -> None:
        """Mete el evento en la cola aplicando la politica de descarte."""
        with self._cond:
            if self._cerrada:
                return
            if evento["type"] == "progress" and self._fusionar_progress(evento):
                return
            while len(self._eventos) >= self._max_eventos:
                if not self._expulsar():
                    logger.warning(
                        "Cola de la suscripcion %s llena y sin descartables; "
                        "se cae el evento '%s'.",
                        self.id,
                        evento["type"],
                    )
                    return
            self._eventos.append(evento)
            self._cond.notify()

    def _fusionar_progress(self, evento: dict[str, Any]) -> bool:
        """Sustituye el ``progress`` en cola por el nuevo.

        Returns:
            ``True`` si habia un ``progress`` en cola y se ha sustituido.
        """
        for indice, en_cola in enumerate(self._eventos):
            if en_cola["type"] == "progress":
                self._eventos[indice] = evento
                return True
        return False

    def _expulsar(self) -> bool:
        """Saca un evento de la cola para dejar sitio. ``False`` si no hay.

        Nunca expulsa un ``job`` ni un ``tia``: primero se van los ``log`` y
        luego los ``progress``.
        """
        for tipo in ("log", "progress"):
            for indice, en_cola in enumerate(self._eventos):
                if en_cola["type"] == tipo:
                    del self._eventos[indice]
                    return True
        return False


class BusEventos:
    """Bus de eventos de la SPA.

    Publica los cuatro tipos de evento y lleva el ultimo ``progress``, el
    ultimo ``tia`` y el ultimo ``job`` para hidratar a los clientes que se
    conectan despues.
    """

    def __init__(self, max_eventos: int = 100) -> None:
        """Crea el bus.

        Args:
            max_eventos: eventos en cola por suscriptor. Al superarlos se
                descarta lo menos importante.
        """
        self._lock = threading.Lock()
        self._max_eventos = max_eventos
        self._siguiente_id = 0
        self._suscriptores: dict[int, Suscripcion] = {}
        self._ultimo_progress: dict[str, Any] | None = None
        self._ultimo_tia: dict[str, Any] | None = None
        self._ultimo_job: dict[str, Any] | None = None
        self._cerrado = False

    # ── publicacion ──────────────────────────────────────────────────────

    def publicar(self, tipo: str, carga: dict[str, Any]) -> None:
        """Publica un evento a todos los suscriptores.

        El evento se serializa antes de repartirse: si no se puede, no se
        publica nada y se lanza el error. Un evento roto no puede romper el
        stream de un suscriptor.

        Args:
            tipo: ``progress``, ``job``, ``log`` o ``tia``.
            carga: cuerpo del evento. Se anade el campo ``type``.

        Raises:
            ValueError: si ``tipo`` no es uno de los cuatro admitidos.
            SerializacionError: si el evento no se puede serializar a JSON.
        """
        if tipo not in TIPOS:
            raise ValueError(f"Tipo de evento desconocido: {tipo!r}. Admite: {TIPOS}.")
        evento = {"type": tipo, **carga}
        try:
            json.dumps(evento, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise SerializacionError(
                f"El evento '{tipo}' no es serializable a JSON: "
                f"{type(exc).__name__}. Devuelve tipos primitivos."
            ) from exc
        with self._lock:
            if self._cerrado:
                return
            if tipo == "progress":
                self._ultimo_progress = evento
            elif tipo == "tia":
                self._ultimo_tia = evento
            elif tipo == "job":
                self._ultimo_job = evento
            suscriptores = list(self._suscriptores.values())
        for suscriptor in suscriptores:
            suscriptor._encolar(evento)

    # ── suscripcion ──────────────────────────────────────────────────────

    def suscribir(self) -> Suscripcion:
        """Crea una suscripcion.

        La suscripcion recibe de inmediato el ultimo ``progress``, el ultimo
        ``tia`` y el ultimo ``job`` conocidos, si los hay.

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
            if self._ultimo_job is not None:
                suscriptor._encolar(self._ultimo_job)
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
            suscriptor.cerrar()

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

    def ultimo_job(self) -> dict[str, Any] | None:
        """Ultimo evento ``job`` publicado, o ``None``."""
        with self._lock:
            return self._ultimo_job


# ── puente con el logging ─────────────────────────────────────────────────


class HandlerEventos(logging.Handler):
    """Handler de logging que publica cada linea en el bus.

    El nivel viaja como ``nivel`` y el texto como ``mensaje``. Si el registro
    trae excepcion, el traceback viaja como ``detalle``.

    Dos guardas de seguridad:

    - No publica los registros del propio logger ``zc_suite.nucleo.tia.eventos``: el bus
      avisa cuando una cola se llena y avisar volveria a llenar la cola.
    - Un guard de reentrada por hilo: si la publicacion provoke un log, ese
      log no vuelve a publicar.
    """

    def __init__(self, bus: BusEventos) -> None:
        super().__init__()
        self.bus = bus
        self._local = threading.local()

    def emit(self, record: logging.LogRecord) -> None:
        """Publica el registro como evento ``log``."""
        if getattr(self._local, "dentro", False):
            return
        if record.name == NOMBRE_LOGGER or record.name.startswith(f"{NOMBRE_LOGGER}."):
            return
        try:
            mensaje = record.getMessage()
        except Exception:
            mensaje = str(record.msg)
        carga: dict[str, Any] = {
            "nivel": record.levelname.lower(),
            "mensaje": mensaje,
            "detalle": self._detalle(record),
        }
        self._local.dentro = True
        try:
            self.bus.publicar("log", carga)
        except Exception:
            self.handleError(record)
        finally:
            self._local.dentro = False

    @staticmethod
    def _detalle(record: logging.LogRecord) -> str | None:
        """Traceback del registro, o ``None`` si no traia excepcion."""
        if not record.exc_info:
            return None
        return "".join(traceback.format_exception(*record.exc_info))


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
    ``zc_suite.nucleo.web.app``.
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
