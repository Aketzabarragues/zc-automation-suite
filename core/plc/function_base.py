"""core.plc.function_base — clase base de los Function Blocks (FBs).

Fase 2 del refactor: state machine discreto ``nStep`` con tolerancia
best-effort.  Cada FB es un orquestador asíncrono de una operación
del operario contra TIA Portal (subir excel, escanear bloques,
sincronizar dispositivos, etc.).

State machine::

    nStep=0   idle      (FB creado, sin start)
    nStep=10  arrancar  (transición tras start OK)
    nStep=20  ejecutar  (transición durante tick si procede)
    nStep=30  finalizar (transición al completar)
    nStep=99  done      (terminal OK, el engine NO tickea más)
    nStep=98  error     (terminal con error_msg, el engine NO tickea más)

Las subclases overridean ``_tick_locked()`` para implementar la
lógica.  La base lanza ``NotImplementedError`` si se tickea sin
overridear (error de programación, no de runtime).

Concurrencia: ``start()`` y ``tick()`` son coroutines que comparten
estado (``nStep``, ``result``, ``error_msg``).  Siguen el patrón
"lock del assert" del greenfield: el wrapper público adquiere
``self._lock`` y delega en un método privado ``_x_locked`` que asume
el lock cogido y arranca con ``assert self._lock.locked()``.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class FunctionBase:
    """Clase base de un Function Block (state machine asíncrono).

    API pública:
      - ``__init__(nombre)`` — estado inicial ``nStep=n_idle`` (0).
      - ``start(**params)`` — arranca el FB.  Idempotente: si ya está
        activo o terminal, ignora la llamada (``False``).
      - ``tick()`` — avanza el state machine un paso.  La base lanza
        ``NotImplementedError``; las subclases overridean
        ``_tick_locked()`` (no ``tick()`` directamente) para mantener
        el contrato del lock.
      - ``is_terminal()`` — ``True`` si el FB está en ``n_idle``,
        ``n_done`` o ``n_error``; el engine NO tickea FBs terminales.

    Estado compartido (protegido por ``self._lock``):
      - ``nStep: int``  — paso discreto del state machine.
      - ``error_msg: str | None``  — mensaje si ``nStep == n_error``.
      - ``result: Any``  — payload de retorno si ``nStep == n_done``.
    """

    # Constantes de estado a nivel de clase: las subclases y el engine
    # las referencian sin necesidad de instanciar.
    n_idle: int = 0
    n_done: int = 99
    n_error: int = 98

    def __init__(self, nombre: str) -> None:
        self.nombre: str = nombre
        self.nStep: int = self.n_idle
        self.error_msg: str | None = None
        self.result: Any = None
        # Parámetros del último start() exitoso.  Las subclases los
        # leen desde _tick_locked() si los necesitan.
        self._params: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # API pública (adquiere el lock y delega en el _locked gemelo)
    # ------------------------------------------------------------------

    async def start(self, **params: Any) -> bool:
        """Arranca el FB.  Idempotente: si ya está activo, ignora.

        Devuelve ``True`` si pasó ``nStep`` de ``n_idle`` a 10,
        ``False`` si ya estaba activo o en estado terminal.
        """
        async with self._lock:
            return await self._start_locked(**params)

    async def tick(self) -> None:
        """Avanza el state machine un paso.  Overridear ``_tick_locked``.

        Tolerancia best-effort (Fase 2, paso 2.0.4): si ``_tick_locked()``
        lanza una excepción de runtime (no de programación), el wrapper
        la captura, hace log, fija ``error_msg`` y transita ``nStep`` a
        ``n_error``.  El FB queda terminal pero vivo: el operario ve el
        error y puede resetearlo manualmente.  ``NotImplementedError`` y
        ``AssertionError`` propagan (errores de programación, no se
        silencian).
        """
        async with self._lock:
            try:
                await self._tick_locked()
            except (NotImplementedError, AssertionError):
                # Programación: la subclase olvidó overridear o el lock
                # no estaba cogido.  Propaga para que el dev lo vea
                # claro en consola/tests.
                raise
            except Exception as e:
                # Runtime: TIA Portal, Excel, red, etc.  Degradado pero
                # vivo — el operario ve el error y resetea el FB.
                logger.exception(
                    "FB %s: error en tick() (nStep=%d) — %s: %s",
                    self.nombre, self.nStep, type(e).__name__, e,
                )
                self.error_msg = f"{type(e).__name__}: {e}"
                self.nStep = self.n_error

    def is_terminal(self) -> bool:
        """``True`` si el FB está en estado terminal y NO debe tickearse.

        Idle (``nStep=0``) también cuenta como terminal: un FB sin
        ``start()`` no hace nada en ``tick()``.  ``n_done`` y
        ``n_error`` son los dos estados finales tras una ejecución.
        """
        return self.nStep in (self.n_idle, self.n_done, self.n_error)

    # ------------------------------------------------------------------
    # Métodos privados (asumen self._lock cogido)
    # ------------------------------------------------------------------

    async def _start_locked(self, **params: Any) -> bool:
        """Asume ``self._lock`` cogido.  No llamar directamente.

        Idempotente: si ``nStep != n_idle``, ignora y devuelve ``False``.
        En caso contrario, captura ``params``, resetea ``error_msg`` y
        ``result``, y avanza ``nStep`` a 10.
        """
        assert self._lock.locked(), "_start_locked() requiere self._lock cogido"
        if self.nStep != self.n_idle:
            logger.warning(
                "FB %s: start() ignorado, ya activo o terminal (nStep=%d)",
                self.nombre,
                self.nStep,
            )
            return False
        self._params = dict(params)
        self.error_msg = None
        self.result = None
        self.nStep = 10
        logger.info("FB %s: start() OK (nStep=%d)", self.nombre, self.nStep)
        return True

    async def _tick_locked(self) -> None:
        """Asume ``self._lock`` cogido.  Overridear en subclases.

        La base hace dos cosas y se detiene ahí:
          1. Guarda defensiva de ``is_terminal()`` (no-op si terminal).
          2. Si no, lanza ``NotImplementedError`` (error de programación
             — la subclase olvidó overridear).
        """
        assert self._lock.locked(), "_tick_locked() requiere self._lock cogido"
        if self.is_terminal():
            # El engine ya filtra, pero si alguien llama tick()
            # manualmente sobre un FB idle/done/error, no hacemos nada.
            return
        raise NotImplementedError(
            f"FB {self.nombre}: _tick_locked() debe ser implementado por "
            f"la subclase (ver areas/<area>/functions/function_*.py)"
        )
