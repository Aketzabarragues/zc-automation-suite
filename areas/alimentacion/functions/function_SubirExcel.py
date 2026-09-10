"""Function block: subir el Excel del operario.

Fase 2, paso 2.1.2.  Encapsula el use case legacy
``UploadExcelUseCase`` (areas/alimentacion/application/use_cases/
upload_excel.py) en un ``FunctionBase`` con state machine
``nStep = 10 -> 20 -> 30 -> 99 (n_done)`` o ``98 (n_error)``.

State machine:
  nStep=10  arrancar   (pre-flight: validar config y xlsx_path)
  nStep=20  parsear    (ExcelLoader.load + ExcelCacheManager.put)
  nStep=30  volcar     (AppState + summary + log + self.result)
  nStep=99  done       (terminal OK)
  nStep=98  error      (terminal con error_msg, vía wrapper de la base)

El FB es best-effort: cada step envuelve su trabajo en try/except
y re-lanza.  El wrapper ``tick()`` de la base captura la excepción,
fija ``error_msg`` y transita a ``n_error`` (paso 2.0.4).  El estado
parcial queda: el cache puede estar populado aunque el AppState no.
El caller (router 2.2.1) decide qué hacer con eso.

Trade-off respecto al use case legacy: este FB NO lanza
``HTTPException``.  El use case legacy lo hacía porque su único
consumidor era FastAPI; el FB es transport-agnostic, así que deja
que las excepciones de dominio (RuntimeError, ValueError, errores
del loader, etc.) propaguen tal cual.  La forma del ``self.result``
es la misma que la del use case (back-compat con la SPA).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable

from areas.alimentacion.infrastructure.cache import ExcelCacheManager
from areas.alimentacion.infrastructure.loaders import ExcelLoader
from core.application.log_buffer import LogBuffer, get_log_buffer
from core.application.progress_buffer import ProgressTracker, get_progress_tracker
from core.application.state import AppState, get_app_state
from core.infrastructure.config_manager import ConfigManager
from core.plc.function_base import FunctionBase


class FunctionSubirExcel(FunctionBase):
    """FB que sube el Excel del operario y popula ``AppState``.

    Inyección de dependencias vía constructor (mismo patrón que el
    use case legacy, ver ``upload_excel.py:UploadExcelUseCase``):
      - ``config_manager``: configuración TIA del departamento
        activo.  Obligatorio: si es ``None`` al ejecutar, lanza
        ``RuntimeError``.
      - ``app_state``: estado de la app.  Default Singleton
        (``get_app_state()``).
      - ``progress_tracker``: tracker de progreso.  Default Singleton.
      - ``log``: buffer de logs.  Default Singleton.
      - ``excel_loader_factory``: factoría del loader.  Default
        ``ExcelLoader``.  Inyectada para tests.
      - ``excel_cache_cls``: clase del cache.  Default
        ``ExcelCacheManager``.  Inyectada para tests.

    Runtime params via ``start(**kwargs)``:
      - ``xlsx_path`` (``str | Path``): ruta al ``.xlsx`` a parsear.
        Obligatorio.

    El ``self.result`` se popula con la misma shape que el use case
    legacy::

        {
            "ok": True,
            "summary": {"DispED": N, "DispEA": M, ...},
            "total_dispositivos": int,
            "dimensiones": {...},  # cache.n_max.to_api_dict()
        }
    """

    def __init__(
        self,
        nombre: str = "subir_excel",
        config_manager: ConfigManager | None = None,
        app_state: AppState | None = None,
        progress_tracker: ProgressTracker | None = None,
        log: LogBuffer | None = None,
        excel_loader_factory: Callable[..., ExcelLoader] = ExcelLoader,
        excel_cache_cls: type[ExcelCacheManager] = ExcelCacheManager,
    ) -> None:
        super().__init__(nombre)
        self._config = config_manager
        self._state: AppState = (
            app_state if app_state is not None else get_app_state()
        )
        self._progress: ProgressTracker = (
            progress_tracker if progress_tracker is not None
            else get_progress_tracker()
        )
        self._log: LogBuffer = log if log is not None else get_log_buffer()
        self._loader_factory = excel_loader_factory
        self._cache_cls = excel_cache_cls
        # Estado entre ticks (atributos internos, empiezan vacíos).
        self._xlsx_path: str = ""
        self._cache: Any = None  # ExcelCache, tipado Any para evitar import cíclico

    async def _tick_locked(self) -> None:
        assert self._lock.locked()

        if self.nStep == 10:
            self._step_arrancar()
        elif self.nStep == 20:
            await self._step_parsear()
        elif self.nStep == 30:
            self._step_volcar_y_result()

    # ------------------------------------------------------------------
    # Pasos del state machine
    # ------------------------------------------------------------------

    def _step_arrancar(self) -> None:
        """nStep=10→20: pre-flight.  Valida config y captura xlsx_path."""
        if self._config is None:
            raise RuntimeError(
                "FunctionSubirExcel requiere config_manager explícito. "
                "Inyéctalo en el constructor."
            )
        xlsx_path = self._params.get("xlsx_path")
        if not xlsx_path:
            raise ValueError(
                "FunctionSubirExcel.start(xlsx_path=...) es obligatorio"
            )
        self._xlsx_path = str(xlsx_path)
        self.nStep = 20

    async def _step_parsear(self) -> None:
        """nStep=20→30: parsea el xlsx (en hilo) y guarda en cache.

        Emite la stage ``parsear_excel`` al ``ProgressTracker``.
        Re-lanza cualquier excepción para que el wrapper de la base
        la capture y ponga el FB en ``n_error`` con ``error_msg``.
        """
        self._progress.start_stage("parsear_excel")
        try:
            loader = self._loader_factory(config_manager=self._config)
            cache = await asyncio.to_thread(loader.load, self._xlsx_path)
            await self._cache_cls.put(cache)
            total_devs = sum(len(v) for v in cache.dispositivos.values())
            self._progress.finish_stage(
                "parsear_excel",
                f"{total_devs} dispositivos parseados",
            )
            self._cache = cache
            self.nStep = 30
        except Exception as e:
            self._log.error(f"[excel/parse] Fallo al parsear el Excel: {e}")
            raise

    def _step_volcar_y_result(self) -> None:
        """nStep=30→99: vuelca AppState, construye summary y result.

        Emite la stage ``volcar_appstate``.  Loggea el éxito con el
        conteo por tipo canónico (mismo shape que el use case legacy).
        """
        self._progress.start_stage("volcar_appstate")
        try:
            for hw, devices_tuple in self._cache.dispositivos.items():
                # Back-compat con la SPA: poblar ``state.dispositivos_<hw>``
                # desde ``cache.dispositivos`` (la SPA espera ``list``,
                # no ``tuple``).
                self._state.set_devices(hw, list(devices_tuple))
            self._state.dimensiones = self._cache.n_max
            self._state.excel_cache = self._cache
            self._state.excel_path = self._cache.excel_path
            self._progress.finish_stage(
                "volcar_appstate", "Estado actualizado"
            )
        except Exception as e:
            self._log.error(f"[excel/state] Fallo al volcar AppState: {e}")
            raise

        # Summary con la shape legacy: {tipo_canonica: count}.
        summary: dict[str, int] = {}
        for hw in self._config.list_hw_types_active():
            target = self._config.get_excel_target_for(hw)
            if target is None:
                continue
            canonica = target.get("canonical", "")
            if not canonica:
                continue
            devices_tuple = self._cache.dispositivos.get(hw, ())
            summary[canonica] = len(devices_tuple)

        n_procesos = len(self._cache.procesos)
        n_preal = len(self._cache.parametros_real)
        n_pint = len(self._cache.parametros_int)
        n_alarmas = len(self._cache.alarmas)
        self._log.success(
            f"[excel/load] Carga maestra: {sum(summary.values())} "
            f"dispositivos ({len(summary)} tipos), {n_procesos} "
            f"procesos, {n_preal} parámetros reales, {n_pint} "
            f"parámetros enteros, {n_alarmas} alarmas."
        )

        self.result = {
            "ok": True,
            "summary": summary,
            "total_dispositivos": sum(summary.values()),
            "dimensiones": self._cache.n_max.to_api_dict(),
        }
        self.nStep = self.n_done
