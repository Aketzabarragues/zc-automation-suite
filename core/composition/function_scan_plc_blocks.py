"""FB core: escanear bloques/tag tables/UDTs de un PLC contra TIA Portal.

Encapsula la operacion one-shot "scan de bloques de un PLC". Tras
``n_done``, el resultado queda cacheado en ``TIADataBloqueCache``
(Singleton en ``core.infrastructure.tia.tia_bloque_cache``) y
cualquier caller puede hacer lookups sincronos via ``TIADataBloqueCache.get``.

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
"""
from __future__ import annotations

from typing import Any

from core.composition.plc_function_base import FunctionBase
from core.runtime.app_state import AppState, get_app_state
from core.runtime.log_buffer import LogBuffer, get_log_buffer


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
        steps: list[dict[str, Any]] | None = None,
        tracker: Any = None,
        # ── ZONA 0: deps comunes ──
        config_manager: Any = None,
        tia_client: Any = None,
        build_cache: Any = None,
        log: Any = None,
        # ── Deps especificas de este FB ──
        app_state: AppState | None = None,
    ) -> None:
        super().__init__(
            nombre=nombre,
            titulo=titulo,
            steps=steps if steps is not None else [
                {"nombre": "check_cache"},
                {"nombre": "escanear"},
            ],
            tracker=tracker,
        )
        # ZONA 0: deps inyectadas.
        self._config = config_manager  # No usado en este FB.
        self._tia_client = tia_client
        self._build_cache = build_cache  # No usado en este FB.
        self._log: LogBuffer = log if log is not None else get_log_buffer()
        # Deps especificas.
        self._state: AppState = (
            app_state if app_state is not None else get_app_state()
        )
        # ZONA 3: estado entre ticks.
        self._plc_name: str = ""
        self._force_refresh: bool = False

    # ==================================================================
    # HOOK 1: on_start  (ZONA 3: validar params)
    # ==================================================================

    def on_start(self, **params: Any) -> None:
        """Pre-flight: capturar y validar ``plc_name``."""
        plc_name = params.get("plc_name")
        if not plc_name:
            raise ValueError(
                "FunctionScanPlcBlocks.start(plc_name=...) es obligatorio"
            )
        self._plc_name = str(plc_name)
        self._force_refresh = bool(params.get("force_refresh", False))
        self._log.info(
            f"[{self.nombre}] Iniciando scan de '{self._plc_name}' "
            f"(force_refresh={self._force_refresh})"
        )

    # ==================================================================
    # HOOK 2: run_step  (ZONA 4: CASE por etapa)
    # ==================================================================

    async def run_step(self, idx: int, **params: Any) -> str:
        """CASE de los 2 pasos."""
        # Lazy import para evitar ciclo con core.infrastructure.tia.
        from core.infrastructure.tia.scan_plc_blocks import scan_plc_blocks
        from core.infrastructure.tia.tia_bloque_cache import TIADataBloqueCache

        if self._tia_client is None:
            raise RuntimeError(
                "FunctionScanPlcBlocks requiere tia_client explicito. "
                "Inyectalo en el constructor al registrar el FB."
            )

        step_nombre = self.steps[idx]["nombre"]
        match step_nombre:
            case "check_cache":
                # Si la cache esta fresca y no force_refresh, saltamos
                # al segundo paso sin re-escanear (el helper hara clear
                # si force_refresh=True). Para "fresh" usamos el TTL
                # del singleton TIADataBloqueCache; si no hay entrada,
                # seguimos al escaneo.
                if not self._force_refresh:
                    cached = await TIADataBloqueCache.get(self._plc_name)
                    if cached is not None:
                        self._stats["cache_hit"] = {
                            "plc_name": self._plc_name,
                            "n_blocks": len(cached.blocks),
                            "n_tag_tables": len(cached.tag_tables),
                        }
                        return f"cache fresco: {len(cached.blocks)} bloques"
                return "cache no fresco o force_refresh: re-escaneando"

            case "escanear":
                cache = await scan_plc_blocks(
                    self._plc_name,
                    force_refresh=self._force_refresh,
                    tia_client=self._tia_client,
                    timeout_s=self.STEP_TIMEOUT_S,
                )
                self._stats["escanear"] = {
                    "plc_name": self._plc_name,
                    "n_blocks": len(cache.blocks),
                    "n_tag_tables": len(cache.tag_tables),
                    "n_udts": len(cache.udts),
                    "scanned_at": cache.scanned_at.isoformat(),
                }
                self._log.success(
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

            case _:
                raise ValueError(f"step no soportado: {step_nombre!r}")

    # ==================================================================
    # HOOK 3: on_finish  (ZONA 5: vuelco del result)
    # ==================================================================

    def on_finish(self, **params: Any) -> None:
        """Vuelca ``self.result`` con la shape del FB."""
        scan_stats = self._stats.get("escanear", {})
        cache_hit_stats = self._stats.get("cache_hit", {})
        # Si venimos de cache_hit, ``escanear`` no se ejecuto.
        if scan_stats:
            self.result = {
                "ok": True,
                "plc_name": scan_stats.get("plc_name", self._plc_name),
                "n_blocks": scan_stats.get("n_blocks", 0),
                "n_tag_tables": scan_stats.get("n_tag_tables", 0),
                "n_udts": scan_stats.get("n_udts", 0),
                "scanned_at": scan_stats.get("scanned_at"),
                "from_cache": False,
            }
        elif cache_hit_stats:
            self.result = {
                "ok": True,
                "plc_name": cache_hit_stats.get("plc_name", self._plc_name),
                "n_blocks": cache_hit_stats.get("n_blocks", 0),
                "n_tag_tables": cache_hit_stats.get("n_tag_tables", 0),
                "n_udts": 0,
                "scanned_at": None,
                "from_cache": True,
            }
        else:
            self.result = {
                "ok": True,
                "plc_name": self._plc_name,
                "n_blocks": 0,
                "n_tag_tables": 0,
                "n_udts": 0,
                "scanned_at": None,
                "from_cache": False,
            }


__all__ = ["FunctionScanPlcBlocks"]
