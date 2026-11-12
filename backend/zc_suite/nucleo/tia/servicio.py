"""zc_suite.nucleo.tia.servicio — el hilo unico, dueno del portal.

Todo el contacto con el SDK de Siemens vive aqui:

- Un unico hilo daemon ejecuta los trabajos ENTEROS. El ``import`` de
  ``siemens_tia_scripting`` ocurre dentro de ese hilo y en ningun otro punto
  del proceso.
- ``ServicioTIA.lanzar(funcion, **params)`` encola un trabajo y devuelve su
  ``job_id``. Si ya hay uno en curso, lanza ``OcupadoError`` y la ruta responde
  ``409``.

El modulo no sabe nada de SSE: publica con el callback ``publicador`` que le
inyecte el llamador, con la forma ``publicador(tipo, carga)`` y ``tipo`` en
``progress``, ``job``, ``log`` y ``tia``.

Restricciones:

- El portal es un objeto COM afin a hilo. Solo el hilo de TIA lo toca.
  ``estado()`` devuelve valores cacheados, nunca consulta al portal.
- Los fallos son excepciones. Nunca se devuelve ``{"ok": False}``.
"""
from __future__ import annotations

import json
import logging
import re
import tempfile
import threading
import traceback
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from zc_suite.errores import TIAError
from zc_suite.nucleo.tia.errores import (
    CanceladoError,
    FueraDelHiloError,
    OcupadoError,
    SinPortalError,
    texto_error,
)
from zc_suite.nucleo.tia.job import CANCELADO, ERROR, OK, Job

logger = logging.getLogger(__name__)

#: Callback de publicacion: ``publicador(tipo, carga)``.
Publicador = Callable[[str, dict[str, Any]], None]

#: Devuelve el modulo ``siemens_tia_scripting`` ya importado.
Cargador = Callable[[], Any]

#: Segundos entre comprobaciones de vida del portal cuando el hilo esta ocioso.
INTERVALO_PING = 10.0

#: Lo que ve el operario cuando el portal deja de responder.
#:
#: El detalle tecnico (el error pendiente de .NET) no sale de aqui: se
#: queda en el log, donde si sirve para diagnosticar.
AVISO_TIA_CERRADO = "TIA Portal se ha cerrado o no responde"


def es_serializable(valor: Any) -> bool:
    """``True`` si el valor se puede enviar al navegador como JSON."""
    try:
        json.dumps(valor, ensure_ascii=False)
    except (TypeError, ValueError):
        return False
    return True

# ── carga del SDK ──────────────────────────────────────────────────────────


def silenciar_log_nativo(ts: Any, ruta_log: Path) -> None:
    """Desactiva la salida por consola del log nativo de Siemens.

    API documentada del SDK: ``set_logging(path, console)``.
    """
    try:
        ts.set_logging(path=str(ruta_log), console=False)
    except Exception as exc:
        logger.warning("No se pudo silenciar el log nativo de Siemens: %s", exc)


#: Errores del SDK que se traducen a un mensaje para el operario. El
#: texto original de Siemens se queda en el log.
TRADUCCIONES_SDK: tuple[tuple[str, str], ...] = (
    (
        "no matching tia portal version",
        "No hay ningún TIA Portal abierto (o su versión no es compatible). "
        "Abre TIA Portal con el proyecto y vuelve a conectar.",
    ),
    (
        "opennessaccessexception",
        "TIA Portal ha rechazado la conexión. Comprueba que el usuario "
        "pertenece al grupo de Openness y que el proyecto está abierto.",
    ),
)


def mensaje_operador(exc: Exception) -> str:
    """Mensaje para el operario de un fallo del SDK.

    Los errores conocidos del SDK se traducen a un texto accionable. El
    original se conserva en el log y en la excepcion que lo causo.
    """
    texto = str(exc).lower()
    for marca, mensaje in TRADUCCIONES_SDK:
        if marca in texto:
            return mensaje
    return f"{type(exc).__name__}: {exc}"


def version_tia_instalada(ts: Any) -> str:
    """La version de TIA Portal instalada, tal y como la ve el SDK.

    Unica via documentada: ``get_installed_bundles()`` devuelve los bundles
    instalados con su titulo ("Siemens TIA Portal V18.0 Upd5"). El manual
    **no** expone la version del portal conectado.

    Por defecto el SDK engancha la ultima version instalada
    (``attach_portal`` sin ``version``), asi que normalmente coincide con la
    conectada.

    Returns:
        La version, tipo ``"V21.1"``. Cadena vacia si no se puede averiguar.
    """
    try:
        bundles = ts.get_installed_bundles()
    except Exception:
        return ""
    versiones: list[tuple[int, int]] = []
    for bundle in bundles or []:
        try:
            titulo = str(bundle.get_title())
        except Exception:
            continue
        if "TIA Portal" not in titulo:
            continue
        coincidencia = re.search(r"\bV(\d+)\.(\d+)\b", titulo)
        if coincidencia:
            versiones.append((int(coincidencia.group(1)), int(coincidencia.group(2))))
    if not versiones:
        return ""
    mayor, menor = max(versiones)
    return f"V{mayor}.{menor}"


def pid_del_portal(portal: Any) -> int:
    """PID del portal, forzando la salida de los errores pendientes del SDK.

    Peculiaridad de ``siemens_tia_scripting``: cuando TIA se cierra, la
    llamada a ``get_process_id()`` puede devolver bien pero dejar un error
    .NET *pendiente*. Ese error no salta en la llamada: salta en la
    siguiente operacion del hilo, que puede ser un ``wait()`` de Python y
    tumbar el hilo entero.

    Por eso, despues de la llamada se hace una comprobacion trivial. Si hay
    un error pendiente, salta aqui, dentro del ``try`` de quien llama, y no
    mas tarde en un sitio que no parece relacionado.
    """
    pid = portal.get_process_id()
    if pid is None:
        raise TIAError("El portal de TIA no devolvio PID.")
    return int(pid)


def cargar_modulo_tia() -> Any:
    """Importa ``siemens_tia_scripting``.

    Este es el UNICO punto del proceso donde se importa el wrapper. Solo lo
    llama el hilo de TIA.
    """
    try:
        import siemens_tia_scripting as ts
    except ImportError as exc:
        raise TIAError(
            "No se pudo importar 'siemens_tia_scripting'. La wheel oficial de "
            "Siemens no esta instalada en este interprete. Ver docs/INSTALAR.md."
        ) from exc
    return ts

# ── servicio ───────────────────────────────────────────────────────────────


class ServicioTIA:
    """Hilo unico de TIA y estado de la conexion con el portal.

    El servicio es el dueno del portal: un unico hilo daemon ejecuta los
    trabajos enteros. El portal no se toca desde fuera de ese hilo.
    """

    def __init__(
        self,
        publicador: Publicador | None = None,
        cargador: Cargador | None = None,
        ruta_log: Path | None = None,
        intervalo_ping: float = INTERVALO_PING,
    ) -> None:
        """Crea el servicio. El hilo no arranca hasta ``arrancar()``.

        Args:
            publicador: callback ``(tipo, carga)`` del bus de eventos.
            cargador: devuelve el modulo ``siemens_tia_scripting``. Solo se
                usa en tests para inyectar un modulo falso.
            ruta_log: fichero donde el SDK escribe su log nativo.
            intervalo_ping: segundos entre comprobaciones de vida del portal
                cuando no hay ningun trabajo en curso.
        """
        self._publicador = publicador
        self._cargador = cargador
        self._ruta_log = ruta_log or Path(tempfile.gettempdir()) / "zc_tia_scripting.log"
        self._intervalo_ping = intervalo_ping

        self._lock = threading.Lock()
        self._parar = threading.Event()
        self._hay_trabajo = threading.Event()
        self._hilo: threading.Thread | None = None

        self._ocupado = False
        self._pendiente: tuple[Callable[..., Any], Job, dict[str, Any]] | None = None
        self._job_actual: Job | None = None
        self._trabajo_actual: str | None = None

        self._ts: Any = None
        self._portal: Any = None
        self._modo_portal: str | None = None
        self._ultimo_error: str | None = None
        self._conexion_publicada: tuple[bool, str | None] | None = None
        self._version_tia: str = ""

    # ── ciclo de vida del hilo ───────────────────────────────────────────

    def arrancar(self) -> None:
        """Arranca el hilo de TIA. Idempotente."""
        with self._lock:
            if self._hilo is not None and self._hilo.is_alive():
                return
            self._parar.clear()
            self._hilo = threading.Thread(
                target=self._bucle,
                name="zc-tia",
                daemon=True,
            )
            self._hilo.start()
        logger.info("Hilo de TIA arrancado.")

    def parar(self, timeout: float = 5.0) -> None:
        """Para el hilo de TIA y espera a que termine."""
        self._parar.set()
        self._hay_trabajo.set()
        hilo = self._hilo
        if hilo is not None:
            hilo.join(timeout=timeout)
            if hilo.is_alive():
                logger.warning("El hilo de TIA no termino en %.1fs.", timeout)
        self._hilo = None
        logger.info("Hilo de TIA parado.")

    def _bucle(self) -> None:
        """Toma el trabajo pendiente y lo ejecuta entero.

        Cuando no hay trabajo, comprueba que el portal siga vivo. La
        comprobacion se hace aqui, en el hilo dueno del portal.

        El hilo **no puede morir**. Cada iteracion va dentro de un
        ``try``: si algo falla (un error pendiente del SDK que salta en el
        ``wait``, un COM que se cae), se anota, se da el portal por perdido
        y se sigue. Un hilo muerto deja la app zombi: el portal no responde
        pero la app sigue creyendo que esta conectada.
        """
        while not self._parar.is_set():
            try:
                self._hay_trabajo.wait(timeout=self._intervalo_ping)
                if self._parar.is_set():
                    break
                self._hay_trabajo.clear()
                with self._lock:
                    pendiente = self._pendiente
                    self._pendiente = None
                if pendiente is None:
                    self._verificar_conexion()
                    continue
                funcion, job, params = pendiente
                self._ejecutar(funcion, job, params)
            except BaseException:
                logger.exception(
                    "Fallo inesperado en el hilo de TIA. El hilo continua."
                )
                self._perder_portal(
                    "El hilo de TIA ha encontrado un fallo y sigue en pie: "
                    "se da el portal por perdido."
                )

    # ── encolado ─────────────────────────────────────────────────────────

    def _hilo_vivo(self) -> bool:
        """``True`` si el hilo de TIA esta vivo."""
        hilo = self._hilo
        return hilo is not None and hilo.is_alive()

    def _perder_portal(self, mensaje: str) -> None:
        """Da el portal por perdido y publica el nuevo estado.

        El aviso tambien va a la consola de la SPA: es lo que el
        operario ve. El detalle tecnico se queda en el log.
        """
        self._portal = None
        self._modo_portal = None
        self._ultimo_error = mensaje
        self.publicar("log", {"nivel": "error", "mensaje": mensaje})
        self._publicar_conexion()

    def _asegurar_hilo(self) -> None:
        """Arranca el hilo de TIA si no esta vivo.

        Si el hilo anterior ha muerto, el reinicio no se hace en silencio:
        se avisa por log y por el evento ``tia``, porque el trabajo que
        estuviera en curso se ha perdido.
        """
        if self._hilo_vivo():
            return
        if self._hilo is not None:
            logger.error(
                "El hilo de TIA ha muerto; se reinicia. El trabajo en curso se ha perdido."
            )
            self._ultimo_error = "El hilo de TIA se reinició tras un fallo"
            self._ocupado = False
            self._trabajo_actual = None
            self._publicar_conexion()
        self.arrancar()

    def lanzar(self, funcion: Callable[..., Any], **params: Any) -> str:
        """Encola un trabajo y devuelve su ``job_id``.

        Args:
            funcion: recibe ``(job, **params)`` y devuelve el resultado del
                trabajo.
            params: argumentos con los que se llama a la funcion.

        Raises:
            OcupadoError: si ya hay un trabajo en curso.
        """
        job = Job(job_id=uuid.uuid4().hex, operacion=funcion.__name__, servicio=self)
        with self._lock:
            if self._ocupado:
                raise OcupadoError("Hay un trabajo en curso. Espera a que termine.")
            self._ocupado = True
            self._pendiente = (funcion, job, params)
        self._asegurar_hilo()
        self._hay_trabajo.set()
        logger.info("Trabajo encolado: %s (%s)", job.id, funcion.__name__)
        return job.id

    def cancelar(self, job_id: str) -> bool:
        """Pide la cancelacion de un trabajo.

        Sirve para un trabajo en cola y para uno que ya esta en ejecucion:
        la cancelacion se respeta en el siguiente paso.

        Returns:
            ``True`` si el trabajo existe y se ha marcado para cancelar.
        """
        with self._lock:
            pendiente = self._pendiente
            actual = self._job_actual
        job: Job | None = None
        if pendiente is not None and pendiente[1].id == job_id:
            job = pendiente[1]
        elif actual is not None and actual.id == job_id:
            job = actual
        if job is None:
            return False
        job.cancelar()
        return True

    # ── estado ───────────────────────────────────────────────────────────

    @property
    def conectado(self) -> bool:
        """``True`` si hay portal abierto y el hilo de TIA sigue vivo.

        Si el hilo ha muerto, la conexion no vale: el portal guardado
        pertenece a un hilo que ya no existe.
        """
        return self._portal is not None and self._hilo_vivo()

    @property
    def ocupado(self) -> bool:
        """``True`` si hay un trabajo en curso o en cola."""
        with self._lock:
            return self._ocupado

    @property
    def version_tia(self) -> str:
        """La version de TIA Portal conectada. Vacia si no se sabe."""
        return self._version_tia

    def _exigir_hilo(self) -> None:
        """Comprueba que la llamada viene del hilo de TIA.

        Raises:
            FueraDelHiloError: si la llamada viene de otro hilo.
        """
        if self._hilo is not None and threading.current_thread() is not self._hilo:
            raise FueraDelHiloError(
                "El portal de TIA solo se puede usar desde el hilo de TIA. "
                "Esta llamada ha llegado desde otro hilo."
            )

    @property
    def portal(self) -> Any:
        """El portal de TIA.

        Raises:
            FueraDelHiloError: si se lee desde un hilo que no es el de TIA.
            SinPortalError: si no hay conexion.
        """
        self._exigir_hilo()
        if self._portal is None:
            raise SinPortalError("No hay conexion con TIA Portal. Conectate primero.")
        return self._portal

    def estado(self) -> dict[str, Any]:
        """Estado de la conexion, sin tocar el portal.

        Los valores estan cacheados por el hilo de TIA: leerlos desde otro
        hilo es seguro.
        """
        return {
            "conectado": self.conectado,
            "trabajo_actual": self._trabajo_actual,
            "ultimo_error": self._ultimo_error,
            "version_tia": self._version_tia,
        }

    # ── publicacion ──────────────────────────────────────────────────────

    def publicar(self, tipo: str, carga: dict[str, Any]) -> None:
        """Publica un evento. Best effort: un bus roto no tumba un trabajo."""
        if self._publicador is None:
            return
        try:
            self._publicador(tipo, carga)
        except Exception:
            logger.exception("Fallo publicando el evento '%s'.", tipo)

    def _publicar_conexion(self) -> None:
        """Publica el estado de la conexion, solo si ha cambiado.

        Lo que se compara es la conexion (si esta vivo y cual es el ultimo
        error), no el trabajo en curso. Sin esto, una desconexion se
        anuncia dos veces: una al detectarla y otra al cerrar el trabajo.
        """
        estado = self.estado()
        firma = (estado["conectado"], estado["ultimo_error"])
        if firma == self._conexion_publicada:
            return
        self._conexion_publicada = firma
        self.publicar("tia", estado)

    # ── ejecucion ────────────────────────────────────────────────────────

    def _ejecutar(
        self,
        funcion: Callable[..., Any],
        job: Job,
        params: dict[str, Any],
    ) -> None:
        """Ejecuta el trabajo entero dentro del hilo de TIA."""
        self._trabajo_actual = job.id
        self._ultimo_error = None
        with self._lock:
            self._job_actual = job
        self._publicar_conexion()
        estado = OK
        resultado: Any = None
        error: str | None = None
        traza: str | None = None
        nivel_final = logging.ERROR
        try:
            resultado = funcion(job, **params)
        except CanceladoError as exc:
            estado = CANCELADO
            error = texto_error(exc)
            logger.info("Trabajo %s cancelado.", job.id)
        except TIAError as exc:
            # Fallo esperado: TIA cerrado, sin proyecto, sin permiso. Se
            # registra en una linea; el traceback solo para lo inesperado.
            estado = ERROR
            error = texto_error(exc)
            nivel_final = logging.WARNING
            logger.warning("Trabajo %s fallo: %s", job.id, error)
        except Exception as exc:
            estado = ERROR
            error = texto_error(exc)
            traza = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            logger.exception("Trabajo %s fallo.", job.id)
        else:
            if resultado is not None and not es_serializable(resultado):
                estado = ERROR
                error = (
                    f"El resultado de {job.operacion} no es serializable a JSON: "
                    f"{type(resultado).__name__}. Devuelve tipos primitivos."
                )
                resultado = None
                logger.error("Trabajo %s: %s", job.id, error)
        finally:
            job.finalizar(estado, error, traza, nivel_final)
            if estado == ERROR:
                self._ultimo_error = error
            self._verificar_conexion()
            self.publicar(
                "job",
                {
                    "job": job.id,
                    "estado": estado,
                    "resultado": resultado,
                    "error": error,
                },
            )
            self.publicar("progress", job.snapshot(activo=False))
            self._trabajo_actual = None
            with self._lock:
                self._job_actual = None
                self._ocupado = False
            self._publicar_conexion()

    def _verificar_conexion(self) -> None:
        """Comprueba que el portal sigue vivo. Solo desde el hilo de TIA.

        Si el portal ha muerto, queda desconectado y se publica el evento
        ``tia`` con el nuevo estado.
        """
        if self._portal is None:
            return
        try:
            pid_del_portal(self._portal)
        except BaseException as exc:
            logger.warning("El portal de TIA ya no responde: %s", exc)
            self._perder_portal(AVISO_TIA_CERRADO)
            self._publicar_conexion()

    # ── operaciones del hilo ─────────────────────────────────────────────
    # Solo se llaman desde dentro de un trabajo, o sea, desde el hilo de TIA.

    def cargar_sdk(self) -> Any:
        """Carga el wrapper de Siemens y silencia su log nativo. Idempotente."""
        if self._ts is None:
            cargador = self._cargador or cargar_modulo_tia
            self._ts = cargador()
            silenciar_log_nativo(self._ts, self._ruta_log)
            logger.info("SDK de TIA cargado.")
        return self._ts

    def abrir_portal(self, modo: str = "attach") -> Any:
        """Abre o engancha el portal de TIA Portal.

        Modos de portal (``Enums.PortalMode``):

        - ``"attach"`` -> ``WithGraphicalUserInterface``. Es el flujo del
          operario: TIA Portal ya abierto con su proyecto, y la app se
          engancha a esa instancia.
        - ``"open"`` -> ``AnyUserInterface``. Abre una instancia nueva. Es
          el valor que usaba el flujo de "abrir proyecto" de la version
          anterior; existe en el enum del SDK, aunque el manual solo
          documenta ``WithGraphicalUserInterface`` y
          ``WithoutGraphicalUserInterface``.

        Args:
            modo: ``"attach"`` o ``"open"``.

        Raises:
            TIAError: si el portal no se puede abrir.
            FueraDelHiloError: si la llamada no viene del hilo de TIA.
        """
        self._exigir_hilo()
        if modo not in ("attach", "open"):
            raise TIAError(f"Modo de portal invalido: {modo!r}. Usa 'attach' u 'open'.")
        ts = self.cargar_sdk()
        if self._portal is not None:
            if self._portal_vivo():
                return self._portal
            logger.warning(
                "El portal guardado no responde; se descarta y se vuelve a enganchar."
            )
            self._portal = None
            self._modo_portal = None
        if modo == "attach":
            portal_mode = ts.Enums.PortalMode.WithGraphicalUserInterface
        else:
            portal_mode = ts.Enums.PortalMode.AnyUserInterface
        try:
            if modo == "attach":
                portal = ts.attach_portal(portal_mode=portal_mode)
            else:
                portal = ts.open_portal(portal_mode=portal_mode)
        except Exception as exc:
            accion = "enganchar" if modo == "attach" else "abrir"
            logger.warning(
                "No se pudo %s el portal de TIA: %s: %s",
                accion,
                type(exc).__name__,
                exc,
            )
            raise TIAError(mensaje_operador(exc)) from exc
        if portal is None:
            raise TIAError(
                "El portal de TIA devolvio None. Comprueba que TIA Portal este "
                "abierto y que el usuario pertenezca al grupo de Openness."
            )
        self._portal = portal
        self._modo_portal = modo
        self._version_tia = version_tia_instalada(ts)
        self._publicar_conexion()
        return portal

    def _portal_vivo(self) -> bool:
        """``True`` si el portal guardado sigue respondiendo."""
        if self._portal is None:
            return False
        try:
            pid_del_portal(self._portal)
        except BaseException:
            return False
        return True

    def cerrar_portal(self) -> None:
        """Cierra o desengancha el portal. Idempotente."""
        self._exigir_hilo()
        portal = self._portal
        if portal is None:
            return
        try:
            if self._modo_portal == "open":
                portal.close_portal()
            else:
                portal.detach()
        except BaseException as exc:
            logger.warning("No se pudo cerrar el portal de TIA: %s", exc)
        finally:
            self._portal = None
            self._modo_portal = None
            self._publicar_conexion()

# ── trabajos de conexion ───────────────────────────────────────────────────


def conectar(job: Job, modo: str = "attach") -> dict[str, Any]:
    """Conecta con TIA Portal.

    Args:
        job: trabajo en curso.
        modo: ``"attach"`` se engancha a un TIA Portal ya abierto (por
            defecto, que es el flujo del operario); ``"open"`` abre una
            instancia nueva.
    """
    job.empezar(
        "Conectar con TIA Portal",
        [
            ("cargar_sdk", "Cargar el SDK de Siemens"),
            ("abrir_portal", "Enganchar TIA Portal"),
        ],
    )
    with job.paso("cargar_sdk") as paso:
        job.tia.cargar_sdk()
        paso["detail"] = "SDK de Siemens cargado"
    with job.paso("abrir_portal") as paso:
        portal = job.tia.abrir_portal(modo)
        paso["detail"] = f"PID {portal.get_process_id()}"
    return {
        "conectado": True,
        "modo": modo,
        "pid": portal.get_process_id(),
        "version_tia": job.tia.version_tia,
    }


def desconectar(job: Job) -> dict[str, Any]:
    """Desconecta de TIA Portal. Idempotente."""
    job.empezar("Desconectar de TIA Portal", [("cerrar_portal", "Cerrar el portal")])
    with job.paso("cerrar_portal") as paso:
        job.tia.cerrar_portal()
        paso["detail"] = "Portal cerrado"
    return {"conectado": False}
