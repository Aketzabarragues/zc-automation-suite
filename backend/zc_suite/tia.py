"""zc_suite.tia — hilo unico, unico dueno del portal de TIA Portal.

Todo el contacto con el SDK de Siemens vive aqui:

- Un unico hilo daemon ejecuta los trabajos ENTEROS. El ``import`` de
  ``siemens_tia_scripting`` ocurre dentro de ese hilo y en ningun otro punto
  del proceso.
- ``ServicioTIA.lanzar(funcion, **params)`` encola un trabajo y devuelve su
  ``job_id``. Si ya hay uno en curso, lanza ``OcupadoError`` y la ruta responde
  ``409``.
- ``Job`` describe el trabajo: declara sus pasos, los va marcando y expone
  ``job.tia.portal``, la unica via al portal.
- ``transaccion(job, texto)`` envuelve las escrituras en TIA en la
  transaccion nativa, con rollback si algo falla.

El modulo no sabe nada de SSE: publica con el callback ``publicador`` que le
inyecte el llamador, con la forma ``publicador(tipo, carga)`` y ``tipo`` en
``progress``, ``job``, ``log`` y ``tia``.

Restricciones:

- El portal es un objeto COM afin a hilo. Solo el hilo de TIA lo toca.
  ``estado()`` devuelve valores cacheados, nunca consulta al portal.
- Los fallos son excepciones. Nunca se devuelve ``{"ok": False}``.
"""
from __future__ import annotations

import logging
import tempfile
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Callback de publicacion: ``publicador(tipo, carga)``.
Publicador = Callable[[str, dict[str, Any]], None]

#: Devuelve el modulo ``siemens_tia_scripting`` ya importado.
Cargador = Callable[[], Any]

#: Estados de un paso del trabajo.
PENDIENTE = "pending"
EN_CURSO = "running"
HECHO = "done"
ERROR = "error"

#: Estados de un trabajo completo.
OK = "ok"
CANCELADO = "cancelado"

#: Segundos entre comprobaciones de vida del portal cuando el hilo esta ocioso.
INTERVALO_PING = 10.0


# ── errores ────────────────────────────────────────────────────────────────


class TIAError(Exception):
    """Fallo del subsistema TIA."""


class OcupadoError(TIAError):
    """Hay un trabajo en curso: no se puede encolar otro."""


class SinPortalError(TIAError):
    """No hay conexion con TIA Portal."""


class CanceladoError(TIAError):
    """El trabajo fue cancelado por el operario."""


class TransaccionError(TIAError):
    """Fallo en una transaccion de TIA.

    El mensaje distingue si fallo la operacion o el commit de la
    transaccion, y si el rollback se pudo completar.
    """


class FueraDelHiloError(TIAError):
    """El portal se ha usado desde un hilo que no es el de TIA."""


# ── helpers ────────────────────────────────────────────────────────────────


def _ahora() -> str:
    """Marca de tiempo ISO con segundos."""
    return datetime.now().isoformat(timespec="seconds")


def _etiqueta(nombre: str) -> str:
    """Etiqueta legible de un paso a partir de su identificador."""
    return nombre.replace("_", " ").capitalize()


# ── paso del trabajo ───────────────────────────────────────────────────────


class _Etapa(dict[str, Any]):
    """Registro de un paso del trabajo.

    Es un dict normal, de modo que el codigo del trabajo escribe el detalle
    con ``paso["detail"] = "..."``. Cada mutacion publica el progreso, para
    que el detalle se vea en el faceplate mientras el paso sigue en curso.
    """

    def __init__(self, datos: dict[str, Any], al_cambiar: Callable[[], None]) -> None:
        super().__init__(datos)
        self._al_cambiar = al_cambiar
        self._interno = False

    def __setitem__(self, clave: str, valor: Any) -> None:
        super().__setitem__(clave, valor)
        if not self._interno:
            self._al_cambiar()

    def _set_interno(self, **campos: Any) -> None:
        """Actualiza campos del nucleo en una sola publicacion."""
        self._interno = True
        try:
            for clave, valor in campos.items():
                super().__setitem__(clave, valor)
        finally:
            self._interno = False
        self._al_cambiar()


# ── trabajo ────────────────────────────────────────────────────────────────


class Job:
    """Un trabajo en ejecucion dentro del hilo de TIA.

    El trabajo declara sus pasos al inicio con ``empezar`` y los va marcando
    con ``paso``. El estado del trabajo son variables locales de la funcion
    que lo ejecuta: aqui solo vive lo que hace falta para reporting.
    """

    def __init__(self, job_id: str, operacion: str, servicio: ServicioTIA) -> None:
        self.id = job_id
        self.tia = servicio
        self._operacion = operacion
        self._titulo = operacion
        self._etapas: list[_Etapa] = []
        self._por_id: dict[str, _Etapa] = {}
        self._cancelado = threading.Event()
        self._empezado_at: str | None = None
        self._terminado_at: str | None = None
        self._error: str | None = None

    # ── consultas ───────────────────────────────────────────────────────

    @property
    def cancelado(self) -> bool:
        """``True`` si el operario ha pedido la cancelacion."""
        return self._cancelado.is_set()

    def cancelar(self) -> None:
        """Pide la cancelacion. Se respeta entre pasos."""
        self._cancelado.set()
        self.log("Cancelacion solicitada.", nivel="aviso")

    # ── ciclo de vida ────────────────────────────────────────────────────

    def empezar(self, titulo: str, pasos: list[str]) -> None:
        """Declara el trabajo y todos sus pasos.

        Args:
            titulo: texto que ve el operario.
            pasos: identificadores de los pasos, en orden de ejecucion.

        Raises:
            ValueError: si ``pasos`` esta vacio o repite un identificador.
        """
        if not pasos:
            raise ValueError("El trabajo debe declarar al menos un paso.")
        if len(set(pasos)) != len(pasos):
            raise ValueError(f"Hay pasos repetidos en {pasos!r}.")
        self._titulo = titulo
        self._empezado_at = _ahora()
        self._etapas = [
            _Etapa(
                {
                    "id": nombre,
                    "label": _etiqueta(nombre),
                    "status": PENDIENTE,
                    "detail": None,
                    "started_at": None,
                    "finished_at": None,
                },
                self._publicar_progreso,
            )
            for nombre in pasos
        ]
        self._por_id = {etapa["id"]: etapa for etapa in self._etapas}
        self._publicar_progreso()

    @contextmanager
    def paso(self, nombre: str) -> Iterator[dict[str, Any]]:
        """Marca un paso como en curso y lo cierra al salir.

        El dict que entrega es el registro del paso: se escribe el detalle
        con ``paso["detail"] = "..."``.

        Raises:
            ValueError: si el paso no fue declarado en ``empezar``.
            CanceladoError: si el trabajo estaba cancelado antes de empezar.
        """
        if nombre not in self._por_id:
            declarados = list(self._por_id)
            raise ValueError(
                f"El paso '{nombre}' no fue declarado en job.empezar(). "
                f"Pasos declarados: {declarados}"
            )
        if self.cancelado:
            raise CanceladoError("El trabajo fue cancelado.")
        etapa = self._por_id[nombre]
        etapa._set_interno(status=EN_CURSO, started_at=_ahora())
        try:
            yield etapa
        except BaseException:
            etapa._set_interno(status=ERROR, finished_at=_ahora())
            raise
        else:
            etapa._set_interno(status=HECHO, finished_at=_ahora())

    def finalizar(self, estado: str, error: str | None) -> None:
        """Cierra el trabajo y publica el estado final."""
        self._terminado_at = _ahora()
        self._error = error
        if estado != OK:
            for etapa in self._etapas:
                if etapa["status"] == EN_CURSO:
                    etapa._set_interno(status=ERROR, finished_at=_ahora())

    def snapshot(self, activo: bool = True) -> dict[str, Any]:
        """Estado del trabajo con la forma que consume el faceplate."""
        etapas = [dict(etapa) for etapa in self._etapas]
        total = len(etapas)
        current = sum(1 for etapa in etapas if etapa["status"] in (HECHO, ERROR))
        return {
            "active": activo,
            "operation": self._operacion,
            "label": self._titulo,
            "current": current,
            "total": total,
            "percent": round(100.0 * current / total) if total else 0,
            "stages": etapas,
            "started_at": self._empezado_at,
            "finished_at": self._terminado_at,
            "error": self._error,
        }

    # ── publicacion ──────────────────────────────────────────────────────

    def log(self, mensaje: str, nivel: str = "info") -> None:
        """Publica una linea de log del trabajo."""
        self.tia.publicar("log", {"nivel": nivel, "mensaje": mensaje})

    def _publicar_progreso(self) -> None:
        self.tia.publicar("progress", self.snapshot())


# ── transaccion ────────────────────────────────────────────────────────────


def proyecto_activo(portal: Any) -> Any:
    """Devuelve el proyecto abierto del portal.

    Raises:
        SinPortalError: si no hay proyecto abierto.
    """
    proyecto = portal.get_project()
    if not proyecto:
        raise SinPortalError(
            "No hay ningun proyecto abierto en TIA Portal. Abre el proyecto y repite."
        )
    return proyecto


def _revertir(proyecto: Any, texto: str) -> tuple[bool, str]:
    """Ejecuta el rollback de la transaccion.

    Returns:
        Tupla ``(ok, descripcion)``. ``ok`` es ``False`` si el rollback
        fallo; la descripcion dice que paso.
    """
    try:
        proyecto.end_transaction(rollback=True)
    except Exception as exc:
        logger.error(
            "Rollback fallido tras abortar '%s': %s: %s",
            texto,
            type(exc).__name__,
            exc,
        )
        return (
            False,
            f"Rollback NO completado ({type(exc).__name__}: {exc}): "
            "el proyecto puede haber quedado a medias.",
        )
    return True, "Rollback ejecutado."


def texto_error(exc: BaseException) -> str:
    """Texto del error de un trabajo: tipo, mensaje y notas.

    Las notas las anade ``transaccion`` con ``add_note``. No se tocan los
    ``args`` de la excepcion: para ``OSError`` y ``KeyError`` el mensaje se
    construye a partir de ellos y se perderia.
    """
    texto = f"{type(exc).__name__}: {exc}"
    notas = getattr(exc, "__notes__", None)
    if notas:
        texto = f"{texto} [{' | '.join(notas)}]"
    return texto


@contextmanager
def transaccion(job: Job, texto: str) -> Iterator[None]:
    """Envuelve las escrituras en TIA en una transaccion nativa.

    Hace ``start_transaction`` -> yield -> ``end_transaction(rollback=False)``.

    Si la operacion falla, hace ``end_transaction(rollback=True)`` y vuelve a
    lanzar la misma excepcion con una nota que dice que fallo la operacion y
    si el rollback se pudo completar.

    Si el commit falla, tambien intenta el rollback y lanza
    ``TransaccionError`` diciendo que fallo el commit.

    Raises:
        TransaccionError: si fallo el commit, o si fallo la operacion y su
            rollback tampoco se pudo completar.
    """
    proyecto = proyecto_activo(job.tia.portal)
    proyecto.start_transaction(undo_text=texto, dialog_text=texto)
    try:
        yield
    except BaseException as exc:
        ok_rollback, rollback_txt = _revertir(proyecto, texto)
        if not ok_rollback:
            raise TransaccionError(
                f"Fallo de la operacion en la transaccion '{texto}': "
                f"{type(exc).__name__}: {exc}. {rollback_txt}"
            ) from exc
        exc.add_note(f"Transaccion '{texto}': fallo de la operacion. {rollback_txt}")
        raise
    else:
        try:
            proyecto.end_transaction(rollback=False)
        except Exception as exc_commit:
            ok_rollback, rollback_txt = _revertir(proyecto, texto)
            if ok_rollback:
                detalle = "No se confirmó nada: el rollback dejó el proyecto como estaba."
            else:
                detalle = rollback_txt
            raise TransaccionError(
                f"Fallo del commit de la transaccion '{texto}': "
                f"{type(exc_commit).__name__}: {exc_commit}. {detalle}"
            ) from exc_commit


# ── carga del SDK ──────────────────────────────────────────────────────────


def silenciar_log_nativo(ts: Any, ruta_log: Path) -> None:
    """Desactiva la salida por consola del log nativo de Siemens.

    API documentada del SDK: ``set_logging(path, console)``.
    """
    try:
        ts.set_logging(path=str(ruta_log), console=False)
    except Exception as exc:
        logger.warning("No se pudo silenciar el log nativo de Siemens: %s", exc)


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
        """
        while not self._parar.is_set():
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

    # ── encolado ─────────────────────────────────────────────────────────

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
        self.arrancar()
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
        """``True`` si hay portal abierto."""
        return self._portal is not None

    @property
    def ocupado(self) -> bool:
        """``True`` si hay un trabajo en curso o en cola."""
        with self._lock:
            return self._ocupado

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
        self.publicar("tia", self.estado())

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
        try:
            resultado = funcion(job, **params)
        except CanceladoError as exc:
            estado = CANCELADO
            error = texto_error(exc)
            logger.info("Trabajo %s cancelado.", job.id)
        except Exception as exc:
            estado = ERROR
            error = texto_error(exc)
            logger.exception("Trabajo %s fallo.", job.id)
        finally:
            job.finalizar(estado, error)
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
            self._portal.get_process_id()
        except Exception as exc:
            logger.warning("El portal de TIA ya no responde: %s", exc)
            self._portal = None
            self._modo_portal = None
            self._ultimo_error = f"La conexion con TIA Portal se ha perdido: {exc}"
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
            return self._portal
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
            raise TIAError(
                f"No se pudo {accion} el portal de TIA: {type(exc).__name__}: {exc}"
            ) from exc
        if portal is None:
            raise TIAError(
                "El portal de TIA devolvio None. Comprueba que TIA Portal este "
                "abierto y que el usuario pertenezca al grupo de Openness."
            )
        self._portal = portal
        self._modo_portal = modo
        self._publicar_conexion()
        return portal

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
        except Exception as exc:
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
    job.empezar("Conectar con TIA Portal", ["cargar_sdk", "abrir_portal"])
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
    }


def desconectar(job: Job) -> dict[str, Any]:
    """Desconecta de TIA Portal. Idempotente."""
    job.empezar("Desconectar de TIA Portal", ["cerrar_portal"])
    with job.paso("cerrar_portal") as paso:
        job.tia.cerrar_portal()
        paso["detail"] = "Portal cerrado"
    return {"conectado": False}
