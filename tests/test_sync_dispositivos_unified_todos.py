"""Tests de regresión: ``generar_prevision`` devuelve lista unificada ``todos``.

El método ``SyncDispositivosInstancesUseCase.generar_prevision`` debe
devolver, además de las listas legacy ``agregados/eliminados/renombrados``,
una lista ``todos`` con **una fila por dispositivo** (los del PLC + los
del AppState) y un campo ``status`` por fila:

  - ``"agregar"``     → en AppState pero no en TIA (value nuevo).
  - ``"renombrar"``   → mismo value, distinto plc_tag.
  - ``"eliminar"``    → en TIA pero no en AppState.
  - ``"sin_cambios"`` → mismo value y mismo plc_tag.

Esto alimenta la vista de pestañas del componente
``SincronizacionTia.js``: cada pestaña muestra la lista completa del
tipo (ED/EA/SA/V/M/MVF) ordenada por ``numero`` ascendente, con un
badge de estado por fila.

Estrategia: llamar a ``_compute_diff_readonly`` directamente (es
estático, no requiere gateway) y luego pasar el resultado a un
helper de construcción de la lista unificada. Si el helper no existe
como método público, lo cubrimos a través de ``generar_prevision`` con
un gateway mockeado.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock

import pytest

from application.state import AppState
from application.use_cases.sync_dispositivos_instances import (
    SyncDispositivosInstancesUseCase,
)
from core.alimentacion.models.dispositivos import DispV
from infrastructure.config_manager import ConfigManager
from infrastructure.gateway import TIAProcessGateway


def _write_plc_user_constants_xml(
    xml_path: Path,
    constants: list[tuple[str, str]],
) -> None:
    """Escribe un PlcTagTable XML con PlcUserConstant (value, name)."""
    root = ET.Element("SW.Tags.PlcTagTable")
    al = ET.SubElement(root, "AttributeList")
    ET.SubElement(al, "Name").text = xml_path.stem
    ol = ET.SubElement(root, "ObjectList")
    for value, name in constants:
        const = ET.SubElement(
            ol, "SW.Tags.PlcUserConstant", {"ID": name}
        )
        attr_list = ET.SubElement(const, "AttributeList")
        ET.SubElement(attr_list, "Name").text = name
        ET.SubElement(attr_list, "DataTypeName").text = "Int"
        ET.SubElement(attr_list, "Value").text = value
    ET.ElementTree(root).write(
        str(xml_path), encoding="utf-8", xml_declaration=True
    )


def _build_state_with_v(
    v_devices: list[tuple[int, str]],
) -> AppState:
    """Construye un AppState con DispV a partir de ``[(numero, plc_tag), ...]``."""
    state = AppState()
    state.dispositivos_v = [
        DispV(
            numero=num, plc_tag=plc_tag, plc_comentario="",
            descripcion="", uid=f"V_{num:03d}", tag=0, fat=0,
            s_byte=0, s_bit=0, rr_byte=0, rr_bit=0,
            rt_byte=0, rt_bit=0, gr_alarma="", cuadro="",
            observaciones="", plc_tipo="int",
            plc_index=0, hmi_index=0, hmi_texto="",
            cfg_habilitar="", cfg_byteretornoreposo="",
            cfg_bitretornoreposo="", cfg_byteretornotrabajo="",
            cfg_bitretornotrabajo="", cfg_byteactivacion="",
            cfg_bitactivacion="", cfg_habitreposo="",
            cfg_habitrtrabajo="", cfg_grupoalarma="",
            comentario_db="",
        )
        for num, plc_tag in v_devices
    ]
    return state


def _mock_config_manager() -> ConfigManager:
    """Crea un ConfigManager real apuntando al config.json del repo."""
    return ConfigManager("infrastructure/config.json")


def _mock_gateway_with_export(
    tmp_path: Path, tia_state: dict[str, list[tuple[str, str]]],
) -> MagicMock:
    """Mockea el gateway para que ``export_plc_tags_xml`` escriba
    ``tia_state`` en la carpeta recibida por argumento.

    El use case pasa como ``target_dir`` la ruta
    ``{build_cache_dir}/base/tags/``. El mock escribe ahí mismo con
    la jerarquía ``2000_Dispositivos/<tabla>.xml`` o
    ``000_Sistema/<tabla>.xml`` según el nombre.

    ``tia_state`` mapea nombre de tabla → lista de ``(value_str, plc_tag)``.
    """
    gw = MagicMock(spec=TIAProcessGateway)

    async def fake_export(plc_name, target_dir):
        base = Path(target_dir)
        base.mkdir(parents=True, exist_ok=True)
        dev_folder = base / "2000_Dispositivos"
        dev_folder.mkdir(parents=True, exist_ok=True)
        nmax_folder = base / "000_Sistema"
        nmax_folder.mkdir(parents=True, exist_ok=True)
        for table_name, constants in tia_state.items():
            if "Config_Dispositivos" in table_name:
                _write_plc_user_constants_xml(
                    nmax_folder / f"{table_name}.xml", constants
                )
            else:
                _write_plc_user_constants_xml(
                    dev_folder / f"{table_name}.xml", constants
                )
        return str(target_dir)

    gw.export_plc_tags_xml = AsyncMock(side_effect=fake_export)
    gw.execute_transactional_batch = AsyncMock(
        return_value={"success": True, "operations_executed": 0, "details": []}
    )
    return gw


# ──────────────────────────────────────────────────────────────────────
# Tests: lista unificada ``todos`` con status por fila
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_todos_includes_sin_cambios(tmp_path: Path) -> None:
    """Devices que ya coinciden deben aparecer como ``sin_cambios``."""
    state = _build_state_with_v([
        (1, "V_001"),  # igual a TIA
        (2, "V_002"),  # igual a TIA
    ])
    cm = _mock_config_manager()
    gw = _mock_gateway_with_export(tmp_path, {
        "2000_Disp_V": [
            ("1", "V_001"),
            ("2", "V_002"),
        ],
    })
    uc = SyncDispositivosInstancesUseCase(
        gateway=gw, config_manager=cm, state=state,
        build_cache_dir=tmp_path / "cache",
    )
    prev = await uc.generar_prevision("PLC1")

    todos_v = [r for r in prev["todos"] if r["type"] == "v"]
    assert len(todos_v) == 2
    assert all(r["status"] == "sin_cambios" for r in todos_v)
    # Orden por numero ascendente.
    assert [r["numero"] for r in todos_v] == [1, 2]
    # Sin cambios: actual == nuevo.
    for r in todos_v:
        assert r["actual"] == r["nuevo"]


@pytest.mark.asyncio
async def test_todos_marks_renombrar(tmp_path: Path) -> None:
    """Mismo numero, distinto plc_tag → ``renombrar``."""
    state = _build_state_with_v([
        (1, "V_NEW"),  # distinto a TIA (que tiene V_OLD)
    ])
    cm = _mock_config_manager()
    gw = _mock_gateway_with_export(tmp_path, {
        "2000_Disp_V": [("1", "V_OLD")],
    })
    uc = SyncDispositivosInstancesUseCase(
        gateway=gw, config_manager=cm, state=state,
        build_cache_dir=tmp_path / "cache",
    )
    prev = await uc.generar_prevision("PLC1")

    row = next(r for r in prev["todos"] if r["type"] == "v")
    assert row["status"] == "renombrar"
    assert row["actual"] == "V_OLD"
    assert row["nuevo"] == "V_NEW"


@pytest.mark.asyncio
async def test_todos_marks_eliminar(tmp_path: Path) -> None:
    """En TIA pero no en AppState → ``eliminar`` con nuevo=None."""
    state = _build_state_with_v([
        (1, "V_001"),  # existe en ambos
        # value 2 está en TIA pero NO en AppState → eliminar
    ])
    cm = _mock_config_manager()
    gw = _mock_gateway_with_export(tmp_path, {
        "2000_Disp_V": [
            ("1", "V_001"),
            ("2", "V_002"),
        ],
    })
    uc = SyncDispositivosInstancesUseCase(
        gateway=gw, config_manager=cm, state=state,
        build_cache_dir=tmp_path / "cache",
    )
    prev = await uc.generar_prevision("PLC1")

    rows_v = sorted(
        (r for r in prev["todos"] if r["type"] == "v"),
        key=lambda r: r["numero"],
    )
    assert len(rows_v) == 2
    assert rows_v[0]["status"] == "sin_cambios"
    assert rows_v[0]["numero"] == 1
    assert rows_v[1]["status"] == "eliminar"
    assert rows_v[1]["numero"] == 2
    assert rows_v[1]["actual"] == "V_002"
    assert rows_v[1]["nuevo"] is None


@pytest.mark.asyncio
async def test_todos_marks_agregar(tmp_path: Path) -> None:
    """En AppState pero no en TIA → ``agregar`` con actual=None."""
    state = _build_state_with_v([
        (1, "V_001"),  # existe en ambos
        (2, "V_NEW"),  # NUEVO: no está en TIA
    ])
    cm = _mock_config_manager()
    gw = _mock_gateway_with_export(tmp_path, {
        "2000_Disp_V": [("1", "V_001")],
    })
    uc = SyncDispositivosInstancesUseCase(
        gateway=gw, config_manager=cm, state=state,
        build_cache_dir=tmp_path / "cache",
    )
    prev = await uc.generar_prevision("PLC1")

    rows_v = sorted(
        (r for r in prev["todos"] if r["type"] == "v"),
        key=lambda r: r["numero"],
    )
    assert len(rows_v) == 2
    assert rows_v[0]["status"] == "sin_cambios"
    assert rows_v[0]["numero"] == 1
    assert rows_v[1]["status"] == "agregar"
    assert rows_v[1]["numero"] == 2
    assert rows_v[1]["actual"] is None
    assert rows_v[1]["nuevo"] == "V_NEW"


@pytest.mark.asyncio
async def test_todos_contains_all_states_in_one_call(tmp_path: Path) -> None:
    """Una sola previsualización contiene los 4 estados a la vez."""
    state = _build_state_with_v([
        (1, "V_A"),       # sin cambios
        (2, "V_NEW_2"),   # renombrar (TIA: V_B)
        (3, "V_NEW_3"),   # agregar (TIA: no existe)
        # 4 está en TIA → eliminar (no en AppState)
    ])
    cm = _mock_config_manager()
    gw = _mock_gateway_with_export(tmp_path, {
        "2000_Disp_V": [
            ("1", "V_A"),
            ("2", "V_B"),
            ("4", "V_D"),
        ],
    })
    uc = SyncDispositivosInstancesUseCase(
        gateway=gw, config_manager=cm, state=state,
        build_cache_dir=tmp_path / "cache",
    )
    prev = await uc.generar_prevision("PLC1")

    rows_v = sorted(
        (r for r in prev["todos"] if r["type"] == "v"),
        key=lambda r: r["numero"],
    )
    assert [r["numero"] for r in rows_v] == [1, 2, 3, 4]
    assert [r["status"] for r in rows_v] == [
        "sin_cambios", "renombrar", "agregar", "eliminar",
    ]


@pytest.mark.asyncio
async def test_summary_counters_match_todos(tmp_path: Path) -> None:
    """Los contadores de ``summary`` cuadran con las listas legacy y con ``todos``."""
    state = _build_state_with_v([
        (1, "V_NEW"),  # renombrar
        (2, "V_002"),  # sin cambios
    ])
    cm = _mock_config_manager()
    gw = _mock_gateway_with_export(tmp_path, {
        "2000_Disp_V": [
            ("1", "V_OLD"),
            ("2", "V_002"),
            ("3", "V_TO_DELETE"),  # eliminar
        ],
    })
    uc = SyncDispositivosInstancesUseCase(
        gateway=gw, config_manager=cm, state=state,
        build_cache_dir=tmp_path / "cache",
    )
    prev = await uc.generar_prevision("PLC1")

    assert prev["summary"]["agregados"] == 0
    assert prev["summary"]["renombrados"] == 1
    assert prev["summary"]["eliminados"] == 1
    assert prev["summary"]["sin_cambios"] == 1
    assert prev["summary"]["total"] == 3

    # Back-compat con las listas legacy.
    assert len(prev["agregados"]) == 0
    assert len(prev["renombrados"]) == 1
    assert len(prev["eliminados"]) == 1


@pytest.mark.asyncio
async def test_todos_sorted_by_numero_ascending(tmp_path: Path) -> None:
    """El orden de ``todos`` es por ``type`` y luego ``numero`` ascendente."""
    state = _build_state_with_v([
        (3, "V_003"),
        (1, "V_001"),
        (2, "V_002"),
    ])
    cm = _mock_config_manager()
    gw = _mock_gateway_with_export(tmp_path, {
        "2000_Disp_V": [],  # PLC vacío
    })
    uc = SyncDispositivosInstancesUseCase(
        gateway=gw, config_manager=cm, state=state,
        build_cache_dir=tmp_path / "cache",
    )
    prev = await uc.generar_prevision("PLC1")

    rows_v = [r for r in prev["todos"] if r["type"] == "v"]
    assert [r["numero"] for r in rows_v] == [1, 2, 3]
