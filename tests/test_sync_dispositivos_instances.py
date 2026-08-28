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

from areas.alimentacion.application.use_cases.sync_dispositivos_instances import (
    SyncDispositivosInstancesUseCase,
)
from core.application.state import AppState
from areas.alimentacion.domain.models.dispositivos import (
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
    # Nuevo op compuesto del worker (release 2026-08-28).
    # Por defecto devuelve success=True con operations_executed=0
    # para que los tests que no lo configuran explicitamente no fallen
    # en asserts sobre el conteo.
    gw.commit_devices_sync = AsyncMock(
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
    mock_gateway.commit_devices_sync.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_ejecutar_transaccion_single_batch_with_nmax_and_devices(
    use_case, mock_gateway
):
    """Si hay N_MAX + device renames, se invoca ``commit_devices_sync`` UNA vez.

    Verifica que ``commit_devices_sync`` se llama UNA vez con el
    payload completo:
      - ``nmax_ops`` (lista de ``{table_name, constant_name, new_value}``).
      - ``rename_ops`` (lista de ``{table_name, current_name, new_name}``).

    En esta release (2026-08-28): todo el flujo (N_MAX + renames +
    devices) corre bajo UNA sola transaccion TIA via el op compuesto
    ``commit_devices_sync`` del worker.
    """
    mock_gateway.commit_devices_sync.return_value = {
        "success": True,
        "operations_executed": 3,
        "details": [],
    }
    result = await use_case.ejecutar_transaccion("PLC1", {})
    assert result["success"] is True
    # 1 sola llamada al commit compuesto.
    mock_gateway.commit_devices_sync.assert_called_once()
    call = mock_gateway.commit_devices_sync.call_args
    # El op compuesto recibe: plc_name, nmax_ops, rename_ops,
    # device_changes, work_dir, undo_text.
    assert call.kwargs.get("plc_name") == "PLC1" or call.args[0] == "PLC1"
    nmax_ops = call.kwargs.get("nmax_ops")
    rename_ops = call.kwargs.get("rename_ops")
    device_changes = call.kwargs.get("device_changes")
    work_dir = call.kwargs.get("work_dir")
    undo_text = call.kwargs.get("undo_text")
    # 1) N_MAX: hay al menos 1 op de N_MAX.
    assert nmax_ops is not None and len(nmax_ops) > 0
    for op in nmax_ops:
        assert op["table_name"] == "000_Config_Dispositivos"
        assert "constant_name" in op
        assert "new_value" in op
    # 2) Renames: hay al menos 1 op de rename.
    assert rename_ops is not None and len(rename_ops) > 0
    for op in rename_ops:
        assert "table_name" in op
        assert "current_name" in op
        assert "new_name" in op
    # 3) device_changes es una lista (puede estar vacia si no hay adds/removes).
    assert isinstance(device_changes, list)
    # 4) work_dir existe y es ruta absoluta.
    assert work_dir is not None
    assert Path(work_dir).is_absolute()
    # 5) undo_text menciona el ambito.
    assert undo_text is not None
    assert "N_MAX" in undo_text
    assert "Dispositivos" in undo_text
    # El resultado incluye el conteo de N_MAX updates.
    assert "n_max_updates" in result
    # Y el conteo coincide con el numero de ops enviadas.
    assert result["n_max_updates"] == len(nmax_ops)


@pytest.mark.asyncio
async def test_ejecutar_transaccion_propagates_errors(use_case, mock_gateway):
    """Si el commit falla, el error se propaga al caller."""
    mock_gateway.commit_devices_sync.side_effect = RuntimeError(
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
    mock_gateway.commit_devices_sync.return_value = {
        "success": True,
        "operations_executed": 3,
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
        "areas.alimentacion.application.use_cases.sync_dispositivos_instances."
        "SyncDispositivosInstancesUseCase.generar_prevision",
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
    mock_gateway.commit_devices_sync.return_value = {
        "success": True,
        "operations_executed": 4,
        "details": [],
    }

    result = await use_case.ejecutar_transaccion("PLC1", {})
    assert result["success"] is True

    # El use case debe haber llamado a commit_devices_sync UNA vez con
    # device_changes conteniendo 2000_Disp_ED.
    mock_gateway.commit_devices_sync.assert_called_once()
    call = mock_gateway.commit_devices_sync.call_args
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
    """Despues del commit, el use case llama a ``compile_plc`` (fuera de transaccion).

    La compilacion no puede ir dentro de la transaccion: si falla,
    el PLC ya esta modificado (commit ya aplicado). Llamarla despues
    permite reportar el error sin revertir el sync.
    """
    mock_gateway.commit_devices_sync.return_value = {
        "success": True,
        "operations_executed": 3,
        "details": [],
    }
    # compile_plc retorna True si HAY errores (semantica Siemens).
    # Para el caso feliz, retornamos False.
    mock_gateway.compile_plc = AsyncMock(return_value=False)

    result = await use_case.ejecutar_transaccion("PLC1", {})
    assert result["success"] is True
    # El use case debe haber llamado a compile_plc UNA vez con el plc_name.
    mock_gateway.compile_plc.assert_called_once_with("PLC1")
    # El resultado incluye compile_ok=True (sin errores).
    assert result["compile_ok"] is True
    assert result["compile_error"] is None


@pytest.mark.asyncio
async def test_ejecutar_transaccion_handles_compile_errors_gracefully(
    use_case, mock_gateway
):
    """Si la compilacion falla (TIA reporta errores), el resultado lo refleja.

    El commit YA fue aplicado. La compilacion falla (p. ej. N_MAX cambio
    dimensiones de DBs). El use case devuelve ``compile_ok=False`` con
    un mensaje de error, pero el ``success=True`` porque el commit
    fue exitoso.
    """
    mock_gateway.commit_devices_sync.return_value = {
        "success": True,
        "operations_executed": 3,
        "details": [],
    }
    # compile_plc retorna True si HAY errores.
    mock_gateway.compile_plc = AsyncMock(return_value=True)

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
    """Si ``compile_plc`` lanza una excepcion, no fallamos el resultado.

    El commit ya fue aplicado. Reportamos el error de compilacion pero
    no abortamos: el operario puede ver el problema en TIA Portal
    directamente.
    """
    mock_gateway.commit_devices_sync.return_value = {
        "success": True,
        "operations_executed": 3,
        "details": [],
    }
    mock_gateway.compile_plc = AsyncMock(
        side_effect=RuntimeError("TIA Openness timeout")
    )

    result = await use_case.ejecutar_transaccion("PLC1", {})
    # El commit fue exitoso, asi que success=True.
    assert result["success"] is True
    # Pero compile_ok=False y compile_error tiene la excepcion.
    assert result["compile_ok"] is False
    assert "TIA Openness timeout" in result["compile_error"]


@pytest.mark.asyncio
async def test_ejecutar_transaccion_passes_bypass_flags_from_env(
    use_case, mock_gateway, monkeypatch
):
    """Las env vars ZC_SYNC_* se leen en el use case y se pasan al gateway.

    Esto permite al operario acotar el sync por fase SIN recompilar:
      set ZC_SYNC_RENAMES=0 → solo N_MAX
      set ZC_SYNC_DEVICES=0  → N_MAX + renames
    Verificamos el camino inverso: el use case lee las env vars y
    propaga los flags correctos al gateway.
    """
    import os
    # Forzamos que SOLO N_MAX este activo (renames y devices bypassed).
    monkeypatch.setenv("ZC_SYNC_NMAX", "1")
    monkeypatch.setenv("ZC_SYNC_RENAMES", "0")
    monkeypatch.setenv("ZC_SYNC_DEVICES", "0")
    # Necesitamos al menos 1 N_MAX op para que el batch no haga early-return.
    use_case._state.dimensiones = DimensionesDispositivos(
        num_disp_ed=15, num_disp_ea=0, num_disp_sa=0,
        num_disp_v=10, num_disp_m=0, num_disp_m_vf=0,
    )
    mock_gateway.commit_devices_sync = AsyncMock(
        return_value={"success": True, "operations_executed": 1, "details": []}
    )
    await use_case.ejecutar_transaccion("PLC1", {})
    mock_gateway.commit_devices_sync.assert_called_once()
    call = mock_gateway.commit_devices_sync.call_args
    assert call.kwargs.get("enable_nmax") is True
    assert call.kwargs.get("enable_renames") is False
    assert call.kwargs.get("enable_devices") is False


@pytest.mark.asyncio
async def test_ejecutar_transaccion_bypass_flags_default_true(
    use_case, mock_gateway, monkeypatch
):
    """Sin env vars (o con valores invalidos), todos los flags son True."""
    import os
    for v in ("ZC_SYNC_NMAX", "ZC_SYNC_RENAMES", "ZC_SYNC_DEVICES"):
        monkeypatch.delenv(v, raising=False)
    use_case._state.dimensiones = DimensionesDispositivos(
        num_disp_ed=15, num_disp_ea=0, num_disp_sa=0,
        num_disp_v=10, num_disp_m=0, num_disp_m_vf=0,
    )
    mock_gateway.commit_devices_sync = AsyncMock(
        return_value={"success": True, "operations_executed": 1, "details": []}
    )
    await use_case.ejecutar_transaccion("PLC1", {})
    call = mock_gateway.commit_devices_sync.call_args
    assert call.kwargs.get("enable_nmax") is True
    assert call.kwargs.get("enable_renames") is True
    assert call.kwargs.get("enable_devices") is True


@pytest.mark.asyncio
async def test_ejecutar_transaccion_bypass_env_various_truthy_values(
    use_case, mock_gateway, monkeypatch
):
    """Acepta varios formatos: 1/true/yes/on (True) y 0/false/no/off (False)."""
    import os
    test_cases = [
        (("1", "0", "true"), (True, False, True)),
        (("false", "yes", "off"), (False, True, False)),
        (("on", "no", "1"), (True, False, True)),
        (("", "1", "1"), (True, True, True)),  # vacio = default
        (("invalid", "1", "1"), (True, True, True)),  # invalido = default
    ]
    for nmax_env, expected in test_cases:
        monkeypatch.setenv("ZC_SYNC_NMAX", nmax_env[0])
        monkeypatch.setenv("ZC_SYNC_RENAMES", nmax_env[1])
        monkeypatch.setenv("ZC_SYNC_DEVICES", nmax_env[2])
        use_case._state.dimensiones = DimensionesDispositivos(
            num_disp_ed=15, num_disp_ea=0, num_disp_sa=0,
            num_disp_v=10, num_disp_m=0, num_disp_m_vf=0,
        )
        mock_gateway.commit_devices_sync = AsyncMock(
            return_value={"success": True, "operations_executed": 1, "details": []}
        )
        await use_case.ejecutar_transaccion("PLC1", {})
        call = mock_gateway.commit_devices_sync.call_args
        assert call.kwargs.get("enable_nmax") == expected[0], (
            f"env=({nmax_env!r}) expected enable_nmax={expected[0]}, "
            f"got {call.kwargs.get('enable_nmax')}"
        )
        assert call.kwargs.get("enable_renames") == expected[1]
        assert call.kwargs.get("enable_devices") == expected[2]
