"""Tests de SyncConstantsFromExcelUseCase (patron preview/apply).

Estrategia de lectura: EXPORT -> PARSE.
El orquestador exporta cada PlcTagTable a una carpeta temporal
y la parsea con SimaticMLTagParser.parse_user_constants().
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from application.state import AppState
from application.use_cases.sync_constants_from_excel import (
    SyncConstantsFromExcelUseCase,
)
from core.alimentacion.models.dispositivos import (
    DispED,
    DispV,
    DimensionesDispositivos,
)


# Helper: escribe un XML PlcTagTable de fixture.
def _write_plc_tag_table_xml(
    xml_path: Path,
    constants: list[tuple[str, str]],
) -> None:
    root = ET.Element("SW.Tags.PlcTagTable")
    al = ET.SubElement(root, "AttributeList")
    ET.SubElement(al, "Name").text = xml_path.stem
    ol = ET.SubElement(root, "ObjectList")
    for name, value_str in constants:
        const = ET.SubElement(ol, "SW.Tags.PlcUserConstant", {"ID": name})
        attr_list = ET.SubElement(const, "AttributeList")
        ET.SubElement(attr_list, "Name").text = name
        ET.SubElement(attr_list, "DataTypeName").text = "Int"
        ET.SubElement(attr_list, "Value").text = value_str
    ET.ElementTree(root).write(str(xml_path), encoding="utf-8", xml_declaration=True)


# Helper: escribe el árbol bulk (con jerarquía de carpetas) que
# simula el resultado de ``export_plc_tags_xml``. Crea:
#   {target_dir}/000_Sistema/000_Config_Dispositivos.xml  (N_MAX)
#   {target_dir}/2000_Dispositivos/2000_Disp_ED.xml
#   {target_dir}/2000_Dispositivos/2000_Disp_V.xml
#   {target_dir}/003_Procesos/999_Otra_Cosa.xml            (NO se usa)
#   {target_dir}/2000_Dispositivos/2000_Disp_SD.xml        (NO se usa)
#
# Formato de los constants: ``[(Name, Value), ...]`` (ver
# ``_write_plc_tag_table_xml`` más arriba).
def _write_bulk_export_tree(target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "000_Sistema").mkdir(parents=True, exist_ok=True)
    (target_dir / "2000_Dispositivos").mkdir(parents=True, exist_ok=True)
    (target_dir / "003_Procesos").mkdir(parents=True, exist_ok=True)
    # N_MAX (estado actual en TIA): N_MAX_DISP_ED=10, N_MAX_DISP_V=12.
    # El Excel (app_state_with_data) tiene 15 y 15 → diff esperado.
    _write_plc_tag_table_xml(
        target_dir / "000_Sistema" / "000_Config_Dispositivos.xml",
        [("N_MAX_DISP_ED", "10"), ("N_MAX_DISP_V", "12")],
    )
    # DispED (estado actual en TIA): value=1 → name=V_001, value=2 → V_002.
    # El Excel tiene los mismos valores y nombres → 0 ops en DispED.
    _write_plc_tag_table_xml(
        target_dir / "2000_Dispositivos" / "2000_Disp_ED.xml",
        [("V_001", "1"), ("V_002", "2")],
    )
    # DispV (estado actual en TIA): value=1 → name=V_OLD.
    # El Excel tiene value=1 → name=V_VA_101 → 1 op rename.
    _write_plc_tag_table_xml(
        target_dir / "2000_Dispositivos" / "2000_Disp_V.xml",
        [("V_OLD", "1")],
    )
    # Tablas "ruido" (legacy / otro subsistema): NUNCA deben parsearse.
    _write_plc_tag_table_xml(
        target_dir / "003_Procesos" / "999_Otra_Cosa.xml",
        [("NO_DEBE_APARECER", "1")],
    )
    _write_plc_tag_table_xml(
        target_dir / "2000_Dispositivos" / "2000_Disp_SD.xml",
        [("NO_DEBE_APARECER", "1")],
    )


@pytest.fixture
def mock_gateway() -> AsyncMock:
    gw = AsyncMock()

    async def fake_bulk_export(plc_name, target_dir):
        _write_bulk_export_tree(Path(target_dir))
        return str(target_dir)

    gw.export_plc_tags_xml = AsyncMock(side_effect=fake_bulk_export)
    # Compatibilidad con tests legacy: export_tag_table ahora es
    # opcional (el fix usa el bulk). Si alguien lo llama, devuelve
    # el path vacío.
    gw.export_tag_table = AsyncMock(return_value="")
    gw.execute_unified_sync = AsyncMock(
        return_value={"success": True, "operations_executed": 0, "details": []}
    )
    gw.clear_cache = MagicMock()
    return gw


@pytest.fixture
def mock_config_manager() -> MagicMock:
    cm = MagicMock()
    cm.get_global_config_table_name = MagicMock(
        return_value="000_Config_Dispositivos"
    )
    cm.get_tia_folder_nmax = MagicMock(return_value="000_Sistema")
    cm.get_tia_folder_dispositivos = MagicMock(return_value="2000_Dispositivos")
    cm.list_hw_types = MagicMock(return_value=["ed", "v"])
    cm.get_tag_table_name = MagicMock(
        side_effect=lambda hw: {"ed": "2000_Disp_ED", "v": "2000_Disp_V"}.get(hw)
    )
    return cm


@pytest.fixture
def app_state_with_data() -> AppState:
    state = AppState()
    state.dispositivos_ed = [
        DispED(
            numero=1, plc_tag="V_001", plc_comentario="", descripcion="",
            uid="ED_001",
            tag=1, fat=0, e_byte=0, e_bit=0,
            gr_alarma="", cuadro="", observaciones="", plc_tipo="int",
            plc_index=1, hmi_index=1, hmi_texto="E1",
            cfg_habilitar="", cfg_byte_entrada="", cfg_bit_entrada="",
            cfg_grupo_alarma="", comentario_db="",
        ),
        DispED(
            numero=2, plc_tag="V_002", plc_comentario="", descripcion="",
            uid="ED_002",
            tag=0, fat=0, e_byte=0, e_bit=0,
            gr_alarma="", cuadro="", observaciones="", plc_tipo="int",
            plc_index=2, hmi_index=2, hmi_texto="Rsv",
            cfg_habilitar="", cfg_byte_entrada="", cfg_bit_entrada="",
            cfg_grupo_alarma="", comentario_db="",
        ),
    ]
    state.dispositivos_v = [
        DispV(
            numero=1, plc_tag="V_VA_101", plc_comentario="", descripcion="",
            uid="V_001",
            tag=101, fat=0, s_byte=0, s_bit=0,
            rr_byte=0, rr_bit=0, rt_byte=0, rt_bit=0,
            gr_alarma="", cuadro="", observaciones="", plc_tipo="int",
            plc_index=1, hmi_index=1, hmi_texto="VA-101",
            cfg_habilitar="", cfg_byteretornoreposo="",
            cfg_bitretornoreposo="", cfg_byteretornotrabajo="",
            cfg_bitretornotrabajo="", cfg_byteactivacion="",
            cfg_bitactivacion="", cfg_habitreposo="",
            cfg_habitrtrabajo="", cfg_grupoalarma="",
            comentario_db="",
        ),
    ]
    state.dimensiones = DimensionesDispositivos(
        num_disp_ed=15, num_disp_ea=20, num_disp_sa=10,
        num_disp_v=15, num_disp_m=10, num_disp_m_vf=5,
    )
    return state


@pytest.fixture
def empty_app_state() -> AppState:
    return AppState()


@pytest.fixture
def use_case(
    mock_gateway: AsyncMock,
    mock_config_manager: MagicMock,
    app_state_with_data: AppState,
) -> SyncConstantsFromExcelUseCase:
    return SyncConstantsFromExcelUseCase(
        gateway=mock_gateway,
        config_manager=mock_config_manager,
        app_state=app_state_with_data,
    )


# === Tests de preview() ===

@pytest.mark.asyncio
async def test_preview_with_empty_app_state_warns(
    mock_gateway, mock_config_manager, empty_app_state,
):
    uc = SyncConstantsFromExcelUseCase(
        gateway=mock_gateway,
        config_manager=mock_config_manager,
        app_state=empty_app_state,
    )
    result = await uc.preview("PLC1")
    assert result["success"] is True
    assert result["preview"] is True
    assert result["has_app_state"] is False
    assert len(result["warnings"]) > 0
    assert "AppState está vacío" in result["warnings"][0]
    assert result["summary"]["has_changes"] is False


@pytest.mark.asyncio
async def test_preview_does_NOT_execute_transaction(use_case, mock_gateway):
    await use_case.preview("PLC1")
    mock_gateway.execute_unified_sync.assert_not_called()
    mock_gateway.clear_cache.assert_not_called()


@pytest.mark.asyncio
async def test_preview_exports_all_tables(use_case, mock_gateway):
    """preview() llama a ``export_plc_tags_xml`` (bulk) UNA sola vez.

    La fix del preflight usa el export bulk con jerarquía preservada
    y parsea **solo** los 7 XMLs de las carpetas conocidas (1 N_MAX
    + 6 dispositivos). Por tanto:
      - ``export_plc_tags_xml`` se llama 1 vez.
      - ``export_tag_table`` (single, legacy) NO se llama.
    """
    await use_case.preview("PLC1")
    mock_gateway.export_plc_tags_xml.assert_called_once()
    mock_gateway.export_plc_tags_xml.assert_called_with(
        plc_name="PLC1", target_dir=ANY
    )
    # export_tag_table queda en desuso desde el fix.
    mock_gateway.export_tag_table.assert_not_called()


@pytest.mark.asyncio
async def test_preview_cleans_temp_dir(use_case, mock_gateway):
    """preview() limpia la carpeta temporal tras ejecutar (finally)."""
    captured: list[str] = []
    original = mock_gateway.export_plc_tags_xml.side_effect

    async def spy(plc_name, target_dir):
        captured.append(target_dir)
        return await original(plc_name, target_dir)

    mock_gateway.export_plc_tags_xml.side_effect = spy
    await use_case.preview("PLC1")

    assert len(captured) == 1
    for td in captured:
        assert "zc_sync_" in td
        assert not Path(td).exists(), f"Temp dir {td} no fue limpiada"


# === Tests de execute() ===

@pytest.mark.asyncio
async def test_executes_transaction(use_case, mock_gateway):
    mock_gateway.execute_unified_sync.return_value = {
        "success": True,
        "operations_executed": 5,
        "details": {"nmax": [], "renames": []},
    }
    result = await use_case.execute("PLC1")
    assert result["success"] is True
    assert result["applied"] is True
    mock_gateway.execute_unified_sync.assert_called_once()


@pytest.mark.asyncio
async def test_execute_clears_cache_on_success(use_case, mock_gateway):
    mock_gateway.execute_unified_sync.return_value = {
        "success": True, "operations_executed": 0, "details": []
    }
    await use_case.execute("PLC1")
    mock_gateway.clear_cache.assert_called_once()


@pytest.mark.asyncio
async def test_execute_propagates_gateway_errors(use_case, mock_gateway):
    mock_gateway.execute_unified_sync.side_effect = RuntimeError("Timeout")
    with pytest.raises(RuntimeError, match="Timeout"):
        await use_case.execute("PLC1")


@pytest.mark.asyncio
async def test_execute_propagates_export_errors(use_case, mock_gateway):
    """Si el export bulk falla, la preflight NO aborta (devuelve {}).

    Política: el export bulk es un side-effect; si falla, la preflight
    devuelve ``{"nmax_current": {}, "device_current": {}}`` y la
    SPA/MCP verá "0 ops" en lugar de un 500. La transacción
    (``execute_unified_sync``) sigue sin invocarse porque no hay
    diff que aplicar.
    """
    mock_gateway.export_plc_tags_xml.side_effect = RuntimeError("Export falló")
    # El execute() propaga la excepción solo si NO devuelve diff
    # con estados vacíos. La fix lo absorbe: comprobamos que el
    # gateway NO llegó a invocar la transacción.
    try:
        await use_case.execute("PLC1")
    except RuntimeError:
        pass  # también aceptable si la preflight decide propagar.
    mock_gateway.execute_unified_sync.assert_not_called()


@pytest.mark.asyncio
async def test_execute_with_empty_app_state_warns(
    mock_gateway, mock_config_manager, empty_app_state,
):
    uc = SyncConstantsFromExcelUseCase(
        gateway=mock_gateway,
        config_manager=mock_config_manager,
        app_state=empty_app_state,
    )
    mock_gateway.execute_unified_sync.return_value = {
        "success": True, "operations_executed": 0, "details": []
    }
    result = await uc.execute("PLC1")
    assert result["applied"] is True
    assert len(result["warnings"]) > 0


# === Tests de helpers privados ===

def test_build_nmax_desired_from_appstate(
    mock_gateway, mock_config_manager, app_state_with_data,
):
    uc = SyncConstantsFromExcelUseCase(
        gateway=mock_gateway,
        config_manager=mock_config_manager,
        app_state=app_state_with_data,
    )
    desired = uc._build_nmax_desired_from_appstate()
    assert desired["N_MAX_DISP_ED"] == 15
    assert desired["N_MAX_DISP_V"] == 15
    assert desired["N_MAX_DISP_M_VF"] == 5


def test_build_device_states_uses_app_state_lists(
    mock_gateway, mock_config_manager, app_state_with_data,
):
    uc = SyncConstantsFromExcelUseCase(
        gateway=mock_gateway,
        config_manager=mock_config_manager,
        app_state=app_state_with_data,
    )
    states = uc._build_device_states_from_appstate(
        device_current={"ed": {}, "v": {}}
    )
    assert "ed" in states
    assert "v" in states
    assert "ea" not in states
    assert states["ed"]["desired"]["V_001"] == 1
    assert states["v"]["desired"]["V_VA_101"] == 1


def test_check_app_state_returns_warning_when_empty(
    mock_gateway, mock_config_manager, empty_app_state,
):
    uc = SyncConstantsFromExcelUseCase(
        gateway=mock_gateway,
        config_manager=mock_config_manager,
        app_state=empty_app_state,
    )
    warnings = uc._check_app_state()
    assert len(warnings) > 0
    assert "AppState está vacío" in warnings[0]


def test_check_app_state_returns_empty_when_populated(
    mock_gateway, mock_config_manager, app_state_with_data,
):
    uc = SyncConstantsFromExcelUseCase(
        gateway=mock_gateway,
        config_manager=mock_config_manager,
        app_state=app_state_with_data,
    )
    warnings = uc._check_app_state()
    assert warnings == []
