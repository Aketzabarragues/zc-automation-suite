"""Tests del método del gateway ``update_disp_instance_comments_batch``.

**Sept-2026:** el método ya NO usa ``execute_transactional_batch``. Hace
6 invocaciones separadas a ``_dispatch_worker`` (1 por hw_type) con
``update_disp_comments_db_apply_<hw>``. Mockeamos ``_dispatch_worker`` y
``clear_cache`` del gateway para no lanzar el subprocess real (requiere
TIA + siemens_tia_scripting).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.infrastructure.gateway import TIAProcessGateway


@pytest.fixture
def gateway() -> TIAProcessGateway:
    """Gateway fresco, con ``_dispatch_worker`` y ``clear_cache`` mockeados."""
    g = TIAProcessGateway()
    g._dispatch_worker = AsyncMock(
        return_value={
            "hw_type": "ed",
            "db_name": "DB2000_ED",
            "modified": True,
            "disp_comment_result": {
                "reused": {},
                "inserted": {},
                "no_usar_mlc": "MLC_xxx",
                "total_mlcs_in_res": 1,
            },
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


def test_dispatcha_6_operaciones_separadas(
    gateway: TIAProcessGateway,
) -> None:
    """slot_maps con 6 tipos → 6 invocaciones separadas a ``_dispatch_worker``
    con ``update_disp_comments_db_apply_<hw>`` (1 dispatch por hw_type).

    Sept-2026: el método ya NO usa ``execute_transactional_batch``; cada
    handler abre/cierra su propia tx TIA.
    """
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
    result = asyncio.run(
        gateway.update_disp_instance_comments_batch(
            plc_name="PLC_X",
            dispositivos_slot_maps=slot_maps,
            target_folder="2000_Dispositivos",
            db_names=db_names,
            db_array_names=db_array_names,
        )
    )

    # 6 invocaciones separadas, 1 por hw_type.
    assert gateway._dispatch_worker.await_count == 6
    # Cada invocación es un comando distinto ``update_disp_comments_db_apply_<hw>``.
    commands = [c.args[0] for c in gateway._dispatch_worker.await_args_list]
    assert set(commands) == {
        "update_disp_comments_db_apply_ed",
        "update_disp_comments_db_apply_ea",
        "update_disp_comments_db_apply_sa",
        "update_disp_comments_db_apply_v",
        "update_disp_comments_db_apply_m",
        "update_disp_comments_db_apply_m_vf",
    }
    # Cada op debe tener db_name, db_array_name, target_folder, plc_name, slot_map correctos.
    for call in gateway._dispatch_worker.await_args_list:
        cmd = call.args[0]
        op_args = call.args[1]
        hw = cmd.removeprefix("update_disp_comments_db_apply_")
        assert op_args["db_name"] == db_names[hw]
        assert op_args["db_array_name"] == db_array_names[hw]
        assert op_args["target_folder"] == "2000_Dispositivos"
        assert op_args["plc_name"] == "PLC_X"
        assert op_args["slot_map"]["0"] == "NO USAR"
    # El return tiene operations_executed == 6.
    assert result["operations_executed"] == 6
    assert result["success"] is True


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

    for call in gateway._dispatch_worker.await_args_list:
        op_args = call.args[1]
        assert op_args["target_folder"] == "OTRA_CARPETA"


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
    """El work_dir es ``<build_cache>/alimentacion/dispositivos/exports/``.

    Mismo path canónico que ``DispSyncInstancesUseCase`` (que escribe
    en ``exports/`` para su flujo de N_MAX + devices). Unificar el
    subdir permite que ``ContextCache.clean()`` aplique a ambos
    flujos de dispositivos desde un único punto.
    """
    import asyncio

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
    expected = tmp_path / ".build_cache" / "alimentacion" / "dispositivos" / "exports"
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
    assert (cache / "alimentacion" / "dispositivos" / "exports").exists()


def test_work_dir_parametrizable_por_area_y_contexto(
    gateway: TIAProcessGateway, tmp_path: Path,
) -> None:
    """Los params ``area_id``/``contexto``/``subestado`` permiten reutilizar
    el método para un 2º área sin tocar el gateway (que vive en ``core/``
    y no debe saber de áreas).

    Por defecto apuntan a ``alimentacion/dispositivos/exports/``. Si se
    pasan otros valores, el workdir se construye desde esos params
    respetando la jerarquía ``<root>/<area_id>/<contexto>/<subestado>/``.
    """
    import asyncio

    # Caso 1: defaults -> alimentacion/dispositivos/exports/.
    asyncio.run(
        gateway.update_disp_instance_comments_batch(
            plc_name="PLC_X",
            dispositivos_slot_maps={"ed": {0: "NO USAR", 1: "X"}},
            target_folder="2000_Dispositivos",
            db_names={"ed": "DB2000_ED"},
            db_array_names={"ed": "ED"},
            build_cache_dir=tmp_path,
        )
    )
    assert (tmp_path / "alimentacion" / "dispositivos" / "exports").exists()

    # Caso 2: 2º área hipotética con contexto propio. El gateway
    # construye el path sin saber qué es "trazabilidad" — solo aplica
    # la jerarquía parametrizada.
    asyncio.run(
        gateway.update_disp_instance_comments_batch(
            plc_name="PLC_Y",
            dispositivos_slot_maps={"ed": {0: "NO USAR", 1: "Y"}},
            target_folder="9000_Lotes",
            db_names={"ed": "DB9000_LOTES"},
            db_array_names={"ed": "LOTES"},
            area_id="trazabilidad",
            contexto="lotes",
            subestado="exports",
            build_cache_dir=tmp_path,
        )
    )
    assert (tmp_path / "trazabilidad" / "lotes" / "exports").exists()


def test_subestado_acepta_subpath_typed_9_carpetas(
    gateway: TIAProcessGateway, tmp_path: Path,
) -> None:
    """El param ``subestado`` acepta subpaths typed (ej. ``exports/bloques``).

    Convención de 9 carpetas (plan 2026-09-08): los ``.s7dcl``/``.s7res``
    de los 6 DBs de dispositivos viven en la subcarpeta
    ``exports/bloques/``, no en la raíz ``exports/``. El use case
    ``DispSyncInstancesUseCase.ejecutar_transaccion`` (commit 4) pasa
    ``subestado="exports/bloques"`` explícitamente al gateway, y el
    work_dir se construye respetando ese subpath (sin asumir
    ``exports/`` plano). El test verifica que el gateway NO
    hardcodea el subdir: cualquier valor de subestado se concatena
    tal cual al path base.
    """
    import asyncio

    asyncio.run(
        gateway.update_disp_instance_comments_batch(
            plc_name="PLC_X",
            dispositivos_slot_maps={"ed": {0: "NO USAR", 1: "X"}},
            target_folder="2000_Dispositivos",
            db_names={"ed": "DB2000_ED"},
            db_array_names={"ed": "ED"},
            area_id="alimentacion",
            contexto="dispositivos",
            subestado="exports/bloques",
            build_cache_dir=tmp_path,
        )
    )
    # El work_dir se construye como
    # ``<root>/alimentacion/dispositivos/exports/bloques``.
    assert (
        tmp_path / "alimentacion" / "dispositivos" / "exports" / "bloques"
    ).exists()
