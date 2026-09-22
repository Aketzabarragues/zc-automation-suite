"""FB que sube el Excel del operario y popula ``AppState``.

Hereda de ``FunctionTemplate`` (plantilla con Zona 0 de inyeccion
de deps). La logica pura vive en ``helpers/excel/excel_upload.py``;
aqui solo esta la state machine + tracker + 2 pasos.

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


class FunctionExcelCargar(FunctionBase):
    """FB: carga el Excel del operario y popula ``AppState``."""

    # ==================================================================
    # CONFIGURACION ESTATICA DEL FB
    # ==================================================================

    # TOCAR Zona 1: timeout por step. Parsear el Excel puede tardar
    # ~5-10s en cold-start (load + 10 parsers). Holgura a 30s.
    STEP_TIMEOUT_S: float = 30.0

    # Tabla declarativa de stages. Cada tupla: (idx, "nombre_step",
    # "atributo_metodo_en_el_FB"). El ``run_step`` dispatcha contra
    # esta tabla en vez de un ``match``/``case`` inline, para que el
    # flujo sea legible arriba de la clase y los tests puedan
    # mockear ``fb._stage_N_<nombre>`` directamente.
    #
    # Convencion:
    #   - ``idx`` correlativo, 1-based.
    #   - ``nombre_step`` debe coincidir con ``self.steps[idx]["nombre"]``
    #     (registrado en __init__). Si cambias uno, cambia el otro.
    #   - ``atributo_metodo`` es un metodo del FB (no externo): un cambio de
    #     signatura requiere actualizar este registro.
    STAGES: list[tuple[int, str, str]] = [
        (1, "parsear_excel",    "_stage_1_parsear_excel"),
        (2, "volcar_appstate",  "_stage_2_volcar_appstate"),
    ]

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
        # entre ``function_excel_cargar`` y ``helpers/excel/excel_upload``.
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
                "FunctionExcelCargar.start(xlsx_path=...) es obligatorio"
            )
        self._xlsx_path = str(xlsx_path)
        logger.debug(
            f"[{self.nombre}] Iniciando carga desde {self._xlsx_path}"
        )

    # ==================================================================
    # HOOK 2: run_step  (ZONA 4: CASE por etapa)
    # ==================================================================

    async def run_step(self, idx: int, **params: Any) -> str:
        """CASE de los 2 pasos (dispatch declarativo via tabla ``STAGES``).

        Itera la tabla ``STAGES`` declarada arriba de la clase; cada
        tupla ``(idx, nombre, atributo_metodo)`` mapea el step logico
        del FB al metodo real ``_stage_N_<nombre>`` que lo implementa.
        """
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
                "FunctionExcelCargar requiere config_manager explicito. "
                "Inyectalo en el constructor al registrar el FB."
            )

        # Tabla declarativa de stages: (idx, nombre, atributo_metodo).
        # Cada stage es un metodo del FB con prefijo ``_stage_N_<nombre>``.
        # El dispatcher de abajo itera esta tabla; no usamos ``match``
        # para que el orden sea visible arriba de la clase y los tests
        # puedan mockear ``fb._stage_N_<nombre>`` directamente.
        #
        # El lookup es por ``nombre`` (no por ``idx``) porque
        # ``FunctionBase._step_ejecutar`` pasa ``idx`` 0-indexed sobre
        # ``self.steps``. El ``idx`` de la tabla STAGES es 1-based y
        # solo se usa para logging legible ("paso 1/2").
        step_nombre = self.steps[idx]["nombre"]
        for _s_idx, s_nombre, s_attr in self.STAGES:
            if s_nombre == step_nombre:
                handler = getattr(self, s_attr)
                result = await handler()
                return result
        raise ValueError(
            f"step {idx} ({step_nombre!r}) no esta en STAGES "
            f"de FunctionExcelCargar"
        )

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
        # NOTA: en un FB async esto seria await, pero ``on_finish``
        # Recuperamos el cache via la ClassVar publica
        # ``ExcelCacheManager._cache``. El atributo ``_state`` no
        # existe y daba None, lo que mostraba '0 proc' aunque el
        # cache tuviera datos.
        cache = ExcelCacheManager._cache
        dimensiones = cache.n_max.to_api_dict() if cache else None
        # Conteos de software para el resumen completo en la consola
        # web (procesos, preal, pint, alarmas, n_max).
        software = None
        if cache is not None:
            software = {
                "procesos": len(cache.procesos),
                "preal": len(cache.parametros_real),
                "pint": len(cache.parametros_int),
                "alarmas": len(cache.alarmas),
                # El router muestra el conteo de N_MAX en el resumen.
                # ``cache.n_max`` es un ``DimensionesDispositivos``
                # (dataclass), no una lista -> usamos ``all_nmax()``
                # que retorna el dict unificado de N_MAX legacy (6) +
                # extras (``extras={}`` por defecto).
                "n_max_total": len(cache.n_max.all_nmax()),
            }
        self.result = {
            "ok": True,
            "summary": self._stats.get("volcar_appstate", {}).get("summary", {}),
            "total_dispositivos": self._stats.get("volcar_appstate", {}).get(
                "total_dispositivos", 0
            ),
            "dimensiones": dimensiones,
            "software": software,
        }

    # ==================================================================
    # Stages del FB (ZONA 4: metodos privados numerados).
    #
    # Cada ``_stage_N_<nombre>`` corresponde a UNA entrada de la tabla
    # ``STAGES`` arriba. Si cambias el flujo del stage, cambia la
    # tabla tambien.
    # ==================================================================

    async def _stage_1_parsear_excel(self) -> str:
        """Stage 1: parsea el ``.xlsx`` con ``parse_excel_to_cache``.

        Lazy import para evitar ciclo entre este FB y
        ``helpers/excel/excel_upload``. Devuelve un resumen legible del
        conteo total de dispositivos parseados.
        """
        from areas.alimentacion.helpers.excel.excel_cache_manager import (
            ExcelCacheManager,
        )
        from areas.alimentacion.helpers.excel.excel_loader import ExcelLoader
        from areas.alimentacion.helpers.excel.excel_upload import (
            parse_excel_to_cache,
        )

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

    async def _stage_2_volcar_appstate(self) -> str:
        """Stage 2: vuelca el cache al ``AppState`` con ``dump_cache_to_state``.

        El cache ya esta en memoria del Engine global (lo puso
        ``parse_excel_to_cache`` via ``ExcelCacheManager.put``). Aqui lo
        recuperamos y lo copiamos al ``AppState``.
        """
        from areas.alimentacion.helpers.excel.excel_cache_manager import (
            ExcelCacheManager,
        )
        from areas.alimentacion.helpers.excel.excel_upload import (
            dump_cache_to_state,
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
        logger.debug(
            f"[{self.nombre}] Carga: {summary_dict['total_dispositivos']} "
            f"dispositivos ({len(summary_dict['summary'])} tipos)"
        )
        return "Estado actualizado"


__all__ = ["FunctionExcelCargar"]
