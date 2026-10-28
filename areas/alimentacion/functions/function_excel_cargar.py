"""FB que sube el Excel del operario y popula ``AppCache``.

Hereda de ``FunctionBase`` (plantilla con Zona 0 de inyeccion de
deps). La logica pura vive en ``helpers/excel/excel_upload.py``;
aqui solo esta la state machine + tracker + 1 paso.

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
        "software": {...},
    }

Propiedad del temporal: el router escribe el ``.xlsx`` subido a un
tempfile y encola este FB con su ``xlsx_path``. Quien lo lee es el
FB, asi que quien lo borra es el FB (``execute()`` lo hace en un
``finally``): el temporal no sobrevive ni a un fallo del parseo ni a
una cancelacion.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from core.composition.plc_function_base import FunctionBase
from core.infrastructure.log.log_web_bridge import install_web_level
from core.runtime.app_cache import AppCache, get_app_cache

logger = logging.getLogger(__name__)
# Asegura que ``Logger.web/ok`` existen en tests/scripts (idempotente).
install_web_level()


class FunctionExcelCargar(FunctionBase):
    """FB: carga el Excel del operario y popula ``AppCache``."""

    # ==================================================================
    # CONFIGURACION ESTATICA DEL FB
    # ==================================================================

    # TOCAR Zona 1: timeout por step. Parsear el Excel puede tardar
    # ~5-10s en cold-start (load + 10 parsers). Holgura a 30s.
    STEP_TIMEOUT_S: float = 30.0

    # Area fija: este FB solo opera sobre ``alimentacion``. Cualquier
    # cambio requiere refactor a un ``area_id`` inyectable.
    AREA_ID: str = "alimentacion"

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
        (1, "Parsear y volcar Excel",       "_stage_1_parsear_y_volcar"),
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
        app_cache: AppCache | None = None,
    ) -> None:
        super().__init__(
            nombre=nombre,
            titulo=titulo,
            steps=steps if steps is not None else [
                {"nombre": "Parsear y volcar Excel"},
            ],
            tracker=tracker,
        )
        # ZONA 0: deps inyectadas
        self._config = config_manager
        self._tia_client = tia_client  # No usado en este FB.
        self._build_cache = build_cache  # No usado en este FB.
        # Deps especificas
        # ``excel_loader_factory`` se importa lazy en run_step (ZONA 4)
        # para evitar import circular entre ``function_excel_cargar`` y
        # ``helpers/excel/excel_upload``.
        self._loader_factory = excel_loader_factory
        self._app_cache: AppCache = (
            app_cache if app_cache is not None else get_app_cache()
        )
        # ZONA 3: estado entre ticks
        self._xlsx_path: str = ""

    # ==================================================================
    # HOOK 0: execute()  (ciclo de vida del temporal)
    # ==================================================================

    def execute(self, **params: Any) -> Any:
        """Ejecuta el FB y borra el temporal al terminar (OK o error).

        Override del entry point del OB1 (``FunctionBase.execute``).
        El router escribe el ``.xlsx`` subido a un tempfile y encola
        este FB con su ``xlsx_path``: quien lo lee es el FB, asi que
        el borrado va aqui y no en el router. El ``finally`` lo hace
        garantizado para todos los caminos de salida: parseo OK,
        parseo con error, cancelacion o params invalidos.
        """
        try:
            return super().execute(**params)
        finally:
            self._borrar_temporal()

    def _borrar_temporal(self) -> None:
        """Borra el ``.xlsx`` temporal de esta carga (si existe).

        Best-effort: si el fichero ya no esta (ruta de test, o
        borrado por otro camino) no hay nada que hacer y el error no
        se propaga (el FB no debe caer por un cleanup).
        """
        path = self._xlsx_path
        if not path:
            return
        try:
            os.unlink(path)
        except OSError:
            logger.debug(
                f"[{self.nombre}] temporal no borrado: {path}"
            )
        finally:
            self._xlsx_path = ""

    # ==================================================================
    # HOOK 1: on_start  (ZONA 3: validar params)
    # ==================================================================

    def on_start(self, **params: Any) -> None:
        """Pre-flight: capturar y validar ``xlsx_path``."""
        # Limpia la ruta de la carga anterior: si esta ejecucion no
        # recibe ``xlsx_path``, el cleanup no debe tocar el temporal
        # de otro trabajo.
        self._xlsx_path = ""
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

    def run_step(self, idx: int, **params: Any) -> str:
        """CASE del unico paso (dispatch declarativo via tabla ``STAGES``).

        Itera la tabla ``STAGES`` declarada arriba de la clase; cada
        tupla ``(idx, nombre, atributo_metodo)`` mapea el step logico
        del FB al metodo real ``_stage_N_<nombre>`` que lo implementa.
        """
        # Lazy import para evitar ciclo con helpers/excel/excel_upload.
        from areas.alimentacion.helpers.excel.excel_upload import (
            parse_excel_to_cache,
        )
        from areas.alimentacion.helpers.excel.excel_loader import ExcelLoader

        if self._config is None:
            raise RuntimeError(
                "FunctionExcelCargar requiere config_manager explicito. "
                "Inyectalo en el constructor al registrar el FB."
            )

        step_nombre = self.steps[idx]["nombre"]
        for _s_idx, s_nombre, s_attr in self.STAGES:
            if s_nombre == step_nombre:
                handler = getattr(self, s_attr)
                result = handler()
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
        # Lectura sincronica del cache desde AppCache (la fuente de
        # verdad vive en ``app_cache.area(area_id).excel_full``; este
        # FB la escribio en el stage unico via ``parse_excel_to_cache``).
        # Protegido: si el cache no esta disponible, el FB no debe caer
        # en ``on_finish`` (el trabajo ya se hizo).
        dimensiones = None
        software = None
        try:
            from core.runtime.excel_cache import excel_get_full
            cache = excel_get_full(self._app_cache, self.AREA_ID)
            if cache is not None:
                dimensiones = cache.n_max.to_api_dict()
                software = {
                    "procesos": len(cache.procesos),
                    "preal": len(cache.parametros_real),
                    "pint": len(cache.parametros_int),
                    "alarmas": len(cache.alarmas),
                    "n_max_total": len(cache.n_max.to_api_dict()),
                }
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                f"[{self.nombre}] cache no disponible en on_finish: {exc}"
            )
        self.result = {
            "ok": True,
            "summary": self._stats.get("parsear_excel", {}).get("summary", {}),
            "total_dispositivos": self._stats.get("parsear_excel", {}).get(
                "total_dispositivos", 0
            ),
            "dimensiones": dimensiones,
            "software": software,
        }
        # El "ok" con el resumen completo lo emite el FB (no el
        # router): con el patron OB1 el router ya respondio 202 antes
        # de que el Excel estuviera cargado.
        self._log_resumen(software)

    def _log_resumen(self, software: dict[str, int] | None) -> None:
        """Emite el ``ok`` con el resumen del Excel ya cargado.

        Plan living TRAZABILIDAD_LOGGING §5 (operacion 1): el operario
        ve en la consola web "Excel cargado: N disp + N proc + ...".
        No debe tumbar el FB si el resumen no se puede construir.
        """
        sw = software or {}
        total = 0
        if isinstance(self.result, dict):
            total = self.result.get("total_dispositivos", 0) or 0
        try:
            logger.ok(
                f"Excel cargado: {total} disp + "
                f"{sw.get('procesos', 0)} proc + "
                f"{sw.get('preal', 0)} preal + "
                f"{sw.get('pint', 0)} pint + "
                f"{sw.get('alarmas', 0)} alm + "
                f"{sw.get('n_max_total', 0)} N_MAX"
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                f"[{self.nombre}] no se pudo emitir el resumen: {exc}"
            )

    # ==================================================================
    # Stages del FB (ZONA 4: metodos privados numerados).
    #
    # Cada ``_stage_N_<nombre>`` corresponde a UNA entrada de la tabla
    # ``STAGES`` arriba. Si cambias el flujo del stage, cambia la
    # tabla tambien.
    # ==================================================================

    def _stage_1_parsear_y_volcar(self) -> str:
        """Stage 1: parsea el ``.xlsx`` y lo escribe al ``AppCache``.

        Lazy import para evitar ciclo entre este FB y
        ``helpers/excel/excel_upload``. ``parse_excel_to_cache``
        escribe el cache completo y rederiva el activo en el
        ``AppCache`` del area; este stage solo calcula el ``summary``
        con la shape legacy (claves canonicas desde el config).
        """
        from areas.alimentacion.helpers.excel.excel_loader import ExcelLoader
        from areas.alimentacion.helpers.excel.excel_upload import (
            parse_excel_to_cache,
        )

        cache = parse_excel_to_cache(
            config_manager=self._config,
            excel_path=self._xlsx_path,
            app_cache=self._app_cache,
            area_id=self.AREA_ID,
            loader_factory=self._loader_factory or ExcelLoader,
        )
        total_devs = sum(
            len(v) for v in cache.dispositivos.values()
        )
        # ``summary`` con la shape legacy: ``{tipo_canonica: count}``.
        # Las claves canonicas vienen del config_manager (el cache no
        # expone directamente ``DispED``, ``DispEA``, ...).
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
        self._stats["parsear_excel"] = {
            "xlsx_path": self._xlsx_path,
            "total_dispositivos": total_devs,
            "summary": summary,
        }
        logger.debug(
            f"[{self.nombre}] Carga: {total_devs} dispositivos "
            f"({len(summary)} tipos)"
        )
        return f"{total_devs} dispositivos parseados"


__all__ = ["FunctionExcelCargar"]