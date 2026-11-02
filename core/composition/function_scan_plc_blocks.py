"""FB core: escanear bloques/tag tables/UDTs de un PLC contra TIA Portal.

Encapsula la operacion one-shot "scan de bloques de un PLC". Tras
``n_done``, el resultado queda cacheado en ``app_cache.plc_blocks``
(contenedor unico en ``core.runtime.app_cache``) y cualquier caller
puede hacer lookups sincronos via ``plc_blocks_get(app_cache, plc_name)``.

Hereda directo de ``FunctionBase`` (no del template) porque su logica
es especifica y no aporta Zona 0 generica.

Runtime params via ``start(**kwargs)``:
  - ``plc_name`` (str): nombre del PLC a escanear. Obligatorio.
  - ``force_refresh`` (bool, default False): si True, invalida el
    cache IT antes de re-escanear.

El ``self.result`` se popula con la shape::
    {
        "ok": True,
        "plc_name": str,
        "n_blocks": int,
        "n_tag_tables": int,
        "n_udts": int,
        "scanned_at": str,  # ISO
    }

Steps (2). Cada step se declara encima de su propio codigo con ``@step``
y devuelve su detail:
  - check_cache -> mira si el cache de bloques del PLC sigue fresco
  - escanear    -> escanea bloques, tablas de tags y UDTs del PLC
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from core.composition.fb_step import step
from core.composition.plc_function_base import FunctionBase
from core.infrastructure.log.log_web_bridge import install_web_level
from core.runtime.app_cache import AppCache, get_app_cache

logger = logging.getLogger(__name__)
# Asegura que ``Logger.web/ok`` existen en tests/scripts (idempotente).
install_web_level()


class FunctionScanPlcBlocks(FunctionBase):
    """FB core: escanea bloques/tag tables/UDTs de un PLC."""

    # ==================================================================
    # CONFIGURACION ESTATICA DEL FB
    # ==================================================================

    # Un scan contra TIA Portal puede tardar ~3-10s segun tamano del
    # proyecto. Holgura generosa.
    STEP_TIMEOUT_S: float = 60.0

    # ==================================================================
    # CONSTRUCTOR
    # ==================================================================

    def __init__(
        self,
        nombre: str = "scan_plc_blocks",
        titulo: str = "Escanear bloques de un PLC",
        tracker: Any = None,
        # ── ZONA 0: deps comunes ──
        config_manager: Any = None,
        tia_client: Any = None,
        build_cache: Any = None,
        # ── Deps especificas de este FB ──
        app_cache: AppCache | None = None,
    ) -> None:
        super().__init__(
            nombre=nombre,
            titulo=titulo,
            tracker=tracker,
        )
        # ZONA 0: deps inyectadas.
        self._config = config_manager  # No usado en este FB.
        self._tia_client = tia_client
        self._build_cache = build_cache  # No usado en este FB.
        # Deps especificas.
        self._app_cache: AppCache = (
            app_cache if app_cache is not None else get_app_cache()
        )
        # ZONA 3: estado entre ticks. El ctx se recrea en cada
        # ``on_start()``: es el estado del run en curso.
        self._ctx: "ScanPlcBlocksContext | None" = None

    # ==================================================================
    # HOOK 1: on_start  (ZONA 3: validar params)
    # ==================================================================

    def on_start(self, **params: Any) -> None:
        """Pre-flight: validar params y crear el ctx del run."""
        plc_name = params.get("plc_name")
        if not plc_name:
            raise ValueError(
                "FunctionScanPlcBlocks.execute(plc_name=...) es obligatorio"
            )
        if self._tia_client is None:
            raise RuntimeError(
                "FunctionScanPlcBlocks requiere tia_client explicito. "
                "Inyectalo en el constructor al registrar el FB."
            )
        self._ctx = ScanPlcBlocksContext(
            plc_name=str(plc_name),
            force_refresh=bool(params.get("force_refresh", False)),
        )
        logger.debug(
            f"[{self.nombre}] Iniciando scan de '{self._ctx.plc_name}' "
            f"(force_refresh={self._ctx.force_refresh})"
        )

    # ==================================================================
    # LOS STEPS
    #
    # Cada ``_stage_N_<slug>`` es un step declarado con ``@step``. El
    # motor los recoge en orden de definicion (que es el orden del
    # flujo) y hace el dispatch. El metodo devuelve su detail.
    # ==================================================================

    @step(
        "check_cache",
        descripcion="Mira si el cache de bloques del PLC sigue fresco",
    )
    def _stage_1_check_cache(self) -> str:
        """Si la cache esta fresca y no force_refresh, no re-escanea.

        Para "fresh" usamos el TTL del app_cache; si no hay entrada,
        se sigue al escaneo.
        """
        # Lazy import para evitar ciclo con core.infrastructure.tia.
        from core.infrastructure.tia.tia_cache import plc_blocks_get

        if not self._ctx.force_refresh:
            cached = plc_blocks_get(self._app_cache, self._ctx.plc_name)
            if cached is not None:
                self._stats["cache_hit"] = {
                    "plc_name": self._ctx.plc_name,
                    "n_blocks": len(cached.blocks),
                    "n_tag_tables": len(cached.tag_tables),
                }
                return f"cache fresco: {len(cached.blocks)} bloques"
        return "cache no fresco o force_refresh: re-escaneando"

    @step(
        "escanear",
        descripcion="Escanea bloques, tablas de tags y UDTs del PLC",
    )
    def _stage_2_escanear(self) -> str:
        """Escanea el PLC y puebla el cache de bloques."""
        from core.infrastructure.tia.tia_cache import scan_plc_blocks

        cache = scan_plc_blocks(
            self._ctx.plc_name,
            force_refresh=self._ctx.force_refresh,
            tia_client=self._tia_client,
            app_cache=self._app_cache,
            timeout_s=self.STEP_TIMEOUT_S,
        )
        self._stats["escanear"] = {
            "plc_name": self._ctx.plc_name,
            "n_blocks": len(cache.blocks),
            "n_tag_tables": len(cache.tag_tables),
            "n_udts": len(cache.udts),
            "scanned_at": cache.scanned_at.isoformat(),
        }
        logger.debug(
            f"[{self.nombre}] Scan completo: "
            f"{len(cache.blocks)} bloques, "
            f"{len(cache.tag_tables)} tablas, "
            f"{len(cache.udts)} UDTs"
        )
        return (
            f"{len(cache.blocks)} bloques · "
            f"{len(cache.tag_tables)} tablas · "
            f"{len(cache.udts)} UDTs"
        )

    # ==================================================================
    # HOOK 3: on_finish  (ZONA 5: vuelco del result)
    # ==================================================================

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` con la shape del FB.

        El resumen del scan lo emite aqui: el router ya respondio
        ``202`` cuando el scan todavia no habia terminado.
        """
        self._log_resumen()
        scan_stats = self._stats.get("escanear", {})
        cache_hit_stats = self._stats.get("cache_hit", {})
        plc_name = self._ctx.plc_name if self._ctx is not None else ""
        # Si venimos de cache_hit, ``escanear`` no se ejecuto.
        if scan_stats:
            self.result = {
                "ok": True,
                "plc_name": scan_stats.get("plc_name", plc_name),
                "n_blocks": scan_stats.get("n_blocks", 0),
                "n_tag_tables": scan_stats.get("n_tag_tables", 0),
                "n_udts": scan_stats.get("n_udts", 0),
                "scanned_at": scan_stats.get("scanned_at"),
                "from_cache": False,
            }
        elif cache_hit_stats:
            self.result = {
                "ok": True,
                "plc_name": cache_hit_stats.get("plc_name", plc_name),
                "n_blocks": cache_hit_stats.get("n_blocks", 0),
                "n_tag_tables": cache_hit_stats.get("n_tag_tables", 0),
                "n_udts": 0,
                "scanned_at": None,
                "from_cache": True,
            }
        else:
            self.result = {
                "ok": True,
                "plc_name": plc_name,
                "n_blocks": 0,
                "n_tag_tables": 0,
                "n_udts": 0,
                "scanned_at": None,
                "from_cache": False,
            }

    def _log_resumen(self) -> None:
        """Emite el resumen del scan para la consola del operario."""
        stats = self._stats.get("escanear") or self._stats.get("cache_hit") or {}
        plc_name = self._ctx.plc_name if self._ctx is not None else ""
        logger.ok(
            f"PLC '{plc_name}' cache: "
            f"{stats.get('n_blocks', 0)} bloques, "
            f"{stats.get('n_tag_tables', 0)} tablas, "
            f"{stats.get('n_udts', 0)} UDTs"
        )


@dataclass
class ScanPlcBlocksContext:
    """Estado del run del FB de scan de bloques."""

    plc_name: str
    force_refresh: bool


__all__ = ["FunctionScanPlcBlocks", "ScanPlcBlocksContext"]
