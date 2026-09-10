"""Tests del caso de uso ``ScanPlcBlocksUseCase``.

El gateway se mockea con ``MagicMock(spec=TIAProcessGateway)``; el método
async ``scan_plc_blocks`` se sustituye por ``AsyncMock`` (ver
``.clinerules``: nunca mockear el worker directamente). Cada test
prepara la respuesta del ``AsyncMock`` con un ``BloqueCache``
equivalente para que la lógica del use case lo procese.

El ``ProgressTracker`` también va mockeado con ``MagicMock`` para
verificar que el use case emite los eventos ``begin`` /
``start_stage`` / ``finish_stage`` / ``finish`` que el
``ProgressIndicator`` del sidebar consume vía polling.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from areas.alimentacion.application.use_cases.scan_plc_blocks import (
    ScanPlcBlocksUseCase,
)
from core.application.progress_buffer import ProgressTracker
from core.infrastructure.gateway import TIAProcessGateway
from core.models import BloqueCache, BloquePLC


def _make_response(plc_name: str) -> BloqueCache:
    """Cache de respuesta: 2 bloques + 1 tabla."""
    b1 = BloquePLC(nombre="DB1_SYS", numero=1, tipo="DB", ruta="0_Sistema\\DB1_SYS")
    b2 = BloquePLC(nombre="FB_Main", numero=0, tipo="FB", ruta="0_Sistema\\FB_Main")
    t1 = BloquePLC(
        nombre="Default_tag_table", numero=0, tipo="OTHER", ruta=""
    )
    return BloqueCache(
        blocks={
            BloquePLC.normalize_name(b1.nombre): b1,
            BloquePLC.normalize_name(b2.nombre): b2,
        },
        tag_tables={BloquePLC.normalize_name(t1.nombre): t1},
        plc_name=plc_name,
    )


@pytest.fixture
def gateway() -> TIAProcessGateway:
    """Gateway mockeado: ``scan_plc_blocks`` es async."""
    g = MagicMock(spec=TIAProcessGateway)
    g.scan_plc_blocks = AsyncMock(
        side_effect=lambda plc, force_refresh=False: _make_response(plc)
    )
    return g


@pytest.fixture
def progress() -> ProgressTracker:
    """``ProgressTracker`` mockeado. Solo inspeccionamos las llamadas,
    no necesitamos threading ni snapshot real (eso lo cubren los
    tests de ``test_progress_endpoint.py`` / ``test_progress_buffer.py``).
    """
    return MagicMock(spec=ProgressTracker)


@pytest.fixture
def use_case(
    gateway: TIAProcessGateway,
    progress: ProgressTracker,
) -> ScanPlcBlocksUseCase:
    return ScanPlcBlocksUseCase(gateway, progress=progress)


# ────────────────────────────────────────────────────────────────────────
# ensure_cache
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_block_triggers_scan_on_miss(
    use_case: ScanPlcBlocksUseCase,
    gateway: TIAProcessGateway,
) -> None:
    """Cache local vacío → primer ``get_block`` debe disparar un scan via gateway."""
    # Forzamos: ``get_block`` no puede disparar el scan (es sync).
    # El contrato real es: el caller debe llamar ``ensure_cache`` antes.
    # Aqui validamos que ``ensure_cache`` SI dispara el scan.
    result = await use_case.ensure_cache("PLC_X")
    assert result.plc_name == "PLC_X"
    gateway.scan_plc_blocks.assert_awaited_once_with("PLC_X", force_refresh=False)


@pytest.mark.asyncio
async def test_ensure_cache_uses_local_cache_on_hit(
    use_case: ScanPlcBlocksUseCase,
    gateway: TIAProcessGateway,
) -> None:
    """Tras un ``ensure_cache``, un segundo call no toca el gateway."""
    await use_case.ensure_cache("PLC_X")
    await use_case.ensure_cache("PLC_X")
    assert gateway.scan_plc_blocks.await_count == 1


@pytest.mark.asyncio
async def test_ensure_cache_force_refresh_bypasses_local(
    use_case: ScanPlcBlocksUseCase,
    gateway: TIAProcessGateway,
) -> None:
    """``force_refresh=True`` reescanea aunque haya cache local."""
    await use_case.ensure_cache("PLC_X")
    await use_case.ensure_cache("PLC_X", force_refresh=True)
    assert gateway.scan_plc_blocks.await_count == 2
    # Y se propaga al gateway.
    gateway.scan_plc_blocks.assert_any_await("PLC_X", force_refresh=True)


# ────────────────────────────────────────────────────────────────────────
# Emisión de progreso al ProgressTracker
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ensure_cache_emits_progress_events_on_real_scan(
    use_case: ScanPlcBlocksUseCase,
    progress: ProgressTracker,
) -> None:
    """Primer ``ensure_cache`` (cache miss) emite begin/start/finish/finish
    al ``ProgressTracker`` con un stage ``scan_blocks``.
    """
    await use_case.ensure_cache("PLC_X")

    progress.begin.assert_called_once()
    call_args = progress.begin.call_args
    assert call_args.args[0] == "scan_plc_blocks::PLC_X"
    assert call_args.args[1] == "Cache de bloques de 'PLC_X'"
    assert list(call_args.args[2]) == ["scan_blocks"]

    progress.start_stage.assert_called_once_with(
        "scan_blocks", detail="Consultando TIA Portal…"
    )
    progress.finish_stage.assert_called_once()
    finish_args = progress.finish_stage.call_args
    assert finish_args.args[0] == "scan_blocks"
    # El detail reporta el conteo: 2 bloques · 1 tabla (del _make_response).
    assert finish_args.kwargs.get("detail") == "2 bloques · 1 tablas"
    progress.finish.assert_called_once_with(success=True)


@pytest.mark.asyncio
async def test_ensure_cache_does_not_emit_progress_on_cache_hit(
    use_case: ScanPlcBlocksUseCase,
    progress: ProgressTracker,
) -> None:
    """Segundo ``ensure_cache`` del mismo PLC dentro del TTL → NO
    reemite progreso (sería un flash sin trabajo real en el panel).
    """
    await use_case.ensure_cache("PLC_X")
    progress.reset_mock()  # limpiar el primer scan
    await use_case.ensure_cache("PLC_X")  # hit local, sin re-scan

    progress.begin.assert_not_called()
    progress.start_stage.assert_not_called()
    progress.finish_stage.assert_not_called()
    progress.finish.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_cache_emits_progress_on_force_refresh(
    use_case: ScanPlcBlocksUseCase,
    progress: ProgressTracker,
) -> None:
    """``force_refresh=True`` siempre emite progreso aunque haya cache local."""
    await use_case.ensure_cache("PLC_X")
    progress.reset_mock()
    await use_case.ensure_cache("PLC_X", force_refresh=True)

    progress.begin.assert_called_once()
    progress.finish.assert_called_once_with(success=True)


@pytest.mark.asyncio
async def test_ensure_cache_emits_error_progress_on_gateway_failure(
    use_case: ScanPlcBlocksUseCase,
    gateway: TIAProcessGateway,
    progress: ProgressTracker,
) -> None:
    """Si el gateway lanza, el use case emite ``error_stage`` y
    ``finish(success=False)`` y re-lanza la excepción original.
    """
    gateway.scan_plc_blocks = AsyncMock(
        side_effect=RuntimeError("TIA Portal desconectado")
    )
    with pytest.raises(RuntimeError, match="TIA Portal desconectado"):
        await use_case.ensure_cache("PLC_X")

    progress.begin.assert_called_once()
    progress.error_stage.assert_called_once()
    progress.finish.assert_called_once()
    assert progress.finish.call_args.kwargs.get("success") is False
    assert progress.finish.call_args.kwargs.get("error", "").startswith(
        "RuntimeError: TIA Portal desconectado"
    )


# ────────────────────────────────────────────────────────────────────────
# get_block / get_block_path
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_block_returns_dto_after_ensure(
    use_case: ScanPlcBlocksUseCase,
) -> None:
    """Tras ``ensure_cache``, ``get_block`` devuelve el DTO con su ruta."""
    await use_case.ensure_cache("PLC_X")
    b = use_case.get_block("PLC_X", "DB1_SYS")
    assert b is not None
    assert b.nombre == "DB1_SYS"
    assert b.tipo == "DB"
    assert b.numero == 1
    assert b.ruta == "0_Sistema\\DB1_SYS"


@pytest.mark.asyncio
async def test_get_block_is_case_and_space_insensitive(
    use_case: ScanPlcBlocksUseCase,
) -> None:
    """Lookup tolerante a mayusculas, espacios y NBSP."""
    await use_case.ensure_cache("PLC_X")
    # Variantes que normalizan al mismo key.
    assert use_case.get_block("PLC_X", "db1_sys") is not None
    assert use_case.get_block("PLC_X", "DB 1_SYS") is not None
    assert use_case.get_block("PLC_X", "db\xa01_sys") is not None


def test_get_block_returns_none_for_unknown_plc(
    use_case: ScanPlcBlocksUseCase,
) -> None:
    """PLC sin cache local → ``None`` (sin disparar scan)."""
    assert use_case.get_block("PLC_OTRO", "DB1_SYS") is None


def test_get_block_returns_none_for_unknown_block(
    use_case: ScanPlcBlocksUseCase,
) -> None:
    """Bloque que no esta en el cache → ``None`` (sin scan)."""
    # Caso negativo: el cache no se ha poblado, get_block devuelve None
    # sin tocar el gateway.
    assert use_case.get_block("PLC_X", "DB9999") is None


@pytest.mark.asyncio
async def test_get_block_path_returns_ruta(
    use_case: ScanPlcBlocksUseCase,
) -> None:
    """``get_block_path`` devuelve la ``ruta`` o ``None``."""
    await use_case.ensure_cache("PLC_X")
    assert use_case.get_block_path("PLC_X", "DB1_SYS") == "0_Sistema\\DB1_SYS"
    assert use_case.get_block_path("PLC_X", "INEXISTENTE") is None
    assert use_case.get_block_path("PLC_OTRO", "DB1_SYS") is None


# ────────────────────────────────────────────────────────────────────────
# bloque_existe
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bloque_existe_returns_true_for_known_block(
    use_case: ScanPlcBlocksUseCase,
) -> None:
    await use_case.ensure_cache("PLC_X")
    assert use_case.bloque_existe("PLC_X", "DB1_SYS") is True
    # Tolerante a mayus/espacios. ``"db1 sys"`` normaliza a ``"db1sys"``;
    # como nuestro cache contiene ``"DB1_SYS"`` (que normaliza a
    # ``"db1_sys"``), el lookup falla. Usamos una variante que conserve
    # el guion bajo tras normalizar.
    assert use_case.bloque_existe("PLC_X", "db1_sys") is True


def test_bloque_existe_returns_false_for_unknown_block(
    use_case: ScanPlcBlocksUseCase,
) -> None:
    assert use_case.bloque_existe("PLC_X", "DB9999") is False
    assert use_case.bloque_existe("PLC_OTRO", "DB1_SYS") is False


# ────────────────────────────────────────────────────────────────────────
# list_blocks / list_tag_tables
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_blocks_returns_all_blocks(
    use_case: ScanPlcBlocksUseCase,
) -> None:
    await use_case.ensure_cache("PLC_X")
    blocks = use_case.list_blocks("PLC_X")
    nombres = {b.nombre for b in blocks}
    assert nombres == {"DB1_SYS", "FB_Main"}
    assert len(blocks) == 2


def test_list_blocks_empty_when_no_cache(
    use_case: ScanPlcBlocksUseCase,
) -> None:
    assert use_case.list_blocks("PLC_X") == []


@pytest.mark.asyncio
async def test_list_tag_tables_returns_tag_tables(
    use_case: ScanPlcBlocksUseCase,
) -> None:
    await use_case.ensure_cache("PLC_X")
    tables = use_case.list_tag_tables("PLC_X")
    assert len(tables) == 1
    assert tables[0].nombre == "Default_tag_table"
    assert tables[0].tipo == "OTHER"


def test_list_tag_tables_empty_when_no_cache(
    use_case: ScanPlcBlocksUseCase,
) -> None:
    assert use_case.list_tag_tables("PLC_X") == []


# ────────────────────────────────────────────────────────────────────────
# invalidate
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalidate_clears_local_cache_without_touching_gateway(
    use_case: ScanPlcBlocksUseCase,
    gateway: TIAProcessGateway,
) -> None:
    """``invalidate`` solo limpia la cache local; el gateway queda intacto."""
    await use_case.ensure_cache("PLC_X")
    use_case.invalidate("PLC_X")
    # Ahora ``list_blocks`` devuelve vacio, pero el gateway NO se
    # reconsultó.
    assert use_case.list_blocks("PLC_X") == []
    assert gateway.scan_plc_blocks.await_count == 1

    # Re-ensure dispara un nuevo scan.
    await use_case.ensure_cache("PLC_X")
    assert gateway.scan_plc_blocks.await_count == 2


@pytest.mark.asyncio
async def test_invalidate_none_clears_all(
    use_case: ScanPlcBlocksUseCase,
) -> None:
    await use_case.ensure_cache("PLC_A")
    await use_case.ensure_cache("PLC_B")
    use_case.invalidate(None)
    assert use_case.list_blocks("PLC_A") == []
    assert use_case.list_blocks("PLC_B") == []
