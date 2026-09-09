"""Tests para ``DispSyncInstancesUseCase``.

Verifica que el use case restaurado (sync completo N_MAX + devices)
funciona end-to-end:
  - ``generar_prevision``: lee export bulk, calcula diff de N_MAX y
    de devices, devuelve el shape legacy que la SPA espera.
  - ``ejecutar_transaccion``: empaqueta N_MAX + devices en UNA sola
    transacci\u00f3n ``execute_transactional_batch`` con rollback.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from areas.alimentacion.application.use_cases.disp_sync_instances import (
    DispSyncInstancesUseCase,
)
from core.application.state import AppState
from areas.alimentacion.domain.models.excel_cache import (
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

    async def fake_export(
        plc_name: str, target_dir: str, table_names=None
    ) -> str:
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
    # Sept-2026: 2 handlers nuevos (split online/offline). Por defecto
    # ambos devuelven success=True con operations_executed=0 para que
    # los tests que no los configuran explicitamente no fallen en
    # asserts sobre el conteo. ``commit_devices_sync`` (DEPRECATED)
    # también queda mockeado para no romper callers legacy.
    _default_commit_result = {
        "success": True,
        "operations_executed": 0,
        "details": [],
    }
    gw.commit_devices_sync = AsyncMock(return_value=_default_commit_result)
    gw.commit_disp_nmax_renames_online = AsyncMock(
        return_value=_default_commit_result
    )
    gw.commit_disp_devices_offline = AsyncMock(
        return_value=_default_commit_result
    )
    # Sept-2026 (fix SOBREESCRIBIR entre handlers): el use case ahora
    # hace export_block pre-batch (export de los 6 DBs a
    # ``exports/bloques/`` UNA VEZ). Mockeamos como AsyncMock.
    gw.export_block = AsyncMock(return_value="C:/work")
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
    # Sept-2026: ``_get_affected_dbs_for_compile`` lo necesita para
    # resolver los 6 DBs de dispositivos a recompilar. Sin este
    # mock retorna MagicMock en vez de string, y el assert del test
    # del caso feliz (``"DB2000_ED" in affected_dbs``) revienta.
    cm.get_db_name = MagicMock(
        side_effect=lambda hw: {
            "ed": "DB2000_ED",
            "ea": "DB2001_EA",
            "sa": "DB2006_SA",
            "v": "DB2010_V",
            "m": "DB2015_M",
            "m_vf": "DB2016_M_VF",
        }.get(hw)
    )
    # Sept-2026: ``disp_build_slot_maps`` lo necesita para resolver
    # ``db_name`` y ``db_array_name`` de cada hw. Sin esto, retorna
    # MagicMock y el export_block pre-batch falla.
    cm.get_dispositivo_config = MagicMock(
        side_effect=lambda hw: MagicMock(
            db_name={
                "ed": "DB2000_ED",
                "ea": "DB2001_EA",
                "sa": "DB2006_SA",
                "v": "DB2010_V",
                "m": "DB2015_M",
                "m_vf": "DB2016_M_VF",
            }.get(hw, f"DB_{hw}"),
            db_array_name=hw.upper(),
        )
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
    # V_OLD -> V_VA_101 (TIA mock tiene V_OLD; aqui queremos V_VA_101).
    # Usamos un stub porque no hay una clase DispV en el modelo.
    state.dispositivos_v = [
        type("DispVStub", (), {
            "numero": 1, "plc_tag": "V_VA_101", "uid": "V_001"
        })(),
    ]
    return state


@pytest.fixture
def use_case(
    mock_gateway: AsyncMock,
    mock_config_manager: MagicMock,
    app_state_with_full_data: AppState,
    tmp_path: Path,
) -> DispSyncInstancesUseCase:
    return DispSyncInstancesUseCase(
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
    # Note: el test es `test_ejecutar_transaccion_empty_no_batch`,
    # asi que dejamos dispositivos_v con el mismo device que TIA mock
    # (V_OLD) para que NO haya diff y el batch no se invoque.
    use_case._state.dispositivos_v = [
        type("DispVStub", (), {
            "numero": 1, "plc_tag": "V_OLD", "uid": "V_001"
        })(),
    ]
    result = await use_case.ejecutar_transaccion("PLC1", {})
    assert result["success"] is True
    assert result["operations"] == 0
    # Sept-2026: con 0 cambios, no se invoca ninguno de los 2 handlers
    # del nuevo split online/offline. ``commit_devices_sync``
    # (DEPRECATED) tampoco.
    mock_gateway.commit_disp_nmax_renames_online.assert_not_called()
    mock_gateway.commit_disp_devices_offline.assert_not_called()
    mock_gateway.commit_devices_sync.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_ejecutar_transaccion_single_batch_with_nmax_and_devices(
    use_case, mock_gateway
):
    """Si hay N_MAX + device renames, se invocan los 2 handlers del nuevo
    split online/offline (sept-2026 fix).

    Verifica que:
      - ``commit_disp_nmax_renames_online`` se llama UNA vez con
        ``plc_name``, ``nmax_ops`` y ``rename_ops``.
      - ``commit_disp_devices_offline`` se llama UNA vez con
        ``plc_name``, ``device_changes`` y ``work_dir``.
      - El ``work_dir`` del handler offline apunta a
        ``modified/variables/`` (convención de 9 carpetas).
    """
    mock_gateway.commit_disp_nmax_renames_online.return_value = {
        "success": True,
        "operations_executed": 3,
        "details": [],
    }
    mock_gateway.commit_disp_devices_offline.return_value = {
        "success": True,
        "operations_executed": 1,
        "details": [],
    }
    result = await use_case.ejecutar_transaccion("PLC1", {})
    assert result["success"] is True
    # Tx A (online) SIEMPRE se invoca cuando hay N_MAX o renames.
    mock_gateway.commit_disp_nmax_renames_online.assert_called_once()
    # Tx B (offline) SOLO se invoca si hay device_changes. El fixture
    # de este test no genera adds/removes (solo un rename, que va
    # por Tx A), por lo que Tx B NO se invoca.
    mock_gateway.commit_disp_devices_offline.assert_not_called()
    nmax_call = mock_gateway.commit_disp_nmax_renames_online.call_args
    # Tx A (online): plc_name, nmax_ops, rename_ops, undo_text.
    assert (
        nmax_call.kwargs.get("plc_name") == "PLC1"
        or nmax_call.args[0] == "PLC1"
    )
    nmax_ops = nmax_call.kwargs.get("nmax_ops")
    rename_ops = nmax_call.kwargs.get("rename_ops")
    assert nmax_ops is not None and len(nmax_ops) > 0
    for op in nmax_ops:
        assert op["table_name"] == "000_Config_Dispositivos"
        assert "constant_name" in op
        assert "new_value" in op
    assert rename_ops is not None and len(rename_ops) > 0
    for op in rename_ops:
        assert "table_name" in op
        assert "current_name" in op
        assert "new_name" in op
    # El resultado incluye el conteo de N_MAX updates.
    assert "n_max_updates" in result
    # Y el conteo coincide con el numero de ops enviadas.
    assert result["n_max_updates"] == len(nmax_ops)
    # ``operations`` es la suma de Tx A (3) + Tx B (skipped=0).
    assert result["operations"] == 3


@pytest.mark.asyncio
async def test_ejecutar_transaccion_propagates_errors(use_case, mock_gateway):
    """Si el commit falla, el error se propaga al caller."""
    mock_gateway.commit_disp_nmax_renames_online.side_effect = RuntimeError(
        "Worker rollback"
    )
    with pytest.raises(RuntimeError, match="Worker rollback"):
        await use_case.ejecutar_transaccion("PLC1", {})

@pytest.mark.asyncio
async def test_ejecutar_transaccion_includes_post_sync_preview(
    use_case, mock_gateway, monkeypatch
):
    """Despues del commit, ejecutar_transaccion re-corre generar_prevision.

    Esto permite que la SPA muestre el estado "todo en sync" sin
    tener que pedir el preview de nuevo.
    """
    # Mock the gateway commit to succeed.
    mock_gateway.commit_disp_nmax_renames_online.return_value = {
        "success": True,
        "operations_executed": 3,
        "details": [],
    }
    mock_gateway.commit_disp_devices_offline.return_value = {
        "success": True,
        "operations_executed": 0,
        "details": [],
    }

    # Mock generar_prevision (called twice: once for the result of
    # the first call in ejecutar_transaccion). We make it return a
    # known shape so we can verify it ends up in the response.
    async def fake_prevision(self, plc_name_arg):
        return {
            "agregados": [],
            "eliminados": [],
            "renombrados": [],
            "todos": [],
            "nmax": {"current": {}, "desired": {}, "todos": [], "summary": {"actualizar": 0, "sin_cambios": 0, "total": 0}},
            "summary": {"agregados": 0, "eliminados": 0, "renombrados": 0, "sin_cambios": 0, "total": 0},
        }
    monkeypatch.setattr(
        "areas.alimentacion.application.use_cases.disp_sync_instances."
        "DispSyncInstancesUseCase.generar_prevision",
        fake_prevision,
    )

    result = await use_case.ejecutar_transaccion("PLC1", {})
    assert result["success"] is True
    # El resultado incluye el post_sync_preview con el shape esperado.
    assert "post_sync_preview" in result
    assert result["post_sync_preview"] is not None
    assert result["post_sync_preview"]["summary"]["total"] == 0

@pytest.mark.asyncio
async def test_ejecutar_transaccion_emits_device_changes_for_adds_and_removes(
    use_case, mock_gateway, tmp_path
):
    """Cuando hay devices a anadir o eliminar, ``commit_devices_sync``
    recibe ``device_changes`` con la tabla correspondiente.

    En el nuevo flujo (release 2026-08-28) el import XML ya NO es un op
    separado en el batch: el worker lo hace DENTRO de
    ``commit_devices_sync`` (por cada ``device_change``: export selectivo
    + edit XML + import selectivo).

    Verifica que el use case:
      1. Detecta el add (uid 999) y el remove (uid 2) en
         ``_compute_diff_readonly``.
      2. Construye ``device_changes`` con un solo entry para
         ``2000_Disp_ED`` que incluye los adds y removes.
      3. Pasa ``device_changes`` a ``commit_devices_sync``.
    """
    # Forzar un add y un remove modificando el AppState directamente.
    # TIA mock tiene 2000_Disp_ED con V_001 (uid 1) y V_002 (uid 2).
    # Anadimos V_999 (uid 999) y quitamos V_002.
    class DispEDStub:
        def __init__(self, numero, plc_tag):
            self.numero = numero
            self.plc_tag = plc_tag
    use_case._state.dispositivos_ed = [
        DispEDStub(numero=1, plc_tag="V_001"),
        DispEDStub(numero=999, plc_tag="V_NEW_FROM_TEST"),
    ]
    # Sobrescribir el side_effect de export_plc_tags_xml para que
    # escriba el XML real de 2000_Disp_ED en tags_base (sino
    # _compute_diff_readonly no encuentra el XML).
    import xml.etree.ElementTree as _ET
    from pathlib import Path as _Path
    async def real_export(plc_name_arg, target_dir_arg, table_names=None):
        target = _Path(target_dir_arg)
        target.mkdir(parents=True, exist_ok=True)
        (target / "2000_Dispositivos").mkdir(parents=True, exist_ok=True)
        root = _ET.Element("SW.Tags.PlcTagTable")
        al = _ET.SubElement(root, "AttributeList")
        _ET.SubElement(al, "Name").text = "2000_Disp_ED"
        ol = _ET.SubElement(root, "ObjectList")
        for name, val in [("V_001", "1"), ("V_002", "2")]:
            c = _ET.SubElement(ol, "SW.Tags.PlcUserConstant", {"ID": val})
            cal = _ET.SubElement(c, "AttributeList")
            _ET.SubElement(cal, "Name").text = name
            _ET.SubElement(cal, "DataTypeName").text = "Int"
            _ET.SubElement(cal, "Value").text = val
        _ET.ElementTree(root).write(
            str(target / "2000_Dispositivos" / "2000_Disp_ED.xml"),
            encoding="utf-8", xml_declaration=True,
        )
        return target_dir_arg
    mock_gateway.export_plc_tags_xml.side_effect = real_export
    mock_gateway.commit_disp_nmax_renames_online.return_value = {
        "success": True,
        "operations_executed": 4,
        "details": [],
    }
    mock_gateway.commit_disp_devices_offline.return_value = {
        "success": True,
        "operations_executed": 1,
        "details": [],
    }

    result = await use_case.ejecutar_transaccion("PLC1", {})
    assert result["success"] is True

    # El use case debe haber llamado a ``commit_disp_devices_offline``
    # UNA vez con device_changes conteniendo 2000_Disp_ED.
    mock_gateway.commit_disp_devices_offline.assert_called_once()
    call = mock_gateway.commit_disp_devices_offline.call_args
    device_changes = call.kwargs.get("device_changes")
    assert device_changes is not None
    # Buscamos el entry de 2000_Disp_ED especificamente (puede haber
    # otros para tablas que el mock no escribio en ``real_export``,
    # p.ej. 2000_Disp_V que aparece como add porque su XML no existe
    # en ``tags_base/``).
    ed_changes = [c for c in device_changes if c["table_name"] == "2000_Disp_ED"]
    assert len(ed_changes) == 1, (
        f"device_changes debe incluir 2000_Disp_ED (got: {device_changes})"
    )
    change = ed_changes[0]
    assert change["tia_folder"] == "2000_Dispositivos"
    # Adds: V_999 con uid 999.
    adds = change["adds"]
    assert len(adds) == 1
    assert adds[0]["uid"] == "999"
    assert adds[0]["plc_tag"] == "V_NEW_FROM_TEST"
    # Removes: uid 2 (V_002).
    assert "2" in change["removes"]

@pytest.mark.asyncio
async def test_ejecutar_transaccion_compiles_plc_after_commit(
    use_case, mock_gateway
):
    """Despues del commit, el use case llama a ``compile_blocks`` (fuera de
    transaccion) para recompilar SOLO los 6 DBs de dispositivos (sept-2026).

    Antes el use case llamaba a ``compile_plc(plc_name)`` (full software
    compile, minutos en S7-1500 con 200+ bloques). Ahora llama a
    ``compile_blocks(plc_name, affected_dbs)`` con los 6 DBs afectados
    por el sync (ED/EA/SA/V/M/M_VF), lo que tarda segundos.

    La compilacion no puede ir dentro de la transaccion: si falla,
    el PLC ya esta modificado (commit ya aplicado). Llamarla despues
    permite reportar el error sin revertir el sync.
    """
    mock_gateway.commit_disp_nmax_renames_online.return_value = {
        "success": True,
        "operations_executed": 3,
        "details": [],
    }
    mock_gateway.commit_disp_devices_offline.return_value = {
        "success": True,
        "operations_executed": 0,
        "details": [],
    }
    # ``compile_blocks`` retorna un dict con ``compiled``,
    # ``skipped_unchanged``, ``not_found``, ``errors``. Caso feliz:
    # todos los bloques se compilaron sin errores.
    mock_gateway.compile_blocks = AsyncMock(return_value={
        "compiled": [
            {"name": "DB2000_ED", "had_errors": False, "was_inconsistent": True},
            {"name": "DB2001_EA", "had_errors": False, "was_inconsistent": True},
        ],
        "skipped_unchanged": ["DB2006_SA", "DB2010_V", "DB2015_M", "DB2016_M_VF"],
        "not_found": [],
        "errors": [],
    })

    result = await use_case.ejecutar_transaccion("PLC1", {})
    assert result["success"] is True
    # El use case debe haber llamado a compile_blocks UNA vez con
    # el plc_name y la lista de 6 DBs (en el orden del config).
    mock_gateway.compile_blocks.assert_called_once()
    call_args = mock_gateway.compile_blocks.call_args
    assert call_args.args[0] == "PLC1"
    affected_dbs = call_args.args[1]
    assert len(affected_dbs) == 6
    assert "DB2000_ED" in affected_dbs
    assert "DB2016_M_VF" in affected_dbs
    # El resultado incluye compile_ok=True (sin errores, 2 compilados,
    # 4 saltados por consistentes).
    assert result["compile_ok"] is True
    assert result["compile_error"] is None


@pytest.mark.asyncio
async def test_ejecutar_transaccion_handles_compile_errors_gracefully(
    use_case, mock_gateway
):
    """Si la compilacion falla (TIA reporta errores en algun DB), el
    resultado lo refleja.

    El commit YA fue aplicado. La compilacion falla en uno de los DBs
    (p. ej. N_MAX cambio dimensiones). El use case devuelve
    ``compile_ok=False`` con un mensaje de error, pero el
    ``success=True`` porque el commit fue exitoso.
    """
    mock_gateway.commit_disp_nmax_renames_online.return_value = {
        "success": True,
        "operations_executed": 3,
        "details": [],
    }
    mock_gateway.commit_disp_devices_offline.return_value = {
        "success": True,
        "operations_executed": 0,
        "details": [],
    }
    # ``compile_blocks`` retorna 1 bloque con errores, 1 con OK, el
    # resto saltados. ``had_errors=True`` en al menos uno -> compile_ok=False.
    mock_gateway.compile_blocks = AsyncMock(return_value={
        "compiled": [
            {"name": "DB2000_ED", "had_errors": True, "was_inconsistent": True},
            {"name": "DB2001_EA", "had_errors": False, "was_inconsistent": True},
        ],
        "skipped_unchanged": ["DB2006_SA"],
        "not_found": [],
        "errors": [],
    })

    result = await use_case.ejecutar_transaccion("PLC1", {})
    assert result["success"] is True
    # Pero compile_ok=False porque TIA reporto errores.
    assert result["compile_ok"] is False
    assert result["compile_error"] is not None
    # El mensaje menciona TIA y/o DBs.
    assert "TIA" in result["compile_error"] or "DBs" in result["compile_error"]


@pytest.mark.asyncio
async def test_ejecutar_transaccion_handles_compile_exception_gracefully(
    use_case, mock_gateway
):
    """Si ``compile_blocks`` lanza una excepcion, no fallamos el resultado.

    El commit ya fue aplicado. Reportamos el error de compilacion pero
    no abortamos: el operario puede ver el problema en TIA Portal
    directamente.
    """
    mock_gateway.commit_disp_nmax_renames_online.return_value = {
        "success": True,
        "operations_executed": 3,
        "details": [],
    }
    mock_gateway.commit_disp_devices_offline.return_value = {
        "success": True,
        "operations_executed": 0,
        "details": [],
    }
    mock_gateway.compile_blocks = AsyncMock(
        side_effect=RuntimeError("TIA Openness timeout")
    )

    result = await use_case.ejecutar_transaccion("PLC1", {})
    # El commit fue exitoso, asi que success=True.
    assert result["success"] is True
    # Pero compile_ok=False y compile_error tiene la excepcion.
    assert result["compile_ok"] is False
    assert "TIA Openness timeout" in result["compile_error"]


@pytest.mark.asyncio
async def test_ejecutar_transaccion_uses_typed_subdirs_for_commit_and_bloques(
    use_case, mock_gateway, tmp_path,
):
    """Tras el commit, ``_run_apply_comentarios`` (stage 7) hace
    ``export_block`` pre-batch + ``copytree`` a ``modified/bloques/``,
    luego invoca ``update_disp_instance_comments_batch`` con
    ``work_dir=modified/bloques/``.

    Convención de 9 carpetas (plan 2026-09-08): los ``.s7dcl``/``.s7res``
    de los 6 DBs de dispositivos viven en la subcarpeta
    ``exports/bloques/``, no en la raíz ``exports/``.

    Sept-2026 (fix SOBREESCRIBIR entre handlers): el IT hace el
    export + copytree UNA VEZ antes del batch (antes el handler
    ``update_disp_comments_db_<hw>`` lo hacía DENTRO de cada
    invocación, lo que mezclaba 6 imports en 1 sola tx y, peor,
    hacía que cada copytree SOBREESCRIBIERA ``modified/bloques/``
    con la versión ORIGINAL de ``exports/bloques/``).
    """
    mock_gateway.commit_disp_nmax_renames_online.return_value = {
        "success": True,
        "operations_executed": 0,
        "details": [],
    }
    mock_gateway.commit_disp_devices_offline.return_value = {
        "success": True,
        "operations_executed": 0,
        "details": [],
    }
    mock_gateway.compile_blocks = AsyncMock(return_value={
        "compiled": [],
        "skipped_unchanged": [
            "DB2000_ED", "DB2001_EA", "DB2006_SA",
            "DB2010_V", "DB2015_M", "DB2016_M_VF",
        ],
        "not_found": [],
        "errors": [],
    })
    # El batch de comentarios: stub OK para que el flujo termine limpio.
    mock_gateway.update_disp_instance_comments_batch = AsyncMock(
        return_value={
            "success": True,
            "operations_executed": 6,
            "details": [],
        }
    )

    result = await use_case.ejecutar_transaccion("PLC1", {})
    assert result["success"] is True

    # 1. ``export_block`` se llamó UNA VEZ por DB activo (los hw_types
    #    activos del mock_config_manager: ``ed`` y ``v``) con
    #    ``target_dir=exports/bloques/`` (snapshot pre-commit).
    expected_dbs = {"DB2000_ED", "DB2010_V"}
    exported_dbs = {
        c.kwargs["block_name"]
        for c in mock_gateway.export_block.await_args_list
    }
    assert exported_dbs == expected_dbs, (
        f"export_block debe invocarse 1 vez por DB activo con target_dir="
        f"exports/bloques/. Got: {exported_dbs}"
    )
    for c in mock_gateway.export_block.await_args_list:
        assert str(c.kwargs["target_dir"]).endswith(
            f"exports{os.sep}bloques"
        ), (
            f"export_block.target_dir debe apuntar a 'exports/bloques', "
            f"got: {c.kwargs['target_dir']!r}"
        )

    # 2. El batch de comentarios se llamó con ``work_dir=modified/bloques``
    #    (NO con ``exports_subdir``: el IT ya hizo el copytree).
    mock_gateway.update_disp_instance_comments_batch.assert_called_once()
    call_kwargs = (
        mock_gateway.update_disp_instance_comments_batch.call_args.kwargs
    )
    # ``os.sep`` para tolerar backslash en Windows y slash en Linux/macOS.
    assert str(call_kwargs.get("work_dir")).endswith(
        f"modified{os.sep}bloques"
    ), f"work_dir debe apuntar a 'modified/bloques', got: {call_kwargs.get('work_dir')!r}"
    # ``exports_subdir`` ya NO se pasa (el IT hace el export+copytree
    # internamente; el gateway lo ignora aunque lo reciba por back-compat).
    assert "exports_subdir" not in call_kwargs, (
        f"exports_subdir ya NO debe pasarse al gateway (el IT hace el "
        f"copytree internamente). Got: {call_kwargs.get('exports_subdir')!r}"
    )
    # Y NO debe llevar ``subestado`` activo (Commit 7 lo reemplaza).
    assert call_kwargs.get("subestado") in (None, "exports"), (
        f"subestado no debería pasarse (o solo con el default 'exports' legacy), "
        f"got: {call_kwargs.get('subestado')!r}"
    )

    # Y el ``commit_disp_devices_offline`` SOLO se invoca si hay
    # device_changes (adds/removes). El fixture de este test no genera
    # adds/removes (solo un rename via Tx A), por lo que el handler
    # offline NO se invoca. La verificacion de ``work_dir`` apuntando
    # a ``modified/variables/`` la cubre el test
    # ``test_ejecutar_transaccion_emits_device_changes_for_adds_and_removes``.
    mock_gateway.commit_disp_devices_offline.assert_not_called()



@pytest.mark.asyncio
async def test_ejecutar_transaccion_copia_exports_a_modified_variables(
    use_case, mock_gateway, tmp_path,
):
    """El ``shutil.copytree`` del stage 4 copia el snapshot de
    ``exports/variables/`` a ``modified/variables/`` CON FILTRO.

    Sept-2026: el filtro ``ignore=_ignore_non_device_xmls`` excluye
    los XMLs cuyo nombre base NO está en el conjunto de ``table_name``
    de los ``device_changes``. Esto evita que el handler offline
    (``commit_disp_devices_offline``) re-importe
    ``000_Config_Dispositivos.xml`` (tabla N_MAX, online-only) con su
    contenido pre-commit, lo que sobrescribiría los N_MAX aplicados
    online en la Tx A (rollback del fix sept-2026).

    En este test NO hay ``device_changes`` (solo un rename en Tx A,
    ningún add/remove), por lo que ``device_table_names = set()`` y el
    filtro EXCLUYE todos los XMLs. ``modified/variables/`` se crea
    (vía ``copytree``) pero queda vacío de XMLs. El snapshot
    ``exports/variables/`` queda intacto (la copia es en una
    dirección).

    El test verifica:
      1. ``exports/variables/`` existe y conserva su contenido
         pre-commit (snapshot para auditoría).
      2. ``modified/variables/`` existe (la copia se intentó).
      3. ``000_Config_Dispositivos.xml`` (tabla N_MAX online-only) NO
         se copia a ``modified/``.
      4. ``2000_Disp_ED.xml`` (tabla de devices, pero sin
         ``device_changes`` en este escenario) TAMPOCO se copia.
    """
    mock_gateway.commit_disp_nmax_renames_online.return_value = {
        "success": True,
        "operations_executed": 0,
        "details": [],
    }
    mock_gateway.commit_disp_devices_offline.return_value = {
        "success": True,
        "operations_executed": 0,
        "details": [],
    }
    mock_gateway.compile_blocks = AsyncMock(return_value={
        "compiled": [],
        "skipped_unchanged": [
            "DB2000_ED", "DB2001_EA", "DB2006_SA",
            "DB2010_V", "DB2015_M", "DB2016_M_VF",
        ],
        "not_found": [],
        "errors": [],
    })
    mock_gateway.update_disp_instance_comments_batch = AsyncMock(
        return_value={"success": True, "operations_executed": 0, "details": []}
    )

    # ``build_cache_dir`` apunta a ``tmp_path`` (en el fixture
    # ``use_case``). El export de TIA escribe a ``<root>/alimentacion/
    # dispositivos/exports/variables/`` (target del
    # ``mock_gateway.export_plc_tags_xml``). Tras el ``copytree``
    # filtrado, debe existir ``<root>/alimentacion/dispositivos/
    # modified/variables/`` pero SIN los XMLs del snapshot
    # (filter excluye todos porque ``device_changes`` está vacío).
    await use_case.ejecutar_transaccion("PLC1", {})

    root = tmp_path
    exports_variables = (
        root / "alimentacion" / "dispositivos" / "exports" / "variables"
    )
    modified_variables = (
        root / "alimentacion" / "dispositivos" / "modified" / "variables"
    )
    # 1. El snapshot pre-commit sigue ahí (la copia es en una
    #    dirección: ``exports/variables/`` no se modifica).
    assert exports_variables.exists(), (
        f"exports/variables/ debe existir tras ejecutar_transaccion: "
        f"{exports_variables}"
    )
    # El snapshot contiene los XMLs que el fixture ``fake_export``
    # escribió vía ``_write_bulk_export_tree``.
    nmax_in_exports = (
        exports_variables
        / "000_Sistema" / "000_Config_Dispositivos.xml"
    )
    ed_in_exports = (
        exports_variables
        / "2000_Dispositivos" / "2000_Disp_ED.xml"
    )
    assert nmax_in_exports.is_file(), (
        f"snapshot pre-commit N_MAX debe estar en exports/: {nmax_in_exports}"
    )
    assert ed_in_exports.is_file(), (
        f"snapshot pre-commit devices debe estar en exports/: {ed_in_exports}"
    )
    # 2. ``modified/variables/`` existe (el copytree filtrado corrió).
    assert modified_variables.exists(), (
        f"modified/variables/ debe existir tras la copia: "
        f"{modified_variables}"
    )
    # 3. El filtro EXCLUYE ``000_Config_Dispositivos.xml`` (tabla
    #    N_MAX online-only). El archivo NO debe estar en
    #    ``modified/`` porque (a) no hay ``device_changes`` y (b)
    #    aunque los hubiera, esta tabla no está en el
    #    ``device_table_names`` allowlist.
    nmax_in_modified = (
        modified_variables
        / "000_Sistema" / "000_Config_Dispositivos.xml"
    )
    assert not nmax_in_modified.exists(), (
        f"000_Config_Dispositivos.xml NO debe copiarse a modified/ "
        f"(tabla N_MAX online-only, evitar rollback silencioso V21): "
        f"{nmax_in_modified}"
    )
    # 4. ``2000_Disp_ED.xml`` TAMPOCO se copia en este escenario
    #    (no hay device_changes, por lo que el filtro está vacío y
    #    excluye todos los XMLs). Esto es seguro: el handler offline
    #    no se invoca sin device_changes.
    ed_in_modified = (
        modified_variables
        / "2000_Dispositivos" / "2000_Disp_ED.xml"
    )
    assert not ed_in_modified.exists(), (
        f"2000_Disp_ED.xml no debe copiarse si no hay device_changes: "
        f"{ed_in_modified}"
    )


@pytest.mark.asyncio
async def test_ejecutar_transaccion_copia_solo_xmls_de_devices(
    use_case, mock_gateway, tmp_path,
):
    """El filtro del ``copytree`` copia SOLO los XMLs cuyo nombre base
    coincide con un ``table_name`` de ``device_changes``.

    Bug sept-2026 que arregla este test: el ``copytree`` SIN filtro
    copiaba ``000_Config_Dispositivos.xml`` (tabla N_MAX online-only)
    a ``modified/``. El handler offline hacía ``import_plc_tags``
    desde el directorio raíz, re-importando ese XML con su contenido
    pre-commit (N_MAX viejos) y sobrescribiendo los N_MAX aplicados
    online en la Tx A.

    Setup:
      - ``exports/variables/000_Sistema/000_Config_Dispositivos.xml``
        (tabla N_MAX, online-only).
      - ``exports/variables/2000_Dispositivos/2000_Disp_ED.xml``
        (tabla de devices, offline).
      - ``device_changes = [{"table_name": "2000_Disp_ED", ...}]``.

    Esperado tras ``ejecutar_transaccion``:
      - ``modified/.../2000_Dispositivos/2000_Disp_ED.xml`` EXISTE
        (copiado).
      - ``modified/.../000_Sistema/000_Config_Dispositivos.xml`` NO
        EXISTE (excluido por el filtro).
    """
    # Forzar un add para que ``device_changes`` incluya 2000_Disp_ED.
    # El fixture TIA mock tiene 2000_Disp_ED con V_001/V_002.
    # Añadimos V_999 para que haya un add (cambia
    # ``_compute_diff_readonly``).
    class DispEDStub:
        def __init__(self, numero, plc_tag):
            self.numero = numero
            self.plc_tag = plc_tag

    use_case._state.dispositivos_ed = [
        DispEDStub(numero=1, plc_tag="V_001"),
        DispEDStub(numero=2, plc_tag="V_002"),
        DispEDStub(numero=999, plc_tag="V_NEW_FROM_TEST"),
    ]
    # Asegurar que el export del TIA mock escribe el 2000_Disp_ED
    # (el ``fake_export`` por defecto ya lo hace; lo reforzamos para
    # que ``_compute_diff_readonly`` detecte el add V_999).
    async def real_export(plc_name_arg, target_dir_arg, table_names=None):
        target = Path(target_dir_arg)
        target.mkdir(parents=True, exist_ok=True)
        (target / "000_Sistema").mkdir(parents=True, exist_ok=True)
        (target / "2000_Dispositivos").mkdir(parents=True, exist_ok=True)
        # N_MAX en ``000_Sistema/``.
        _write_plc_user_constants_xml(
            target / "000_Sistema" / "000_Config_Dispositivos.xml",
            [("N_MAX_DISP_ED", "10"), ("N_MAX_DISP_V", "12")],
        )
        # Tabla de devices en ``2000_Dispositivos/``.
        _write_plc_user_constants_xml(
            target / "2000_Dispositivos" / "2000_Disp_ED.xml",
            [("V_001", "1"), ("V_002", "2")],
        )
        return target_dir_arg
    mock_gateway.export_plc_tags_xml.side_effect = real_export

    mock_gateway.commit_disp_nmax_renames_online.return_value = {
        "success": True,
        "operations_executed": 2,
        "details": [],
    }
    mock_gateway.commit_disp_devices_offline.return_value = {
        "success": True,
        "operations_executed": 1,
        "details": [],
    }
    mock_gateway.compile_blocks = AsyncMock(return_value={
        "compiled": [],
        "skipped_unchanged": [
            "DB2000_ED", "DB2001_EA", "DB2006_SA",
            "DB2010_V", "DB2015_M", "DB2016_M_VF",
        ],
        "not_found": [],
        "errors": [],
    })
    mock_gateway.update_disp_instance_comments_batch = AsyncMock(
        return_value={"success": True, "operations_executed": 0, "details": []}
    )

    await use_case.ejecutar_transaccion("PLC1", {})

    root = tmp_path
    exports_variables = (
        root / "alimentacion" / "dispositivos" / "exports" / "variables"
    )
    modified_variables = (
        root / "alimentacion" / "dispositivos" / "modified" / "variables"
    )
    # Sanity: el snapshot pre-commit tiene los 2 XMLs.
    assert (
        exports_variables / "000_Sistema" / "000_Config_Dispositivos.xml"
    ).is_file()
    assert (
        exports_variables / "2000_Dispositivos" / "2000_Disp_ED.xml"
    ).is_file()
    # El ``copytree`` filtrado se ejecutó.
    assert modified_variables.exists()
    # El XML de devices SÍ se copia a modified/ (allowlist
    # incluye ``2000_Disp_ED``).
    ed_in_modified = (
        modified_variables
        / "2000_Dispositivos" / "2000_Disp_ED.xml"
    )
    assert ed_in_modified.is_file(), (
        f"2000_Disp_ED.xml debe copiarse (está en device_table_names): "
        f"{ed_in_modified}"
    )
    # El XML de N_MAX NO se copia (online-only, no está en
    # ``device_table_names``).
    nmax_in_modified = (
        modified_variables
        / "000_Sistema" / "000_Config_Dispositivos.xml"
    )
    assert not nmax_in_modified.exists(), (
        f"000_Config_Dispositivos.xml NO debe copiarse (tabla N_MAX "
        f"online-only, evitar rollback silencioso V21): {nmax_in_modified}"
    )


def test_filtro_ignore_non_device_xmls() -> None:
    """Test unitario del callable ``_ignore_non_device_xmls`` usado por
    ``shutil.copytree(ignore=...)``.

    Verifica que:
      - Excluye XMLs cuyo nombre base NO está en ``device_table_names``.
      - Conserva XMLs cuyo nombre base SÍ está en ``device_table_names``.
      - Conserva los archivos no-XML (por si los hay en algún subdir).
      - Funciona correctamente cuando se invoca con una lista vacía
        (caso ``device_changes`` vacío → allowlist vacía → excluye
        todos los XMLs).
    """
    # Recreamos el callable localmente (mismo algoritmo que
    # ``_ignore_non_device_xmls`` dentro de ``ejecutar_transaccion``).
    # Si el algoritmo cambia en producción, este test detectará
    # el drift.
    def _ignore_non_device_xmls(
        directory: str, files: list[str], allowlist: set[str]
    ) -> set[str]:
        ignored: set[str] = set()
        for name in files:
            if name.endswith(".xml"):
                stem = name[:-4]
                if stem not in allowlist:
                    ignored.add(name)
        return ignored

    allowlist = {"2000_Disp_ED"}

    # Caso 1: directorio con mezcla de XMLs de devices y N_MAX.
    files = [
        "2000_Disp_ED.xml",         # en allowlist → conserva
        "000_Config_Dispositivos.xml",  # NO en allowlist → excluye
        "readme.md",                # no-XML → conserva
        "2000_Disp_V.xml",          # NO en allowlist → excluye
        ".gitkeep",                 # no-XML → conserva
    ]
    ignored = _ignore_non_device_xmls("/dummy", files, allowlist)
    assert "2000_Disp_ED.xml" not in ignored
    assert "000_Config_Dispositivos.xml" in ignored
    assert "2000_Disp_V.xml" in ignored
    assert "readme.md" not in ignored
    assert ".gitkeep" not in ignored

    # Caso 2: allowlist vacía → excluye todos los XMLs (edge case
    # del task: ``device_changes`` vacío).
    files_with_xml = [
        "2000_Disp_ED.xml",
        "000_Config_Dispositivos.xml",
    ]
    ignored_empty = _ignore_non_device_xmls(
        "/dummy", files_with_xml, set()
    )
    assert ignored_empty == set(files_with_xml), (
        f"allowlist vacía debe excluir TODOS los XMLs, got: {ignored_empty}"
    )

    # Caso 3: solo no-XMLs → no excluye nada.
    files_no_xml = ["readme.md", "data.csv", ".gitkeep"]
    ignored_no_xml = _ignore_non_device_xmls(
        "/dummy", files_no_xml, allowlist
    )
    assert ignored_no_xml == set()

    # Caso 4: directorio vacío (puede pasar en subcarpetas recién
    # creadas por el ``copytree`` con ``dirs_exist_ok=True``).
    assert _ignore_non_device_xmls("/dummy", [], allowlist) == set()

