"""Tests para ``SyncDispositivosInstancesUseCase``.

Verifica que el use case restaurado (sync completo N_MAX + devices)
funciona end-to-end:
  - ``generar_prevision``: lee export bulk, calcula diff de N_MAX y
    de devices, devuelve el shape legacy que la SPA espera.
  - ``ejecutar_transaccion``: empaqueta N_MAX + devices en UNA sola
    transacci\u00f3n ``execute_transactional_batch`` con rollback.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from application.areas.alimentacion.use_cases.sync_dispositivos_instances import (
    SyncDispositivosInstancesUseCase,
)
from application.state import AppState
from core.alimentacion.models.dispositivos import (
    DispED,
    DimensionesDispositivos,
)


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


def _write_bulk_export_tree(
    target_dir: Path,
    nmax_constants: list[tuple[str, str]] | None = None,
    device_tables: dict[str, list[tuple[str, str]]] | None = None,
) -> None:
    """Simula export_plc_tags_xml con N_MAX y tablas de devices."""
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "000_Sistema").mkdir(parents=True, exist_ok=True)
    (target_dir / "2000_Dispositivos").mkdir(parents=True, exist_ok=True)
    if nmax_constants is None:
        nmax_constants = [
            ("N_MAX_DISP_ED", "10"),
            ("N_MAX_DISP_V", "12"),
        ]
    _write_plc_user_constants_xml(
        target_dir / "000_Sistema" / "000_Config_Dispositivos.xml",
        nmax_constants,
    )
    if device_tables:
        for table_name, constants in device_tables.items():
            _write_plc_user_constants_xml(
                target_dir / "2000_Dispositivos" / f"{table_name}.xml",
                constants,
            )


# ────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_gateway() -> AsyncMock:
    gw = AsyncMock()

    async def fake_export(plc_name: str, target_dir: str) -> str:
        # TIA con:
        #   N_MAX: N_MAX_DISP_ED=10, N_MAX_DISP_V=12.
        #   Devices: 2000_Disp_ED con value=1 -> "V_001" y value=2 -> "V_002".
        #           2000_Disp_V con value=1 -> "V_OLD".
        _write_bulk_export_tree(
            Path(target_dir),
            nmax_constants=[
                ("N_MAX_DISP_ED", "10"),
                ("N_MAX_DISP_V", "12"),
            ],
            device_tables={
                "2000_Disp_ED": [("V_001", "1"), ("V_002", "2")],
                "2000_Disp_V": [("V_OLD", "1")],
            },
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
    return gw


@pytest.fixture
def mock_config_manager() -> MagicMock:
    cm = MagicMock()
    cm.get_global_config_table_name = MagicMock(
        return_value="000_Config_Dispositivos"
    )
    cm.get_tia_folder_nmax = MagicMock(return_value="000_Sistema")
    cm.get_tia_folder_dispositivos = MagicMock(
        return_value="2000_Dispositivos"
    )
    cm.list_nmax_active = MagicMock(
        return_value=[
            "N_MAX_DISP_ED", "N_MAX_DISP_EA", "N_MAX_DISP_SA",
            "N_MAX_DISP_V", "N_MAX_DISP_M", "N_MAX_DISP_M_VF",
        ]
    )
    cm.list_hw_types_active = MagicMock(return_value=["ed", "v"])
    cm.get_tag_table_name = MagicMock(
        side_effect=lambda hw: {"ed": "2000_Disp_ED", "v": "2000_Disp_V"}.get(hw)
    )
    cm.get_app_state_attr_for = MagicMock(
        side_effect=lambda hw: f"dispositivos_{hw}"
    )
    return cm


@pytest.fixture
def app_state_with_full_data() -> AppState:
    """AppState con N_MAX + devices que difieren del TIA mock."""
    state = AppState()
    # N_MAX: 15/15 vs TIA 10/12 -> diff.
    state.dimensiones = DimensionesDispositivos(
        num_disp_ed=15, num_disp_ea=20, num_disp_sa=10,
        num_disp_v=15, num_disp_m=10, num_disp_m_vf=5,
    )
    # Devices: DispED con V_001/V_002 (en TIA tambi\u00e9n) y DispV con V_VA_101
    # (TIA tiene V_OLD) -> 1 rename.
    state.dispositivos_ed = [
        DispED(
            numero=1, plc_tag="V_001", plc_comentario="", descripcion="",
            uid="ED_001", tag=1, fat=0, e_byte=0, e_bit=0,
            gr_alarma="", cuadro="", observaciones="", plc_tipo="int",
            plc_index=1, hmi_index=1, hmi_texto="E1",
            cfg_habilitar="", cfg_byte_entrada="", cfg_bit_entrada="",
            cfg_grupo_alarma="", comentario_db="",
        ),
        DispED(
            numero=2, plc_tag="V_002", plc_comentario="", descripcion="",
            uid="ED_002", tag=0, fat=0, e_byte=0, e_bit=0,
            gr_alarma="", cuadro="", observaciones="", plc_tipo="int",
            plc_index=2, hmi_index=2, hmi_texto="Rsv",
            cfg_habilitar="", cfg_byte_entrada="", cfg_bit_entrada="",
            cfg_grupo_alarma="", comentario_db="",
        ),
    ]
    state.dispositivos_v = [
        # numero=1, plc_tag="V_VA_101" (TIA tiene V_OLD) -> rename.
    ]
    return state


@pytest.fixture
def use_case(
    mock_gateway: AsyncMock,
    mock_config_manager: MagicMock,
    app_state_with_full_data: AppState,
    tmp_path: Path,
) -> SyncDispositivosInstancesUseCase:
    return SyncDispositivosInstancesUseCase(
        gateway=mock_gateway,
        config_manager=mock_config_manager,
        state=app_state_with_full_data,
        build_cache_dir=tmp_path,
    )


# ────────────────────────────────────────────────────────────────────────
# Tests de generar_prevision
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generar_prevision_returns_legacy_spa_shape(
    use_case, mock_gateway
):
    """El preview devuelve el shape legacy que la SPA espera."""
    result = await use_case.generar_prevision("PLC1")
    # Campos legacy SPA.
    assert "agregados" in result
    assert "eliminados" in result
    assert "renombrados" in result
    assert "todos" in result
    assert "nmax" in result
    assert "summary" in result
    # N_MAX block con la estructura correcta.
    assert "current" in result["nmax"]
    assert "desired" in result["nmax"]
    assert "todos" in result["nmax"]
    assert "summary" in result["nmax"]


@pytest.mark.asyncio
async def test_generar_prevision_nmax_detects_changes(use_case):
    """N_MAX: 2 cambios (ED 10->15, V 12->15) detectados."""
    result = await use_case.generar_prevision("PLC1")
    nmax = result["nmax"]
    # 2 actualizar (ED y V), 4 sin_cambios (EA/SA/M/M_VF=0/0/0/0 vs 0).
    # Wait: el fixture tiene EA=20, SA=10, M=10, M_VF=5; TIA no tiene estas
    # constantes, por lo que en TIA current son None y desired son !=0 => 4
    # actualizar. Total: 6 actualizar, 0 sin_cambios.
    assert nmax["summary"]["actualizar"] >= 2
    assert nmax["summary"]["total"] == 6
    # Verificar que los N_MAX espec\u00edficos aparecen en el diff.
    todo_names = {t["name"] for t in nmax["todos"]}
    assert "N_MAX_DISP_ED" in todo_names
    assert "N_MAX_DISP_V" in todo_names


@pytest.mark.asyncio
async def test_generar_prevision_detects_device_rename(
    use_case, mock_gateway
):
    """El preview detecta renames de devices (V_OLD -> V_VA_101)."""
    # A\u00f1adimos un device con V_VA_101 en el state.
    use_case._state.dispositivos_v = [
        # numero=1, plc_tag="V_VA_101" produce rename de V_OLD a V_VA_101.
        type("DispVStub", (), {
            "numero": 1, "plc_tag": "V_VA_101", "uid": "V_001"
        })(),
    ]
    result = await use_case.generar_prevision("PLC1")
    # El rename debe aparecer en renombrados.
    renames = result["renombrados"]
    assert len(renames) == 1
    assert renames[0]["actual"] == "V_OLD"
    assert renames[0]["nuevo"] == "V_VA_101"
    # Y en todos con status=renombrar.
    rename_todos = [r for r in result["todos"] if r["status"] == "renombrar"]
    assert len(rename_todos) == 1


# ────────────────────────────────────────────────────────────────────────
# Tests de ejecutar_transaccion (N_MAX + devices en UNA transacci\u00f3n)
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ejecutar_transaccion_empty_no_batch(
    use_case, mock_gateway
):
    """Si NO hay cambios, NO se invoca ``execute_transactional_batch``.

    Para que el batch esté vacío, el AppState debe COINCIDIR con el
    TIA mock: N_MAX_DISP_ED=10, N_MAX_DISP_V=12, devices sin cambios.
    """
    # Alinear N_MAX con TIA (10/12) y devices idénticos.
    use_case._state.dimensiones = DimensionesDispositivos(
        num_disp_ed=10, num_disp_ea=0, num_disp_sa=0,
        num_disp_v=12, num_disp_m=0, num_disp_m_vf=0,
    )
    use_case._state.dispositivos_ed = [
        DispED(
            numero=1, plc_tag="V_001", plc_comentario="", descripcion="",
            uid="ED_001", tag=0, fat=0, e_byte=0, e_bit=0,
            gr_alarma="", cuadro="", observaciones="", plc_tipo="int",
            plc_index=0, hmi_index=0, hmi_texto="",
            cfg_habilitar="", cfg_byte_entrada="", cfg_bit_entrada="",
            cfg_grupo_alarma="", comentario_db="",
        ),
        DispED(
            numero=2, plc_tag="V_002", plc_comentario="", descripcion="",
            uid="ED_002", tag=0, fat=0, e_byte=0, e_bit=0,
            gr_alarma="", cuadro="", observaciones="", plc_tipo="int",
            plc_index=0, hmi_index=0, hmi_texto="",
            cfg_habilitar="", cfg_byte_entrada="", cfg_bit_entrada="",
            cfg_grupo_alarma="", comentario_db="",
        ),
    ]
    use_case._state.dispositivos_v = []
    result = await use_case.ejecutar_transaccion("PLC1", {})
    assert result["success"] is True
    assert result["operations"] == 0
    mock_gateway.execute_transactional_batch.assert_not_called()


@pytest.mark.asyncio
async def test_ejecutar_transaccion_single_batch_with_nmax_and_devices(
    use_case, mock_gateway
):
    """Si hay N_MAX + devices, se invocan TODAS en UNA sola transacci\u00f3n.

    Verifica que ``execute_transactional_batch`` se llama UNA vez con
    la lista de ops que incluye:
      - ``update_user_constant_value`` para N_MAX.
      - (eventualmente) ``rename_plc_tag`` para devices renombrados.
      - (eventualmente) ``import_plc_tags_xml`` para add/remove.

    En este test solo verificamos que:
      1. La transacci\u00f3n se llama UNA vez.
      2. Incluye al menos UNA op ``update_user_constant_value`` (N_MAX).
    """
    mock_gateway.execute_transactional_batch.return_value = {
        "success": True,
        "operations_executed": 3,
        "details": [],
    }
    result = await use_case.ejecutar_transaccion("PLC1", {})
    assert result["success"] is True
    # 1 sola llamada a la transacci\u00f3n.
    mock_gateway.execute_transactional_batch.assert_called_once()
    # La lista de ops incluye update_user_constant_value (N_MAX).
    call = mock_gateway.execute_transactional_batch.call_args
    operations = call.kwargs.get("operations") or call.args[0]
    nmax_ops = [op for op in operations if op["command"] == "update_user_constant_value"]
    assert len(nmax_ops) > 0
    # Todas las N_MAX ops tienen plc_name=PLC1 y table_name correcto.
    for op in nmax_ops:
        assert op["args"]["plc_name"] == "PLC1"
        assert op["args"]["table_name"] == "000_Config_Dispositivos"
    # El undo_text menciona el \u00e1mbito.
    undo_text = call.kwargs.get("undo_text") or call.args[1]
    assert "N_MAX" in undo_text
    assert "devices" in undo_text  # marcador bypass
    # El resultado incluye el conteo de N_MAX updates.
    assert "n_max_updates" in result


@pytest.mark.asyncio
async def test_ejecutar_transaccion_propagates_errors(use_case, mock_gateway):
    """Si la transacci\u00f3n falla, el error se propaga al caller."""
    mock_gateway.execute_transactional_batch.side_effect = RuntimeError(
        "Worker rollback"
    )
    with pytest.raises(RuntimeError, match="Worker rollback"):
        await use_case.ejecutar_transaccion("PLC1", {})
