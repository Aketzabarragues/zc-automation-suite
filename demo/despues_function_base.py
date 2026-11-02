"""DESPUES (formato A): el motor de FBs con los pasos declarados con @step.

Propuesta sobre core/composition/plc_function_base.py.
NO se aplica a la aplicacion: esto es la demo del diseno.

El cambio de fondo: cada paso del FB se declara UNA vez, con su nombre
y su descripcion, encima de su propio codigo:

    @step("Exportar etiquetas", descripcion="Exporta las tablas de tags")
    def _stage_1_exportar_tags(self) -> str:
        ...
        return "Exportar etiquetas: 13 tablas exportadas"

El motor recoge esos pasos (en orden de definicion = orden del flujo),
hace el dispatch y pone el detail en el tracker. El FB no tiene ni
``steps=``, ni tabla ``STAGES``, ni ``run_step``, ni ``_step_summary``.

Lo que NO cambia (contrato con el engine, los routers y la SPA):
``execute``, ``nStep``, ``result``, ``error_msg``, ``is_terminal``,
``request_cancel``, el shape de ``fb_state`` y de ``progress``, y los
nombres visibles de los pasos.

El recorrido (``_step_arrancar`` -> pasos -> ``_step_finalizar``) y el
contrato con el tracker son los del motor real. Lo unico que cambia es
de donde salen los pasos: de los metodos marcados con ``@step``.
"""
from __future__ import annotations

import inspect
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger("zc")

# Atributo con el que se marca un metodo como paso del FB.
STEP_ATTR = "_step_spec"


@dataclass(frozen=True)
class StepSpec:
    """Lo que un paso declara sobre si mismo."""

    nombre: str
    descripcion: str
    metodo: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "nombre": self.nombre,
            "descripcion": self.descripcion,
            "handler": self.metodo,
        }


def step(nombre: str, descripcion: str = "") -> Callable[[Callable], Callable]:
    """Declara un metodo como paso del FB.

    Args:
        nombre: etiqueta del paso. Es lo que ve el operario en la barra
            de progreso, asi que no se renombra a la ligera.
        descripcion: que hace el paso. Va al log y al diagrama del FB.

    El orden de los pasos es el de definicion de los metodos: el flujo
    se lee de arriba abajo, como un SFC.
    """

    def deco(fn: Callable) -> Callable:
        setattr(
            fn,
            STEP_ATTR,
            StepSpec(
                nombre=nombre,
                descripcion=descripcion,
                metodo=fn.__name__,
            ),
        )
        return fn

    return deco


class TrackerConsola:
    """Stand-in del ``ProgressTracker``: imprime lo que ve el operario.

    Reproduce el contrato que usa el motor: ``begin`` declara el flujo,
    ``start_stage`` falla si el stage no estaba declarado, y
    ``finish_stage`` / ``error_stage`` cierran cada caja.
    """

    def __init__(self) -> None:
        self._estado: dict[str, str] = {}
        self._activo = False

    @property
    def active(self) -> bool:
        return self._activo

    def begin(
        self,
        operation: str,
        label: str = "",
        stages: list[str] | None = None,
    ) -> None:
        self._estado = {s: "pending" for s in (stages or [])}
        self._activo = True
        print(f"\n[{operation}] {label}")
        print(f"  flujo: {' -> '.join(self._estado)}")

    def start_stage(self, stage_id: str, detail: str | None = None) -> None:
        if stage_id not in self._estado:
            raise KeyError(f"stage no declarado: {stage_id!r}")
        self._estado[stage_id] = "running"

    def finish_stage(self, stage_id: str, detail: str | None = None) -> None:
        if self._estado.get(stage_id) in ("done", "error"):
            return
        self._estado[stage_id] = "done"
        print(f"  [ok] {stage_id}" + (f" -- {detail}" if detail else ""))

    def error_stage(self, stage_id: str, detail: str | None = None) -> None:
        self._estado[stage_id] = "error"
        print(f"  [error] {stage_id}" + (f" -- {detail}" if detail else ""))

    def finish(self, success: bool = True, error: str | None = None) -> None:
        self._activo = False
        print("  [fin] ok" if success else f"  [fin] error: {error}")


class _TrackerNulo:
    """Tracker que no hace nada: para correr sin barra de progreso."""

    @property
    def active(self) -> bool:
        return False

    def begin(self, *args: Any, **kwargs: Any) -> None:
        pass

    def start_stage(self, *args: Any, **kwargs: Any) -> None:
        pass

    def finish_stage(self, *args: Any, **kwargs: Any) -> None:
        pass

    def error_stage(self, *args: Any, **kwargs: Any) -> None:
        pass

    def finish(self, *args: Any, **kwargs: Any) -> None:
        pass


class FunctionBase:
    """Base de los Function Blocks (motor del OB1)."""

    n_idle: int = 0
    n_arrancar: int = 10
    n_ejecutar: int = 20
    n_finalizar: int = 95
    n_done: int = 99
    n_error: int = 98

    STEP_TIMEOUT_S: float = 300.0

    def __init__(
        self,
        nombre: str,
        titulo: str,
        steps: list[dict[str, Any]] | None = None,
        tracker: Any = None,
        step_timeout_s: float | None = None,
    ) -> None:
        self.nombre = nombre
        self.titulo = titulo
        # Los pasos salen de los metodos marcados con @step. El parametro
        # ``steps`` queda solo para la transicion (FBs que aun no han
        # migrado): en el formato final desaparece.
        declarados = self.pasos_declarados()
        if declarados and steps is not None:
            # Migracion a medias: el FB declara unos pasos por @step y
            # otros por la lista. Las dos listas no se pueden mezclar sin
            # duplicar o saltarse pasos, asi que se para aqui.
            raise ValueError(
                f"FB {self.__class__.__name__}: declara pasos con @step y "
                f"a la vez pasa steps=. Migra el FB entero o nada."
            )
        if declarados:
            self.steps: list[dict[str, Any]] = [s.as_dict() for s in declarados]
        else:
            self.steps = [
                s if isinstance(s, dict) else {"nombre": s}
                for s in (steps or [])
            ]
        self._tracker = tracker if tracker is not None else _TrackerNulo()
        self._step_timeout_s = (
            step_timeout_s if step_timeout_s is not None else self.STEP_TIMEOUT_S
        )
        self._step_idx: int = 0
        self._cancelled = threading.Event()
        self.nStep: int = self.n_idle
        self.error_msg: str | None = None
        self.result: Any = None
        self._params: dict[str, Any] = {}
        self._stats: dict[str, Any] = {}
        self._exec_lock = threading.Lock()
        self._on_nstep_change: Callable[[int, int], None] | None = None

    # ------------------------------------------------------------------
    # Los pasos
    # ------------------------------------------------------------------

    @classmethod
    def pasos_declarados(cls) -> list[StepSpec]:
        """Pasos declarados con ``@step``, en orden de definicion.

        El orden de definicion de los metodos es el orden del flujo: se
        lee de arriba abajo, como un SFC.
        """
        specs: list[StepSpec] = []
        vistos: set[str] = set()
        for klass in reversed(cls.__mro__):
            for _attr, value in vars(klass).items():
                spec = getattr(value, STEP_ATTR, None)
                if spec is None:
                    continue
                if spec.nombre in vistos:
                    raise ValueError(
                        f"FB {cls.__name__}: nombre de paso duplicado "
                        f"{spec.nombre!r}"
                    )
                vistos.add(spec.nombre)
                specs.append(spec)
        return specs

    @classmethod
    def diagramar(cls) -> str:
        """Diagrama SFC del FB, generado desde la misma declaracion."""
        from demo.diagrama_sfc import diagrama_ascii

        return diagrama_ascii(cls)

    # ------------------------------------------------------------------
    # Hooks que aportan los FBs
    # ------------------------------------------------------------------

    def on_start(self, **params: Any) -> None:
        """Pre-flight SYNC. Default: no-op."""
        pass

    def on_finish(self, **params: Any) -> None:
        """Post-proceso. Default: no-op."""
        self.result = {"ok": True}

    def reset_run_state(self) -> None:
        """Hook de reinicio del estado por llamada. Default: no-op."""
        return None

    # ------------------------------------------------------------------
    # Estado y notificacion
    # ------------------------------------------------------------------

    def _notify_nstep_change(self, old: int, new: int) -> None:
        if self._on_nstep_change is not None and old != new:
            self._on_nstep_change(old, new)

    def is_terminal(self) -> bool:
        """``True`` si el FB esta en estado terminal (idle, done o error)."""
        return self.nStep in (self.n_idle, self.n_done, self.n_error)

    def _reset_state_for_run(self, params: dict[str, Any]) -> None:
        """Limpia el estado por-llamada."""
        self._stats.clear()
        self._params = dict(params)
        self.error_msg = None
        self.result = None
        self._step_idx = 0
        self._cancelled.clear()
        self.reset_run_state()

    def _fail_with(self, exc: BaseException, contexto: str) -> None:
        """Fija ``error_msg``, cierra el tracker y transiciona a ``n_error``."""
        logger.error(
            f"[{self.nombre}] ERROR en {contexto} "
            f"(nStep={self.nStep}): {type(exc).__name__}: {exc}"
        )
        self.error_msg = f"{type(exc).__name__}: {exc}"
        self._close_tracker_on_error()
        self.nStep = self.n_error

    def request_cancel(self, reason: str) -> bool:
        """Cancelacion cooperativa: la pide el hilo de Flask."""
        if self.is_terminal():
            return False
        if self.error_msg is None:
            self.error_msg = reason
        self._cancelled.set()
        return True

    # ------------------------------------------------------------------
    # Ejecucion
    # ------------------------------------------------------------------

    def execute(self, **params: Any) -> Any:
        """Ejecuta el FB completo de principio a fin (SINC)."""
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
        if not self.is_terminal():
            return self.result

        self._reset_state_for_run(params)
        n_before = self.nStep
        self.nStep = self.n_arrancar
        self._notify_nstep_change(n_before, self.nStep)

        try:
            before = self.nStep
            self._step_arrancar()
            self._notify_nstep_change(before, self.nStep)

            while self.nStep == self.n_ejecutar:
                before = self.nStep
                self._step_ejecutar_sync()
                self._notify_nstep_change(before, self.nStep)

            if self.nStep == self.n_finalizar:
                before = self.nStep
                self._step_finalizar()
                self._notify_nstep_change(before, self.nStep)
        except (NotImplementedError, AssertionError) as e:
            self.error_msg = f"{type(e).__name__}: {e}"
            self._close_tracker_on_error()
            self.nStep = self.n_error
            raise
        except Exception as e:
            self._fail_with(e, "execute()")

        return self.result

    def _step_ejecutar_sync(self) -> None:
        """nStep 20 (sync): ejecuta el step ``_step_idx``."""
        if self._cancelled.is_set():
            raise RuntimeError(self.error_msg or "cancelled")
        idx = self._step_idx
        if idx >= len(self.steps):
            self.nStep = self.n_finalizar
            return
        step_info = self.steps[idx]
        step_nombre = step_info["nombre"]
        descripcion = step_info.get("descripcion")
        if descripcion:
            logger.info(f"{step_nombre}: {descripcion}")
        self._tracker.start_stage(step_nombre)
        _t0 = time.monotonic()
        try:
            detail = self._run_step_with_timeout(idx)
        except TimeoutError:
            self._tracker.error_stage(
                step_nombre, f"timeout >{self._step_timeout_s}s",
            )
            raise
        except Exception:
            self._tracker.error_stage(step_nombre, self.error_msg or "error")
            raise
        self._tracker.finish_stage(
            step_nombre, detail=str(detail) if detail else None,
        )
        self._step_idx += 1
        if self._cancelled.is_set():
            raise RuntimeError(self.error_msg or "cancelled")
        if self._step_idx >= len(self.steps):
            self.nStep = self.n_finalizar

    def _invoke_step_sync(self, idx: int) -> str:
        """Ejecuta el step ``idx`` y devuelve su detail.

        El handler es un metodo del propio FB, declarado con ``@step``.
        Si el step no declara handler, cae al hook ``run_step``
        (compatibilidad para migrar FB a FB).
        """
        step_info = self.steps[idx]
        handler = step_info.get("handler")

        if handler is not None:
            outcome = getattr(self, handler)()
        else:
            outcome = self.run_step(idx, **self._params)

        if inspect.isawaitable(outcome):
            raise TypeError(
                "el handler del step devuelve una corrutina: los FBs deben "
                "ser sync (se ejecutan en el hilo del dispatcher del OB1)"
            )
        return outcome

    def _run_step_with_timeout(self, idx: int) -> str:
        """Ejecuta el step ``idx`` con el timeout de ``STEP_TIMEOUT_S``."""
        box: dict[str, Any] = {}

        def _runner() -> None:
            try:
                box["detail"] = self._invoke_step_sync(idx)
            except BaseException as exc:  # noqa: BLE001 - se relanza en el caller
                box["error"] = exc

        worker = threading.Thread(
            target=_runner,
            name=f"fb-{self.nombre}-step{idx}",
            daemon=True,
        )
        worker.start()
        worker.join(self._step_timeout_s)
        if worker.is_alive():
            raise TimeoutError(
                f"FB {self.nombre}: step {idx} supero "
                f"{self._step_timeout_s}s"
            )
        if "error" in box:
            raise box["error"]
        return box.get("detail", "")

    def run_step(self, idx: int, **params: Any) -> str:
        """Hook de compatibilidad. Los FBs migrados ya no lo usan.

        Se mantiene mientras haya FBs con la forma antigua; el guard
        ``test_fbs_sync_contract`` pasa a verificar los handlers.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # State machine (privado)
    # ------------------------------------------------------------------

    def _step_arrancar(self) -> None:
        """nStep 10 -> 20. ``on_start`` + ``tracker.begin``."""
        self.on_start(**self._params)
        self._tracker.begin(
            operation=self.nombre,
            label=self.titulo,
            stages=[s["nombre"] for s in self.steps],
        )
        self.nStep = self.n_ejecutar

    def _step_finalizar(self) -> None:
        """nStep 95 -> 99. ``on_finish`` + ``tracker.finish(success=True)``."""
        self.on_finish(**self._params)
        self._tracker.finish(success=True)
        self.nStep = self.n_done

    def _close_tracker_on_error(self) -> None:
        """Cierra el tracker con ``success=False``."""
        try:
            if 0 <= self._step_idx < len(self.steps):
                stage_nombre = self.steps[self._step_idx]["nombre"]
                if getattr(self._tracker, "active", False):
                    self._tracker.error_stage(
                        stage_nombre, self.error_msg or "error",
                    )
            if getattr(self._tracker, "active", False):
                self._tracker.finish(success=False, error=self.error_msg)
        except Exception:
            pass
