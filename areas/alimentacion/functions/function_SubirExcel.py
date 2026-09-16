"""FB que sube el Excel del operario y popula ``AppState``.

Migrado del use case legacy ``application/use_cases/upload_excel.py``
(sept-2026, refactor de areas). Hereda de ``FunctionTemplate``
(plantilla con Zona 0 de inyeccion de deps). La logica pura vive en
``helpers/excel/excel_upload.py``; aqui solo esta la state machine +
tracker + 2 pasos.

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
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.composition.plc_function_base import FunctionBase
from core.runtime.app_state import AppState, get_app_state

logger = logging.getLogger(__name__)


class FunctionSubirExcel(FunctionBase):
    """FB: carga el Excel del operario y popula ``AppState``."""

    # ==================================================================
    # CONFIGURACION ESTATICA DEL FB
    # ==================================================================

    # TOCAR Zona 1: timeout por step. Parsear el Excel puede tardar
    # ~5-10s en cold-start (load + 10 parsers). Holgura a 30s.
    STEP_TIMEOUT_S: float = 30.0

    # ==================================================================
    # CONSTRUCTOR
    # ==================================================================

    def __init__(
        self,
        nombre: str = "subir_excel",
        titulo: str = "Subir Excel corporativo",
        steps: list[dict[str, Any]] | None = None,
        tracker: Any = None,
        # ── ZONA 0: deps comunes ──
        config_manager: Any = None,
        tia_client: Any = None,
        build_cache: Any = None,
        # ── Deps especificas de este FB ──
        excel_loader_factory: type = None,
        excel_cache_cls: type = None,
        app_state: AppState | None = None,
    ) -> None:
        super().__init__(
            nombre=nombre,
            titulo=titulo,
            steps=steps if steps is not None else [
                {"nombre": "parsear_excel"},
                {"nombre": "volcar_appstate"},
            ],
            tracker=tracker,
        )
        # ZONA 0: deps inyectadas
        self._config = config_manager
        self._tia_client = tia_client  # No usado en este FB.
        self._build_cache = build_cache  # No usado en este FB.
        # Deps especificas
        # ``excel_loader_factory`` y ``excel_cache_cls`` se importan
        # lazily en run_step (ZONA 4) para evitar import circular
        # entre ``function_SubirExcel`` y ``helpers/excel/excel_upload``.
        self._loader_factory = excel_loader_factory
        self._cache_cls = excel_cache_cls
        self._state: AppState = (
            app_state if app_state is not None else get_app_state()
        )
        # ZONA 3: estado entre ticks
        self._xlsx_path: str = ""

    # ==================================================================
    # HOOK 1: on_start  (ZONA 3: validar params)
    # ==================================================================

    def on_start(self, **params: Any) -> None:
        """Pre-flight: capturar y validar ``xlsx_path``."""
        xlsx_path = params.get("xlsx_path")
        if not xlsx_path:
            raise ValueError(
                "FunctionSubirExcel.start(xlsx_path=...) es obligatorio"
            )
        self._xlsx_path = str(xlsx_path)
        logger.web(
            f"[{self.nombre}] Iniciando carga desde {self._xlsx_path}"
        )

    # ==================================================================
    # HOOK 2: run_step  (ZONA 4: CASE por etapa)
    # ==================================================================

    async def run_step(self, idx: int, **params: Any) -> str:
        """CASE de los 2 pasos."""
        # Lazy import para evitar ciclo con helpers/excel/excel_upload.
        from areas.alimentacion.helpers.excel.excel_upload import (
            dump_cache_to_state,
            parse_excel_to_cache,
        )
        from areas.alimentacion.helpers.excel.excel_cache_manager import (
            ExcelCacheManager,
        )
        from areas.alimentacion.helpers.excel.excel_loader import ExcelLoader

        if self._config is None:
            raise RuntimeError(
                "FunctionSubirExcel requiere config_manager explicito. "
                "Inyectalo en el constructor al registrar el FB."
            )

        step_nombre = self.steps[idx]["nombre"]
        match step_nombre:
            case "parsear_excel":
                cache = await parse_excel_to_cache(
                    config_manager=self._config,
                    excel_path=self._xlsx_path,
                    cache_cls=self._cache_cls or ExcelCacheManager,
                    loader_factory=self._loader_factory or ExcelLoader,
                )
                # Guardamos el cache en self._stats para ``on_finish``.
                total_devs = sum(
                    len(v) for v in cache.dispositivos.values()
                )
                self._stats["parsear_excel"] = {
                    "xlsx_path": self._xlsx_path,
                    "total_dispositivos": total_devs,
                }
                return f"{total_devs} dispositivos parseados"

            case "volcar_appstate":
                # Recuperar el cache del cache global (lo puso
                # ``parse_excel_to_cache`` via ``ExcelCacheManager.put``).
                # Import desde el submódulo (no del paquete ``excel``
                # porque su ``__init__.py`` está vacío por convención,
                # ver b36d147).
                from areas.alimentacion.helpers.excel.excel_cache_manager import (
                    ExcelCacheManager,
                )
                cache = await ExcelCacheManager.get()
                if cache is None:
                    raise RuntimeError(
                        "cache vacio tras parsear_excel. "
                        "Esto no deberia ocurrir."
                    )
                summary_dict = dump_cache_to_state(
                    cache=cache,
                    app_state=self._state,
                    config_manager=self._config,
                )
                self._stats["volcar_appstate"] = {
                    "summary": summary_dict["summary"],
                    "total_dispositivos": summary_dict["total_dispositivos"],
                }
                # Log de exito del volcado al AppState.
                logger.ok(
                    f"[{self.nombre}] Carga: {summary_dict['total_dispositivos']} "
                    f"dispositivos ({len(summary_dict['summary'])} tipos)"
                )
                return "Estado actualizado"

            case _:
                raise ValueError(f"step no soportado: {step_nombre!r}")

    # ==================================================================
    # HOOK 3: on_finish  (ZONA 5: vuelco del result)
    # ==================================================================

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` con la shape legacy del endpoint."""
        # Recuperamos el cache para devolver las ``dimensiones``.
        from areas.alimentacion.helpers.excel.excel_cache_manager import (
            ExcelCacheManager,
        )
        # NOTA: en un FB async esto seria await, pero ``on_finish``
        # es sync. El cache ya esta en memoria del Engine global
        # asi que lo recuperamos sync via el ``cache_cls`` directo.
        cache = ExcelCacheManager._state if hasattr(ExcelCacheManager, "_state") else None
        # Si no podemos recuperar el cache sync, lo dejamos a ``None``
        # en dimensiones (la SPA no rompe si ve ``None``).
        dimensiones = cache.n_max.to_api_dict() if cache else None
        self.result = {
            "ok": True,
            "summary": self._stats.get("volcar_appstate", {}).get("summary", {}),
            "total_dispositivos": self._stats.get("volcar_appstate", {}).get(
                "total_dispositivos", 0
            ),
            "dimensiones": dimensiones,
        }


__all__ = ["FunctionSubirExcel"]
