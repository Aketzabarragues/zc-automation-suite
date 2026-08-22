"""Tests de regresión: ``generar_prevision`` incluye N_MAX en la respuesta.

El método ``SyncDispositivosInstancesUseCase.generar_prevision`` ahora
incluye, además de la lista unificada ``todos`` de dispositivos, un
bloque ``nmax`` con la diff de las PlcUserConstant de la tabla
``000_Config_Dispositivos``.

Estructura del bloque ``nmax``:
  {
    "current":  {"10": "N_MAX_DISP_ED", "12": "N_MAX_DISP_V", ...},
    "desired":  {"N_MAX_DISP_ED": 15, "N_MAX_DISP_EA": 20, ...},
    "todos":    [
      {"name": "N_MAX_DISP_ED", "actual": 10, "nuevo": 15, "status": "actualizar"},
      ...
    ],
    "summary":  {"actualizar": 1, "sin_cambios": 3, ...}
  }

El ``status`` puede ser:
  - "actualizar"   : mismo nombre, valor distinto
  - "sin_cambios"  : mismo nombre, mismo valor
  - "eliminar"     : en TIA, no en AppState
  - "nuevo"        : en AppState, no en TIA
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from application.state import AppState
from application.use_cases.sync_dispositivos_instances import (
    SyncDispositivosInstancesUseCase,
)
from core.alimentacion.models.dispositivos import DimensionesDispositivos
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


def _build_state_with_dimensiones(
    num_ed: int = 0, num_ea: int = 0, num_sa: int = 0,
    num_v: int = 0, num_m: int = 0, num_m_vf: int = 0,
) -> AppState:
    """Crea un AppState con dimensiones específicas."""
    state = AppState()
    state.dimensiones = DimensionesDispositivos(
        num_disp_ed=num_ed,
        num_disp_ea=num_ea,
        num_disp_sa=num_sa,
        num_disp_v=num_v,
        num_disp_m=num_m,
        num_disp_m_vf=num_m_vf,
    )
    return state


# Alias deprecado (compat con tests iniciales).
_build_state_with_dimensiones_2 = _build_state_with_dimensiones


def _mock_config_manager() -> ConfigManager:
    """Crea un ConfigManager real apuntando al config.json del repo."""
    return ConfigManager("infrastructure/config.json")


def _mock_gateway_with_nmax(
    tmp_path: Path, tia_nmax: dict[str, list[tuple[str, str]]],
) -> MagicMock:
    """Mockea el gateway para que ``export_plc_tags_xml`` escriba las
    tablas TIA (incluida N_MAX) en la jerarquía esperada."""
    gw = MagicMock()

    async def fake_export(plc_name, target_dir):
        base = Path(target_dir)
        base.mkdir(parents=True, exist_ok=True)
        nmax_folder = base / "000_Sistema"
        nmax_folder.mkdir(parents=True, exist_ok=True)
        dev_folder = base / "2000_Dispositivos"
        dev_folder.mkdir(parents=True, exist_ok=True)
        for table_name, constants in tia_nmax.items():
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
# Tests
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_nmax_block_in_response(tmp_path: Path) -> None:
    """``generar_prevision`` incluye el bloque ``nmax`` en la respuesta."""
    state = _build_state_with_dimensiones_2(num_ed=15, num_v=20)
    cm = _mock_config_manager()
    # TIA: N_MAX_DISP_ED=10, N_MAX_DISP_V=12.
    gw = _mock_gateway_with_nmax(tmp_path, {
        "000_Config_Dispositivos": [
            ("10", "N_MAX_DISP_ED"),
            ("12", "N_MAX_DISP_V"),
        ],
    })
    uc = SyncDispositivosInstancesUseCase(
        gateway=gw, config_manager=cm, state=state,
        build_cache_dir=tmp_path / "cache",
    )
    prev = await uc.generar_prevision("PLC1")
    assert "nmax" in prev
    assert "todos" in prev["nmax"]
    assert "current" in prev["nmax"]
    assert "desired" in prev["nmax"]
    assert "summary" in prev["nmax"]


@pytest.mark.asyncio
async def test_nmax_diff_marks_actualizar(tmp_path: Path) -> None:
    """Mismo nombre, valor distinto → ``actualizar``."""
    state = _build_state_with_dimensiones_2(num_ed=15, num_v=20)
    cm = _mock_config_manager()
    gw = _mock_gateway_with_nmax(tmp_path, {
        "000_Config_Dispositivos": [
            ("10", "N_MAX_DISP_ED"),  # TIA: value=10, name=N_MAX_DISP_ED
            ("12", "N_MAX_DISP_V"),   # TIA: value=12, name=N_MAX_DISP_V
        ],
    })
    uc = SyncDispositivosInstancesUseCase(
        gateway=gw, config_manager=cm, state=state,
        build_cache_dir=tmp_path / "cache",
    )
    prev = await uc.generar_prevision("PLC1")

    ed_row = next(r for r in prev["nmax"]["todos"] if r["name"] == "N_MAX_DISP_ED")
    v_row = next(r for r in prev["nmax"]["todos"] if r["name"] == "N_MAX_DISP_V")

    assert ed_row["status"] == "actualizar"
    assert ed_row["actual"] == 10
    assert ed_row["nuevo"] == 15
    assert v_row["status"] == "actualizar"
    assert v_row["actual"] == 12
    assert v_row["nuevo"] == 20


@pytest.mark.asyncio
async def test_nmax_diff_marks_sin_cambios(tmp_path: Path) -> None:
    """Mismo nombre, mismo valor → ``sin_cambios``."""
    state = _build_state_with_dimensiones_2(num_ed=10, num_v=12)
    cm = _mock_config_manager()
    gw = _mock_gateway_with_nmax(tmp_path, {
        "000_Config_Dispositivos": [
            ("10", "N_MAX_DISP_ED"),
            ("12", "N_MAX_DISP_V"),
        ],
    })
    uc = SyncDispositivosInstancesUseCase(
        gateway=gw, config_manager=cm, state=state,
        build_cache_dir=tmp_path / "cache",
    )
    prev = await uc.generar_prevision("PLC1")

    ed_row = next(r for r in prev["nmax"]["todos"] if r["name"] == "N_MAX_DISP_ED")
    assert ed_row["status"] == "sin_cambios"
    assert ed_row["actual"] == 10
    assert ed_row["nuevo"] == 10


@pytest.mark.asyncio
async def test_nmax_diff_marks_actualizar_y_sin_cambios(tmp_path: Path) -> None:
    """Combinación actualizar + sin_cambios.

    Las N_MAX son PlcUserConstant que **siempre existen** en TIA,
    así que los únicos estados posibles son ``actualizar`` (cambio
    de valor) y ``sin_cambios`` (mismo valor). No hay "nuevo" ni
    "eliminar" en este flujo.
    """
    state = _build_state_with_dimensiones_2(
        num_ed=15,    # actualizar (TIA 10 → 15)
        num_ea=99,    # actualizar (no en TIA, Excel=99)
        num_v=12,     # sin cambios (TIA 12 = 12)
        # sa no configurado en AppState (num_disp_sa=0) →
        # TIA 5 → AppState 0 = actualizar.
    )
    cm = _mock_config_manager()
    gw = _mock_gateway_with_nmax(tmp_path, {
        "000_Config_Dispositivos": [
            ("10", "N_MAX_DISP_ED"),   # en TIA y AppState
            ("5",  "N_MAX_DISP_SA"),   # en TIA, AppState=0
            ("12", "N_MAX_DISP_V"),    # en TIA y AppState (mismo)
        ],
    })
    uc = SyncDispositivosInstancesUseCase(
        gateway=gw, config_manager=cm, state=state,
        build_cache_dir=tmp_path / "cache",
    )
    prev = await uc.generar_prevision("PLC1")

    rows_by_name = {r["name"]: r for r in prev["nmax"]["todos"]}

    # ED: 10 → 15 = actualizar.
    assert rows_by_name["N_MAX_DISP_ED"]["status"] == "actualizar"
    assert rows_by_name["N_MAX_DISP_ED"]["actual"] == 10
    assert rows_by_name["N_MAX_DISP_ED"]["nuevo"] == 15

    # EA: no en TIA, Excel=99 → actualizar (cur_val=None != 99).
    assert rows_by_name["N_MAX_DISP_EA"]["status"] == "actualizar"
    assert rows_by_name["N_MAX_DISP_EA"]["actual"] is None
    assert rows_by_name["N_MAX_DISP_EA"]["nuevo"] == 99

    # SA: TIA 5, AppState 0 → actualizar (valor cambia, no se elimina).
    assert rows_by_name["N_MAX_DISP_SA"]["status"] == "actualizar"
    assert rows_by_name["N_MAX_DISP_SA"]["actual"] == 5
    assert rows_by_name["N_MAX_DISP_SA"]["nuevo"] == 0

    # V: TIA 12, AppState 12 → sin_cambios.
    assert rows_by_name["N_MAX_DISP_V"]["status"] == "sin_cambios"
    assert rows_by_name["N_MAX_DISP_V"]["actual"] == 12
    assert rows_by_name["N_MAX_DISP_V"]["nuevo"] == 12

    # M y M_VF también aparecen: TIA no las tiene, AppState=0, así
    # que current=None != 0 = actualizar.
    assert rows_by_name["N_MAX_DISP_M"]["status"] == "actualizar"
    assert rows_by_name["N_MAX_DISP_M"]["actual"] is None
    assert rows_by_name["N_MAX_DISP_M"]["nuevo"] == 0
    assert rows_by_name["N_MAX_DISP_M_VF"]["status"] == "actualizar"
    assert rows_by_name["N_MAX_DISP_M_VF"]["actual"] is None
    assert rows_by_name["N_MAX_DISP_M_VF"]["nuevo"] == 0

    # Summary: solo 2 contadores (actualizar, sin_cambios). NO hay
    # "nuevo" ni "eliminar" en el summary de N_MAX.
    s = prev["nmax"]["summary"]
    assert s["actualizar"] == 5   # ED, EA, SA, M, M_VF
    assert s["sin_cambios"] == 1  # V
    assert s["total"] == 6        # 6 N_MAX (ED, EA, SA, V, M, M_VF)
    assert "nuevo" not in s       # N_MAX nunca es "nuevo"
    assert "eliminar" not in s    # N_MAX nunca es "eliminar"


@pytest.mark.asyncio
async def test_nmax_returns_empty_when_xml_missing(tmp_path: Path) -> None:
    """Si el XML N_MAX no está, retorna bloques vacíos (no aborta)."""
    state = _build_state_with_dimensiones_2(num_ed=15)
    cm = _mock_config_manager()
    gw = _mock_gateway_with_nmax(tmp_path, {})  # sin tablas
    uc = SyncDispositivosInstancesUseCase(
        gateway=gw, config_manager=cm, state=state,
        build_cache_dir=tmp_path / "cache",
    )
    prev = await uc.generar_prevision("PLC1")

    assert "nmax" in prev
    # current vacío, desired lleno (desde AppState).
    assert prev["nmax"]["current"] == {}
    assert prev["nmax"]["desired"]["N_MAX_DISP_ED"] == 15
    # Todos los N_MAX aparecen como "actualizar" (current=None,
    # desired=15 para ED o 0 para el resto, siempre distinto).
    for row in prev["nmax"]["todos"]:
        assert row["status"] == "actualizar"
        assert row["actual"] is None


@pytest.mark.asyncio
async def test_nmax_ordered_by_name_natural(tmp_path: Path) -> None:
    """El orden de los N_MAX sigue el orden natural ED, EA, SA, V, M, M_VF."""
    state = _build_state_with_dimensiones_2(
        num_ed=1, num_ea=2, num_sa=3, num_v=4, num_m=5, num_m_vf=6,
    )
    cm = _mock_config_manager()
    gw = _mock_gateway_with_nmax(tmp_path, {
        "000_Config_Dispositivos": [
            ("1", "N_MAX_DISP_ED"),
            ("2", "N_MAX_DISP_EA"),
            ("3", "N_MAX_DISP_SA"),
            ("4", "N_MAX_DISP_V"),
            ("5", "N_MAX_DISP_M"),
            ("6", "N_MAX_DISP_M_VF"),
        ],
    })
    uc = SyncDispositivosInstancesUseCase(
        gateway=gw, config_manager=cm, state=state,
        build_cache_dir=tmp_path / "cache",
    )
    prev = await uc.generar_prevision("PLC1")

    names = [r["name"] for r in prev["nmax"]["todos"]]
    # Orden natural esperado (orden de inserción del dict, no
    # lexicográfico — preserva el orden ED, EA, SA, V, M, M_VF
    # que el operador espera ver, igual que el Inspector).
    assert names == [
        "N_MAX_DISP_ED",
        "N_MAX_DISP_EA",
        "N_MAX_DISP_SA",
        "N_MAX_DISP_V",
        "N_MAX_DISP_M",
        "N_MAX_DISP_M_VF",
    ]


@pytest.mark.asyncio
async def test_nmax_actualizar_when_dimensiones_is_zero(tmp_path: Path) -> None:
    """Si AppState.dimensiones está a 0, TIA tiene X → status ``actualizar``."""
    state = AppState()  # dimensiones = todo a 0
    cm = _mock_config_manager()
    gw = _mock_gateway_with_nmax(tmp_path, {
        "000_Config_Dispositivos": [
            ("10", "N_MAX_DISP_ED"),
        ],
    })
    uc = SyncDispositivosInstancesUseCase(
        gateway=gw, config_manager=cm, state=state,
        build_cache_dir=tmp_path / "cache",
    )
    prev = await uc.generar_prevision("PLC1")
    ed_row = next(r for r in prev["nmax"]["todos"] if r["name"] == "N_MAX_DISP_ED")
    assert ed_row["status"] == "actualizar"
    assert ed_row["actual"] == 10
    assert ed_row["nuevo"] == 0
