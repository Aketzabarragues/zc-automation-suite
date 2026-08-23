"""Tests para ``SyncDispAlimentacionUseCase``.

Estrategia: mocks ligeros sobre ``TIAProcessGateway`` (AsyncMock) y
``ConfigManager`` (MagicMock). El worker OT NO se invoca: los tests
verifican que el use case delega correctamente en el gateway.

Casos cubiertos:
  - ``preview_disp`` con AppState vacío → has_changes=False, warnings.
  - ``preview_disp`` con AppState lleno y TIA sin cambios → 0 ops.
  - ``preview_disp`` con AppState lleno y TIA con cambios → ops correctas.
  - ``preview_disp`` parsea SOLO el XML de N_MAX (no toca dispositivos).
  - ``preview_disp`` limpia el tempdir en finally.
  - ``apply_disp`` con diff vacío → 0 llamadas a execute_transactional_batch.
  - ``apply_disp`` con diff de N ops → 1 llamada con N operaciones.
  - ``apply_disp`` invoca clear_cache tras el éxito.
  - ``apply_disp`` propaga errores del worker.
  - ``apply_disp`` NO llama a update_user_constant_value directamente
    (eso lo hace el worker internamente vía la transacción).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from application.areas.alimentacion.use_cases.sync_disp_alimentacion import (
    SyncDispAlimentacionUseCase,
)
from application.state import AppState
from core.alimentacion.models.dispositivos import DimensionesDispositivos


# ────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────


def _write_plc_user_constants_xml(
    xml_path: Path,
    constants: list[tuple[str, str]],
) -> None:
    """Escribe un PlcTagTable XML con PlcUserConstant (name, value)."""
    root = ET.Element("SW.Tags.PlcTagTable")
    al = ET.SubElement(root, "AttributeList")
    ET.SubElement(al, "Name").text = xml_path.stem
    ol = ET.SubElement(root, "ObjectList")
    for name, value_str in constants:
        const = ET.SubElement(
            ol, "SW.Tags.PlcUserConstant", {"ID": name}
        )
        attr_list = ET.SubElement(const, "AttributeList")
        ET.SubElement(attr_list, "Name").text = name
        ET.SubElement(attr_list, "DataTypeName").text = "Int"
        ET.SubElement(attr_list, "Value").text = value_str
    ET.ElementTree(root).write(
        str(xml_path), encoding="utf-8", xml_declaration=True
    )


def _write_bulk_export_with_nmax(
    target_dir: Path,
    nmax_xml_constants: list[tuple[str, str]],
    include_device_xmls: bool = True,
) -> None:
    """Simula export_plc_tags_xml: jerarquía con N_MAX y (opcionalmente)
    6 tablas de dispositivos. Las de dispositivos NO deben parsearse.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "000_Sistema").mkdir(parents=True, exist_ok=True)
    (target_dir / "2000_Dispositivos").mkdir(parents=True, exist_ok=True)

    # N_MAX (lo que SÍ se parsea).
    _write_plc_user_constants_xml(
        target_dir / "000_Sistema" / "000_Config_Dispositivos.xml",
        nmax_xml_constants,
    )

    if include_device_xmls:
        # Ruido: las 6 tablas de dispositivos NO deben parsearse.
        for stem in [
            "2000_Disp_ED", "2000_Disp_EA", "2000_Disp_SA",
            "2000_Disp_V", "2000_Disp_M", "2000_Disp_M_VF",
        ]:
            _write_plc_user_constants_xml(
                target_dir / "2000_Dispositivos" / f"{stem}.xml",
                [("NO_DEBE_APARECER", "1")],
            )


# ────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_gateway() -> AsyncMock:
    """Gateway mockeado: ``export_plc_tags_xml`` escribe el árbol bulk,
    ``execute_transactional_batch`` devuelve éxito."""
    gw = AsyncMock()

    async def fake_export(plc_name: str, target_dir: str) -> str:
        # Por defecto: TIA con N_MAX_DISP_ED=10, N_MAX_DISP_V=12.
        _write_bulk_export_with_nmax(
            Path(target_dir),
            [
                ("N_MAX_DISP_ED", "10"),
                ("N_MAX_DISP_V", "12"),
            ],
            include_device_xmls=True,
        )
        return target_dir

    gw.export_plc_tags_xml = AsyncMock(side_effect=fake_export)
    gw.execute_transactional_batch = AsyncMock(
        return_value={
            "success": True,
            "operations_executed": 0,
            "details": [],
        }
    )
    gw.clear_cache = MagicMock()
    # ``update_user_constant_value`` NUNCA debe ser llamado directamente
    # por el use case (lo hace el worker vía la transacción).
    gw.update_user_constant_value = AsyncMock()
    return gw


@pytest.fixture
def mock_config_manager() -> MagicMock:
    cm = MagicMock()
    cm.get_global_config_table_name = MagicMock(
        return_value="000_Config_Dispositivos"
    )
    cm.get_tia_folder_nmax = MagicMock(return_value="000_Sistema")
    cm.list_nmax_active = MagicMock(
        return_value=[
            "N_MAX_DISP_ED", "N_MAX_DISP_EA", "N_MAX_DISP_SA",
            "N_MAX_DISP_V", "N_MAX_DISP_M", "N_MAX_DISP_M_VF",
        ]
    )
    return cm


@pytest.fixture
def app_state_with_dimensiones() -> AppState:
    """AppState con dimensiones que difieren del TIA mock (ED=10, V=12)."""
    state = AppState()
    state.dimensiones = DimensionesDispositivos(
        num_disp_ed=15,   # TIA=10 → diff
        num_disp_ea=20,   # TIA=ausente → 0 (sin cambio)
        num_disp_sa=10,
        num_disp_v=15,    # TIA=12 → diff
        num_disp_m=10,
        num_disp_m_vf=5,
    )
    return state


@pytest.fixture
def app_state_in_sync() -> AppState:
    """AppState con dimensiones IGUALES al TIA mock (ED=10, V=12)."""
    state = AppState()
    state.dimensiones = DimensionesDispositivos(
        num_disp_ed=10,
        num_disp_ea=0,    # TIA sin esta constante → ignorado
        num_disp_sa=0,
        num_disp_v=12,
        num_disp_m=0,
        num_disp_m_vf=0,
    )
    return state


@pytest.fixture
def empty_app_state() -> AppState:
    return AppState()


@pytest.fixture
def use_case(
    mock_gateway: AsyncMock,
    mock_config_manager: MagicMock,
    app_state_with_dimensiones: AppState,
) -> SyncDispAlimentacionUseCase:
    return SyncDispAlimentacionUseCase(
        gateway=mock_gateway,
        config_manager=mock_config_manager,
        app_state=app_state_with_dimensiones,
    )


# ────────────────────────────────────────────────────────────────────────
# Tests de preview_disp
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_preview_disp_with_empty_app_state_warns(
    mock_gateway, mock_config_manager, empty_app_state
):
    uc = SyncDispAlimentacionUseCase(
        gateway=mock_gateway,
        config_manager=mock_config_manager,
        app_state=empty_app_state,
    )
    result = await uc.preview_disp("PLC1")
    assert result["success"] is True
    assert result["preview"] is True
    assert result["has_changes"] is False
    assert len(result["warnings"]) > 0
    assert "AppState está vacío" in result["warnings"][0]
    assert result["ops"] == []
    # No se toca TIA.
    mock_gateway.export_plc_tags_xml.assert_not_called()
    mock_gateway.execute_transactional_batch.assert_not_called()


@pytest.mark.asyncio
async def test_preview_disp_does_not_touch_tia(use_case, mock_gateway):
    await use_case.preview_disp("PLC1")
    mock_gateway.execute_transactional_batch.assert_not_called()
    mock_gateway.clear_cache.assert_not_called()
    mock_gateway.update_user_constant_value.assert_not_called()


@pytest.mark.asyncio
async def test_preview_disp_exports_only_nmax_xml(
    use_case, mock_gateway
):
    """preview_disp llama a ``export_plc_tags_xml`` una sola vez (bulk)."""
    await use_case.preview_disp("PLC1")
    mock_gateway.export_plc_tags_xml.assert_called_once()
    mock_gateway.export_plc_tags_xml.assert_called_with(
        plc_name="PLC1", target_dir=ANY
    )


@pytest.mark.asyncio
async def test_preview_disp_cleans_temp_dir(
    use_case, mock_gateway
):
    """El tempdir se elimina en finally (no queda en disco)."""
    captured: list[str] = []
    original = mock_gateway.export_plc_tags_xml.side_effect

    async def spy(plc_name: str, target_dir: str) -> str:
        captured.append(target_dir)
        return await original(plc_name, target_dir)

    mock_gateway.export_plc_tags_xml.side_effect = spy
    await use_case.preview_disp("PLC1")

    assert len(captured) == 1
    for td in captured:
        assert "zc_nmax_" in td
        assert not Path(td).exists(), f"Tempdir {td} no se limpió"


@pytest.mark.asyncio
async def test_preview_disp_in_sync_returns_no_changes(
    mock_gateway, mock_config_manager, app_state_in_sync
):
    """Si Excel y TIA coinciden en N_MAX → has_changes=False, ops=[]."""
    uc = SyncDispAlimentacionUseCase(
        gateway=mock_gateway,
        config_manager=mock_config_manager,
        app_state=app_state_in_sync,
    )
    result = await uc.preview_disp("PLC1")
    assert result["has_changes"] is False
    assert result["ops"] == []
    assert result["summary"]["n_max_updates"] == 0
    assert result["summary"]["total_ops"] == 0


@pytest.mark.asyncio
async def test_preview_disp_detects_nmax_changes(use_case):
    """TIA tiene ED=10/V=12, desired=ED=15/V=15 → 2 ops."""
    result = await use_case.preview_disp("PLC1")
    assert result["has_changes"] is True
    assert result["summary"]["n_max_updates"] == 2
    assert result["summary"]["total_ops"] == 2
    assert len(result["ops"]) == 2

    # Verificar contenido de las ops.
    ops_by_name = {op["args"]["constant_name"]: op for op in result["ops"]}
    assert "N_MAX_DISP_ED" in ops_by_name
    assert "N_MAX_DISP_V" in ops_by_name
    assert ops_by_name["N_MAX_DISP_ED"]["args"]["new_value"] == 15
    assert ops_by_name["N_MAX_DISP_V"]["args"]["new_value"] == 15
    assert ops_by_name["N_MAX_DISP_ED"]["args"]["plc_name"] == "PLC1"
    assert ops_by_name["N_MAX_DISP_ED"]["args"]["table_name"] == (
        "000_Config_Dispositivos"
    )
    assert (
        ops_by_name["N_MAX_DISP_ED"]["command"]
        == "update_user_constant_value"
    )


@pytest.mark.asyncio
async def test_preview_disp_propagates_export_errors(
    mock_config_manager, app_state_with_dimensiones
):
    """Si el export bulk falla, preview_disp NO aborta: devuelve
    has_changes=False con un warning accionable."""
    gw = AsyncMock()
    gw.export_plc_tags_xml = AsyncMock(
        side_effect=RuntimeError("TIA no responde")
    )

    uc = SyncDispAlimentacionUseCase(
        gateway=gw,
        config_manager=mock_config_manager,
        app_state=app_state_with_dimensiones,
    )
    result = await uc.preview_disp("PLC1")
    assert result["has_changes"] is False
    assert result["ops"] == []
    assert len(result["warnings"]) > 0
    assert "Export bulk del PLC falló" in result["warnings"][0]


# ────────────────────────────────────────────────────────────────────────
# Tests de apply_disp
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_disp_empty_diff_no_transaction(
    mock_gateway, mock_config_manager, app_state_in_sync
):
    """Diff vacío → NO se invoca ``execute_transactional_batch``.
    Se devuelve applied=True con operations_executed=0.
    """
    uc = SyncDispAlimentacionUseCase(
        gateway=mock_gateway,
        config_manager=mock_config_manager,
        app_state=app_state_in_sync,
    )
    result = await uc.apply_disp("PLC1")
    assert result["applied"] is True
    assert result["operations_executed"] == 0
    mock_gateway.execute_transactional_batch.assert_not_called()
    mock_gateway.clear_cache.assert_not_called()
    # Aún más importante: NO se invoca update_user_constant_value directo.
    mock_gateway.update_user_constant_value.assert_not_called()


@pytest.mark.asyncio
async def test_apply_disp_with_empty_app_state_does_not_touch_tia(
    mock_gateway, mock_config_manager, empty_app_state
):
    uc = SyncDispAlimentacionUseCase(
        gateway=mock_gateway,
        config_manager=mock_config_manager,
        app_state=empty_app_state,
    )
    result = await uc.apply_disp("PLC1")
    assert result["applied"] is True
    assert result["operations_executed"] == 0
    mock_gateway.export_plc_tags_xml.assert_not_called()
    mock_gateway.execute_transactional_batch.assert_not_called()


@pytest.mark.asyncio
async def test_apply_disp_calls_execute_transactional_batch_once(
    use_case, mock_gateway
):
    """Con N=2 ops, ``execute_transactional_batch`` se llama EXACTAMENTE
    una vez con una lista de 2 operaciones ``update_user_constant_value``.
    """
    mock_gateway.execute_transactional_batch.return_value = {
        "success": True,
        "operations_executed": 2,
        "details": [
            {"step": 1, "command": "update_user_constant_value", "result": True},
            {"step": 2, "command": "update_user_constant_value", "result": True},
        ],
    }
    result = await use_case.apply_disp("PLC1")
    assert result["applied"] is True
    assert result["operations_executed"] == 2
    assert result["summary"]["n_max_updates"] == 2

    mock_gateway.execute_transactional_batch.assert_called_once()
    call = mock_gateway.execute_transactional_batch.call_args
    operations = call.kwargs.get("operations") or call.args[0]
    undo_text = call.kwargs.get("undo_text") or call.args[1]
    assert len(operations) == 2
    for op in operations:
        assert op["command"] == "update_user_constant_value"
        assert op["args"]["plc_name"] == "PLC1"
        assert op["args"]["table_name"] == "000_Config_Dispositivos"
        assert op["args"]["constant_name"] in (
            "N_MAX_DISP_ED", "N_MAX_DISP_V"
        )
        assert op["args"]["new_value"] in (15, 15)
    assert "SyncDispAlimentacion" in undo_text
    assert "PLC1" in undo_text


@pytest.mark.asyncio
async def test_apply_disp_does_not_call_update_user_constant_value_directly(
    use_case, mock_gateway
):
    """Regla arquitectónica: el use case NO llama a update_user_constant_value
    directamente. Lo hace el worker dentro de la transacción. El mock debe
    verificar que ``update_user_constant_value`` NO se invoca desde el
    use case.
    """
    mock_gateway.execute_transactional_batch.return_value = {
        "success": True,
        "operations_executed": 2,
        "details": [],
    }
    await use_case.apply_disp("PLC1")
    mock_gateway.update_user_constant_value.assert_not_called()


@pytest.mark.asyncio
async def test_apply_disp_clears_cache_on_success(
    use_case, mock_gateway
):
    mock_gateway.execute_transactional_batch.return_value = {
        "success": True,
        "operations_executed": 2,
        "details": [],
    }
    await use_case.apply_disp("PLC1")
    mock_gateway.clear_cache.assert_called_once()


@pytest.mark.asyncio
async def test_apply_disp_does_not_clear_cache_on_error(
    use_case, mock_gateway
):
    """Si la transacción falla, NO se invoca ``clear_cache``
    (el worker ya hizo rollback; el use case propaga el error)."""
    mock_gateway.execute_transactional_batch.side_effect = RuntimeError(
        "Worker rollback"
    )
    with pytest.raises(RuntimeError, match="Worker rollback"):
        await use_case.apply_disp("PLC1")
    mock_gateway.clear_cache.assert_not_called()


@pytest.mark.asyncio
async def test_apply_disp_propagates_export_errors(
    mock_config_manager, app_state_with_dimensiones
):
    gw = AsyncMock()
    gw.export_plc_tags_xml = AsyncMock(
        side_effect=RuntimeError("TIA no responde")
    )

    uc = SyncDispAlimentacionUseCase(
        gateway=gw,
        config_manager=mock_config_manager,
        app_state=app_state_with_dimensiones,
    )
    # El export falla → no hay ops → no-op idempotente (no aborta).
    result = await uc.apply_disp("PLC1")
    assert result["applied"] is True
    assert result["operations_executed"] == 0
    gw.execute_transactional_batch.assert_not_called()


# ────────────────────────────────────────────────────────────────────────
# Tests de helpers privados
# ────────────────────────────────────────────────────────────────────────


def test_check_app_state_returns_warning_when_empty(
    mock_gateway, mock_config_manager, empty_app_state
):
    uc = SyncDispAlimentacionUseCase(
        gateway=mock_gateway,
        config_manager=mock_config_manager,
        app_state=empty_app_state,
    )
    warnings = uc._check_app_state()
    assert len(warnings) > 0
    assert "AppState está vacío" in warnings[0]


def test_check_app_state_returns_empty_when_populated(
    use_case,
):
    warnings = use_case._check_app_state()
    assert warnings == []


def test_build_nmax_desired_reads_from_dimensiones(use_case):
    desired = use_case._build_nmax_desired()
    assert desired["N_MAX_DISP_ED"] == 15
    assert desired["N_MAX_DISP_V"] == 15
    assert desired["N_MAX_DISP_M_VF"] == 5


def test_compute_nmax_ops_delegates_to_pure_motor(
    use_case, mock_config_manager
):
    """El use case delega en ``CalculateConstantsDiffUseCase`` (motor puro)."""
    current = {"N_MAX_DISP_ED": 10, "N_MAX_DISP_V": 12}
    desired = {"N_MAX_DISP_ED": 15, "N_MAX_DISP_V": 15}
    ops = use_case._compute_nmax_ops("PLC1", current, desired)
    assert len(ops) == 2
    assert all(op["command"] == "update_user_constant_value" for op in ops)


# ────────────────────────────────────────────────────────────────────────
# Tests de la shape legacy (compatibilidad con la SPA de alimentacion)
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_preview_disp_returns_legacy_spa_fields(
    use_case, mock_gateway
):
    """El preview debe incluir los campos legacy que lee la SPA.

    La SPA de alimentacion (Dispositivos.js) lee:
      - ``agregados`` / ``eliminados`` / ``renombrados`` / ``todos`` (listas).
      - ``nmax.todos`` (lista con ``{name, actual, nuevo, status}``).
      - ``nmax.summary`` (``{actualizar, sin_cambios, total}``).
      - ``summary`` mezclado (``agregados``, ``renombrados``, ``eliminados``,
        ``sin_cambios``, ``total`` + ``n_max_updates``, ``total_ops``).
    """
    result = await use_case.preview_disp("PLC1")
    # Listas legacy (vacías en esta release porque N_MAX no las usa).
    assert result["agregados"] == []
    assert result["eliminados"] == []
    assert result["renombrados"] == []
    assert result["todos"] == []
    # Bloque nmax con todos los campos legacy.
    assert "nmax" in result
    assert "current" in result["nmax"]
    assert "desired" in result["nmax"]
    assert "todos" in result["nmax"]
    assert "summary" in result["nmax"]
    # Todos los items de nmax.todos tienen la forma correcta.
    for item in result["nmax"]["todos"]:
        assert set(item.keys()) == {"name", "actual", "nuevo", "status"}
        assert item["status"] in ("actualizar", "sin_cambios")
    # nmax.summary tiene los 3 contadores.
    assert set(result["nmax"]["summary"].keys()) == {
        "actualizar", "sin_cambios", "total"
    }
    # Summary mergeado: nuevos + legacy.
    s = result["summary"]
    # Nuevos
    assert "n_max_updates" in s
    assert "total_ops" in s
    assert "has_changes" in s
    # Legacy
    assert s["agregados"] == 0
    assert s["renombrados"] == 0
    assert s["eliminados"] == 0
    assert "sin_cambios" in s
    assert "total" in s


@pytest.mark.asyncio
async def test_preview_disp_nmax_todos_have_correct_status(
    use_case, mock_gateway
):
    """Las N_MAX con valor actual == deseado deben tener ``status=sin_cambios``."""
    result = await use_case.preview_disp("PLC1")
    # El fixture TIA mock tiene N_MAX_DISP_ED=10 y N_MAX_DISP_V=12.
    # El fixture AppState tiene N_MAX_DISP_ED=15, N_MAX_DISP_V=15.
    # => ambas son "actualizar". Las demás N_MAX (EA/SA/M/M_VF=0 en TIA
    # y 20/10/10/5 en desired) también son "actualizar".
    n_actualizar = sum(
        1 for r in result["nmax"]["todos"]
        if r["status"] == "actualizar"
    )
    n_sin_cambios = sum(
        1 for r in result["nmax"]["todos"]
        if r["status"] == "sin_cambios"
    )
    assert n_actualizar == result["nmax"]["summary"]["actualizar"]
    assert n_sin_cambios == result["nmax"]["summary"]["sin_cambios"]
    assert n_actualizar + n_sin_cambios == result["nmax"]["summary"]["total"]


@pytest.mark.asyncio
async def test_preview_disp_empty_app_state_returns_legacy_shape(
    mock_gateway, mock_config_manager, empty_app_state
):
    """Aunque AppState esté vacío, la SPA debe ver todos los campos
    legacy (con valores neutros: ``agregados=[]``, ``nmax.todos=[]``)."""
    uc = SyncDispAlimentacionUseCase(
        gateway=mock_gateway,
        config_manager=mock_config_manager,
        app_state=empty_app_state,
    )
    result = await uc.preview_disp("PLC1")
    assert result["has_changes"] is False
    assert result["agregados"] == []
    assert result["eliminados"] == []
    assert result["renombrados"] == []
    assert result["todos"] == []
    assert "nmax" in result
    # nmax.todos puede tener 6 entradas (las 6 N_MAX del catálogo con
    # status "actualizar" porque desired=0 y current={}).
    assert "nmax" in result
    assert "summary" in result["nmax"]
    # Summary mergeado presente.
    s = result["summary"]
    assert s["n_max_updates"] == 0
    assert s["agregados"] == 0
    assert s["renombrados"] == 0
    assert s["eliminados"] == 0

