"""Function Base con progress_tracker integrado, steps declarativos y timeout.

State machine discreto ``nStep`` con tolerancia best-effort. Cada FB
es un orquestador de una operacion del operario contra TIA Portal (subir
excel, escanear bloques, sincronizar dispositivos, etc.).

A diferencia de un FB "pelado", este base lleva integrado el HMI
(progress_tracker): begin al arrancar, start/finish/error por cada
step, finish al cerrar. Las subclases solo aportan declaracion
estatica de steps y la logica de cada step.

State machine::

    nStep=0   idle      (FB creado, sin start)
    nStep=10  arrancar  (on_start + tracker.begin)
    nStep=20  ejecutar  (loop de steps: start_stage -> run_step -> finish/error)
    nStep=95  finalizar (on_finish + tracker.finish(success=True))
    nStep=99  done      (terminal OK, el engine NO tickea mas)
    nStep=98  error     (terminal con error_msg, el engine NO tickea mas)

Dos caminos de ejecucion (ver ``execute`` y ``tick``):

  - ``execute(**params)`` (SINC, via nueva): el hilo ejecutor del OB1
    llama al FB y espera a que termine. Es el camino que usa el worker
    TIA, que es bloqueante por naturaleza.
  - ``start()`` / ``tick()`` (ASYNC, via legacy): el engine tickea el FB
    un step por invocacion. Se mantiene durante la migracion y desaparece
    cuando el engine pasa a ser un OB1 con cola de trabajos.

Hooks overridables por las subclases (FBs reales):
  - ``on_start(**params)``         pre-flight SYNC. Validar params.
  - ``run_step(idx, **params)``    logica del step N.
  - ``on_finish(**params)``        post-flight SYNC. Vuelca self.result.

Cancelacion cooperativa: ``cancel(reason)`` marca un flag; el step en
curso lo comprueba en la frontera de etapa y el base cierra con
``tracker.finish(success=False)`` + ``nStep = n_error``.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import threading
import time
import traceback
from collections.abc import Callable
from typing import Any

from core.runtime.progress_buffer import ProgressTracker, get_progress_tracker

logger = logging.getLogger(__name__)


class FunctionBase:
    """FB base con HMI (progress_tracker) integrado y cancel cooperativo."""

    # Constantes de estado a nivel de clase: las subclases y el engine
    # las referencian sin necesidad de instanciar.
    n_idle: int = 0
    n_arrancar: int = 10
    n_ejecutar: int = 20
    n_finalizar: int = 95
    n_done: int = 99
    n_error: int = 98

    # Timeout por defecto por step (segundos). Las subclases pueden
    # overridear si su logica lo requiere (p. ej. I/O de red).
    STEP_TIMEOUT_S: float = 300.0

    def __init__(
        self,
        nombre: str,
        titulo: str,
        steps: list[dict[str, Any]],
        tracker: ProgressTracker | None = None,
        step_timeout_s: float | None = None,
    ) -> None:
        self.nombre = nombre
        self.titulo = titulo
        # Normaliza a list[dict]. Acepta strings por ergonomia (los
        # FBs simples no necesitan dicts), pero la representacion
        # interna siempre es dict para admitir metadata futura
        # (descripcion, timeout propio, etc.).
        self.steps: list[dict[str, Any]] = [
            s if isinstance(s, dict) else {"nombre": s}
            for s in steps
        ]
        # Tracker: inyeccion obligatoria en FBs reales. Default al
        # singleton global solo para tests basicos y smoke (mismo
        # patron que LogBuffer).
        self._tracker = tracker if tracker is not None else get_progress_tracker()
        self._step_timeout_s = (
            step_timeout_s if step_timeout_s is not None else self.STEP_TIMEOUT_S
        )
        self._step_idx: int = 0
        # ``asyncio.Lock`` se ata al event loop en su primer uso. Como el
        # camino legacy sobrevive entre invocaciones efimeras (el engine
        # crea un ``asyncio.run()`` por ciclo y los routers hacen
        # ``asyncio.run(fb.start())`` desde hilos de Flask), el loop
        # cambia en cada invocacion y el primitive del loop anterior
        # dispara "bound to a different event loop".
        # ``_ensure_loop_objects()`` lo recrea perezosamente al inicio de
        # cada entry point async.
        self._loop: asyncio.AbstractEventLoop | None = None
        # Flag de cancelacion: ``threading.Event`` (no asyncio) para que
        # ``cancel()`` desde un hilo de Flask lo active de forma segura
        # mientras el hilo ejecutor esta dentro de un step.
        self._cancelled = threading.Event()

        # Estado publico del FB (mismo shape que antes para compatibilidad
        # con publishers SSE y endpoints REST).
        self.nStep: int = self.n_idle
        self.error_msg: str | None = None
        self.result: Any = None
        self._params: dict[str, Any] = {}
        # Estado entre ticks: dict ``{step_nombre: stats}`` que cada
        # step rellena con info util (contadores, paths, etc.) y que
        # ``on_finish`` consulta para construir ``self.result``.
        self._stats: dict[str, Any] = {}
        self._lock = asyncio.Lock()
        # Exclusion mutua entre los dos caminos de ejecucion: el legacy
        # (``tick()``, engine) y el nuevo (``execute()``, OB1). Sin esto,
        # un FB registrado en el engine podia ser tickeado mientras el
        # OB1 lo ejecutaba: el step corria dos veces y el FB se quedaba
        # en un estado incoherente (n_finalizar, no terminal).
        self._exec_lock = threading.Lock()
        # Hook opcional: invocado tras cada cambio de nStep con
        # (old_nStep, new_nStep). No-op si None. Lo cablea publishers
        # para retransmitir fb_state al bus SSE.
        self._on_nstep_change: Callable[[int, int], None] | None = None

    # ------------------------------------------------------------------
    # Hooks overridables (los FBs reales solo aportan estos)
    # ------------------------------------------------------------------

    def on_start(self, **params: Any) -> None:
        """Pre-flight SYNC. Validar params, preparar estado interno.

        Lanzar ``ValueError`` si falta algun param obligatorio; el
        ``execute()`` lo captura y transiciona a ``n_error`` con
        ``tracker.error_stage(...)``. Default: no-op.
        """
        pass

    async def run_step(self, idx: int, **params: Any) -> str:
        """Logica del step ``idx``. Devuelve un detail (string) para el HMI.

        Default: ``NotImplementedError`` (la subclase olvido overridear).
        Lanzar cualquier excepcion aborta el step actual; el base
        emite ``tracker.error_stage(...)`` y transiciona a ``n_error``.
        """
        raise NotImplementedError(
            f"FB {self.nombre}: run_step() debe ser implementado por la subclase"
        )

    def on_finish(self, **params: Any) -> None:
        """Post-flight SYNC. Vuelca ``self.result`` con la shape que
        el caller espera. Default: ``{"ok": True}``.
        """
        self.result = {"ok": True}

    # ------------------------------------------------------------------
    # Estado y notificacion
    # ------------------------------------------------------------------

    def _notify_nstep_change(self, old: int, new: int) -> None:
        """Dispara el hook si nStep cambio. Llamar tras cualquier mutacion."""
        if self._on_nstep_change is not None and old != new:
            self._on_nstep_change(old, new)

    def is_terminal(self) -> bool:
        """``True`` si el FB esta en estado terminal y NO debe tickearse."""
        return self.nStep in (self.n_idle, self.n_done, self.n_error)

    def _ensure_loop_objects(self) -> None:
        """(Re)crea ``_lock`` si el event loop cambio.

        Los primitives de asyncio (``Lock``) se atan al loop en su
        primer ``acquire()``. Cuando el FB sobrevive entre llamadas
        efimeras -- el engine legacy crea un ``asyncio.run()`` por
        ciclo, y los routers hacen ``asyncio.run(fb.start())`` desde
        hilos de Flask -- el loop cambia en cada invocacion y el
        primitive del loop anterior dispara ``RuntimeError: ... is
        bound to a different event loop``. Recrearlo aqui (solo si el
        loop cambio) resuelve el binding sin pagar el coste cuando el
        loop es estable.

        El flag ``_cancelled`` NO se recrea: es un ``threading.Event``
        y su estado debe sobrevivir entre llamadas (un ``cancel()``
        desde el hilo de Flask tiene que ser visto por el hilo
        ejecutor).
        """
        current = asyncio.get_running_loop()
        if self._loop is not current:
            self._loop = current
            self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Reset del estado por-llamada
    # ------------------------------------------------------------------

    def _reset_state_for_run(self, params: dict[str, Any]) -> None:
        """Limpia el estado por-llamada.

        Se mantiene la identidad del FB (Zona 0, deps inyectadas,
        ``_tracker``, ``_on_nstep_change``); solo se reinician los
        datos de la ejecucion en curso.
        """
        self._stats.clear()
        self._params = dict(params)
        self.error_msg = None
        self.result = None
        self._step_idx = 0
        self._cancelled.clear()

    def _fail_with(self, exc: BaseException, contexto: str) -> None:
        """Fija ``error_msg``, cierra el tracker y transiciona a ``n_error``.

        Asume que el caller ya ha capturado la excepcion. El traceback
        se manda tanto al log de Python (debugging offline) como a la
        consola web de la SPA (el operario lo ve en vivo).
        """
        tb_str = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ).rstrip()
        logger.exception(
            "FB %s: error en %s (nStep=%d) -- %s: %s",
            self.nombre, contexto, self.nStep, type(exc).__name__, exc,
        )
        logger.error(
            f"[{self.nombre}] ERROR en {contexto} "
            f"(nStep={self.nStep}): {type(exc).__name__}: {exc}\n"
            f"{tb_str}"
        )
        self.error_msg = f"{type(exc).__name__}: {exc}"
        self._close_tracker_on_error()
        self.nStep = self.n_error

    # ------------------------------------------------------------------
    # Camino NUEVO: execute() (sync, hilo del OB1)
    # ------------------------------------------------------------------

    def execute(self, **params: Any) -> Any:
        """Ejecuta el FB completo de principio a fin (SINC).

        Entry point del OB1: el hilo que ejecuta el trabajo llama a este
        metodo y espera a que termine. Devuelve ``self.result``.

        No propaga excepciones de runtime: captura la excepcion, fija
        ``error_msg``, cierra el tracker con ``success=False`` y
        transiciona a ``n_error`` (mismo contrato que ``tick()``).
        ``NotImplementedError`` y ``AssertionError`` si propagan
        (errores de programacion, no se silencian), pero el FB queda
        en estado terminal para que no se re-intente en bucle.

        Si el FB ya esta activo, o hay otra ejecucion en curso, no hace
        nada y devuelve ``self.result`` tal cual.
        """
        if not self._exec_lock.acquire(blocking=False):
            logger.warning(
                "FB %s: execute() ignorado, ya hay una ejecucion en curso",
                self.nombre,
            )
            return self.result
        try:
            return self._execute_locked(**params)
        finally:
            self._exec_lock.release()

    def _execute_locked(self, **params: Any) -> Any:
        """Cuerpo de ``execute()``. Asume ``self._exec_lock`` cogido."""
        if not self.is_terminal():
            logger.warning(
                "FB %s: execute() ignorado, FB activo (nStep=%d)",
                self.nombre, self.nStep,
            )
            return self.result

        self._reset_state_for_run(params)
        n_before = self.nStep
        self.nStep = self.n_arrancar
        logger.info("FB %s: execute() OK (nStep=%d)", self.nombre, self.nStep)
        self._notify_nstep_change(n_before, self.nStep)

        try:
            before = self.nStep
            self._step_arrancar()
            self._notify_nstep_change(before, self.nStep)

            while self.nStep == self.n_ejecutar:
                before = self.nStep
                self._step_ejecutar_sync()
                self._notify_nstep_change(before, self.nStep)

            # Si el FB fue cancelado, ``nStep`` es ``n_error`` y no se
            # finaliza: el tracker ya se cerro con success=False.
            if self.nStep == self.n_finalizar:
                before = self.nStep
                self._step_finalizar()
                self._notify_nstep_change(before, self.nStep)
        except (NotImplementedError, AssertionError) as e:
            # Error de programacion: se propaga para que el dev lo vea
            # claro, pero el FB NO se queda en n_ejecutar (bricked, se
            # re-intentaria en bucle). Se marca terminal.
            self.error_msg = f"{type(e).__name__}: {e}"
            before = self.nStep
            self._close_tracker_on_error()
            self.nStep = self.n_error
            self._notify_nstep_change(before, self.nStep)
            raise
        except Exception as e:
            before = self.nStep
            self._fail_with(e, "execute()")
            self._notify_nstep_change(before, self.nStep)

        return self.result

    def _step_ejecutar_sync(self) -> None:
        """nStep 20 (sync): ejecuta el step ``_step_idx`` o transiciona a 95."""
        if self._cancelled.is_set():
            raise RuntimeError(self.error_msg or "cancelled")
        idx = self._step_idx
        if idx >= len(self.steps):
            self.nStep = self.n_finalizar
            return
        step_nombre = self.steps[idx]["nombre"]
        self._tracker.start_stage(step_nombre)
        logger.debug(f"{step_nombre}: entrando...")
        _t0 = time.monotonic()
        try:
            detail = self._run_step_with_timeout(idx)
        except TimeoutError:
            self._tracker.error_stage(
                step_nombre, f"timeout >{self._step_timeout_s}s",
            )
            raise
        except Exception:
            # El detail del error lo captura execute() en self.error_msg.
            self._tracker.error_stage(step_nombre, self.error_msg or "error")
            raise
        self._tracker.finish_stage(
            step_nombre, detail=str(detail) if detail else None,
        )
        _ms = (time.monotonic() - _t0) * 1000
        logger.debug(
            f"{step_nombre}: saliendo en {_ms:.0f}ms"
            + (f" ({detail})" if detail else "")
        )
        self._step_idx += 1
        # Un cancel puede haber llegado DURANTE el step (hilo de Flask).
        # Se comprueba aqui para no cerrar el FB como ``n_done``: la
        # cancelacion manda sobre el resultado del step.
        if self._cancelled.is_set():
            raise RuntimeError(self.error_msg or "cancelled")
        if self._step_idx >= len(self.steps):
            self.nStep = self.n_finalizar

    def _invoke_step_sync(self, idx: int) -> str:
        """Invoca ``run_step`` y resuelve el detail.

        Shim de migracion: un ``run_step`` que devuelve una corrutina
        (FB legacy todavia async) se resuelve con ``asyncio.run`` (el
        hilo del step no tiene event loop). Un ``run_step`` ya sync
        devuelve el detail directamente.
        """
        outcome = self.run_step(idx, **self._params)
        if inspect.isawaitable(outcome):
            outcome = asyncio.run(outcome)
        return outcome

    def _run_step_with_timeout(self, idx: int) -> str:
        """Ejecuta el step ``idx`` con el timeout de ``STEP_TIMEOUT_S``.

        El step corre en un hilo daemon: si expira, el hilo se abandona
        (no se puede matar un hilo) y el error se propaga al caller.

        Riesgo asumido: el hilo abandonado puede seguir mutando el
        estado del FB (``_stats``) despues del timeout. El camino
        legacy tiene el mismo riesgo: ``asyncio.wait_for`` cancela la
        corrutina, pero el hilo de un ``to_thread`` sigue vivo y
        mutando. La diferencia es que aqui no hay ninguna corrutiva
        viva que dependa del hilo abandonado.
        """
        box: dict[str, Any] = {}

        def _runner() -> None:
            try:
                box["detail"] = self._invoke_step_sync(idx)
            except BaseException as exc:  # noqa: BLE001 - se re-lanza en el caller
                box["error"] = exc

        worker = threading.Thread(
            target=_runner,
            name=f"fb-{self.nombre}-step{idx}",
            daemon=True,
        )
        worker.start()
        worker.join(timeout=self._step_timeout_s)
        if worker.is_alive():
            raise TimeoutError(
                f"step {idx} supero el timeout de {self._step_timeout_s}s"
            )
        error = box.get("error")
        if error is not None:
            raise error
        return box.get("detail") or ""

    # ------------------------------------------------------------------
    # API publica legacy (async, engine) -- se retira con el OB1
    # ------------------------------------------------------------------

    async def start(self, **params: Any) -> bool:
        """Arranca (o re-arranca) el FB.

        Acepta arranque inicial desde ``n_idle`` y re-arranque desde
        ``n_done``/``n_error``: el FB es una pieza reutilizable que el
        operario dispara N veces contra el engine (subir excel,
        sincronizar dispositivos, etc.) sin necesidad de reiniciar la
        app. En el re-arranque se limpia el estado por-llamada
        (``_stats``, ``_params``, ``error_msg``, ``result``,
        ``_step_idx``, ``_cancelled``); la identidad del FB y las
        deps inyectadas (``nombre``, ``titulo``, ``_tracker``,
        ``_on_nstep_change``, Zona 0) se mantienen.

        Rechaza la llamada si el FB esta activo (``n_arrancar``,
        ``n_ejecutar``, ``n_finalizar``) para no interrumpir un
        ciclo en vuelo: el caller recibe ``False`` (HTTP 409 en el
        router) y puede reintentar cuando el FB vuelva a un estado
        terminal.

        Returns:
            True si transiciono a ``n_arrancar``.
            False si estaba activo y se rechazo la llamada.
        """
        self._ensure_loop_objects()
        async with self._lock:
            if self.nStep not in (self.n_idle, self.n_done, self.n_error):
                logger.warning(
                    "FB %s: start() ignorado, FB activo (nStep=%d)",
                    self.nombre, self.nStep,
                )
                return False
            # Trazabilidad: si re-arrancamos desde terminal, deja una
            # linea visible en ConsolaLogs con el motivo antes de
            # pisar ``error_msg``. El operario ya vio el error por SSE
            # en tiempo real, pero la linea marca donde empieza el
            # ciclo nuevo (equivalente HMI del "fault acknowledged"
            # en PLC).
            prev_nStep = self.nStep
            prev_error = self.error_msg
            if prev_nStep == self.n_done:
                logger.info(
                    "FB %s: re-arrancando (ultima ejecucion OK)",
                    self.nombre,
                )
            elif prev_nStep == self.n_error:
                logger.warning(
                    "FB %s: re-arrancando tras error: %s",
                    self.nombre, prev_error or "<sin mensaje>",
                )
            # Reset del estado por-llamada (deps + identidad OK).
            self._reset_state_for_run(params)
            n_before = self.nStep
            self.nStep = self.n_arrancar
            logger.info("FB %s: start() OK (nStep=%d)", self.nombre, self.nStep)
            self._notify_nstep_change(n_before, self.nStep)
            return True

    async def tick(self) -> None:
        """Avanza el state machine un paso. Lo llama el engine.

        Tolerancia best-effort: si la logica lanza una excepcion de
        runtime, el wrapper la captura, fija ``error_msg``, cierra
        ``tracker.finish(success=False)`` y transita a ``n_error``.
        ``NotImplementedError`` y ``AssertionError`` propagan (errores
        de programacion, no se silencian).

        Si hay una ejecucion sync en curso (``execute()``), el tick se
        omite: los dos caminos no pueden tocar el FB a la vez.
        """
        self._ensure_loop_objects()
        if not self._exec_lock.acquire(blocking=False):
            logger.debug(
                "FB %s: tick() omitido, hay una ejecucion en curso",
                self.nombre,
            )
            return
        try:
            async with self._lock:
                n_before = self.nStep
                try:
                    await self._tick_locked()
                except (NotImplementedError, AssertionError):
                    raise
                except Exception as e:
                    self._fail_with(e, "tick()")
                self._notify_nstep_change(n_before, self.nStep)
        finally:
            self._exec_lock.release()

    async def cancel(self, reason: str = "cancelled") -> None:
        """Paro cooperativo. Marca flag y transiciona a ``n_error``.

        El flag es un ``threading.Event``: se puede activar desde un
        hilo de Flask mientras el hilo ejecutor esta dentro de un step.
        El step en curso lo comprueba en la frontera de etapa.
        No-op si ya esta terminal.
        """
        self._ensure_loop_objects()
        async with self._lock:
            if self.is_terminal():
                return
            logger.info("FB %s: cancel() solicitado (%s)", self.nombre, reason)
            self._cancelled.set()
            self.error_msg = reason
            n_before = self.nStep
            self._close_tracker_on_error()
            self.nStep = self.n_error
            self._notify_nstep_change(n_before, self.nStep)

    # ------------------------------------------------------------------
    # State machine (privado; asume self._lock cogido)
    # ------------------------------------------------------------------

    async def _tick_locked(self) -> None:
        assert self._lock.locked()
        if self.nStep == self.n_idle:
            return
        if self.nStep == self.n_arrancar:
            self._step_arrancar()
        elif self.nStep == self.n_ejecutar:
            await self._step_ejecutar()
        elif self.nStep == self.n_finalizar:
            self._step_finalizar()
        # n_done / n_error: no-op. El engine ya los skipea.

    def _step_arrancar(self) -> None:
        """nStep 10 -> 20. ``on_start`` + ``tracker.begin``.

        Si ``on_start`` lanza (p. ej. ``ValueError`` por params
        invalidos), el ``execute()`` lo captura, cierra el tracker y va
        a ``n_error``.
        """
        self.on_start(**self._params)
        self._tracker.begin(
            operation=self.nombre,
            label=self.titulo,
            stages=[s["nombre"] for s in self.steps],
        )
        self.nStep = self.n_ejecutar

    async def _step_ejecutar(self) -> None:
        """nStep 20: ejecuta el step ``_step_idx`` o transiciona a 95."""
        if self._cancelled.is_set():
            raise RuntimeError(self.error_msg or "cancelled")
        idx = self._step_idx
        if idx >= len(self.steps):
            self.nStep = self.n_finalizar
            return
        step_nombre = self.steps[idx]["nombre"]
        self._tracker.start_stage(step_nombre)
        # Wrapper entry/exit va a DEBUG (no web). El operario ya ve
        # el flujo via los ``_log.web/ok`` explicitos de cada FB
        # (``[scan_plc_blocks] Iniciando scan de '...'``, etc.) y
        # el progress tracker (start_stage/finish_stage) en la UI.
        logger.debug(f"{step_nombre}: entrando...")
        _t0 = time.monotonic()
        try:
            if inspect.iscoroutinefunction(self.run_step):
                detail = await asyncio.wait_for(
                    self.run_step(idx, **self._params),
                    timeout=self._step_timeout_s,
                )
            else:
                # ``run_step`` ya es sync (FB migrado): se ejecuta en un
                # hilo daemon con el timeout del base, igual que hace
                # el camino sync. NO se puede pasar a ``wait_for``
                # porque su valor de retorno no es una corrutina.
                detail = await asyncio.to_thread(self._run_step_with_timeout, idx)
        except TimeoutError:
            self._tracker.error_stage(
                step_nombre, f"timeout >{self._step_timeout_s}s",
            )
            raise
        except asyncio.CancelledError:
            self._tracker.error_stage(step_nombre, "cancelled")
            raise
        except Exception:
            # El detail del error lo captura el tick() en self.error_msg.
            self._tracker.error_stage(step_nombre, self.error_msg or "error")
            raise
        self._tracker.finish_stage(
            step_nombre, detail=str(detail) if detail else None,
        )
        _ms = (time.monotonic() - _t0) * 1000
        logger.debug(
            f"{step_nombre}: saliendo en {_ms:.0f}ms"
            + (f" ({detail})" if detail else "")
        )
        self._step_idx += 1
        if self._step_idx >= len(self.steps):
            self.nStep = self.n_finalizar

    def _step_finalizar(self) -> None:
        """nStep 95 -> 99. ``on_finish`` + ``tracker.finish(success=True)``."""
        self.on_finish(**self._params)
        self._tracker.finish(success=True)
        self.nStep = self.n_done

    def _close_tracker_on_error(self) -> None:
        """Cierra el tracker con ``success=False``. Asume lock cogido.

        Usado por ``tick()`` (tras excepcion), ``execute()`` (tras
        excepcion) y ``cancel()``. Deja el tracker en estado inactivo
        para que la SPA no muestre la barra "pegada".
        """
        try:
            # Marca el stage en curso (si lo hay) como error para que la
            # SPA lo vea enrojecido. No-op si ya esta terminal.
            if 0 <= self._step_idx < len(self.steps):
                stage_nombre = self.steps[self._step_idx]["nombre"]
                # Solo emitimos error_stage si el tracker sigue activo.
                if getattr(self._tracker, "active", False):
                    self._tracker.error_stage(
                        stage_nombre, self.error_msg or "error",
                    )
            if getattr(self._tracker, "active", False):
                self._tracker.finish(success=False, error=self.error_msg)
        except Exception as exc:  # noqa: BLE001
            # Nunca rompemos el cierre del FB por un fallo del tracker.
            logger.debug("FB %s: cierre de tracker fallo: %s", self.nombre, exc)


__all__ = ["FunctionBase"]
