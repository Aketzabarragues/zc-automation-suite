"""Application Layer - Carga del Excel corporativo (subdominio alimentación).

Caso de uso: extraer la lógica de negocio del endpoint
``POST /api/v1/excel/upload`` para que sea testeable sin FastAPI,
reusable desde otros puntos de entrada (MCP, jobs, recargas) y
preparada para la Fase 7 (``GenerateProcessUseCase`` se compondrá
con este).

Responsabilidades del use case:
  1. Parsear el ``.xlsx`` vía ``ExcelLoader`` (en thread, no bloquea
     el event loop de asyncio).
  2. Cachear el resultado en ``ExcelCacheManager`` (singleton IT).
  3. Volcar el resultado al ``AppState`` (devices, dimensiones,
     excel_cache, excel_path) en la shape legacy que la SPA y los
     routers siguen leyendo.
  4. Construir el ``summary`` con la misma lógica data-driven del
     endpoint (iterando ``ConfigManager.list_hw_types_active()`` y
     resolviendo el ``canonical`` por hw).
  5. Emitir logs y progress (stages ``parsear_excel`` y
     ``volcar_appstate``).

El handler FastAPI (``areas/alimentacion/interfaces/web/excel.py``)
se queda en la orquestación HTTP pura: recibir el ``UploadFile``,
escribirlo a un tempfile, abrir el tracker, delegar en este use case
y devolver el dict resultante. No contiene lógica de negocio.

Stages de progress (alineado con ``.clinerules`` §7):
  ``["parsear_excel", "volcar_appstate"]``

Trade-off documentado: este use case lanza ``HTTPException(400)``
directamente cuando el parseo o el volcado fallan. Se hace así por
dos motivos:
  1. Coherencia con el comportamiento histórico del endpoint
     (back-compat con los 3 tests existentes de
     ``test_excel_endpoint_with_cache.py``).
  2. Cero valor añadir una excepción de dominio intermedia: el
     único consumidor hoy es el router FastAPI, y FastAPI entiende
     ``HTTPException`` nativamente.

La consecuencia negativa es que este use case deja de ser
transport-agnostic: si mañana se quisiera invocar desde un job
batch o desde otro protocolo, habría que refactorizar para usar
una excepción de dominio. Por ahora, la simplicidad gana.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from areas.alimentacion.infrastructure.cache import ExcelCacheManager
from areas.alimentacion.infrastructure.loaders import ExcelLoader
from core.application.log_buffer import LogBuffer, get_log_buffer
from core.application.progress_buffer import ProgressTracker, get_progress_tracker
from core.application.state import AppState, get_app_state
from core.infrastructure.config_manager import ConfigManager


class UploadExcelUseCase:
    """Caso de uso: carga el Excel corporativo y popula ``AppState``.

    Atributos:
        excel_cache_manager: clase (no instancia) del cache manager.
            El real (``ExcelCacheManager``) expone ``put`` /
            ``get`` / ``clear`` como ``@classmethod`` sobre un
            estado a nivel de clase. Se pasa la clase para que los
            tests puedan inyectar un fake sin tocar el singleton
            global.
        config_manager: configuración TIA del departamento activo.
            Si es ``None`` al ejecutar, se lanza ``RuntimeError``
            (el router siempre lo inyecta vía ``Depends``).
        app_state: estado de la app. Por defecto el Singleton
            (``get_app_state()``).
        progress_tracker: tracker de progreso. Por defecto el
            Singleton (``get_progress_tracker()``).
        log: buffer de logs. Por defecto el Singleton
            (``get_log_buffer()``).
    """

    def __init__(
        self,
        excel_cache_manager: type[ExcelCacheManager] = ExcelCacheManager,
        config_manager: ConfigManager | None = None,
        app_state: AppState | None = None,
        progress_tracker: ProgressTracker | None = None,
        log: LogBuffer | None = None,
    ) -> None:
        self._cache_cls = excel_cache_manager
        self._config = config_manager
        self._state = app_state if app_state is not None else get_app_state()
        self._progress: ProgressTracker = (
            progress_tracker if progress_tracker is not None
            else get_progress_tracker()
        )
        self._log: LogBuffer = log if log is not None else get_log_buffer()

    # ── API pública ──────────────────────────────────────────────────────

    async def execute(self, excel_path: str | Path) -> dict[str, Any]:
        """Carga el Excel desde ``excel_path``, popula el cache y el
        ``AppState``, y devuelve el response del endpoint.

        Args:
            excel_path: ruta al ``.xlsx`` a parsear (absoluta o
                relativa). El cache guarda la versión
                ``absolute()``.

        Returns:
            ``dict`` con la shape::

                {
                    "ok": True,
                    "summary": {"DispED": 1, "DispEA": 1, ...},
                    "total_dispositivos": 6,
                    "dimensiones": {<api_dict de n_max>},
                }

        Raises:
            HTTPException(400): si el parseo o el volcado al
                ``AppState`` fallan. Se loggea el error y se cierra
                el ``ProgressTracker`` con ``success=False`` antes
                de propagar.

        Note:
            Asume que el caller ya hizo ``progress.begin(...)``
            con los stages ``["parsear_excel", "volcar_appstate"]``.
            El use case solo emite ``start_stage`` / ``finish_stage``
            y ``finish(success=...)``. El handler llama a
            ``progress.finish(success=True)`` tras un ``execute``
            exitoso.
        """
        if self._config is None:
            raise RuntimeError(
                "UploadExcelUseCase.execute requiere un config_manager "
                "explícito. El router debe inyectarlo vía Depends."
            )

        # ── Stage 1: parsear_excel ────────────────────────────────────
        self._progress.start_stage("parsear_excel")
        try:
            loader = ExcelLoader(config_manager=self._config)
            cache = await asyncio.to_thread(loader.load, excel_path)
            await self._cache_cls.put(cache)
            total_devs = sum(len(v) for v in cache.dispositivos.values())
            self._progress.finish_stage(
                "parsear_excel",
                f"{total_devs} dispositivos parseados",
            )

            # ── Stage 2: volcar_appstate ──────────────────────────────
            self._progress.start_stage("volcar_appstate")
            # Back-compat con la SPA: poblar ``state.dispositivos_<hw>``
            # desde ``cache.dispositivos`` (la SPA sigue esperando
            # ``list``, no ``tuple``).
            for hw, devices_tuple in cache.dispositivos.items():
                self._state.set_devices(hw, list(devices_tuple))
            self._state.dimensiones = cache.n_max
            # El cache vive en el área de alimentación, pero AppState
            # lo expone como placeholder ``Any`` (ver ``state.py``).
            self._state.excel_cache = cache
            self._state.excel_path = cache.excel_path
            self._progress.finish_stage(
                "volcar_appstate", "Estado actualizado"
            )
        except Exception as exc:
            self._progress.finish(success=False, error=str(exc))
            self._log.error(
                f"[excel/parse] Fallo al parsear el Excel: {exc}"
            )
            raise HTTPException(
                status_code=400, detail=f"excel_upload failed: {exc}"
            ) from exc

        # ── Summary + log de éxito ────────────────────────────────────
        # ``summary`` con la shape legacy: ``{tipo_canonica: count}``.
        # Como el cache no expone directamente las claves canónicas
        # (``DispED``...), derivamos el summary a partir de los
        # ``hw_type`` de ``config_manager``.
        summary: dict[str, int] = {}
        for hw in self._config.list_hw_types_active():
            target = self._config.get_excel_target_for(hw)
            if target is None:
                continue
            canonica = target.get("canonical", "")
            if not canonica:
                continue
            devices_tuple = cache.dispositivos.get(hw, ())
            summary[canonica] = len(devices_tuple)

        n_procesos = len(cache.procesos)
        n_preal = len(cache.parametros_real)
        n_pint = len(cache.parametros_int)
        n_alarmas = len(cache.alarmas)
        self._log.success(
            f"[excel/load] Carga maestra: {sum(summary.values())} "
            f"dispositivos ({len(summary)} tipos), {n_procesos} "
            f"procesos, {n_preal} parámetros reales, {n_pint} "
            f"parámetros enteros, {n_alarmas} alarmas."
        )

        return {
            "ok": True,
            "summary": summary,
            "total_dispositivos": sum(summary.values()),
            # ``to_api_dict()`` en vez de ``dataclasses.asdict``:
            # oculta el campo ``extras`` (interno / futuro) de la
            # respuesta al cliente del upload. Mismo shape que
            # ``dataclasses.asdict`` salvo por la ausencia de
            # ``extras``.
            "dimensiones": cache.n_max.to_api_dict(),
        }


__all__ = ["UploadExcelUseCase"]
