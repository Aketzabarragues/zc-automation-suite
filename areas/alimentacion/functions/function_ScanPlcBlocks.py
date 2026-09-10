"""Function block: escanear bloques de un PLC y cachear en proceso.

Fase 2, paso 2.1.3b.  Encapsula el use case legacy
``ScanPlcBlocksUseCase.ensure_cache`` (areas/alimentacion/application/
use_cases/scan_plc_blocks.py) en un ``FunctionBase`` con state
machine ``nStep = 10 -> 20 -> 30 -> 99 (n_done)`` o ``98 (n_error)``.

State machine:
  nStep=10  arrancar   (pre-flight: validar gateway y plc_name)
  nStep=20  check_cache  (si está fresco y no force_refresh, done)
  nStep=30  escanear     (gateway.scan_plc_blocks + cache local)
  nStep=99  done       (terminal OK)
  nStep=98  error      (terminal con error_msg, vía wrapper de la base)

El FB encapsula la parte one-shot (``ensure_cache``) y expone los
métodos de lookup (``get_block``, ``list_blocks``, ``list_tag_tables``,
``bloque_existe``) como API persistente post-scan en la misma clase.
La cache vive en ``self._local_cache``.  El engine tickea el FB
hasta ``n_done``; tras eso, los lookups siguen disponibles sin
intervención del engine (no son parte del state machine).

Trade-offs respecto al use case legacy:
  - El FB NO llama ``progress.begin()`` ni ``progress.finish()``
    (asume que el caller las hace, mismo contrato que
    ``FunctionSubirExcel``).  El FB solo emite
    ``start_stage``/``finish_stage``/``error_stage``.
  - El FB NO lanza ``HTTPException`` (transport-agnostic, como el
    resto de FBs de Fase 2).  Las excepciones del gateway o del
    loader propagan tal cual; el wrapper ``tick()`` de la base las
    captura y pone el FB en ``n_error`` con ``error_msg``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from core.application.progress_buffer import (
    ProgressTracker,
    get_progress_tracker,
)
from core.infrastructure.gateway import TIAProcessGateway
from core.models import BloqueCache, BloquePLC
from core.plc.function_base import FunctionBase

logger = logging.getLogger(__name__)

# TTL del cache local: 5 minutos, mismo que el use case legacy
# (``_LOCAL_CACHE_TTL_SECONDS`` en ``scan_plc_blocks.py``).
_LOCAL_CACHE_TTL_SECONDS: float = 5.0 * 60.0


def _is_fresh(scanned_at: datetime | None) -> bool:
    """``True`` si ``scanned_at`` tiene menos de ``_LOCAL_CACHE_TTL_SECONDS``."""
    if scanned_at is None:
        return False
    if scanned_at.tzinfo is None:
        scanned_at = scanned_at.replace(tzinfo=timezone.utc)
    delta = (datetime.now(timezone.utc) - scanned_at).total_seconds()
    return 0 <= delta < _LOCAL_CACHE_TTL_SECONDS


class FunctionScanPlcBlocks(FunctionBase):
    """FB que escanea bloques de un PLC y los cachea en proceso.

    Inyección de dependencias vía constructor:
      - ``gateway``: TIAProcessGateway.  Obligatorio: si es ``None`` al
        ejecutar, lanza ``RuntimeError``.
      - ``progress_tracker``: ProgressTracker.  Default Singleton.

    Runtime params via ``start(**kwargs)``:
      - ``plc_name`` (str): nombre del PLC.  Obligatorio.
      - ``force_refresh`` (bool, default False): si ``True``, ignora
        el cache local Y el del gateway.

    Tras ``n_done``, la cache está en ``self._local_cache`` y los
    lookups (``get_block``, ``list_blocks``, etc.) funcionan sin
    intervención del engine.
    """

    def __init__(
        self,
        nombre: str = "scan_plc_blocks",
        gateway: TIAProcessGateway | None = None,
        progress_tracker: ProgressTracker | None = None,
    ) -> None:
        super().__init__(nombre)
        self._gateway = gateway
        self._progress: ProgressTracker = (
            progress_tracker if progress_tracker is not None
            else get_progress_tracker()
        )
        # Cache local por plc_name.  Mismo shape que la del gateway.
        self._local_cache: dict[str, BloqueCache] = {}
        # Estado entre ticks (atributos internos).
        self._plc_name: str = ""
        self._force_refresh: bool = False
        self._cache: BloqueCache | None = None  # último cache escaneado

    async def _tick_locked(self) -> None:
        assert self._lock.locked()
        if self.nStep == 10:
            self._step_arrancar()
        elif self.nStep == 20:
            await self._step_check_cache()
        elif self.nStep == 30:
            await self._step_scan()

    # ------------------------------------------------------------------
    # Pasos del state machine
    # ------------------------------------------------------------------

    def _step_arrancar(self) -> None:
        """nStep=10→20: pre-flight.  Valida gateway y captura params."""
        if self._gateway is None:
            raise RuntimeError(
                "FunctionScanPlcBlocks requiere gateway explícito. "
                "Inyéctalo en el constructor."
            )
        plc_name = self._params.get("plc_name")
        if not plc_name:
            raise ValueError(
                "FunctionScanPlcBlocks.start(plc_name=...) es obligatorio"
            )
        self._plc_name = plc_name
        self._force_refresh = bool(self._params.get("force_refresh", False))
        self.nStep = 20

    async def _step_check_cache(self) -> None:
        """nStep=20→30 (o →99 si cache fresco y no force_refresh).

        Si el cache local para ``plc_name`` está fresco y no se
        forzó refresh, salta al estado done sin escanear (el use
        case legacy hace lo mismo en ``ensure_cache``).
        """
        existing = self._local_cache.get(self._plc_name)
        if not self._force_refresh and existing is not None and _is_fresh(existing.scanned_at):
            self._cache = existing
            self.nStep = self.n_done
            return
        self.nStep = 30

    async def _step_scan(self) -> None:
        """nStep=30→99: escanea via gateway y popula la cache local.

        Emite la stage ``scan_blocks`` al ``ProgressTracker``.  En
        error, llama ``error_stage`` con detalle y re-lanza la
        excepción para que el wrapper de la base ponga ``n_error``.
        """
        self._progress.start_stage("scan_blocks", detail="Consultando TIA Portal…")
        try:
            cache = await self._gateway.scan_plc_blocks(
                self._plc_name, force_refresh=self._force_refresh
            )
            self._local_cache[self._plc_name] = cache
            self._cache = cache
            detail = (
                f"{len(cache.blocks)} bloques · "
                f"{len(cache.tag_tables)} tablas"
            )
            self._progress.finish_stage("scan_blocks", detail=detail)
            logger.info(
                "FunctionScanPlcBlocks: cache refrescado para PLC '%s' "
                "(%d bloques, %d tablas).",
                self._plc_name,
                len(cache.blocks),
                len(cache.tag_tables),
            )
            self.nStep = self.n_done
        except Exception as e:
            err_msg = f"{type(e).__name__}: {e}"
            try:
                self._progress.error_stage("scan_blocks", detail=err_msg)
            except Exception:
                # El tracker nunca debe romper el FB.
                pass
            raise

    # ------------------------------------------------------------------
    # Lookup methods (API persistente post-scan, no parte del state machine)
    # ------------------------------------------------------------------

    def get_block(self, plc_name: str, nombre: str) -> BloquePLC | None:
        """Lookup sincrónico de un bloque por nombre.

        Case/space-insensitive (vía ``BloquePLC.normalize_name``).  Si
        la cache local está vacía para ``plc_name``, devuelve
        ``None`` — NO dispara scan.  El caller debe garantizar que
        ``ensure_cache`` se llamó antes (vía el engine o
        ``start()`` + ``tick()`` hasta ``n_done``).
        """
        cache = self._local_cache.get(plc_name)
        if cache is None:
            return None
        key = BloquePLC.normalize_name(nombre)
        return cache.blocks.get(key)

    def get_block_path(self, plc_name: str, nombre: str) -> str | None:
        """Shortcut: ``ruta`` de un bloque o ``None`` si no está cacheado."""
        block = self.get_block(plc_name, nombre)
        return block.ruta if block is not None else None

    def list_blocks(self, plc_name: str) -> list[BloquePLC]:
        """Lista todos los bloques cacheados para ``plc_name`` (orden arbitrario)."""
        cache = self._local_cache.get(plc_name)
        if cache is None:
            return []
        return list(cache.blocks.values())

    def list_tag_tables(self, plc_name: str) -> list[BloquePLC]:
        """Lista todas las tag tables cacheadas para ``plc_name`` (orden arbitrario)."""
        cache = self._local_cache.get(plc_name)
        if cache is None:
            return []
        return list(cache.tag_tables.values())

    def bloque_existe(self, plc_name: str, nombre: str) -> bool:
        """``True`` si el bloque está en la cache local (no dispara scan)."""
        return self.get_block(plc_name, nombre) is not None

    def invalidate(self, plc_name: str | None = None) -> None:
        """Borra la cache local de un PLC (o todas).  NO toca el gateway.

        Útil en tests para forzar un re-scan en el siguiente
        ``start()`` + ``tick()`` hasta ``n_done``.
        """
        if plc_name is None:
            self._local_cache.clear()
        else:
            self._local_cache.pop(plc_name, None)
