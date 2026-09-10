"""El "PLC" base de zc-automation-suite: Engine, FB_Base, DBs, FBs trasversales.

Este modulo es **trasversal puro**: no conoce areas. Los FBs y DBs
especificos de area viven en ``areas/<area>/plc/`` (ver ``AGENTS.md``
§1 y §5).

Modelo IEC 61131-3 implementado en Python:

  - **FB (Function Block):** clase con ``nStep`` discreto
    (``0 = idle``, ``n_done = done``, ``n_error = 99 = error``).
    ``start(**params)`` es sincrono e idempotente. ``tick()`` es
    ``async`` y lo llama el Engine cada 100 ms. Las excepciones en
    ``tick()`` se capturan: ``nError=1``, ``error_msg=str(e)``,
    ``nStep=n_error`` (estado terminal).

  - **DB (Data Block):** ``@dataclass`` compartida. ``DB_EstadoConexion``
    es trasversal y vive aqui; las areas tienen las suyas en
    ``areas/<area>/plc/data.py``.

  - **Engine (OB1):** singleton. Loop asyncio de 100 ms que tickea los
    FBs activos y publica cambios al bus SSE. Las areas registran
    sus FBs/DBs con ``engine.register_fb`` / ``engine.register_db``.

Convenciones (.clinerules §5, §6, §9; AGENTS.md):
  - ``from __future__ import annotations`` en todo modulo con type
    hints forward-ref.
  - Type hints en TODAS las firmas.
  - ``asyncio`` eficiente, nada bloqueante en el event loop.
  - ``nStep`` se incrementa de 10 en 10 (10, 20, 30, ...) para que
    los logs sean faciles de leer.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any, ClassVar, Optional, Protocol

# ============================================================================
#  Data Block trasversal: estado de la conexion con TIA Portal
# ============================================================================


@dataclass
class DB_EstadoConexion:
    """Estado compartido de la conexion con el worker TIA.

    Trasversal: la usan TODOS los FBs que necesiten saber si TIA
    Portal esta conectado. Vive en este modulo por convencion
    (ver AGENTS.md §2).

    Atributos:
        worker_alive: ``True`` si el subproceso del worker esta vivo.
            El bridge lo actualiza tras un ``ping`` exitoso.
        tia_state: uno de ``"idle" | "connecting" | "connected" | "error"``.
            El FB ``FB_ConexionTIA`` lo transita; el HMI lo pinta.
        project_name: nombre del proyecto TIA abierto (vacio si
            no hay proyecto o no hay conexion).
        project_path: ruta completa al ``.apXX`` del proyecto abierto.
        plcs: lista de PLCs del proyecto (cada elemento es un dict
            primitivo devuelto por el worker).
        last_error: ultimo mensaje de error relevante para el operario.
            Vacio si no hay error.
        last_ping_ok_unix: timestamp ``time.time()`` del ultimo
            ``ping`` exitoso contra el worker. ``0.0`` si nunca
            se ha hecho ping.
    """

    worker_alive: bool = False
    tia_state: str = "idle"
    project_name: str = ""
    project_path: str = ""
    plcs: list = field(default_factory=list)
    last_error: str = ""
    last_ping_ok_unix: float = 0.0


# Singleton a nivel de modulo. La convencion del proyecto es
# que el estado trasversal del PLC es global (single-tenant,
# .clinerules §11). Las areas pueden tener DBs adicionales en
# ``areas/<area>/plc/data.py``.
DB_ESTADO = DB_EstadoConexion()


# ============================================================================
#  WorkerBridge: Protocol que define el contrato con la fachada
# ============================================================================
#
# El contrato se ha ajustado al WorkerBridge real implementado en
# ``core/worker/worker_bridge.py`` por el agente ``tia-ot-worker``
# (rama paralela, mismo branch). Los puntos clave:
#   - ``attach()`` es async y acepta ``portal_mode`` (default "Primary").
#   - ``detach()`` es async (idempotente).
#   - ``list_plcs()`` devuelve ``list[dict]`` (no dict con claves
#     ``plcs``/``project_name``/``project_path``; el project info
#     viene de ``get_project_info()`` por separado).
#   - ``start()`` y ``shutdown()`` son async; gestionan el subproceso
#     del worker.
#
# Cualquier clase que implemente estos metodos sirve. La implementacion
# real es ``core.worker.worker_bridge.WorkerBridge``; este modulo aporta
# un ``MockWorkerBridge`` para tests y para la Fase 1 (cuando el
# orquestador integre el bridge real en un commit posterior, el
# lifespan cambiara de ``MockWorkerBridge()`` a ``WorkerBridge()``).


class WorkerBridgeProtocol(Protocol):
    """Contrato minimo que la fachada ``WorkerBridge`` debe cumplir.

    Cualquier clase con estos metodos sirve. Lo implementan:
      - ``core.worker.worker_bridge.WorkerBridge`` (real, escrito por
        el agente ``tia-ot-worker``).
      - ``MockWorkerBridge`` en este modulo (para tests + Fase 1).
    """

    async def start(self) -> None:
        """Lanza el subproceso del worker. Idempotente."""
        ...

    async def shutdown(self) -> None:
        """Cierra el subproceso del worker y libera el ``.pyd`` de
        Siemens (leccion X2). Idempotente."""
        ...

    async def attach(self, portal_mode: str = "Primary") -> int:
        """Attach a una instancia YA en ejecucion de TIA Portal.
        ``ts.attach_portal()`` NO lanza TIA Portal.

        Returns:
            PID de TIA Portal al que se hizo attach.

        Raises:
            WorkerCommandError: si TIA no esta en ejecucion.
        """
        ...

    async def detach(self) -> None:
        """Detach del portal attached. Idempotente."""
        ...

    async def list_plcs(self) -> list[dict]:
        """Lista los PLCs del proyecto activo. ``list[dict]`` con
        primitivos (sin objetos .NET)."""
        ...

    async def get_project_info(self) -> dict:
        """Propiedades del proyecto activo. ``dict`` con al menos
        ``name`` y ``path``."""
        ...


# ============================================================================
#  MockWorkerBridge: implementacion en memoria para tests + Fase 1
# ============================================================================


class MockWorkerBridge:
    """Implementacion en memoria del ``WorkerBridgeProtocol``.

    Se usa en:
      1. **Tests**: permite ejercitar la logica del Engine y de los
         FBs sin tener TIA Portal abierto. Es lo que el ``lifespan``
         de FastAPI instancia durante Fase 1 (mientras el orquestador
         no integre el bridge real en un commit posterior).
      2. **Smoke tests locales**: para verificar que el HMI arranca
         sin necesidad de TIA Portal.

    Comportamiento:
      - ``start()`` / ``shutdown()`` son no-ops idempotentes.
      - ``attach()`` marca ``attached=True`` y devuelve un PID falso.
      - ``list_plcs()`` devuelve una lista vacia.
      - ``get_project_info()`` devuelve un dict vacio.
      - ``detach()`` marca ``attached=False``.

    Si los tests necesitan respuestas concretas, pueden monkey-patch
    los metodos con ``unittest.mock.AsyncMock``.
    """

    def __init__(self) -> None:
        self.attached: bool = False
        self.fake_pid: int = 99999
        self.fake_plcs: list[dict] = []
        self.fake_project_info: dict = {
            "name": "ProyectoMock",
            "path": "C:/mock/proj.ap17",
        }
        self.start_count: int = 0
        self.shutdown_count: int = 0
        self.detach_count: int = 0

    async def start(self) -> None:
        self.start_count += 1

    async def shutdown(self) -> None:
        self.shutdown_count += 1

    async def attach(self, portal_mode: str = "Primary") -> int:
        self.attached = True
        return self.fake_pid

    async def detach(self) -> None:
        self.detach_count += 1
        self.attached = False

    async def list_plcs(self) -> list[dict]:
        return list(self.fake_plcs)  # copia defensiva

    async def get_project_info(self) -> dict:
        return dict(self.fake_project_info)  # copia defensiva


# ============================================================================
#  FB_Base: clase base para todos los Function Blocks
# ============================================================================


class FB_Base:
    """Clase base de los Function Blocks (modelo IEC 61131-3).

    Atributos publicos:
        nombre: nombre del FB. Lo asigna la subclase o el Engine al
            registrarlo. Se usa como clave en el snapshot/SSE.
        nStep: etapa actual del state machine. ``0`` = idle,
            ``n_done`` (override) = done, ``n_error`` (clase) = 99 = error.
        nError: codigo de error (``0`` = sin error).
        error_msg: mensaje legible del ultimo error.
        progress: 0..100, lo pinta el HMI como barra de progreso.
        step_name: descripcion humana de la etapa actual (para logs y UI).
        result: payload opcional al terminal ``n_done``.

    Convenciones de las subclases:
      - Override ``n_done`` con la etapa terminal OK (ej. ``n_done = 30``).
      - ``n_error = 99`` viene de la base; no cambiar.
      - Implementar ``start(**params)`` solo si necesita capturar params
        (llamar ``super().start(**params)`` para que la base resetee
        el state machine). Por defecto la base ya resetea.
      - Implementar ``async def tick(self) -> None`` con la logica del
        state machine. Si lanza excepcion, la base la captura y pone
        ``nError=1, nStep=99``.

    Ciclo de vida:
      1. Operario llama ``POST /plc/fb/{nombre}/start`` -> router llama
         ``fb.start(**params)`` (sincrono, idempotente).
      2. ``start()`` resetea a ``nStep=10`` (primera etapa) y guarda
         params en ``self._params``.
      3. Engine tickea el FB cada 100 ms mientras ``nStep not in
         (0, n_done, n_error)``. Publica al SSE en cada cambio de
         ``nStep``.
      4. ``tick()`` avanza etapas hasta ``n_done`` o ``n_error``.
    """

    # Etapas terminales. Las subclases overridean ``n_done`` con el
    # valor que tenga sentido (ej. 30 si la ultima etapa es 20).
    n_done: ClassVar[int] = 0
    # Codigo de error. Por convencion del proyecto, siempre 99.
    n_error: ClassVar[int] = 99

    def __init__(self, nombre: str) -> None:
        self.nombre: str = nombre
        self.nStep: int = 0
        self.nError: int = 0
        self.error_msg: str = ""
        self.progress: int = 0
        self.step_name: str = ""
        self.result: Any = None
        # Params de la ultima llamada a ``start()``. Las subclases
        # los leen en ``tick()``. La base solo los guarda.
        self._params: dict = {}

    def start(self, **params: Any) -> None:
        """Arranca el FB. **Sincrono e idempotente.**

        Args:
            **params: parametros del FB. Se guardan en ``self._params``
                y se entregan a ``_on_start(**params)`` para que la
                subclase los procese si lo necesita.

        Comportamiento:
          - Si ``nStep`` ya esta en una etapa activa (no idle, no
            done, no error), la llamada se ignora (idempotencia).
            Esto evita que doble-clics del operario en "Conectar"
            arranquen el FB dos veces.
          - Si no, resetea ``nStep=10``, ``nError=0``, ``error_msg=""``,
            ``progress=0``, ``step_name=""``, ``result=None`` y llama
            a ``_on_start(**params)`` (hook que las subclases pueden
            overridear para capturar params).
        """
        # Idempotencia: si ya esta corriendo, ignorar.
        if self.nStep not in (0, self.n_done, self.n_error):
            return
        # Reset completo del state machine.
        self.nStep = 10
        self.nError = 0
        self.error_msg = ""
        self.progress = 0
        self.step_name = ""
        self.result = None
        self._params = dict(params)
        # Hook privado: las subclases capturan params aqui.
        self._on_start(**params)

    def _on_start(self, **params: Any) -> None:
        """Hook privado que las subclases overridean para capturar params.

        Por defecto no hace nada. La base no impone la firma; la
        subclase pone los campos que necesite. Se invoca UNA vez por
        cada ``start()`` que no se ignora por idempotencia.
        """

    def get_state(self) -> dict:
        """Snapshot del estado del FB para enviar por SSE.

        Returns:
            ``dict`` con todos los campos publicos relevantes. El
            campo ``name`` se incluye para que el HMI pueda
            identificar el FB sin necesidad de conocer la clave
            del dict en el snapshot.
        """
        state: dict = {
            "name": self.nombre,
            "nStep": self.nStep,
            "nError": self.nError,
            "error": self.error_msg,
            "progress": self.progress,
            "step_name": self.step_name,
        }
        # Si esta en estado terminal OK, exponer el result.
        if self.nStep == self.n_done:
            state["type"] = "done"
            state["result"] = self.result
        elif self.nStep == self.n_error:
            state["type"] = "error"
        else:
            state["type"] = "fb"
        return state

    async def tick(self) -> None:
        """Logica del state machine. Abstracto: lo implementa la subclase.

        Raises:
            NotImplementedError: si la subclase no lo overridea.
        """
        raise NotImplementedError(
            f"FB '{self.nombre}' no implementa tick()"
        )


# ============================================================================
#  FB_ConexionTIA: el unico FB trasversal de Fase 1
# ============================================================================


class FB_ConexionTIA(FB_Base):
    """FB trasversal: conecta con TIA Portal y lista los PLCs del proyecto.

    State machine:
        nStep=10 -> ``await self.bridge.attach()``. Si OK, transita
            a ``nStep=20``, ``progress=50``, ``step_name="Listando..."``.
        nStep=20 -> ``await self.bridge.list_plcs()`` y
            ``await self.bridge.get_project_info()`` (este ultimo
            best-effort: si falla, los campos del proyecto quedan
            vacios en la DB pero el FB no se rompe). Si OK, escribe
            ``db.plcs``, ``db.project_name``, ``db.project_path``,
            transita a ``nStep=30`` (done), ``progress=100``.

        nStep=30 (n_done) -> terminal OK.
        nStep=99 (n_error) -> cualquier fallo en un ``await``;
            ``self.db.last_error`` se actualiza con el mensaje.

    Args:
        bridge: fachada ``WorkerBridgeProtocol``. Cumple el contrato
            definido arriba (mock o real).
        db: instancia de ``DB_EstadoConexion``. Se actualiza
            in-place a medida que el FB transita etapas.
    """

    # Etapa terminal OK. El FB tiene 2 etapas (10, 20), asi que el
    # done cae en 30 por convencion de "incrementos de 10".
    n_done: ClassVar[int] = 30

    def __init__(
        self,
        bridge: WorkerBridgeProtocol,
        db: DB_EstadoConexion,
    ) -> None:
        super().__init__(nombre="ConexionTIA")
        self.bridge: WorkerBridgeProtocol = bridge
        self.db: DB_EstadoConexion = db

    async def tick(self) -> None:
        """Avanza una etapa del state machine. El Engine lo llama
        cada 100 ms mientras ``nStep`` este en etapa activa.

        Si cualquier ``await`` lanza excepcion, se captura y se
        transita a ``nStep=99`` con ``nError=1`` y
        ``self.db.tia_state="error"``.
        """
        try:
            if self.nStep == 10:
                self.db.tia_state = "connecting"
                self.step_name = "Conectando con TIA"
                # ``attach`` toma ``portal_mode`` opcional (default
                # "Primary" en el bridge real). No necesitamos el
                # PID que retorna; el bridge ya actualiza su estado
                # interno de doble-checked locking.
                await self.bridge.attach()
                self.nStep = 20
                self.progress = 50
            elif self.nStep == 20:
                self.step_name = "Listando PLCs"
                plcs = await self.bridge.list_plcs()
                # ``plcs`` es ``list[dict]`` segun el contrato.
                # Defensive copy por si el bridge reusa la lista.
                self.db.plcs = list(plcs)
                # ``get_project_info`` es best-effort: si el worker
                # no lo implementa todavia, capturamos y seguimos
                # con los PLCs (que es lo minimo util para el HMI).
                try:
                    info = await self.bridge.get_project_info()
                except Exception:
                    info = {}
                self.db.project_name = str(info.get("name", ""))
                self.db.project_path = str(info.get("path", ""))
                self.db.tia_state = "connected"
                self.nStep = 30
                self.progress = 100
            # nStep=30 (done) es terminal; el Engine lo skipea.
        except Exception as exc:  # noqa: BLE001 - capturamos todo
            # Cualquier fallo del worker (TIA cerrado, proyecto no
            # abierto, timeout, ...) cae aqui. Marcamos el FB en
            # error terminal y dejamos la DB en estado consistente.
            self.nError = 1
            self.error_msg = str(exc)
            self.nStep = self.n_error
            self.db.tia_state = "error"
            self.db.last_error = str(exc)

    async def disconnect(self) -> None:
        """Desconecta del worker. **Async.** Lo llama el router
        cuando el operario pulsa "Desconectar" (o equivalente).

        Comportamiento:
          - Si el FB esta en ``n_done`` (30), llama a
            ``await self.bridge.detach()`` y resetea estado + DB.
          - Si el FB esta en otro estado (idle, error, en curso),
            se ignora: ``detach()`` sigue siendo idempotente
            desde el lado del bridge, pero el FB no resetea su
            estado (para no perder el diagnostico del error).
        """
        # Solo reseteamos si estabamos en estado terminal OK.
        # En cualquier otro caso, el bridge.detach() es idempotente
        # y seguro de llamar, pero el FB mantiene su estado para
        # que el HMI pueda mostrar el error o el progreso.
        if self.nStep == self.n_done:
            await self.bridge.detach()
            self.nStep = 0
            self.progress = 0
            self.step_name = ""
            self.result = None
            self.db.tia_state = "idle"
            self.db.plcs = []
            self.db.project_name = ""
            self.db.project_path = ""


# ============================================================================
#  Engine: el OB1 (loop de 100 ms, bus SSE, registro de FBs/DBs)
# ============================================================================


def _dataclass_to_dict(obj: Any) -> Any:
    """Convierte recursivamente dataclasses a ``dict``.

    Maneja dataclasses, ``list`` y ``dict`` anidados. Para todo lo
    demas, devuelve el valor tal cual. Esto permite que el snapshot
    del Engine se serialice a JSON sin sorpresas.

    Args:
        obj: cualquier valor. Si es dataclass, se convierte a
            ``{field_name: recurse(field_value)}``. Si es ``list``
            o ``tuple``, se mapea elemento a elemento. Si es ``dict``,
            se mapea valor a valor. Otro caso: identidad.

    Returns:
        Version ``dict``/``list``/``primitivo`` del objeto.
    """
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {
            f.name: _dataclass_to_dict(getattr(obj, f.name))
            for f in dataclasses.fields(obj)
        }
    if isinstance(obj, list):
        return [_dataclass_to_dict(x) for x in obj]
    if isinstance(obj, tuple):
        return tuple(_dataclass_to_dict(x) for x in obj)
    if isinstance(obj, dict):
        return {k: _dataclass_to_dict(v) for k, v in obj.items()}
    return obj


class Engine:
    """El OB1: loop asyncio de 100 ms que tickea FBs y alimenta el SSE.

    Atributos:
        fbs: dict ``{nombre: FB_Base}`` de FBs registrados.
        dbs: dict ``{nombre: object}`` de DBs registrados. La
            ``DB_EstadoConexion`` trasversal siempre esta presente
            bajo la clave ``"estado_conexion"``.
        db_estado: referencia directa a la ``DB_EstadoConexion``
            trasversal. Atajo para FBs que la necesitan; el
            ``register_db`` la pone tambien en ``self.dbs``.

    Constantes:
        TICK_INTERVAL: periodo del loop en segundos (``0.1`` = 100 ms).
            Verificado contra ``.clinerules`` §5: el operario
            percibe ``progress`` actualizandose ~10 veces/segundo,
            suficiente para una barra de progreso fluida.

    Ciclo de vida:
        1. ``core/web/app.py::lifespan`` (startup) llama
           ``ENGINE.start_loop()``.
        2. La task asyncio tickea todos los FBs cada 100 ms.
        3. Los routers usan ``subscribe()`` / ``unsubscribe()``
           para conectarse al bus SSE.
        4. ``lifespan`` (shutdown) llama ``cancel()`` sobre
           ``self._task`` para parar el loop limpiamente.
    """

    TICK_INTERVAL: ClassVar[float] = 0.1

    def __init__(self) -> None:
        self.fbs: dict[str, FB_Base] = {}
        self.dbs: dict[str, object] = {}
        self.db_estado: DB_EstadoConexion = DB_ESTADO
        # ``self.dbs["estado_conexion"]`` se rellena en ``register_db``
        # para que el snapshot lo incluya (atajo + composicion).
        self._subs: set[asyncio.Queue] = set()
        self._task: asyncio.Task | None = None
        self._stopped: bool = False

    # ── Registro de FBs y DBs ────────────────────────────────────────

    def register_fb(self, name: str, fb: FB_Base) -> None:
        """Registra un FB en el Engine.

        Si ya hay un FB con ese nombre, lo SOBREESCRIBE sin aviso
        (util en tests para reemplazar FBs; en produccion los nombres
        son unicos por convencion del proyecto).
        """
        self.fbs[name] = fb

    def register_db(self, name: str, db: object) -> None:
        """Registra una DB (Data Block) en el Engine.

        La ``DB_EstadoConexion`` trasversal se registra bajo
        ``"estado_conexion"``; las areas registran las suyas en
        ``areas/<area>/plc/__init__.py::register_plc``.
        """
        self.dbs[name] = db
        # Si es la DB_EstadoConexion, tambien la exponemos como
        # ``self.db_estado`` para acceso directo desde FBs/routers.
        if isinstance(db, DB_EstadoConexion):
            self.db_estado = db

    # ── Loop principal ────────────────────────────────────────────────

    def start_loop(self) -> None:
        """Arranca la task asyncio del loop. **No-op si ya esta
        arrancada o parada.** Idempotente para soportar reinicios
        en tests.
        """
        if self._task is not None and not self._task.done():
            return
        self._stopped = False
        self._task = asyncio.create_task(self._loop(), name="plc-engine-loop")

    async def stop_loop(self) -> None:
        """Para el loop limpiamente. Espera a que la task termine.

        Llamado desde el ``lifespan`` de FastAPI al apagar la app.
        Tras esto, ``start_loop()`` puede volver a arrancarlo.
        """
        self._stopped = True
        if self._task is None:
            return
        if not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                # Cancelado o ya cerrado: ambos son fine.
                pass
        self._task = None

    async def _loop(self) -> None:
        """Loop principal. Dura lo que viva la app."""
        try:
            while not self._stopped:
                await asyncio.sleep(self.TICK_INTERVAL)
                await self._tick_all()
        except asyncio.CancelledError:
            # Shutdown normal; subimos la cancelacion para que
            # ``stop_loop()`` la vea y complete limpiamente.
            raise
        except Exception:  # noqa: BLE001
            # Bug nuestro: el loop no debe morir por un error en
            # un FB individual (los FBs ya capturan sus excepciones).
            # Si llegamos aqui, algo del propio Engine fallo; lo
            # dejamos propagar para que el lifespan lo registre.
            raise

    async def _tick_all(self) -> None:
        """Ejecuta un tick sobre todos los FBs registrados.

        Extraido de ``_loop()`` para que los tests puedan ejercitar
        un unico ciclo sin esperar 100 ms. **No** es parte del
        contrato publico; el Engine expone ``start_loop()`` /
        ``stop_loop()`` para produccion.
        """
        for fb in list(self.fbs.values()):
            # Skip terminales: idle (0), done, error. Ver tests de
            # ``test_engine.py`` y ``test_fb_base.py``.
            if fb.nStep in (0, fb.n_done, fb.n_error):
                continue
            prev_step = fb.nStep
            try:
                await fb.tick()
            except Exception as exc:  # noqa: BLE001 - defensivo
                # La base del FB ya captura excepciones en ``tick()``,
                # pero si una subclase olvida hacerlo, no dejamos que
                # el loop se caiga.
                fb.nError = 1
                fb.error_msg = str(exc)
                fb.nStep = fb.n_error
            if fb.nStep != prev_step:
                self._publish_fb_state(fb)

    # ── Bus SSE ───────────────────────────────────────────────────────

    def subscribe(self) -> asyncio.Queue:
        """Crea una ``asyncio.Queue`` y la suscribe al bus de eventos.

        Cada suscriptor tiene su propia cola (``maxsize=200``). Si
        un suscriptor es lento, los eventos se descartan (no
        bloqueamos al Engine). Ver ``.clinerules`` §6.

        Returns:
            La cola. Pasarla a ``unsubscribe()`` al cerrar la
            conexion SSE.
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Desuscribe una cola. **Idempotente** (silencioso si la
        cola no estaba suscrita). Lo llama el ``try/finally`` del
        generador SSE al cerrar la conexion.
        """
        self._subs.discard(q)

    def _publish_fb_state(self, fb: FB_Base) -> None:
        """Publica el estado de un FB a todos los suscriptores.

        Itera ``list(self._subs)`` para evitar problemas si un
        suscriptor se desuscribe durante la iteracion. Las colas
        llenas se descartan silenciosamente con ``put_nowait``
        + ``QueueFull`` capturado.

        El payload es ``fb.get_state()`` con un campo ``name``
        anadido por ``get_state()``. Si el FB esta en done, el
        payload ya lleva ``"type": "done", "result": ...``; si
        esta en error, lleva ``"type": "error"``.
        """
        # Copia defensiva: si una suscripcion se cierra mientras
        # publicamos, no queremos mutar el set durante la
        # iteracion.
        payload = fb.get_state()
        for q in list(self._subs):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                # Suscriptor lento: descartar el evento. Es la
                # politica documentada en .clinerules §6.
                pass

    def _publish_raw(self, payload: dict) -> None:
        """Publica un evento arbitrario (ej. snapshot inicial).

        Misma politica de ``QueueFull`` que ``_publish_fb_state``.
        Usado por el router SSE al enviar el snapshot.
        """
        for q in list(self._subs):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    # ── Snapshot ──────────────────────────────────────────────────────

    def get_snapshot(self) -> dict:
        """Snapshot completo del estado del Engine para el SSE inicial.

        Returns:
            ``dict`` con:
              - ``"type": "snapshot"``
              - ``"dbs"``: ``{nombre: dataclass_to_dict(db)}``
              - ``"fbs"``: ``{nombre: fb.get_state()}``

            Se serializa a JSON en el router con ``json.dumps``.
        """
        return {
            "type": "snapshot",
            "dbs": {
                name: _dataclass_to_dict(db)
                for name, db in self.dbs.items()
            },
            "fbs": {
                name: fb.get_state()
                for name, fb in self.fbs.items()
            },
        }


# Singleton a nivel de modulo. La convencion del proyecto es que
# el Engine es global (single-tenant, .clinerules §11). El ``lifespan``
# de FastAPI arranca su loop al startup y lo para al shutdown.
ENGINE = Engine()

# Registramos la DB trasversal en el singleton. La convencion del
# proyecto es que la clave es ``"estado_conexion"``; cualquier FB
# o router que necesite la DB la lee de ``ENGINE.dbs[...]`` o
# ``ENGINE.db_estado`` (atajo).
ENGINE.register_db("estado_conexion", DB_ESTADO)


# ============================================================================
#  Helpers publicos
# ============================================================================


def snapshot_to_json_bytes(snapshot: dict) -> bytes:
    """Serializa un snapshot a bytes UTF-8 con formato SSE.

    Args:
        snapshot: dict (tipicamente ``Engine.get_snapshot()`` o
            el payload de ``_publish_fb_state``).

    Returns:
        ``b'data: {json}\\n\\n'`` listo para yield en el generador
        SSE. Usar ``json.dumps(..., ensure_ascii=False)`` para
        no romper acentos en mensajes de error.
    """
    return f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n".encode()


async def sse_event_stream(
    engine: Engine,
    max_events: int = 0,
) -> AsyncGenerator[bytes, None]:
    """Generador SSE reutilizable: snapshot inicial + stream de eventos.

    Args:
        engine: del que tomamos el snapshot y al que nos suscribimos.
        max_events: si ``> 0``, cierra el stream tras emitir ese
            numero de eventos (modo test). ``0`` = infinito (modo
            produccion). El snapshot inicial cuenta como 1.

    Yields:
        Chunks ``bytes`` formateados como ``data: {json}\\n\\n``.
    """
    q = engine.subscribe()
    try:
        # Snapshot inicial (cuenta como 1 evento si ``max_events > 0``).
        yield snapshot_to_json_bytes(engine.get_snapshot())
        if max_events > 0:
            return
        # Stream: bloqueamos esperando el siguiente evento. Si el
        # cliente cierra la conexion, el ``finally`` desuscribe.
        while True:
            event = await q.get()
            yield snapshot_to_json_bytes(event)
            if max_events > 0:
                # Por si el caller quiere contar tambien los
                # eventos del stream (no usado en Fase 1; el
                # snapshot ya cubre el caso test).
                return
    finally:
        engine.unsubscribe(q)
