"""Tests del método del gateway ``update_disp_instance_comments_batch``.

Mockeamos ``execute_transactional_batch`` y ``clear_cache`` del gateway
para no lanzar el subprocess real (requiere TIA + siemens_tia_scripting).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from infrastructure.gateway import TIAProcessGateway


@pytest.fixture
def gateway() -> TIAProcessGateway:
    """Gateway fresco, con execute_transactional_batch y clear_cache mockeados."""
    g = TIAProcessGateway()
    g.execute_transactional_batch = AsyncMock(
        return_value={
            "success": True,
            "operations_executed": 6,
            "details": [],
        }
    )
    g.clear_cache = MagicMock()
    return g


def test_raises_si_slot_maps_vacio(gateway: TIAProcessGateway) -> None:
    """slot_maps vacío → ValueError antes de tocar TIA."""
    import asyncio
    with pytest.raises(ValueError, match="está vacío"):
        asyncio.run(
            gateway.update_disp_instance_comments_batch(
                plc_name="PLC_X",
                dispositivos_slot_maps={},
                target_folder="2000_Dispositivos",
                db_names={},
                db_array_names={},
            )
        )


def test_raises_si_slot_0_no_es_no_usar(gateway: TIAProcessGateway) -> None:
    """slot_map de un tipo sin 'NO USAR' en 0 → ValueError."""
    import asyncio
    with pytest.raises(ValueError, match="NO USAR"):
        asyncio.run(
            gateway.update_disp_instance_comments_batch(
                plc_name="PLC_X",
                dispositivos_slot_maps={
                    "ed": {0: "Comentario incorrecto", 1: "Bomba 1"},
                },
                target_folder="2000_Dispositivos",
                db_names={"ed": "DB2000_ED"},
                db_array_names={"ed": "ED"},
            )
        )


def test_construye_6_operaciones_con_args_completos(
    gateway: TIAProcessGateway,
) -> None:
    """slot_maps con 6 tipos → 6 operaciones con db_name / db_array_name / target_folder."""
    import asyncio

    slot_maps = {
        "ed":   {0: "NO USAR", 1: "X"},
        "ea":   {0: "NO USAR", 1: "Y"},
        "sa":   {0: "NO USAR"},
        "v":    {0: "NO USAR"},
        "m":    {0: "NO USAR"},
        "m_vf": {0: "NO USAR"},
    }
    db_names = {
        "ed":   "DB2000_ED",
        "ea":   "DB2001_EA",
        "sa":   "DB2006_SA",
        "v":    "DB2010_V",
        "m":    "DB2015_M",
        "m_vf": "DB2016_M_VF",
    }
    db_array_names = {
        "ed":   "ED",
        "ea":   "EA",
        "sa":   "SA",
        "v":    "V",
        "m":    "M",
        "m_vf": "M_VF",
    }
    asyncio.run(
        gateway.update_disp_instance_comments_batch(
            plc_name="PLC_X",
            dispositivos_slot_maps=slot_maps,
            target_folder="2000_Dispositivos",
            db_names=db_names,
            db_array_names=db_array_names,
        )
    )

    call_args = gateway.execute_transactional_batch.call_args
    ops = call_args.args[0]
    assert len(ops) == 6
    # Cada op debe tener db_name y db_array_name correctamente poblados.
    for op in ops:
        cmd = op["command"]
        assert cmd.startswith("update_disp_comments_db_")
        hw = cmd.removeprefix("update_disp_comments_db_")
        assert op["args"]["db_name"] == db_names[hw]
        assert op["args"]["db_array_name"] == db_array_names[hw]
        assert op["args"]["target_folder"] == "2000_Dispositivos"
        assert op["args"]["plc_name"] == "PLC_X"
        assert op["args"]["slot_map"]["0"] == "NO USAR"


def test_target_folder_no_hardcodeado(gateway: TIAProcessGateway) -> None:
    """target_folder viene del caller, no se hardcodea en el gateway."""
    import asyncio

    asyncio.run(
        gateway.update_disp_instance_comments_batch(
            plc_name="PLC_X",
            dispositivos_slot_maps={"ed": {0: "NO USAR", 1: "X"}},
            target_folder="OTRA_CARPETA",
            db_names={"ed": "DB2000_ED"},
            db_array_names={"ed": "ED"},
        )
    )

    ops = gateway.execute_transactional_batch.call_args.args[0]
    for op in ops:
        assert op["args"]["target_folder"] == "OTRA_CARPETA"


def test_llama_clear_cache_en_exito(gateway: TIAProcessGateway) -> None:
    """Tras ejecutar el batch OK, clear_cache se invoca."""
    import asyncio

    asyncio.run(
        gateway.update_disp_instance_comments_batch(
            plc_name="PLC_X",
            dispositivos_slot_maps={"ed": {0: "NO USAR", 1: "X"}},
            target_folder="2000_Dispositivos",
            db_names={"ed": "DB2000_ED"},
            db_array_names={"ed": "ED"},
        )
    )
    gateway.clear_cache.assert_called_once()


def test_work_dir_usa_build_cache(
    gateway: TIAProcessGateway, tmp_path: Path,
) -> None:
    """El work_dir es ``<build_cache>/comments/`` (mismo patrón que ``base/tags/``)."""
    import asyncio
    from pathlib import Path

    asyncio.run(
        gateway.update_disp_instance_comments_batch(
            plc_name="PLC_X",
            dispositivos_slot_maps={"ed": {0: "NO USAR", 1: "X"}},
            target_folder="2000_Dispositivos",
            db_names={"ed": "DB2000_ED"},
            db_array_names={"ed": "ED"},
            build_cache_dir=tmp_path / ".build_cache",
        )
    )
    # El directorio existe tras la llamada (se preserva entre llamadas).
    expected = tmp_path / ".build_cache" / "comments"
    assert expected.exists()


def test_work_dir_se_conserva_entre_ejecuciones(
    gateway: TIAProcessGateway, tmp_path: Path,
) -> None:
    """El work_dir persiste entre llamadas (no se borra tras la operación)."""
    import asyncio

    cache = tmp_path / ".build_cache"
    for _ in range(2):
        asyncio.run(
            gateway.update_disp_instance_comments_batch(
                plc_name="PLC_X",
                dispositivos_slot_maps={"ed": {0: "NO USAR", 1: "X"}},
                target_folder="2000_Dispositivos",
                db_names={"ed": "DB2000_ED"},
                db_array_names={"ed": "ED"},
                build_cache_dir=cache,
            )
        )
    # El directorio sigue existiendo tras 2 ejecuciones.
    assert (cache / "comments").exists()
