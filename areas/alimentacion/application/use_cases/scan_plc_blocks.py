"""Application Layer - Escaneo y cache de bloques PLC del área de alimentación.

Caso de uso: expone una API sincrónica de alto nivel sobre el gateway
asíncrono ``TIAProcessGateway.scan_plc_blocks``. Mantiene su propio
cache en proceso (independiente del del gateway) para que los flujos
de ``sincronizar_textos`` y ``generar_proceso`` puedan resolver nombres
de bloques a sus rutas en TIA sin tener que saber nada de COM.

Emite progreso a través del ``ProgressTracker`` Singleton (``begin`` /
``start_stage`` / ``finish_stage`` / ``finish``) para que el
``ProgressIndicator`` del sidebar refleje el scan como una tarea
más, sin widgets nuevos en la SPA. La SPA es observadora pura: solo
lee el tracker (que ya tiene su polling 500 ms en ``main.js``).

El use case es genérico en intención: vive en el área de alimentación
porque esa es el primer consumidor real (``re-import DB a carpeta
original``, ``sincronizar_textos``, ``generar_proceso``). Si en el
futuro otro departamento necesita la misma API, se moverá a
``core/application/use_cases/``.

API:
  - ``ensure_cache(plc_name, force_refresh=False)`` → ``BloqueCache``.
    Idempotente. Si el cache local esta vacio o expiró, dispara el
    scan via gateway y emite un task al ``ProgressTracker``.
  - ``get_block(plc_name, nombre)`` → ``BloquePLC | None``.
  - ``get_block_path(plc_name, nombre)`` → ``str | None``.
  - ``list_blocks(plc_name)`` → ``list[BloquePLC]``.
  - ``list_tag_tables(plc_name)`` → ``list[BloquePLC]``.
  - ``bloque_existe(plc_name, nombre)`` → ``bool``.

Restricciones arquitectónicas:
  - NO importa ``siemens_tia_scripting``.
  - Solo depende del gateway (inyectado por constructor).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from core.application.progress_buffer import (
    ProgressTracker,
    get_progress_tracker,
)
from core.infrastructure.gateway import TIAProcessGateway
from core.models import BloqueCache, BloquePLC


_logger = logging.getLogger(
    f"{__name__}.ScanPlcBlocksUseCase"
)


# Umbral (segundos) bajo el cual el cache local del use case se considera
# ``fresco`` y NO re-emite progreso. Mismo TTL que el del gateway para
# que ambos estén en sintonía.
_LOCAL_CACHE_TTL_SECONDS: float = 5.0 * 60.0


def _is_fresh(scanned_at: datetime) -> bool:
    """``True`` si ``scanned_at`` tiene menos de ``_LOCAL_CACHE_TTL_SECONDS``."""
    if scanned_at is None:
        return False
    if scanned_at.tzinfo is None:
        scanned_at = scanned_at.replace(tzinfo=timezone.utc)
    delta = (datetime.now(timezone.utc) - scanned_at).total_seconds()
    return 0 <= delta < _LOCAL_CACHE_TTL_SECONDS


class ScanPlcBlocksUseCase:
    """Caso de uso: escaneo + lookup de bloques PLC (cache en proceso)."""

    def __init__(
        self,
        gateway: TIAProcessGateway,
        progress: ProgressTracker | None = None,
    ) -> None:
        self._gateway = gateway
        # ``ProgressTracker`` opcional; si no se inyecta, usamos el
        # Singleton (mismo patrón que ``SyncDispositivosInstancesUseCase``).
        self._progress = progress if progress is not None else get_progress_tracker()
        # Cache local por plc_name. Independiente del cache del gateway
        # (``_bloques_cache``): este vive en el caso de uso y permite
        # ``force_refresh`` locales sin tocar el cache del gateway. La
        # forma es la misma que la del gateway para no introducir un
        # mapping paralelo.
        self._local_cache: dict[str, BloqueCache] = {}

    # ── API pública ────────────────────────────────────────────────────────

    async def ensure_cache(
        self, plc_name: str, force_refresh: bool = False
    ) -> BloqueCache:
        """Asegura que ``plc_name`` tiene cache; si no, escanea via gateway.

        Emite un task al ``ProgressTracker`` (``begin`` →
        ``start_stage`` → ``finish_stage`` → ``finish``) con un solo
        stage ``scan_blocks`` cuyo ``detail`` al terminar reporta
        ``"N bloques · M tablas"``. El frontend lo ve en el
        ``ProgressIndicator`` ya existente (polling 500 ms en
        ``main.js``); no añadimos ningún widget nuevo en la SPA.

        Si el cache local está fresco y ``force_refresh=False``, NO
        emite progreso (sería un flash sin trabajo real) y devuelve
        el cache directamente.

        Args:
            plc_name: nombre del PLC.
            force_refresh: si ``True``, ignora el cache local Y el del
                gateway (lanza un escaneo fresco contra TIA).

        Returns:
            ``BloqueCache`` válido (puede estar vacío si el PLC no
            tiene bloques / tablas, pero el cache se rellena siempre).
        """
        existing = self._local_cache.get(plc_name)
        if not force_refresh and existing is not None and _is_fresh(existing.scanned_at):
            return existing

        operation = f"scan_plc_blocks::{plc_name}"
        label = f"Cache de bloques de '{plc_name}'"
        self._progress.begin(operation, label, ["scan_blocks"])
        try:
            self._progress.start_stage("scan_blocks", detail="Consultando TIA Portal…")
            cache = await self._gateway.scan_plc_blocks(
                plc_name, force_refresh=force_refresh
            )
            self._local_cache[plc_name] = cache
            detail = (
                f"{len(cache.blocks)} bloques · "
                f"{len(cache.tag_tables)} tablas"
            )
            self._progress.finish_stage("scan_blocks", detail=detail)
            self._progress.finish(success=True)
            _logger.info(
                "ScanPlcBlocksUseCase: cache refrescado para PLC '%s' "
                "(%d bloques, %d tablas).",
                plc_name,
                len(cache.blocks),
                len(cache.tag_tables),
            )
            return cache
        except Exception as exc:
            err_msg = f"{type(exc).__name__}: {exc}"
            try:
                self._progress.error_stage("scan_blocks", detail=err_msg)
                self._progress.finish(success=False, error=err_msg)
            except Exception:
                # El tracker nunca debe romper el use case.
                pass
            raise

    def get_block(self, plc_name: str, nombre: str) -> BloquePLC | None:
        """Lookup sincrónico de un bloque por nombre (case/space-insensitive).

        Si el cache local esta vacío para ``plc_name``, NO dispara scan:
        eso es responsabilidad de ``ensure_cache``. El caller debe
        garantizar que se llamó antes.
        """
        cache = self._local_cache.get(plc_name)
        if cache is None:
            return None
        key = BloquePLC.normalize_name(nombre)
        return cache.blocks.get(key)

    def get_block_path(self, plc_name: str, nombre: str) -> str | None:
        """Shortcut: ``ruta`` de un bloque o ``None`` si no esta cacheado."""
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
        """``True`` si el bloque esta en el cache local (no dispara scan)."""
        return self.get_block(plc_name, nombre) is not None

    # ── Helpers de testing / composición ───────────────────────────────────

    def invalidate(self, plc_name: str | None = None) -> None:
        """Borra la cache local de un PLC (o todas). NO toca el gateway.

        Útil en tests para forzar un re-scan en el siguiente
        ``ensure_cache``.
        """
        if plc_name is None:
            self._local_cache.clear()
        else:
            self._local_cache.pop(plc_name, None)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"ScanPlcBlocksUseCase(cached_plcs={list(self._local_cache.keys())})"
        )
