"""PLANTILLA base para Function Blocks (FBs) reales.

Cuando migres un use case legacy (SubirExcel, ScanPlcBlocks,
Sincronizar*, etc.), haz una copia de este archivo y adapta SOLO
las zonas marcadas con ``# TOCAR:``. El resto (state machine,
lock, progress_tracker, timeouts, cancel, error_stage) lo hereda
del ``FunctionBase`` y no hay que tocarlo.

============================================================================
ZONAS A TOCAR (migracion de un FB real)
============================================================================

  ZONA 0  Dependencias comunes (inyeccion en ``__init__``).
        Por defecto todas son ``None``; el FB concreto las recibe
        del ``register_fb()`` en ``register_alimentacion``. Ver la
        lista en el constructor mas abajo.

  1. ``STEP_TIMEOUT_S``  Timeout por step (segundos). Ajustar al
                        peor caso del FB real.

  2. ``__init__``       - ``nombre``: id canonico del FB
                                    (ej: "sync_dispositivos").
                        - ``titulo``:  texto del HMI
                                    (ej: "Sincronizar dispositivos").
                        - ``steps``:   lista de etapas del FB
                                    (minimo 1, recomendado 3-7).

  3. ``on_start``       Validar params obligatorios del ``start()``.
                        Lanzar ``ValueError`` si falta algo.
                        Tambien aqui se capturan las deps inyectadas
                        en atributos privados (``self._xlsx_path``,
                        ``self._plc_name``, etc.).

  4. ``run_step``       CASE con la logica de cada etapa. Cada
                        rama hace el trabajo del step y retorna
                        un ``detail`` (str) para el HMI. Aqui
                        ``self._tia_client``, ``self._config``,
                        ``self._build_cache`` y ``self._log`` ya
                        estan disponibles.

  5. ``on_finish``      Vuelca ``self.result`` con la shape final
                        que el caller (use case / endpoint REST)
                        espera.

============================================================================
LO QUE NO SE TOCA (lo gestiona el base)
============================================================================

  - State machine: idle (0) -> arrancar (10) -> ejecutar (20) ->
    finalizar (95) -> done (99); o error (98).
  - Lock + idempotencia del ``start()``.
  - Hook ``_on_nstep_change`` (cablea ``fb_state`` al bus SSE).
  - ``progress_tracker``: begin/start_stage/finish_stage/error_stage
    /finish, automaticos.
  - Timeout por step (``asyncio.wait_for`` con ``STEP_TIMEOUT_S``).
  - ``cancel(reason)``: paro cooperativo que cierra el tracker con
    ``success=False``.

============================================================================
EJEMPLO MINIMO (todo # TOCAR: ya rellenado con datos dummy)
============================================================================

  Cuando se arranque, esta plantilla emite 10 progress events al bus
  SSE con stages ``paso_1..paso_10``. Sirve como smoke del propio
  base. Para usarla como FB real, copiar y adaptar.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from core.composition.plc_function_base import FunctionBase
from core.runtime.progress_buffer import ProgressTracker, get_progress_tracker

logger = logging.getLogger(__name__)


class FunctionTemplate(FunctionBase):
    """Plantilla generica con 10 pasos dummy. Copiar y adaptar para FBs reales."""

    # ==================================================================
    # CONFIGURACION ESTATICA DEL FB
    # ==================================================================

    # TOCAR: timeout por step (segundos). Si una etapa hace I/O real
    # (TIA Portal, Excel, red), ajustar al peor caso medido en campo.
    STEP_TIMEOUT_S: float = 60.0

    # ==================================================================
    # CONSTRUCTOR
    # ==================================================================

    def __init__(
        self,
        nombre: str = "template",
        titulo: str = "Plantilla FB",
        steps: list[dict[str, Any]] | None = None,
        tracker: ProgressTracker | None = None,
        # ── ZONA 0: deps comunes (todas opcionales, default None) ──
        # config_manager: ConfigManager del departamento activo (lectura
        #                 de hw_types, n_max_catalog, excel_target, etc).
        #                 Inyectado por ``register_alimentacion`` al
        #                 registrar el FB en el engine.
        # tia_client:     SyncTIAClient del core. Sustituye al legacy
        #                 TIAProcessGateway (borrado en refactor sept-2026).
        #                 None si el FB no toca TIA (ej. SubirExcel).
        # build_cache:    BuildCache del area (.build_cache/<area>/<contexto>/...).
        #                 None si el FB no exporta nada a TIA.
        config_manager: Any = None,
        tia_client: Any = None,
        build_cache: Any = None,
    ) -> None:
        super().__init__(
            # TOCAR: id canonico del FB (snake_case, estable, sin espacios).
            #        Se usa como ``operation`` del progress_tracker y como
            #        clave del endpoint REST (``/api/v1/plc/fb/<nombre>/...``).
            nombre=nombre,
            # TOCAR: titulo que ve el operario en el HMI (Spanish OK).
            titulo=titulo,
            # TOCAR: lista de etapas del FB. Cada step es un dict con al
            #        menos ``nombre`` (id canonico del step). Recomendado
            #        entre 3 y 7; minimo 1. La duracion NO la usa el base
            #        (es solo referencia para tests), pero queda aqui para
            #        que la spec del FB sea autodocumentada.
            steps=steps if steps is not None else [
                {"nombre": "paso_1"},
                {"nombre": "paso_2"},
                {"nombre": "paso_3"},
                {"nombre": "paso_4"},
                {"nombre": "paso_5"},
                {"nombre": "paso_6"},
                {"nombre": "paso_7"},
                {"nombre": "paso_8"},
                {"nombre": "paso_9"},
                {"nombre": "paso_10"},
            ],
            tracker=tracker if tracker is not None else get_progress_tracker(),
        )
        # ==================================================================
        # ESTADO INTERNO DEL FB (ZONA 0: deps inyectadas)
        # ==================================================================
        self._config = config_manager
        self._tia_client = tia_client
        self._build_cache = build_cache
        # ==================================================================
        # ESTADO INTERNO DEL FB (ZONA 3: atributos del start())
        # ==================================================================
        # TOCAR: atributos privados del FB (estado del proceso). Se inicializan
        # en ``on_start`` cuando llegan los params del ``start()``. Ejemplos:
        #
        #   self._excel_path: str | None = None
        #   self._plc: Any = None
        #   self._bloques_creados: list = []
        #   self._stats: dict[str, Any] = {}
        #
        # Mantener siempre prefijo ``_`` (accede solo el propio FB).
        self._stats: dict[str, Any] = {}

    # ==================================================================
    # HOOK 1: on_start  (pre-flight SYNC)
    # ==================================================================
    # Se llama UNA vez, justo despues de ``start()``, antes del primer step.
    # Si lanza ``ValueError`` (param obligatorio faltante), el ``tick()``
    # del base lo captura, emite ``tracker.error_stage`` y va a n_error.
    #
    # Equivalente SCL: validar IN del FB y cargar variables internas.

    def on_start(self, **params: Any) -> None:
        """Pre-flight: validar params + preparar estado interno."""
        # TOCAR: leer y validar params del ``start(**kwargs)``. Ejemplo:
        #
        #   excel_path = params.get("excel_path", "")
        #   if not excel_path:
        #       raise ValueError("excel_path es obligatorio")
        #   if not Path(excel_path).exists():
        #       raise ValueError(f"excel no encontrado: {excel_path}")
        #   self._excel_path = excel_path
        #
        # Si el FB no necesita params, dejar este metodo vacio (pass).
        # La plantilla lo deja vacio para que el smoke pueda correr sin
        # pasar nada en el body del POST /start.
        pass

    # ==================================================================
    # HOOK 2: run_step  (CASE por etapa)
    # ==================================================================
    # El base llama a este metodo UNA vez por cada step. Entre llamada
    # y llamada, el base hace:
    #   - ``tracker.start_stage(nombre)``
    #   - ``await asyncio.wait_for(self.run_step(idx), timeout=STEP_TIMEOUT_S)``
    #   - ``tracker.finish_stage(nombre, detail=<valor de retorno>)``
    #   - incrementa ``_step_idx`` y vuelve a entrar si quedan steps.
    #
    # Si este metodo LANZA cualquier excepcion, el base emite
    # ``tracker.error_stage(...)`` y transiciona a n_error automaticamente.
    #
    # Equivalente SCL: ``CASE self.steps[idx].nombre OF ... END_CASE;``.

    async def run_step(self, idx: int, **params: Any) -> str:
        """Logica del step N. Devuelve un detail (str) para el HMI."""
        step_nombre = self.steps[idx]["nombre"]
        logger.info(f"[{self.nombre}] CASE {step_nombre} (idx={idx})")

        # ------------------------------------------------------------------
        # CASE step_nombre OF
        # ------------------------------------------------------------------
        # TOCAR: cada rama del CASE = una etapa del FB real. Renombrar
        # ``paso_X`` a los ids canonicos de tu FB (ej: "parsear_excel",
        # "validar_N_MAX", etc.). Cada rama debe:
        #   1. Hacer su trabajo (I/O, CPU, lo que sea). Si es awaitable
        #      (subprocess, network, etc.), usar ``await``.
        #   2. Rellenar ``self._stats[step_nombre] = {...}`` con info util.
        #   3. Retornar un ``detail`` (str) que el HMI mostrara junto al
        #      nombre del step (ej: "142 filas", "OK", "12 bloques").
        match step_nombre:
            case "paso_1":
                await asyncio.sleep(0.3)
                self._stats["paso_1"] = {"ok": True}
                return "paso 1 OK"

            case "paso_2":
                await asyncio.sleep(0.3)
                self._stats["paso_2"] = {"ok": True}
                return "paso 2 OK"

            case "paso_3":
                await asyncio.sleep(0.3)
                self._stats["paso_3"] = {"ok": True}
                return "paso 3 OK"

            case "paso_4":
                await asyncio.sleep(0.3)
                self._stats["paso_4"] = {"ok": True}
                return "paso 4 OK"

            case "paso_5":
                await asyncio.sleep(0.3)
                self._stats["paso_5"] = {"ok": True}
                return "paso 5 OK"

            case "paso_6":
                await asyncio.sleep(0.3)
                self._stats["paso_6"] = {"ok": True}
                return "paso 6 OK"

            case "paso_7":
                await asyncio.sleep(0.3)
                self._stats["paso_7"] = {"ok": True}
                return "paso 7 OK"

            case "paso_8":
                await asyncio.sleep(0.3)
                self._stats["paso_8"] = {"ok": True}
                return "paso 8 OK"

            case "paso_9":
                await asyncio.sleep(0.3)
                self._stats["paso_9"] = {"ok": True}
                return "paso 9 OK"

            case "paso_10":
                await asyncio.sleep(0.3)
                self._stats["paso_10"] = {"ok": True}
                return "paso 10 OK"

            case _:
                # Defensivo: step no soportado. Lanza ValueError para que
                # el base vaya a n_error con error_stage.
                raise ValueError(f"step no soportado: {step_nombre!r}")

    # ==================================================================
    # HOOK 3: on_finish  (post-flight SYNC)
    # ==================================================================
    # Se llama UNA vez, tras ejecutar el ultimo step OK, antes de
    # transicionar a n_done. Aqui se vuelca ``self.result`` con la
    # shape final que el caller (use case / endpoint REST) leera
    # via ``GET /api/v1/plc/fb/<nombre>/status`` -> ``result``.
    #
    # Equivalente SCL: rellenar variables OUT del FB.

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` con la shape final del FB."""
        # TOCAR: shape de ``self.result``. Recomendacion:
        #   - ``ok``: True si todo fue bien.
        #   - ``titulo``, ``steps_completed``, ``total_steps``: meta del FB.
        #   - Campos especificos del FB (ej: bloques creados, dispositivos
        #     sincronizados, contadores, etc.). Sacarlos de ``self._stats``.
        self.result = {
            "ok": True,
            "titulo": self.titulo,
            "steps_completed": self._step_idx,
            "total_steps": len(self.steps),
            "stats": dict(self._stats),
        }


__all__ = ["FunctionTemplate"]
